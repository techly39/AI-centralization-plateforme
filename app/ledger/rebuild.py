"""``rebuild_state()`` — reconstruct derived tables by replaying the ledger.

This is the maintenance command required by TRD §5: derived tables
(``positions``, ``cash_balances``) must be reproducible from ``events`` alone.
It is deterministic and idempotent — running it twice yields the same tables.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import CashBalance, Event, Position
from app.ledger.reducers import DerivedState, apply_event


def rebuild_state(session: Session) -> DerivedState:
    """Drop and rebuild derived tables from the full event history.

    The caller owns the transaction. Returns the computed state for inspection
    or comparison (used by tests to assert replay determinism).
    """
    # Replay every event in canonical order into an in-memory accumulator.
    state = DerivedState()
    events = session.execute(select(Event).order_by(Event.ts, Event.id)).scalars()
    for event in events:
        apply_event(state, event)

    # Wipe and repopulate the derived tables from the accumulator.
    session.execute(delete(Position))
    session.execute(delete(CashBalance))
    session.flush()

    for pod_id, balance in state.cash.items():
        session.add(CashBalance(pod_id=pod_id, balance=balance))
    for (pod_id, ticker), pos in state.positions.items():
        session.add(
            Position(
                pod_id=pod_id,
                ticker=ticker,
                qty=pos["qty"],
                avg_cost=pos["avg_cost"],
            )
        )
    session.flush()
    return state
