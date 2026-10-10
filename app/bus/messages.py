"""The message bus (TRD §7 "Messaging", principle 2).

Everything that crosses a pod boundary goes through here and is logged. There is
no side channel: agents do not talk to each other, they talk to the app, and the
app keeps the record.

Three decisions worth knowing before you read the code:

**Addressing.** ``agent:<id>``, ``pod:<id>``, or ``broadcast`` — see
:mod:`app.bus.refs`. Any role may address an agent or a pod (TRD §6 "send
message (any agent/pod)"). ``broadcast`` is the restricted one: management may
address the whole firm, a PM's broadcast is *scoped to its own pod* (the TRD
grants pm "broadcast to a pod (own pod)"), and an analyst may not broadcast at
all. A PM's ``broadcast`` is therefore stored — and returned — as
``pod:<their pod>``: the effective audience, not the word they typed.

**Visibility.** A message is readable by its sender, by the agent it names, by
every member of the pod it names, and by everyone if it is a firm broadcast.
That predicate is written once, in :func:`visible_to`, and used by every read
path. Management can step outside it with ``mine=false``, which is the
``read_cross_pod`` right from the matrix.

**Polling cursors.** ``since`` filters on the *clock's* time, and in backtest
mode (Phase 3) the clock stands still — many messages will share one timestamp,
so a time cursor alone would skip or repeat them. ``after_id`` is the cursor
that always works: ids are monotonic in insertion order. Poll with ``after_id``,
filter with ``since``.

**Reading backwards.** ``after_id`` alone only ever walks forward from the
beginning, so an agent joining a fund that has been running for a month would
have to page through every message ever sent just to find out where the ledger
ends. ``latest=True`` returns the last page directly, and ``before_id`` walks
back from there. The two directions are mutually exclusive — see
:class:`~app.bus.errors.ConflictingCursorsError`. Whichever way a page was
gathered, it is returned oldest-first, so callers only ever deal with one order.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.bus.errors import (
    BroadcastNotPermittedError,
    ConflictingCursorsError,
    PodScopeError,
    SenderNotPermittedError,
    UnknownRecipientError,
)
from app.bus.refs import BROADCAST, Recipient, agent_ref, parse_ref, pod_ref
from app.clock import get_clock
from app.db.models import Agent, AgentRole, Message, Pod
from app.ledger.events import EVENT_MESSAGE_SENT, append_event
from app.registry.permissions import Action, has_permission

#: Cap on a single ``GET /messages`` page. Agents poll in a loop; an unbounded
#: read would let one call return a whole run's history and blow the context
#: window of whatever is reading it.
MAX_PAGE = 500


# --- Sending ----------------------------------------------------------------

def resolve_audience(session: Session, *, sender: Agent, to: str) -> Recipient:
    """Turn what the sender typed into the audience that will actually receive it.

    Applies the TRD §6 rules for who may address whom, and rewrites a PM's
    ``broadcast`` into its own pod. Returns the effective recipient.

    Raises:
        InvalidRecipientError: malformed address.
        UnknownRecipientError: no such agent/pod.
        SenderNotPermittedError / BroadcastNotPermittedError / PodScopeError.
    """
    if not has_permission(sender.role, Action.SEND_MESSAGE):
        raise SenderNotPermittedError(
            f"role {sender.role.value!r} may not send messages"
        )

    recipient = parse_ref(to)

    if recipient.kind == "broadcast":
        if not has_permission(sender.role, Action.BROADCAST):
            raise BroadcastNotPermittedError(
                f"role {sender.role.value!r} may not broadcast — address a "
                "specific agent ('agent:<id>') or pod ('pod:<id>') instead"
            )
        # Management (and the system identity) reach the whole firm. A PM's
        # broadcast is its own pod, per the "(own pod)" qualifier in TRD §6.
        if sender.role is AgentRole.pm:
            if sender.pod_id is None:
                raise PodScopeError(
                    f"{sender.name!r} belongs to no pod, so there is nothing to "
                    "broadcast to"
                )
            return Recipient(kind="pod", id=sender.pod_id)
        return recipient

    if recipient.kind == "agent":
        # A deactivated agent is still a legal recipient: the message is
        # recorded, and it is readable again if the agent comes back. Refusing
        # would throw away an audit trail to prevent nothing.
        if session.get(Agent, recipient.id) is None:
            raise UnknownRecipientError(
                f"no agent with id {recipient.id}",
                detail={"to": recipient.ref},
            )
    elif recipient.kind == "pod":
        if session.get(Pod, recipient.id) is None:
            raise UnknownRecipientError(
                f"no pod with id {recipient.id}",
                detail={"to": recipient.ref},
            )

    return recipient


def send_message(
    session: Session,
    *,
    sender: Agent,
    to: str,
    body: str,
    thread_id: str | None = None,
    structured_payload: dict | None = None,
) -> Message:
    """Put one message on the bus and log it to the ledger.

    The caller owns the transaction. Returns the stored message, whose
    ``to_ref`` is the *effective* audience (see the module docstring on
    broadcast scoping).
    """
    recipient = resolve_audience(session, sender=sender, to=to)

    message = Message(
        ts=get_clock().now(),
        from_agent=sender.id,
        to_ref=recipient.ref,
        thread_id=thread_id,
        body=body,
        structured_payload_json=structured_payload,
    )
    session.add(message)
    session.flush()  # populates message.id

    append_event(
        session,
        type=EVENT_MESSAGE_SENT,
        actor_agent_id=sender.id,
        payload={
            "message_id": message.id,
            "to": recipient.ref,
            "from_agent_id": sender.id,
            "thread_id": thread_id,
            # Present so ``GET /events?type=message_sent`` can be filtered by
            # pod without joining back to the messages table.
            "pod_id": recipient.id if recipient.kind == "pod" else sender.pod_id,
        },
    )
    return message


# --- Reading ----------------------------------------------------------------

def visible_to(viewer: Agent) -> ColumnElement[bool]:
    """The one definition of "messages this agent is entitled to read".

    Written as a SQL predicate rather than a post-filter so that ``limit`` means
    "the newest N messages *you can see*", not "the newest N messages, minus the
    ones you couldn't".
    """
    clauses = [
        Message.from_agent == viewer.id,
        Message.to_ref == BROADCAST,
        Message.to_ref == agent_ref(viewer.id),
    ]
    if viewer.pod_id is not None:
        clauses.append(Message.to_ref == pod_ref(viewer.pod_id))
    return or_(*clauses)


def list_messages(
    session: Session,
    *,
    viewer: Agent,
    mine: bool = True,
    since: datetime | None = None,
    thread_id: str | None = None,
    after_id: int | None = None,
    before_id: int | None = None,
    latest: bool = False,
    limit: int = 200,
) -> Sequence[Message]:
    """Messages in chronological order, oldest first.

    Oldest-first is what a polling loop needs: append what you got to your
    transcript and remember the last id. ``mine=False`` lifts the visibility
    filter and must only be reached by a caller the API has checked for
    ``read_cross_pod``.

    Args:
        after_id: page *forward* — only messages with a higher id. The polling
            cursor.
        before_id: page *backward* — only messages with a lower id. The way to
            walk into history one page at a time.
        latest: start at the end of the ledger rather than the beginning, so
            the newest ``limit`` messages come back in a single call.

    Raises:
        ConflictingCursorsError: ``after_id`` combined with ``before_id`` or
            ``latest``.
    """
    backwards = latest or before_id is not None
    if after_id is not None and backwards:
        raise ConflictingCursorsError(
            "read forwards or backwards, not both: use 'after_id' to poll for "
            "new messages, or 'latest'/'before_id' to read history",
            detail={"after_id": after_id, "before_id": before_id, "latest": latest},
        )

    stmt = select(Message)
    if mine:
        stmt = stmt.where(visible_to(viewer))
    if since is not None:
        stmt = stmt.where(Message.ts >= since)
    if thread_id is not None:
        stmt = stmt.where(Message.thread_id == thread_id)
    if after_id is not None:
        stmt = stmt.where(Message.id > after_id)
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)

    page = min(limit, MAX_PAGE)
    if backwards:
        # Take the newest `page` rows in the database's order, then flip them,
        # so the caller still gets oldest-first. Ordering by id as well as ts
        # matters for the same reason `after_id` exists: in backtest mode a
        # whole conversation can share one timestamp.
        stmt = stmt.order_by(Message.ts.desc(), Message.id.desc()).limit(page)
        return list(reversed(session.execute(stmt).scalars().all()))

    stmt = stmt.order_by(Message.ts, Message.id).limit(page)
    return session.execute(stmt).scalars().all()


def count_messages_sent_by_pod(session: Session, pod_id: int) -> int:
    """How many messages the agents of one pod have sent (a metrics input)."""
    return (
        session.scalar(
            select(func.count())
            .select_from(Message)
            .join(Agent, Agent.id == Message.from_agent)
            .where(Agent.pod_id == pod_id)
        )
        or 0
    )
