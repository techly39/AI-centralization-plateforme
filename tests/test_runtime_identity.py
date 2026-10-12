"""The world's clock belongs to the Runtime (ADR-033, B-032, B-000f).

Claims under test:

* ``CONTROL_CLOCK`` is held by ``runtime`` and ``system`` only — no firm role.
* The ``runtime`` identity may read and advance the clock and do nothing a
  participant does (no order, message, registration, market data, directory).
* It is created only by ``fund-env seed-runtime`` / :func:`seed_runtime_agent`,
  one per database; it can never be registered over HTTP or deactivated by a
  firm agent, and nobody may register its name or ``system``'s.
* ``system`` is found by role, so a name can no longer make an agent physics.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import cli
from app.clock import LiveClock, get_clock, set_clock
from app.db.models import Agent, AgentRole, AgentStatus, Event
from app.ledger.events import EVENT_CLOCK_ADVANCED, EVENT_PERMISSION_DENIED
from app.registry.permissions import PHYSICS_ROLES, Action, has_permission
from app.registry.pods import create_pod, fund_pod
from app.registry.security import generate_api_key, hash_api_key
from app.registry.service import (
    RUNTIME_AGENT_NAME,
    RegistryError,
    ReservedIdentityError,
    get_or_create_system_agent,
    is_reserved_name,
    register_agent,
    seed_runtime_agent,
)
from app.run_clock import start_backtest

START = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


@pytest.fixture
def world(SessionFactory) -> dict:
    """A backtest at START with management, a funded desk, a PM, an analyst and
    the runtime identity."""
    s = SessionFactory()
    try:
        start_backtest(s, start=START)
        mgmt, admin = register_agent(s, name="management", role=AgentRole.management)
        pod = create_pod(s, name="desk")
        fund_pod(s, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(s), reason="seed")
        _, pm = register_agent(s, name="pm", role=AgentRole.pm, pod_id=pod.id)
        _, an = register_agent(s, name="an", role=AgentRole.analyst, pod_id=pod.id)
        rt, runtime = seed_runtime_agent(s)
        s.commit()
        ids = {"pod_id": pod.id, "runtime_id": rt.id, "admin_id": mgmt.id}
    finally:
        s.close()
    return {"admin": admin, "pm": pm, "an": an, "runtime": runtime, **ids}


def _events(db, type_: str | None = None) -> list[Event]:
    db.expire_all()
    q = select(Event).order_by(Event.id)
    if type_ is not None:
        q = q.where(Event.type == type_)
    return list(db.execute(q).scalars())


# --- the matrix --------------------------------------------------------------

def test_only_physics_holds_control_clock():
    holders = {r for r in AgentRole if has_permission(r, Action.CONTROL_CLOCK)}
    assert holders == {AgentRole.runtime, AgentRole.system}


def test_the_runtime_role_is_halt_and_clock_only():
    granted = {a for a in Action if has_permission(AgentRole.runtime, a)}
    assert granted == {Action.READ_HALT, Action.READ_CLOCK, Action.CONTROL_CLOCK}


def test_physics_roles_are_exactly_system_and_runtime():
    assert PHYSICS_ROLES == {AgentRole.system, AgentRole.runtime}


# --- over HTTP ---------------------------------------------------------------

def test_management_may_not_advance_and_is_recorded(client, world, db):
    resp = client.post("/clock/advance", headers=H(world["admin"]), json={"days": 1})
    assert resp.status_code == 403, resp.text
    assert get_clock().now() == START
    assert not _events(db, EVENT_CLOCK_ADVANCED)
    [denied] = _events(db, EVENT_PERMISSION_DENIED)
    assert denied.actor_agent_id == world["admin_id"]
    assert denied.payload_json["action"] == "control_clock"


def test_the_runtime_identity_advances_the_clock(client, world, db):
    resp = client.post("/clock/advance", headers=H(world["runtime"]), json={"days": 1})
    assert resp.status_code == 200, resp.text
    [adv] = _events(db, EVENT_CLOCK_ADVANCED)
    assert adv.actor_agent_id == world["runtime_id"]
    assert client.get("/clock", headers=H(world["pm"])).json()["now"].startswith("2024-01-03")


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/orders", {"ticker": "AAPL", "side": "buy", "qty": 1,
                         "price_type": "market", "justification": "t"}),
    ("POST", "/messages", {"to": "pm", "type": "note", "body": "buy"}),
    ("POST", "/agents/register", {"name": "mole", "role": "pm", "pod_id": 1}),
    ("GET", "/agents", None),
    ("GET", "/price/AAPL", None),
    ("GET", "/portfolio/1", None),
    ("GET", "/events", None),
    ("GET", "/messages", None),
    ("POST", "/costs", {"tokens_in": 1, "tokens_out": 1, "usd_cost": 0.01}),
    ("POST", "/tasks/start", {"subject": "tick"}),
])
def test_the_runtime_identity_does_nothing_a_participant_does(
    client, world, db, method, path, body
):
    before = len(_events(db))
    resp = client.request(method, path, headers=H(world["runtime"]), json=body)
    assert resp.status_code == 403, (path, resp.status_code, resp.text)
    new = _events(db)[before:]
    assert [e.type for e in new] == [EVENT_PERMISSION_DENIED], (path, [e.type for e in new])


def test_the_runtime_identity_may_ask_who_it_is_the_time_and_the_halt(client, world):
    me = client.get("/me", headers=H(world["runtime"])).json()
    assert (me["name"], me["role"], me["pod_id"]) == (RUNTIME_AGENT_NAME, "runtime", None)
    assert client.get("/clock", headers=H(world["runtime"])).status_code == 200
    assert client.get("/halt", headers=H(world["runtime"])).status_code == 200


def test_a_halted_world_refuses_the_runtimes_advance(client, world, halt_file, db):
    halt_file.touch()
    resp = client.post("/clock/advance", headers=H(world["runtime"]), json={"days": 1})
    assert resp.status_code == 423
    assert get_clock().now() == START and not _events(db, EVENT_CLOCK_ADVANCED)


@pytest.mark.parametrize("role", ["runtime", "system"])
def test_physics_roles_cannot_be_registered_over_http(client, admin_key, db, role):
    resp = client.post("/agents/register", headers=H(admin_key),
                       json={"name": "x", "role": role, "pod_id": None})
    assert resp.status_code == 422
    assert db.scalar(select(Agent).where(Agent.name == "x")) is None


@pytest.mark.parametrize("name", [
    "system", "runtime", "System", "RUNTIME", " runtime ", "runtime\n",
    "ｓｙｓｔｅｍ",              # fullwidth: NFKC folds it
    "sys​tem",            # zero-width space (Cf) dropped
    "ſystem",                  # long s: casefold folds it
])
def test_reserved_names_cannot_be_registered(client, admin_key, db, name):
    resp = client.post("/agents/register", headers=H(admin_key),
                       json={"name": name, "role": "analyst", "pod_id": None})
    assert resp.status_code == 409, (name, resp.status_code, resp.text)
    assert db.scalar(select(Agent).where(Agent.name == name)) is None


@pytest.mark.parametrize("name", ["systems", "runtime-pm", "my runtime", "sys tem"])
def test_names_that_merely_contain_a_reserved_word_are_fine(name):
    assert not is_reserved_name(name)


@pytest.mark.parametrize("target", ["runtime_id", "system"])
def test_management_cannot_switch_off_physics(client, world, db, target):
    if target == "system":
        target_id = get_or_create_system_agent(db).id
        db.commit()
    else:
        target_id = world[target]
    resp = client.post(f"/agents/{target_id}/deactivate", headers=H(world["admin"]))
    assert resp.status_code == 403, resp.text
    db.expire_all()
    assert db.get(Agent, target_id).status is AgentStatus.active
    denied = _events(db, EVENT_PERMISSION_DENIED)[-1]
    assert denied.payload_json["action"] == "deactivate_agents"
    assert denied.payload_json["target_agent_id"] == target_id
    assert denied.payload_json["reason"] == "reserved_identity"
    assert not _events(db, "agent_deactivated")
    # ... and the clock hand still works.
    assert client.post("/clock/advance", headers=H(world["runtime"]),
                       json={"days": 1}).status_code == 200


def test_management_still_deactivates_firm_agents(client, world, db):
    """The guard is about physics' roles, not a blanket refusal."""
    pm_id = client.get("/me", headers=H(world["pm"])).json()["id"]
    resp = client.post(f"/agents/{pm_id}/deactivate", headers=H(world["admin"]))
    assert resp.status_code == 200, resp.text


# --- the service and the CLI -------------------------------------------------

@pytest.mark.parametrize("role", sorted(PHYSICS_ROLES, key=lambda r: r.value))
def test_register_agent_refuses_physics_roles(db, role):
    with pytest.raises(ReservedIdentityError):
        register_agent(db, name="anything", role=role)


def test_one_runtime_identity_per_database(db):
    agent, key = seed_runtime_agent(db)
    db.commit()
    assert agent.role is AgentRole.runtime and agent.pod_id is None and key
    with pytest.raises(ReservedIdentityError, match="already has a runtime identity"):
        seed_runtime_agent(db)
    db.rollback()
    assert len(db.scalars(select(Agent).where(Agent.role == AgentRole.runtime)).all()) == 1
    [registered] = _events(db, "agent_registered")
    assert registered.payload_json["role"] == "runtime"


def test_system_is_found_by_role_not_name(db):
    """A system row under another name (as a migrated database might hold) is
    still the system identity; no second one is created."""
    row = Agent(name="physics", role=AgentRole.system, pod_id=None,
                api_key_hash=hash_api_key(generate_api_key()), status=AgentStatus.active,
                created_at=START)
    db.add(row)
    db.flush()
    assert get_or_create_system_agent(db).id == row.id
    assert len(db.scalars(select(Agent).where(Agent.role == AgentRole.system)).all()) == 1


def test_a_pre_adr_squatter_fails_loudly_never_becomes_system(db):
    """A database written before ADR-033 may hold an analyst named 'system'.
    The app refuses to borrow its identity rather than attribute to it."""
    squatter = Agent(name="system", role=AgentRole.analyst, pod_id=None,
                     api_key_hash=hash_api_key(generate_api_key()), status=AgentStatus.active,
                     created_at=START)
    db.add(squatter)
    db.flush()
    with pytest.raises(ReservedIdentityError, match="non-system agent"):
        get_or_create_system_agent(db)


def test_a_reserved_identity_error_is_a_registry_error():
    """Callers that catch RegistryError (CLI, API) keep catching it."""
    assert issubclass(ReservedIdentityError, RegistryError)


@pytest.fixture
def cli_on_test_db(SessionFactory, monkeypatch) -> None:
    @contextmanager
    def scope() -> Iterator:
        s = SessionFactory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)


def test_cli_seed_runtime_prints_a_working_key_once(cli_on_test_db, client, capsys, db):
    assert cli.main(["seed-runtime"]) == 0
    out = capsys.readouterr().out
    key = out.strip().splitlines()[-1].strip()
    assert client.get("/me", headers=H(key)).json()["role"] == "runtime"
    assert cli.main(["seed-runtime"]) == 1
    assert "already has a runtime identity" in capsys.readouterr().err
