"""R-3b-1: the lockstep conductor (ADR-032 (5), ADR-033).

Claims under test:

* every step wakes every mind **once, one at a time, in spec-id order**, then the
  clock moves one step **by the runtime identity's hand**, ``steps`` times;
* HALT before a step, inside a wake, or after the last wake of a step ends the
  run ``halted`` and the clock does not move again;
* a refused wake ends the run ``refused`` with no advance; a crashing mind is
  recorded and the run goes on;
* the conductor refuses, before anything wakes, a clock key that is not the
  runtime identity, a live run, an unreadable clock, and duplicate spec ids;
  ``steps`` and ``days_per_step`` are plain ints in range;
* a clock that will not advance ends the run ``error`` with the status.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.db.base import get_session
from app.db.models import AgentRole, Event
from app.ledger.events import EVENT_CLOCK_ADVANCED
from app.main import create_app
from app.registry.pods import create_pod
from app.registry.service import register_agent, seed_runtime_agent
from app.run_clock import start_backtest
from mcp_server import FundClient
from runtime import governance, lockstep, scripted
from runtime.lockstep import Mind, run_backtest
from runtime.providers import CompletionResponse, ToolCall
from runtime.spec import AgentSpec

START = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def gov(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "governance"
    d.mkdir()
    monkeypatch.setattr(governance, "HALT_FILE", d / "HALT")
    monkeypatch.setattr(governance, "HUMAN_YAML", d / "human.yaml")
    (d / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: null\n")
    return d


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


@pytest.fixture
def woke(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Install test scripts. ``woke`` lists every wake, by the script's own label.

    A test script may keep state (it reports to the test); the real scripts may not.
    """
    log: list[str] = []

    def reader(label: str):
        def script(request):
            if not any(m.role == "assistant" for m in request.messages):
                log.append(label)
                return CompletionResponse(content="time?", tool_calls=[
                    ToolCall(id="c", name="get_clock")])
            return CompletionResponse(content="done")
        return script

    def crash(request):
        log.append("crash")
        raise RuntimeError("a mind's bug")

    more = {"read-a": reader("a"), "read-b": reader("b"), "read-c": reader("c"),
            "crash": crash}
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | more))
    return log


def _spec(id: str, pod: int, script: str = "read-a", **fields) -> AgentSpec:
    return AgentSpec(**({"id": id, "name": id, "role": "pm", "pod": pod, "provider": "scripted",
                         "script": script, "charter": "Read the clock."} | fields))


@pytest.fixture
def world(SessionFactory) -> dict:
    """A backtest at START: pods 1–3 with a PM each, management, and the runtime identity."""
    s = SessionFactory()
    try:
        start_backtest(s, start=START)
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        keys = {}
        for n in (1, 2, 3):
            pod = create_pod(s, name=f"desk-{n}")
            _, keys[pod.id] = register_agent(s, name=f"pm-{n}", role=AgentRole.pm, pod_id=pod.id)
        _, clock_key = seed_runtime_agent(s)
        s.commit()
    finally:
        s.close()
    set_clock(LiveClock())  # the server's lifespan installs the run's clock itself
    return {"admin": admin, "pm": keys, "clock": clock_key}


def _app(SessionFactory):
    app = create_app()

    def _session():
        s = SessionFactory()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_session] = _session
    return app


def conduct(SessionFactory, keys_by_spec: list[tuple[AgentSpec, str]], clock_key: str,
            **kwargs) -> lockstep.RunRecord:
    """Run the conductor against the test App over ASGI, the server on the run's clock."""
    app = _app(SessionFactory)

    async def go() -> lockstep.RunRecord:
        transport = httpx.ASGITransport(app=app)

        def client(key: str) -> FundClient:
            return FundClient(base_url="http://fund.test", api_key=key, transport=transport)
        clients = [client(k) for _, k in keys_by_spec]
        clock = client(clock_key)
        try:
            minds = [Mind(spec, c) for (spec, _), c in zip(keys_by_spec, clients)]
            return await run_backtest(minds, clock, **kwargs)
        finally:
            for c in [*clients, clock]:
                await c.aclose()

    with TestClient(app):
        return asyncio.run(go())


def _advances(SessionFactory) -> list[Event]:
    with SessionFactory() as s:
        return list(s.execute(select(Event).where(Event.type == EVENT_CLOCK_ADVANCED)
                              .order_by(Event.id)).scalars())


# --- the lockstep -----------------------------------------------------------------------

def test_every_step_wakes_every_mind_in_id_order_then_advances(SessionFactory, world, woke):
    pm = world["pm"]
    handed = [(_spec("c-pm", 3, "read-c"), pm[3]), (_spec("a-pm", 1, "read-a"), pm[1]),
              (_spec("b-pm", 2, "read-b"), pm[2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=3)
    assert (run.ended, run.reason, run.minds) == ("completed", "completed", "scripted")
    assert woke == ["a", "b", "c"] * 3
    assert [[w.spec_id for w in st.wakes] for st in run.steps] == [["a-pm", "b-pm", "c-pm"]] * 3
    assert all(w.ended == "done" for st in run.steps for w in st.wakes)
    # Each step starts where the last one's advance landed, one day apart.
    ats = [datetime.fromisoformat(st.at.replace("Z", "+00:00")) for st in run.steps]
    assert ats == [START + timedelta(days=i) for i in range(3)]
    assert [st.advanced_to for st in run.steps[:-1]] == [st.at for st in run.steps[1:]]
    advances = _advances(SessionFactory)
    assert len(advances) == 3 and len({e.actor_agent_id for e in advances}) == 1


def test_the_hand_on_the_clock_is_the_runtime_identity(SessionFactory, world, woke):
    conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1])], world["clock"], steps=2)
    with SessionFactory() as s:
        from app.db.models import Agent
        hands = {s.get(Agent, e.actor_agent_id).role for e in _advances(SessionFactory)}
    assert hands == {AgentRole.runtime}


def test_days_per_step_moves_the_clock_that_far(SessionFactory, world, woke):
    run = conduct(SessionFactory, [], world["clock"], steps=2, days_per_step=7)
    assert run.ended == "completed" and run.minds == ""
    [first, second] = _advances(SessionFactory)
    assert first.payload_json["minutes"] == second.payload_json["minutes"] == 7 * 24 * 60


def test_a_world_with_no_minds_still_lives_its_steps(SessionFactory, world, woke):
    run = conduct(SessionFactory, [], world["clock"], steps=4)
    assert run.ended == "completed" and [st.wakes for st in run.steps] == [()] * 4
    assert len(_advances(SessionFactory)) == 4 and woke == []


def test_zero_steps_wakes_nothing_and_moves_nothing(SessionFactory, world, woke):
    run = conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1])], world["clock"], steps=0)
    assert (run.ended, run.steps) == ("completed", ())
    assert woke == [] and _advances(SessionFactory) == []


# --- HALT -------------------------------------------------------------------------------

def test_halt_before_the_run_wakes_nothing(SessionFactory, world, woke, gov):
    (gov / "HALT").write_text("")
    run = conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1])], world["clock"], steps=3)
    assert (run.ended, run.steps) == ("halted", ())
    assert woke == [] and _advances(SessionFactory) == []


def test_halt_inside_a_wake_ends_the_run_without_moving_time(SessionFactory, world, woke,
                                                             gov, monkeypatch):
    calls = {"n": 0}

    def halts_on_day_two(request):
        if not any(m.role == "assistant" for m in request.messages):
            calls["n"] += 1
            if calls["n"] == 2:
                (gov / "HALT").write_text("")  # the Human halts while this mind thinks
            return CompletionResponse(content="", tool_calls=[ToolCall(id="c", name="get_clock")])
        return CompletionResponse(content="done")
    monkeypatch.setattr(scripted, "SCRIPTS",
                        MappingProxyType(dict(scripted.SCRIPTS) | {"halter": halts_on_day_two}))
    handed = [(_spec("a-pm", 1, "halter"), world["pm"][1]), (_spec("b-pm", 2, "read-b"),
                                                            world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=5)
    assert (run.ended, len(run.steps)) == ("halted", 2)
    last = run.steps[-1]
    assert [w.ended for w in last.wakes] == ["halted"] and last.advanced_to is None
    assert woke == ["b"]                    # b woke on day one only
    assert len(_advances(SessionFactory)) == 1


def test_halt_after_the_last_wake_stops_the_advance(SessionFactory, world, gov, monkeypatch):
    def halts_when_done(request):
        (gov / "HALT").write_text("")
        return CompletionResponse(content="done, and the Human halts")
    monkeypatch.setattr(scripted, "SCRIPTS",
                        MappingProxyType(dict(scripted.SCRIPTS) | {"late": halts_when_done}))
    run = conduct(SessionFactory, [(_spec("a-pm", 1, "late"), world["pm"][1])],
                  world["clock"], steps=3)
    assert run.ended == "halted" and [w.ended for w in run.steps[0].wakes] == ["done"]
    assert run.steps[0].advanced_to is None and _advances(SessionFactory) == []


# --- refusals and errors ----------------------------------------------------------------

def test_a_key_that_is_not_its_specs_agent_refuses_the_run_before_step_0(
        SessionFactory, world, woke):
    """pm-1's key under a spec for pod 2. Since red-team 0015 H2 every key is read
    before step 0, so nobody wakes at all (was: a woke once, then the run was refused)."""
    handed = [(_spec("a-pm", 1, "read-a"), world["pm"][1]),
              (_spec("b-pm", 2, "read-b"), world["pm"][1])]
    run = conduct(SessionFactory, handed, world["clock"], steps=3)
    assert (run.ended, run.reason, run.steps) == ("refused", "identity_mismatch:b-pm", ())
    assert woke == [] and _advances(SessionFactory) == []


def test_a_refused_wake_ends_the_run_and_time_stays(SessionFactory, world, woke,
                                                    monkeypatch):
    """A mind the run names is refused mid-run (its script is gone from the table
    after day one: unknown_script). The world does not move on without it."""
    def vanishing(request):
        table = dict(scripted.SCRIPTS)
        del table["vanish"]
        monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(table))
        return CompletionResponse(content="done")
    monkeypatch.setattr(scripted, "SCRIPTS",
                        MappingProxyType(dict(scripted.SCRIPTS) | {"vanish": vanishing}))
    handed = [(_spec("a-pm", 1, "read-a"), world["pm"][1]),
              (_spec("b-pm", 2, "vanish"), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=3)
    assert (run.ended, run.reason) == ("refused", "wake_refused:b-pm:unknown_script")
    assert len(run.steps) == 2 and run.steps[1].advanced_to is None
    assert woke == ["a", "a"] and len(_advances(SessionFactory)) == 1
    assert run.retired == ()


def test_an_unreadable_mind_refuses_the_run(SessionFactory, world, woke):
    run = conduct(SessionFactory, [(_spec("a-pm", 1), "not-a-key")], world["clock"], steps=2)
    assert (run.ended, run.reason, run.steps) == ("refused", "mind_unreadable:a-pm:401", ())
    assert woke == [] and _advances(SessionFactory) == []


def test_a_spending_mind_is_refused_under_a_null_cap(SessionFactory, world, woke):
    spec = _spec("a-pm", 1, provider="metered", script=None)
    run = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=2)
    assert (run.ended, run.reason, run.minds) == ("refused", "wake_refused:a-pm:cap_null",
                                                  "metered")
    assert _advances(SessionFactory) == []


def test_a_crashing_mind_is_recorded_and_the_world_goes_on(SessionFactory, world, woke):
    handed = [(_spec("a-pm", 1, "crash"), world["pm"][1]), (_spec("b-pm", 2, "read-b"),
                                                           world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=2)
    assert run.ended == "completed"
    assert [[(w.ended, w.reason) for w in st.wakes] for st in run.steps] == [
        [("error", "provider_error:RuntimeError"), ("done", "done")]] * 2
    assert len(_advances(SessionFactory)) == 2


@pytest.mark.parametrize("who", ["admin", "pm"])
def test_only_the_runtime_identity_may_hold_the_clock(SessionFactory, world, woke, who):
    key = world["admin"] if who == "admin" else world["pm"][2]
    run = conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1])], key, steps=2)
    assert (run.ended, run.reason, run.steps) == ("refused", "clock_identity", ())
    assert woke == [] and _advances(SessionFactory) == []


def test_an_unknown_clock_key_is_refused(SessionFactory, world, woke):
    run = conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1])], "not-a-key", steps=2)
    assert (run.ended, run.reason) == ("refused", "clock_unreadable:401") and woke == []


def test_a_live_run_is_refused(SessionFactory, woke):
    s = SessionFactory()
    try:
        _, clock_key = seed_runtime_agent(s)
        pod = create_pod(s, name="desk")
        _, pm = register_agent(s, name="pm-1", role=AgentRole.pm, pod_id=pod.id)
        s.commit()
        pod_id = pod.id
    finally:
        s.close()
    run = conduct(SessionFactory, [(_spec("a-pm", pod_id), pm)], clock_key, steps=2)
    assert (run.ended, run.reason) == ("refused", "not_backtest") and woke == []


def test_duplicate_spec_ids_are_refused(SessionFactory, world, woke):
    handed = [(_spec("a-pm", 1), world["pm"][1]), (_spec("a-pm", 2), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=2)
    assert (run.ended, run.reason) == ("refused", "duplicate_spec_id") and woke == []


def test_a_clock_that_will_not_advance_ends_the_run_in_error(SessionFactory, world, woke,
                                                             halt_file):
    """Physics' own HALT (423 on writes) while the Runtime's governance says run:
    the minds read, the advance is refused, the run says so and stops."""
    halt_file.write_text("")
    run = conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1])], world["clock"], steps=3)
    assert (run.ended, run.reason) == ("error", "advance_failed:423")
    assert len(run.steps) == 1 and run.steps[0].advanced_to is None
    assert woke == ["a"] and _advances(SessionFactory) == []


class _OddClock:
    """A clock hand whose answers lack ``now`` (audit c24 NOTE 2)."""

    def __init__(self, bad_on: str) -> None:
        self.bad_on, self.reads = bad_on, 0

    async def get(self, path: str):
        if path == "/me":
            return {"role": "runtime"}
        self.reads += 1
        if self.bad_on == "step" and self.reads > 1:
            return {"mode": "backtest"}
        return {"mode": "backtest", "now": "2024-01-02T15:00:00Z"}

    async def post(self, path: str, body: dict):
        return {} if self.bad_on == "advance" else {"now": "2024-01-03T15:00:00Z"}


@pytest.mark.parametrize("bad_on", ["step", "advance"])
def test_a_clock_answer_without_now_ends_the_run_in_error(bad_on):
    run = asyncio.run(run_backtest([], _OddClock(bad_on), steps=2))  # type: ignore[arg-type]
    assert (run.ended, run.reason) == ("error", "clock_malformed")
    assert len(run.steps) == (1 if bad_on == "advance" else 0)


@pytest.mark.parametrize("kwargs", [
    {"steps": -1}, {"steps": True}, {"steps": 1.0}, {"steps": lockstep.MAX_STEPS + 1},
    {"steps": 1, "days_per_step": 0}, {"steps": 1, "days_per_step": False},
    {"steps": 1, "days_per_step": lockstep.MAX_DAYS_PER_STEP + 1},
])
def test_steps_and_days_are_plain_ints_in_range(kwargs):
    with pytest.raises(ValueError):
        asyncio.run(run_backtest([], None, **kwargs))  # type: ignore[arg-type]
