"""Test doubles for the two services the app injects everywhere: time and prices.

Both exist because Phase 2's metrics are *time series* — a Sharpe ratio needs
days, and the live clock only ever offers one. Rather than sleep or wait, tests
install a clock they can move and a price feed with a real history behind it.

These are deliberately here and not in ``app/``: :class:`HistoricalProvider` is
what the ``MarketDataProvider`` interface exists for, and proving the app works
against a second implementation of it is part of what the interface buys us.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from app.marketdata.base import (
    Bar,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    normalise_ticker,
)


class FrozenClock:
    """A clock that only moves when a test moves it.

    Same shape as :class:`app.clock.LiveClock`; installed with
    ``app.clock.set_clock``, which is the seam Phase 3's backtest clock will use
    for real.
    """

    mode = "frozen"

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = moment

    def advance(self, **delta: float) -> datetime:
        """Move forward, e.g. ``clock.advance(days=1)``."""
        self._now = self._now + timedelta(**delta)
        return self._now


class HistoricalProvider(MarketDataProvider):
    """A price feed with an actual past: ``{ticker: {date: close}}``.

    Each entry is one daily bar, open at 00:00 UTC of its date and ended at the
    next midnight — the same law the real providers obey (ADR-028). ``get_price``
    answers with the close of the last day that had *ended* by ``as_of``, stamped
    at its end: at noon on day D that is D−1's close, never D's, so a test cannot
    prove something using a close nobody could have known yet.
    """

    name = "historical-test"

    def __init__(self, series: dict[str, dict[date, float]]) -> None:
        self._series = {
            normalise_ticker(ticker): dict(sorted(days.items()))
            for ticker, days in series.items()
        }

    def set_price(self, ticker: str, on: date, price: float) -> None:
        symbol = normalise_ticker(ticker)
        days = self._series.setdefault(symbol, {})
        days[on] = price
        self._series[symbol] = dict(sorted(days.items()))

    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        days = self._series.get(symbol) or {}
        ended = [d for d in days if _day_end(d) <= as_of]
        if not ended:
            raise UnknownTickerError(f"no completed test day for {symbol!r} at {as_of}")
        last = max(ended)
        return Quote(ticker=symbol, price=days[last], as_of=_day_end(last), source=self.name)

    def _bars(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        days = self._series.get(symbol)
        if not days:
            raise UnknownTickerError(f"no test history for {symbol!r}")
        # Every day in the window; the base drops the ones not ended by as_of.
        return [
            Bar(
                ts=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=0.0,
            )
            for day, close in days.items()
            if start <= day < end
        ]


def _day_end(day: date) -> datetime:
    """When a test day's bar ends: the next midnight, UTC."""
    return datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


def straight_line(
    start: date, closes: list[float], *, step_days: int = 1
) -> dict[date, float]:
    """``[100, 101, 99]`` from a start date → a dated series, for readable tests."""
    return {start + timedelta(days=i * step_days): price for i, price in enumerate(closes)}


def world_key(n: int) -> bytes:
    """A 32-byte synthetic-world key named by ``n``, for reproducible tests.

    Public by construction — anyone who reads this file can derive it — so it is
    for test worlds only; a real world's key is ``secrets.token_bytes(32)``
    kept out of the repo (red-team 0010).
    """
    return hashlib.sha256(f"test-world-{n}".encode()).digest()
