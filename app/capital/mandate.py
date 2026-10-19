"""A seeded pod's mandate: the orders that bring its book to what its rule holds today.

A reader, not an actor: it places nothing. The pod's PM (a scripted mind in the demo, a real one
later) sends the orders through ``POST /orders`` like any other, so the order system checks every
one (the risk ladder's limits included: the planner does not know the pod's stage, physics does).

The rule is the pitch the machine seeded, run by the same law as its backtest
(:func:`app.strategy.rule.holding`), its rebalances counted from the day before the seed (the last
close the pod could first trade at). Sizing: each name's target is ``weight × equity`` at the last
close, less a buffer for the fee; a name is traded only when it is more than ``tolerance`` of the
equity away from its target (no churn on drift). Sells first; buys are scaled to the cash the sells
leave.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capital.service import book
from app.config import get_settings
from app.db.models import Position
from app.ledger.events import ledger_now
from app.marketdata import MarketDataProvider
from app.oms.service import get_cash
from app.strategy.rule import IMPACT_WINDOW, StrategyRule, holding

TOLERANCE = 0.02


class NoMandate(LookupError):
    """The machine never seeded this pod."""


def mandate_orders(session: Session, *, pod_id: int, provider: MarketDataProvider,
                   tolerance: float = TOLERANCE) -> dict[str, Any]:
    entry = book(session)["pods"].get(pod_id)
    if entry is None:
        raise NoMandate(f"pod {pod_id} has no seeded rule")
    rule = StrategyRule.model_validate(entry["rule"])
    now = ledger_now(session)
    start = date.fromisoformat(entry["seeded_on"]) - timedelta(days=1)
    warmup = timedelta(days=int(1.6 * max(rule.lookback, IMPACT_WINDOW)) + 10)
    bars = {t: provider.get_ohlcv(t, start=start - warmup, end=now.date() + timedelta(days=1),
                                  interval="1d", as_of=now) for t in rule.universe}
    held = holding(rule, bars, start=start)
    price = {t: bars[t][-1].close for t in rule.universe}
    positions = {p.ticker: p.qty for p in session.scalars(
        select(Position).where(Position.pod_id == pod_id))}
    cash = get_cash(session, pod_id)
    for ticker in positions:
        if ticker not in price:
            price[ticker] = provider.get_price(ticker, as_of=now).price
    equity = cash + sum(qty * price[t] for t, qty in positions.items())
    buffer = 1.0 - 3 * get_settings().oms.fee_rate
    target = {t: max(0.0, w) * equity * buffer / price[t] for t, w in held.weights.items()}

    sells, buys = [], []
    for ticker in sorted(set(target) | set(positions)):
        have, want = positions.get(ticker, 0.0), target.get(ticker, 0.0)
        gap = (want - have) * price[ticker]
        if want == 0.0 and have > 0:
            sells.append({"ticker": ticker, "side": "sell", "qty": have})
        elif abs(gap) > tolerance * equity:
            (buys if gap > 0 else sells).append(
                {"ticker": ticker, "side": "buy" if gap > 0 else "sell", "qty": abs(want - have)})
    fee = get_settings().oms.fee_rate
    freed = cash + sum(o["qty"] * price[o["ticker"]] * (1 - fee) for o in sells)
    need = sum(o["qty"] * price[o["ticker"]] * (1 + fee) for o in buys)
    if need > freed > 0:
        for o in buys:
            o["qty"] *= freed / need * (1 - fee)
    elif freed <= 0:
        buys = []
    return {"pod_id": pod_id, "day": held.day.isoformat(),
            "rebalanced_on": held.rebalanced_on.isoformat(), "weights": held.weights,
            "equity": equity, "orders": sells + buys}
