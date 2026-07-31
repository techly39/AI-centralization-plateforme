"""Agent registry: identity lifecycle and directory lookups.

All writes append a matching event to the ledger so the audit trail is complete.
The caller (API layer / CLI) owns the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Agent, AgentRole, AgentStatus
from app.ledger.events import (
    EVENT_AGENT_DEACTIVATED,
    EVENT_AGENT_REGISTERED,
    append_event,
)
from app.registry.security import generate_api_key, hash_api_key


class RegistryError(Exception):
    """Raised for registry-level problems (duplicate name, missing agent)."""


def register_agent(
    session: Session,
    *,
    name: str,
    role: AgentRole,
    pod_id: int | None = None,
    charter_ref: str | None = None,
    research_domains: list[str] | None = None,
    actor_agent_id: int | None = None,
) -> tuple[Agent, str]:
    """Create an agent and return it together with its plaintext API key.

    The plaintext key exists only in this return value — it is never stored, so
    the caller must surface it to the operator immediately and once.
    """
    if session.scalar(select(Agent).where(Agent.name == name)) is not None:
        raise RegistryError(f"an agent named {name!r} already exists")

    api_key = generate_api_key()
    agent = Agent(
        name=name,
        role=role,
        pod_id=pod_id,
        api_key_hash=hash_api_key(api_key),
        charter_ref=charter_ref,
        research_domains=research_domains,
        status=AgentStatus.active,
        created_at=get_clock().now(),
    )
    session.add(agent)
    session.flush()  # populate agent.id

    append_event(
        session,
        type=EVENT_AGENT_REGISTERED,
        actor_agent_id=actor_agent_id,
        payload={
            "agent_id": agent.id,
            "name": name,
            "role": role.value,
            "pod_id": pod_id,
        },
    )
    return agent, api_key


def deactivate_agent(
    session: Session,
    *,
    agent_id: int,
    actor_agent_id: int | None = None,
) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise RegistryError(f"no agent with id {agent_id}")

    agent.status = AgentStatus.inactive
    session.flush()
    append_event(
        session,
        type=EVENT_AGENT_DEACTIVATED,
        actor_agent_id=actor_agent_id,
        payload={"agent_id": agent.id},
    )
    return agent


#: Name of the built-in identity the app itself acts under (rejection notices,
#: scheduled fills). It is a real row so that foreign keys and the audit trail
#: work, but it is never handed an API key anyone can use.
SYSTEM_AGENT_NAME = "system"


def get_or_create_system_agent(session: Session) -> Agent:
    """The app's own identity, created on first use.

    Its API key is generated, hashed, and immediately discarded: nothing can
    authenticate as ``system`` over HTTP, which is the point — internal actions
    are attributable without opening a back door.
    """
    agent = session.scalar(select(Agent).where(Agent.name == SYSTEM_AGENT_NAME))
    if agent is not None:
        return agent

    agent = Agent(
        name=SYSTEM_AGENT_NAME,
        role=AgentRole.system,
        pod_id=None,
        api_key_hash=hash_api_key(generate_api_key()),
        charter_ref=None,
        status=AgentStatus.active,
        created_at=get_clock().now(),
    )
    session.add(agent)
    session.flush()
    return agent


def get_agent_by_api_key(session: Session, api_key: str) -> Agent | None:
    """Look up the active agent owning ``api_key``; ``None`` if unknown/inactive."""
    if not api_key:
        return None
    agent = session.scalar(
        select(Agent).where(Agent.api_key_hash == hash_api_key(api_key))
    )
    if agent is None or agent.status is not AgentStatus.active:
        return None
    return agent


def list_directory(session: Session) -> Sequence[Agent]:
    """All agents, ordered by id — the shared directory."""
    return session.execute(select(Agent).order_by(Agent.id)).scalars().all()


def count_agents(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Agent)) or 0
