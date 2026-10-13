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
* a clock that will not advance ends the run ``error`` with the status;
* Era I exit criteria, end to end (R-5a, ADR-036): a conducted mind asking for
  tomorrow's bars is refused, a window across now holds no unfinished bar, and its
  ``advance_clock`` is refused (EC3); HALT appearing as a tool call returns lets no
  further call, wake, advance or event happen (EC5); a spending mind is never built
  under a null or numeric cap, while zero-cost minds still wake (EC6).
"""

from __future__ import annotations

import asyncio
import json
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
from mcp_server.client import FundAPIError
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
    # The name is the pod's PM's in `world`: a key wears its spec's name (ADR-032 (n)).
    return AgentSpec(**({"id": id, "name": f"pm-{pod}", "role": "pm", "pod": pod,
                         "provider": "scripted",
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


def test_halt_between_two_minds_wakes_ends_halted(SessionFactory, world, woke, gov, monkeypatch):
    """B-054: the gate refuses b's wake (``halted``); the run was ``refused``, now ``halted``."""
    def halts_when_done(request):
        (gov / "HALT").write_text("")
        return CompletionResponse(content="done, and the Human halts")
    monkeypatch.setattr(scripted, "SCRIPTS",
                        MappingProxyType(dict(scripted.SCRIPTS) | {"late": halts_when_done}))
    run = conduct(SessionFactory, [(_spec("a-pm", 1, "late"), world["pm"][1]),
                                   (_spec("b-pm", 2, "read-b"), world["pm"][2])],
                  world["clock"], steps=3)
    assert (run.ended, run.reason) == ("halted", "halted")
    [step] = run.steps
    assert [(w.ended, w.reason) for w in step.wakes][1] == ("refused", "halted")
    assert step.wakes[0].ended == "done" and woke == []
    assert step.advanced_to is None and _advances(SessionFactory) == []


def test_a_non_halt_wake_refusal_between_minds_still_ends_refused(SessionFactory, world, woke,
                                                                  monkeypatch):
    """Counter-example: only the gate's ``halted`` is relabelled."""
    from runtime.native import WakeRecord
    real = lockstep.wake

    async def wake(spec, client, **kw):
        if spec.id == "b-pm":
            return WakeRecord(spec.id, "refused", "bad_input", 0)
        return await real(spec, client, **kw)
    monkeypatch.setattr(lockstep, "wake", wake)
    run = conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1]),
                                   (_spec("b-pm", 2, "read-b"), world["pm"][2])],
                  world["clock"], steps=3)
    assert (run.ended, run.reason) == ("refused", "wake_refused:b-pm:bad_input")
    assert woke == ["a"] and _advances(SessionFactory) == []


# --- refusals and errors ----------------------------------------------------------------

def test_a_key_that_is_not_its_specs_agent_refuses_the_run_before_step_0(
        SessionFactory, world, woke):
    """pm-1's key under a spec for pod 2. Since red-team 0015 H2 every key is read
    before step 0, so nobody wakes at all (was: a woke once, then the run was refused)."""
    # b-pm wears pm-1's own name, so only the pod differs (audit c26 BLOCK 1).
    handed = [(_spec("a-pm", 1, "read-a"), world["pm"][1]),
              (_spec("b-pm", 2, "read-b", name="pm-1"), world["pm"][1])]
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


def test_a_clock_physics_halted_will_not_advance_ends_the_run_halted(SessionFactory, world, woke,
                                                                    halt_file):
    """Physics' own HALT (423 on writes) while the Runtime's governance says run:
    the minds read, the advance is refused, the run says so and stops. B-054: it
    says ``halted`` (was ``error``/``advance_failed:423``): only physics' HALT answers 423."""
    halt_file.write_text("")
    run = conduct(SessionFactory, [(_spec("a-pm", 1), world["pm"][1])], world["clock"], steps=3)
    assert (run.ended, run.reason) == ("halted", "halted")
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


class _FailingAdvance:
    """An advance that fails (500), then a ``/clock`` re-read that says one of: the
    clock moved, it stayed, physics cannot be asked, or the answer has no ``now``
    (red-team 0015 H3, audit c24-b WARN 1)."""

    def __init__(self, after: str) -> None:
        self.after, self.advanced = after, False

    async def get(self, path: str):
        if path == "/me":
            return {"role": "runtime"}
        if not self.advanced:
            return {"mode": "backtest", "now": "2024-01-02T15:00:00Z"}
        if self.after == "unreadable":
            raise FundAPIError(503, "physics unreachable", path=path)
        if self.after == "malformed":
            return {"mode": "backtest"}
        moved = self.after == "moved"
        return {"mode": "backtest",
                "now": "2024-01-03T15:00:00Z" if moved else "2024-01-02T15:00:00Z"}

    async def post(self, path: str, body: dict):
        self.advanced = True
        raise FundAPIError(500, "the sweep broke", path=path)


@pytest.mark.parametrize(("after", "reason", "advanced_to"), [
    ("moved", "advance_failed:500", "2024-01-03T15:00:00Z"),
    ("stayed", "advance_failed:500", None),
    ("unreadable", "advance_failed:500:clock_unknown", None),
    ("malformed", "advance_failed:500:clock_unknown", None),
])
def test_a_failed_advance_records_what_physics_says_or_that_it_cannot(after, reason,
                                                                      advanced_to):
    """``advanced_to=None`` alone would mean both "stayed" and "nobody knows"; the
    reason tells them apart."""
    run = asyncio.run(run_backtest([], _FailingAdvance(after), steps=3))  # type: ignore[arg-type]
    assert (run.ended, run.reason) == ("error", reason)
    assert len(run.steps) == 1 and run.steps[0].advanced_to == advanced_to


@pytest.mark.parametrize("kwargs", [
    {"steps": -1}, {"steps": True}, {"steps": 1.0}, {"steps": lockstep.MAX_STEPS + 1},
    {"steps": 1, "days_per_step": 0}, {"steps": 1, "days_per_step": False},
    {"steps": 1, "days_per_step": lockstep.MAX_DAYS_PER_STEP + 1},
])
def test_steps_and_days_are_plain_ints_in_range(kwargs):
    with pytest.raises(ValueError):
        asyncio.run(run_backtest([], None, **kwargs))  # type: ignore[arg-type]


# --- R-3b-2a: the c24 audit's carry-overs -------------------------------------------------

def test_when_every_mind_is_retired_the_world_still_lives_its_steps(SessionFactory, world,
                                                                    monkeypatch):
    """Audit c24-b NOTE 4/5: management fires the PM in step 1 and itself in step 2.
    Each is retired at the step its next wake was refused; steps 4 and 5 wake no one,
    and the clock still moves: it is the Runtime's, not the minds'."""
    wakes = {"n": 0}

    def fire(who: int) -> CompletionResponse:
        return CompletionResponse(content="you're fired", tool_calls=[
            ToolCall(id="fire", name="deactivate_agent", arguments={"agent_id": who})])

    def firer(request):
        turns = sum(m.role == "assistant" for m in request.messages)
        if turns == 0:
            wakes["n"] += 1
            return CompletionResponse(content="who is here?",
                                      tool_calls=[ToolCall(id="dir", name="list_agents")])
        if turns == 1 and wakes["n"] == 2:
            directory = json.loads(request.messages[-1].content)
            return fire(next(a["id"] for a in directory if a["name"] == "pm-2"))
        if turns == 1 and wakes["n"] == 3:
            return fire(json.loads(request.messages[1].content)["me"]["id"])
        return CompletionResponse(content="done")

    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(
        dict(scripted.SCRIPTS) | {"firer": firer, "read-b": _read_once}))
    handed = [(AgentSpec(id="a-mgmt", name="management", role="management", provider="scripted",
                         script="firer", charter="Run the firm."), world["admin"]),
              (_spec("b-pm", 2, "read-b"), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=5)
    assert run.ended == "completed", run.reason
    assert (run.retired, run.retired_at) == (("b-pm", "a-mgmt"), (1, 3))
    assert [len(st.wakes) for st in run.steps] == [2, 2, 1, 1, 0]
    assert all(st.advanced_to for st in run.steps) and len(_advances(SessionFactory)) == 5


def _read_once(request):
    if not any(m.role == "assistant" for m in request.messages):
        return CompletionResponse(content="time?", tool_calls=[ToolCall(id="c", name="get_clock")])
    return CompletionResponse(content="done")


class _FlakyMe(FundClient):
    """A live key whose ``/me`` fails once, with 503, on the ``fail_on``-th read."""

    def __init__(self, *args, fail_on: int, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reads, self.fail_on = 0, fail_on

    async def request(self, method, path, **kwargs):
        if path == "/me":
            self.reads += 1
            if self.reads == self.fail_on:
                raise FundAPIError(503, "the App blinked", path=path)
        return await super().request(method, path, **kwargs)


def test_a_no_identity_refusal_with_a_live_key_still_ends_the_run(SessionFactory, world,
                                                                  monkeypatch):
    """Audit c24-b NOTE 3: retirement is only for a key physics now answers 401. A
    wake refused ``no_identity`` while the key still works (a blip, not a firing)
    ends the run with no advance, as any other refused wake does."""
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(
        dict(scripted.SCRIPTS) | {"read-a": _read_once}))
    app = _app(SessionFactory)

    async def go() -> lockstep.RunRecord:
        transport = httpx.ASGITransport(app=app)
        # /me reads: 1 before step 0, 2 in step 0's wake, 3 in step 1's wake (fails).
        async with _FlakyMe(base_url="http://fund.test", api_key=world["pm"][1],
                            transport=transport, fail_on=3) as pm, \
                FundClient(base_url="http://fund.test", api_key=world["clock"],
                           transport=transport) as clock:
            return await run_backtest([Mind(_spec("a-pm", 1, "read-a"), pm)], clock, steps=3)

    with TestClient(app):
        run = asyncio.run(go())
    assert (run.ended, run.reason) == ("refused", "wake_refused:a-pm:no_identity")
    assert run.retired == () and len(run.steps) == 2 and run.steps[1].advanced_to is None
    assert len(_advances(SessionFactory)) == 1


# --- Era I exit criteria (R-5a, ADR-036): EC3, EC5, EC6 ---------------------------------
# Each gate below existed before these tests. They prove it end to end: a mind run by the
# conductor, every act through the published MCP tools, over HTTP, into physics.

def _asks(calls_for, seen: list[list]):
    """A test script: read the clock, then make ``calls_for(now)``'s calls in one batch,
    then report every tool answer of that batch to ``seen`` (one list per wake)."""
    def script(request):
        turns = sum(m.role == "assistant" for m in request.messages)
        if turns == 0:
            return CompletionResponse(content="", tool_calls=[ToolCall(id="now", name="get_clock")])
        if turns == 1:
            now = datetime.fromisoformat(
                json.loads(request.messages[-1].content)["now"].replace("Z", "+00:00"))
            return CompletionResponse(content="", tool_calls=calls_for(now))
        last = max(i for i, m in enumerate(request.messages) if m.role == "assistant")
        seen.append([m.model_copy() for m in request.messages[last + 1:]])
        return CompletionResponse(content="done")
    return script


def _install(monkeypatch, **scripts) -> None:
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | scripts))


def _day(now: datetime, days: int) -> str:
    return (now.date() + timedelta(days=days)).isoformat()


def test_ec3_a_mind_asking_for_tomorrows_bars_is_refused(SessionFactory, world, monkeypatch):
    seen: list[list] = []
    _install(monkeypatch, ahead=_asks(lambda now: [ToolCall(
        id="ahead", name="get_ohlcv",
        arguments={"ticker": "AAPL", "start": _day(now, 1), "end": _day(now, 3)})], seen))
    run = conduct(SessionFactory, [(_spec("a-pm", 1, "ahead"), world["pm"][1])],
                  world["clock"], steps=2)
    assert (run.ended, len(run.steps)) == ("completed", 2)
    assert [w.ended for st in run.steps for w in st.wakes] == ["done", "done"]
    assert len(seen) == 2
    for [answer] in seen:
        assert answer.is_error and "no look-ahead" in answer.content and "400" in answer.content


def test_ec3_a_window_past_now_holds_no_bar_that_has_not_ended(SessionFactory, world,
                                                                monkeypatch):
    """Counter-example to "only ``start`` is guarded": a window that ends after now is
    served, but clipped — every bar in it had ended by the step's now (ADR-028)."""
    from app.marketdata.base import bar_end
    seen: list[list] = []
    _install(monkeypatch, across=_asks(lambda now: [ToolCall(
        id="across", name="get_ohlcv",
        arguments={"ticker": "AAPL", "start": _day(now, -5), "end": _day(now, 5)})], seen))
    run = conduct(SessionFactory, [(_spec("a-pm", 1, "across"), world["pm"][1])],
                  world["clock"], steps=3)
    assert run.ended == "completed" and len(run.steps) == len(seen) == 3
    for step, [answer] in zip(run.steps, seen):
        at = datetime.fromisoformat(step.at.replace("Z", "+00:00"))
        assert not answer.is_error
        bars = json.loads(answer.content)["bars"]
        assert bars, "the window before now must still be served"
        for bar in bars:
            ts = datetime.fromisoformat(bar["ts"].replace("Z", "+00:00"))
            assert bar_end(ts, "1d") <= at


def test_ec3_a_mind_cannot_reach_tomorrow_by_moving_the_clock(SessionFactory, world,
                                                               monkeypatch):
    seen: list[list] = []
    _install(monkeypatch, mover=_asks(lambda now: [ToolCall(
        id="move", name="advance_clock", arguments={"days": 1})], seen))
    run = conduct(SessionFactory, [(_spec("a-pm", 1, "mover"), world["pm"][1])],
                  world["clock"], steps=2)
    assert run.ended == "completed" and len(seen) == 2
    for [answer] in seen:
        assert answer.is_error and "403" in answer.content
    advances = _advances(SessionFactory)
    with SessionFactory() as s:
        from app.db.models import Agent
        assert {s.get(Agent, e.actor_agent_id).role for e in advances} == {AgentRole.runtime}
    assert len(advances) == 2  # the runtime's own advances, one per step, and no other


def _max_event_id(SessionFactory) -> int:
    with SessionFactory() as s:
        return max(s.execute(select(Event.id)).scalars())


def _halting_execute(monkeypatch, gov, SessionFactory, on_call: str) -> dict:
    """After the tool call with id ``on_call`` returns, the Human creates HALT. Records
    the newest event id at that moment."""
    from runtime import native
    original = native._execute
    when: dict = {}

    async def execute(*args, **kwargs):
        message = await original(*args, **kwargs)
        if message.tool_call_id == on_call and not when:
            (gov / "HALT").write_text("")
            when["last_event"] = _max_event_id(SessionFactory)
        return message
    monkeypatch.setattr(native, "_execute", execute)
    return when


def test_ec5_halt_created_during_a_tool_call_stops_the_run_within_that_call(
        SessionFactory, world, woke, gov, monkeypatch):
    """"Within one tick" (ADR-036): the tool call in flight when HALT appears finishes,
    and nothing after it happens — no further call, no wake, no advance, no event
    (Art. 5.2). HALT is written as that call's answer returns, before the wake reads
    on (audit c30 NOTE 1): for the Runtime that is the same moment as "during"."""
    wakes = {"n": 0}

    def three_reads(request):
        turns = sum(m.role == "assistant" for m in request.messages)
        if turns == 0:
            wakes["n"] += 1
            n = wakes["n"]
            return CompletionResponse(content="", tool_calls=[
                ToolCall(id=f"w{n}-{i}", name="get_clock") for i in (1, 2, 3)])
        return CompletionResponse(content="done")
    _install(monkeypatch, three=three_reads)
    when = _halting_execute(monkeypatch, gov, SessionFactory, on_call="w2-1")
    handed = [(_spec("a-pm", 1, "three"), world["pm"][1]),
              (_spec("b-pm", 2, "read-b"), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=5)
    assert (run.ended, len(run.steps)) == ("halted", 2)
    [halted] = run.steps[1].wakes                 # b, later in id order, never woke that step
    assert halted.ended == "halted" and halted.tool_calls == 1  # of 3 asked for (per wake)
    assert [w.tool_calls for w in run.steps[0].wakes] == [3, 1]  # day one ran whole
    last = max(i for i, m in enumerate(halted.transcript) if m.role == "assistant")
    assert [m.tool_call_id for m in halted.transcript[last + 1:]] == ["w2-1"]
    assert woke == ["b"]
    assert run.steps[1].advanced_to is None and len(_advances(SessionFactory)) == 1
    assert _max_event_id(SessionFactory) == when["last_event"]


def test_ec5_halt_on_the_last_call_of_a_step_wakes_no_one_and_moves_nothing(
        SessionFactory, world, woke, gov, monkeypatch):
    _install(monkeypatch, last=_asks(lambda now: [ToolCall(id="last", name="get_clock")], []))
    when = _halting_execute(monkeypatch, gov, SessionFactory, on_call="last")
    handed = [(_spec("a-pm", 1, "read-a"), world["pm"][1]),
              (_spec("b-pm", 2, "last"), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=3)
    assert (run.ended, len(run.steps)) == ("halted", 1)
    assert [w.ended for w in run.steps[0].wakes] == ["done", "halted"]
    assert woke == ["a"] and run.steps[0].advanced_to is None
    assert _advances(SessionFactory) == []
    assert _max_event_id(SessionFactory) == when["last_event"]


def _built(monkeypatch) -> list[str]:
    """Every spec a mind is built for. A gate that refuses first builds nothing, so no
    provider exists to be called."""
    from runtime import native
    original, built = native.build_provider, []

    def build(spec, tape=None):  # R-4b: the registry takes a tape; the spy passes it through
        built.append(spec.id)
        return original(spec, tape)
    monkeypatch.setattr(native, "build_provider", build)
    return built


def test_ec6_cap_null_never_builds_a_spending_mind(SessionFactory, world, woke, monkeypatch):
    built = _built(monkeypatch)
    handed = [(_spec("a-pm", 1, "read-a"), world["pm"][1]),
              (_spec("b-pm", 2, provider="metered", script=None), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=3)
    assert (run.ended, run.reason) == ("refused", "wake_refused:b-pm:cap_null")
    assert built == ["a-pm"] and woke == ["a"]
    assert run.steps[0].advanced_to is None and _advances(SessionFactory) == []


def test_ec6_a_numeric_cap_still_refuses_spending_until_metering(SessionFactory, world, woke,
                                                                 gov, monkeypatch):
    """Counter-example to "only null refuses": until R-6 gives a mind a metered key, a
    number in the cap wakes no spending mind either (ADR-032 (4))."""
    (gov / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: 5\n")
    built = _built(monkeypatch)
    run = conduct(SessionFactory, [(_spec("a-pm", 1, provider="metered", script=None),
                                    world["pm"][1])], world["clock"], steps=2)
    assert (run.ended, run.reason) == ("refused", "wake_refused:a-pm:no_metered_key")
    assert built == [] and _advances(SessionFactory) == []


def test_ec6_zero_cost_minds_still_wake_under_cap_null(SessionFactory, world, woke,
                                                       monkeypatch):
    """The positive control, and today's law (Q-0005, answer B pending the Human)."""
    built = _built(monkeypatch)
    run = conduct(SessionFactory, [(_spec("a-pm", 1, "read-a"), world["pm"][1])],
                  world["clock"], steps=3)
    assert run.ended == "completed" and woke == ["a"] * 3 and built == ["a-pm"] * 3
    assert len(_advances(SessionFactory)) == 3
