"""Management above the pods (idea: a manager chooses the hires). The firm's manager reads the
board (every pod), picks a freed place's hire among the candidates its vacancy lists and writes the
firm's direction (:mod:`app.capital.management`). Every agent reads the direction.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.schemas import IdPath
from app.capital.management import (
    MAX_BRIEF,
    MAX_DIRECTION,
    ManagementError,
    board,
    direction,
    pick,
    set_direction,
)
from app.db.base import get_session
from app.db.models import Agent
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(tags=["management"])


class PickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str = Field(min_length=1, max_length=16,
                           description="A candidate's id from the vacancy's list (c1, c2, ...).")
    brief: str = Field(default="", max_length=MAX_BRIEF,
                       description="What the new PM is told, from you, on its first morning.")


class DirectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_DIRECTION,
                      description="The firm's direction, in your words: every PM reads it.")


def _answer(exc: ManagementError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.detail)


@router.get("/board", response_model=dict[str, Any])
def get_board(
    _: Agent = Depends(require(Action.READ_CROSS_POD)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Every pod not closed (cash, positions, exposures, the centre's capital in it, stage,
    drawdown, thinking cost, last month's fitness, design) and the firm's centre."""
    return board(session)


@router.post("/vacancies/{vacancy_id}/pick", response_model=dict[str, Any])
def post_pick(
    vacancy_id: IdPath,
    body: PickIn,
    actor: Agent = Depends(require(Action.MANAGE_FIRM)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Pick who fills a freed place: one of its vacancy's candidates, once, before the fill, with
    a brief for the new PM. The manager only."""
    try:
        return pick(session, vacancy_id=vacancy_id, candidate=body.candidate, brief=body.brief,
                    actor=actor)
    except ManagementError as exc:
        raise _answer(exc) from exc


@router.get("/direction", response_model=dict[str, Any])
def get_direction(
    # The manager's word to the firm, read like a message: every firm agent, never the clock key.
    _: Agent = Depends(require(Action.READ_MESSAGES)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """The firm's latest direction (``null`` while none is written)."""
    return {"direction": direction(session)}


@router.post("/direction", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def post_direction(
    body: DirectionIn,
    actor: Agent = Depends(require(Action.MANAGE_FIRM)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Write the firm's direction. The manager only."""
    try:
        return {"direction": set_direction(session, text=body.text, actor=actor)}
    except ManagementError as exc:
        raise _answer(exc) from exc
