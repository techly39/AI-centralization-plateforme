"""Pods: creation and funding.

A pod is a trading desk: a name, a virtual cash allocation, and the agents
attached to it. Nothing in Phase 1 can be exercised without one — a PM with no
pod has nothing to trade with — so the operator CLI needs these two operations
even though the management **API** for allocations belongs to Phase 3 (TRD §11).

:func:`fund_pod` is written so that Phase 3's ``POST /allocations`` can call it
unchanged: it takes an acting agent, appends the ``allocation_set`` event, folds
that event into cash, and records the allocation row. When the endpoint arrives
it supplies the real management agent instead of the built-in system identity,
and nothing else changes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Agent, Allocation, Pod
from app.ledger.apply import apply_event_to_db
from app.ledger.events import EVENT_ALLOCATION_SET, append_event
from app.registry.service import RegistryError


def create_pod(session: Session, *, name: str) -> Pod:
    """Create a trading pod. Names are unique."""
    if session.scalar(select(Pod).where(Pod.name == name)) is not None:
        raise RegistryError(f"a pod named {name!r} already exists")
    pod = Pod(name=name, status="active", current_allocation=0.0,
              created_at=get_clock().now())
    session.add(pod)
    session.flush()
    return pod


def get_pod(session: Session, pod_id: int) -> Pod:
    pod = session.get(Pod, pod_id)
    if pod is None:
        raise RegistryError(f"no pod with id {pod_id}")
    return pod


def fund_pod(
    session: Session,
    *,
    pod_id: int,
    delta: float,
    actor: Agent,
    reason: str | None = None,
) -> Pod:
    """Move a pod's allocation by ``delta`` (negative withdraws).

    The cash balance is *not* written directly: the event is appended and the
    balance is derived from it, so a ``rebuild-state`` reproduces this exactly.
    """
    pod = get_pod(session, pod_id)

    event = append_event(
        session,
        type=EVENT_ALLOCATION_SET,
        actor_agent_id=actor.id,
        payload={"pod_id": pod_id, "delta": float(delta), "reason": reason},
    )
    apply_event_to_db(session, event)

    pod.current_allocation = pod.current_allocation + float(delta)
    session.add(
        Allocation(
            ts=event.ts,
            pod_id=pod_id,
            delta=float(delta),
            new_total=pod.current_allocation,
            set_by=actor.id,
            reason=reason,
        )
    )
    session.flush()
    return pod
