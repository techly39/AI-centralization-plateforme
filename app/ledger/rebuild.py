"""``rebuild_state()`` — reconstruct derived tables by replaying the ledger.

This is the maintenance command required by TRD §5: derived tables
(``positions``, ``cash_balances``) must be reproducible from ``events`` alone.
It is deterministic and idempotent — running it twice yields the same tables.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import CashBalance, Event, Pod, Position
from app.ledger.events import (
    EVENT_ALLOCATION_SET,
    EVENT_HIRE_FAILED,
    EVENT_PM_LET_GO,
    EVENT_POD_STAGE_CHANGED,
)
from app.ledger.reducers import DerivedState, apply_event


def stage_from(event: Event) -> tuple[int, str] | None:
    """The pod stage an event sets, ``(pod_id, stage)``, or ``None``: the risk ladder's latest
    ``pod_stage_changed``; a failed hire's empty pod and a let-go PM's empty pod are closed."""
    payload = event.payload_json or {}
    if event.type == EVENT_POD_STAGE_CHANGED:
        return int(payload["pod_id"]), str(payload["to"])
    if event.type == EVENT_HIRE_FAILED or (event.type == EVENT_PM_LET_GO
                                           and payload.get("pod_closed")):
        return int(payload["pod_id"]), "closed"
    return None


def rebuild_state(session: Session) -> DerivedState:
    """Drop and rebuild derived tables from the full event history.

    The caller owns the transaction. Returns the computed state for inspection
    or comparison (used by tests to assert replay determinism).
    """
    # Replay every event in append order — the order live state folded them
    # (ADR-025) — into an in-memory accumulator. Not ``ts``: a ledger written
    # before time was made monotonic can hold a later event with an earlier stamp.
    state = DerivedState()
    # The pod rows' ledger-backed columns: the capital put in (every allocation_set) and the
    # risk ladder's stage (the latest pod_stage_changed), which the order system reads.
    allocated: dict[int, float] = {}
    stage: dict[int, str] = {}
    events = session.execute(select(Event).order_by(Event.id)).scalars()
    for event in events:
        apply_event(state, event)
        payload = event.payload_json or {}
        if event.type == EVENT_ALLOCATION_SET:
            pod_id = int(payload["pod_id"])
            allocated[pod_id] = allocated.get(pod_id, 0.0) + float(payload["delta"])
        elif (staged := stage_from(event)) is not None:
            stage[staged[0]] = staged[1]

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
    for pod in session.execute(select(Pod)).scalars():
        pod.current_allocation = allocated.get(pod.id, 0.0)
        if pod.id in stage:
            pod.status = stage[pod.id]
    session.flush()
    return state
