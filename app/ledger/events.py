"""Append-only event store (TRD §5, principle 4).

The ledger is the source of truth. Anything that changes state appends an
``Event`` here through :func:`append_event`; derived tables are rebuilt from it.
Event ``type`` strings are centralised as constants so producers and reducers
cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Event

# --- Canonical event types --------------------------------------------------
# Lifecycle / audit events (no derived-state effect):
EVENT_AGENT_REGISTERED = "agent_registered"
EVENT_AGENT_DEACTIVATED = "agent_deactivated"
EVENT_PERMISSION_DENIED = "permission_denied"

EVENT_MESSAGE_SENT = "message_sent"       # payload: {message_id, to, from_agent_id}

# OMS lifecycle events (audit only — no effect on derived state):
EVENT_ORDER_PLACED = "order_placed"       # payload: {order_id, pod_id, ticker, side, ...}
EVENT_ORDER_REJECTED = "order_rejected"   # payload: {order_id, reason, detail}
EVENT_ORDER_CANCELLED = "order_cancelled" # payload: {order_id}

# State-changing events consumed by the rebuild reducers. Every reducer-backed
# event MUST carry ``pod_id`` in its payload: that is how the incremental
# applier (app/ledger/apply.py) knows which derived rows to load and rewrite.
EVENT_ALLOCATION_SET = "allocation_set"   # payload: {pod_id, delta}
EVENT_ORDER_FILLED = "order_filled"       # payload: {pod_id, ticker, side, qty, fill_price, fee}


def append_event(
    session: Session,
    *,
    type: str,
    actor_agent_id: int | None,
    payload: dict | None = None,
) -> Event:
    """Append one immutable event, timestamped from the injected clock.

    The caller owns the transaction (commit/rollback). We flush so the event's
    ``id`` is populated for anyone who needs it in the same unit of work.
    """
    event = Event(
        ts=get_clock().now(),
        actor_agent_id=actor_agent_id,
        type=type,
        payload_json=payload or {},
    )
    session.add(event)
    session.flush()
    return event


def read_events(
    session: Session,
    *,
    actor_agent_id: int | None = None,
    type: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> Sequence[Event]:
    """Query the ledger in deterministic order (ts, then insertion id)."""
    stmt = select(Event)
    if actor_agent_id is not None:
        stmt = stmt.where(Event.actor_agent_id == actor_agent_id)
    if type is not None:
        stmt = stmt.where(Event.type == type)
    if since is not None:
        stmt = stmt.where(Event.ts >= since)
    stmt = stmt.order_by(Event.ts, Event.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return session.execute(stmt).scalars().all()
