"""The permission matrix from TRD §6, enforced in the API layer.

Permissions live in code, never in prompts. Some actions are additionally scoped
to "own pod" (place orders, broadcast) — that pod check is applied by the
relevant endpoint in the phase that implements it; this module answers the
coarse "may this role ever do X" question, which is the Phase 0 gate.
"""

from __future__ import annotations

import enum

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
