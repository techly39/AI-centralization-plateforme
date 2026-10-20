"""The Order Management System (TRD §8).

This is the deterministic core: no LLM anywhere near it, no wall-clock reads, no
filesystem. An order arrives already authenticated from the API layer, and this
module decides what happens to it.

The flow, in the TRD's own order:

1. Permission and pod scope. The API layer has already checked the role against
   the permission matrix; the OMS re-checks it against **the same matrix** (so
   the two can never disagree) and then answers the question the matrix cannot:
   is this the agent's **own** pod? See :mod:`app.oms.errors` for why both.
2. Price, from the injected :class:`~app.marketdata.MarketDataProvider`, stamped
   with the injected clock.
3. Cash check including the simulated fee. Not enough → the order is stored as
   ``rejected`` and the PM is messaged with the actual numbers.
4. ``market`` fills immediately; ``limit`` is parked as ``pending`` for the
   monitor (:mod:`app.oms.monitor`).
5. Sells verify the position, may be partial, and book realised P&L.

**Transactions.** Unlike the registry service, these functions commit for
themselves. They have to: correctness depends on holding :data:`OMS_LOCK`
across the read-check-write-commit sequence, and a lock released before the
commit would let two concurrent orders both see the same cash and both spend it.
The app is single-process by design (TRD §12 rules out containers/orchestration),
so a process-wide lock is the right size of solution — if this ever becomes
multi-process, replace it with ``BEGIN IMMEDIATE`` transactions or row locks, and
nothing else needs to change.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from datetime import datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bus.notify import notify_agent
from app.clock import get_clock
from app.config import get_settings
from app.db.models import (
    Agent,
    AgentRole,
    CashBalance,
    Order,
    OrderSide,
    OrderStatus,
    Pod,
    Position,
    PriceType,
)
from app.ledger.apply import apply_event_to_db
from app.ledger.events import (
    EVENT_ORDER_CANCELLED,
    EVENT_ORDER_FILLED,
    EVENT_ORDER_PLACED,
    EVENT_ORDER_REJECTED,
    append_event,
    ledger_now,
)
from app.marketdata import (
    MarketDataError,
    MarketDataProvider,
    get_provider,
    normalise_ticker,
)
from app.oms.errors import (
    InsufficientCashError,
    InsufficientPositionError,
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderRejected,
    OrderValidationError,
    PodLimitError,
    PodScopeError,
    PriceUnavailableError,
    RoleNotPermittedError,
)
from app.oms.money import (
    QTY_EPSILON,
    buy_cost,
    realized_pnl,
    round_money,
    sell_proceeds,
)
from app.registry.permissions import Action, has_permission

#: Serialises every read-check-write on pod cash and positions. See module docstring.
OMS_LOCK = threading.RLock()


# --- Derived-state readers --------------------------------------------------

def get_cash(session: Session, pod_id: int) -> float:
    """Current cash for a pod (0.0 if it has never been funded)."""
    row = session.get(CashBalance, pod_id)
    return row.balance if row is not None else 0.0


def get_position(session: Session, pod_id: int, ticker: str) -> Position | None:
    return session.get(Position, (pod_id, ticker))


# --- Validation -------------------------------------------------------------

def _coerce_side(side: OrderSide | str) -> OrderSide:
    try:
        return side if isinstance(side, OrderSide) else OrderSide(str(side).lower())
    except ValueError:
        raise OrderValidationError(f"side must be 'buy' or 'sell', got {side!r}")


def _coerce_price_type(price_type: PriceType | str) -> PriceType:
    try:
        return (
            price_type
            if isinstance(price_type, PriceType)
            else PriceType(str(price_type).lower())
        )
    except ValueError:
        raise OrderValidationError(
            f"price_type must be 'market' or 'limit', got {price_type!r}"
        )


def _validate_request(
    *,
    actor: Agent,
    ticker: str,
    qty: float,
    price_type: PriceType,
    limit_price: float | None,
) -> tuple[int, str]:
    """Check everything that can be checked without touching the market.

    Returns the resolved ``(pod_id, ticker)``.
    """
    # Two different questions, deliberately kept apart:
    #
    #   1. May this role ever place an order? The API already asked this via
    #      Depends(require(Action.PLACE_ORDER)). Asking again means the OMS is
    #      safe when called from anywhere else — a script, a Phase 3 backtest
    #      driver, a test. It consults `has_permission`, the same matrix the
    #      API used, so the two layers can never drift apart: add a role to
    #      _MATRIX and both start allowing it, with no change here.
    #
    #   2. Is it *this agent's* pod? The matrix is a role → action table and
    #      cannot express "own pod" (TRD §6), so only the OMS can answer it.
    if not has_permission(actor.role, Action.PLACE_ORDER):
        raise RoleNotPermittedError(
            f"role {actor.role.value!r} may not place orders"
        )
    if actor.pod_id is None:
        raise PodScopeError(
            f"agent {actor.name!r} belongs to no pod, so it has nothing to trade with"
        )

    symbol = normalise_ticker(ticker)

    if qty is None or not math.isfinite(qty) or qty <= 0:
        raise OrderValidationError(f"qty must be a positive number, got {qty!r}")

    if price_type is PriceType.limit:
        if limit_price is None:
            raise OrderValidationError("limit orders require a limit_price")
        if limit_price <= 0:
            raise OrderValidationError(
                f"limit_price must be positive, got {limit_price!r}"
            )
    elif limit_price is not None:
        raise OrderValidationError("market orders must not carry a limit_price")

    return actor.pod_id, symbol


# --- Placing ----------------------------------------------------------------

def place_order(
    session: Session,
    *,
    actor: Agent,
    ticker: str,
    side: OrderSide | str,
    qty: float,
    price_type: PriceType | str,
    limit_price: float | None = None,
    justification: str | None = None,
    provider: MarketDataProvider | None = None,
) -> Order:
    """Submit one order and take it as far as it can go right now.

    Returns the stored order. Check ``order.status``: a ``rejected`` order is a
    normal outcome (no cash, no shares), not an error — the reason is in
    ``order.status_reason`` and a message is waiting for the PM.

    Raises:
        OrderValidationError: malformed request; nothing was stored.
        RoleNotPermittedError / PodScopeError: not allowed; nothing was stored.
        PriceUnavailableError: the market could not be read; nothing was stored.
    """
    side = _coerce_side(side)
    price_type = _coerce_price_type(price_type)
    pod_id, symbol = _validate_request(
        actor=actor,
        ticker=ticker,
        qty=qty,
        price_type=price_type,
        limit_price=limit_price,
    )

    provider = provider or get_provider()
    # The ledger's now, not the raw clock: the order is stamped with it (ADR-025)
    # so it is priced at it too, even when the clock is behind the ledger (ADR-029).
    now = ledger_now(session)

    # The reference price: what the order is worth *right now*. A market order
    # fills at it; a limit order is only cash-checked against its own limit
    # (which _validate_request has already guaranteed is present and positive).
    reference_price = (
        _fetch_price(provider, symbol, now)
        if price_type is PriceType.market
        else float(limit_price)  # type: ignore[arg-type]
    )

    with OMS_LOCK:
        stamp_now = ledger_now(session)
        if get_clock().mode != "live" and stamp_now != now:
            # A backtest clock advanced while the price was fetched (red-team
            # 0007): the order will be stamped at the new now, so it is priced
            # there too. Only this rare path fetches under the lock.
            now = stamp_now
            if price_type is PriceType.market:
                reference_price = _fetch_price(provider, symbol, now)
        try:
            # Under the lock: the capital machine changes a pod's stage under it too.
            assert_pod_may_trade(session, pod_id=pod_id, side=side)
            order = Order(
                pod_id=pod_id,
                created_by=actor.id,
                ticker=symbol,
                side=side,
                qty=float(qty),
                price_type=price_type,
                limit_price=limit_price,
                status=OrderStatus.pending,
                justification=justification,
                created_at=now,
            )
            session.add(order)
            session.flush()  # populates order.id

            placed = append_event(
                session,
                type=EVENT_ORDER_PLACED,
                actor_agent_id=actor.id,
                payload={
                    "order_id": order.id,
                    "pod_id": pod_id,
                    "ticker": symbol,
                    "side": side.value,
                    "qty": float(qty),
                    "price_type": price_type.value,
                    "limit_price": limit_price,
                    "reference_price": reference_price,
                    "justification": justification,
                },
            )
            # Stamped like its event: the clock may be behind the ledger (ADR-025).
            order.created_at = placed.ts

            try:
                # Affordability is checked for both order types at submission
                # (TRD §8.2), against the reference price. Limit orders are
                # re-checked at fill time, because cash moves in between.
                assert_affordable(
                    session,
                    pod_id=pod_id,
                    ticker=symbol,
                    side=side,
                    qty=float(qty),
                    price=reference_price,
                )
            except OrderRejected as rejection:
                record_rejection(session, order, rejection, actor_agent_id=actor.id)
                session.commit()
                return order

            if price_type is PriceType.market:
                execute_fill(
                    session,
                    order,
                    price=reference_price,
                    actor_agent_id=actor.id,
                )
            else:
                logger.bind(order_id=order.id, pod_id=pod_id).info(
                    "limit order queued: {} {} x{} @ {}",
                    side.value,
                    symbol,
                    qty,
                    limit_price,
                )

            session.commit()
            return order
        except Exception:
            session.rollback()
            raise


def _fetch_price(
    provider: MarketDataProvider, symbol: str, now: datetime
) -> float:
    try:
        return provider.get_price(symbol, as_of=now).price
    except MarketDataError as exc:
        raise PriceUnavailableError(
            f"no price available for {symbol}: {exc}",
            detail={"ticker": symbol},
        ) from exc


# --- The risk ladder's limits (app/capital/) ----------------------------------

def assert_pod_may_trade(session: Session, *, pod_id: int, side: OrderSide) -> None:
    """Raise :class:`PodLimitError` if the ladder forbids this order: a closed pod trades
    nothing, a reduce-only pod only sells. Read fresh from the database, never a cached row."""
    stage = session.execute(select(Pod.status).where(Pod.id == pod_id)).scalar()
    if stage == "closed":
        raise PodLimitError(
            f"pod {pod_id} is closed by the risk ladder: it may not trade",
            detail={"pod_id": pod_id, "stage": stage})
    if stage == "reduce_only" and side is OrderSide.buy:
        raise PodLimitError(
            f"pod {pod_id} is reduce-only (the risk ladder): it may sell, not buy",
            detail={"pod_id": pod_id, "stage": stage})


def force_sell(
    session: Session,
    *,
    pod_id: int,
    ticker: str,
    qty: float,
    actor: Agent,
    reason: str,
    provider: MarketDataProvider,
) -> Order:
    """Physics sells ``qty`` of a pod's position at the market (the capital machine: a recall of
    capital, a cut, a closed pod). Placed and filled like any market order, as ``actor`` (the
    system identity), on no agent's behalf. The caller holds :data:`OMS_LOCK` and commits."""
    if actor.role is not AgentRole.system:
        raise RoleNotPermittedError("only physics' own identity sells a pod's position by force")
    now = ledger_now(session)
    price = _fetch_price(provider, ticker, now)
    order = Order(pod_id=pod_id, created_by=actor.id, ticker=ticker, side=OrderSide.sell,
                  qty=float(qty), price_type=PriceType.market, limit_price=None,
                  status=OrderStatus.pending, justification=reason, created_at=now)
    session.add(order)
    session.flush()
    placed = append_event(session, type=EVENT_ORDER_PLACED, actor_agent_id=actor.id, payload={
        "order_id": order.id, "pod_id": pod_id, "ticker": ticker, "side": "sell",
        "qty": float(qty), "price_type": "market", "limit_price": None,
        "reference_price": price, "justification": reason})
    order.created_at = placed.ts
    assert_affordable(session, pod_id=pod_id, ticker=ticker, side=OrderSide.sell,
                      qty=float(qty), price=price)
    execute_fill(session, order, price=price, actor_agent_id=actor.id)
    return order


# --- Affordability ----------------------------------------------------------

def assert_affordable(
    session: Session,
    *,
    pod_id: int,
    ticker: str,
    side: OrderSide,
    qty: float,
    price: float,
) -> None:
    """Raise an :class:`OrderRejected` if the pod cannot support this trade."""
    settings = get_settings()

    if side is OrderSide.buy:
        total, fee = buy_cost(qty, price, settings.oms.fee_rate)
        available = get_cash(session, pod_id)
        if total > available:
            raise InsufficientCashError(
                f"needs ${total:,.2f} (${qty * price:,.2f} + ${fee:,.2f} fee) "
                f"but pod {pod_id} holds ${available:,.2f}",
                detail={
                    "required": round_money(total),
                    "notional": round_money(qty * price),
                    "fee": fee,
                    "available": round_money(available),
                    "shortfall": round_money(total - available),
                },
            )
        return

    position = get_position(session, pod_id, ticker)
    held = position.qty if position is not None else 0.0
    # QTY_EPSILON forgives float dust on a position, never a sell of nothing.
    if position is None or qty > held + QTY_EPSILON:
        raise InsufficientPositionError(
            f"cannot sell {qty:g} {ticker}: pod {pod_id} holds {held:g}",
            detail={"ticker": ticker, "requested": qty, "held": held},
        )


# --- Fills, rejections, cancellations ---------------------------------------

def execute_fill(
    session: Session,
    order: Order,
    *,
    price: float,
    actor_agent_id: int | None,
) -> None:
    """Execute ``order`` at ``price``: emit the event, then move the state.

    The event is written first and the derived tables are updated *from* it, so
    the ledger can never describe a fill the portfolio does not reflect, or the
    other way round.
    """
    settings = get_settings()
    qty = order.qty
    booked_pnl: float | None = None

    if order.side is OrderSide.buy:
        _, fee = buy_cost(qty, price, settings.oms.fee_rate)
    else:
        _, fee = sell_proceeds(qty, price, settings.oms.fee_rate)
        position = get_position(session, order.pod_id, order.ticker)
        avg_cost = position.avg_cost if position is not None else 0.0
        booked_pnl = realized_pnl(qty, price, avg_cost, fee)

    payload = {
        "order_id": order.id,
        "pod_id": order.pod_id,
        "ticker": order.ticker,
        "side": order.side.value,
        "qty": qty,
        "fill_price": price,
        "fee": fee,
        "price_type": order.price_type.value,
    }
    if booked_pnl is not None:
        payload["realized_pnl"] = booked_pnl

    event = append_event(
        session,
        type=EVENT_ORDER_FILLED,
        actor_agent_id=actor_agent_id,
        payload=payload,
    )
    apply_event_to_db(session, event)

    order.status = OrderStatus.filled
    # The ledger's (held) time, not the clock's: the row agents read must
    # agree with the event that is the truth (ADR-025).
    order.filled_at = event.ts
    order.fill_price = price
    order.fee = fee
    order.realized_pnl = booked_pnl
    session.flush()

    logger.bind(
        order_id=order.id,
        pod_id=order.pod_id,
        event_id=event.id,
    ).info(
        "FILLED {} {} x{:g} @ {:.4f} (fee {:.2f}, cash now {:.2f})",
        order.side.value,
        order.ticker,
        qty,
        price,
        fee,
        get_cash(session, order.pod_id),
    )


def record_rejection(
    session: Session,
    order: Order,
    rejection: OrderRejected,
    *,
    actor_agent_id: int | None,
) -> None:
    """Record a rejection and tell the PM why (TRD §8.2)."""
    order.status = OrderStatus.rejected
    order.status_reason = rejection.message
    session.flush()

    append_event(
        session,
        type=EVENT_ORDER_REJECTED,
        actor_agent_id=actor_agent_id,
        payload={
            "order_id": order.id,
            "pod_id": order.pod_id,
            "ticker": order.ticker,
            "reason": rejection.code,
            "message": rejection.message,
            **rejection.detail,
        },
    )

    notify_agent(
        session,
        to_agent_id=order.created_by,
        body=(
            f"Order #{order.id} rejected: {order.side.value} {order.qty:g} "
            f"{order.ticker} — {rejection.message}"
        ),
        payload={
            "kind": "order_rejected",
            "order_id": order.id,
            "pod_id": order.pod_id,
            "ticker": order.ticker,
            "side": order.side.value,
            "qty": order.qty,
            "reason": rejection.code,
            **rejection.detail,
        },
        thread_id=f"order-{order.id}",
    )

    logger.bind(order_id=order.id, pod_id=order.pod_id).warning(
        "REJECTED {} {} x{:g}: {}",
        order.side.value,
        order.ticker,
        order.qty,
        rejection.message,
    )


def cancel_order(session: Session, *, actor: Agent, order_id: int) -> Order:
    """Cancel a pending order. Only its own pod's PM (or management) may.

    Raises:
        OrderNotFoundError, PodScopeError, OrderNotCancellableError.
    """
    with OMS_LOCK:
        try:
            order = session.get(Order, order_id)
            if order is None:
                raise OrderNotFoundError(f"no order with id {order_id}")
            # Same two questions as placement — see _validate_request.
            if not has_permission(actor.role, Action.PLACE_ORDER):
                raise RoleNotPermittedError(
                    f"role {actor.role.value!r} may not cancel orders"
                )
            if actor.role is not AgentRole.system and order.pod_id != actor.pod_id:
                raise PodScopeError(
                    f"order {order_id} belongs to pod {order.pod_id}, "
                    f"not to {actor.name!r}'s pod"
                )
            if order.status is not OrderStatus.pending:
                raise OrderNotCancellableError(
                    f"order {order_id} is {order.status.value}, only pending "
                    "orders can be cancelled"
                )

            order.status = OrderStatus.cancelled
            order.status_reason = f"cancelled by {actor.name}"
            session.flush()
            append_event(
                session,
                type=EVENT_ORDER_CANCELLED,
                actor_agent_id=actor.id,
                payload={
                    "order_id": order.id,
                    "pod_id": order.pod_id,
                    "ticker": order.ticker,
                },
            )
            session.commit()
            return order
        except Exception:
            session.rollback()
            raise


def cancel_pending(session: Session, *, pod_id: int, actor: Agent, reason: str) -> list[Order]:
    """Physics cancels every pending order of ``pod_id`` (its PMs were let go: an order they left
    must not fill after them). No permission check, no commit: the caller is physics and owns the
    transaction (and holds OMS_LOCK)."""
    orders = list(session.scalars(select(Order).where(
        Order.pod_id == pod_id, Order.status == OrderStatus.pending).order_by(Order.id)))
    for order in orders:
        order.status = OrderStatus.cancelled
        order.status_reason = reason
        session.flush()
        append_event(session, type=EVENT_ORDER_CANCELLED, actor_agent_id=actor.id, payload={
            "order_id": order.id, "pod_id": order.pod_id, "ticker": order.ticker})
    return orders


# --- Queries ----------------------------------------------------------------

def list_orders(
    session: Session,
    *,
    pod_id: int | None = None,
    status: OrderStatus | None = None,
    ticker: str | None = None,
    limit: int = 200,
) -> Sequence[Order]:
    """Orders newest first, optionally narrowed by pod / status / ticker."""
    stmt = select(Order)
    if pod_id is not None:
        stmt = stmt.where(Order.pod_id == pod_id)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if ticker is not None:
        stmt = stmt.where(Order.ticker == normalise_ticker(ticker))
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit)
    return session.execute(stmt).scalars().all()


def get_order(session: Session, order_id: int) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise OrderNotFoundError(f"no order with id {order_id}")
    return order
