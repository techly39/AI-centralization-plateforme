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
from runtime import cli
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


@pytest.mark.parametrize("flags", [["--steps", "-1"], ["--steps", "3661"],
                                   ["--steps", "2", "--days-per-step", "0"],
                                   ["--steps", "2", "--days-per-step", "367"],
                                   ["--steps", "2", "--max-tool-calls", "-1"]])
def test_sizes_out_of_range_are_refused_before_anything(SessionFactory, keys, specs, capsys,
                                                        flags):
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), *flags], capsys)
    assert (code, out) == (2, None) and _made(SessionFactory) == {}


@pytest.mark.parametrize("url", ["http://example.com:8000", "ftp://127.0.0.1:8000",
                                 "http://user:pw@127.0.0.1:8000", "http://127.0.0.1:port",
                                 "http://127.0.0.1.evil.example", "127.0.0.1:8000"])
def test_a_server_off_this_machine_is_refused(SessionFactory, keys, specs, capsys, url):
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2",
                                           "--server", url], capsys)
    assert (code, out) == (2, None) and "this machine" in err and _made(SessionFactory) == {}


def test_a_server_that_is_not_there_is_a_refusal_not_a_crash(keys, specs, capsys):
    """No transport: a real connection to a loopback port nothing listens on."""
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
    (gov / "HALT").write_text("")
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and out["reason"].startswith("provision:wake_refused:a-pm:")
    assert out["registered"] == [] and _made(SessionFactory) == {} and woke == []


def test_a_taken_name_provisions_nothing(SessionFactory, keys, tmp_path, woke, capsys):
    specs = _write_specs(tmp_path / "specs", _spec("a-pm", "desk-1-pm", 1),
                         _spec("b-pm", "pm-2", 2))  # world's own PM of pod 2
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and (out["reason"], out["registered"]) == ("provision:name_taken:b-pm", [])
    assert _made(SessionFactory) == {} and woke == []
