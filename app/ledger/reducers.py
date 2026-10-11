"""Event reducers: pure functions that fold events into derived state.

``rebuild_state`` replays every event through these reducers to reconstruct the
``positions`` and ``cash_balances`` tables. Reducers must stay **pure and
deterministic** — no clock, no I/O, no randomness — so that replaying the same
events always yields identical state (TRD Definition of Done).

The order/allocation reducers encode the exact cash and average-cost arithmetic
the OMS will emit in Phase 1, so they are the single place that math lives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.db.models import Event
from app.ledger.events import EVENT_ALLOCATION_SET, EVENT_ORDER_FILLED

#: Quantities below this are treated as zero (float dust from partial sells).
#: Lives here, below the OMS, because the reducer is where a position closes;
#: the OMS re-exports it from ``app.oms.money`` for its sell check.
QTY_EPSILON = 1e-9


@dataclass
class DerivedState:
    """In-memory accumulator built during a replay."""

    # pod_id -> cash balance
    cash: dict[int, float] = field(default_factory=dict)
    # (pod_id, ticker) -> {"qty": float, "avg_cost": float}
    positions: dict[tuple[int, str], dict[str, float]] = field(default_factory=dict)


Reducer = Callable[[DerivedState, dict], None]
_REDUCERS: dict[str, Reducer] = {}


def reducer(event_type: str) -> Callable[[Reducer], Reducer]:
    def register(fn: Reducer) -> Reducer:
        _REDUCERS[event_type] = fn
        return fn
    return register


def apply_event(state: DerivedState, event: Event) -> None:
    """Fold a single event into ``state`` (no-op for events without a reducer)."""
    fn = _REDUCERS.get(event.type)
    if fn is not None:
        fn(state, event.payload_json or {})


def reducer_event_types() -> frozenset[str]:
    """Every event type that moves derived state.

    Anything replaying history to reconstruct a portfolio — ``rebuild_state``,
    the metrics equity curve — should select on this rather than hard-coding a
    list, so adding a reducer cannot silently leave a replay behind.
    """
    return frozenset(_REDUCERS)


@reducer(EVENT_ALLOCATION_SET)
def _apply_allocation(state: DerivedState, payload: dict) -> None:
    pod_id = int(payload["pod_id"])
    delta = float(payload["delta"])
    state.cash[pod_id] = state.cash.get(pod_id, 0.0) + delta


@reducer(EVENT_ORDER_FILLED)
def _apply_order_filled(state: DerivedState, payload: dict) -> None:
    pod_id = int(payload["pod_id"])
    ticker = str(payload["ticker"])
    side = str(payload["side"])
    qty = float(payload["qty"])
    price = float(payload["fill_price"])
    fee = float(payload.get("fee", 0.0))
    key = (pod_id, ticker)
    pos = state.positions.get(key, {"qty": 0.0, "avg_cost": 0.0})

    if side == "buy":
        state.cash[pod_id] = state.cash.get(pod_id, 0.0) - (qty * price + fee)
        new_qty = pos["qty"] + qty
        # Weighted-average cost basis.
        pos["avg_cost"] = (
            (pos["qty"] * pos["avg_cost"] + qty * price) / new_qty
            if new_qty > 0
            else 0.0
        )
        pos["qty"] = new_qty
        state.positions[key] = pos
    elif side == "sell":
        if key not in state.positions or qty > pos["qty"] + QTY_EPSILON:
            # The OMS never fills such a sell (nor any sell of a ticker the pod
            # does not hold), so a history holding one is corrupt or replayed
            # out of order: say so, never erase it (ADR-025).
            raise ValueError(
                f"sell of {qty:g} {ticker} beyond pod {pod_id}'s position "
                f"of {pos['qty']:g}"
            )
        state.cash[pod_id] = state.cash.get(pod_id, 0.0) + (qty * price - fee)
        pos["qty"] -= qty
        if pos["qty"] <= QTY_EPSILON:
            state.positions.pop(key, None)
        else:
            state.positions[key] = pos
    else:  # pragma: no cover - guarded by enum at write time
        raise ValueError(f"unknown order side: {side!r}")
