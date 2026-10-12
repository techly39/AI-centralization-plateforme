"""R-3b-2c-2: physics records what drives a run's minds (ADR-032 (p)).

Claims under test:

* ``POST /run/minds`` takes a declaration from the ``CONTROL_CLOCK`` hand (the
  runtime identity) on a backtest run, once, and records ``run_minds_declared
  {minds}`` with the kinds sorted; :func:`app.run_clock.run_minds` reads it back;
* it refuses, writing nothing: a firm agent (403), a live run, a second
  declaration, one after the clock moved, one after a firm agent acted, an
  unknown kind, an empty list, a kind twice, and anything under HALT;
* a declaration the ledger shows came after a firm agent's event (the race the
  lock cannot close for writes that take no lock) reads as ``None``, as does an
  undeclared run and a live one;
* ``fund-runtime backtest`` declares before it registers anyone: the run's
  ledger names ``scripted``, the declaration precedes every registration, and a
  run whose firm agent already acted is refused before any agent is made;
* the Runtime's provider→kind copy and the schema's ``MindKind`` agree with
  physics' ``MIND_KINDS``, and an unknown provider is declared ``model``.
"""

from __future__ import annotations

from typing import get_args

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.schemas import MindKind
from app.db.models import Agent, AgentRole, AgentStatus, Event
from app.ledger.events import (
    EVENT_AGENT_REGISTERED,
    EVENT_MESSAGE_SENT,
    EVENT_RUN_MINDS_DECLARED,
    append_event,
)
from app.registry.service import register_agent, seed_runtime_agent
from app.run_clock import (
    MIND_KINDS,
    RunMindsError,
    declare_minds,
    install_run_clock,
    run_minds,
)
from runtime import lockstep
from runtime.spec import AgentSpec
from tests.test_runtime_cli_backtest import _made, _run, keys, specs  # noqa: F401 - fixtures
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    _app,
    gov,
    live_afterwards,
    woke,
    world,
)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture
def client(SessionFactory, world):
    with TestClient(_app(SessionFactory)) as c:
        yield c


def _declarations(SessionFactory) -> list[Event]:
    with SessionFactory() as s:
        return list(s.execute(select(Event).where(Event.type == EVENT_RUN_MINDS_DECLARED)
                              .order_by(Event.id)).scalars())


def _minds(SessionFactory) -> tuple[str, ...] | None:
    with SessionFactory() as s:
        return run_minds(s)


@pytest.fixture
def on_run_clock(SessionFactory, world) -> None:
    """Writes straight to the ledger, as the server would: on the run's clock."""
    with SessionFactory() as s:
        install_run_clock(s)


def _runtime_id(SessionFactory) -> int:
    with SessionFactory() as s:
        return s.scalar(select(Agent.id).where(Agent.role == AgentRole.runtime))


# --- the declaration -----------------------------------------------------------------------

def test_the_runtime_declares_once_and_physics_reads_it_back(SessionFactory, world, client):
    assert _minds(SessionFactory) is None  # undeclared
    resp = client.post("/run/minds", headers=H(world["clock"]),
                       json={"minds": ["scripted", "cassette"]})
    assert resp.status_code == 201, resp.text
    assert resp.json()["minds"] == ["cassette", "scripted"]
    [event] = _declarations(SessionFactory)
    assert event.payload_json == {"minds": ["cassette", "scripted"]}
    assert event.actor_agent_id == _runtime_id(SessionFactory)
    assert resp.json()["event_id"] == event.id
    assert _minds(SessionFactory) == ("cassette", "scripted")


def test_a_second_declaration_is_refused(SessionFactory, world, client):
    assert client.post("/run/minds", headers=H(world["clock"]),
                       json={"minds": ["scripted"]}).status_code == 201
    resp = client.post("/run/minds", headers=H(world["clock"]), json={"minds": ["model"]})
    assert resp.status_code == 409 and "once" in resp.json()["detail"]
    assert len(_declarations(SessionFactory)) == 1
    assert _minds(SessionFactory) == ("scripted",)


def test_a_firm_agent_cannot_declare(SessionFactory, world, client):
    for key in (world["admin"], world["pm"][1]):
        resp = client.post("/run/minds", headers=H(key), json={"minds": ["model"]})
        assert resp.status_code == 403
    assert _declarations(SessionFactory) == []


def test_a_declaration_after_the_clock_moved_is_refused(SessionFactory, world, client):
    assert client.post("/clock/advance", headers=H(world["clock"]),
                       json={"days": 1}).status_code == 200
    resp = client.post("/run/minds", headers=H(world["clock"]), json={"minds": ["scripted"]})
    assert resp.status_code == 409 and "too late" in resp.json()["detail"]
    assert _declarations(SessionFactory) == []


def test_a_declaration_after_a_firm_agent_acted_is_refused(SessionFactory, world, client):
    assert client.get("/clock", headers=H(world["pm"][1])).status_code == 200  # a read writes nothing
    assert client.post("/messages", headers=H(world["pm"][1]),
                       json={"to": "broadcast", "body": "early"}).status_code == 201
    resp = client.post("/run/minds", headers=H(world["clock"]), json={"minds": ["scripted"]})
    assert resp.status_code == 409 and "too late" in resp.json()["detail"]
    assert _declarations(SessionFactory) == []


def test_a_firm_agents_refused_act_counts_as_acting(SessionFactory, world, client):
    """A ``permission_denied`` event names its actor: the agent did something in the run."""
    assert client.post("/clock/advance", headers=H(world["pm"][1]),
                       json={"days": 1}).status_code == 403
    resp = client.post("/run/minds", headers=H(world["clock"]), json={"minds": ["scripted"]})
    assert resp.status_code == 409


def test_the_runtimes_own_refused_act_does_not_spoil_the_declaration(SessionFactory, world,
                                                                     client):
    assert client.get("/agents", headers=H(world["clock"])).status_code == 403
    resp = client.post("/run/minds", headers=H(world["clock"]), json={"minds": ["scripted"]})
    assert resp.status_code == 201


@pytest.mark.parametrize("minds", [[], ["human"], ["Scripted"], ["scripted", "scripted"],
                                   ["scripted", "model", "cassette", "model"], "scripted",
                                   [1], None])
def test_a_bad_list_of_kinds_is_refused(SessionFactory, world, client, minds):
    resp = client.post("/run/minds", headers=H(world["clock"]), json={"minds": minds})
    assert resp.status_code == 422
    assert _declarations(SessionFactory) == []


def test_extra_fields_are_refused(SessionFactory, world, client):
    resp = client.post("/run/minds", headers=H(world["clock"]),
                       json={"minds": ["scripted"], "verified": True})
    assert resp.status_code == 422


def test_halt_refuses_the_declaration(SessionFactory, world, client, halt_file):
    halt_file.write_text("stop")
    resp = client.post("/run/minds", headers=H(world["clock"]), json={"minds": ["scripted"]})
    assert resp.status_code == 423
    assert _declarations(SessionFactory) == []


def test_a_live_run_declares_nothing(SessionFactory):
    with SessionFactory() as s:
        _, clock_key = seed_runtime_agent(s)
        s.commit()
    with TestClient(_app(SessionFactory)) as c:
        resp = c.post("/run/minds", headers=H(clock_key), json={"minds": ["scripted"]})
    assert resp.status_code == 409 and "backtest" in resp.json()["detail"]
    assert _declarations(SessionFactory) == [] and _minds(SessionFactory) is None


# --- the service, called directly -----------------------------------------------------------

@pytest.mark.parametrize("minds", [[], ["human"], "scripted", ("scripted", 1), [["model"]]])
def test_the_service_refuses_what_the_schema_would(SessionFactory, world, minds):
    with SessionFactory() as s:
        with pytest.raises(RunMindsError):
            declare_minds(s, minds=minds, actor_agent_id=_runtime_id(SessionFactory))
    assert _declarations(SessionFactory) == []


def test_a_declaration_that_lost_the_race_reads_as_none(SessionFactory, world, on_run_clock):
    """A firm agent's write that takes no lock (a message) can land between the
    check and the append. The ledger keeps the order; the reader trusts it."""
    rid = _runtime_id(SessionFactory)  # outside: closing a session rolls the shared one back
    with SessionFactory() as s:
        pm = s.scalar(select(Agent).where(Agent.name == "pm-1"))
        append_event(s, type=EVENT_MESSAGE_SENT, actor_agent_id=pm.id,
                     payload={"message_id": 0, "to": "broadcast", "from_agent_id": pm.id})
        append_event(s, type=EVENT_RUN_MINDS_DECLARED, actor_agent_id=rid,
                     payload={"minds": ["scripted"]})
        s.commit()
        assert run_minds(s) is None


def test_only_the_first_declaration_is_read(SessionFactory, world, on_run_clock):
    """Two declarations can exist only by a race; the second never replaces the first."""
    rid = _runtime_id(SessionFactory)
    with SessionFactory() as s:
        for kinds in (["scripted"], ["model"]):
            append_event(s, type=EVENT_RUN_MINDS_DECLARED, actor_agent_id=rid,
                         payload={"minds": kinds})
        s.commit()
        assert run_minds(s) == ("scripted",)


# --- the command ----------------------------------------------------------------------------

def test_the_command_declares_before_it_registers(SessionFactory, keys, specs, woke, capsys):
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 0, out
    assert _minds(SessionFactory) == ("scripted",)
    [declared] = _declarations(SessionFactory)
    with SessionFactory() as s:
        made = [e.id for e in s.execute(select(Event).where(
            Event.type == EVENT_AGENT_REGISTERED, Event.actor_agent_id.is_not(None))).scalars()]
    assert len(made) == 2 and declared.id < min(made)


def test_a_run_whose_firm_agent_acted_is_refused_before_any_agent_is_made(
        SessionFactory, keys, specs, woke, capsys, on_run_clock):
    with SessionFactory() as s:
        register_agent(s, name="early-bird", role=AgentRole.analyst,
                       actor_agent_id=s.scalar(select(Agent.id).where(Agent.name == "management")))
        s.commit()
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 1 and out["reason"] == "minds_refused:409" and out["registered"] == []
    assert set(_made(SessionFactory)) == {"early-bird"} and woke == []


# --- the copies agree -----------------------------------------------------------------------

def test_the_schema_and_the_runtime_name_physics_kinds():
    assert set(get_args(MindKind)) == MIND_KINDS
    assert set(lockstep._KIND.values()) | {"model"} == MIND_KINDS


def _spec(provider: str, adapter: str = "native") -> AgentSpec:
    return AgentSpec(id=f"x-{provider}-{adapter}", name=f"x-{provider}-{adapter}", role="pm",
                     pod=1, provider=provider, adapter=adapter, script="read-a", charter="c")


def test_an_unknown_provider_is_declared_a_model():
    assert lockstep.mind_kinds([_spec("scripted"), _spec("scripted")]) == ["scripted"]
    assert lockstep.mind_kinds([_spec("scripted"), _spec("metered")]) == ["model", "scripted"]


def test_a_zero_cost_provider_through_a_spending_adapter_is_a_model():
    """Audit c28 WARN 1: ``scripted`` through ``openclaw`` runs OpenClaw's own model."""
    assert lockstep.mind_kinds([_spec("scripted", "openclaw")]) == ["model"]
    assert lockstep.mind_kinds([_spec("cassette", "openclaw")]) == ["model"]
    assert lockstep.mind_kinds([_spec("cassette")]) == ["cassette"]


# --- audit c28 notes ------------------------------------------------------------------------

def test_a_deactivated_agents_event_still_counts_as_acting(SessionFactory, world, on_run_clock):
    rid = _runtime_id(SessionFactory)
    with SessionFactory() as s:
        pm = s.scalar(select(Agent).where(Agent.name == "pm-1"))
        append_event(s, type=EVENT_MESSAGE_SENT, actor_agent_id=pm.id,
                     payload={"message_id": 0, "to": "broadcast", "from_agent_id": pm.id})
        pm.status = AgentStatus.inactive
        s.commit()
        with pytest.raises(RunMindsError, match="too late"):
            declare_minds(s, minds=["scripted"], actor_agent_id=rid)


def test_a_declaration_a_firm_agent_wrote_is_never_read(SessionFactory, world, on_run_clock):
    """No route lets a firm agent write the type; the reader does not rely on that."""
    with SessionFactory() as s:
        admin = s.scalar(select(Agent.id).where(Agent.name == "management"))
        rid = s.scalar(select(Agent.id).where(Agent.role == AgentRole.runtime))
        append_event(s, type=EVENT_RUN_MINDS_DECLARED, actor_agent_id=admin,
                     payload={"minds": ["scripted"]})
        s.commit()
        assert run_minds(s) is None
        append_event(s, type=EVENT_RUN_MINDS_DECLARED, actor_agent_id=None,
                     payload={"minds": ["scripted"]})
        s.commit()
        assert run_minds(s) is None
        # The forged one is a firm agent's event: the runtime's own declaration is now late.
        with pytest.raises(RunMindsError, match="too late"):
            declare_minds(s, minds=["model"], actor_agent_id=rid)
