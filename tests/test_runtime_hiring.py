"""Onboarding.exe (idea: a dead pod is replaced): ``fund-runtime backtest --hire`` fills the
vacancies the risk ladder opens, mid-run, under the cap, and the recording replays the hires.

A vacancy is staged in the ledger before the run (the close itself is physics', tested in
``tests/test_hiring.py`` and proven on a made-up market in ``acceptance/pod_replacement.py``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.capital.allocation import PodTrack
from app.clock import LiveClock, set_clock
from app.db.base import Base
from app.capital.hiring import open_vacancy
from app.config import HiringConfig, get_settings
from app.db.models import Agent, AgentRole, Event, Pod
from app.ledger.events import EVENT_CAPITAL_SEEDED, EVENT_PITCH_SUBMITTED, append_event
from app.registry.pods import create_pod
from app.registry.service import get_or_create_system_agent, register_agent, seed_runtime_agent
from app.run_clock import install_run_clock, start_backtest
from runtime import cli
from runtime.replay import HireRecord, Recording, RecordingError
from tests.test_runtime_cli_backtest import _write_specs
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    START,
    _app,
    gov,
    live_afterwards,
    woke,
    world,
)

RULE = {"language": "strategy-v1", "signal": "momentum", "universe": ["SYNA", "SYNB"],
        "lookback": 20, "rebalance_every": 5, "top_n": 1, "side": "long_only", "gross": 1.0}


def _stage_vacancy(SessionFactory, pod_id: int = 1) -> int:
    s = SessionFactory()
    try:
        install_run_clock(s)
        system = get_or_create_system_agent(s)
        pitch = append_event(s, type=EVENT_PITCH_SUBMITTED, actor_agent_id=system.id,
                             payload={"pod_id": pod_id, "hypothesis": "h", "rule": RULE})
        append_event(s, type=EVENT_CAPITAL_SEEDED, actor_agent_id=system.id, payload={
            "pod_id": pod_id, "pitch_id": pitch.id, "seed_usd": 1.0, "rule": RULE,
            "cost_at_seed_usd": 0.0})
        s.get(Pod, pod_id).status = "closed"
        record = PodTrack(pod_id=pod_id, seeded=pitch.id, stage="closed", equity=0.0,
                          days=("2024-01-02",), returns=(-0.11,), cost_usd=0.0, drawdown=0.11)
        vid = open_vacancy(s, pod_id=pod_id, record=record, actor=system).id
        s.commit()
        return vid
    finally:
        s.close()
        set_clock(LiveClock())  # the server's lifespan installs the run's clock itself


@pytest.fixture
def keys(world, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, world["admin"])
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, world["clock"])
    return world


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    return _write_specs(tmp_path / "specs", {
        "id": "a-pm", "name": "desk-2-pm", "role": "pm", "pod": 2, "provider": "scripted",
        "script": "read-a", "charter": "Read the clock."})


def _template(tmp_path: Path, **fields) -> Path:
    path = tmp_path / "hire.yaml"
    path.write_text(yaml.safe_dump({"provider": "scripted", "script": "read-c", **fields}))
    return path


def _run(SessionFactory, argv: list[str], capsys, command: str = "backtest"):
    app = _app(SessionFactory)
    with TestClient(app):
        code = cli.main([command, *argv], transport=httpx.ASGITransport(app=app))
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


def test_a_vacancy_is_filled_the_next_morning_and_the_new_pm_wakes_with_its_post_mortem(
        SessionFactory, keys, specs, woke, tmp_path, capsys):
    vid = _stage_vacancy(SessionFactory)
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2", "--hire",
                                           str(_template(tmp_path))], capsys)
    assert code == 0, (out or {}).get("reason")
    run = out["run"]
    assert [(h["step"], h["vacancy_id"], h["spec_id"], h["outcome"]) for h in run["hires"]] == [
        (0, vid, "hire-1", "hired")]
    assert out["registered"] == ["a-pm", "hire-1"]
    assert [[w["spec_id"] for w in st["wakes"]] for st in run["steps"]] == [["a-pm", "hire-1"]] * 2
    assert woke == ["a", "c"] * 2
    context = json.loads(run["steps"][0]["wakes"][1]["transcript"][1]["content"])
    assert context["input"]["post_mortem"]["pod_id"] == 1 and context["input"]["vacancy_id"] == vid
    assert context["me"]["name"] == "hire-1-pm"
    hired = dict(run["agents"])["hire-1"]
    with SessionFactory() as s:
        agent = s.get(Agent, hired)
        assert (agent.name, agent.charter_ref) == ("hire-1-pm", f"vacancy:{vid}")
        assert s.get(Pod, agent.pod_id).name == "hire-1"
    # the next mornings see a filled vacancy: one hire, not one per day
    assert len(run["hires"]) == 1


def test_a_budget_that_does_not_fit_the_cap_is_refused_in_the_ledger(
        SessionFactory, keys, specs, woke, tmp_path, capsys, gov):
    (gov / "human.yaml").write_text(   # < the $0.30 hire
        "firm:\n  monthly_llm_usd_cap: 0.25\n  max_agents_total: 200\n")
    vid = _stage_vacancy(SessionFactory)
    code, out, err = _run(SessionFactory, [
        "--specs", str(specs), "--steps", "2",
        "--hire", str(_template(tmp_path, provider="fake-metered"))], capsys)
    assert code == 0, err
    assert [(h["step"], h["outcome"]) for h in out["run"]["hires"]] == [
        (0, "refused:budget_over_cap"), (1, "refused:budget_over_cap")]
    assert "does not fit the monthly cap" in out["run"]["hires"][0]["reason"]
    with SessionFactory() as s:
        refused = [e.payload_json for e in s.scalars(select(Event).where(
            Event.type == "hire_refused"))]
        assert [r["vacancy_id"] for r in refused] == [vid, vid]
        assert s.scalar(select(Agent).where(Agent.name == "hire-1-pm")) is None
    assert out["registered"] == ["a-pm"] and "metering" in out


def test_a_metered_hire_gets_its_own_key_inside_the_cap(SessionFactory, keys, specs, woke,
                                                        tmp_path, capsys, gov):
    (gov / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: 1\n  max_agents_total: 200\n")
    _stage_vacancy(SessionFactory)
    code, out, err = _run(SessionFactory, [
        "--specs", str(specs), "--steps", "1",
        "--hire", str(_template(tmp_path, provider="fake-metered"))], capsys)
    assert code == 0, err
    keys_ = {k["spec_id"]: k for k in out["metering"]["keys"]}
    assert keys_["hire-1"]["limit_usd_micros"] == 300_000
    assert keys_["hire-1"]["agent_id"] == dict(out["run"]["agents"])["hire-1"]


def test_physics_refusal_is_recorded_and_the_run_goes_on(SessionFactory, keys, specs, woke,
                                                         tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(get_settings(), "hiring", HiringConfig(max_live_pods=1))
    vid = _stage_vacancy(SessionFactory)   # the law, frozen here: one live pod; two are live
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1", "--hire",
                                         str(_template(tmp_path))], capsys)
    assert code == 0
    assert [(h["vacancy_id"], h["spec_id"], h["outcome"]) for h in out["run"]["hires"]] == [
        (vid, "hire-1", "refused:physics:409")]


def test_a_squatted_name_gives_the_hire_the_next_one(SessionFactory, keys, specs, woke,
                                                     tmp_path, capsys):
    _stage_vacancy(SessionFactory)
    with SessionFactory() as s:      # the operator took the name the law gives the new pod
        s.add(Pod(name="hire-1", created_at=s.get(Pod, 1).created_at))
        s.commit()
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1", "--hire",
                                         str(_template(tmp_path))], capsys)
    assert code == 0
    assert [(h["spec_id"], h["outcome"]) for h in out["run"]["hires"]] == [("hire-1-2", "hired")]
    assert out["registered"] == ["a-pm", "hire-1-2"]


def test_a_runs_own_mind_may_not_wear_a_hire_id(SessionFactory, keys, tmp_path, woke, capsys):
    specs = _write_specs(tmp_path / "specs", {
        "id": "hire-1", "name": "desk-2-pm", "role": "pm", "pod": 2, "provider": "scripted",
        "script": "read-a", "charter": "Read the clock."})
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1", "--hire",
                                         str(_template(tmp_path))], capsys)
    assert code == 1 and out["reason"] == "provision:hire_prefix:hire-1"


def test_the_hire_is_recorded_and_replays(SessionFactory, keys, specs, woke, tmp_path, capsys,
                                          engine):
    _stage_vacancy(SessionFactory)
    tape = tmp_path / "run.cassette.json"
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "2", "--hire",
                                           str(_template(tmp_path)), "--cassette", str(tape)],
                          capsys)
    assert code == 0, err
    doc = json.loads(tape.read_text())
    assert doc["parameters"]["hiring"]["provider"] == "scripted"
    rec = Recording.load(tape)
    assert rec.hired_ids == {"hire-1"} and rec.spec_ids == {"a-pm", "hire-1"}
    # the same world again, set up as the recorded one was: the replay hires the same PM
    _reset(engine, SessionFactory)
    vid = _stage_vacancy(SessionFactory)
    code, out, err = _run(SessionFactory, ["--cassette", str(tape)], capsys, command="replay")
    assert code == 0, err
    assert [(h["vacancy_id"], h["outcome"]) for h in out["run"]["hires"]] == [(vid, "hired")]
    assert out["run"]["minds"] == "cassette"


def test_a_replay_whose_world_opens_no_vacancy_diverges_at_the_hire(
        SessionFactory, keys, specs, woke, tmp_path, capsys, engine):
    _stage_vacancy(SessionFactory)
    tape = tmp_path / "run.cassette.json"
    assert _run(SessionFactory, ["--specs", str(specs), "--steps", "1", "--hire",
                                 str(_template(tmp_path)), "--cassette", str(tape)],
                capsys)[0] == 0
    _reset(engine, SessionFactory)    # no vacancy this time
    code, out, _ = _run(SessionFactory, ["--cassette", str(tape)], capsys, command="replay")
    assert code == 1 and out["reason"] == "diverged:hire:0:0:hire"


def test_a_recorded_hire_record_is_data():
    with pytest.raises(RecordingError):
        HireRecord(0, 1, "hire-1", "hired")                   # a hire names its agent
    with pytest.raises(RecordingError):
        HireRecord(0, 1, "pm-1", "hired", 4)                  # only a hire id
    with pytest.raises(RecordingError):
        HireRecord(0, 1, "hire-1", "refused:budget_over_cap", 4, "x")
    assert HireRecord(0, 1, "hire-1", "refused:key_over_cap", 4).agent_id == 4


def _reset(engine, SessionFactory) -> None:
    """A fresh world as the ``world`` fixture builds it, in the same database; its keys in the
    environment (the replay registers its minds afresh)."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionFactory()
    try:
        start_backtest(s, start=START)
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        for n in (1, 2, 3):
            pod = create_pod(s, name=f"desk-{n}")
            register_agent(s, name=f"pm-{n}", role=AgentRole.pm, pod_id=pod.id)
        _, clock = seed_runtime_agent(s)
        s.commit()
    finally:
        s.close()
    set_clock(LiveClock())
    os.environ[cli.REGISTRAR_KEY_ENV] = admin
    os.environ[cli.CLOCK_KEY_ENV] = clock


def test_a_key_the_month_cannot_hold_deactivates_the_hire_and_is_not_retried(
        SessionFactory, keys, specs, woke, tmp_path, capsys, gov, monkeypatch):
    from runtime.metering import FakeProvisioner
    from runtime.openrouter import OverCap

    (gov / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: 1\n  max_agents_total: 200\n")

    def full(self, agent_id, limit):
        raise OverCap("another run holds the month")
    monkeypatch.setattr(FakeProvisioner, "create_key", full)
    vid = _stage_vacancy(SessionFactory)
    code, out, err = _run(SessionFactory, [
        "--specs", str(specs), "--steps", "2",
        "--hire", str(_template(tmp_path, provider="fake-metered"))], capsys)
    assert code == 0, err
    hires = out["run"]["hires"]
    assert [(h["step"], h["outcome"]) for h in hires] == [
        (0, "refused:key_over_cap"), (1, "refused:no_key_room")]
    with SessionFactory() as s:
        agent = s.get(Agent, hires[0]["agent_id"])
        assert agent.status.value == "inactive"
        assert s.get(Pod, agent.pod_id).status == "closed"           # the failed hire's pod
        failed = [e.payload_json for e in s.scalars(select(Event).where(
            Event.type == "hire_failed"))]
        assert [f["vacancy_id"] for f in failed] == [vid]
    assert out["registered"] == ["a-pm"]


def test_a_hire_that_fits_the_cap_alone_but_not_with_the_runs_keys_is_refused(
        SessionFactory, keys, tmp_path, woke, capsys, gov):
    (gov / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: 1\n  max_agents_total: 200\n")
    metered = _write_specs(tmp_path / "metered", {
        "id": "a-pm", "name": "desk-2-pm", "role": "pm", "pod": 2, "provider": "fake-metered",
        "script": "read-a", "budget_usd": 0.8, "charter": "Read the clock."})
    vid = _stage_vacancy(SessionFactory)
    code, out, err = _run(SessionFactory, [
        "--specs", str(metered), "--steps", "1",
        "--hire", str(_template(tmp_path, provider="fake-metered"))], capsys)   # $0.30 alone fits
    assert code == 0, err
    assert [(h["vacancy_id"], h["outcome"]) for h in out["run"]["hires"]] == [
        (vid, "refused:budget_over_cap")]
    assert [k["spec_id"] for k in out["metering"]["keys"]] == ["a-pm"]     # no key for the hire
    with SessionFactory() as s:
        assert not s.scalars(select(Agent).where(Agent.name.like("hire-%"))).all()
