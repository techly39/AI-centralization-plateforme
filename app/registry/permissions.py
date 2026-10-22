"""The permission matrix from TRD §6, enforced in the API layer.

Permissions live in code, never in prompts. Some actions are additionally scoped
to "own pod" (place orders, broadcast) — that pod check is applied by the
relevant endpoint in the phase that implements it; this module answers the
coarse "may this role ever do X" question, which is the Phase 0 gate.
"""

from __future__ import annotations

import enum
from typing import Any

from app.db.models import AgentRole


class Action(str, enum.Enum):
    SEND_MESSAGE = "send_message"
    READ_MESSAGES = "read_messages"        # own inbox; cross-agent needs READ_CROSS_POD
    LIST_AGENTS = "list_agents"
    READ_MARKET_DATA = "read_market_data"
    READ_OWN_PORTFOLIO = "read_own_portfolio"
    REPORT_COST = "report_cost"            # always about oneself (see app/metrics/reporting.py)
    REPORT_TASK = "report_task"            # always about oneself
    PLACE_ORDER = "place_order"            # own pod (scope enforced in OMS)
    READ_CROSS_POD = "read_cross_pod"      # other pods' metrics/logs/events
    SET_ALLOCATION = "set_allocation"
    BROADCAST = "broadcast"                # own pod for pm; any for management
    REGISTER_AGENTS = "register_agents"
    DEACTIVATE_AGENTS = "deactivate_agents"
    READ_HALT = "read_halt"                # is the world halted? (GET /halt)
    READ_CLOCK = "read_clock"              # the fund's now (GET /clock) — ADR-026
    CONTROL_CLOCK = "control_clock"        # advance a backtest clock — ADR-027
    REPORT_METERED_COST = "report_metered_cost"  # system-reported cost of an agent — ADR-041
    RUN_RESEARCH = "run_research"          # research backtests for the own pod (ADR-048)
    SUBMIT_PITCH = "submit_pitch"          # pitch a strategy for the own pod (ADR-048)
    READ_PITCHES = "read_pitches"          # own pod's pitches and research; others need READ_CROSS_POD
    REQUEST_TEAM = "request_team"          # a PM asks for (and lets go) its own pod's analysts
    MANAGE_FIRM = "manage_firm"            # the manager mind: pick a freed place's hire, set direction
    READ_HEADLINES = "read_headlines"      # the world's headlines, with the agent's data right
    READ_COMPANY_DATA = "read_company_data"  # companies' quarterly reports, with the data right
    READ_DEBATES = "read_debates"          # pitches in debate and their threads (a pod member: its own)
    ARGUE = "argue"                        # write in a pitch's debate thread (a PM: its own pod's)


#: Actions the TRD §6 table does not list because they are not privileges at
#: all: every authenticated agent may read its own inbox, report its own cost
#: and work, ask whether the world is halted, and read the clock (ADR-026: in
#: backtest the fund's now is a simulated date an agent cannot learn elsewhere).
#: They are still Actions rather than bare "any agent may" checks
#: so that the matrix below stays a complete description of the API surface —
#: one place to look, and one place to change.
_UNIVERSAL: frozenset[Action] = frozenset(
    {
        Action.READ_MESSAGES,
        Action.REPORT_COST,
        Action.REPORT_TASK,
        Action.READ_HALT,
        Action.READ_CLOCK,
    }
)


# Role -> set of permitted actions: the TRD §6 table plus ``_UNIVERSAL`` (ADR-023, ADR-026).
_MATRIX: dict[AgentRole, frozenset[Action]] = {
    AgentRole.analyst: _UNIVERSAL
    | frozenset(
        {
            Action.SEND_MESSAGE,
            Action.LIST_AGENTS,
            Action.READ_MARKET_DATA,
            Action.READ_OWN_PORTFOLIO,
            Action.RUN_RESEARCH,
            Action.READ_PITCHES,
            Action.READ_HEADLINES,
            Action.READ_COMPANY_DATA,
            Action.READ_DEBATES,
        }
    ),
    AgentRole.pm: _UNIVERSAL
    | frozenset(
        {
            Action.SEND_MESSAGE,
            Action.LIST_AGENTS,
            Action.READ_MARKET_DATA,
            Action.READ_OWN_PORTFOLIO,
            Action.PLACE_ORDER,
            Action.BROADCAST,
            Action.RUN_RESEARCH,
            Action.SUBMIT_PITCH,
            Action.READ_PITCHES,
            Action.REQUEST_TEAM,
            Action.READ_HEADLINES,
            Action.READ_COMPANY_DATA,
            Action.READ_DEBATES,
            Action.ARGUE,
        }
    ),
    AgentRole.management: _UNIVERSAL
    | frozenset(
        {
            Action.SEND_MESSAGE,
            Action.LIST_AGENTS,
            Action.READ_MARKET_DATA,
            Action.READ_OWN_PORTFOLIO,
            Action.READ_CROSS_POD,
            Action.SET_ALLOCATION,
            Action.BROADCAST,
            Action.REGISTER_AGENTS,
            Action.DEACTIVATE_AGENTS,
            Action.READ_PITCHES,
        }
    ),
    # 'manager' is the firm's manager mind (idea: management above the pods): it reads every pod
    # and picks among the hires the law lists, briefs the new PM and writes the firm's direction.
    # It is not the registrar: it registers, deactivates, moves capital, trades and pitches
    # nothing (the TRD's 'management' role is the operator's registrar, which the Runtime holds).
    AgentRole.manager: _UNIVERSAL
    | frozenset(
        {
            Action.SEND_MESSAGE,
            Action.LIST_AGENTS,
            Action.READ_MARKET_DATA,
            Action.READ_CROSS_POD,
            Action.READ_PITCHES,
            Action.MANAGE_FIRM,
            Action.READ_DEBATES,
        }
    ),
    # 'reviewer' is a centre mind that argues pitches (idea: the pitch, then a full report; the
    # debate): it reads the pitches in debate and the data the operator gave it, and writes in a
    # pitch's thread, nowhere else. No pod: it cannot trade, pitch, research, message, hire or rule.
    # Nor does it read an inbox: nobody lobbies it off the thread (red-team, the debate).
    AgentRole.reviewer: (_UNIVERSAL - {Action.READ_MESSAGES})
    | frozenset(
        {
            Action.READ_MARKET_DATA,
            Action.READ_HEADLINES,
            Action.READ_COMPANY_DATA,
            Action.READ_DEBATES,
            Action.ARGUE,
        }
    ),
    # 'runtime' is the Runtime's identity (ADR-033, B-032): it moves a backtest's
    # clock between lockstep steps and does nothing a participant does — not
    # even the universal inbox / cost / task reports, so no ledger row it writes
    # can pass for agent activity. The world's time is not a firm agent's lever
    # (Art. 10), so management lost CONTROL_CLOCK — a TRD §6 deviation, in the ADR.
    # It also posts the *metered* cost of other agents (ADR-041): a metering row
    # is physics' attestation about an agent, never activity of the runtime
    # itself, and no firm role holds the right.
    AgentRole.runtime: frozenset(
        {
            Action.READ_HALT,
            Action.READ_CLOCK,
            Action.CONTROL_CLOCK,
            Action.REPORT_METERED_COST,
        }
    ),
    # 'system' is the internal/bootstrap identity and may do anything.
    AgentRole.system: frozenset(Action),
}

#: Physics' own identities (ADR-033): created only by code or the operator CLI,
#: never registered over HTTP, never deactivated by a firm agent, and their
#: names are reserved so no agent can wear them.
PHYSICS_ROLES: frozenset[AgentRole] = frozenset({AgentRole.system, AgentRole.runtime})


def has_permission(role: AgentRole, action: Action) -> bool:
    return action in _MATRIX.get(role, frozenset())


def may_hire(session: Any, actor: Any) -> bool:
    """Hiring (filling or refusing a vacancy) is the Runtime's act through the operator's
    registrar: a role that registers agents, made by the operator's own command, never by another
    agent over HTTP (red-team, a dead pod is replaced: else a firm mind takes a hire the Runtime
    refused for the cap and holds a second identity)."""
    from app.registry.service import registered_by_operator   # it imports this module

    return (has_permission(actor.role, Action.REGISTER_AGENTS)
            and registered_by_operator(session, actor))


#: Centre minds: no pod, made only by the operator's registrar.
CENTRE_ROLES: frozenset[AgentRole] = frozenset({AgentRole.manager, AgentRole.reviewer})


def may_register_role(session: Any, actor: Any, role: AgentRole) -> bool:
    """Who may make an agent of ``role``: the firm's manager and its reviewers only by the
    operator's registrar (a management agent another agent made does not make the firm's
    management)."""
    return role not in CENTRE_ROLES or may_hire(session, actor)


def may_declare_model(session: Any, actor: Any, role: AgentRole) -> bool:
    """Declaring the model an agent runs on (a founding PM's design, which a child inherits under
    the reproduction law) is the operator's registrar's act, and only for a PM: a firm mind that
    registers agents does not put a model on the record (red-team, designs reproduce)."""
    return role == AgentRole.pm and may_hire(session, actor)


# --- data rights (idea: data packages) ----------------------------------------------------------

#: What an agent may be granted beyond prices, which every reader holds. Each is one Action.
DATA_RIGHTS: dict[str, Action] = {"headlines": Action.READ_HEADLINES,
                                  "company": Action.READ_COMPANY_DATA}


def data_rights(session: Any, agent_id: int) -> frozenset[str]:
    """The data rights the ledger grants ``agent_id`` (never taken back while it lives): folded
    from ``data_rights_granted``, so a rebuilt world holds exactly the same."""
    from sqlalchemy import select

    from app.db.models import Event
    from app.ledger.events import EVENT_DATA_RIGHTS_GRANTED

    held: set[str] = set()
    for payload in session.scalars(select(Event.payload_json).where(
            Event.type == EVENT_DATA_RIGHTS_GRANTED)):
        if payload.get("agent_id") == agent_id:
            held.update(r for r in payload.get("rights", ()) if r in DATA_RIGHTS)
    return frozenset(held)


def data_right_problem(session: Any, agent: Any, right: str) -> str | None:
    """Why ``agent`` may not read ``right``'s data, else ``None``. The role must hold the right's
    action, and the agent the right itself (physics' own identity reads everything)."""
    if right not in DATA_RIGHTS:
        return f"no data named {right!r}"
    if agent.role == AgentRole.system:
        return None
    if not has_permission(agent.role, DATA_RIGHTS[right]):
        return f"a {agent.role.value} reads no {right}: only PMs and analysts are given data"
    if right not in data_rights(session, agent.id):
        return (f"you hold no right to {right}: your data is "
                f"{', '.join(['prices', *sorted(data_rights(session, agent.id))])} (the operator "
                f"grants data at registration; a PM may ask for an analyst with it)")
    return None


def may_grant_data(session: Any, actor: Any, role: AgentRole) -> bool:
    """Granting data at registration is the operator's registrar's act, and only to a PM, an
    analyst or a reviewer: a firm mind that registers agents hands out no data."""
    return (role in (AgentRole.pm, AgentRole.analyst, AgentRole.reviewer)
            and may_hire(session, actor))


def grant_data(session: Any, *, agent_id: int, rights: Any, by: Any, how: str) -> None:
    """Write ``data_rights_granted`` (nothing when ``rights`` is empty). The caller has checked
    who may grant, and owns the transaction."""
    from app.ledger.events import EVENT_DATA_RIGHTS_GRANTED, append_event

    rights = sorted(set(rights))
    if not rights:
        return
    if not set(rights) <= set(DATA_RIGHTS):
        raise ValueError(f"data rights are {sorted(DATA_RIGHTS)}")
    append_event(session, type=EVENT_DATA_RIGHTS_GRANTED,
                 actor_agent_id=by.id if by is not None else None,
                 payload={"agent_id": agent_id, "rights": rights,
                          "by": by.name if by is not None else None, "how": how})
