"""Ledger query endpoint (TRD §10). Cross-pod reads are management-only."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import EventOut
from app.db.base import get_session
from app.db.models import Agent
from app.ledger.events import read_events
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(tags=["observability"])


@router.get("/events", response_model=list[EventOut])
def list_events(
    actor: int | None = Query(default=None, description="Filter by acting agent id."),
    type: str | None = Query(default=None, description="Filter by event type."),
    since: datetime | None = Query(default=None, description="Only events at/after this time."),
    limit: int = Query(default=200, ge=1, le=1000),
    _: Agent = Depends(require(Action.READ_CROSS_POD)),
    session: Session = Depends(get_session),
) -> list[EventOut]:
    events = read_events(
        session, actor_agent_id=actor, type=type, since=since, limit=limit
    )
    return [EventOut.model_validate(e) for e in events]
