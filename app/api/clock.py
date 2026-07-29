"""Clock endpoint (TRD §7). Read-only in Phase 0 — live mode only.

``POST /clock/mode`` and ``POST /clock/advance`` (backtest control) arrive in
Phase 3. Clock access is management/system-only per the TRD, gated here via the
same cross-pod read permission that management/system hold.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas import ClockOut
from app.clock import get_clock
from app.db.models import Agent
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(tags=["clock"])


@router.get("/clock", response_model=ClockOut)
def read_clock(_: Agent = Depends(require(Action.READ_CROSS_POD))) -> ClockOut:
    clock = get_clock()
    return ClockOut(mode=clock.mode, now=clock.now())
