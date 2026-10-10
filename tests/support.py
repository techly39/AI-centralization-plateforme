"""Test doubles for the two services the app injects everywhere: time and prices.

Both exist because Phase 2's metrics are *time series* — a Sharpe ratio needs
days, and the live clock only ever offers one. Rather than sleep or wait, tests
install a clock they can move and a price feed with a real history behind it.

These are deliberately here and not in ``app/``: :class:`HistoricalProvider` is
what the ``MarketDataProvider`` interface exists for, and proving the app works
against a second implementation of it is part of what the interface buys us.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.marketdata.base import (
    Bar,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    normalise_ticker,
    validate_window,
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

    ``get_price`` answers with the close of the most recent day at or before
    ``as_of`` — including the look-ahead guarantee the interface requires, so a
    test cannot accidentally prove something using tomorrow's price.
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

    def _close_at(self, symbol: str, on: date) -> float | None:
        days = self._series.get(symbol)
        if not days:
            return None
        candidates = [d for d in days if d <= on]
        return days[max(candidates)] if candidates else None

    def get_price(self, ticker: str, *, as_of: datetime) -> Quote:
        symbol = normalise_ticker(ticker)
        price = self._close_at(symbol, as_of.date())
        if price is None:
            raise UnknownTickerError(f"no test history for {symbol!r} at {as_of.date()}")
        return Quote(ticker=symbol, price=price, as_of=as_of, source=self.name)

    def get_ohlcv(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        symbol = normalise_ticker(ticker)
        validate_window(start, end, interval, as_of)
        days = self._series.get(symbol)
        if not days:
            raise UnknownTickerError(f"no test history for {symbol!r}")

        bars = [
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
        return [bar for bar in bars if bar.ts <= as_of]


def straight_line(
    start: date, closes: list[float], *, step_days: int = 1
) -> dict[date, float]:
    """``[100, 101, 99]`` from a start date → a dated series, for readable tests."""
    return {start + timedelta(days=i * step_days): price for i, price in enumerate(closes)}
