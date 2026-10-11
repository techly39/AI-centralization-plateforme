"""FastAPI authentication & authorization dependencies.

Every request must present ``X-API-Key``. :func:`get_current_agent` resolves it
to an active agent (401 otherwise) and refuses writes while the world is halted
(423, :mod:`app.registry.halt`). :func:`require` builds a dependency that
enforces one :class:`Action` from the permission matrix, logging a
``permission_denied`` event and returning 403 on violation (TRD §6).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.db.models import Agent
from app.ledger.events import EVENT_PERMISSION_DENIED, append_event
from app.registry.halt import refuse_if_halted
from app.registry.permissions import Action, has_permission
from app.registry.service import get_agent_by_api_key

# auto_error=False so we can return our own 401 body/logging instead of FastAPI's.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_current_agent(
    request: Request,
    api_key: str | None = Security(_api_key_header),
    session: Session = Depends(get_session),
) -> Agent:
    agent = get_agent_by_api_key(session, api_key or "")
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    # Every authenticated endpoint passes through here, so this one line is the
    # whole halt gate for the API (app/registry/halt.py).
    refuse_if_halted(request, session, agent)
    return agent


def deny(
    session: Session,
    agent: Agent,
    action: Action,
    *,
    detail: str,
    context: dict | None = None,
) -> HTTPException:
    """Log a permission violation and build the 403 to raise (TRD §6).

    Used for checks the coarse role matrix cannot express — above all "is this
    *your* pod". Returns the exception rather than raising it so the call site
    reads ``raise deny(...)`` and control flow stays obvious.
    """
    append_event(
        session,
        type=EVENT_PERMISSION_DENIED,
        actor_agent_id=agent.id,
        payload={
            "action": action.value,
            "role": agent.role.value,
            "detail": detail,
            **(context or {}),
        },
    )
    session.commit()
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require(action: Action) -> Callable[..., Agent]:
    """Return a dependency that admits only agents permitted to do ``action``."""

    def _dependency(
        agent: Agent = Depends(get_current_agent),
        session: Session = Depends(get_session),
    ) -> Agent:
        if not has_permission(agent.role, action):
            append_event(
                session,
                type=EVENT_PERMISSION_DENIED,
                actor_agent_id=agent.id,
                payload={"action": action.value, "role": agent.role.value},
            )
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{agent.role.value}' may not perform '{action.value}'.",
            )
        return agent

    return _dependency
