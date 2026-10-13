"""System-reported cost endpoint (ADR-041) — the Runtime's identity only.

The Runtime's provisioner knows what each key it minted has really cost; the
Runtime posts that total here. No firm agent holds the right, and a body names
the agent explicitly because the caller is never the subject: attribution comes
from the key's binding, not from who asks. See :mod:`app.metrics.metering`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import MeteredUsageIn, MeteredUsageOut
from app.db.base import get_session
from app.db.models import Agent
from app.metrics.metering import (
    METER_LOCK,
    KeyBoundElsewhere,
    NotAFirmAgent,
    UnknownMeteredAgent,
    UsageDecreased,
    record_metered_usage,
)
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(prefix="/metering", tags=["metering"])


@router.post("/usage", response_model=MeteredUsageOut)
def post_metered_usage(
    body: MeteredUsageIn,
    actor: Agent = Depends(require(Action.REPORT_METERED_COST)),
    session: Session = Depends(get_session),
) -> MeteredUsageOut:
    """Record a key's cumulative cost for the agent it was minted for."""
    # The lock spans the check, the append and the commit: two posts for one key
    # cannot both pass the check.
    with METER_LOCK:
        try:
            event = record_metered_usage(
                session,
                actor=actor,
                agent_id=body.agent_id,
                key_ref=body.key_ref,
                usd_micros_total=body.usd_micros_total,
            )
            session.commit()
        except UnknownMeteredAgent as exc:
            session.rollback()
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message)
        except NotAFirmAgent as exc:
            session.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
        except (KeyBoundElsewhere, UsageDecreased) as exc:
            session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message)
    return MeteredUsageOut(
        agent_id=body.agent_id,
        key_ref=body.key_ref,
        usd_micros_total=body.usd_micros_total,
        recorded=event is not None,
        event_id=event.id if event is not None else None,
    )
