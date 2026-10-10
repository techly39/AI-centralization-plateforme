"""The bus: every message that crosses an agent or pod boundary (TRD §7).

Where to look:

* :mod:`app.bus.refs` — the addressing format (``agent:3``, ``pod:1``,
  ``broadcast``) and its parser.
* :mod:`app.bus.messages` — sending, visibility, and the read/polling query.
* :mod:`app.bus.notify` — messages the *app itself* sends (order rejections).
* :mod:`app.bus.errors` — what can go wrong and the code each failure carries.

Principle 2 of the TRD lives here: agents never talk to each other directly, so
there is exactly one record of what was said, and it is queryable.
"""

from app.bus.errors import (
    BroadcastNotPermittedError,
    BusAccessError,
    BusError,
    ConflictingCursorsError,
    InvalidRecipientError,
    PodScopeError,
    SenderNotPermittedError,
    UnknownRecipientError,
)
from app.bus.messages import (
    MAX_PAGE,
    count_messages_sent_by_pod,
    list_messages,
    resolve_audience,
    send_message,
    visible_to,
)
from app.bus.notify import notify_agent
from app.bus.refs import BROADCAST, Recipient, agent_ref, parse_ref, pod_ref

__all__ = [
    "BROADCAST",
    "MAX_PAGE",
    "BroadcastNotPermittedError",
    "BusAccessError",
    "BusError",
    "ConflictingCursorsError",
    "InvalidRecipientError",
    "PodScopeError",
    "Recipient",
    "SenderNotPermittedError",
    "UnknownRecipientError",
    "agent_ref",
    "count_messages_sent_by_pod",
    "list_messages",
    "notify_agent",
    "parse_ref",
    "pod_ref",
    "resolve_audience",
    "send_message",
    "visible_to",
]
