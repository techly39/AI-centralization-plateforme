"""A way back from a lost clock key, and reserved identities checked at startup (B-041).

Claims under test:

* ``fund-env rotate-runtime-key`` / :func:`rotate_runtime_key` gives the one
  runtime identity a new key; the old key gets 401 in the same commit; the event
  ``agent_key_rotated`` names the agent and carries neither key nor hash.
* It refuses a database with no runtime identity, and one with two.
* The server and every operator command that runs on the database's clock refuse
  to start on a database where a firm agent wears a reserved name, or where more
  than one runtime row exists — before the clock is installed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cli
from app.clock import LiveClock, get_clock, set_clock
from app.db.base import get_session
from app.db.models import Agent, AgentRole, AgentStatus, Event
from app.ledger.events import EVENT_AGENT_KEY_ROTATED
from app.main import create_app
from app.registry.security import generate_api_key, hash_api_key
from app.registry.service import (
    RegistryError,
    ReservedIdentityError,
    _create_agent,
    check_reserved_identities,
    reserved_identity_problems,
    rotate_runtime_key,
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


def _squat(db, name: str, role: AgentRole = AgentRole.analyst) -> Agent:
    """An agent as a database written before ADR-033 (or by hand) may hold it."""
    row = Agent(name=name, role=role, pod_id=None,
                api_key_hash=hash_api_key(generate_api_key()), status=AgentStatus.active,
                created_at=START)
    db.add(row)
    db.flush()
    return row


# --- rotation ---------------------------------------------------------------------------

def test_rotation_kills_the_old_key_and_the_new_one_advances(client, db):
    start_backtest(db, start=START)
    agent, old = seed_runtime_agent(db)
    db.commit()
    assert client.post("/clock/advance", json={"days": 1}, headers=H(old)).status_code == 200

    same, new = rotate_runtime_key(db)
    db.commit()
    assert same.id == agent.id and new != old
    assert client.get("/me", headers=H(old)).status_code == 401
    assert client.post("/clock/advance", json={"days": 1}, headers=H(old)).status_code == 401
    r = client.post("/clock/advance", json={"days": 1}, headers=H(new))
    assert r.status_code == 200, r.text
    assert client.get("/me", headers=H(new)).json()["role"] == "runtime"


def test_rotation_records_the_agent_and_never_the_secret(db):
    agent, old = seed_runtime_agent(db)
    _, new = rotate_runtime_key(db)
    db.commit()
    [event] = db.scalars(select(Event).where(Event.type == EVENT_AGENT_KEY_ROTATED)).all()
    assert event.payload_json == {"agent_id": agent.id} and event.actor_agent_id is None
    every_event = json.dumps([e.payload_json for e in db.scalars(select(Event)).all()])
    for secret in (old, new, hash_api_key(old), hash_api_key(new)):
        assert secret not in every_event


def test_rotation_keeps_one_identity_and_its_name(db):
    seed_runtime_agent(db)
    rotate_runtime_key(db)
    rotate_runtime_key(db)
    db.commit()
    rows = db.scalars(select(Agent).where(Agent.role == AgentRole.runtime)).all()
    assert [(r.name, r.status) for r in rows] == [("runtime", AgentStatus.active)]


def test_rotation_needs_a_runtime_identity(db):
    with pytest.raises(RegistryError, match="no runtime identity"):
        rotate_runtime_key(db)
    assert db.scalars(select(Event).where(Event.type == EVENT_AGENT_KEY_ROTATED)).all() == []


def test_rotation_refuses_two_runtime_identities(db):
    seed_runtime_agent(db)
    _create_agent(db, name="clock-2", role=AgentRole.runtime, pod_id=None, charter_ref=None,
                  research_domains=None, actor_agent_id=None)
    with pytest.raises(ReservedIdentityError, match="2 runtime identities"):
        rotate_runtime_key(db)


def test_rotation_touches_no_firm_agent(db, admin_key):
    seed_runtime_agent(db)
    before = {a.id: a.api_key_hash for a in db.scalars(select(Agent)).all()
              if a.role is not AgentRole.runtime}
    rotate_runtime_key(db)
    db.commit()
    db.expire_all()
    after = {a.id: a.api_key_hash for a in db.scalars(select(Agent)).all()
             if a.role is not AgentRole.runtime}
    assert after == before


def test_there_is_no_endpoint_for_rotation(client):
    """Operator-only: no published route rotates a key."""
    paths = {getattr(r, "path", "") for r in client.app.routes}
    assert not any("rotate" in p or "key" in p for p in paths), paths


# --- the operator CLI -------------------------------------------------------------------

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


def test_cli_rotation_prints_a_working_key_once(cli_on_test_db, client, capsys):
    assert cli.main(["rotate-runtime-key"]) == 1
    assert "no runtime identity" in capsys.readouterr().err
    assert cli.main(["seed-runtime"]) == 0
    old = capsys.readouterr().out.strip().splitlines()[-1].strip()
    assert cli.main(["rotate-runtime-key"]) == 0
    out = capsys.readouterr().out
    new = out.strip().splitlines()[-1].strip()
    assert out.count(new) == 1 and old not in out
    assert client.get("/me", headers=H(old)).status_code == 401
    assert client.get("/me", headers=H(new)).json()["role"] == "runtime"


@pytest.mark.parametrize("name", ["system", "runtime", "SYSTEM", " runtime ", "runtime️"])
def test_cli_refuses_a_database_with_a_reserved_name_squatter(cli_on_test_db, db, capsys,
                                                               name):
    _squat(db, name)
    db.commit()
    assert cli.main(["create-pod", "--name", "desk"]) == 1
    err = capsys.readouterr().err
    assert "reserved" in err and "operator must repair" in err


_ARGS = {"seed-admin": [], "seed-runtime": [], "rotate-runtime-key": [],
         "create-pod": ["--name", "desk"], "fund-pod": ["--pod-id", "1", "--delta", "1"],
         "check-orders": [], "rebuild-state": []}


def test_the_cli_table_above_is_every_command_on_the_database_clock():
    commands = set(cli.build_parser()._subparsers._group_actions[0].choices)
    assert set(_ARGS) == commands - cli._NO_RUN_CLOCK


@pytest.mark.parametrize("command", sorted(_ARGS))
def test_every_command_on_the_database_clock_refuses_a_squatted_database(
        cli_on_test_db, db, capsys, command):
    _squat(db, "system")
    db.commit()
    count = len(db.scalars(select(Event)).all())
    assert cli.main([command, *_ARGS[command]]) == 1
    assert "holds the reserved name 'system'" in capsys.readouterr().err
    db.expire_all()
    assert len(db.scalars(select(Event)).all()) == count   # nothing was written


# --- startup ----------------------------------------------------------------------------

def _app_on(SessionFactory):
    app = create_app()

    def _session() -> Iterator:
        s = SessionFactory()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_session] = _session
    return app


def test_the_server_refuses_to_start_on_a_squatted_database(SessionFactory, db):
    start_backtest(db, start=START)
    set_clock(LiveClock())
    _squat(db, "system")
    db.commit()
    before = get_clock()
    with pytest.raises(ReservedIdentityError, match="holds the reserved name 'system'"):
        with TestClient(_app_on(SessionFactory)):
            pass
    # Refused before the clock was installed: the process's clock is untouched.
    assert get_clock() is before


def test_the_server_refuses_two_runtime_identities(SessionFactory, db):
    seed_runtime_agent(db)
    _create_agent(db, name="clock-2", role=AgentRole.runtime, pod_id=None, charter_ref=None,
                  research_domains=None, actor_agent_id=None)
    db.commit()
    with pytest.raises(ReservedIdentityError, match="2 runtime identities"):
        with TestClient(_app_on(SessionFactory)):
            pass


def test_a_healthy_database_starts(SessionFactory, db, admin_key):
    seed_runtime_agent(db)
    db.commit()
    assert reserved_identity_problems(db) == []
    check_reserved_identities(db)
    with TestClient(_app_on(SessionFactory)) as c:
        assert c.get("/me", headers=H(admin_key)).status_code == 200


def test_physics_rows_wearing_their_own_names_are_no_problem(db):
    from app.registry.service import get_or_create_system_agent
    get_or_create_system_agent(db)
    seed_runtime_agent(db)
    assert reserved_identity_problems(db) == []


def test_seeding_beside_a_runtime_squatter_is_refused_by_the_service(db):
    """Audit c24 WARN 1: the startup check now fires first in the CLI, so this pins
    the service's own guard for callers that bypass the CLI (R-3b-2 provisioning)."""
    _squat(db, "runtime", AgentRole.management)
    with pytest.raises(RegistryError, match="already exists"):
        seed_runtime_agent(db)
    assert not db.scalars(select(Agent).where(Agent.role == AgentRole.runtime)).all()


def test_every_problem_is_named_at_once(db):
    a = _squat(db, "system")
    b = _squat(db, "Runtime", AgentRole.pm)
    problems = reserved_identity_problems(db)
    assert len(problems) == 2
    assert str(a.id) in problems[0] and str(b.id) in problems[1]
