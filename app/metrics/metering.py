"""System-reported cost (ADR-041, TRD principle: the app never trusts a self-report it can replace).

``app/metrics/reporting.py`` holds what an agent *says* it spent. This module
holds what the Runtime's provisioner says each provisioned key has *actually*
cost, in total so far, in integer micro-dollars. Three rules make it usable as
the number pods are ranked on:

**Cumulative, never deltas.** A post carries a key's running total. A re-post of
the same total writes nothing, a retry cannot double-count, and a sync that was
refused during a HALT catches up exactly afterwards. The reader counts each key
once, at its maximum total.

**A key belongs to the first agent it names.** The binding is the key's first
``cost_metered`` event. A later event naming another agent is refused on the way
in (409) and ignored — and counted in ``conflicts`` — by the reader, so an event
forged straight into the ledger cannot move a key onto a rival.

**The ledger is the only store.** There is no table: :func:`metered_by_agent`
folds ``cost_metered`` events in id order, so a rebuild cannot disagree with it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Agent, Cost, Event
from app.ledger.events import EVENT_COST_METERED, append_event
from app.limits import MAX_ID, MAX_METERED_USD_MICROS
from app.registry.permissions import PHYSICS_ROLES

#: Held by the endpoint across the check, the append *and* the commit, so two
#: posts for one key cannot both pass the check. One process only: a second
#: server on the same file is the B-036 class (the reader's first-binding and
#: maximum-total rules still keep such a race from rebinding or double-counting).
METER_LOCK = threading.Lock()


class MeteringError(Exception):
    code = "metering_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnknownMeteredAgent(MeteringError):
    """No such agent (HTTP 404)."""

    code = "unknown_agent"


class NotAFirmAgent(MeteringError):
    """A physics identity cannot be metered (HTTP 422)."""

    code = "not_a_firm_agent"


class KeyBoundElsewhere(MeteringError):
    """The key's first event named another agent (HTTP 409)."""

    code = "key_bound_elsewhere"


class UsageDecreased(MeteringError):
    """A key's cumulative total never goes down (HTTP 409)."""

    code = "usage_decreased"


@dataclass(slots=True)
class AgentMetered:
    pod_id: int | None
    usd_micros: int


class MeteredLedger(dict[int, AgentMetered]):
    """``{agent_id: AgentMetered}`` plus how many events the reader had to ignore."""

    conflicts: int = 0
    malformed: int = 0


def _valid(payload: object) -> tuple[int, int | None, str, int] | None:
    """``(agent_id, pod_id, key_ref, total)`` from a payload, or ``None`` if it is not one."""
    if not isinstance(payload, dict):
        return None
    agent_id, pod_id = payload.get("agent_id"), payload.get("pod_id")
    key_ref, total = payload.get("key_ref"), payload.get("usd_micros_total")
    if type(agent_id) is not int or not 1 <= agent_id <= MAX_ID or not isinstance(key_ref, str):
        return None
    if pod_id is not None and (type(pod_id) is not int or not 1 <= pod_id <= MAX_ID):
        return None
    if type(total) is not int or not 0 <= total <= MAX_METERED_USD_MICROS:
        return None
    return agent_id, pod_id, key_ref, total


def metered_by_agent(session: Session, *, upto_event_id: int | None = None) -> MeteredLedger:
    """Each agent's metered micro-dollars: per key the maximum total, summed over keys
    (``upto_event_id``: as the ledger stood at that event, e.g. a generation's start).

    The first event of a key binds it to an agent; a later event for another
    agent counts as a conflict and is ignored. An event whose payload is not a
    well-formed metering row counts as malformed and is ignored.
    """
    stmt = select(Event.payload_json).where(Event.type == EVENT_COST_METERED)
    if upto_event_id is not None:
        stmt = stmt.where(Event.id <= upto_event_id)
    rows = session.execute(stmt.order_by(Event.id)).scalars()
    result = MeteredLedger()
    keys: dict[str, tuple[int, int | None, int]] = {}   # key_ref -> (agent, pod, max total)
    for payload in rows:
        parsed = _valid(payload)
        if parsed is None:
            result.malformed += 1
            continue
        agent_id, pod_id, key_ref, total = parsed
        bound = keys.get(key_ref)
        if bound is not None and bound[0] != agent_id:
            result.conflicts += 1
            continue
        keys[key_ref] = (agent_id, pod_id, max(total, bound[2] if bound else 0))
    for agent_id, pod_id, total in keys.values():
        entry = result.get(agent_id)
        if entry is None:
            result[agent_id] = AgentMetered(pod_id=pod_id, usd_micros=total)
        else:
            entry.usd_micros += total
            entry.pod_id = pod_id
    return result


def record_metered_usage(
    session: Session,
    *,
    actor: Agent,
    agent_id: int,
    key_ref: str,
    usd_micros_total: int,
) -> Event | None:
    """Record a key's cumulative total for an agent; ``None`` if nothing changed.

    Caller owns the transaction and holds :data:`METER_LOCK` through its commit.
    Inactive agents are accepted: spend lands after a deactivation.
    """
    # The API schema refuses these first (422); this guards in-process callers.
    if type(usd_micros_total) is not int or not 0 <= usd_micros_total <= MAX_METERED_USD_MICROS:
        raise ValueError(f"usd_micros_total outside 0..{MAX_METERED_USD_MICROS}")
    target = session.get(Agent, agent_id)
    if target is None:
        raise UnknownMeteredAgent(f"no agent with id {agent_id}")
    if target.role in PHYSICS_ROLES:
        raise NotAFirmAgent("a physics identity has no metered cost")

    # Same reading as the metrics: the key's first well-formed event binds it, and
    # an event for another agent after that (forged into the ledger) is ignored.
    bound: int | None = None
    latest: int | None = None
    payloads = session.execute(
        select(Event.payload_json).where(Event.type == EVENT_COST_METERED).order_by(Event.id)
    ).scalars()
    for payload in payloads:
        parsed = _valid(payload)
        if parsed is None or parsed[2] != key_ref:
            continue
        if bound is None:
            bound = parsed[0]
        if parsed[0] != bound:
            continue
        latest = parsed[3] if latest is None else max(latest, parsed[3])
    if bound is not None and bound != agent_id:
        raise KeyBoundElsewhere("this key already belongs to another agent")
    if latest is not None:
        if usd_micros_total < latest:
            raise UsageDecreased(f"a key's total never decreases (it is already {latest})")
        if usd_micros_total == latest:
            return None
    return append_event(
        session,
        type=EVENT_COST_METERED,
        actor_agent_id=actor.id,
        payload={
            "agent_id": agent_id,
            "pod_id": target.pod_id,
            "key_ref": key_ref,
            "usd_micros_total": usd_micros_total,
        },
    )


@dataclass(slots=True)
class MeteredAgentRow:
    agent_id: int
    pod_id: int | None
    usd_micros: int
    #: What the agent said it spent (``costs`` rows), shown beside the meter, never added to it.
    self_reported_usd: float


@dataclass(slots=True)
class MeteredSummary:
    agents: list[MeteredAgentRow]
    #: Σ of every key's maximum total; ``None`` when nothing is metered (unmeasured, not free).
    total_usd_micros: int | None
    conflicts: int
    malformed: int


def metered_summary(session: Session) -> MeteredSummary:
    """Each metered agent's metered cost and own self-report, with what the reader ignored.
    A pure fold of the ledger (plus the self-report table): a rebuild cannot disagree."""
    metered = metered_by_agent(session)
    reported: dict[int, float] = {}
    if metered:
        rows = session.execute(
            select(Cost.agent_id, func.coalesce(func.sum(Cost.usd_cost), 0.0))
            .where(Cost.agent_id.in_(list(metered))).group_by(Cost.agent_id)
        ).all()
        reported = {agent_id: float(total) for agent_id, total in rows}
    agents = [MeteredAgentRow(aid, m.pod_id, m.usd_micros, reported.get(aid, 0.0))
              for aid, m in sorted(metered.items())]
    total = sum(a.usd_micros for a in agents) if agents else None
    return MeteredSummary(agents, total, metered.conflicts, metered.malformed)
