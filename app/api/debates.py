"""The debate before a seed (idea: the pitch, then a full report; first slice). Under the debate
law an eligible pitch waits in its debate: the firm's reviewers and its PM argue it in its thread,
the firm's manager seeds it now or holds it (:mod:`app.capital.debate`).

Thin: scope each read to who may see it (a reviewer or the manager: every debate; a pod member:
its own pod's), delegate, translate refusals.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.schemas import IdPath
from app.capital.debate import (
    MAX_ARGUMENT,
    MAX_REASON,
    DebateError,
    NotYourDebate,
    argue,
    debate_view,
    debates,
    list_debates,
    own_pitch,
    rule,
)
from app.db.base import get_session
from app.db.models import Agent, AgentRole
from app.registry.auth import deny, require
from app.registry.permissions import Action

router = APIRouter(tags=["debate"])

#: Roles that read every debate: the centre's minds.
_READ_ALL = (AgentRole.reviewer, AgentRole.manager)


class ArgueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_ARGUMENT,
                      description="Your argument, in your words: everyone in the debate reads it.")


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["seed", "hold"] = Field(
        description="seed: the centre pays the law's seed the next morning; hold: the seed is "
                    "refused and the PM reads your reason.")
    reason: str = Field(default="", max_length=MAX_REASON,
                        description="Why (required for a hold): the PM reads it.")


def _answer(exc: DebateError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.detail)


def _readable(session: Session, actor: Agent, pitch_id: int) -> None:
    """403 (logged) unless ``actor`` may read ``pitch_id``'s debate; 404 if there is none. A pod
    member is asked first whether the pitch is its own, with one answer for every other: whether
    another pod's pitch is in debate is not told (red-team)."""
    if actor.role not in _READ_ALL and not own_pitch(session, pitch_id, actor):
        raise deny(session, actor, Action.READ_DEBATES,
                   detail=f"pitch {pitch_id} is not your pod's",
                   context={"pitch_id": pitch_id})
    if debates(session).get(pitch_id) is None:
        raise HTTPException(404, detail=f"pitch {pitch_id} has no debate")


@router.get("/debates", response_model=list[dict[str, Any]])
def get_debates(
    status: Literal["open", "all"] = Query(default="open",
                                           description="open: those still argued; all: every one."),
    actor: Agent = Depends(require(Action.READ_DEBATES)),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """The pitches in debate before their seed (a pod member: its own pod's), oldest first: the
    pitch (hypothesis, rule, the gates' numbers), the day it closes, the thread, the verdict."""
    if actor.role not in _READ_ALL and actor.pod_id is None:
        return []
    return list_debates(session, pod_id=None if actor.role in _READ_ALL else actor.pod_id,
                        open_only=status == "open")


@router.get("/debates/{pitch_id}", response_model=dict[str, Any])
def get_debate(
    pitch_id: IdPath,
    actor: Agent = Depends(require(Action.READ_DEBATES)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """One pitch's debate."""
    _readable(session, actor, pitch_id)
    return debate_view(session, pitch_id)


@router.post("/debates/{pitch_id}/argue", response_model=dict[str, Any], status_code=201)
def post_argument(
    pitch_id: IdPath,
    body: ArgueIn,
    actor: Agent = Depends(require(Action.ARGUE)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Write in a pitch's debate thread while it is open: a reviewer in any, a PM in its own
    pod's. At most five posts each."""
    try:
        return argue(session, pitch_id=pitch_id, text=body.text, actor=actor)
    except NotYourDebate as exc:
        raise deny(session, actor, Action.ARGUE, detail=str(exc),
                   context={"pitch_id": pitch_id}) from exc
    except DebateError as exc:
        raise _answer(exc) from exc


@router.post("/debates/{pitch_id}/verdict", response_model=dict[str, Any], status_code=201)
def post_verdict(
    pitch_id: IdPath,
    body: RuleIn,
    actor: Agent = Depends(require(Action.MANAGE_FIRM)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Rule once on a pitch in debate, while it is open: seed (paid the next morning) or hold
    (refused, with your reason). No verdict: the seed is paid when the debate closes. The
    manager only."""
    try:
        return rule(session, pitch_id=pitch_id, verdict=body.verdict, reason=body.reason,
                    actor=actor)
    except DebateError as exc:
        raise _answer(exc) from exc
