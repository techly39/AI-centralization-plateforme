"""R-3b-2c-1: ``fund-runtime backtest`` — a run from a specs directory (ADR-032 (o)).

Claims under test:

* the command provisions one App agent per spec through the registrar key, then
  conducts the run with the clock key, and prints ``{ended, reason, registered,
  run}`` as JSON; exit 0 only for ``completed``; the workflow input reaches every
  wake; the output carries no key;
* the clock key is checked **before anything is registered**: on a live database,
  or with a key that is not the runtime identity, no agent is made;
* the command refuses itself (exit 2, nothing contacted) without both keys in the
  environment, with one key for both jobs, with no specs, with an input that is
  not a JSON object, with sizes out of range, and with a server that is not on
  this machine;
* a provisioning refusal (HALT, a taken name) exits 1 and names what may exist;
  a run that ends early exits 1.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Agent, AgentRole, Event
from app.ledger.events import EVENT_CLOCK_ADVANCED
from app.registry.pods import create_pod
from app.registry.service import register_agent, seed_runtime_agent
from runtime import cassette, cli
from runtime.providers import CompletionResponse, ToolCall
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    _app,
    gov,
    live_afterwards,
    woke,
    world,
)

#: The agents ``world`` registers itself.
WORLD = {"management", "pm-1", "pm-2", "pm-3", "runtime"}


def _write_specs(directory: Path, *specs: dict) -> Path:
    directory.mkdir(exist_ok=True)
    for spec in specs:
        (directory / f"{spec['id']}.yaml").write_text(yaml.safe_dump(spec))
    return directory


def _spec(id: str, name: str, pod: int, script: str = "read-a") -> dict:
    return {"id": id, "name": name, "role": "pm", "pod": pod, "provider": "scripted",
            "script": script, "charter": "Read the clock."}


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    return _write_specs(tmp_path / "specs", _spec("a-pm", "desk-1-pm", 1, "read-a"),
                        _spec("b-pm", "desk-2-pm", 2, "read-b"))


@pytest.fixture
def keys(world, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, world["admin"])
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, world["clock"])
    return world


def _run(SessionFactory, argv: list[str], capsys) -> tuple[int, dict | None, str]:
    """``fund-runtime`` against the test App over ASGI: ``(exit, stdout JSON, stderr)``."""
    app = _app(SessionFactory)
    with TestClient(app):
        code = cli.main(["backtest", *argv], transport=httpx.ASGITransport(app=app))
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


def _made(SessionFactory) -> dict[str, str | None]:
    with SessionFactory() as s:
        return {a.name: a.charter_ref for a in s.execute(select(Agent)).scalars()
                if a.name not in WORLD}


def _advances(SessionFactory) -> int:
    with SessionFactory() as s:
        return len(list(s.execute(select(Event).where(Event.type == EVENT_CLOCK_ADVANCED))
                        .scalars()))


# --- a run --------------------------------------------------------------------------------

def test_the_command_provisions_the_specs_and_lives_the_run(
        SessionFactory, keys, specs, woke, tmp_path, capsys):
    (tmp_path / "input.json").write_text(json.dumps({"universe": ["SYNA"]}))
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "3",
                                         "--input", str(tmp_path / "input.json")], capsys)
    assert code == 0 and (out["ended"], out["reason"]) == ("completed", "completed")
    assert out["registered"] == ["a-pm", "b-pm"]
    assert _made(SessionFactory) == {"desk-1-pm": "spec:a-pm", "desk-2-pm": "spec:b-pm"}
    run = out["run"]
    assert (run["ended"], run["minds"], len(run["steps"])) == ("completed", "scripted", 3)
    assert [[w["spec_id"] for w in st["wakes"]] for st in run["steps"]] == [["a-pm", "b-pm"]] * 3
    assert woke == ["a", "b"] * 3 and _advances(SessionFactory) == 3
    # The workflow input reached the wake, as the mind's context says.
    context = json.loads(run["steps"][0]["wakes"][0]["transcript"][1]["content"])
    assert context["input"] == {"universe": ["SYNA"]}


def test_the_output_carries_no_key(SessionFactory, keys, specs, woke, capsys):
    app = _app(SessionFactory)
    with TestClient(app):
        assert cli.main(["backtest", "--specs", str(specs), "--steps", "1"],
                        transport=httpx.ASGITransport(app=app)) == 0
    out, err = capsys.readouterr()
    assert keys["admin"] not in out + err and keys["clock"] not in out + err
    assert re.findall(r"fk_[A-Za-z0-9_-]{20,}", out + err) == []  # no minted mind key either


def test_a_key_a_mind_was_handed_is_not_printed(SessionFactory, keys, tmp_path, monkeypatch,
                                                capsys):
    """Audit c27 BLOCK 1: a management mind's ``register_agent`` result carries the
    new agent's key, and the transcript keeps tool results as they came."""
    from types import MappingProxyType

    from runtime import scripted

    def hires(request):
        if not any(m.role == "assistant" for m in request.messages):
            return CompletionResponse(content="hiring", tool_calls=[ToolCall(
                id="hire", name="register_agent",
                arguments={"name": "hire-1", "role": "analyst", "pod_id": 1})])
        return CompletionResponse(content="done")
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | {"hire": hires}))
    specs = _write_specs(tmp_path / "specs", {
        "id": "m-boss", "name": "desk-boss", "role": "management", "pod": None,
        "provider": "scripted", "script": "hire", "charter": "Hire."})
    app = _app(SessionFactory)
    with TestClient(app):
        assert cli.main(["backtest", "--specs", str(specs), "--steps", "1"],
                        transport=httpx.ASGITransport(app=app)) == 0
    out, err = capsys.readouterr()
    assert "hire-1" in _made(SessionFactory)  # the hire happened: a key was in the record
    assert "fk_<redacted>" in out
    assert re.findall(r"fk_[A-Za-z0-9_-]{20,}", out + err) == []


def test_redact_replaces_every_minted_key():
    from app.registry.security import generate_api_key
    minted = [generate_api_key() for _ in range(200)]
    text = json.dumps({"k": minted, "nested": json.dumps({"api_key": minted[0]})})
    assert not any(k in cli.redact(text) for k in minted)
    assert cli.redact('{"note": "fk_ alone, and fk"}') == '{"note": "fk_ alone, and fk"}'


def test_a_key_goes_through_no_proxy_from_the_environment(monkeypatch):
    """Audit c27 WARN 1: httpx honours HTTP(S)_PROXY / ALL_PROXY and the OS's proxy
    settings unless told not to; the key must reach the App and nothing else."""
    from mcp_server import FundClient
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example:3128")
    client = FundClient(base_url="http://127.0.0.1:8000", api_key="fk_x")
    assert client._client.trust_env is False
    asyncio.run(client.aclose())


def test_a_run_that_ends_early_exits_1(SessionFactory, keys, specs, woke, gov, monkeypatch,
                                       capsys):
    from types import MappingProxyType

    from runtime import scripted

    def halts(request):
        if not any(m.role == "assistant" for m in request.messages):
            (gov / "HALT").write_text("")
            return CompletionResponse(content="time?", tool_calls=[ToolCall(id="c", name="get_clock")])
        return CompletionResponse(content="done")
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | {"read-b": halts}))
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "3"], capsys)
    assert code == 1 and out["ended"] == "halted" and out["registered"] == ["a-pm", "b-pm"]
    assert _advances(SessionFactory) == 0


# --- --cassette (R-4a) ----------------------------------------------------------------------

def test_cassette_flag_writes_the_record_that_was_printed(
        SessionFactory, keys, specs, woke, tmp_path, capsys):
    path = tmp_path / "month.cassette.json"
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2",
                                           "--cassette", str(path)], capsys)
    assert code == 0 and out["ended"] == "completed"
    doc = json.loads(path.read_text())
    assert (doc["cassette_version"], doc["redactions"]) == (2, 0)
    assert doc["outcome"] == out  # the file holds what was printed
    # M-002: the file also holds what the replay needs, so one file is enough.
    assert doc["parameters"] == {"days_per_step": 1, "max_tool_calls": 64, "steps": 2,
                                 "workflow_input": {}}
    assert [e["spec"]["id"] for e in doc["specs"]] == ["a-pm", "b-pm"]
    assert all(e["sha256"] == cassette.spec_sha256(e["spec"]) for e in doc["specs"])
    assert (doc["world"], doc["ledger"]) == (None, None)  # an operator-hosted App: unverifiable
    assert all(w["tools_sha256"] and "model" in w
               for st in out["run"]["steps"] for w in st["wakes"])
    wakes = [w for st in out["run"]["steps"] for w in st["wakes"]]
    assert all(len(w["exchanges"]) == sum(m["role"] == "assistant" for m in w["transcript"])
               for w in wakes)
    assert all(e["usage"] is not None and len(e["request_sha256"]) == 64
               for w in wakes for e in w["exchanges"]) and wakes[0]["exchanges"]
    assert f"cassette {path} (0 redactions)" in err
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_a_refused_run_is_written_too(SessionFactory, specs, woke, monkeypatch, tmp_path, capsys):
    """A trial is never hidden (Art. 9): ``not_backtest`` still leaves its cassette."""
    s = SessionFactory()
    try:
        _, clock_key = seed_runtime_agent(s)
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        for n in (1, 2):
            create_pod(s, name=f"desk-{n}")
        s.commit()
    finally:
        s.close()
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, admin)
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, clock_key)
    path = tmp_path / "refused.cassette.json"
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2",
                                         "--cassette", str(path)], capsys)
    assert code == 1 and out["reason"] == "not_backtest"
    assert json.loads(path.read_text())["outcome"] == out


@pytest.mark.parametrize("name", ["taken.cassette.json", "wrong-suffix.json"])
def test_a_cassette_path_that_cannot_be_written_is_refused_before_anything(
        SessionFactory, keys, specs, woke, tmp_path, capsys, name):
    path = tmp_path / name
    path.write_text("mine")
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2",
                                           "--cassette", str(path)], capsys)
    assert (code, out) == (2, None) and "cassette" in err
    assert _made(SessionFactory) == {} and woke == [] and path.read_text() == "mine"


def test_a_cassette_that_cannot_be_written_after_the_run_exits_1(
        SessionFactory, keys, specs, woke, tmp_path, monkeypatch, capsys):
    """The path was fine at the check and taken during the run."""
    path = tmp_path / "late.cassette.json"
    real = cli._conduct

    async def conduct_then_take(*a, **kw):
        out = await real(*a, **kw)
        path.write_text("someone else's")
        return out
    monkeypatch.setattr(cli, "_conduct", conduct_then_take)
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "1",
                                           "--cassette", str(path)], capsys)
    assert code == 1 and out["ended"] == "completed"  # the outcome was still printed
    assert "exists" in err and path.read_text() == "someone else's"


def test_the_cassette_holds_no_key_a_mind_was_handed(
        SessionFactory, keys, tmp_path, monkeypatch, capsys):
    from types import MappingProxyType

    from runtime import scripted

    def hires(request):
        if not any(m.role == "assistant" for m in request.messages):
            return CompletionResponse(content="hiring", tool_calls=[ToolCall(
                id="hire", name="register_agent",
                arguments={"name": "hire-1", "role": "analyst", "pod_id": 1})])
        return CompletionResponse(content="done")
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | {"hire": hires}))
    specs = _write_specs(tmp_path / "specs", {
        "id": "m-boss", "name": "desk-boss", "role": "management", "pod": None,
        "provider": "scripted", "script": "hire", "charter": "Hire."})
    path = tmp_path / "hire.cassette.json"
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1",
                                         "--cassette", str(path)], capsys)
    assert code == 0 and "hire-1" in _made(SessionFactory)
    raw = path.read_text()
    assert re.findall(r"fk_[A-Za-z0-9_-]{20,}", raw) == []
    assert json.loads(raw)["redactions"] >= 1
    for secret in (keys["admin"], keys["clock"]):
        assert secret not in raw


# --- the clock is checked before anything is registered ------------------------------------

def test_a_live_database_gains_no_agents(SessionFactory, specs, woke, monkeypatch, capsys):
    s = SessionFactory()
    try:
        _, clock_key = seed_runtime_agent(s)
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        for n in (1, 2):
            create_pod(s, name=f"desk-{n}")
        s.commit()
    finally:
        s.close()
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, admin)
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, clock_key)
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and out == {"ended": "refused", "reason": "not_backtest",
                                 "registered": [], "run": None}
    assert _made(SessionFactory) == {} and woke == []


@pytest.mark.parametrize("clock", ["admin", "pm", "nonsense"])
def test_a_clock_key_that_is_not_the_runtime_registers_nothing(
        SessionFactory, keys, specs, woke, monkeypatch, capsys, clock):
    key = {"admin": keys["admin"], "pm": keys["pm"][1], "nonsense": "fk_not-a-key"}[clock]
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, key)
    if clock == "admin":  # one key for both jobs is the command's own refusal
        code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
        assert (code, out) == (2, None) and "one key" in err
    else:
        code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
        assert code == 1 and out["reason"] == {"pm": "clock_identity",
                                               "nonsense": "clock_unreadable:401"}[clock]
        assert out["registered"] == [] and out["run"] is None
    assert _made(SessionFactory) == {} and woke == [] and _advances(SessionFactory) == 0


# --- the command refuses itself ------------------------------------------------------------

@pytest.mark.parametrize("missing", [cli.REGISTRAR_KEY_ENV, cli.CLOCK_KEY_ENV])
def test_a_missing_key_is_refused_before_anything(SessionFactory, keys, specs, woke,
                                                  monkeypatch, capsys, missing):
    monkeypatch.setenv(missing, "  ")
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert (code, out) == (2, None) and missing in err
    assert _made(SessionFactory) == {}


def test_no_specs_is_refused(SessionFactory, keys, tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    code, out, err = _run(SessionFactory, ["--specs", str(tmp_path / "empty"), "--steps", "2"],
                          capsys)
    assert (code, out) == (2, None) and "no specs" in err and _advances(SessionFactory) == 0


@pytest.mark.parametrize("text", ["[1, 2]", "not json", '"a string"'])
def test_an_input_that_is_not_a_json_object_is_refused(SessionFactory, keys, specs, tmp_path,
                                                       capsys, text):
    (tmp_path / "input.json").write_text(text)
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2",
                                         "--input", str(tmp_path / "input.json")], capsys)
    assert (code, out) == (2, None) and _made(SessionFactory) == {}


@pytest.mark.parametrize("flags", [["--steps", "-1"], ["--steps", "0"], ["--steps", "3661"],
                                   ["--steps", "2", "--days-per-step", "0"],
                                   ["--steps", "2", "--days-per-step", "367"],
                                   ["--steps", "2", "--max-tool-calls", "-1"],
                                   ["--steps", "2", "--max-tool-calls", "1025"]])
def test_sizes_out_of_range_are_refused_before_anything(SessionFactory, keys, specs, capsys,
                                                        flags):
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), *flags], capsys)
    assert (code, out) == (2, None) and _made(SessionFactory) == {}


@pytest.mark.parametrize("url", ["http://example.com:8000", "ftp://127.0.0.1:8000",
                                 "http://user:pw@127.0.0.1:8000", "http://127.0.0.1:port",
                                 "http://127.0.0.1.evil.example", "127.0.0.1:8000",
                                 "http://localhost:8000"])
def test_a_server_off_this_machine_is_refused(SessionFactory, keys, specs, capsys, url):
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2",
                                           "--server", url], capsys)
    assert (code, out) == (2, None) and "this machine" in err and _made(SessionFactory) == {}


def test_a_server_that_is_not_there_is_a_refusal_not_a_crash(keys, specs, woke, capsys):
    """No transport: a real connection to a loopback port nothing listens on.
    (``woke`` installs the specs' scripts: since B-053 they are vetted before the
    clock is asked, so specs naming no script would be refused first.)"""
    import socket
    with socket.socket() as s:  # a port that was free a moment ago
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    code = cli.main(["backtest", "--specs", str(specs), "--steps", "2",
                     "--server", f"http://127.0.0.1:{port}"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out == {"ended": "refused", "reason": "clock_unreadable:503",
                                 "registered": [], "run": None}


def test_the_server_may_come_from_the_environment(SessionFactory, keys, specs, monkeypatch,
                                                  capsys):
    monkeypatch.setenv(cli.SERVER_ENV, "http://evil.example")
    code, _, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 2 and "this machine" in err


def test_the_shipped_desk_month_is_a_pod_of_two_scripted_minds():
    """``specs/desk-month`` is what the smoke run lives (scripts/smoke_run.py)."""
    from runtime.spec import load_specs
    root = Path(__file__).resolve().parent.parent / "specs" / "desk-month"
    assert [(s.id, s.name, s.role, s.pod, s.provider, s.script) for s in load_specs(root)] == [
        ("a-analyst", "desk-1-analyst", "analyst", 1, "scripted", "ma-signal-analyst"),
        ("b-pm", "desk-1-pm", "pm", 1, "scripted", "signal-pm")]
    assert json.loads((root / "input.json").read_text()) == {"universe": ["SYNA", "SYNB"]}


# --- provisioning refusals -----------------------------------------------------------------

def test_halt_provisions_nothing(SessionFactory, keys, specs, woke, gov, capsys):
    """B-054: was ``refused``/``provision:wake_refused:a-pm:halted``; a HALT run is ``halted``.
    Nothing is declared either (B-053)."""
    from app.ledger.events import EVENT_RUN_MINDS_DECLARED
    (gov / "HALT").write_text("")
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and out == {"ended": "halted", "reason": "halted", "registered": [],
                                 "run": None}
    assert _made(SessionFactory) == {} and woke == [] and _advances(SessionFactory) == 0
    with SessionFactory() as s:
        assert s.scalar(select(Event).where(Event.type == EVENT_RUN_MINDS_DECLARED)) is None


class HaltsAt(httpx.AsyncBaseTransport):
    """The App over ASGI, and the Human writes HALT (both files: the Runtime's and
    physics') ``when`` (``before`` | ``after``) the first request to ``path``."""

    def __init__(self, app, path: str, when: str, files: tuple[Path, ...]) -> None:
        self.inner, self.path, self.when, self.files = httpx.ASGITransport(app=app), path, when, files

    def _halt(self) -> None:
        for f in self.files:
            f.write_text("")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hit = request.url.path == self.path and not self.files[0].exists()
        if hit and self.when == "before":
            self._halt()
        resp = await self.inner.handle_async_request(request)
        if hit and self.when == "after":
            self._halt()
        return resp


def run_halting_at(SessionFactory, argv, capsys, path: str, when: str,
                   files: tuple[Path, ...]) -> tuple[int, dict | None]:
    app = _app(SessionFactory)
    with TestClient(app):
        code = cli.main(["backtest", *argv], transport=HaltsAt(app, path, when, files))
    out, _ = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None)


@pytest.mark.parametrize("path, registered", [
    ("/run/minds", []),              # after the declaration, before provision reads the law
    ("/agents/register", ["a-pm"]),  # after the first registration (provision's re-read)
])
def test_halt_during_provisioning_ends_halted_and_names_what_exists(
        SessionFactory, keys, specs, woke, gov, halt_file, capsys, path, registered):
    """B-054: was ``refused``/``provision:wake_refused:…:halted`` or ``provision:halted``."""
    code, out = run_halting_at(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys,
                               path, "after", (gov / "HALT", halt_file))
    assert code == 1 and out == {"ended": "halted", "reason": "halted",
                                 "registered": registered, "run": None}
    assert len(_made(SessionFactory)) == len(registered) and woke == []
    assert _advances(SessionFactory) == 0


def test_a_taken_name_provisions_nothing(SessionFactory, keys, tmp_path, woke, capsys):
    specs = _write_specs(tmp_path / "specs", _spec("a-pm", "desk-1-pm", 1),
                         _spec("b-pm", "pm-2", 2))  # world's own PM of pod 2
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and (out["reason"], out["registered"]) == ("provision:name_taken:b-pm", [])
    assert _made(SessionFactory) == {} and woke == []
