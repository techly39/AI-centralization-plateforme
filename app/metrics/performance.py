"""The performance statistics, as pure functions (TRD §7 "Metrics").

Nothing here touches the database, the clock, or the market. Give it a list of
daily equity observations and it gives you the numbers management ranks pods by.
That isolation is the point: these are the formulas someone will argue about, and
an argument is much easier to settle against a function you can call in a REPL
than against a query buried in an endpoint.

**Capital flows are not performance.** A pod handed another million did not earn
anything, so returns are computed *time-weighted*: each day's return measures
only what the market did to the money already there, and management adding or
withdrawing capital is subtracted out before the division. Without that, the
leaderboard would rank pods by how much cash they were given.

Convention: flows are treated as arriving at the **end** of the day, which is
what the allocation endpoint does in practice — the cash lands and only starts
working the following session.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

#: Trading days in a year — the standard convention for annualising a daily
#: Sharpe ratio. Configurable in ``config.yaml``; this is the default.
TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """What one pod was worth at the close of one day."""

    on: date
    #: Cash plus the market value of every position held, in USD.
    equity: float
    #: External capital added (positive) or withdrawn (negative) that day.
    #: Not earnings — subtracted out before the day's return is computed.
    net_flow: float = 0.0


def daily_returns(curve: list[EquityPoint]) -> list[float]:
    """Time-weighted daily returns, one per day after the first.

    Days that follow a zero or negative equity are skipped rather than made up:
    a pod with no capital has no return, and dividing by it would invent one.
    """
    returns: list[float] = []
    for previous, current in zip(curve, curve[1:]):
        if previous.equity <= 0:
            continue
        returns.append((current.equity - current.net_flow) / previous.equity - 1.0)
    return returns


def compound(returns: list[float]) -> float:
    """Total time-weighted return over the whole series, e.g. ``0.12`` for +12%."""
    growth = 1.0
    for r in returns:
        growth *= 1.0 + r
    return growth - 1.0


def sharpe_daily(
    returns: list[float], *, risk_free_daily: float = 0.0
) -> float | None:
    """Sharpe ratio on the daily series: mean excess return / its volatility.

    ``None`` when it cannot honestly be computed — fewer than two observations,
    or a completely flat series (zero volatility, where the ratio is undefined
    rather than infinite). A null is information; a fabricated number is not.
    """
    if len(returns) < 2:
        return None
    excess = [r - risk_free_daily for r in returns]
    volatility = statistics.stdev(excess)  # sample stdev (n-1)
    if volatility == 0 or not math.isfinite(volatility):
        return None
    return statistics.fmean(excess) / volatility


def annualise(daily: float | None, *, trading_days: int = TRADING_DAYS_PER_YEAR) -> float | None:
    """Scale a daily Sharpe to an annual one (×√trading days)."""
    if daily is None:
        return None
    return daily * math.sqrt(trading_days)


def max_drawdown(returns: list[float]) -> float | None:
    """Deepest peak-to-trough fall of the compounded return index.

    Returned as a **negative** fraction (``-0.23`` is a 23% drawdown), or ``0.0``
    for a series that never fell. Computed on the compounded *returns* rather
    than on raw equity so that a capital withdrawal is not reported as a loss.
    """
    if not returns:
        return None
    index = 1.0
    peak = 1.0
    worst = 0.0
    for r in returns:
        index *= 1.0 + r
        peak = max(peak, index)
        if peak > 0:
            worst = min(worst, index / peak - 1.0)
    return worst


def hit_rate(*, wins: int, closed: int) -> float | None:
    """Share of closed trades that made money; ``None`` before any trade closed.

    "Closed" means a sell that booked realised P&L. An open position is not a
    result yet, so counting it either way would be a guess.
    """
    if closed <= 0:
        return None
    return wins / closed
