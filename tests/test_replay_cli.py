"""R-4b-2a: ``fund-runtime replay`` (ADR-040).

Claims under test:

* the command refuses itself (exit 2, nothing contacted) for a cassette that is not a completed
  run, specs that are not the recording's minds, a spec that carries a model, and every usage
  error ``backtest`` has; it takes no ``--steps`` (the recording holds the count);
* a recorded scripted run, replayed into a fresh database of the same world, ends ``completed``
  at zero usage, declares ``cassette`` before any firm act, and leaves a ledger that
  ``compare-ledgers`` finds equal to the recorded one but for the declaration;
* the replay is not blind to what the v1 cassette does not store: another world, another
  workflow input, another days-per-step each end ``diverged`` (exit 1) with an unequal ledger.

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


def _replay(desk: Desk, path: Path, input_file: Path | None, monkeypatch, capsys, *extra: str):
    argv = ["replay", "--cassette", str(path), "--specs", str(DESK), *extra]
    if input_file is not None:
        argv += ["--input", str(input_file)]
    return desk.run(argv, monkeypatch, capsys)


# --- a replay -------------------------------------------------------------------------------

def test_replay_cli_replays_the_recorded_run(tmp_path, input_file, monkeypatch, capsys) -> None:
    recorded, rec_out, path = _record(tmp_path, input_file, monkeypatch, capsys)
    fresh = Desk(11)
    code, out, err = _replay(fresh, path, input_file, monkeypatch, capsys)
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
    assert _replay(fresh, path, input_file, monkeypatch, capsys)[0] == 0
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
    code, out, _ = _replay(other, path, input_file, monkeypatch, capsys)
    assert code == 1 and out["ended"] == "diverged" and out["reason"].endswith(":world"), out["reason"]
    result = compare(ledger_rows(recorded.to_file(tmp_path / "a.db")),
                     ledger_rows(other.to_file(tmp_path / "b.db")))
    assert result.equal is False and result.first_difference is not None


def test_replay_cli_with_another_input_diverges_at_turn_0(tmp_path, input_file, monkeypatch, capsys) -> None:
    """Counter-example to "v1 does not store the input, so it is not checked"."""
    _, _, path = _record(tmp_path, input_file, monkeypatch, capsys)
    other_input = tmp_path / "other.json"
    other_input.write_text(json.dumps({"universe": ["SYNA"]}))
    code, out, _ = _replay(Desk(11), path, other_input, monkeypatch, capsys)
    assert code == 1 and out["reason"] == "diverged:a-analyst:0:0:world", out["reason"]


def test_replay_cli_with_another_days_per_step_diverges_on_the_calendar(
        tmp_path, input_file, monkeypatch, capsys) -> None:
    _, _, path = _record(tmp_path, input_file, monkeypatch, capsys)
    code, out, _ = _replay(Desk(11), path, input_file, monkeypatch, capsys, "--days-per-step", "2")
    assert code == 1 and out["reason"] == "diverged:clock:0:0:calendar_landed", out["reason"]


def test_replay_takes_no_steps_flag(tmp_path, monkeypatch, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["replay", "--cassette", str(tmp_path / "x.cassette.json"), "--specs", str(DESK),
                  "--steps", "5"])
    assert exit_.value.code == 2


# --- the command refuses itself --------------------------------------------------------------

class Recorder(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        return httpx.Response(500)


def _good_cassette(tmp_path: Path, **over) -> Path:
    outcome = _outcome_of(_wake_json("a-analyst"), _wake_json("b-pm"), **over)
    outcome["run"]["steps"][0]["advanced_to"] = "2024-01-03T14:30:00Z"
    path = tmp_path / "good.cassette.json"
    cassette.write(path, outcome)
    return path


def _specs_dir(tmp_path: Path, *ids: str, **fields) -> Path:
    directory = tmp_path / "specs"
    directory.mkdir()
    for id in ids:
        spec = yaml.safe_load((DESK / f"{id}.yaml").read_text()) | fields
        (directory / f"{id}.yaml").write_text(yaml.safe_dump(spec))
    return directory


def test_the_usage_cases_start_from_a_command_that_passes(tmp_path, monkeypatch, capsys) -> None:
    """Control for the cases below: a good cassette, the desk specs and good keys get past every
    usage check and reach the server (here a stub that answers 500: the run is refused, exit 1).
    Without this, a bad fixture would make every case below pass by failing at the cassette."""
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, "fk_registrar-key-0000")
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, "fk_clock-key-0000")
    transport = Recorder()
    code = cli.main(["replay", "--cassette", str(_good_cassette(tmp_path)), "--specs", str(DESK)],
                    transport=transport)
    capsys.readouterr()
    assert code == 1 and transport.requests > 0


CASES = ["missing","pretty", "refused_run", "diverged_run", "halted_run", "extra_spec",
         "missing_spec", "model_spec", "no_registrar_key", "equal_keys", "remote_server",
         "zero_days", "huge_tool_budget", "bad_input", "no_specs"]


@pytest.mark.parametrize("case", CASES)
def test_replay_usage_errors_exit_2_and_contact_nothing(case, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, "fk_registrar-key-0000")
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, "fk_clock-key-0000")
    cass, specs, extra = _good_cassette(tmp_path), DESK, []
    if case == "missing":
        cass = tmp_path / "missing.cassette.json"
    elif case == "pretty":
        pretty = tmp_path / "pretty.cassette.json"
        pretty.write_text(json.dumps(json.loads(cass.read_text()), indent=2))
        cass = pretty
    elif case == "refused_run":
        path = tmp_path / "refused.cassette.json"
        cassette.write(path, {"ended": "refused", "reason": "provision:x", "registered": [], "run": None})
        cass = path
    elif case in {"diverged_run", "halted_run"}:
        path = tmp_path / "ended.cassette.json"
        cassette.write(path, _outcome_of(_wake_json("a-analyst"), _wake_json("b-pm"),
                                         ended=case.split("_")[0]))
        cass = path
    elif case == "extra_spec":
        specs = _specs_dir(tmp_path, "a-analyst", "b-pm")
        (specs / "c-pm.yaml").write_text((specs / "b-pm.yaml").read_text().replace("b-pm", "c-pm")
                                         .replace("desk-1-pm", "desk-1-pm-2"))
    elif case == "missing_spec":
        specs = _specs_dir(tmp_path, "a-analyst")
    elif case == "model_spec":
        specs = _specs_dir(tmp_path, "a-analyst", "b-pm", model="some-model")
    elif case == "no_registrar_key":
        monkeypatch.delenv(cli.REGISTRAR_KEY_ENV)
    elif case == "equal_keys":
        monkeypatch.setenv(cli.CLOCK_KEY_ENV, "fk_registrar-key-0000")
    elif case == "remote_server":
        extra = ["--server", "http://example.com:8000"]
    elif case == "zero_days":
        extra = ["--days-per-step", "0"]
    elif case == "huge_tool_budget":
        extra = [f"--max-tool-calls", str(cli.MAX_TOOL_CALLS + 1)]
    elif case == "bad_input":
        bad = tmp_path / "bad.json"
        bad.write_text("[1]")
        extra = ["--input", str(bad)]
    elif case == "no_specs":
        specs = tmp_path / "empty"
        specs.mkdir()
    transport = Recorder()
    code = cli.main(["replay", "--cassette", str(cass), "--specs", str(specs), *extra],
                    transport=transport)
    out, err = capsys.readouterr()
    assert code == 2 and out == "" and err.startswith("fund-runtime:"), (case, err)
    assert transport.requests == 0
