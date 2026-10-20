"""Agent registry: identity lifecycle and directory lookups.

All writes append a matching event to the ledger so the audit trail is complete.
The caller (API layer / CLI) owns the transaction.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Agent, AgentRole, AgentStatus, Event
from app.ledger.events import (
    EVENT_AGENT_DEACTIVATED,
    EVENT_AGENT_KEY_ROTATED,
    EVENT_AGENT_REGISTERED,
    append_event,
)
from app.registry.permissions import PHYSICS_ROLES
from app.registry.security import generate_api_key, hash_api_key


class RegistryError(Exception):
    """Raised for registry-level problems (duplicate name, missing agent)."""


class ReservedIdentityError(RegistryError):
    """An act on one of physics' own identities that no caller may do (ADR-033)."""


#: Name of the built-in identity the app itself acts under (rejection notices,
#: scheduled fills). It is a real row so that foreign keys and the audit trail
#: work, but it is never handed an API key anyone can use.
SYSTEM_AGENT_NAME = "system"
#: Name of the Runtime's identity, the only holder of ``CONTROL_CLOCK`` besides
#: ``system`` (ADR-033). Created by ``fund-env seed-runtime``, one per database.
RUNTIME_AGENT_NAME = "runtime"
_RESERVED_NAMES = frozenset({SYSTEM_AGENT_NAME, RUNTIME_AGENT_NAME})


#: Categories that draw nothing of their own: controls, format characters,
#: unassigned/private/surrogate code points, and combining marks (variation
#: selectors, the grapheme joiner, Khmer U+17B4 — red-team 0014 H1). Dropping a
#: visible mark too only widens what counts as reserved: the safe side.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cn", "Co", "Cs", "Mn", "Me"})
#: Letters and symbols that render blank (Hangul fillers, braille blank), after NFKC.
_BLANK_CHARS = frozenset("ᅟᅠㅤﾠ⠀")


def _name_key(name: str) -> str:
    """The name as a reader sees it: NFKC, case-folded, characters that draw
    nothing dropped, surrounding space stripped. Lookalikes from other scripts
    (Cyrillic 'с') are not folded — the identity is the role, the reserved name
    only keeps the directory honest."""
    folded = unicodedata.normalize("NFKC", name).casefold()
    return "".join(
        c for c in folded
        if unicodedata.category(c) not in _INVISIBLE_CATEGORIES and c not in _BLANK_CHARS
    ).strip()


def is_reserved_name(name: str) -> bool:
    return _name_key(name) in _RESERVED_NAMES


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

    Physics' identities (``system``, ``runtime``) are not registered here, and
    no agent may take their names (ADR-033, B-000f).
    """
    if role in PHYSICS_ROLES:
        raise ReservedIdentityError(f"role {role.value!r} is physics' own; it is not registered")
    if is_reserved_name(name):
        raise ReservedIdentityError(f"the name {name!r} is reserved")
    return _create_agent(session, name=name, role=role, pod_id=pod_id,
                         charter_ref=charter_ref, research_domains=research_domains,
                         actor_agent_id=actor_agent_id)


def _create_agent(
    session: Session,
    *,
    name: str,
    role: AgentRole,
    pod_id: int | None,
    charter_ref: str | None,
    research_domains: list[str] | None,
    actor_agent_id: int | None,
) -> tuple[Agent, str]:
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
    if agent.role in PHYSICS_ROLES:
        # A firm agent switching off the world's clock hand (or physics' own
        # notices) would be a participant pulling a world lever (Art. 10).
        raise ReservedIdentityError(f"agent {agent_id} is physics' own identity")

    agent.status = AgentStatus.inactive
    session.flush()
    append_event(
        session,
        type=EVENT_AGENT_DEACTIVATED,
        actor_agent_id=actor_agent_id,
        payload={"agent_id": agent.id},
    )
    return agent


def registered_by_operator(session: Session, agent: Agent) -> bool:
    """Was ``agent`` made by the operator's own command (``fund-env seed-admin``, a genesis), not
    by another agent over HTTP? Its ``agent_registered`` names no actor. A run's minds are always
    registered by a registrar, so no mind is operator-made (red-team, pod replacement: hiring is
    the Runtime's act, through the operator's registrar, never a firm mind's)."""
    for event in session.scalars(select(Event).where(Event.type == EVENT_AGENT_REGISTERED)
                                 .order_by(Event.id)):
        if (event.payload_json or {}).get("agent_id") == agent.id:
            return event.actor_agent_id is None
    return False


def get_or_create_system_agent(session: Session) -> Agent:
    """The app's own identity, created on first use.

    Its API key is generated, hashed, and immediately discarded: nothing can
    authenticate as ``system`` over HTTP, which is the point — internal actions
    are attributable without opening a back door.

    Found by *role*, never by name (B-000f): a name is something an agent could
    have been given; the role is not.
    """
    agent = session.scalar(
        select(Agent).where(Agent.role == AgentRole.system).order_by(Agent.id).limit(1)
    )
    if agent is not None:
        return agent
    if session.scalar(select(Agent).where(Agent.name == SYSTEM_AGENT_NAME)) is not None:
        # Only a database written before ADR-033 can hold this: an ordinary agent
        # registered as 'system'. Fail loudly rather than borrow its identity.
        raise ReservedIdentityError(
            f"the name {SYSTEM_AGENT_NAME!r} is held by a non-system agent "
            "(registered before ADR-033); the operator must rename it"
        )

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


def seed_runtime_agent(session: Session) -> tuple[Agent, str]:
    """Create the Runtime's identity and return it with its key (shown once).

    One per database: the Runtime is one conductor, and a second clock hand
    would be a second, unaccounted lever on the world's time (ADR-033). Like
    ``system`` it is found by role; the name is reserved so no agent wears it.
    """
    existing = session.scalar(
        select(Agent).where(Agent.role == AgentRole.runtime).order_by(Agent.id).limit(1)
    )
    if existing is not None:
        raise ReservedIdentityError(
            f"this database already has a runtime identity (id {existing.id})"
        )
    return _create_agent(session, name=RUNTIME_AGENT_NAME, role=AgentRole.runtime,
                         pod_id=None, charter_ref=None, research_domains=None,
                         actor_agent_id=None)


def rotate_runtime_key(session: Session) -> tuple[Agent, str]:
    """Give the Runtime's identity a new key and return it (shown once) — B-041.

    The old key stops working in the same commit: its hash is replaced, not
    kept beside the new one. A lost or leaked key would otherwise freeze the
    backtest or leave a second hand on its clock. Operator-only (no endpoint):
    a firm agent rotating the clock hand's key would be pulling a world lever.
    The event names the agent, never the key or its hash.
    """
    runtimes = session.execute(
        select(Agent).where(Agent.role == AgentRole.runtime).order_by(Agent.id)
    ).scalars().all()
    if not runtimes:
        raise RegistryError("this database has no runtime identity (fund-env seed-runtime)")
    if len(runtimes) > 1:
        raise ReservedIdentityError(
            f"this database has {len(runtimes)} runtime identities; it must have one"
        )
    agent = runtimes[0]
    api_key = generate_api_key()
    agent.api_key_hash = hash_api_key(api_key)
    session.flush()
    append_event(session, type=EVENT_AGENT_KEY_ROTATED, actor_agent_id=None,
                 payload={"agent_id": agent.id})
    return agent, api_key


def reserved_identity_problems(session: Session) -> list[str]:
    """What, in this database, breaks ADR-033's reserved identities (B-041).

    A database written before ADR-033 can hold an ordinary agent wearing a
    reserved name; a hand-edited one, two runtime rows. Either is found at
    startup (server and operator CLI), not at the first act that needs the
    identity. Read-only: the operator repairs, physics never renames an agent.
    """
    problems = [
        f"agent {a.id} ({a.role.value}) holds the reserved name {a.name!r}"
        for a in list_directory(session)
        if a.role not in PHYSICS_ROLES and is_reserved_name(a.name)
    ]
    runtimes = session.scalar(
        select(func.count()).select_from(Agent).where(Agent.role == AgentRole.runtime)
    ) or 0
    if runtimes > 1:
        problems.append(f"{runtimes} runtime identities; a database has at most one")
    return problems


def check_reserved_identities(session: Session) -> None:
    """Raise :class:`ReservedIdentityError` naming every problem, if there is one."""
    problems = reserved_identity_problems(session)
    if problems:
        raise ReservedIdentityError(
            "reserved identities are broken (ADR-033): " + "; ".join(problems)
            + ". The operator must repair the database before it runs."
        )


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
