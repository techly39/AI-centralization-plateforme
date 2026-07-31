"""Apply one freshly-appended event to the derived tables, in place.

Why this module exists: the OMS must not recompute a portfolio from scratch on
every fill (that gets slower with every event ever written), but the derived
tables must still match a full replay exactly — that equality is a Definition of
Done item in the TRD.

The trick is that this module owns **no arithmetic**. It loads the affected
pod's derived rows into the same :class:`DerivedState` structure
:func:`app.ledger.rebuild.rebuild_state` uses, calls the same reducer, and
writes the result back. There is exactly one implementation of the money math
(``app/ledger/reducers.py``), so live state and replayed state cannot drift.

Scope rule: an event affects derived state only if its payload carries
``pod_id``. Any future reducer must follow that convention (see
``app/ledger/events.py``); ``tests/test_oms_replay_consistency.py`` fails loudly
if one does not.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CashBalance, Event, Position
from app.ledger.reducers import DerivedState, apply_event


def apply_event_to_db(session: Session, event: Event) -> None:
    """Fold ``event`` into ``positions`` / ``cash_balances`` for its pod.

    The caller owns the transaction. Events without a ``pod_id`` (registration,
    permission denials, order placements) have no derived effect and are skipped.
    """
    payload = event.payload_json or {}
    raw_pod_id = payload.get("pod_id")
    if raw_pod_id is None:
        return
    pod_id = int(raw_pod_id)

    state = _load_pod_state(session, pod_id)
    apply_event(state, event)
    _write_pod_state(session, pod_id, state)


def _load_pod_state(session: Session, pod_id: int) -> DerivedState:
    """Read one pod's current derived rows into a replay accumulator."""
    state = DerivedState()

    cash_row = session.get(CashBalance, pod_id)
    if cash_row is not None:
        state.cash[pod_id] = cash_row.balance

    rows = session.execute(
        select(Position).where(Position.pod_id == pod_id)
    ).scalars()
    for row in rows:
        state.positions[(pod_id, row.ticker)] = {
            "qty": row.qty,
            "avg_cost": row.avg_cost,
        }
    return state


def _write_pod_state(session: Session, pod_id: int, state: DerivedState) -> None:
    """Persist the accumulator back, including positions the fold closed out."""
    balance = state.cash.get(pod_id)
    if balance is not None:
        cash_row = session.get(CashBalance, pod_id)
        if cash_row is None:
            session.add(CashBalance(pod_id=pod_id, balance=balance))
        else:
            cash_row.balance = balance

    existing = {
        row.ticker: row
        for row in session.execute(
            select(Position).where(Position.pod_id == pod_id)
        ).scalars()
    }

    for (_, ticker), pos in state.positions.items():
        row = existing.pop(ticker, None)
        if row is None:
            session.add(
                Position(
                    pod_id=pod_id,
                    ticker=ticker,
                    qty=pos["qty"],
                    avg_cost=pos["avg_cost"],
                )
            )
        else:
            row.qty = pos["qty"]
            row.avg_cost = pos["avg_cost"]

    # Anything still in ``existing`` was dropped by the reducer (fully sold), so
    # it must disappear from the table too — otherwise a closed position would
    # linger and a rebuild would silently disagree with live state.
    for row in existing.values():
        session.delete(row)

    session.flush()
