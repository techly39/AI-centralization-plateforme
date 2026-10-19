"""Clock endpoints (TRD §7, ADR-026, ADR-027).

Every authenticated agent may read the clock (ADR-026, amending TRD §7's
"system/management only" for the read): in backtest mode the fund's now is a
simulated date, and an agent has no other honest way to learn it.

Moving it is ``POST /clock/advance``: backtest runs only, ``CONTROL_CLOCK``
(the Runtime's ``runtime`` identity and ``system`` — never a firm agent, ADR-033). There is no ``POST /clock/mode``: the
mode is a fact of the run's database, fixed when it was created (ADR-027).

``POST /run/minds`` is the same hand saying what drives the run's minds, once,
before anything has happened in it (ADR-032 (p)). It lives here because it is
the conductor's word about the run, under the conductor's permission.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import (
    ClockAdvanceIn,
    ClockAdvanceOut,
    ClockOut,
    RunMindsIn,
    RunMindsOut,
)
from app.capital.service import safe_sweep
from app.clock import get_clock
from app.db.base import get_session
from app.db.models import Agent
from app.ledger.events import ledger_now
from app.marketdata import get_provider
from app.oms.monitor import check_pending_orders
from app.registry.auth import require
from app.registry.permissions import Action
from app.run_clock import RunClockError, RunMindsError, advance, declare_minds

router = APIRouter(tags=["clock"])


@router.get("/clock", response_model=ClockOut)
def read_clock(
    _: Agent = Depends(require(Action.READ_CLOCK)),
    session: Session = Depends(get_session),
) -> ClockOut:
    # ``now`` is the ledger's now, not the raw clock: the stamp the agent's next
    # event will carry, even after the clock steps back (red-team 0006).
    return ClockOut(mode=get_clock().mode, now=ledger_now(session))


@router.post("/clock/advance", response_model=ClockAdvanceOut)
def advance_clock(
    body: ClockAdvanceIn,
    agent: Agent = Depends(require(Action.CONTROL_CLOCK)),
    session: Session = Depends(get_session),
) -> ClockAdvanceOut:
    try:
        previous, now = advance(
            session, minutes=body.total_minutes, actor_agent_id=agent.id
        )
    except RunClockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    # Pending limit orders are checked on every advance, by the same sweep the
    # live scheduler runs on a timer (TRD §9): one code path for both modes.
    sweep = check_pending_orders(session)
    # Then the capital machine (idea: capital follows results): the drawdown ladder, seeds for
    # eligible pitches, and the re-weighing when it is due. A no-op until a pitch is eligible.
    safe_sweep(session, provider=get_provider())
    return ClockAdvanceOut(
        mode=get_clock().mode,
        previous=previous,
        now=now,
        filled_order_ids=sweep.filled,
        rejected_order_ids=sweep.rejected,
    )


@router.post("/run/minds", response_model=RunMindsOut, status_code=status.HTTP_201_CREATED)
def declare_run_minds(
    body: RunMindsIn,
    agent: Agent = Depends(require(Action.CONTROL_CLOCK)),
    session: Session = Depends(get_session),
) -> RunMindsOut:
    try:
        event = declare_minds(session, minds=body.minds, actor_agent_id=agent.id)
    except RunMindsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return RunMindsOut(
        minds=event.payload_json["minds"], declared_at=event.ts, event_id=event.id
    )
