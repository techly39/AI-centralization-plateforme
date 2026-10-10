"""Messages the app sends about itself.

TRD §8.2 requires the OMS to message the PM back when an order is rejected. That
notice is not a side channel: it is a real row in ``messages``, sent under the
built-in ``system`` identity, and it shows up in ``GET /messages`` beside
everything an agent said. Principle 2 has no exceptions, including for the app.

Every notice carries ``structured_payload_json`` as well as prose, per TRD §10:
an agent should be able to act on the numbers without parsing English.

The addressing format lives in :mod:`app.bus.refs` and the send path in
:mod:`app.bus.messages` — this module only decides *what* the app says.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.bus.messages import send_message
from app.bus.refs import agent_ref
from app.db.models import Message
from app.registry.service import get_or_create_system_agent


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
    return send_message(
        session,
        sender=system,
        to=agent_ref(to_agent_id),
        body=body,
        thread_id=thread_id,
        structured_payload=payload,
    )
