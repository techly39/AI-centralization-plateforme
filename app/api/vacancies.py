"""Vacancies: a pod the risk ladder closed, and the hire that replaces it (idea: a dead pod is
replaced). Physics opens a vacancy (:mod:`app.capital.hiring`); a registrar fills it or the Runtime
refuses the hire. Management reads every vacancy; the PM hired into one reads its own, with the
post-mortem of the pod it replaced.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.schemas import IdPath
from app.capital.hiring import MAX_REASON, HiringError, fill, refuse, vacancies, vacancy
from app.db.base import get_session
from app.db.models import Agent
from app.registry.auth import deny, get_current_agent, require
from app.registry.permissions import Action, has_permission, may_hire

router = APIRouter(tags=["vacancies"])


class RefuseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON,
                        description="Why the hire cannot be made now, in plain words.")


def _answer(exc: HiringError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.detail)


def _operator_only(session: Session, actor: Agent, vacancy_id: int) -> None:
    """Hiring is the Runtime's act through the operator's registrar: a management agent another
    agent registered (a firm mind) is refused, logged (red-team: else a mind takes a hire the
    Runtime refused for the cap, and holds a second identity)."""
    if not may_hire(session, actor):
        raise deny(session, actor, Action.REGISTER_AGENTS,
                   detail="only the operator's registrar hires: a firm mind does not fill or "
                          "refuse a vacancy", context={"vacancy_id": vacancy_id})


@router.get("/vacancies", response_model=list[dict[str, Any]])
def get_vacancies(
    actor: Agent = Depends(require(Action.READ_CROSS_POD)),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Every vacancy of the run, oldest first: the dead pod, its post-mortem, the hire the law
    names, and whether it is filled."""
    return vacancies(session)


@router.get("/vacancies/{vacancy_id}", response_model=dict[str, Any])
def get_vacancy(
    vacancy_id: IdPath,
    actor: Agent = Depends(get_current_agent),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """One vacancy with the post-mortem of the pod it replaces. Yours to read if your pod filled
    it; management reads every one."""
    try:
        found = vacancy(session, vacancy_id)
    except HiringError as exc:
        if has_permission(actor.role, Action.READ_CROSS_POD):
            raise _answer(exc) from exc
        found = None
    mine = (found is not None and found["filled"] is not None and actor.pod_id is not None
            and found["filled"]["pod_id"] == actor.pod_id)
    if not mine and not has_permission(actor.role, Action.READ_CROSS_POD):
        # Not found and not yours answer alike: a pod member learns nothing of other vacancies.
        raise deny(session, actor, Action.READ_CROSS_POD,
                   detail=f"vacancy {vacancy_id} is not the one your pod filled",
                   context={"vacancy_id": vacancy_id})
    if "candidates" in found and not has_permission(actor.role, Action.READ_CROSS_POD):
        # The management law's list holds other live pods' rules (each candidate's parent): a pod
        # member reads its own hire only (red-team, a manager chooses the hires).
        found = {k: v for k, v in found.items() if k != "candidates"}
    return found


@router.post("/vacancies/{vacancy_id}/fill", response_model=dict[str, Any],
             status_code=status.HTTP_201_CREATED)
def post_fill(
    vacancy_id: IdPath,
    actor: Agent = Depends(require(Action.REGISTER_AGENTS)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Fill an open vacancy as its law says: a new pod and a new PM. The PM's key is in this answer
    and nowhere else, once. Refused (409, in the ledger) at the firm's pod limit. The operator's
    registrar only."""
    _operator_only(session, actor, vacancy_id)
    try:
        found, agent, key = fill(session, vacancy_id=vacancy_id, actor=actor)
    except HiringError as exc:
        raise _answer(exc) from exc
    return {"vacancy": found,
            "agent": {"id": agent.id, "name": agent.name, "role": agent.role.value,
                      "pod_id": agent.pod_id, "api_key": key}}


@router.post("/vacancies/{vacancy_id}/refuse", response_model=dict[str, Any])
def post_refuse(
    vacancy_id: IdPath,
    body: RefuseIn,
    actor: Agent = Depends(require(Action.REGISTER_AGENTS)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Refuse the hire for now (the Runtime: its budget does not fit the cap). The vacancy stays
    open; the refusal is in the ledger. The operator's registrar only."""
    _operator_only(session, actor, vacancy_id)
    try:
        return refuse(session, vacancy_id=vacancy_id, reason=body.reason, actor=actor)
    except HiringError as exc:
        raise _answer(exc) from exc
