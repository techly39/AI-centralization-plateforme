"""The pending-order monitor (TRD §8.4).

A limit order sits in the book until the market comes to it. This module is the
thing that looks. It is a plain function, deliberately: the live scheduler calls
it on a timer (:mod:`app.scheduler`), and Phase 3's ``POST /clock/advance`` will
call the exact same function on every simulated step. One code path, so a
backtest fills orders the same way live trading does.

Crossing rules, and they are strict inequalities in the PM's favour:

* **buy limit** fills when the market trades **at or below** the limit;
* **sell limit** fills when the market trades **at or above** it.

The fill happens at the *market* price, not the limit price — if the market gaps
through your limit you get the better price, which is how a real book behaves.

Cash and position are re-validated at fill time (a limit order placed yesterday
must not overdraw a pod that spent its cash this morning). A pending order that
can no longer be afforded is rejected, not silently dropped, and its PM is told.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Order, OrderSide, OrderStatus, PriceType
from app.marketdata import MarketDataError, MarketDataProvider, get_provider
from app.oms.errors import OrderRejected
from app.oms.service import (
    OMS_LOCK,
    assert_affordable,
    execute_fill,
    record_rejection,
)
from app.registry.halt import is_halted


@dataclass
class MonitorResult:
    """What one sweep did — returned so callers can log or assert on it."""

    checked: int = 0
    filled: list[int] = field(default_factory=list)
    rejected: list[int] = field(default_factory=list)
    #: Tickers whose price could not be read; their orders stay pending.
    unpriced: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.filled or self.rejected)


def crosses(order: Order, market_price: float) -> bool:
    """Has the market reached this order's limit?"""
    if order.limit_price is None:  # pragma: no cover - guarded at placement
        return False
    if order.side is OrderSide.buy:
        return market_price <= order.limit_price
    return market_price >= order.limit_price


def pending_limit_orders(
    session: Session, *, pod_id: int | None = None
) -> list[Order]:
    stmt = (
        select(Order)
        .where(
            Order.status == OrderStatus.pending,
            Order.price_type == PriceType.limit,
        )
        .order_by(Order.created_at, Order.id)  # oldest first: price-time priority
    )
    if pod_id is not None:
        stmt = stmt.where(Order.pod_id == pod_id)
    return list(session.execute(stmt).scalars().all())


def check_pending_orders(
    session: Session,
    *,
    provider: MarketDataProvider | None = None,
    pod_id: int | None = None,
) -> MonitorResult:
    """Price every pending limit order once and fill the ones that cross.

    Commits its own transaction (see the transaction note in
    :mod:`app.oms.service`). Safe to call concurrently with ``place_order``.
    While the world is halted it fills nothing and returns an empty result.
    """
    result = MonitorResult()
    if is_halted():
        return result
    provider = provider or get_provider()
    now = get_clock().now()

    with OMS_LOCK:
        try:
            orders = pending_limit_orders(session, pod_id=pod_id)
            result.checked = len(orders)
            if not orders:
                return result

            # One price lookup per distinct ticker per sweep, not one per order:
            # a pod with 20 pending AAPL orders must not make 20 network calls.
            prices: dict[str, float] = {}
            for order in orders:
                if order.ticker in prices or order.ticker in result.unpriced:
                    continue
                try:
                    prices[order.ticker] = provider.get_price(
                        order.ticker, as_of=now
                    ).price
                except MarketDataError as exc:
                    # Leave the order pending; a feed hiccup is not a decision.
                    result.unpriced.append(order.ticker)
                    logger.bind(ticker=order.ticker).warning(
                        "pending-order check skipped, no price: {}", exc
                    )

            for order in orders:
                price = prices.get(order.ticker)
                if price is None or not crosses(order, price):
                    continue

                try:
                    assert_affordable(
                        session,
                        pod_id=order.pod_id,
                        ticker=order.ticker,
                        side=order.side,
                        qty=order.qty,
                        price=price,
                    )
                except OrderRejected as rejection:
                    record_rejection(
                        session, order, rejection, actor_agent_id=order.created_by
                    )
                    result.rejected.append(order.id)
                    continue

                execute_fill(
                    session,
                    order,
                    price=price,
                    at=now,
                    actor_agent_id=order.created_by,
                )
                result.filled.append(order.id)

            session.commit()
        except Exception:
            session.rollback()
            raise

    if result:
        logger.bind(
            filled=result.filled, rejected=result.rejected
        ).info("pending-order sweep: {} checked", result.checked)
    return result
