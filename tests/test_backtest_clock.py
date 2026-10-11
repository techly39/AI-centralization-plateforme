"""The backtest clock (ADR-027, B-004 slice a).

A run is a database: a backtest is a fresh database opened by ``run_started``,
its simulated now moves only by ``POST /clock/advance`` (``CONTROL_CLOCK``),
forward, bounded, never past the real now; each advance is a ``clock_advanced``
event and runs the pending-order sweep; a restart resumes from the ledger.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import cli
from app.clock import BacktestClock, LiveClock, get_clock, set_clock, wall_now
from app.db.models import AgentRole, CashBalance, Event, Position
from app.ledger.events import EVENT_CLOCK_ADVANCED, EVENT_RUN_STARTED
from app.ledger.rebuild import rebuild_state
from app.limits import MAX_ADVANCE_DAYS
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import RunClockError, install_run_clock, start_backtest

START = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


@pytest.fixture
def backtest(SessionFactory) -> dict[str, str]:
    """An empty database opened as a backtest at START, then seeded."""
    session = SessionFactory()
    try:
        start_backtest(session, start=START)
        _, admin = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="desk")
        fund_pod(session, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(session), reason="seed")
        _, pm = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
        _, an = register_agent(session, name="an", role=AgentRole.analyst, pod_id=pod.id)
        session.commit()
    finally:
        session.close()
    return {"admin": admin, "pm": pm, "an": an}


@pytest.fixture
def bt_client(backtest, client):
    """The API on the backtest database (its lifespan installs the run's clock)."""
    return client


def _events(db) -> list[Event]:
    db.expire_all()
    return list(db.execute(select(Event).order_by(Event.id)).scalars())


# --- opening a run ------------------------------------------------------------

def test_a_backtest_opens_with_run_started_at_its_start(SessionFactory, db):
    session = SessionFactory()
    clock = start_backtest(session, start=START)
    session.commit()
    session.close()
    assert get_clock() is clock and clock.mode == "backtest" and clock.now() == START
    [event] = _events(db)
    assert event.type == EVENT_RUN_STARTED and event.ts == START
    # A run records whether its market data had the look-ahead guard (auditor,
    # cycle 15): False before B-005, True since (ADR-028).
    assert event.payload_json == {"mode": "backtest", "start": START.isoformat(),
                                  "look_ahead_guard": True}


def test_a_backtest_refuses_a_database_that_holds_anything(SessionFactory, db, admin_key):
    session = SessionFactory()
    with pytest.raises(RunClockError, match="not empty"):
        start_backtest(session, start=START)
    session.rollback()
    session.close()
    assert get_clock().mode == "live"
    assert all(e.type != EVENT_RUN_STARTED for e in _events(db))


@pytest.mark.parametrize("start", [
    START.replace(tzinfo=None),                 # no timezone
    wall_now() + timedelta(days=1),             # the future has no data
    wall_now() - timedelta(seconds=30),         # inside the live-quote window
])
def test_a_backtest_refuses_a_bad_start(SessionFactory, db, start):
    session = SessionFactory()
    with pytest.raises(RunClockError):
        start_backtest(session, start=start)
    session.close()
    assert get_clock().mode == "live" and _events(db) == []


def test_a_live_database_leaves_the_clock_alone(db, admin_key, frozen_clock):
    assert install_run_clock(db) is None
    assert get_clock() is frozen_clock


# --- reading and advancing ----------------------------------------------------

def test_every_role_reads_the_simulated_now(bt_client, backtest):
    for key in backtest.values():
        body = bt_client.get("/clock", headers=H(key)).json()
        assert body["mode"] == "backtest"
        assert datetime.fromisoformat(body["now"]) == START


def test_advance_moves_the_clock_and_records_it(bt_client, backtest, db):
    resp = bt_client.post("/clock/advance", headers=H(backtest["admin"]),
                          json={"days": 1, "minutes": 30})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    end = START + timedelta(days=1, minutes=30)
    assert datetime.fromisoformat(body["previous"]) == START
    assert datetime.fromisoformat(body["now"]) == end
    assert get_clock().now() == end
    read = bt_client.get("/clock", headers=H(backtest["pm"])).json()
    assert datetime.fromisoformat(read["now"]) == end
    last = _events(db)[-1]
    assert last.type == EVENT_CLOCK_ADVANCED and last.ts == end
    assert last.payload_json == {"from": START.isoformat(), "to": end.isoformat(),
                                 "minutes": 24 * 60 + 30}


def test_every_event_of_the_run_carries_simulated_time(bt_client, backtest, db):
    """Run scoping by construction: no stamp from today in a 2024 backtest."""
    bt_client.post("/orders", headers=H(backtest["pm"]), json={
        "ticker": "AAPL", "side": "buy", "qty": 10, "price_type": "market",
        "justification": "t"})
    bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 3})
    events = _events(db)
    assert [e.id for e in events] == sorted(e.id for e in events)
    assert all(START <= e.ts <= START + timedelta(days=3) for e in events)
    assert [e.ts for e in events] == sorted(e.ts for e in events)


def test_a_limit_order_fills_on_the_advance_that_crosses_it(bt_client, backtest, prices, db):
    placed = bt_client.post("/orders", headers=H(backtest["pm"]), json={
        "ticker": "AAPL", "side": "buy", "qty": 10, "price_type": "limit",
        "limit_price": 150.0, "justification": "wait for the dip"})
    assert placed.status_code == 201 and placed.json()["status"] == "pending"
    order_id = placed.json()["id"]

    first = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 1})
    assert first.json()["filled_order_ids"] == []

    prices.set_price("AAPL", 140.0)
    second = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 1})
    assert second.json()["filled_order_ids"] == [order_id]
    fill = [e for e in _events(db) if e.type == "order_filled"][-1]
    assert fill.ts == START + timedelta(days=2)
    # Live state equals a replay of the run's ledger.
    state = rebuild_state(db)
    db.expire_all()
    assert {r.pod_id: r.balance for r in db.execute(select(CashBalance)).scalars()} == state.cash
    assert {(r.pod_id, r.ticker): r.qty
            for r in db.execute(select(Position)).scalars()} == {
        k: v["qty"] for k, v in state.positions.items()}


def test_only_clock_control_advances(bt_client, backtest, db):
    before = len(_events(db))
    for who in ("pm", "an"):
        resp = bt_client.post("/clock/advance", headers=H(backtest[who]), json={"days": 1})
        assert resp.status_code == 403
    assert get_clock().now() == START
    assert all(e.type != EVENT_CLOCK_ADVANCED for e in _events(db)[before:])


@pytest.mark.parametrize("body", [
    {}, {"days": 0, "minutes": 0}, {"days": -1}, {"minutes": -5},
    {"days": MAX_ADVANCE_DAYS + 1}, {"days": MAX_ADVANCE_DAYS, "minutes": 1},
    {"days": 1.5}, {"days": 1, "now": "2099-01-01T00:00:00Z"}, {"days": 1, "mode": "live"},
])
def test_a_step_is_forward_and_bounded(bt_client, backtest, body):
    resp = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json=body)
    assert resp.status_code == 422, (body, resp.status_code)
    assert get_clock().now() == START


def test_a_backtest_cannot_pass_the_real_now(SessionFactory, client, db):
    near = wall_now() - timedelta(days=1)
    session = SessionFactory()
    start_backtest(session, start=near)
    _, admin = register_agent(session, name="management", role=AgentRole.management)
    session.commit()
    session.close()
    resp = client.post("/clock/advance", headers=H(admin), json={"days": 2})
    assert resp.status_code == 409 and "real now" in resp.json()["detail"]
    assert get_clock().now() == near.astimezone(timezone.utc)
    assert all(e.type != EVENT_CLOCK_ADVANCED for e in _events(db))


def test_a_backtest_stays_out_of_the_live_quote_window(SessionFactory, client, db):
    """Within a minute of the real now a live feed gives its current quote, so
    a backtest's clock may not step there (ADR-028): it would see its future."""
    near = wall_now() - timedelta(minutes=2)
    session = SessionFactory()
    start_backtest(session, start=near)
    _, admin = register_agent(session, name="management", role=AgentRole.management)
    session.commit()
    session.close()
    resp = client.post("/clock/advance", headers=H(admin), json={"minutes": 2})
    assert resp.status_code == 409 and "real now" in resp.json()["detail"]
    assert get_clock().now() == near.astimezone(timezone.utc)
    assert client.post("/clock/advance", headers=H(admin),
                       json={"minutes": 1}).status_code == 200


def test_a_halted_world_does_not_advance(bt_client, backtest, halt_file, db):
    halt_file.touch()
    resp = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 1})
    assert resp.status_code == 423
    assert get_clock().now() == START
    assert all(e.type != EVENT_CLOCK_ADVANCED for e in _events(db))


# --- restarts -----------------------------------------------------------------

def test_a_restart_resumes_at_the_ledgers_simulated_now(bt_client, backtest, db):
    bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 5})
    set_clock(LiveClock())                       # the process dies
    clock = install_run_clock(db)                # and starts again on this database
    assert isinstance(clock, BacktestClock)
    assert get_clock() is clock and clock.now() == START + timedelta(days=5)


@pytest.fixture
def cli_on_test_db(SessionFactory, monkeypatch) -> None:
    """Point the operator CLI's sessions at the test database."""

    @contextmanager
    def scope() -> Iterator:
        s = SessionFactory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)


def test_the_server_starts_on_its_databases_clock(backtest, SessionFactory):
    """The lifespan installs the run's clock: a fresh server process on a backtest
    database reads and stamps simulated time, never the live clock it booted with."""
    from fastapi.testclient import TestClient

    from app.db.base import get_session
    from app.main import create_app

    set_clock(LiveClock())                       # a fresh server process
    app = create_app()

    def _session() -> Iterator:
        s = SessionFactory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        body = c.get("/clock", headers=H(backtest["pm"])).json()
        assert body["mode"] == "backtest"
        assert datetime.fromisoformat(body["now"]) == START
    assert get_clock().mode == "live"            # put back on shutdown


def test_operator_commands_stamp_the_runs_now(SessionFactory, cli_on_test_db, db):
    """``fund-env create-pod`` on a backtest database stamps simulated time."""
    assert cli.main(["start-backtest", "--start", START.isoformat()]) == 0
    set_clock(LiveClock())                       # a fresh operator process
    assert cli.main(["create-pod", "--name", "desk", "--allocation", "1000"]) == 0
    events = _events(db)
    assert [e.type for e in events] == [EVENT_RUN_STARTED, "allocation_set"]
    assert all(e.ts == START for e in events)


def test_cli_start_backtest_refuses_a_used_database(cli_on_test_db, admin_key, capsys):
    assert cli.main(["start-backtest", "--start", "2024-01-02T15:00:00Z"]) == 1
    assert "not empty" in capsys.readouterr().err
    assert get_clock().mode == "live"
