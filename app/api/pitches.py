"""Research backtests and pitches (ADR-048; idea: the pitch and the gates).

Thin: scope to the caller's pod, delegate to :mod:`app.strategy.service`, translate errors. A
pod's research and pitches are its own: reading another pod's needs ``read_cross_pod``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.schemas import IdPath, PitchIn, PitchOut, ResearchBacktestIn, ResearchBacktestOut
from app.config import get_settings
from app.db.base import get_session
from app.db.models import Agent, Event
from app.ledger.events import EVENT_PITCH_SUBMITTED
from app.limits import MAX_ID
from app.marketdata import MarketDataError, get_provider
from app.registry.auth import deny, require
from app.registry.permissions import Action, has_permission
from app.strategy.service import (
    NotAPodMember,
    StrategyRequestError,
    list_pitches,
    list_research,
    run_research,
    submit_pitch,
)

router = APIRouter(tags=["strategy science"])


def _scope(session: Session, actor: Agent, pod_id: int | None, action: Action) -> int | None:
    """The pod a read is about: the caller's own by default; another, or all (``None``, for a
    caller with no pod), only with cross-pod rights."""
    if pod_id is None and actor.pod_id is not None:
        return actor.pod_id
    if (pod_id is not None and pod_id == actor.pod_id) or has_permission(actor.role,
                                                                          Action.READ_CROSS_POD):
        return pod_id
    raise deny(session, actor, action, detail=(
        "you have no pod: name none you may not read" if pod_id is None
        else f"pod {pod_id} is not your pod"), context={"pod_id": pod_id})


def _refuse(session: Session, actor: Agent, action: Action, exc: Exception) -> HTTPException:
    if isinstance(exc, NotAPodMember):
        return deny(session, actor, action, detail=str(exc), context={})
    if isinstance(exc, StrategyRequestError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/research/backtests", response_model=ResearchBacktestOut,
             status_code=status.HTTP_201_CREATED)
def post_research_backtest(
    body: ResearchBacktestIn,
    actor: Agent = Depends(require(Action.RUN_RESEARCH)),
    session: Session = Depends(get_session),
) -> ResearchBacktestOut:
    """Backtest a strategy rule on the past, before the held-out days. Counted for your pod."""
    settings = get_settings()
    try:
        result = run_research(session, actor=actor, rule=body.rule, start=body.start,
                              end=body.end, provider=get_provider(), law=settings.gates,
                              fee_rate=settings.oms.fee_rate)
    except (NotAPodMember, StrategyRequestError, MarketDataError) as exc:
        session.rollback()
        raise _refuse(session, actor, Action.RUN_RESEARCH, exc)
    session.commit()
    return ResearchBacktestOut.model_validate(result)


@router.get("/research/backtests", response_model=list[ResearchBacktestOut])
def get_research_backtests(
    pod_id: int | None = Query(default=None, ge=1, le=MAX_ID,
                               description="Default: your own pod."),
    actor: Agent = Depends(require(Action.READ_PITCHES)),
    session: Session = Depends(get_session),
) -> list[ResearchBacktestOut]:
    """Every research backtest of a pod, oldest first: the attempts its pitches are judged with."""
    pod = _scope(session, actor, pod_id, Action.READ_PITCHES)
    if pod is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name a pod_id")
    return [ResearchBacktestOut.model_validate(r) for r in list_research(session, pod_id=pod)]


@router.post("/pitches", response_model=PitchOut, status_code=status.HTTP_201_CREATED)
def post_pitch(
    body: PitchIn,
    actor: Agent = Depends(require(Action.SUBMIT_PITCH)),
    session: Session = Depends(get_session),
) -> PitchOut:
    """Pitch a strategy for your pod: the gates judge it on the held-out days, now."""
    settings = get_settings()
    try:
        pitch = submit_pitch(session, actor=actor, rule=body.rule, hypothesis=body.hypothesis,
                             data_needed=body.data_needed, team=body.team,
                             budget_usd=body.budget_usd, provider=get_provider(),
                             law=settings.gates, fee_rate=settings.oms.fee_rate)
    except (NotAPodMember, StrategyRequestError, MarketDataError) as exc:
        session.rollback()
        raise _refuse(session, actor, Action.SUBMIT_PITCH, exc)
    session.commit()
    return PitchOut.model_validate(pitch)


@router.get("/pitches", response_model=list[PitchOut])
def get_pitches(
    pod_id: int | None = Query(default=None, ge=1, le=MAX_ID,
                               description="Default: your own pod (management: every pod)."),
    actor: Agent = Depends(require(Action.READ_PITCHES)),
    session: Session = Depends(get_session),
) -> list[PitchOut]:
    """Every pitch of a pod, oldest first, each with the gates' verdict."""
    pod = _scope(session, actor, pod_id, Action.READ_PITCHES)
    return [PitchOut.model_validate(p) for p in list_pitches(session, pod_id=pod)]


@router.get("/pitches/{pitch_id}", response_model=PitchOut)
def get_pitch(
    pitch_id: IdPath,
    actor: Agent = Depends(require(Action.READ_PITCHES)),
    session: Session = Depends(get_session),
) -> PitchOut:
    """One pitch and its verdict."""
    event = session.get(Event, pitch_id)
    if event is None or event.type != EVENT_PITCH_SUBMITTED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no pitch {pitch_id}")
    pod = _scope(session, actor, event.payload_json.get("pod_id"), Action.READ_PITCHES)
    return next(PitchOut.model_validate(p) for p in list_pitches(session, pod_id=pod)
                if p["id"] == pitch_id)
