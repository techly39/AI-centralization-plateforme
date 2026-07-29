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
    LIST_AGENTS = "list_agents"
    READ_MARKET_DATA = "read_market_data"
    READ_OWN_PORTFOLIO = "read_own_portfolio"
    PLACE_ORDER = "place_order"            # own pod (scope enforced in OMS)
    READ_CROSS_POD = "read_cross_pod"      # other pods' metrics/logs/events
    SET_ALLOCATION = "set_allocation"
    BROADCAST = "broadcast"                # own pod for pm; any for management
    REGISTER_AGENTS = "register_agents"
    DEACTIVATE_AGENTS = "deactivate_agents"


# Role -> set of permitted actions. Mirrors the TRD §6 table exactly.
_MATRIX: dict[AgentRole, frozenset[Action]] = {
    AgentRole.analyst: frozenset(
        {
            Action.SEND_MESSAGE,
            Action.LIST_AGENTS,
            Action.READ_MARKET_DATA,
            Action.READ_OWN_PORTFOLIO,
        }
    ),
    AgentRole.pm: frozenset(
        {
            Action.SEND_MESSAGE,
            Action.LIST_AGENTS,
            Action.READ_MARKET_DATA,
            Action.READ_OWN_PORTFOLIO,
            Action.PLACE_ORDER,
            Action.BROADCAST,
        }
    ),
    AgentRole.management: frozenset(
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
        }
    ),
    # 'system' is the internal/bootstrap identity and may do anything.
    AgentRole.system: frozenset(Action),
}


def has_permission(role: AgentRole, action: Action) -> bool:
    return action in _MATRIX.get(role, frozenset())
