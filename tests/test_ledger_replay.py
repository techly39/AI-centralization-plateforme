"""Ledger replay (TRD §5 + Definition of Done): derived state is reproducible
from ``events`` alone, and ``rebuild_state`` is deterministic and idempotent.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import CashBalance, Position
from app.ledger.events import (
    EVENT_ALLOCATION_SET,
    EVENT_ORDER_FILLED,
    append_event,
)
from app.ledger.rebuild import rebuild_state


def _seed_events(db, make_pod) -> None:
    # Fund pod 1 with 100k, buy 10 AAPL @ 100 (fee 10), buy 10 more @ 120 (fee 12),
    # then sell 5 @ 130 (fee 6.5).
    make_pod(1)
    append_event(db, type=EVENT_ALLOCATION_SET, actor_agent_id=None,
                 payload={"pod_id": 1, "delta": 100_000.0})
    append_event(db, type=EVENT_ORDER_FILLED, actor_agent_id=None,
                 payload={"pod_id": 1, "ticker": "AAPL", "side": "buy",
                          "qty": 10, "fill_price": 100.0, "fee": 10.0})
    append_event(db, type=EVENT_ORDER_FILLED, actor_agent_id=None,
                 payload={"pod_id": 1, "ticker": "AAPL", "side": "buy",
                          "qty": 10, "fill_price": 120.0, "fee": 12.0})
    append_event(db, type=EVENT_ORDER_FILLED, actor_agent_id=None,
                 payload={"pod_id": 1, "ticker": "AAPL", "side": "sell",
                          "qty": 5, "fill_price": 130.0, "fee": 6.5})
    db.commit()


def test_rebuild_produces_expected_state(db, make_pod) -> None:
    _seed_events(db, make_pod)
    state = rebuild_state(db)
    db.commit()

    # Cash: 100000 - (1000+10) - (1200+12) + (650-6.5) = 98421.5
    assert state.cash[1] == 98_421.5
    # Position: 15 shares left; avg cost = (10*100 + 10*120)/20 = 110 (sells don't move avg)
    pos = state.positions[(1, "AAPL")]
    assert pos["qty"] == 15
    assert pos["avg_cost"] == 110.0

    # Derived tables persisted to match.
    cash_row = db.scalar(select(CashBalance).where(CashBalance.pod_id == 1))
    assert cash_row.balance == 98_421.5
    pos_row = db.scalar(select(Position).where(Position.pod_id == 1, Position.ticker == "AAPL"))
    assert pos_row.qty == 15
    assert pos_row.avg_cost == 110.0


def test_rebuild_is_idempotent(db, make_pod) -> None:
    _seed_events(db, make_pod)
    first = rebuild_state(db)
    db.commit()
    second = rebuild_state(db)
    db.commit()
    assert first.cash == second.cash
    assert first.positions == second.positions

    # Running twice must not duplicate derived rows.
    assert len(db.execute(select(CashBalance)).scalars().all()) == 1
    assert len(db.execute(select(Position)).scalars().all()) == 1


def test_fully_closed_position_is_removed(db, make_pod) -> None:
    make_pod(2)
    append_event(db, type=EVENT_ALLOCATION_SET, actor_agent_id=None,
                 payload={"pod_id": 2, "delta": 10_000.0})
    append_event(db, type=EVENT_ORDER_FILLED, actor_agent_id=None,
                 payload={"pod_id": 2, "ticker": "MSFT", "side": "buy",
                          "qty": 5, "fill_price": 200.0, "fee": 0.0})
    append_event(db, type=EVENT_ORDER_FILLED, actor_agent_id=None,
                 payload={"pod_id": 2, "ticker": "MSFT", "side": "sell",
                          "qty": 5, "fill_price": 210.0, "fee": 0.0})
    db.commit()
    state = rebuild_state(db)
    db.commit()
    assert (2, "MSFT") not in state.positions
    assert db.scalar(select(Position).where(Position.pod_id == 2)) is None
    # Cash: 10000 - 1000 + 1050 = 10050
    assert state.cash[2] == 10_050.0
