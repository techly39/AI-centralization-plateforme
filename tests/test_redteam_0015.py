"""RED-TEAM 0015 — attacks on cycle 0024's conductor and runtime-key work (ADR-032 (5),
ADR-033, B-041, R-3b-1).

Claims under attack:

* ``runtime.lockstep.run_backtest`` wakes every mind once per step, in spec-id
  order, then advances the clock with the runtime key; HALT stops it; a refused
  wake ends the run; the RunRecord is an honest account; the input is "copied
  once: every wake of the run sees the same document".
* ``rotate_runtime_key`` is operator-only; ``reserved_identity_problems`` uses the
  same fold as ``register_agent``; the server refuses a squatted DB before it
  installs the run clock.

Attacker: a firm agent (a scripted mind installed via ``runtime.scripted.SCRIPTS``
is the stand-in) and a sloppy operator.

* Plain ``test_held_*``: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.

Run against 4883830.
"""

from __future__ import annotations

import asyncio
import json
from types import MappingProxyType

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.models import AgentRole
from app.main import create_app
from app.registry.service import (
    ReservedIdentityError,
    is_reserved_name,
    register_agent,
    reserved_identity_problems,
)
from mcp_server import FundClient
from runtime import scripted
from runtime.lockstep import Mind, run_backtest
from runtime.providers import CompletionResponse, ToolCall
from runtime.spec import AgentSpec
from tests.test_runtime_lockstep import (  # noqa: F401  (fixtures)
    _advances,
    _app,
    _spec,
    conduct,
    gov,
    live_afterwards,
    woke,
    world,
)


def _mgmt(id: str, script: str) -> AgentSpec:
    return AgentSpec(id=id, name=id, role="management", provider="scripted", script=script,
                     charter="Run the firm.")


def _install(monkeypatch, **scripts) -> None:
    monkeypatch.setattr(scripted, "SCRIPTS",
                        MappingProxyType(dict(scripted.SCRIPTS) | scripts))


def _first_turn(request) -> bool:
    return not any(m.role == "assistant" for m in request.messages)


def _done(request) -> CompletionResponse:
    return CompletionResponse(content="done")


# --- H1: a firm agent ends the world's run ----------------------------------------------

# FIXED cycle 24 — was: RED-TEAM 0015 H1: a management mind deactivates a peer PM mid-run;
# the PM's next wake is refused (no_identity) and the conductor ends the whole backtest
# 'refused'. Management lost CONTROL_CLOCK (ADR-033) but can still stop the world's time at
# the step of its choosing (freeze the run when its book peaks).
def test_redteam_lockstep_a_firm_agent_cannot_stop_the_worlds_clock(
        SessionFactory, world, monkeypatch):
    wakes = {"n": 0}

    def firer(request):
        if _first_turn(request):
            wakes["n"] += 1
            return CompletionResponse(content="who is here?",
                                      tool_calls=[ToolCall(id="dir", name="list_agents")])
        if sum(m.role == "assistant" for m in request.messages) == 1 and wakes["n"] == 2:
            directory = json.loads(request.messages[-1].content)
            target = next(a["id"] for a in directory if a["name"] == "pm-2")
            return CompletionResponse(content="you're fired", tool_calls=[
                ToolCall(id="fire", name="deactivate_agent", arguments={"agent_id": target})])
        return _done(request)

    def reader(request):
        if _first_turn(request):
            return CompletionResponse(content="", tool_calls=[ToolCall(id="c", name="get_clock")])
        return _done(request)

    _install(monkeypatch, firer=firer, reader=reader)
    handed = [(_mgmt("a-mgmt", "firer"), world["admin"]),
              (_spec("b-pm", 2, "reader"), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=5)
    # Today: ("refused", "wake_refused:b-pm:no_identity") after one advance.
    assert run.ended != "refused", run.reason
    assert len(_advances(SessionFactory)) == 5


# --- H2: one App agent, two specs, two turns a step --------------------------------------

# FIXED cycle 24 — was: RED-TEAM 0015 H2: duplicate spec ids are refused, but two specs with
# different ids handed the same App agent's key both pass the wake's role+pod identity
# check: that agent acts twice every step (and sees its own first move before its second).
# The conductor should read /me for every mind before step 0 and refuse a repeated agent id.
def test_redteam_lockstep_one_agent_wakes_once_per_step(SessionFactory, world, woke):
    pm1 = world["pm"][1]
    handed = [(_spec("a-pm", 1, "read-a"), pm1), (_spec("z-pm", 1, "read-b"), pm1)]
    run = conduct(SessionFactory, handed, world["clock"], steps=2)
    # Today: completed, woke == ['a', 'b', 'a', 'b'] — pm-1 had two turns a step.
    assert run.ended == "refused"
    assert woke == []


# --- H3: the record says time stayed when the ledger says it moved -----------------------

# FIXED cycle 24 — was: RED-TEAM 0015 H3: /clock/advance commits the clock_advanced event
# before the pending-order sweep; if the sweep (or the connection) fails afterwards the
# conductor records advanced_to=None / advance_failed:<status> while the ledger holds the
# advance. The record and the ledger disagree on how far the run got. Fix: on an advance
# failure, re-read /clock and record what physics says.
def test_redteam_lockstep_record_matches_ledger_after_a_failed_advance(
        SessionFactory, world, woke, monkeypatch):
    import app.api.clock as clock_api

    def broken_sweep(session, **_):
        raise RuntimeError("the sweep broke after the advance committed")
    monkeypatch.setattr(clock_api, "check_pending_orders", broken_sweep)
    app = _app(SessionFactory)

    async def go():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        pm = FundClient(base_url="http://fund.test", api_key=world["pm"][1], transport=transport)
        clock = FundClient(base_url="http://fund.test", api_key=world["clock"],
                           transport=transport)
        try:
            return await run_backtest([Mind(_spec("a-pm", 1), pm)], clock, steps=3)
        finally:
            await pm.aclose()
            await clock.aclose()

    with TestClient(app):
        run = asyncio.run(go())
    assert (run.ended, run.reason) == ("error", "advance_failed:500")
    ledger = _advances(SessionFactory)
    # Today: the ledger holds one advance, the record says the clock did not move.
    assert (len(ledger) == 0) == (run.steps[-1].advanced_to is None)


# --- H4: the input document is not one document ------------------------------------------

# FIXED cycle 24 — was: RED-TEAM 0015 H4: run_backtest copies workflow_input with dict(), a
# shallow copy; anything holding a nested value (the caller, a concurrent task) can change
# what later minds are shown mid-run, against 'every wake of the run sees the same
# document'. Fix: copy.deepcopy (or a JSON round trip) once, before step 0.
def test_redteam_lockstep_every_wake_sees_the_same_input(SessionFactory, world, monkeypatch):
    universe = ["AAPL"]
    seen: list[list[str]] = []

    def watcher(request):
        if _first_turn(request):
            context = json.loads(next(m for m in request.messages if m.role == "user").content)
            seen.append(list(context["input"]["universe"]))
            universe.append("MSFT")  # someone else holding the caller's list
        return _done(request)

    _install(monkeypatch, watcher=watcher)
    handed = [(_spec("a-pm", 1, "watcher"), world["pm"][1]),
              (_spec("b-pm", 2, "watcher"), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=2,
                  workflow_input={"universe": universe})
    assert run.ended == "completed"
    assert seen == [["AAPL"]] * 4, seen


# --- held ----------------------------------------------------------------------------------

def test_held_a_mind_cannot_move_time_itself(SessionFactory, world, monkeypatch):
    """A management mind calls advance_clock in every wake: 403 each time, and the
    ledger shows exactly ``steps`` advances, all by the conductor."""
    def pusher(request):
        if _first_turn(request):
            return CompletionResponse(content="faster", tool_calls=[
                ToolCall(id="adv", name="advance_clock", arguments={"days": 30})])
        assert request.messages[-1].is_error and "403" in request.messages[-1].content
        return _done(request)

    _install(monkeypatch, pusher=pusher)
    run = conduct(SessionFactory,
                  [(_mgmt("a-mgmt", "pusher"), world["admin"])],
                  world["clock"], steps=3)
    assert run.ended == "completed"
    assert all(w.ended == "done" for st in run.steps for w in st.wakes)
    assert len(_advances(SessionFactory)) == 3


def test_held_the_runtime_key_cannot_wear_a_mind(SessionFactory, world, woke):
    """Sloppy operator: the clock key handed as a mind's key. No spec role is
    'runtime', so the wake is refused and time does not move."""
    run = conduct(SessionFactory, [(_mgmt("a-mgmt", "read-a"),
                                    world["clock"])], world["clock"], steps=2)
    # Since the H2 fix the conductor reads every mind's /me before step 0, so the
    # refusal comes earlier and names the spec (was: wake_refused:a-mgmt:identity_mismatch).
    assert (run.ended, run.reason, run.steps) == ("refused", "identity_mismatch:a-mgmt", ())
    assert woke == [] and _advances(SessionFactory) == []


def test_held_a_mind_cannot_rewrite_the_input_for_the_next(SessionFactory, world, monkeypatch):
    """The mind is shown deep copies: mutating its request's messages changes nothing."""
    seen: list[str] = []

    def vandal(request):
        if _first_turn(request):
            user = next(m for m in request.messages if m.role == "user")
            seen.append(user.content)
            user.content = json.dumps({"input": {"universe": ["EVIL"]}})
        return _done(request)

    _install(monkeypatch, vandal=vandal)
    handed = [(_spec("a-pm", 1, "vandal"), world["pm"][1]),
              (_spec("b-pm", 2, "vandal"), world["pm"][2])]
    run = conduct(SessionFactory, handed, world["clock"], steps=2,
                  workflow_input={"universe": ["AAPL"]})
    assert run.ended == "completed"
    assert all("EVIL" not in s and "AAPL" in s for s in seen) and len(seen) == 4


def test_held_rotation_is_not_reachable_over_http():
    paths = {getattr(r, "path", "") for r in create_app().routes}
    assert not any("rotate" in p for p in paths)


_NAMES = ["runtime", "RUNTIME", "Runtime​", "run­time", "ｒｕｎｔｉｍｅ",
          "system️", " system ", "sys⁠tem", "ѕystem", "runtime-2", "systems",
          "run time", "ㅤruntime", "runtime\U000e01f0", "ſystem", "ꜱystem"]


@pytest.mark.parametrize("name", _NAMES)
def test_held_register_and_startup_check_use_one_fold(db, name):
    """No name passes register_agent and later trips the startup check (a firm
    agent cannot plant a world-stopping name), and no refused name is one the
    check would let through."""
    try:
        register_agent(db, name=name, role=AgentRole.analyst)
        registered = True
    except ReservedIdentityError:
        registered = False
    assert registered is not is_reserved_name(name)
    assert (reserved_identity_problems(db) == []) is True
