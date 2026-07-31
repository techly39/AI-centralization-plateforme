"""Concurrent orders must not double-spend the same cash.

``place_order`` reads the pod's balance, decides, writes, and commits. Without
serialisation, two requests arriving together both read the *old* balance and
both decide they can afford the trade — the pod ends up overdrawn and the
portfolio is quietly wrong. ``app.oms.service.OMS_LOCK`` closes that window.

This test is the reason the lock exists, so it should be the first thing to fail
if someone removes it. It is arranged so the correct answer does not depend on
which thread wins: the pod can afford exactly four of the ten orders, whatever
order they arrive in.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.db.models import AgentRole, OrderStatus
from app.oms.service import get_cash, place_order

# 100 shares at $200 = $20,000 notional + $20 fee = $20,020 per order.
# A $100,000 pod affords four of them ($80,080), never five ($100,100).
ORDERS = 10
QTY = 100
COST_EACH = 20_020.0
AFFORDABLE = 4


def test_concurrent_orders_cannot_overdraw_the_pod(
    SessionFactory, make_pod, fund_pod_cash, prices, db
):
    from app.registry.service import register_agent

    make_pod(1)
    fund_pod_cash(1, 100_000.0)

    session = SessionFactory()
    pm, _ = register_agent(session, name="pm-1", role=AgentRole.pm, pod_id=1)
    session.commit()
    pm_id = pm.id
    session.close()

    def submit(index: int) -> str:
        """One order on its own session, as a real request would have."""
        own_session = SessionFactory()
        try:
            actor = own_session.get(type(pm), pm_id)
            order = place_order(
                own_session,
                actor=actor,
                ticker="AAPL",
                side="buy",
                qty=QTY,
                price_type="market",
                justification=f"concurrent order {index}",
                provider=prices,
            )
            return order.status.value
        finally:
            own_session.close()

    with ThreadPoolExecutor(max_workers=ORDERS) as pool:
        outcomes = list(pool.map(submit, range(ORDERS)))

    filled = outcomes.count(OrderStatus.filled.value)
    rejected = outcomes.count(OrderStatus.rejected.value)

    assert filled == AFFORDABLE, f"expected {AFFORDABLE} fills, got {outcomes}"
    assert rejected == ORDERS - AFFORDABLE

    db.expire_all()
    remaining = get_cash(db, 1)
    assert remaining == 100_000.0 - AFFORDABLE * COST_EACH
    assert remaining >= 0, "the pod was overdrawn — the OMS lock is not holding"
