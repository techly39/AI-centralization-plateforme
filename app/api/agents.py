"""Registry endpoints: register, directory, deactivate (TRD §7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import (
    AgentCreatedResponse,
    AgentRegisterRequest,
    DeactivateResponse,
    DirectoryEntry,
)
from app.db.base import get_session
from app.db.models import Agent, AgentRole
from app.registry.auth import require
from app.registry.permissions import Action
from app.registry.service import (
    RegistryError,
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
    try:
        agent, api_key = register_agent(
            session,
            name=body.name,
            role=AgentRole(body.role),
            pod_id=body.pod_id,
            charter_ref=body.charter_ref,
            research_domains=body.research_domains,
            actor_agent_id=actor.id,
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


@router.get("/agents", response_model=list[DirectoryEntry])
def directory(
    _: Agent = Depends(require(Action.LIST_AGENTS)),
    session: Session = Depends(get_session),
) -> list[DirectoryEntry]:
    return [DirectoryEntry.model_validate(a) for a in list_directory(session)]


@router.post("/agents/{agent_id}/deactivate", response_model=DeactivateResponse)
def deactivate(
    agent_id: int,
    actor: Agent = Depends(require(Action.DEACTIVATE_AGENTS)),
    session: Session = Depends(get_session),
) -> DeactivateResponse:
    try:
        agent = deactivate_agent(session, agent_id=agent_id, actor_agent_id=actor.id)
        session.commit()
    except RegistryError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DeactivateResponse(id=agent.id, status=agent.status)
