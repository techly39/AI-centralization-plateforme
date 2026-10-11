"""RED-TEAM 0005 — attacks on the cycle-0013 replay-order fix (B-016, ADR-025).

Claim under attack: ledger time never runs backwards (the floor is computed
inside the INSERT), every replay folds by event id, the equity curve buckets on
the latest day reached, and the sell reducer raises on a sell beyond position.
So live state, ``rebuild_state``, the metrics equity curve and ``GET /events``
can never disagree, and no agent can make a replay raise for everyone.

Every attack uses only what a firm agent holds: an API key, REST, MCP tools —
plus, where marked, a *world event* (the clock stepping back) that the agent
cannot cause but can be standing next to.

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.clock import LiveClock, get_clock, set_clock
from app.db.models import AgentRole, Base, CashBalance, Event, Order, Pod, Position
from app.ledger.events import (
    EVENT_ALLOCATION_SET,
    EVENT_ORDER_FILLED,
    EVENT_ORDER_PLACED,
    EVENT_PERMISSION_DENIED,
    append_event,
)
from app.ledger.rebuild import rebuild_state
from app.ledger.reducers import QTY_EPSILON
from app.marketdata import StaticProvider
from app.metrics.equity import build_equity_curve
from app.oms import place_order
from app.registry.pods import fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from tests.test_redteam_0001 import H, send, two_desks  # noqa: F401  (fixtures)

T0 = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)
FUTURE = "2099-01-01T00:00:00Z"


def _snapshot(db) -> tuple[dict, dict]:
    db.expire_all()
    cash = {r.pod_id: r.balance for r in db.execute(select(CashBalance)).scalars()}
    positions = {
        (r.pod_id, r.ticker): (r.qty, r.avg_cost)
        for r in db.execute(select(Position)).scalars()
    }
    return cash, positions


def _ledger(db) -> list[Event]:
    db.expire_all()
    return list(db.execute(select(Event).order_by(Event.id)).scalars())


def _assert_monotonic(events: list[Event]) -> None:
    for prev, nxt in zip(events, events[1:]):
        assert nxt.id > prev.id
        assert nxt.ts >= prev.ts, (prev.id, prev.ts, nxt.id, nxt.ts)


class _ThreadClock:
    """A clock whose "now" is per thread: lets two racing writers disagree."""

    mode = "frozen"

    def __init__(self, default: datetime) -> None:
        self._default = default
        self._local = threading.local()

    def set(self, moment: datetime) -> None:
        self._local.now = moment

    def now(self) -> datetime:
        return getattr(self._local, "now", self._default)


@pytest.fixture
def thread_clock():
    clock = _ThreadClock(T0)
    set_clock(clock)
    yield clock
    set_clock(LiveClock())


@pytest.fixture
def file_sessions(tmp_path):
    """A real on-disk SQLite: separate connections, real write locks.

    The suite's in-memory StaticPool shares ONE connection between sessions, so
    it can never show what a second writer sees. This can.
    """
    eng = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    Base.metadata.create_all(eng)
    yield sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, future=True)
    eng.dispose()


# =============================================================================
# HELD — an agent cannot push ledger time (no path sets ts; no clock control)
# =============================================================================

def test_held_agent_supplied_timestamps_never_reach_the_ledger(
    frozen_clock, client, two_desks, admin_key, db
):
    """Smuggle a far-future time through every write an agent has."""
    frozen_clock.set(T0)
    _, pm1_key = two_desks["pm1"]
    _, an1_key = two_desks["an1"]
    stamp = {"ts": FUTURE, "created_at": FUTURE, "filled_at": FUTURE,
             "started_at": FUTURE, "as_of": FUTURE, "type": EVENT_ORDER_FILLED}
    attempts = [
        ("/orders", pm1_key, {"ticker": "AAPL", "side": "buy", "qty": 1,
                              "price_type": "market", "justification": "x"}),
        ("/messages", an1_key, {"to": "pod:1", "body": "hi"}),
        ("/costs", an1_key, {"tokens_in": 1, "tokens_out": 1, "usd_cost": 0.1}),
        ("/tasks/start", an1_key, {"subject": "s"}),
    ]
    for path, key, body in attempts:
        for field, value in stamp.items():
            resp = client.post(path, headers=H(key), json={**body, field: value})
            assert resp.status_code == 422, (path, field, resp.status_code)
    # And the query-string route: ?ts= / ?as_of= on writes is ignored, never stored.
    client.post("/messages?ts=" + FUTURE, headers=H(an1_key),
                json={"to": "pod:1", "body": "q"})

    events = _ledger(db)
    assert all(e.ts.year < 2099 for e in events)
    assert max(e.ts for e in events) <= get_clock().now()
    _assert_monotonic(events)


@pytest.mark.parametrize("method,path", [
    ("POST", "/clock/mode"), ("PUT", "/clock"), ("POST", "/clock"), ("PATCH", "/clock"),
])
def test_held_no_clock_control_on_the_surface(client, two_desks, admin_key, method, path):
    """No route sets the clock or its mode — for any role, management included.
    (``POST /clock/advance`` exists since ADR-027: the test below.)"""
    for key in (two_desks["pm1"][1], two_desks["an1"][1], admin_key):
        resp = client.request(method, path, headers=H(key),
                              json={"now": FUTURE, "mode": "backtest", "days": 10_000})
        assert resp.status_code in (404, 405), (method, path, resp.status_code)


def test_held_no_role_moves_a_live_clock(client, two_desks, admin_key, db):
    """ADR-027: advance is CONTROL_CLOCK (PM/analyst 403) and backtest-only
    (management 409 in a live run); the live clock and the ledger's now stay put."""
    before = client.get("/clock", headers=H(admin_key)).json()
    for who in ("pm1", "an1"):
        resp = client.post("/clock/advance", headers=H(two_desks[who][1]), json={"days": 1})
        assert resp.status_code == 403, (who, resp.status_code)
    resp = client.post("/clock/advance", headers=H(admin_key), json={"days": 1})
    assert resp.status_code == 409, resp.text
    assert get_clock().mode == "live"
    after = client.get("/clock", headers=H(admin_key)).json()
    assert after["mode"] == before["mode"] == "live"
    assert all(e.type != "clock_advanced" for e in _ledger(db))


def test_held_clock_read_is_a_read_only(client, two_desks):
    """Every agent may read the clock (ADR-026, was management-only); reading it
    must reveal nothing but ``mode`` and ``now`` — control is the test above."""
    for who in ("pm1", "an1"):
        resp = client.get("/clock", headers=H(two_desks[who][1]))
        assert resp.status_code == 200
        assert set(resp.json()) == {"mode", "now"}


def test_held_agent_cannot_append_reducer_events(
    frozen_clock, client, two_desks, db
):
    """No agent route lets a caller name the event type or a pod to fold into."""
    frozen_clock.set(T0)
    _, pm1_key = two_desks["pm1"]
    _, an1_key = two_desks["an1"]
    before = db.scalar(select(func.count()).select_from(Event).where(
        Event.type.in_([EVENT_ORDER_FILLED, EVENT_ALLOCATION_SET])))
    bad = {"type": EVENT_ORDER_FILLED, "pod_id": 2, "side": "sell",
           "qty": 1e6, "fill_price": 1.0}
    for path, key, body in [
        ("/messages", an1_key, {"to": "pod:1", "body": "x"}),
        ("/costs", an1_key, {"tokens_in": 1, "tokens_out": 1, "usd_cost": 0.0}),
        ("/tasks/start", an1_key, {"subject": "s"}),
    ]:
        for k, v in bad.items():
            assert client.post(path, headers=H(key), json={**body, k: v}).status_code == 422
    # structured_payload is free JSON, but it is message data, never a ledger event type
    send(client, pm1_key, to="pod:1", body="x", structured_payload=bad)
    after = db.scalar(select(func.count()).select_from(Event).where(
        Event.type.in_([EVENT_ORDER_FILLED, EVENT_ALLOCATION_SET])))
    assert after == before
    rebuild_state(db)  # does not raise


# =============================================================================
# HELD — concurrency: two real writers can never disagree on id vs ts
# =============================================================================

def test_held_racing_writers_with_disagreeing_clocks_stay_monotonic(
    file_sessions, thread_clock
):
    """8 threads, separate connections, each with its own clock jittering ±3 days."""
    errors: list[BaseException] = []

    def writer(seed: int) -> None:
        rng = random.Random(seed)
        session = file_sessions()
        try:
            for _ in range(30):
                thread_clock.set(T0 + timedelta(seconds=rng.randint(-3 * 86400, 3 * 86400),
                                                microseconds=rng.randint(0, 999_999)))
                append_event(session, type=EVENT_PERMISSION_DENIED, actor_agent_id=None,
                             payload={"seed": seed})
                if rng.random() < 0.5:
                    session.commit()
            session.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors

    s = file_sessions()
    try:
        events = _ledger(s)
        assert len(events) == 8 * 30
        _assert_monotonic(events)
    finally:
        s.close()


def test_held_floor_sees_an_uncommitted_rival_once_it_commits(
    file_sessions, thread_clock
):
    """A holds the write lock with a later stamp; B (clock behind) must wait and be held."""
    flushed, go = threading.Event(), threading.Event()
    out: dict[str, Event] = {}

    def a() -> None:
        thread_clock.set(T0 + timedelta(days=2))
        s = file_sessions()
        out["a"] = append_event(s, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
        flushed.set()
        go.wait(10)
        s.commit()
        s.close()

    def b() -> None:
        thread_clock.set(T0 + timedelta(days=1))
        s = file_sessions()
        out["b"] = append_event(s, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
        s.commit()
        out["b_ts"] = out["b"].ts
        s.close()

    ta = threading.Thread(target=a)
    ta.start()
    assert flushed.wait(10)
    tb = threading.Thread(target=b)
    tb.start()
    time.sleep(0.3)  # B is now blocked on A's write lock
    assert tb.is_alive()
    go.set()
    ta.join()
    tb.join()

    assert out["b"].id > out["a"].id
    assert out["b_ts"] == T0 + timedelta(days=2)


def test_held_concurrent_full_position_sells_fill_once_and_replay(
    file_sessions, thread_clock
):
    """Six racing market sells of the whole position: one fills, replay agrees."""
    provider = StaticProvider({"AAPL": 200.0})
    s = file_sessions()
    s.add(Pod(id=1, name="pod-1", created_at=T0))
    s.commit()
    fund_pod(s, pod_id=1, delta=100_000.0,
             actor=get_or_create_system_agent(s), reason="race")
    pm, _ = register_agent(s, name="pm-1", role=AgentRole.pm, pod_id=1)
    s.commit()
    place_order(s, actor=pm, ticker="AAPL", side="buy", qty=10, price_type="market",
                justification="x", provider=provider)
    pm_id = pm.id
    s.close()

    barrier = threading.Barrier(6)
    statuses: list[str] = []
    errors: list[BaseException] = []

    def seller(i: int) -> None:
        thread_clock.set(T0 - timedelta(days=i))  # every seller's clock is behind
        session = file_sessions()
        try:
            actor = session.get(type(pm), pm_id)
            barrier.wait()
            order = place_order(session, actor=actor, ticker="AAPL", side="sell", qty=10,
                                price_type="market", justification="race",
                                provider=provider)
            statuses.append(order.status.value)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=seller, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert sorted(statuses) == ["filled"] + ["rejected"] * 5

    s = file_sessions()
    try:
        live = _snapshot(s)
        rebuild_state(s)
        s.commit()
        assert _snapshot(s) == live
        _assert_monotonic(_ledger(s))
    finally:
        s.close()


# =============================================================================
# HELD — an agent cannot record a sell the replay refuses (no replay DoS)
# =============================================================================

def test_held_agent_churn_with_clock_steps_replays_to_live(
    frozen_clock, client, desk, db, prices
):
    """Partial / dust / at-the-epsilon sells, double limit sells, clock stepping
    back and forth between them: live == rebuild == equity curve, nothing raises."""
    pod_id, _, pm_key = desk
    rng = random.Random(5)
    frozen_clock.set(T0)

    def order(**body):
        return client.post("/orders", headers=H(pm_key), json={
            "justification": "churn", "price_type": "market", **body})

    held = 0.0
    outcomes: set[tuple[str, str]] = set()
    for step in range(60):
        frozen_clock.set(T0 + timedelta(hours=rng.randint(-200, 200)))
        if held < 1 or rng.random() < 0.4:
            q = rng.choice([1.0, 0.1, 1 / 3, 7.0, QTY_EPSILON / 2])
            r = order(ticker="AAPL", side="buy", qty=q)
        else:
            q = rng.choice([held, held / 3, held + QTY_EPSILON / 2, held + QTY_EPSILON,
                            held + 2 * QTY_EPSILON, held * 2])
            r = order(ticker="AAPL", side="sell", qty=q)
        assert r.status_code == 201, r.text
        outcomes.add((r.json()["side"], r.json()["status"]))
        db.expire_all()
        pos = db.get(Position, (pod_id, "AAPL"))
        held = pos.qty if pos else 0.0

    assert {("sell", "filled"), ("sell", "rejected"), ("buy", "filled")} <= outcomes

    # Two resting limit sells for the full position, then the monitor sweeps.
    from app.oms.monitor import check_pending_orders
    for _ in range(2):
        client.post("/orders", headers=H(pm_key), json={
            "justification": "x", "price_type": "limit", "ticker": "AAPL",
            "side": "sell", "qty": max(held, 1.0), "limit_price": 150.0})
    frozen_clock.set(T0 - timedelta(days=30))
    check_pending_orders(db, provider=prices)

    live = _snapshot(db)
    rebuild_state(db)
    db.commit()
    assert _snapshot(db) == live
    events = _ledger(db)
    _assert_monotonic(events)

    as_of = max(get_clock().now(), events[-1].ts)
    curve = build_equity_curve(db, pod_id=pod_id, provider=prices, as_of=as_of)
    held_qty = live[1].get((pod_id, "AAPL"), (0.0, 0.0))[0]
    assert curve.latest_equity == pytest.approx(live[0][pod_id] + held_qty * 200.0,
                                                abs=1e-6)


# =============================================================================
# HOLE (low), CLOSED cycle 13 — a sell up to QTY_EPSILON of a ticker never held
# was filled (shared tolerance `qty > held + QTY_EPSILON`, cash from nothing).
# Now the OMS and the reducer both refuse any sell with no position.
# =============================================================================

def test_naked_dust_sell_of_unheld_ticker_is_refused(frozen_clock, client, desk, db):
    pod_id, _, pm_key = desk
    frozen_clock.set(T0)
    cash_before = _snapshot(db)[0][pod_id]
    resp = client.post("/orders", headers=H(pm_key), json={
        "ticker": "MSFT", "side": "sell", "qty": QTY_EPSILON, "price_type": "market",
        "justification": "sell what I do not own"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "rejected"
    assert _snapshot(db)[0][pod_id] == cash_before


# =============================================================================
# HOLE (low), CLOSED cycle 13 for orders — Order.created_at/filled_at took the raw
# clock while their events were held at the ledger's latest time. Now both are
# copied from their events, as fund_pod does for Allocation.ts. Message.ts,
# Cost.ts and Task times still take the raw clock: B-028.
# =============================================================================

def test_order_fill_time_matches_its_ledger_event(frozen_clock, client, desk, db):
    pod_id, _, pm_key = desk
    frozen_clock.set(T0)

    def buy():
        r = client.post("/orders", headers=H(pm_key), json={
            "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
            "justification": "x"})
        assert r.status_code == 201
        return r.json()

    first = buy()
    frozen_clock.set(T0 - timedelta(days=5))  # world event: the clock steps back
    second = buy()

    db.expire_all()
    fills = {
        e.payload_json["order_id"]: e.ts
        for e in db.scalars(select(Event).where(Event.type == EVENT_ORDER_FILLED))
    }
    placed = {
        e.payload_json["order_id"]: e.ts
        for e in db.scalars(select(Event).where(Event.type == EVENT_ORDER_PLACED))
    }
    for o in (first, second):
        assert datetime.fromisoformat(o["filled_at"]).replace(tzinfo=timezone.utc) \
            == fills[o["id"]]
        assert datetime.fromisoformat(o["created_at"]).replace(tzinfo=timezone.utc) \
            == placed[o["id"]]
    # what agents see must order the fills the way the ledger does
    orders = client.get("/orders", headers=H(pm_key)).json()
    assert [o["id"] for o in orders][:2] == [second["id"], first["id"]]
