"""R-4a: a run writes a cassette (ADR-032 (7), R-4a amendment).

Claims under test:

* **the hash** — ``request_sha256`` is a pure function of a request's JSON value (dict
  order does not matter, one changed character does), with a pinned golden vector;
* **the exchanges** — ``native.wake`` hashes each request *before* the mind sees it and
  records one ``Exchange(seq, request_sha256, usage)`` per model turn it asked for:
  usage is ``None`` exactly when the reply was not accepted (a crash, ``bad_reply``).
  A turn never asked (HALT first) is never recorded; a refused wake records none;
* **the file** — ``dumps`` is deterministic and versioned; every minted key is gone from
  keys, values and JSON nested in strings, and counted; ``write`` is exclusive, mode 0600,
  never is a symlink itself (a symlinked directory is followed), and leaves no file behind on a
  refusal or a failed write;
* **the ignore rule** — cassettes and run directories are gitignored (B-000i).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from app.registry.security import generate_api_key
from runtime import cassette, native
from runtime.cassette import CASSETTE_VERSION, HASH_FORMAT, CassetteError, request_sha256
from runtime.native import wake
from runtime.providers import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from tests.cassette_parts import PARTS
from tests.test_runtime_native import (  # noqa: F401 - fixtures
    _calls,
    _spec,
    anyio_backend,
    fund_client,
    gov,
    scripts,
)

REPO = Path(__file__).resolve().parent.parent


# --- the hash --------------------------------------------------------------------------

def _request(**more) -> CompletionRequest:
    base = dict(
        messages=[Message(role="system", content="Run the desk."),
                  Message(role="user", content='{"me": {"id": 1}}')],
        tools=[ToolSpec(name="get_clock", description="the clock",
                        input_schema={"type": "object", "properties": {"a": 1, "b": 2}})],
        model=None)
    return CompletionRequest(**(base | more))


#: The canonical JSON of ``_request()`` and its digest. A change to either is a format
#: change: bump ``HASH_FORMAT`` and ``CASSETTE_VERSION`` together with it. (M-002 bumped
#: ``CASSETTE_VERSION`` to 2 for the document's shape; the request hash did not change.)
GOLDEN_JSON = (
    '{"messages":[{"content":"Run the desk.","is_error":false,"role":"system",'
    '"tool_call_id":null,"tool_calls":[]},{"content":"{\\"me\\": {\\"id\\": 1}}",'
    '"is_error":false,"role":"user","tool_call_id":null,"tool_calls":[]}],"model":null,'
    '"tools":[{"description":"the clock","input_schema":{"properties":{"a":1,"b":2},'
    '"type":"object"},"name":"get_clock"}]}')
GOLDEN_SHA = "7f9090e0ed9ab8853d500967f92c221f8a037335f2566c5c15371dab412ab46b"


def test_request_sha256_golden_vector() -> None:
    import hashlib
    assert HASH_FORMAT == "sha256/json-sorted-compact-ascii/1" and CASSETTE_VERSION == 2
    assert hashlib.sha256(GOLDEN_JSON.encode()).hexdigest() == GOLDEN_SHA
    assert request_sha256(_request()) == GOLDEN_SHA


def test_request_sha256_ignores_construction_order_and_sees_one_character() -> None:
    reordered = _request(tools=[ToolSpec(
        name="get_clock", description="the clock",
        input_schema={"properties": {"b": 2, "a": 1}, "type": "object"})])
    assert request_sha256(reordered) == request_sha256(_request())
    changed = _request(messages=[Message(role="system", content="Run the desk!"),
                                 *_request().messages[1:]])
    assert request_sha256(changed) != request_sha256(_request())


def test_non_ascii_hashes_as_ascii() -> None:
    """``ensure_ascii``: the digest does not depend on how a file was encoded."""
    r = _request(messages=[Message(role="user", content="café ☃")])
    assert request_sha256(r) == request_sha256(r.model_copy(deep=True))


# --- the exchanges ---------------------------------------------------------------------

def _prefix_requests(rec, tools: list[ToolSpec], model=None) -> list[CompletionRequest]:
    """Rebuild each request from the transcript: everything before the i-th assistant turn."""
    out = []
    for i, m in enumerate(rec.transcript):
        if m.role == "assistant":
            out.append(CompletionRequest(messages=list(rec.transcript[:i]), tools=tools,
                                         model=model))
    return out


@pytest.mark.anyio
async def test_exchange_per_complete_call(fund_client, desk, scripts) -> None:
    _, _, pm_key = desk
    client = fund_client(pm_key)
    scripts(three=_calls("get_clock", turns=2))
    rec = await wake(_spec(script="three"), client, workflow_input={})
    assert rec.ended == "done"
    assert [e.seq for e in rec.exchanges] == [0, 1, 2]
    assert all(e.usage == Usage() for e in rec.exchanges)
    assert len(rec.exchanges) == sum(m.role == "assistant" for m in rec.transcript)
    # The request is recoverable from the transcript, and the digest is of exactly that.
    requests = _prefix_requests(rec, await native.published_tools(client))
    assert [request_sha256(r) for r in requests] == [e.request_sha256 for e in rec.exchanges]


@pytest.mark.anyio
async def test_every_v2_wake_carries_model_and_tools_sha256(fund_client, desk, scripts) -> None:
    """M-002: a wake that asked a turn records the model it asked and its tools' digest."""
    _, _, pm_key = desk
    client = fund_client(pm_key)
    scripts(three=_calls("get_clock", turns=1))
    rec = await wake(_spec(script="three"), client, workflow_input={})
    published = await native.published_tools(client)
    # A scripted mind asks no model (the registry refuses scripted + a model): ``None`` is the
    # recorded fact; a model-bearing mind records ``spec.model`` here.
    assert (rec.model, rec.tools_sha256) == (None, cassette.tools_sha256(published))
    narrowed = await wake(_spec(script="three", tools=("get_clock",)), client, workflow_input={})
    assert narrowed.model is None
    assert narrowed.tools_sha256 == cassette.tools_sha256(
        [t for t in published if t.name == "get_clock"]) != rec.tools_sha256
    # A wake refused before its tools were listed has neither.
    refused = await wake(_spec(wake_policy="never"), client, workflow_input={})
    assert (refused.model, refused.tools_sha256) == (None, None)


@pytest.mark.anyio
async def test_tools_sha256_is_of_the_tools_in_the_request(fund_client, desk, scripts) -> None:
    _, _, pm_key = desk
    client = fund_client(pm_key)
    scripts(three=_calls("get_clock", turns=1))
    rec = await wake(_spec(script="three"), client, workflow_input={})
    tools = await native.published_tools(client)
    assert rec.tools_sha256 == cassette.tools_sha256(tools)
    # The digest is the request's: rebuilding the first request from the record reproduces
    # the hash only with these tools, not with a narrowed list.
    first = CompletionRequest(messages=list(rec.transcript[:2]), tools=tools, model=None)
    assert request_sha256(first) == rec.exchanges[0].request_sha256
    narrowed = CompletionRequest(messages=list(rec.transcript[:2]), tools=tools[:1], model=None)
    assert request_sha256(narrowed) != rec.exchanges[0].request_sha256


@pytest.mark.anyio
async def test_usage_is_what_the_provider_returned(fund_client, desk, scripts) -> None:
    _, _, pm_key = desk
    scripts(paid=lambda r: CompletionResponse(
        content="ok", usage=Usage(input_tokens=7, output_tokens=3, cost_usd=0.5)))
    rec = await wake(_spec(script="paid"), fund_client(pm_key), workflow_input={})
    assert [e.usage for e in rec.exchanges] == [Usage(input_tokens=7, output_tokens=3,
                                                      cost_usd=0.5)]


@pytest.mark.anyio
async def test_the_hash_is_taken_before_the_mind_sees_the_request(
        fund_client, desk, scripts) -> None:
    """A mind that rewrites the request it was handed does not change what was hashed."""
    _, _, pm_key = desk
    client = fund_client(pm_key)

    def tamper(request):
        turn = sum(m.role == "assistant" for m in request.messages)
        for t in request.tools:
            object.__setattr__(t, "description", "tampered")
        if turn == 0:
            return CompletionResponse(tool_calls=[ToolCall(id="c", name="get_clock")])
        # Rewrite an argument dict the mind sent itself, after it was answered.
        request.messages[-2].tool_calls[0].arguments["x"] = 1
        return CompletionResponse(content="done")
    scripts(tamper=tamper)
    rec = await wake(_spec(script="tamper"), client, workflow_input={})
    assert rec.ended == "done"
    requests = _prefix_requests(rec, await native.published_tools(client))
    assert [request_sha256(r) for r in requests] == [e.request_sha256 for e in rec.exchanges]


@pytest.mark.anyio
@pytest.mark.parametrize("reply, reason", [
    (lambda r: 1 / 0, "provider_error:ZeroDivisionError"),
    (lambda r: CompletionResponse(tool_calls=[ToolCall(id="d", name="get_clock"),
                                              ToolCall(id="d", name="get_clock")]), "bad_reply"),
])
async def test_a_turn_whose_reply_was_not_accepted_is_recorded_without_usage(
        fund_client, desk, scripts, reply, reason) -> None:
    _, _, pm_key = desk
    scripts(bad=reply)
    rec = await wake(_spec(script="bad"), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.reason) == ("error", reason)
    (e,) = rec.exchanges
    assert (e.seq, e.usage) == (0, None) and len(e.request_sha256) == 64


@pytest.mark.anyio
async def test_no_exchange_for_a_turn_never_asked(fund_client, desk, gov, scripts,
                                                  monkeypatch) -> None:
    """HALT before the second model turn: one exchange, not two."""
    _, _, pm_key = desk
    real_execute = native._execute

    async def execute_then_halt(server, visible, call, *rest):
        result = await real_execute(server, visible, call, *rest)
        if visible is not None:
            (gov / "HALT").write_text("")
        return result
    monkeypatch.setattr(native, "_execute", execute_then_halt)
    scripts(one=_calls("get_clock", turns=2))
    rec = await wake(_spec(script="one"), fund_client(pm_key), workflow_input={})
    assert rec.ended == "halted" and len(rec.exchanges) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("fields, reason", [
    ({"wake_policy": "never"}, "wake_policy_never"),
    ({"name": "someone-else"}, "identity_mismatch"),
])
async def test_a_refused_wake_has_no_exchanges(fund_client, desk, fields, reason) -> None:
    _, _, pm_key = desk
    rec = await wake(_spec(**fields), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.reason, rec.exchanges) == ("refused", reason, ())


# --- the file --------------------------------------------------------------------------

def test_redact_count_every_position() -> None:
    k1, k2, k3 = (generate_api_key() for _ in range(3))
    outcome = {k1: "as a key", "as_a_value": k2,
               "nested": json.dumps({"api_key": k3}), "note": "fk_ alone, and fk"}
    text, redactions = cassette.dumps(outcome, **PARTS)
    assert not any(k in text for k in (k1, k2, k3))
    doc = json.loads(text)  # still valid JSON
    assert doc["redactions"] == redactions == 3
    assert doc["outcome"]["note"] == "fk_ alone, and fk"  # counter-example: untouched


def test_redact_count_of_nothing_is_zero_and_keeps_the_text() -> None:
    assert cassette.redact_count('{"a": "fk_ alone, and fk"}') == ('{"a": "fk_ alone, and fk"}', 0)


def test_dumps_is_deterministic_and_versioned() -> None:
    outcome = {"b": [1, 2, {"z": None, "a": "é"}], "a": 1.5}
    a = cassette.dumps(outcome, **PARTS)
    b = cassette.dumps(dict(reversed(list(outcome.items()))), **PARTS)
    assert a == b and a[0].isascii()
    doc = json.loads(a[0])
    assert (doc["cassette_version"], doc["hash_format"], doc["redactions"]) == (
        2, HASH_FORMAT, 0)
    assert doc["outcome"] == outcome


def test_dumps_refuses_what_is_not_plain_json() -> None:
    for bad in ({"x": float("nan")}, {"x": object()}, {"x": {1, 2}}):
        with pytest.raises((TypeError, ValueError)):
            cassette.dumps(bad, **PARTS)


def test_write_is_0600_and_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "run.cassette.json"
    n = cassette.write(path, {"ended": "completed"}, **PARTS)
    assert n == 0 and stat.S_IMODE(path.stat().st_mode) == 0o600
    before = path.read_bytes()
    with pytest.raises(CassetteError):
        cassette.write(path, {"ended": "other"}, **PARTS)
    assert path.read_bytes() == before


def test_write_refuses_symlink_bad_suffix_and_missing_parent(tmp_path: Path) -> None:
    d = tmp_path / "out"
    d.mkdir()
    target = d / "elsewhere"
    link = d / "link.cassette.json"
    link.symlink_to(target)  # dangling
    for bad in (link, d / "run.json", d / ".cassette.json", d / "no" / "such" / "x.cassette.json"):
        with pytest.raises(CassetteError):
            cassette.write(bad, {"ended": "completed"}, **PARTS)
    assert not target.exists() and not (d / "run.json").exists()
    assert sorted(p.name for p in d.iterdir()) == ["link.cassette.json"]


def test_the_open_itself_refuses_a_symlink_planted_after_the_check(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A race between ``check_path`` and ``open``: ``O_NOFOLLOW`` is the second lock."""
    target = tmp_path / "elsewhere"
    link = tmp_path / "link.cassette.json"
    link.symlink_to(target)
    monkeypatch.setattr(cassette, "check_path", lambda p: p)
    with pytest.raises(CassetteError):
        cassette.write(link, {"ended": "completed"}, **PARTS)
    assert not target.exists()


def test_a_write_that_fails_part_way_leaves_no_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import errno
    real_fdopen = os.fdopen

    class Full:
        def __init__(self, fd: int) -> None:
            self.f = real_fdopen(fd, "w")

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            self.f.close()

        def write(self, text: str) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(cassette.os, "fdopen", lambda fd, *a, **kw: Full(fd))
    path = tmp_path / "full.cassette.json"
    with pytest.raises(CassetteError):
        cassette.write(path, {"ended": "completed"}, **PARTS)
    assert not path.exists()


def test_check_path_is_what_write_checks(tmp_path: Path) -> None:
    ok = tmp_path / "x.cassette.json"
    assert cassette.check_path(ok) == ok
    ok.write_text("")
    with pytest.raises(CassetteError):
        cassette.check_path(ok)


def test_the_cassette_module_imports_nothing_from_physics() -> None:
    tree = (REPO / "runtime" / "cassette.py").read_text()
    assert "import app" not in tree and "from app" not in tree
    assert "lockstep" not in tree.split('"""', 2)[2]  # no import of the conductor


# --- the ignore rule (B-000i) ----------------------------------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.parametrize("path, ignored", [
    ("x.cassette.json", True),
    ("experiments/a/runs/r.json", True),
    ("experiments/a/spec.yaml", False),
    ("experiments/a/notes.md", False),
])
def test_gitignore_covers_cassettes(path: str, ignored: bool) -> None:
    got = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO).returncode
    assert (got == 0) is ignored


def test_umask_does_not_widen_the_mode(tmp_path: Path) -> None:
    old = os.umask(0)
    try:
        path = tmp_path / "m.cassette.json"
        cassette.write(path, {}, **PARTS)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        os.umask(old)
