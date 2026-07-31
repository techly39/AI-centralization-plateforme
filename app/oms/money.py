"""The fee and cash arithmetic, in one place (TRD §8.2).

Small module on purpose: if the fee model ever changes, this is the only file
that changes, and the tests in ``tests/test_oms_fees.py`` pin the behaviour.

Conventions, decided once and applied everywhere:

* The fee is a fraction of notional (``qty × price``), configurable, default
  0.1%. It is charged on **both** sides — you pay to get in and to get out.
* Money is rounded to cents at the moment it is *recorded* (fees, realised P&L),
  not while it is being accumulated. Rounding a stored number keeps reports
  sane; rounding mid-calculation is how balances drift.
* Fees are charged to cash but are **not** capitalised into a position's average
  cost. So ``avg_cost`` is the clean average execution price, and realised P&L
  is measured against it net of the exit fee. (This matches the reducer the
  ledger has used since Phase 0 — changing it would rewrite history.)
"""

from __future__ import annotations

#: Decimal places money is stored with. Cents.
MONEY_PRECISION = 2
#: Quantities below this are treated as zero (float dust from partial sells).
QTY_EPSILON = 1e-9


def round_money(amount: float) -> float:
    """Round to cents. Use when *recording* an amount, not mid-calculation."""
    return round(amount, MONEY_PRECISION)


def notional(qty: float, price: float) -> float:
    """Gross value of a trade, before fees."""
    return qty * price


def fee_for(qty: float, price: float, fee_rate: float) -> float:
    """Simulated commission on a trade of ``qty`` at ``price``."""
    return round_money(notional(qty, price) * fee_rate)


def buy_cost(qty: float, price: float, fee_rate: float) -> tuple[float, float]:
    """Cash a buy consumes: ``(total, fee)`` where total includes the fee."""
    fee = fee_for(qty, price, fee_rate)
    return notional(qty, price) + fee, fee


def sell_proceeds(qty: float, price: float, fee_rate: float) -> tuple[float, float]:
    """Cash a sell produces: ``(net_proceeds, fee)`` — proceeds are after the fee."""
    fee = fee_for(qty, price, fee_rate)
    return notional(qty, price) - fee, fee


def realized_pnl(qty: float, price: float, avg_cost: float, fee: float) -> float:
    """Profit booked when closing ``qty`` shares carried at ``avg_cost``.

    Net of the exit fee; the entry fee was already expensed when it was paid.
    """
    return round_money(qty * (price - avg_cost) - fee)
