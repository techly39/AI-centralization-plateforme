"""Messaging endpoints (TRD §7). Polling only — no websockets in v1 (§12).

The router parses, delegates to :mod:`app.bus`, and translates failures into HTTP.
Every rule about who may address whom lives in the bus service, so the MCP server
in this same phase gets identical behaviour without restating a single one.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.schemas import MessageOut, MessageSendRequest
from app.bus import (
    BusAccessError,
    ConflictingCursorsError,
    InvalidRecipientError,
    UnknownRecipientError,
    list_messages,
    send_message,
)
from app.bus.messages import MAX_PAGE
from app.db.base import get_session
from app.db.models import Agent
from app.registry.auth import deny, require
from app.registry.permissions import Action, has_permission

router = APIRouter(tags=["messaging"])


@router.post("/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def post_message(
    body: MessageSendRequest,
    actor: Agent = Depends(require(Action.SEND_MESSAGE)),
    session: Session = Depends(get_session),
) -> MessageOut:
    """Put a message on the bus.

    The response's ``to`` is the audience that actually received it, which is
    not always what was asked for: a PM's ``broadcast`` is scoped to their own
    pod (TRD §6). Read it back rather than assuming.
    """
    try:
        message = send_message(
            session,
            sender=actor,
            to=body.to,
            body=body.body,
            thread_id=body.thread_id,
            structured_payload=body.structured_payload,
        )
        session.commit()
    except InvalidRecipientError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except UnknownRecipientError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message)
    except BusAccessError as exc:
        session.rollback()
        # Logged as a permission_denied event, like every other 403 (TRD §6).
        raise deny(
            session,
            actor,
            Action.BROADCAST,
            detail=exc.message,
            context={"to": body.to, "code": exc.code},
        )

    return MessageOut.model_validate(message)


@router.get("/messages", response_model=list[MessageOut])
def get_messages(
    since: datetime | None = Query(
        default=None, description="Only messages at or after this clock time."
    ),
    thread: str | None = Query(default=None, description="Filter to one thread_id."),
    mine: bool = Query(
        default=True,
        description=(
            "True (default): only messages you sent, were sent, or that went to "
            "your pod or the whole firm. False: the entire bus — management only."
        ),
    ),
    after_id: int | None = Query(
        default=None,
        ge=0,
        description=(
            "Forward cursor: only messages with a higher id. Prefer this over "
            "'since' for polling — it stays correct when many messages share a "
            "timestamp."
        ),
    ),
    before_id: int | None = Query(
        default=None,
        ge=0,
        description=(
            "Backward cursor: only messages with a lower id. Use it to page "
            "into history, oldest page last. Cannot be combined with 'after_id'."
        ),
    ),
    latest: bool = Query(
        default=False,
        description=(
            "Start at the end of the ledger: return the newest 'limit' messages "
            "in one call, instead of the oldest. Cannot be combined with "
            "'after_id'."
        ),
    ),
    limit: int = Query(default=200, ge=1, le=MAX_PAGE),
    actor: Agent = Depends(require(Action.READ_MESSAGES)),
    session: Session = Depends(get_session),
) -> list[MessageOut]:
    """Your messages, oldest first — append them to your transcript in order.

    Two ways to read, and they do not mix:

    * **forward** (polling) — call with no cursor, remember the last ``id`` you
      saw, then call again with ``after_id=<that id>``;
    * **backward** (catching up) — ``latest=true`` for the newest page, then
      ``before_id=<lowest id you have>`` to keep walking back.

    Either way the page itself comes back oldest-first.
    """
    if not mine and not has_permission(actor.role, Action.READ_CROSS_POD):
        raise deny(
            session,
            actor,
            Action.READ_CROSS_POD,
            detail="reading other agents' messages requires management rights",
        )

    try:
        messages = list_messages(
            session,
            viewer=actor,
            mine=mine,
            since=since,
            thread_id=thread,
            after_id=after_id,
            before_id=before_id,
            latest=latest,
            limit=limit,
        )
    except ConflictingCursorsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)

    return [MessageOut.model_validate(m) for m in messages]
