"""RED-TEAM 0014 — attacks on cycle 0023's runtime clock identity (ADR-033, B-032, B-000f).

Claims under attack:

* ``CONTROL_CLOCK`` belongs to ``runtime`` (and keyless ``system``) only; management
  lost it. The ``runtime`` role holds READ_HALT, READ_CLOCK, CONTROL_CLOCK and
  nothing else.
* ``PHYSICS_ROLES = {system, runtime}`` are never registered (HTTP 422, service
  ``ReservedIdentityError``) and never deactivated by a firm agent (403, logged).
* The runtime identity is created only by ``fund-env seed-runtime`` /
  :func:`seed_runtime_agent`, one per database. ``system`` is found by role.
* The names ``system`` / ``runtime`` are reserved after NFKC + casefold + dropping
  Cf characters + strip — "the name as a reader sees it". (As attacked at 3cea548;
  since the H1 fix the fold drops Cc Cf Cn Co Cs Mn Me and the blank letters.)

Attacker: a firm agent (management, PM, analyst) holding its own key and the MCP
tools; for the operator path, the operator CLI on backtest / live / halted DBs.

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.

Run against 3cea548.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import cli
from app.bus.messages import send_message
from app.clock import LiveClock, get_clock, set_clock
from app.db.models import Agent, AgentRole, AgentStatus, Event
from app.ledger.events import EVENT_AGENT_REGISTERED, EVENT_CLOCK_ADVANCED
from app.ledger.rebuild import rebuild_state
from app.bus.errors import SenderNotPermittedError
from app.oms.errors import RoleNotPermittedError
from app.oms.service import place_order
from app.registry.pods import create_pod, fund_pod
from app.registry.security import generate_api_key, hash_api_key
from app.registry.service import (
    RUNTIME_AGENT_NAME,
    RegistryError,
    get_or_create_system_agent,
    is_reserved_name,
    register_agent,
    seed_runtime_agent,
)
from app.run_clock import start_backtest
from runtime.spec import AgentSpec

START = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


@pytest.fixture
def world(SessionFactory) -> dict:
    """A backtest at START: management, a funded desk with a PM and analyst, the runtime."""
    s = SessionFactory()
    try:
        start_backtest(s, start=START)
        mgmt, admin = register_agent(s, name="boss", role=AgentRole.management)
        pod = create_pod(s, name="desk")
        fund_pod(s, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(s), reason="seed")
        pm_row, pm = register_agent(s, name="pm", role=AgentRole.pm, pod_id=pod.id)
        _, an = register_agent(s, name="an", role=AgentRole.analyst, pod_id=pod.id)
        rt, runtime = seed_runtime_agent(s)
        system_id = get_or_create_system_agent(s).id
        s.commit()
        ids = {"pod_id": pod.id, "runtime_id": rt.id, "admin_id": mgmt.id,
               "pm_id": pm_row.id, "system_id": system_id}
    finally:
        s.close()
    return {"admin": admin, "pm": pm, "an": an, "runtime": runtime, **ids}


@pytest.fixture
def cli_on_test_db(SessionFactory, monkeypatch) -> None:
    @contextmanager
    def scope() -> Iterator:
        s = SessionFactory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)


def _events(db, type_: str | None = None) -> list[Event]:
    db.expire_all()
    q = select(Event).order_by(Event.id)
    if type_ is not None:
        q = q.where(Event.type == type_)
    return list(db.execute(q).scalars())


# =============================================================================
# HOLES
# =============================================================================

# H1 (low) — the reserved names can be worn with an invisible character that is
# not in category Cf. ``_name_key`` claims to compare "the name as a reader sees
# it", dropping invisible characters, but it only drops Cf. Unicode's
# Default_Ignorable_Code_Point set also holds nonspacing marks (variation
# selectors FE00-FE0F / E0100-E01EF, the combining grapheme joiner U+034F, Khmer
# U+17B4) and letters (Hangul fillers U+115F/U+1160/U+3164/U+FFA0) that render as
# nothing; U+2800 (braille blank) and NUL render as nothing or blank in most UIs.
# Management registers e.g. "runtime️": the directory every agent reads
# (GET /agents) then shows a second "runtime", a firm agent passing for the
# world's clock hand to colleagues who ask "who is the runtime?". The role still
# gates CONTROL_CLOCK, so physics is not fooled — only the directory, which the
# ADR says the reservation exists to keep honest.
_INVISIBLE_WEARS = [
    pytest.param("runtime️", id="VS16-FE0F"),
    pytest.param("system︀", id="VS1-FE00"),
    pytest.param("runtime\U000e0100", id="VS17-E0100"),
    pytest.param("system͏", id="CGJ-034F"),
    pytest.param("runtime឴", id="khmer-17B4"),
    pytest.param("systemᅟ", id="hangul-filler-115F"),
    pytest.param("runtimeㅤ", id="hangul-filler-3164"),
    pytest.param("runtimeﾠ", id="halfwidth-hangul-filler-FFA0"),
    pytest.param("system⠀", id="braille-blank-2800"),
    pytest.param("runtime\x00", id="NUL"),
]


# Fixed in cycle 23 (ADR-033 amendment (a)): the fold drops every category that
# draws nothing (Cc Cf Cn Co Cs Mn Me) and the blank letters. The hole tests are
# now guards and keep their names.
@pytest.mark.parametrize("name", _INVISIBLE_WEARS)
def test_hole_reserved_name_worn_with_a_default_ignorable_character(name):
    assert is_reserved_name(name)


@pytest.mark.parametrize("name", _INVISIBLE_WEARS)
def test_hole_management_registers_a_lookalike_runtime_over_http(client, world, db, name):
    resp = client.post("/agents/register", headers=H(world["admin"]),
                       json={"name": name, "role": "analyst", "pod_id": None})
    assert resp.status_code == 409, (ascii(name), resp.status_code, resp.text)


# =============================================================================
# HELD — attacks that failed; kept as regression guards
# =============================================================================

# --- the runtime key does halt and clock, nothing else ------------------------

_EVERY_ROUTE = [
    ("GET", "/agents", None),
    ("POST", "/agents/register", {"name": "mole", "role": "management"}),
    ("POST", "/agents/1/deactivate", None),
    ("GET", "/events", None),
    ("GET", "/price/AAPL", None),
    ("GET", "/ohlcv/AAPL", None),
    ("GET", "/orders", None),
    ("GET", "/orders?pod=1", None),
    ("POST", "/orders", {"ticker": "AAPL", "side": "buy", "qty": 1,
                         "price_type": "market", "justification": "t"}),
    ("DELETE", "/orders/1", None),
    ("GET", "/portfolio/1", None),
    ("GET", "/messages", None),
    ("GET", "/messages?agent=1", None),
    ("POST", "/messages", {"to": "broadcast", "type": "note", "body": "x"}),
    ("POST", "/costs", {"tokens_in": 1, "tokens_out": 1, "usd_cost": 0.01}),
    ("POST", "/tasks/start", {"subject": "tick"}),
    ("POST", "/tasks/end", {"task_id": 1, "status": "done"}),
    ("GET", "/metrics/pod/1", None),
    ("GET", "/metrics/leaderboard", None),
]


def _template(path: str) -> str:
    """'/orders/1?pod=1' -> '/orders/{}'; '/price/AAPL' -> '/price/{}'."""
    parts = path.split("?")[0].split("/")
    return "/".join("{}" if (p.isdigit() or p == "AAPL") else p for p in parts)


def test_held_every_route_but_me_clock_halt_refuses_the_runtime_key(client, world):
    """Walk the whole published surface, not a sample: any route answering the
    runtime key other than /me, /clock, /halt, /clock/advance, /health is a
    participant act. The first assert proves the sweep covers every route."""
    import re

    paths = client.app.openapi()["paths"]
    published = {(m.upper(), re.sub(r"\{[^}]+\}", "{}", p)) for p, ops in paths.items()
                 for m in ops}
    allowed = {("GET", "/me"), ("GET", "/clock"), ("GET", "/halt"),
               ("POST", "/clock/advance"), ("GET", "/health")}
    swept = {(m, _template(p)) for m, p, _ in _EVERY_ROUTE}
    assert published - allowed <= swept, published - allowed - swept
    for method, path, body in _EVERY_ROUTE:
        resp = client.request(method, path, headers=H(world["runtime"]), json=body)
        assert resp.status_code in (403, 422), (method, path, resp.status_code, resp.text)


def test_held_runtime_cannot_act_through_the_services_either(db, world):
    """The service layer re-checks the matrix: the runtime row cannot trade or
    speak even when code calls the service directly with it as actor."""
    rt = db.get(Agent, world["runtime_id"])
    with pytest.raises(RoleNotPermittedError):
        place_order(db, actor=rt, ticker="AAPL", side="buy", qty=1, price_type="market",
                    justification="x")
    db.rollback()
    with pytest.raises(SenderNotPermittedError):
        send_message(db, sender=rt, to=f"agent:{world['pm_id']}", body="buy everything")
    db.rollback()


def test_held_runtime_cannot_deactivate_physics_or_anyone(client, world, db):
    for target in (world["runtime_id"], world["system_id"], world["pm_id"]):
        r = client.post(f"/agents/{target}/deactivate", headers=H(world["runtime"]))
        assert r.status_code == 403, r.text
    db.expire_all()
    assert all(db.get(Agent, i).status is AgentStatus.active
               for i in (world["runtime_id"], world["system_id"], world["pm_id"]))


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "PUT", "PATCH"])
def test_held_halt_cannot_be_dodged_with_a_read_method_on_advance(
    client, world, halt_file, db, method
):
    """refuse_if_halted lets GET/HEAD/OPTIONS through; none of them moves the clock."""
    halt_file.touch()
    client.request(method, "/clock/advance", headers=H(world["runtime"]), json={"days": 1})
    assert get_clock().now() == START and not _events(db, EVENT_CLOCK_ADVANCED)


# --- no firm role gets a clock hand -------------------------------------------

@pytest.mark.parametrize("who", ["admin", "pm", "an"])
def test_held_no_firm_key_moves_the_clock(client, world, db, who):
    for body in ({"days": 1}, {"minutes": 1}, {"days": 0, "minutes": 1440}):
        r = client.post("/clock/advance", headers=H(world[who]), json=body)
        assert r.status_code == 403, r.text
    assert get_clock().now() == START and not _events(db, EVENT_CLOCK_ADVANCED)


@pytest.mark.parametrize("role", ["Runtime", "RUNTIME", " runtime", "runtime ", "System",
                                  "system​", "ｒｕｎｔｉｍｅ", "runtime\x00"])
def test_held_role_spelling_variants_are_422(client, world, db, role):
    before = db.scalar(select(Agent.id).order_by(Agent.id.desc()).limit(1))
    r = client.post("/agents/register", headers=H(world["admin"]),
                    json={"name": "x-variant", "role": role, "pod_id": None})
    assert r.status_code == 422, r.text
    assert db.scalar(select(Agent.id).order_by(Agent.id.desc()).limit(1)) == before


def test_held_a_mind_spec_cannot_name_a_physics_role():
    for role in ("runtime", "system"):
        with pytest.raises(ValidationError):
            AgentSpec(id="x", name="x", role=role, provider="scripted",
                      script="moving-average-pm", charter="c")


def test_held_management_deactivating_physics_is_403_and_a_second_hand_never_appears(
    client, world, db
):
    """After a refused deactivation, seed-runtime still refuses a second identity."""
    r = client.post(f"/agents/{world['runtime_id']}/deactivate", headers=H(world["admin"]))
    assert r.status_code == 403
    with pytest.raises(RegistryError):
        seed_runtime_agent(db)
    db.rollback()
    assert len(db.scalars(select(Agent).where(Agent.role == AgentRole.runtime)).all()) == 1


def test_held_the_name_constraint_backs_one_runtime_per_database(db, world):
    """Two seeders racing past the role check both insert name 'runtime': the
    unique name constraint refuses the second at the database, so a race yields
    an error, never two hands."""
    db.add(Agent(name=RUNTIME_AGENT_NAME, role=AgentRole.runtime, pod_id=None,
                 api_key_hash=hash_api_key(generate_api_key()),
                 status=AgentStatus.active, created_at=START))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_held_advance_is_attributed_to_the_runtime_and_fills_to_the_pm(client, world, db,
                                                                         prices):
    r = client.post("/orders", headers=H(world["pm"]),
                    json={"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "limit",
                          "limit_price": 150.0, "justification": "dip"})
    assert r.status_code == 201, r.text
    prices.set_price("AAPL", 140.0)
    adv = client.post("/clock/advance", headers=H(world["runtime"]), json={"days": 1})
    assert adv.status_code == 200 and adv.json()["filled_order_ids"]
    [ev] = _events(db, EVENT_CLOCK_ADVANCED)
    assert ev.actor_agent_id == world["runtime_id"]
    fills = _events(db, "order_filled")
    assert fills and all(e.actor_agent_id == world["pm_id"] for e in fills)


# --- the operator path ----------------------------------------------------------

def test_held_seed_runtime_in_a_fresh_process_stamps_the_runs_time(
    cli_on_test_db, SessionFactory, client, capsys, db
):
    """A backtest DB, a new process on the live clock: seed-runtime installs the
    run clock first, so no wall-time stamp holds the ledger (ADR-025)."""
    s = SessionFactory()
    start_backtest(s, start=START)
    s.commit()
    s.close()
    set_clock(LiveClock())                         # a fresh CLI process
    assert cli.main(["seed-runtime"]) == 0
    key = capsys.readouterr().out.strip().splitlines()[-1].strip()
    [reg] = _events(db, EVENT_AGENT_REGISTERED)
    assert reg.ts == START and reg.actor_agent_id is None
    rt = db.scalar(select(Agent).where(Agent.role == AgentRole.runtime))
    assert rt.created_at == START
    assert client.post("/clock/advance", headers=H(key), json={"days": 1}).status_code == 200


def test_held_seed_runtime_on_a_live_db_is_a_hand_with_nothing_to_move(
    cli_on_test_db, client, capsys, db
):
    assert cli.main(["seed-runtime"]) == 0
    key = capsys.readouterr().out.strip().splitlines()[-1].strip()
    r = client.post("/clock/advance", headers=H(key), json={"days": 1})
    assert r.status_code == 409
    assert not _events(db, EVENT_CLOCK_ADVANCED)


def test_held_seed_runtime_under_halt_seeds_but_the_hand_cannot_move(
    cli_on_test_db, SessionFactory, client, capsys, db, halt_file
):
    """Operator commands are the Human's hands and are not gated (halt.py); the
    identity they create is gated like every key."""
    s = SessionFactory()
    start_backtest(s, start=START)
    s.commit()
    s.close()
    halt_file.touch()
    assert cli.main(["seed-runtime"]) == 0
    key = capsys.readouterr().out.strip().splitlines()[-1].strip()
    assert client.post("/clock/advance", headers=H(key), json={"days": 1}).status_code == 423
    assert get_clock().now() == START and not _events(db, EVENT_CLOCK_ADVANCED)


def test_held_a_pre_adr_runtime_squatter_blocks_seeding_loudly(db, cli_on_test_db, capsys):
    """A DB written before ADR-033 may hold management named 'runtime'. seed-runtime
    neither adopts it nor creates a second 'runtime': it fails and says why."""
    db.add(Agent(name="runtime", role=AgentRole.management, pod_id=None,
                 api_key_hash=hash_api_key(generate_api_key()),
                 status=AgentStatus.active, created_at=START))
    db.commit()
    assert cli.main(["seed-runtime"]) == 1
    # Since B-041 (cycle 24) the CLI refuses the squatted database at startup,
    # before seed-runtime runs, and names the squatter (was: "already exists").
    err = capsys.readouterr().err
    assert "holds the reserved name 'runtime'" in err and "management" in err
    assert not db.scalars(select(Agent).where(Agent.role == AgentRole.runtime)).all()


def test_held_seed_runtime_on_an_alembic_migrated_db(tmp_path, monkeypatch):
    """Production DBs are built by alembic, not create_all: the 'runtime' role
    (absent from the initial migration's enum) must store and read back."""
    from alembic import command

    from app.config import get_settings

    url = f"sqlite:///{tmp_path / 'mig.db'}"
    monkeypatch.setattr(get_settings(), "database_url", url)
    command.upgrade(cli._alembic_config(), "head")
    eng = create_engine(url)
    try:
        S = sessionmaker(bind=eng, expire_on_commit=False)
        with S() as s:
            agent, key = seed_runtime_agent(s)
            s.commit()
        with S() as s:
            back = s.scalar(select(Agent).where(Agent.name == RUNTIME_AGENT_NAME))
            assert back.role is AgentRole.runtime
    finally:
        eng.dispose()


def test_held_rebuild_state_leaves_the_identities_and_the_hand_alone(client, world, db):
    """The agents table is not derived; replay must not touch it nor stop the hand."""
    assert client.post("/clock/advance", headers=H(world["runtime"]),
                       json={"days": 1}).status_code == 200
    before = [(a.id, a.name, a.role, a.status) for a in db.scalars(select(Agent))]
    rebuild_state(db)
    db.commit()
    db.expire_all()
    assert [(a.id, a.name, a.role, a.status) for a in db.scalars(select(Agent))] == before
    assert client.post("/clock/advance", headers=H(world["runtime"]),
                       json={"days": 1}).status_code == 200


def test_held_the_system_identity_cannot_be_reached_by_key(client, world, db):
    """system's key is discarded at birth: no key a firm agent could guess or replay
    authenticates as system (only the hash is stored, of a random key)."""
    sysrow = db.get(Agent, world["system_id"])
    for guess in ("system", "", sysrow.api_key_hash, "fk_system"):
        assert client.get("/me", headers=H(guess)).status_code == 401
