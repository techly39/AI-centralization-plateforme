"""Registry endpoints: register, directory, deactivate (TRD §7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import (
    IdPath,
    AgentCreatedResponse,
    AgentRegisterRequest,
    DeactivateResponse,
    DirectoryEntry,
)
from app.capital.hiring import hire_failed, staffing_problem
from app.capital.team import member_deactivated, team_follows
from app.db.base import get_session
from app.db.models import Agent, AgentRole
from app.oms.service import OMS_LOCK
from app.registry.auth import deny, get_current_agent, require
from app.registry.permissions import Action, may_declare_model
from app.registry.service import (
    RegistryError,
    ReservedIdentityError,
    deactivate_agent,
    list_directory,
    register_agent,
)

router = APIRouter(tags=["registry"])


@router.post(
    "/agents/register",
    response_model=AgentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    body: AgentRegisterRequest,
    actor: Agent = Depends(require(Action.REGISTER_AGENTS)),
    session: Session = Depends(get_session),
) -> AgentCreatedResponse:
    if body.model is not None and not may_declare_model(session, actor, AgentRole(body.role)):
        raise deny(session, actor, Action.REGISTER_AGENTS,
                   detail="only the operator's registrar declares a model, and only a PM's",
                   context={"name": body.name, "role": body.role})
    try:
        with OMS_LOCK:  # the cap is counted and the agent committed with no other maker between
            if body.pod_id is not None and (
                    problem := staffing_problem(session, pod_id=body.pod_id, actor=actor)):
                raise RegistryError(problem)
            agent, api_key = register_agent(
                session,
                name=body.name,
                role=AgentRole(body.role),
                pod_id=body.pod_id,
                charter_ref=body.charter_ref,
                research_domains=body.research_domains,
                actor_agent_id=actor.id,
                model=body.model,
            )
            session.commit()
    except RegistryError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return AgentCreatedResponse(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        pod_id=agent.pod_id,
        status=agent.status,
        created_at=agent.created_at,
        api_key=api_key,
    )


@router.get("/me", response_model=DirectoryEntry)
def me(actor: Agent = Depends(get_current_agent)) -> DirectoryEntry:
    """Who the calling API key belongs to: id, name, role, pod, coverage.

    Authentication only — no entry in the permission matrix. Knowing your own
    identity is not a privilege, and gating it would defeat the point: an agent
    that cannot ask who it is has to be *told*, in a prompt, which is a second
    copy of the database that starts drifting the moment anyone is moved
    between pods.

    Every other endpoint needs what this returns — ``pod_id`` for
    ``GET /portfolio/{pod_id}``, ``id`` so colleagues can be told how to reply —
    so a fresh agent's first call should be this one.
    """
    return DirectoryEntry.model_validate(actor)


@router.get("/agents", response_model=list[DirectoryEntry])
def directory(
    _: Agent = Depends(require(Action.LIST_AGENTS)),
    session: Session = Depends(get_session),
) -> list[DirectoryEntry]:
    return [DirectoryEntry.model_validate(a) for a in list_directory(session)]


@router.post("/agents/{agent_id}/deactivate", response_model=DeactivateResponse)
def deactivate(
    agent_id: IdPath,
    actor: Agent = Depends(require(Action.DEACTIVATE_AGENTS)),
    session: Session = Depends(get_session),
) -> DeactivateResponse:
    try:
        agent = deactivate_agent(session, agent_id=agent_id, actor_agent_id=actor.id)
        # A pod's team goes with its last PM (app/capital/team.py), before the hire is judged.
        if agent.role == AgentRole.pm and agent.pod_id is not None:
            team_follows(session, pod_id=agent.pod_id, reason="its PM was deactivated",
                         actor=actor)
        member_deactivated(session, agent=agent, actor=actor)
        # A hired PM gone before its pod's seed is a failed hire: its empty pod closes and the
        # vacancy opens again (app/capital/hiring.py).
        hire_failed(session, agent=agent, actor=actor)
        session.commit()
    except ReservedIdentityError as exc:  # physics' own identity (ADR-033)
        session.rollback()
        raise deny(session, actor, Action.DEACTIVATE_AGENTS, detail=str(exc),
                   context={"target_agent_id": agent_id, "reason": "reserved_identity"})
    except RegistryError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DeactivateResponse(id=agent.id, status=agent.status)
