"""What the bus refuses to do, and why.

Same shape as :mod:`app.oms.errors`: every failure carries a machine-readable
``code`` so an agent can branch on the failure without parsing English (TRD §10),
and the API layer decides the HTTP status from the class, not from the text.

There is no "stored failure" category here. Unlike an order — which can be
legitimately *rejected* and still exist as a record — a message either goes on
the bus or does not exist at all.
"""

from __future__ import annotations


class BusError(Exception):
    """Base class for messaging failures."""

    code = "bus_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class InvalidRecipientError(BusError):
    """The ``to`` field is not a legal address (HTTP 422)."""

    code = "invalid_recipient"


class UnknownRecipientError(BusError):
    """The address is well-formed but names an agent or pod that does not exist.

    Mapped to HTTP 404 rather than silently accepted: a message to nobody is a
    bug in the sender's directory lookup, and swallowing it would let an agent
    believe it had communicated when it had not.
    """

    code = "unknown_recipient"


class ConflictingCursorsError(BusError):
    """A read asked to page forward and backward at once (HTTP 422).

    ``after_id`` and ``before_id``/``latest`` describe opposite directions, so a
    request carrying both has no single correct answer. Refusing is better than
    silently honouring one: a caller that thinks it is reading history while it
    is really tailing new traffic will lose messages without noticing.
    """

    code = "conflicting_cursors"


class BusAccessError(BusError):
    """The sender is not allowed to address this audience (HTTP 403, logged)."""

    code = "bus_access_denied"


class BroadcastNotPermittedError(BusAccessError):
    """The role may not broadcast (TRD §6: analysts may not)."""

    code = "broadcast_not_permitted"


class SenderNotPermittedError(BusAccessError):
    """The role may not send messages at all.

    The permission matrix grants ``send_message`` to every role, so in normal
    operation this never fires. It exists because the bus service re-checks the
    matrix itself and must stay correct if that matrix ever changes.
    """

    code = "sender_not_permitted"


class PodScopeError(BusAccessError):
    """A PM tried to broadcast without belonging to a pod to broadcast to."""

    code = "pod_scope"
