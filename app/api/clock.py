"""Clock endpoint (TRD §7). Read-only in Phase 0 — live mode only.

Every authenticated agent may read the clock (ADR-026, amending TRD §7's
"system/management only" for the read): in backtest mode the fund's now is a
simulated date, and an agent has no other honest way to learn it.

``POST /clock/mode`` and ``POST /clock/advance`` (backtest control) arrive in
Phase 3 (B-004) and stay system/management-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import ClockOut
from app.clock import get_clock
from app.db.base import get_session
from app.db.models import Agent
from app.ledger.events import ledger_now
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(tags=["clock"])


@router.get("/clock", response_model=ClockOut)
def read_clock(
    _: Agent = Depends(require(Action.READ_CLOCK)),
    session: Session = Depends(get_session),
) -> ClockOut:
    # ``now`` is the ledger's now, not the raw clock: the stamp the agent's next
    # event will carry, even after the clock steps back (red-team 0006).
    return ClockOut(mode=get_clock().mode, now=ledger_now(session))
