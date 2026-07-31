"""System-to-agent notifications.

TRD §8.2 requires the OMS to message the PM back when an order is rejected, but
the full messaging API is Phase 2. Rather than invent a side channel (which
principle 2 forbids), this writes a real row into the ``messages`` table under
the built-in ``system`` identity. When Phase 2 builds ``GET /messages``, these
notices are already there and already in the right shape — no migration, no
backfill.

Every notice carries ``structured_payload_json`` as well as prose, per TRD §10:
an agent should be able to act on the numbers without parsing English.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Message
from app.ledger.events import EVENT_MESSAGE_SENT, append_event
from app.registry.service import get_or_create_system_agent

#: ``messages.to_ref`` holds a union — an agent, a pod, or everyone (TRD §5).
#: Bare ids would be ambiguous ("7" could be agent 7 or pod 7), so the kind is
#: written into the string. Decided here, before any message exists, so Phase 2
#: inherits one unambiguous format instead of a guessing rule.
BROADCAST = "broadcast"


def agent_ref(agent_id: int) -> str:
    return f"agent:{agent_id}"


def pod_ref(pod_id: int) -> str:
    return f"pod:{pod_id}"


def notify_agent(
    session: Session,
    *,
    to_agent_id: int,
    body: str,
    payload: dict | None = None,
    thread_id: str | None = None,
) -> Message:
    """Send one message from the app to a single agent and log it.

    The caller owns the transaction.
    """
    system = get_or_create_system_agent(session)
    message = Message(
        ts=get_clock().now(),
        from_agent=system.id,
        to_ref=agent_ref(to_agent_id),
        thread_id=thread_id,
        body=body,
        structured_payload_json=payload,
    )
    session.add(message)
    session.flush()

    append_event(
        session,
        type=EVENT_MESSAGE_SENT,
        actor_agent_id=system.id,
        payload={
            "message_id": message.id,
            "to": agent_ref(to_agent_id),
            "from_agent_id": system.id,
            "thread_id": thread_id,
        },
    )
    return message
