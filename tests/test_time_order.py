"""Time-travel invariants (B-016, ADR-025): replay order is live order.

Live state is folded one event at a time, in the order events were appended
(``app/ledger/apply.py``). Every replay — ``rebuild_state``, the equity curve,
``GET /events`` — must fold in that same order, or a clock that steps back (an
NTP correction live, a rewound backtest clock in Phase 3) makes the rebuilt
portfolio disagree with the one PMs traded (SURVEY §4a.1, probe P3: 10 phantom
shares).

Three laws, each with its own tests:

1. **Ledger time never runs backwards.** ``append_event`` stamps an event no
   earlier than the latest one already in the ledger, so id order and time order
   are the same order and day buckets agree with it.
2. **Every replay folds in id (append) order**, so even a ledger written before
   law 1 (the Human's August ``fund.db``) rebuilds to what was live.
3. **An impossible history is an error, not an erasure.** The sell reducer
   raises on a sell beyond the position instead of silently dropping it.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.clock import get_clock
from app.db.models import CashBalance, Event, Position
from app.ledger.events import (
    EVENT_ALLOCATION_SET,
    EVENT_ORDER_FILLED,
    EVENT_PERMISSION_DENIED,
    append_event,
    read_events,
)
from app.ledger.rebuild import rebuild_state
from app.ledger.reducers import DerivedState, apply_event
from app.metrics.equity import build_equity_curve

T0 = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)


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
    return db.execute(select(Event).order_by(Event.id)).scalars().all()


def _ledger_now(db) -> datetime:
    """The ledger's latest time: the clock may be behind it after a step back."""
    return max(get_clock().now(), _ledger(db)[-1].ts)


def _order(client, key, **body) -> dict:
    resp = client.post(
        "/orders", headers={"X-API-Key": key},
        json={"justification": "time travel", "price_type": "market", **body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- law 1: ledger time never runs backwards --------------------------------

def test_an_event_is_never_stamped_before_the_latest_one(db, make_pod, frozen_clock):
    frozen_clock.set(T0)
    first = append_event(db, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
    frozen_clock.set(T0 - timedelta(days=5))
    second = append_event(db, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
    db.commit()

    assert second.id > first.id
    assert first.ts == T0
    assert second.ts == T0  # held at the ledger's latest time, not 5 June


def test_forward_time_is_the_clock_exactly(db, frozen_clock):
    frozen_clock.set(T0)
    append_event(db, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
    frozen_clock.set(T0 - timedelta(days=1))
    append_event(db, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
    later = T0 + timedelta(hours=3, microseconds=7)
    frozen_clock.set(later)
    third = append_event(db, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
    db.commit()

    assert third.ts == later


def test_the_floor_is_the_committed_ledger_not_this_session(
    SessionFactory, frozen_clock
):
    """The floor is read where the row is written, not remembered per session."""
    stale = SessionFactory()
    other = SessionFactory()
    try:
        frozen_clock.set(T0)
        append_event(stale, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
        stale.commit()

        frozen_clock.set(T0 + timedelta(days=2))
        append_event(other, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
        other.commit()

        frozen_clock.set(T0 + timedelta(days=1))
        late = append_event(stale, type=EVENT_PERMISSION_DENIED, actor_agent_id=None)
        stale.commit()
        assert late.ts == T0 + timedelta(days=2)
    finally:
        stale.close()
        other.close()


def test_backwards_clock_trade_rebuilds_to_live_state(
    frozen_clock, client, desk, db, prices
):
    """SURVEY probe P3: buy on 10 June, clock back to 5 June, sell."""
    pod_id, _, pm_key = desk
    frozen_clock.set(T0)
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10)
    frozen_clock.set(T0 - timedelta(days=5))
    _order(client, pm_key, ticker="AAPL", side="sell", qty=10)

    live = _snapshot(db)
    assert (pod_id, "AAPL") not in live[1]
    rebuild_state(db)
    db.commit()
    assert _snapshot(db) == live  # no phantom shares

    curve = build_equity_curve(db, pod_id=pod_id, provider=prices, as_of=_ledger_now(db))
    assert curve.latest_equity == pytest.approx(live[0][pod_id], abs=1e-6)


# --- law 2: replays fold in append order, whatever the stamps say -----------

def _legacy_ledger(db, make_pod) -> None:
    """A ledger written before law 1: the sell has a later id, an earlier stamp."""
    make_pod(1)
    rows = [
        (T0 - timedelta(days=9), EVENT_ALLOCATION_SET, {"pod_id": 1, "delta": 10_000.0}),
        (T0, EVENT_ORDER_FILLED, {"pod_id": 1, "ticker": "AAPL", "side": "buy",
                                  "qty": 10, "fill_price": 200.0, "fee": 0.0}),
        (T0 - timedelta(days=5), EVENT_ORDER_FILLED, {"pod_id": 1, "ticker": "AAPL",
                                                      "side": "sell", "qty": 10,
                                                      "fill_price": 200.0, "fee": 0.0}),
    ]
    for ts, type_, payload in rows:
        db.add(Event(ts=ts, actor_agent_id=None, type=type_, payload_json=payload))
        db.flush()
    db.commit()


def test_rebuild_folds_a_legacy_ledger_in_append_order(db, make_pod):
    _legacy_ledger(db, make_pod)
    state = rebuild_state(db)
    db.commit()

    assert state.positions == {}
    assert state.cash == {1: 10_000.0}


def test_equity_curve_folds_a_legacy_ledger_in_append_order(db, make_pod, prices):
    _legacy_ledger(db, make_pod)
    curve = build_equity_curve(
        db, pod_id=1, provider=prices, as_of=T0 + timedelta(days=2)
    )
    by_day = {p.on: p.equity for p in curve.points}

    # A late-stamped event counts from the latest day the ledger had reached:
    # the sell lands on 10 June with the buy, never before it.
    assert by_day[(T0 - timedelta(days=5)).date()] == pytest.approx(10_000.0)
    assert all(e == pytest.approx(10_000.0) for e in by_day.values())
    assert len(curve.points) == 12  # 1 June .. 12 June, one point per day


def test_read_events_is_append_order(db, make_pod):
    _legacy_ledger(db, make_pod)
    ids = [e.id for e in read_events(db)]
    assert ids == sorted(ids)


# --- law 3: an impossible history is an error -------------------------------

def _fill(side: str, qty: float) -> Event:
    return Event(type=EVENT_ORDER_FILLED, payload_json={
        "pod_id": 1, "ticker": "AAPL", "side": side, "qty": qty,
        "fill_price": 100.0, "fee": 0.0,
    })


def test_sell_beyond_the_position_raises():
    state = DerivedState()
    apply_event(state, _fill("buy", 5))
    with pytest.raises(ValueError, match="beyond"):
        apply_event(state, _fill("sell", 10))


def test_sell_with_no_position_raises():
    with pytest.raises(ValueError, match="beyond"):
        apply_event(DerivedState(), _fill("sell", 1))


def test_sell_of_the_whole_position_within_float_dust_closes_it():
    state = DerivedState()
    apply_event(state, _fill("buy", 0.3))
    apply_event(state, _fill("sell", 0.1 + 0.2))  # 0.30000000000000004
    assert state.positions == {}


# --- the invariant suite: a random walk through time -------------------------

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_time_travel_keeps_live_equal_to_replay(
    frozen_clock, client, desk, db, prices, seed
):
    """Clock steps back and forth while the desk trades: every law holds."""
    pod_id, _, pm_key = desk
    rng = random.Random(seed)
    frozen_clock.set(T0)
    held: dict[str, float] = {}
    for _ in range(40):
        frozen_clock.set(frozen_clock.now() + timedelta(hours=rng.uniform(-72, 48)))
        ticker = rng.choice(["AAPL", "MSFT", "NVDA"])
        prices.set_price(ticker, round(rng.uniform(50, 500), 2))
        if held.get(ticker, 0) >= 0.01 and rng.random() < 0.5:
            qty = rng.choice([held[ticker], round(held[ticker] / 2, 3)])
            side = "sell"
        else:
            qty, side = rng.randint(1, 20), "buy"
        order = _order(client, pm_key, ticker=ticker, side=side, qty=qty)
        if order["status"] == "filled":
            held[ticker] = held.get(ticker, 0) + (qty if side == "buy" else -qty)

    stamps = [e.ts for e in _ledger(db)]
    assert stamps == sorted(stamps)

    live = _snapshot(db)
    rebuild_state(db)
    db.commit()
    rebuilt = _snapshot(db)
    assert rebuilt[0] == pytest.approx(live[0])
    assert rebuilt[1].keys() == live[1].keys()
    for key, (qty, avg) in live[1].items():
        assert rebuilt[1][key] == pytest.approx((qty, avg))

    as_of = _ledger_now(db)
    curve = build_equity_curve(db, pod_id=pod_id, provider=prices, as_of=as_of)
    expected = live[0][pod_id] + sum(
        qty * prices.get_price(t, as_of=as_of).price
        for (_, t), (qty, _) in live[1].items()
    )
    assert curve.latest_equity == pytest.approx(expected)
