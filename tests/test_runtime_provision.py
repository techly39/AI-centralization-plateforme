"""R-3b-2b-1: minds are provisioned from their specs (ADR-032 (n)).

Claims under test:

* ``provision`` registers one App agent per spec over HTTP, in id order, as the
  spec says (name, role, pod) with ``charter_ref = spec:<id>``. The registrar is
  the actor of every ``agent_registered`` event, and the minds it returns live a
  backtest through the conductor;
* every spec is checked **before any is registered**: HALT, a cap refusal,
  ``wake_policy: never``, a spec no mind can be built from, duplicate ids, names
  that look the same, reserved names and names already taken register nothing;
  a HALT that appears part-way stops the next registration;
* physics decides who may register: the clock key and a PM key get 403 and
  register nothing;
* a refusal part-way names what was already registered, and only that exists;
  an answer that is not the agent asked for is refused and no client is left open;
* **a key must wear its spec's name**: a key with the right role and pod but
  another name cannot wake (``identity_mismatch``) or join a run, and the right
  name with the wrong role or pod cannot either.
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


@pytest.mark.parametrize("specs, reason", [
    ([_spec("a-pm", "ok"), _spec("x-pm", "x", provider="metered", script=None)],
     "wake_refused:x-pm:cap_null"),
    ([_spec("a-pm", "ok"), _spec("x-pm", "x", wake_policy="never")], "wake_policy_never:x-pm"),
    ([_spec("a-pm", "ok"), _spec("x-pm", "x", model="some-model")],
     "provider_refused:x-pm:contradiction"),
    ([_spec("a-pm", "ok"), _spec("x-pm", "x", script="no-such-script")],
     "provider_refused:x-pm:unknown_script"),
    ([_spec("a-pm", "one"), _spec("a-pm", "two")], "duplicate_spec_id"),
    ([_spec("a-pm", "same"), _spec("b-pm", "same")], "duplicate_name"),
    ([_spec("a-pm", "Runtime")], "name_reserved:a-pm"),
    ([_spec("a-pm", "ok"), _spec("b-pm", "fine")], None),
])
def test_vet_is_provisions_own_judgement(SessionFactory, world, woke, gov, specs, reason):
    """B-053: ``vet`` (no client, so no network) says what ``provision`` raises, under one law."""
    from runtime.governance import read_governance
    from runtime.provision import vet
    assert vet(specs, read_governance()) == reason
    if reason is not None:
        err, _, _ = _provision(SessionFactory, specs, world["admin"])
        assert err.reason == reason and _made(SessionFactory) == {}


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


@pytest.mark.parametrize("who, reason, action", [
    ("pm", "register_failed:a-pm:403", "register_agents"),
    ("clock", "directory_unreadable:403", "list_agents"),  # stopped one read earlier
])
def test_physics_decides_who_may_register(SessionFactory, world, woke, who, reason, action):
    key = world["clock"] if who == "clock" else world["pm"][1]
    err, _, _ = _provision(SessionFactory, [_spec("a-pm", "ok")], key)
    assert (err.reason, err.registered) == (reason, ())
    assert _made(SessionFactory) == {}
    [denied] = _events(SessionFactory, EVENT_PERMISSION_DENIED)
    assert denied.payload_json["action"] == action


@pytest.mark.parametrize("name, reason", [
    ("pm-2", "name_taken:c-pm"), ("PM-2​", "name_taken:c-pm"),
    ("runtime", "name_reserved:c-pm"), ("System", "name_reserved:c-pm"),
], ids=["taken", "taken-lookalike", "reserved", "reserved-case"])
def test_a_name_physics_would_refuse_registers_nothing(SessionFactory, world, woke, name,
                                                       reason):
    """Red-team 0016 H3: a refusal knowable in advance is found before anything is
    registered (this test pinned the part-way 409 before; the law is now stronger)."""
    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2"), _spec("c-pm", name)]
    err, _, _ = _provision(SessionFactory, specs, world["admin"])
    assert (err.reason, err.registered) == (reason, ())
    assert _made(SessionFactory) == {}


def test_a_refusal_part_way_names_what_was_registered(SessionFactory, world, woke):
    """Physics refuses the third (here: its pod is a role it may not hold) after two
    were made: only those two exist, are named, and their clients are closed."""
    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2"),
             _spec("c-pm", "fresh-3", pod=None, role="management")]

    class RefusesThird(FundClient):
        async def post(self, path, body=None, **params):
            if body["name"] == "fresh-3":
                body = {**body, "role": "system"}  # physics answers 422
            return await super().post(path, body, **params)

    err, _, closed = _provision(SessionFactory, specs, world["admin"], registrar=RefusesThird)
    assert (err.reason, err.registered) == ("register_failed:c-pm:422", ("a-pm", "b-pm"))
    assert set(_made(SessionFactory)) == {"fresh-1", "fresh-2"}
    assert closed == [True, True]  # no client outlives a failed provisioning


def test_the_runtime_fold_is_physics_fold() -> None:
    """The Runtime cannot import physics, so it keeps a copy of the name fold and the
    reserved names; the copy must not drift."""
    from app.registry import service
    from runtime import provision as rp
    assert rp.RESERVED_NAMES == service._RESERVED_NAMES
    corpus = ["pm-1", "PM-1", " pm-1 ", "pm-1​", "ｐｍ-1", "Runtime", "ſystem", "ꜱystem",
              "run time", "ㅤruntime", "runtime\U000e01f0", "é", "ﬁ", "a\x00b", "ß", "İ"]
    assert [rp.name_key(n) for n in corpus] == [service._name_key(n) for n in corpus]


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


@pytest.mark.parametrize("spec, key", [
    (_spec("a-pm", "management", 1), "admin"),   # right name, wrong role
    (_spec("a-pm", "pm-1", 2), "pm-1"),          # right name, wrong pod
], ids=["role", "pod"])
def test_the_name_alone_is_not_enough(SessionFactory, world, woke, spec, key):
    """Audit c26 BLOCK 1: role and pod are still checked when the name is right."""
    key = world["admin"] if key == "admin" else world["pm"][1]
    app = _app(SessionFactory)

    async def go():
        async with FundClient(base_url="http://fund.test", api_key=key,
                              transport=httpx.ASGITransport(app=app)) as client:
            return await wake(spec, client, workflow_input={})

    with TestClient(app):
        record = asyncio.run(go())
    assert (record.ended, record.reason) == ("refused", "identity_mismatch")
    run = conduct(SessionFactory, [(spec, key)], world["clock"], steps=1)
    assert (run.ended, run.reason) == ("refused", "identity_mismatch:a-pm") and woke == []
