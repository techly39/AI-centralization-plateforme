"""R-4b-2a: ``fund-runtime replay`` (ADR-040).

Claims under test:

* the command refuses itself (exit 2, nothing contacted) for a cassette that is not a completed
  run (or is version 1), specs in the cassette that are not the recording's minds, a spec that
  carries a model, and every usage error ``backtest`` has; it takes no ``--steps`` and (M-002)
  no ``--specs``, ``--input``, ``--days-per-step`` or ``--max-tool-calls``: the cassette holds
  the count, the specs and the run's parameters;
* a recorded scripted run, replayed into a fresh database of the same world, ends ``completed``
  at zero usage, declares ``cassette`` before any firm act, and leaves a ledger that
  ``compare-ledgers`` finds equal to the recorded one but for the declaration;
* the replay is not blind to a tampered cassette or another world: another world, another
  workflow input, another days-per-step in the cassette each end ``diverged`` (exit 1).

Two databases in one test: each is built like the operator's (start-backtest, admin, runtime,
a pod) and held in memory; ledgers are written to files in raw text for ``compare``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Agent, AgentRole, Event
from app.ledger.compare import compare, ledger_rows
from app.marketdata import SyntheticProvider, set_provider
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent, seed_runtime_agent
from app.run_clock import start_backtest
from runtime import cassette, cli
from runtime.providers import Usage
from runtime.spec import AgentSpec
from tests.cassette_parts import PARTS
from tests.support import world_key
from tests.test_cassette_replay import _outcome_of, _wake_json
from tests.test_phase3_probe import CAPITAL, START, SYMBOLS, _fresh_database
from tests.test_runtime_lockstep import _app, gov, live_afterwards  # noqa: F401 - fixtures

REPO = Path(__file__).resolve().parent.parent
DESK = REPO / "specs" / "desk-month"
STEPS = 4


@pytest.fixture(autouse=True)
def _no_monitor(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings().oms, "pending_monitor_enabled", False)
    yield
    set_provider(None)


class Desk:
    """A fresh backtest database set up the way the smoke run's operator does, in a world."""

    def __init__(self, world: int) -> None:
        _, self.Sessions = _fresh_database()
        set_provider(SyntheticProvider(world_key(world), SYMBOLS))
        with self.Sessions() as s:
            start_backtest(s, start=START)
            _, self.registrar = register_agent(s, name="management", role=AgentRole.management)
            _, self.clock = seed_runtime_agent(s)
            pod = create_pod(s, name="desk-1")
            fund_pod(s, pod_id=pod.id, delta=CAPITAL, actor=get_or_create_system_agent(s),
                     reason="pod capital")
            s.commit()
        from app.clock import LiveClock, set_clock
        set_clock(LiveClock())  # the server's lifespan installs the run's clock itself

    def run(self, argv: list[str], monkeypatch, capsys, transport=None) -> tuple[int, dict | None, str]:
        monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, self.registrar)
        monkeypatch.setenv(cli.CLOCK_KEY_ENV, self.clock)
        app = _app(self.Sessions)
        with TestClient(app):
            code = cli.main(argv, transport=transport or httpx.ASGITransport(app=app))
        out, err = capsys.readouterr()
        return code, (json.loads(out) if out.strip() else None), err

    def events(self) -> list[tuple]:
        with self.Sessions() as s:
            return [(e.id, e.ts.isoformat(), e.actor_agent_id, e.type, e.payload_json)
                    for e in s.execute(select(Event).order_by(Event.id)).scalars()]

    def to_file(self, path: Path) -> Path:
        """The ledger in a file, payloads as raw text, the way the operator's database holds them."""
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE events (id INTEGER, ts TEXT, actor_agent_id INTEGER, "
                    "type TEXT, payload_json TEXT)")
        con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                        [(i, ts, a, t, json.dumps(p, sort_keys=True)) for i, ts, a, t, p in self.events()])
        con.commit()
        con.close()
        return path


@pytest.fixture
def input_file(tmp_path: Path) -> Path:
    path = tmp_path / "input.json"
    path.write_text((DESK / "input.json").read_text())
    return path


def _record(tmp_path: Path, input_file: Path, monkeypatch, capsys, world: int = 11) -> tuple[Desk, dict, Path]:
    desk = Desk(world)
    path = tmp_path / "month.cassette.json"
    code, out, _ = desk.run(["backtest", "--specs", str(DESK), "--input", str(input_file),
                             "--steps", str(STEPS), "--cassette", str(path)], monkeypatch, capsys)
    assert code == 0 and out["ended"] == "completed"
    return desk, out, path


def _replay(desk: Desk, path: Path, monkeypatch, capsys, *extra: str):
    """``fund-runtime replay`` from the cassette alone (M-002): no other input exists."""
    return desk.run(["replay", "--cassette", str(path), *extra], monkeypatch, capsys)


def _forge(dest: Path, doc: dict) -> Path:
    """A canonical-looking file for ``doc``, written without the writer's checks."""
    dest.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="ascii")
    return dest


def _tampered(path: Path, dest: Path, **parameters) -> Path:
    """``path``'s cassette with some run parameters changed (specs and tapes untouched)."""
    doc = json.loads(path.read_text(encoding="ascii"))
    doc["parameters"].update(parameters)
    return _forge(dest, doc)


# --- a replay -------------------------------------------------------------------------------

def test_replay_cli_replays_the_recorded_run(tmp_path, input_file, monkeypatch, capsys) -> None:
    recorded, rec_out, path = _record(tmp_path, input_file, monkeypatch, capsys)
    fresh = Desk(11)
    code, out, err = _replay(fresh, path, monkeypatch, capsys)
    assert code == 0 and (out["ended"], out["reason"]) == ("completed", "completed"), (out, err)
    assert out["run"]["minds"] == "cassette" and len(out["run"]["steps"]) == STEPS
    wakes = [w for st in out["run"]["steps"] for w in st["wakes"]]
    assert len(wakes) == 2 * STEPS
    assert all(e["usage"] == Usage().model_dump(mode="json") for w in wakes for e in w["exchanges"])
    printed = json.dumps(out) + err  # `Desk.run` already read stdout: check what it parsed
    assert re.findall(r"fk_[A-Za-z0-9_-]{20,}", printed) == []
    assert fresh.registrar not in printed and fresh.clock not in printed
    # Same transcripts as the recorded run's.
    assert [w["transcript"] for st in out["run"]["steps"] for w in st["wakes"]] == [
        w["transcript"] for st in rec_out["run"]["steps"] for w in st["wakes"]]
    result = compare(ledger_rows(recorded.to_file(tmp_path / "a.db")),
                     ledger_rows(fresh.to_file(tmp_path / "b.db")))
    assert (result.equal, result.allowed, result.first_difference) == (True, 1, None), result


def test_replay_cli_declares_cassette_before_any_firm_act(tmp_path, input_file, monkeypatch, capsys) -> None:
    _, _, path = _record(tmp_path, input_file, monkeypatch, capsys)
    fresh = Desk(11)
    assert _replay(fresh, path, monkeypatch, capsys)[0] == 0
    events = fresh.events()
    (declared,) = [e for e in events if e[3] == "run_minds_declared"]
    assert declared[4] == {"minds": ["cassette"]}
    # The first event of any agent that is not physics' own or the Runtime's, over ALL events
    # (as the smoke run's `minds_check` reads it): none may precede the declaration.
    with fresh.Sessions() as s:
        roles = {a.id: a.role.value for a in s.execute(select(Agent)).scalars()}
    firm = [e[0] for e in events if e[2] is not None and roles[e[2]] not in {"system", "runtime"}]
    assert firm and min(firm) > declared[0], (declared[0], min(firm))


def test_replay_cli_in_another_world_exits_1_diverged(tmp_path, input_file, monkeypatch, capsys) -> None:
    recorded, _, path = _record(tmp_path, input_file, monkeypatch, capsys, world=11)
    other = Desk(12)
    code, out, _ = _replay(other, path, monkeypatch, capsys)
    assert code == 1 and out["ended"] == "diverged" and out["reason"].endswith(":world"), out["reason"]
    result = compare(ledger_rows(recorded.to_file(tmp_path / "a.db")),
                     ledger_rows(other.to_file(tmp_path / "b.db")))
    assert result.equal is False and result.first_difference is not None


def test_replay_takes_specs_and_parameters_from_the_cassette(
        tmp_path, input_file, monkeypatch, capsys) -> None:
    """One file is enough: the recorded parameters and specs are in it, and the replay used them."""
    _, _, path = _record(tmp_path, input_file, monkeypatch, capsys)
    doc = json.loads(path.read_text(encoding="ascii"))
    assert doc["parameters"] == {"days_per_step": 1, "max_tool_calls": 64, "steps": STEPS,
                                 "workflow_input": json.loads(input_file.read_text())}
    assert [e["spec"]["id"] for e in doc["specs"]] == ["a-analyst", "b-pm"]
    monkeypatch.chdir(tmp_path)  # nowhere near specs/
    code, out, err = _replay(Desk(11), path, monkeypatch, capsys)
    assert code == 0 and out["ended"] == "completed", (out, err)


def test_tampered_input_diverges_world_at_turn_0(tmp_path, input_file, monkeypatch, capsys) -> None:
    """The old flag-mismatch test, restated as cassette tampering: the minds see another input."""
    _, _, path = _record(tmp_path, input_file, monkeypatch, capsys)
    other = _tampered(path, tmp_path / "other.cassette.json", workflow_input={"universe": ["SYNA"]})
    code, out, _ = _replay(Desk(11), other, monkeypatch, capsys)
    assert code == 1 and out["reason"] == "diverged:a-analyst:0:0:world", out["reason"]


def test_tampered_days_per_step_diverges_calendar(
        tmp_path, input_file, monkeypatch, capsys) -> None:
    _, _, path = _record(tmp_path, input_file, monkeypatch, capsys)
    other = _tampered(path, tmp_path / "other.cassette.json", days_per_step=2)
    code, out, _ = _replay(Desk(11), other, monkeypatch, capsys)
    assert code == 1 and out["reason"] == "diverged:clock:0:0:calendar_landed", out["reason"]


@pytest.mark.parametrize("flag, value", [
    ("--steps", "5"), ("--specs", str(DESK)), ("--input", "input.json"),
    ("--days-per-step", "2"), ("--max-tool-calls", "8")])
def test_removed_flags_are_usage_errors(flag, value, tmp_path, monkeypatch, capsys) -> None:
    """The cassette holds the count, the specs and every parameter: no flag can contradict it."""
    with pytest.raises(SystemExit) as exit_:
        cli.main(["replay", "--cassette", str(tmp_path / "x.cassette.json"), flag, value])
    assert exit_.value.code == 2


# --- the command refuses itself --------------------------------------------------------------

class Recorder(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        return httpx.Response(500)


def _desk_specs(*ids: str, **fields) -> list[dict]:
    """The desk's spec bodies as a cassette carries them (``AgentSpec.model_dump(mode="json")``)."""
    return [AgentSpec.model_validate(yaml.safe_load((DESK / f"{id}.yaml").read_text()) | fields)
            .model_dump(mode="json") for id in ids]


def _good_cassette(tmp_path: Path, name: str = "good", *, outcome: dict | None = None,
                   specs: list[dict] | None = None, **over) -> Path:
    if outcome is None:
        outcome = _outcome_of(_wake_json("a-analyst"), _wake_json("b-pm"), **over)
        outcome["run"]["steps"][0]["advanced_to"] = "2024-01-03T14:30:00Z"
    path = tmp_path / f"{name}.cassette.json"
    cassette.write(path, outcome, parameters=PARTS["parameters"],
                   specs=specs if specs is not None else _desk_specs("a-analyst", "b-pm"))
    return path


def test_the_usage_cases_start_from_a_command_that_passes(tmp_path, monkeypatch, capsys) -> None:
    """Control for the cases below: a good cassette, the desk specs and good keys get past every
    usage check and reach the server (here a stub that answers 500: the run is refused, exit 1).
    Without this, a bad fixture would make every case below pass by failing at the cassette."""
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, "fk_registrar-key-0000")
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, "fk_clock-key-0000")
    transport = Recorder()
    code = cli.main(["replay", "--cassette", str(_good_cassette(tmp_path))], transport=transport)
    capsys.readouterr()
    assert code == 1 and transport.requests > 0


CASES = ["missing", "pretty", "refused_run", "diverged_run", "halted_run", "extra_spec",
         "missing_spec", "model_spec", "no_registrar_key", "equal_keys", "remote_server",
         "zero_days", "huge_tool_budget", "bad_input", "no_specs", "v1", "spec_edited",
         "steps_disagree"]


@pytest.mark.parametrize("case", CASES)
def test_replay_usage_errors_exit_2_and_contact_nothing(case, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, "fk_registrar-key-0000")
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, "fk_clock-key-0000")
    cass, extra = _good_cassette(tmp_path), []
    doc = json.loads(cass.read_text())
    both = ("a-analyst", "b-pm")
    if case == "missing":
        cass = tmp_path / "missing.cassette.json"
    elif case == "pretty":
        pretty = tmp_path / "pretty.cassette.json"
        pretty.write_text(json.dumps(doc, indent=2))
        cass = pretty
    elif case == "refused_run":
        path = tmp_path / "refused.cassette.json"
        cassette.write(path, {"ended": "refused", "reason": "provision:x", "registered": [], "run": None},
                       parameters=PARTS["parameters"], specs=_desk_specs(*both))
        cass = path
    elif case in {"diverged_run", "halted_run"}:
        cass = _good_cassette(tmp_path, "ended", outcome=_outcome_of(
            _wake_json("a-analyst"), _wake_json("b-pm"), ended=case.split("_")[0]))
    elif case == "extra_spec":
        third = _desk_specs("b-pm")[0] | {"id": "c-pm", "name": "desk-1-pm-2"}
        cass = _good_cassette(tmp_path, "extra", specs=[*_desk_specs(*both), third])
    elif case == "missing_spec":
        cass = _good_cassette(tmp_path, "missing-spec", specs=_desk_specs("a-analyst"))
    elif case == "model_spec":
        cass = _good_cassette(tmp_path, "model", specs=_desk_specs(*both, model="some-model"))
    elif case == "no_registrar_key":
        monkeypatch.delenv(cli.REGISTRAR_KEY_ENV)
    elif case == "equal_keys":
        monkeypatch.setenv(cli.CLOCK_KEY_ENV, "fk_registrar-key-0000")
    elif case == "remote_server":
        extra = ["--server", "http://example.com:8000"]
    elif case in {"zero_days", "huge_tool_budget", "bad_input"}:
        field, value = {"zero_days": ("days_per_step", 0),
                        "huge_tool_budget": ("max_tool_calls", cli.MAX_TOOL_CALLS + 1),
                        "bad_input": ("workflow_input", [1])}[case]
        cass = _tampered(cass, tmp_path / "bad.cassette.json", **{field: value})
    elif case == "no_specs":
        cass = _good_cassette(tmp_path, "empty", specs=[])
    elif case == "v1":
        cass = _forge(tmp_path / "v1.cassette.json", {
            "cassette_version": 1, "hash_format": cassette.HASH_FORMAT, "outcome": doc["outcome"],
            "redactions": 0})
    elif case == "spec_edited":  # a spec changed without its digest
        doc["specs"][0]["spec"]["charter"] = "Do something else."
        cass = _forge(tmp_path / "edited.cassette.json", doc)
    elif case == "steps_disagree":  # the parameters contradict the recording
        cass = _tampered(cass, tmp_path / "steps.cassette.json", steps=7)
    transport = Recorder()
    code = cli.main(["replay", "--cassette", str(cass), *extra], transport=transport)
    out, err = capsys.readouterr()
    assert code == 2 and out == "" and err.startswith("fund-runtime:"), (case, err)
    assert transport.requests == 0
