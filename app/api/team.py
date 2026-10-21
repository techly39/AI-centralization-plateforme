"""Teams (idea: pods, a PM and a small team): a PM asks for an analyst it describes, physics grants
a team place or refuses by name (:mod:`app.capital.team`), and the operator's registrar fills the
place the next morning. A pod's PM and analysts read their team; management reads every pod's.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.schemas import IdPath
from app.capital.team import (
    MAX_CHARTER,
    MAX_REASON,
    TeamError,
    fill,
    let_go,
    places,
    refuse,
    request_analyst,
    team_of,
)
from app.db.base import get_session
from app.db.models import Agent
from app.limits import MAX_ID
from app.registry.auth import deny, require
from app.registry.permissions import Action, has_permission, may_hire

router = APIRouter(tags=["team"])


class AnalystIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    charter: str = Field(min_length=1, max_length=MAX_CHARTER,
                         description="Who the analyst is and what it must do, in your words.")
    model: str = Field(min_length=1, max_length=100,
                       description="A model from the team law's pool (GET /team).")
    budget_usd: float = Field(gt=0, le=50, description="Its thinking budget (its key's limit).")


class RefuseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON,
                        description="Why the hire cannot be made now, in plain words.")


def _answer(exc: TeamError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.detail)


def _operator_only(session: Session, actor: Agent, place_id: int) -> None:
    if not may_hire(session, actor):
        raise deny(session, actor, Action.REGISTER_AGENTS,
                   detail="only the operator's registrar hires: a firm mind does not fill or "
                          "refuse a team place", context={"place_id": place_id})


@router.get("/team", response_model=dict[str, Any])
def get_team(
    pod_id: int | None = Query(default=None, ge=1, le=MAX_ID,
                               description="Default: your own pod."),
    actor: Agent = Depends(require(Action.READ_PITCHES)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Your pod's team: the team law, every analyst place (waiting, working, let go, closed) with
    its charter, model, budget and spending, the team budget taken and left, and every request
    physics refused. Another pod's needs the right to read across pods."""
    target = pod_id if pod_id is not None else actor.pod_id
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="you have no pod: name one")
    if target != actor.pod_id and not has_permission(actor.role, Action.READ_CROSS_POD):
        raise deny(session, actor, Action.READ_CROSS_POD,
                   detail=f"pod {target}'s team is not yours to read", context={"pod_id": target})
    return team_of(session, target)


@router.post("/team/analysts", response_model=dict[str, Any],
             status_code=status.HTTP_201_CREATED)
def post_analyst(
    body: AnalystIn,
    actor: Agent = Depends(require(Action.REQUEST_TEAM)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Ask for an analyst for your pod. Granted: a team place, hired the next morning (201).
    Refused by name (409, in the ledger): the law off, the pool, the pod's limit, its team budget,
    the Human's agent cap. PMs only."""
    try:
        return request_analyst(session, actor=actor, charter=body.charter, model=body.model,
                               budget_usd=body.budget_usd)
    except TeamError as exc:
        raise _answer(exc) from exc


@router.post("/team/places/{place_id}/let-go", response_model=dict[str, Any])
def post_let_go(
    place_id: IdPath,
    actor: Agent = Depends(require(Action.REQUEST_TEAM)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Let your analyst go (its key stops working), or withdraw a place not yet filled. Your own
    pod's places only."""
    try:
        return let_go(session, place_id=place_id, actor=actor)
    except TeamError as exc:
        if exc.status == 403:
            raise deny(session, actor, Action.REQUEST_TEAM, detail=exc.detail,
                       context={"place_id": place_id}) from exc
        raise _answer(exc) from exc


@router.get("/team/places", response_model=list[dict[str, Any]])
def get_places(
    actor: Agent = Depends(require(Action.READ_CROSS_POD)),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Every team place of the run, oldest first. Management only (the Runtime hires from it)."""
    return places(session)


@router.post("/team/places/{place_id}/fill", response_model=dict[str, Any],
             status_code=status.HTTP_201_CREATED)
def post_fill(
    place_id: IdPath,
    actor: Agent = Depends(require(Action.REGISTER_AGENTS)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Hire the analyst a team place names, into its PM's pod. Its key is in this answer and
    nowhere else, once. Refused (409, in the ledger) past the agent cap, or when its PM or pod is
    gone (the place closes). The operator's registrar only."""
    _operator_only(session, actor, place_id)
    try:
        found, agent, key = fill(session, place_id=place_id, actor=actor)
    except TeamError as exc:
        raise _answer(exc) from exc
    return {"place": found,
            "agent": {"id": agent.id, "name": agent.name, "role": agent.role.value,
                      "pod_id": agent.pod_id, "api_key": key}}


@router.post("/team/places/{place_id}/refuse", response_model=dict[str, Any])
def post_refuse(
    place_id: IdPath,
    body: RefuseIn,
    actor: Agent = Depends(require(Action.REGISTER_AGENTS)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Refuse a team hire for now (the Runtime: its key does not fit the cap). The place stays
    open; the refusal is in the ledger. The operator's registrar only."""
    _operator_only(session, actor, place_id)
    try:
        return refuse(session, place_id=place_id, reason=body.reason, actor=actor)
    except TeamError as exc:
        raise _answer(exc) from exc
