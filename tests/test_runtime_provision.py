"""R-3b-2b-1: minds are provisioned from their specs (ADR-032 (n)).

Claims under test:

* ``provision`` registers one App agent per spec over HTTP, in id order, as the
  spec says (name, role, pod) with ``charter_ref = spec:<id>``. The registrar is
  the actor of every ``agent_registered`` event, and the minds it returns live a
  backtest through the conductor;
* every spec is checked **before any is registered**: HALT, a cap refusal,
  ``wake_policy: never``, a spec no mind can be built from, and duplicate ids or
  names register nothing; a HALT that appears part-way stops the next registration;
* physics decides who may register: the clock key and a PM key get 403 and
  register nothing;
* a failure part-way names what was already registered, and only that exists;
  an answer that is not the agent asked for is refused and no client is left open;
* **a key must wear its spec's name**: a key with the right role and pod but
  another name cannot wake (``identity_mismatch``) or join a run.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Agent, Event
from app.ledger.events import EVENT_AGENT_REGISTERED, EVENT_PERMISSION_DENIED
from mcp_server import FundClient
from runtime.lockstep import Mind, run_backtest
from runtime.native import wake
from runtime.provision import ProvisionError, provision
from runtime.spec import AgentSpec
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    _app,
    conduct,
    gov,
    live_afterwards,
    woke,
    world,
)

#: The agents ``world`` registers itself.
WORLD = {"management", "pm-1", "pm-2", "pm-3", "runtime"}


def _spec(id: str, name: str, pod: int | None = 1, **fields) -> AgentSpec:
    base = {"id": id, "name": name, "role": "pm" if pod else "management", "pod": pod,
            "provider": "scripted", "script": "read-a", "charter": "Read the clock."}
    return AgentSpec(**(base | fields))


def _provision(SessionFactory, specs, registrar_key: str, *, steps: int | None = None,
               clock_key: str | None = None, registrar=None):
    """Provision over ASGI; with ``steps``, then run the minds. Returns
    ``(minds or ProvisionError, run or None, closed)``."""
    app = _app(SessionFactory)
    closed: list[bool] = []

    async def go():
        transport = httpx.ASGITransport(app=app)

        class Tracked(FundClient):
            async def aclose(self) -> None:
                closed.append(True)
                await super().aclose()

        def connect(key: str) -> FundClient:
            return Tracked(base_url="http://fund.test", api_key=key, transport=transport)

        reg = (registrar or FundClient)(base_url="http://fund.test", api_key=registrar_key,
                                         transport=transport)
        clock = connect(clock_key) if clock_key else None
        minds: list[Mind] = []
        try:
            try:
                minds = await provision(specs, reg, connect)
            except ProvisionError as exc:
                return exc, None
            run = await run_backtest(minds, clock, steps=steps) if steps else None
            return minds, run
        finally:
            await reg.aclose()
            for c in [*(m.client for m in minds), *([clock] if clock else [])]:
                await c.aclose()

    with TestClient(app):
        out, run = asyncio.run(go())
    return out, run, closed


def _made(SessionFactory) -> dict[str, tuple]:
    """Agents beyond ``world``'s: name → (role, pod, charter_ref)."""
    with SessionFactory() as s:
        return {a.name: (a.role.value, a.pod_id, a.charter_ref)
                for a in s.execute(select(Agent)).scalars() if a.name not in WORLD}


def _events(SessionFactory, type_: str) -> list[Event]:
    with SessionFactory() as s:
        return list(s.execute(select(Event).where(Event.type == type_)
                              .order_by(Event.id)).scalars())


# --- provisioning -----------------------------------------------------------------------

def test_minds_are_registered_from_their_specs_and_live_a_run(SessionFactory, world, woke):
    specs = [_spec("b-pm", "desk-2-pm", 2, script="read-b"), _spec("a-pm", "desk-1-pm", 1)]
    minds, run, _ = _provision(SessionFactory, specs, world["admin"], steps=2,
                               clock_key=world["clock"])
    assert [m.spec.id for m in minds] == ["a-pm", "b-pm"]
    assert _made(SessionFactory) == {"desk-1-pm": ("pm", 1, "spec:a-pm"),
                                     "desk-2-pm": ("pm", 2, "spec:b-pm")}
    registered = [e for e in _events(SessionFactory, EVENT_AGENT_REGISTERED)
                  if e.payload_json["name"] not in WORLD]
    admin_id = next(e.payload_json["agent_id"] for e in _events(SessionFactory,
                    EVENT_AGENT_REGISTERED) if e.payload_json["name"] == "management")
    assert [(e.payload_json["name"], e.actor_agent_id) for e in registered] == [
        ("desk-1-pm", admin_id), ("desk-2-pm", admin_id)]
    assert (run.ended, len(run.steps)) == ("completed", 2) and woke == ["a", "b"] * 2


@pytest.mark.parametrize("spec, reason", [
    (_spec("x-pm", "x", provider="metered", script=None), "wake_refused:x-pm:cap_null"),
    (_spec("x-pm", "x", wake_policy="never"), "wake_policy_never:x-pm"),
    (_spec("x-pm", "x", model="some-model"), "provider_refused:x-pm:contradiction"),
    (_spec("x-pm", "x", script="no-such-script"), "provider_refused:x-pm:unknown_script"),
    (_spec("x-pm", "x", adapter="openclaw"), "wake_refused:x-pm:cap_null"),
], ids=["spending", "never", "contradiction", "unknown-script", "openclaw"])
def test_a_spec_that_could_never_wake_registers_nothing(SessionFactory, world, woke, spec,
                                                        reason):
    good = _spec("a-pm", "ok")  # sorted first: it would have been registered first
    err, _, _ = _provision(SessionFactory, [good, spec], world["admin"])
    assert (err.reason, err.registered) == (reason, ())
    assert _made(SessionFactory) == {}


def test_under_halt_nothing_is_registered(SessionFactory, world, woke, gov):
    (gov / "HALT").write_text("")
    err, _, _ = _provision(SessionFactory, [_spec("a-pm", "ok")], world["admin"])
    assert (err.reason, err.registered) == ("wake_refused:a-pm:halted", ())
    assert _made(SessionFactory) == {}


def test_halt_part_way_stops_the_next_registration(SessionFactory, world, woke, gov):
    class HaltsAfterOne(FundClient):
        async def post(self, path, body=None, **params):
            made = await super().post(path, body, **params)
            (gov / "HALT").write_text("")
            return made

    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2")]
    err, _, closed = _provision(SessionFactory, specs, world["admin"], registrar=HaltsAfterOne)
    assert (err.reason, err.registered) == ("halted", ("a-pm",))
    assert set(_made(SessionFactory)) == {"fresh-1"} and closed == [True]


@pytest.mark.parametrize("specs, reason", [
    ([_spec("a-pm", "one"), _spec("a-pm", "two")], "duplicate_spec_id"),
    ([_spec("a-pm", "same"), _spec("b-pm", "same")], "duplicate_name"),
])
def test_duplicate_ids_or_names_register_nothing(SessionFactory, world, woke, specs, reason):
    err, _, _ = _provision(SessionFactory, specs, world["admin"])
    assert (err.reason, err.registered) == (reason, ())
    assert _made(SessionFactory) == {}


@pytest.mark.parametrize("who", ["clock", "pm"])
def test_physics_decides_who_may_register(SessionFactory, world, woke, who):
    key = world["clock"] if who == "clock" else world["pm"][1]
    err, _, _ = _provision(SessionFactory, [_spec("a-pm", "ok")], key)
    assert (err.reason, err.registered) == ("register_failed:a-pm:403", ())
    assert _made(SessionFactory) == {}
    [denied] = _events(SessionFactory, EVENT_PERMISSION_DENIED)
    assert denied.payload_json["action"] == "register_agents"


@pytest.mark.parametrize("taken", ["pm-2", "runtime"], ids=["taken", "reserved"])
def test_a_failure_part_way_names_what_was_registered(SessionFactory, world, woke, taken):
    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2"), _spec("c-pm", taken),
             _spec("d-pm", "fresh-4")]
    err, _, closed = _provision(SessionFactory, specs, world["admin"])
    assert (err.reason, err.registered) == ("register_failed:c-pm:409", ("a-pm", "b-pm"))
    assert set(_made(SessionFactory)) == {"fresh-1", "fresh-2"}
    assert closed == [True, True]  # no client outlives a failed provisioning


@pytest.mark.parametrize("lie", [
    {"role": "management"}, {"pod_id": 2}, {"name": "someone"}, {"id": "7"}, {"api_key": ""},
    {"id": "same"},
], ids=["role", "pod", "name", "id-not-int", "no-key", "id-twice"])
def test_an_answer_that_is_not_the_agent_asked_for_is_refused(SessionFactory, world, woke, lie):
    class Liar(FundClient):
        async def post(self, path, body=None, **params):
            made = await super().post(path, body, **params)
            if lie == {"id": "same"}:
                return {**made, "id": 1}  # the same agent id for every spec
            return {**made, **lie} if body["name"] == "fresh-2" else made

    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2")]
    err, _, closed = _provision(SessionFactory, specs, world["admin"], registrar=Liar)
    assert (err.reason, err.registered) == ("wrong_agent:b-pm", ("a-pm", "b-pm"))
    assert closed == [True]


# --- the name is bound ------------------------------------------------------------------

def test_a_key_under_another_name_cannot_wake(SessionFactory, world, woke):
    app = _app(SessionFactory)

    async def go():
        async with FundClient(base_url="http://fund.test", api_key=world["pm"][1],
                              transport=httpx.ASGITransport(app=app)) as pm_1:
            return await wake(_spec("a-pm", "not-pm-1"), pm_1, workflow_input={})

    with TestClient(app):
        record = asyncio.run(go())
    assert (record.ended, record.reason, record.tool_calls) == ("refused", "identity_mismatch", 0)
    assert woke == []


def test_a_key_under_another_name_cannot_join_a_run(SessionFactory, world, woke):
    run = conduct(SessionFactory, [(_spec("a-pm", "not-pm-1"), world["pm"][1])],
                  world["clock"], steps=2)
    assert (run.ended, run.reason, run.steps) == ("refused", "identity_mismatch:a-pm", ())
    assert woke == []
