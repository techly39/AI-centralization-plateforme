"""R-4b-1: a replay drives the minds from a cassette (ADR-038, serves EC2's test half, ticks nothing).

Claims under test:

* **the reader** — ``cassette.read`` is the inverse of ``write`` and accepts only the canonical
  v2 document (M-002: version 1 is refused by name): no repeated key (two minted keys redact to one), no NaN, no extra key, no other
  version or hash format, no non-ASCII, no pretty-printing, no symlink or directory, no
  nesting deep enough to exhaust the parser;
* **the recording** — only a completed run replays, and only if its wakes are consistent;
* **the mind** — the name ``cassette`` builds ``CassetteProvider`` from a ``Tape`` and from
  nothing else; provisioning still refuses every contradiction; a replay replies with zero
  usage and shares nothing with the tape;
* **the month** — the recorded scripted month, replayed in the same world into a fresh
  database, leaves the same ledger and transcripts; in another world, or with a narrowed
  tool surface, it ends ``diverged`` at a named place and the clock never moves after it; HALT
  is not mistaken for a divergence.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import json
import os
from pathlib import Path

import pytest

from app.clock import LiveClock, set_clock
from app.marketdata import set_provider
from runtime import cassette, governance
from runtime.cassette import CassetteError
from runtime.lockstep import record_json
from runtime.native import Exchange, WakeRecord, wake
from runtime.providers import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ToolCall,
    Usage,
)
from runtime.provision import ProvisionError, provision
from runtime.registry import ProviderRefused, build_provider
from runtime.replay import (
    CassetteProvider,
    Recording,
    RecordingError,
    ReplayedFailure,
    ReplayMiss,
    Tape,
    Turn,
    as_cassette,
)
from runtime.spec import AgentSpec
from tests.cassette_parts import PARTS
from tests.test_runtime_native import _calls, _spec, anyio_backend, fund_client, gov, scripts  # noqa: F401
from tests.test_runtime_pod import DAYS, _pod_month

REPO = Path(__file__).resolve().parent.parent


# --- the reader ------------------------------------------------------------------------

def _outcome() -> dict:
    return {"run": {"ended": "completed", "steps": [], "note": "fk_<redacted>"}}


def test_read_inverts_write(tmp_path: Path) -> None:
    path = tmp_path / "a.cassette.json"
    outcome = {"run": {"ended": "completed", "steps": []},
               "key": "fk_" + "A" * 43, "n": 1, "t": "café"}
    redactions = cassette.write(path, outcome, **PARTS)
    got = cassette.read(path)
    assert got.redactions == redactions == 1
    assert got.outcome == {**outcome, "key": "fk_<redacted>"}


def _raw(tmp_path: Path, text: str | bytes) -> Path:
    path = tmp_path / "x.cassette.json"
    path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return path


def _doc(**over) -> str:
    spec = PARTS["specs"][0]
    base = {"cassette_version": 2, "hash_format": cassette.HASH_FORMAT, "ledger": None,
            "outcome": {"run": None}, "parameters": PARTS["parameters"], "redactions": 0,
            "specs": [{"sha256": cassette.spec_sha256(spec), "spec": spec}], "world": None}
    base.update(over)
    return json.dumps({k: v for k, v in base.items() if v is not ...}, sort_keys=True,
                      separators=(",", ":"))


def test_read_accepts_the_hand_built_canonical_document(tmp_path: Path) -> None:
    got = cassette.read(_raw(tmp_path, _doc()))  # the builder is right
    assert (got.outcome, got.redactions) == ({"run": None}, 0)


def test_read_refuses_what_is_not_a_canonical_v2_cassette(tmp_path: Path) -> None:
    good = _doc()
    bad = {
        "version 1": _doc(cassette_version=1),
        "version 3": _doc(cassette_version=3),
        "version true": _doc(cassette_version=True),
        "other hash format": _doc(hash_format="sha256/other/1"),
        "extra key": _doc(extra=1),
        "missing key": _doc(redactions=...),
        "negative redactions": _doc(redactions=-1),
        "redactions true": _doc(redactions=True),
        "outcome a list": _doc(outcome=[]),
        "NaN": good.replace('"run":null', '"run":NaN'),
        "Infinity": good.replace('"run":null', '"run":Infinity'),
        "non-ascii byte": good.replace('"run"', '"rün"').encode("utf-8"),
        "pretty-printed": json.dumps(json.loads(good), indent=2),
        "not sorted": '{"redactions":0,' + good[1:].replace(',"redactions":0', ""),
        "trailing text": good + "\n",
        "not json": "cassette",
        "top level a list": "[]",
        "too deep": '{"cassette_version":2,"hash_format":"' + cassette.HASH_FORMAT
                    + '","outcome":' + "[" * 100_000 + "]" * 100_000 + ',"redactions":0}',
    }
    for label, text in bad.items():
        with pytest.raises(CassetteError):
            cassette.read(_raw(tmp_path, text))
        assert label  # the failing case is named by the parametrised-in-spirit loop below
    # Counter-check: each refusal above is for its stated reason, not for a typo in the builder.
    assert cassette.read(_raw(tmp_path, good)).redactions == 0


def test_read_refuses_a_repeated_key_and_two_minted_keys_that_redact_to_one(
        tmp_path: Path) -> None:
    dup = '{"cassette_version":2,"hash_format":"%s","outcome":{"a":1,"a":2},"redactions":0}' % (
        cassette.HASH_FORMAT)
    with pytest.raises(CassetteError, match="twice"):
        cassette.read(_raw(tmp_path, dup))
    # Counter-example: two different minted keys as object keys are two keys when written, one
    # after redaction. Since v2 the writer refuses it (nothing is left behind), so the reader
    # never meets the file it would have had to refuse.
    path = tmp_path / "keys.cassette.json"
    with pytest.raises(CassetteError, match="twice"):
        cassette.write(path, {"run": {"fk_" + "A" * 43: 1, "fk_" + "B" * 43: 2}}, **PARTS)
    assert not path.exists()


def test_read_refuses_a_symlink_a_directory_and_a_missing_file(tmp_path: Path) -> None:
    real = tmp_path / "real.cassette.json"
    cassette.write(real, _outcome(), **PARTS)
    link = tmp_path / "link.cassette.json"
    link.symlink_to(real)
    with pytest.raises(CassetteError):
        cassette.read(link)
    folder = tmp_path / "dir.cassette.json"
    folder.mkdir()
    with pytest.raises(CassetteError):
        cassette.read(folder)
    with pytest.raises(CassetteError):
        cassette.read(tmp_path / "none.cassette.json")
    # A FIFO has no writer: opening it must be refused, not wait (audit c32 WARN 1).
    fifo = tmp_path / "pipe.cassette.json"
    os.mkfifo(fifo)
    with pytest.raises(CassetteError, match="regular"):
        cassette.read(fifo)


# --- the recording ---------------------------------------------------------------------

SHA = "a" * 64


def _wake_json(spec_id: str = "pm", *, ended="done", calls=0, usage=True, sha=SHA,
               content="hold") -> dict:
    """A recorded wake of one answered turn: system, user, assistant."""
    transcript = [Message(role="system", content="Work."),
                  Message(role="user", content='{"me":{"id":1}}'),
                  Message(role="assistant", content=content)]
    return {"spec_id": spec_id, "ended": ended, "reason": ended, "tool_calls": calls,
            "tool_failures": 0, "model": None, "tools_sha256": SHA, "transcript": [m.model_dump(mode="json") for m in transcript],
            "exchanges": [{"seq": 0, "request_sha256": sha,
                           "usage": {"input_tokens": 1, "output_tokens": 2, "cost_usd": 0.5}
                           if usage else None}]}


def _outcome_of(*wakes: dict, ended="completed", **run) -> dict:
    return {"run": {"ended": ended, "retired": [], "steps": [
        {"step": 0, "at": "2024-01-01T00:00:00Z", "wakes": list(wakes), "advanced_to": "x"}],
        **run}}


def test_a_tape_pairs_each_exchange_with_its_reply_and_its_prefix() -> None:
    rec = Recording.from_outcome(_outcome_of(_wake_json()))
    assert (rec.steps, rec.spec_ids) == (1, frozenset({"pm"}))
    tape = rec.tape(0, "pm")
    (turn,) = tape.turns
    assert (tape.ended, tape.tool_calls) == ("done", 0)
    assert turn.request_sha256 == SHA
    assert turn.response == CompletionResponse(
        content="hold", usage=Usage(input_tokens=1, output_tokens=2, cost_usd=0.5))
    assert [m.role for m in turn.prefix] == ["system", "user"]
    assert rec.tape(0, "nobody") == Tape() and rec.tape(5, "pm") == Tape()


def test_a_failed_last_turn_has_no_reply_and_the_whole_transcript_as_its_prefix() -> None:
    w = _wake_json(ended="error", usage=False)
    w["transcript"] = w["transcript"][:2]
    (turn,) = Recording.from_outcome(_outcome_of(w)).tape(0, "pm").turns
    assert turn.response is None and len(turn.prefix) == 2


@pytest.mark.parametrize("outcome", [
    {"run": None}, {}, {"run": []},
    _outcome_of(_wake_json(), ended="halted"),
    _outcome_of(_wake_json(), ended="refused"),
    _outcome_of(_wake_json(), retired=["pm"]),
    _outcome_of(_wake_json(sha="A" * 64)),
    _outcome_of(_wake_json(sha="a" * 63)),
    _outcome_of(_wake_json(sha=7)),
    _outcome_of(_wake_json(), _wake_json()),  # one mind wakes twice in a step
])
def test_a_recording_refuses_what_is_not_a_completed_consistent_run(outcome) -> None:
    with pytest.raises(RecordingError):
        Recording.from_outcome(outcome)


def test_a_hand_built_tape_or_calendar_is_validated() -> None:
    """A negative call count would make the conductor raise mid-run (audit c32 re-audit WARN 1);
    a calendar that does not fit the steps would raise an IndexError there (NOTE 1)."""
    with pytest.raises(RecordingError):
        Tape((), "tool_budget", -1)
    for calendar in ((("a", "b"),), (("a",), ("b",)), (("a", 1), ("b", "c"))):
        with pytest.raises(RecordingError):
            Recording(2, {}, calendar)
    assert Recording(2, {}, (("a", "b"), ("b", "c"))).calendar(1) == ("b", "c")
    assert Recording(2, {}).calendar(1) is None


def test_a_recording_refuses_inconsistent_wakes() -> None:
    def mutate(f):
        w = _wake_json()
        f(w)
        return _outcome_of(w)
    bad = {
        "seq gap": mutate(lambda w: w["exchanges"][0].update(seq=1)),
        "unanswered exchange that is not last": mutate(
            lambda w: w["exchanges"].insert(0, {"seq": 0, "request_sha256": SHA, "usage": None})
            or w["exchanges"][1].update(seq=1)),
        "assistant without an exchange": mutate(lambda w: w["exchanges"].clear()),
        "exchange without an assistant": mutate(lambda w: w["transcript"].pop()),
        "unknown message field": mutate(lambda w: w["transcript"][0].update(extra=1)),
        "usage not a usage": mutate(lambda w: w["exchanges"][0].update(usage={"cost_usd": -1})),
        "ended not a str": mutate(lambda w: w.update(ended=3)),
        "tool_calls a bool": mutate(lambda w: w.update(tool_calls=True)),
        "no transcript": mutate(lambda w: w.pop("transcript")),
    }
    for label, outcome in bad.items():
        with pytest.raises(RecordingError):
            Recording.from_outcome(outcome)
        assert label


# --- the mind --------------------------------------------------------------------------

def _tape_of(*replies: CompletionResponse | None, ended="done") -> Tape:
    out = []
    for r in replies:
        req = CompletionRequest(messages=[Message(role="user", content=f"q{len(out)}")])
        out.append(Turn(cassette.request_sha256(req), r, tuple(req.messages)))
    return Tape(tuple(out), ended, 0)


def _ask(i: int) -> CompletionRequest:
    return CompletionRequest(messages=[Message(role="user", content=f"q{i}")])


def test_the_provider_replays_at_zero_usage_and_shares_nothing_with_the_tape() -> None:
    reply = CompletionResponse(content="hi", tool_calls=[ToolCall(id="c1", name="get_clock")],
                               usage=Usage(input_tokens=9, output_tokens=9, cost_usd=3.0))
    tape = _tape_of(reply)
    provider = CassetteProvider(tape)
    got = provider.complete(_ask(0))
    assert (got.content, got.tool_calls, got.usage) == ("hi", reply.tool_calls, Usage())
    got.tool_calls.append(ToolCall(id="evil", name="x"))
    assert tape.turns[0].response.tool_calls == reply.tool_calls  # the tape is unchanged
    assert tape.turns[0].response.usage.cost_usd == 3.0  # the recorded cost stays with the recording
    assert provider.name == "cassette" and provider.spends_money is False


def test_the_provider_refuses_a_miss_a_turn_beyond_the_tape_and_replays_a_failure() -> None:
    provider = CassetteProvider(_tape_of(CompletionResponse(content="a"), None))
    with pytest.raises(ReplayMiss):
        CassetteProvider(_tape_of(CompletionResponse(content="a"))).complete(_ask(1))
    provider.complete(_ask(0))
    with pytest.raises(ReplayedFailure):
        provider.complete(_ask(1))
    with pytest.raises(ReplayMiss, match="past"):
        provider.complete(_ask(2))
    with pytest.raises(ReplayMiss):
        CassetteProvider(Tape()).complete(_ask(0))


def _cassette_spec(**more) -> AgentSpec:
    return _spec(provider="cassette", script=None, **more)


def test_cassette_builds_exactly_the_cassette_class_and_only_from_a_tape() -> None:
    assert type(build_provider(_cassette_spec(), Tape())) is CassetteProvider
    for not_a_tape in (None, {"turns": []}, CassetteProvider(Tape()), object(),
                       type("Sub", (Tape,), {})()):
        with pytest.raises(ProviderRefused) as caught:
            build_provider(_cassette_spec(), not_a_tape)
        assert caught.value.reason == "unavailable"


def test_the_cassette_class_is_built_for_the_name_cassette_only(monkeypatch) -> None:
    """A provider added to the table later must not fall through to the cassette builder."""
    from types import MappingProxyType
    from runtime import registry
    monkeypatch.setattr(registry, "PROVIDER_CLASSES",
                        MappingProxyType({**registry.PROVIDER_CLASSES, "metered": object}))
    with pytest.raises(ProviderRefused) as caught:
        build_provider(_spec(provider="metered", script=None), Tape())
    assert caught.value.reason == "unavailable"


def test_a_tape_on_any_other_provider_is_a_contradiction() -> None:
    with pytest.raises(ProviderRefused) as caught:
        build_provider(_spec(), Tape())  # the default spec is scripted
    assert caught.value.reason == "contradiction"


@pytest.mark.parametrize("more", [{"budget_usd": 1.0}, {"script": "x"}])
def test_a_cassette_spec_with_a_budget_or_a_script_is_refused_with_a_tape(more) -> None:
    spec = _spec(provider="cassette", **({"script": None} | more))
    with pytest.raises(ProviderRefused) as caught:
        build_provider(spec, Tape())
    assert caught.value.reason == "contradiction"


def test_a_cassette_spec_keeps_its_recorded_model_and_still_calls_nothing() -> None:
    # ADR-047 §6: a replayed real-model mind carries the model it was recorded with (the
    # request hash names it); what it builds is still the tape player, nothing else.
    spec = _spec(provider="cassette", script=None, model="vendor/some-model")
    assert type(build_provider(spec, Tape())) is CassetteProvider


@pytest.mark.anyio
@pytest.mark.parametrize("bad_tape", [{"turns": []}, CassetteProvider(Tape()), "tape",
                                      type("Sub", (Tape,), {})()])
async def test_a_wake_takes_a_tape_only_if_it_is_exactly_a_tape(
        fund_client, desk, bad_tape) -> None:
    _, _, pm_key = desk
    rec = await wake(_cassette_spec(), fund_client(pm_key), workflow_input={}, tape=bad_tape)
    assert (rec.ended, rec.reason, rec.transcript, rec.exchanges, rec.tool_calls) == (
        "refused", "unavailable", (), (), 0)


@pytest.mark.anyio
async def test_a_cassette_mind_with_no_tape_is_refused_and_nothing_wakes(
        fund_client, desk) -> None:
    _, _, pm_key = desk
    rec = await wake(_cassette_spec(), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.reason, rec.tool_calls) == ("refused", "unavailable", 0)


@pytest.mark.anyio
async def test_provisioning_refuses_every_contradiction_of_a_cassette_spec(
        fund_client, desk) -> None:
    # The refusals come before anything is contacted: the registrar is never called.
    for more in ({"budget_usd": 1.0}, {"budget_usd": 1.0, "model": "m"}):
        spec = _spec(provider="cassette", **({"script": None} | more))
        with pytest.raises(ProvisionError, match="provider_refused:.*:contradiction"):
            await provision([spec], fund_client(desk[2]), fund_client)
    spec = _spec(provider="cassette", script="moving-average-pm")
    with pytest.raises(ProvisionError, match="contradiction"):
        await provision([spec], fund_client(desk[2]), fund_client)


def test_the_replay_module_has_no_reach() -> None:
    from tests.test_runtime_native import _imports
    # ``decimal``: exact micro-dollar arithmetic for the recorded charges (no I/O, no reach).
    may = {"__future__", "json", "re", "collections.abc", "dataclasses", "decimal", "pathlib",
           "typing", "pydantic", "runtime", "runtime.providers"}
    found = _imports((REPO / "runtime" / "replay.py").read_text())
    assert "runtime.providers" in found and found <= may, found - may
    for planted in ("import httpx\n", "import socket\n", "from mcp_server import FundClient\n",
                    "open('/etc/hosts')\n"):
        assert not _imports("import json\n" + planted) <= may, planted
    # `from runtime import native` names the module `runtime`, which `may` allows: the planted
    # reach is caught only by the allowlist being exact about what replay.py imports from it.
    src = (REPO / "runtime" / "replay.py").read_text()
    imported = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)
                and n.module == "runtime"]
    assert [a.name for n in imported for a in n.names] == ["cassette"]


# --- where a replay leaves its recording -----------------------------------------------

def _replayed(*, sha: str, before: str, ended="done", calls=0, extra=(), model=None,
              tools=SHA) -> WakeRecord:
    """A replayed one-turn wake whose request hashed to ``sha`` with ``before`` as its user text."""
    transcript = (Message(role="system", content="Work."), Message(role="user", content=before),
                  Message(role="assistant", content="hold"))
    return WakeRecord("pm", ended, ended, calls, transcript, 0,
                      (Exchange(0, sha, Usage()), *extra), model, tools)


def _recorded(user: str, ended="done", calls=0) -> Recording:
    w = _wake_json(ended=ended, calls=calls)
    w["transcript"][1]["content"] = user
    return Recording.from_outcome(_outcome_of(w))


def test_divergence_kinds_come_from_the_records() -> None:
    same = _recorded("today")
    assert same.divergence(0, _replayed(sha=SHA, before="today")) is None
    other = "b" * 64
    assert same.divergence(0, _replayed(sha=other, before="tomorrow")) == "0:world"
    assert same.divergence(0, _replayed(sha=other, before="today")) == "0:surface"
    # A recorded redacted key: the replayed text holds a real one; it redacts equal, the hash differs.
    keyed = _recorded("key fk_<redacted> here")
    live = "key fk_" + "Z" * 43 + " here"
    assert keyed.divergence(0, _replayed(sha=other, before=live)) == "0:key"
    # Counter-example: the same prefix with no marker is a changed surface, not a key.
    assert same.divergence(0, _replayed(sha=other, before="today")) == "0:surface"
    # A turn the recording does not have; a wake that stops early; one that ends differently.
    extra = (Exchange(1, other, None),)
    assert same.divergence(0, _replayed(sha=SHA, before="today", extra=extra)) == "1:unrecorded"
    assert same.divergence(1, _replayed(sha=SHA, before="today")) == "0:unrecorded"
    short = WakeRecord("pm", "refused", "x", 0)
    assert same.divergence(0, short) == "0:ended"
    assert same.divergence(0, _replayed(sha=SHA, before="today", ended="tool_budget")) == "1:ended"
    assert same.divergence(0, _replayed(sha=SHA, before="today", calls=2)) == "1:ended"


def test_note5_changed_tools_with_redacted_key_in_prefix_reads_surface() -> None:
    """c32 NOTE 5: a changed tool surface is a surface change even when a key was redacted."""
    keyed = _recorded("key fk_<redacted> here")
    live = "key fk_" + "Z" * 43 + " here"
    other = "b" * 64
    assert keyed.divergence(0, _replayed(sha=other, before=live, tools="c" * 64)) == "0:surface"
    assert keyed.divergence(0, _replayed(sha=other, before=live, model="m")) == "0:surface"


def test_note5_same_tools_with_redacted_key_reads_key() -> None:
    """Counter-example: with the surface unchanged, the redacted key is what differs."""
    keyed = _recorded("key fk_<redacted> here")
    live = "key fk_" + "Z" * 43 + " here"
    assert keyed.divergence(0, _replayed(sha="b" * 64, before=live)) == "0:key"


def test_wake_without_tools_sha256_is_a_recording_error() -> None:
    for missing in ("tools_sha256", "model"):
        w = _wake_json()
        del w[missing]
        with pytest.raises(RecordingError, match="malformed"):
            Recording.from_outcome(_outcome_of(w))
    for bad in ("short", 7, None):
        w = _wake_json()
        w["tools_sha256"] = bad
        with pytest.raises(RecordingError, match="tools"):
            Recording.from_outcome(_outcome_of(w))


# --- the month -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def replays(tmp_path_factory):
    from app.config import get_settings
    from app.registry import halt
    with pytest.MonkeyPatch.context() as mp:
        d = tmp_path_factory.mktemp("gov")
        (d / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: null\n")
        mp.setattr(governance, "HALT_FILE", d / "HALT")
        mp.setattr(governance, "HUMAN_YAML", d / "human.yaml")
        mp.setattr(halt, "HALT_FILE", d / "PHYSICS_HALT")
        mp.setattr(get_settings().oms, "pending_monitor_enabled", False)
        try:
            recorded = _pod_month(11)
            path = d / "month.cassette.json"
            cassette.write(path, {"run": record_json(recorded["run"])}, **PARTS)
            rec = Recording.load(path)
            yield {"recorded": recorded, "rec": rec, "dir": d,
                   "same": _pod_month(11, replay=rec), "path": path}
        finally:
            set_provider(None)
            set_clock(LiveClock())


def test_a_replayed_month_leaves_the_recorded_ledger(replays) -> None:
    recorded, same = replays["recorded"], replays["same"]
    run = same["run"]
    assert (run.ended, run.reason, run.minds, len(run.steps)) == (
        "completed", "completed", "cassette", DAYS)
    assert len(recorded["ledger"]) == len(same["ledger"])
    for x, y in zip(recorded["ledger"], same["ledger"]):
        assert x == y, f"first divergence at event {x[0]}:\n{x}\n{y}"
    wakes = [w for st in run.steps for w in st.wakes]
    assert [w.transcript for w in wakes] == [
        w.transcript for st in recorded["run"].steps for w in st.wakes]
    assert wakes and all(e.usage == Usage() for w in wakes for e in w.exchanges)
    assert [e.request_sha256 for w in wakes for e in w.exchanges] == [
        e.request_sha256 for st in recorded["run"].steps for w in st.wakes for e in w.exchanges]
    assert replays["rec"].steps == DAYS and len(replays["rec"].spec_ids) == 3


def test_a_replayed_month_writes_the_recorded_cassette_bytes_but_for_the_label(replays) -> None:
    """The record of the replay equals the recorded one except where the minds' provider shows."""
    a = json.loads(cassette.dumps({"run": record_json(replays["recorded"]["run"])}, **PARTS)[0])
    b = json.loads(cassette.dumps({"run": record_json(replays["same"]["run"])}, **PARTS)[0])
    assert a["outcome"]["run"].pop("minds") == "scripted"
    assert b["outcome"]["run"].pop("minds") == "cassette"
    assert a == b


def _count_events(ledger, kind: str) -> int:
    return sum(1 for e in ledger if e[3] == kind)


def test_a_replay_in_another_world_diverges_stops_and_never_moves_the_clock(replays) -> None:
    other = _pod_month(12, replay=replays["rec"])
    run = other["run"]
    assert run.ended == "diverged" and run.minds == "cassette"
    assert run.reason.startswith("diverged:") and run.reason.endswith(":world"), run.reason
    _, spec_id, step, seq, kind = run.reason.split(":")
    assert int(step) == len(run.steps) - 1  # the run stopped at the step it diverged in
    assert run.steps[-1].advanced_to is None
    assert all(st.advanced_to is not None for st in run.steps[:-1])
    # Nothing woke after the diverging wake: the later minds of that step did not run.
    assert [w.spec_id for w in run.steps[-1].wakes][-1] == spec_id
    assert _count_events(other["ledger"], "clock_advanced") == len(run.steps) - 1


def test_a_narrowed_tool_surface_is_a_surface_divergence(replays) -> None:
    def narrow(spec: AgentSpec) -> AgentSpec:
        return spec.model_copy(update={"tools": ("get_clock",)})
    run = _pod_month(11, replay=replays["rec"], tweak=narrow)["run"]
    assert run.ended == "diverged" and run.reason.endswith(":0:surface"), run.reason
    assert len(run.steps) == 1 and run.steps[0].advanced_to is None


def test_a_replay_that_is_halted_ends_halted_not_diverged(replays, gov, monkeypatch) -> None:
    """HALT lands while the first mind is mid-wake (before its 3rd tool call). That wake stops
    with fewer exchanges than its tape: the conductor must read that as HALT, not as an
    ``ended`` divergence, and the clock must not move. (Provisioning itself refuses under HALT,
    so the file cannot exist before the run.)"""
    from runtime import native
    real, calls = native._execute, []

    async def halt_on_third_call(*a, **kw):
        calls.append(1)
        if len(calls) == 3:
            (gov / "HALT").write_text("stop")  # `gov` repoints HALT_FILE: write where it points
        return await real(*a, **kw)
    monkeypatch.setattr(native, "_execute", halt_on_third_call)
    try:
        run = _pod_month(11, replay=replays["rec"])["run"]
    finally:
        (gov / "HALT").unlink(missing_ok=True)
    assert (run.ended, run.reason) == ("halted", "halted")
    (step,) = run.steps
    assert step.advanced_to is None and step.wakes[-1].ended == "halted"
    assert len(step.wakes[-1].exchanges) < len(replays["rec"].tape(0, step.wakes[-1].spec_id).turns)


def test_a_mind_that_is_retired_in_a_replay_is_a_divergence_not_a_quiet_completion(
        replays, monkeypatch) -> None:
    """The recorded run woke every mind every day. If the replay's world retires one (its key
    dies), the run must not finish ``completed`` with a mind missing."""
    from runtime import lockstep
    real, n = lockstep.wake, []

    async def first_wake_finds_a_dead_key(spec, *a, **kw):
        n.append(1)
        if len(n) == 1:
            return WakeRecord(spec.id, "refused", "no_identity", 0)
        return await real(spec, *a, **kw)

    async def dead(client):
        return True
    monkeypatch.setattr(lockstep, "wake", first_wake_finds_a_dead_key)
    monkeypatch.setattr(lockstep, "_key_dead", dead)
    run = _pod_month(11, replay=replays["rec"])["run"]
    assert run.ended == "diverged" and run.reason == "diverged:a-analyst-1:0:0:ended", run.reason
    assert run.steps[-1].advanced_to is None


def test_a_replay_refuses_mixed_minds_wrong_ids_and_wrong_steps(replays) -> None:
    rec = replays["rec"]
    # Mixed: one mind is still scripted.
    def one_scripted(spec):
        return spec if spec.id != "b-pm-1" else spec.model_copy(
            update={"provider": "scripted", "script": "signal-pm"})
    run = _pod_month(11, replay=rec, tweak=one_scripted)["run"]
    assert (run.ended, run.reason, run.steps) == ("refused", "replay_mixed", ())
    # Wrong ids: a mind the recording does not hold.
    renamed = Recording(rec.steps, {(s, ("x-" + i)): rec.tape(s, i)
                                    for s in range(rec.steps) for i in sorted(rec.spec_ids)})
    run = _pod_month(11, replay=renamed)["run"]
    assert (run.ended, run.reason) == ("refused", "replay_minds")
    # Wrong steps.
    short = Recording(rec.steps - 1, {(s, i): rec.tape(s, i)
                                      for s in range(rec.steps - 1) for i in sorted(rec.spec_ids)})
    run = _pod_month(11, replay=short)["run"]
    assert (run.ended, run.reason) == ("refused", "replay_steps")


def test_run_backtest_takes_only_a_real_recording(replays) -> None:
    class Fake:
        steps = DAYS
        spec_ids = frozenset({"a-analyst-1", "b-pm-1", "c-pm-2"})

        def tape(self, step, spec_id):
            return Tape()
    with pytest.raises(ValueError, match="Recording"):
        _pod_month(11, replay=Fake())


def test_cassette_minds_with_no_recording_refuse_to_wake_and_nothing_moves(replays) -> None:
    run = _pod_month(11, cassettes=True)["run"]
    assert (run.ended, run.reason) == ("refused", "wake_refused:a-analyst-1:unavailable")
    assert len(run.steps) == 1 and run.steps[0].advanced_to is None


# --- the refusal law (ADR-040 (2), audit c32 NOTE 4) ------------------------------------------

@pytest.mark.parametrize("why", ["contradiction", "unknown_tool", "identity_mismatch", "bad_input",
                                 "no_identity"])
def test_a_setup_refusal_in_a_replay_is_a_refusal_not_a_divergence(replays, monkeypatch, why) -> None:
    """A replay ends the way a live run would at every wake a live run would stop: a refusal
    that is not a retirement is ``wake_refused``, never ``diverged:...:ended``. The retirement
    test above stays the counter-example (a dead key IS a divergence in a replay)."""
    from runtime import lockstep
    real, n = lockstep.wake, []

    async def first_wake_is_refused(spec, *a, **kw):
        n.append(1)
        if len(n) == 1:
            return WakeRecord(spec.id, "refused", why, 0)
        return await real(spec, *a, **kw)

    async def alive(client):
        return False
    monkeypatch.setattr(lockstep, "wake", first_wake_is_refused)
    monkeypatch.setattr(lockstep, "_key_dead", alive)
    out = _pod_month(11, replay=replays["rec"])
    run = out["run"]
    assert (run.ended, run.reason) == ("refused", f"wake_refused:a-analyst-1:{why}")
    assert run.steps[-1].advanced_to is None
    assert _count_events(out["ledger"], "clock_advanced") == 0
