"""yfinance-backed :class:`MarketDataProvider` (TRD §3).

Delayed live quotes and historical OHLCV. This is the only module in the app
allowed to import ``yfinance``; everything else depends on the interface in
:mod:`app.marketdata.base`.

Two ways to answer a price (ADR-028). Yahoo's quote endpoint knows only the
real present, so it answers an ``as_of`` within :data:`LIVE_QUOTE_WINDOW` of
the real now and nothing else; an older ``as_of`` — every backtest — is
answered with the close of the latest daily or hourly bar that had *ended* by
then, stamped at that bar's end. The real now is read (``wall_now``) only to
tell which of the two the feed can honestly give; it is never a stamp.

Caching: a live quote is reused while the *clock* has moved less than
``marketdata.cache_ttl_seconds`` since it was fetched; a past quote only for
the exact ``as_of`` it answered (a one-minute advance can cross a bar's end).
Keying the cache on the injected clock rather than wall time keeps it correct
in backtest mode too.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.clock import wall_now
from app.marketdata.base import (
    LIVE_QUOTE_WINDOW,
    Bar,
    MarketDataError,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    bar_end,
)

#: How far back a past ``as_of`` looks for its last completed daily bar: long
#: enough to span any exchange holiday stretch.
_PAST_QUOTE_LOOKBACK = timedelta(days=14)

#: Intervals a past quote looks at: the finest /ohlcv serves, and the daily
#: (hourly history does not reach as far back). Weekly and monthly bars end
#: no earlier than the daily bar carrying the same close.
_PAST_QUOTE_INTERVALS = ("1d", "1h")


@dataclass(frozen=True, slots=True)
class _CachedQuote:
    quote: Quote
    fetched_for: datetime  # the ``as_of`` the fetch was made against
    #: A live quote is the present for a short while; a past quote is the
    #: answer for its exact ``as_of`` only — a bar may end the next minute.
    live: bool


def _to_utc(value: Any) -> datetime:
    """Coerce a pandas/py timestamp to an aware UTC datetime."""
    dt = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if not isinstance(dt, datetime):
        raise MarketDataError(f"expected a datetime, got {type(value).__name__}")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class YFinanceProvider(MarketDataProvider):
    """Delayed quotes + historical bars from Yahoo Finance."""

    name = "yfinance"

    def __init__(self, *, cache_ttl_seconds: float = 60.0) -> None:
        self._cache_ttl = timedelta(seconds=max(cache_ttl_seconds, 0.0))
        self._cache: dict[str, _CachedQuote] = {}
        self._lock = threading.Lock()

    # --- prices -------------------------------------------------------------

    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        cached = self._cache_get(symbol, as_of)
        if cached is not None:
            return cached

        live = wall_now() - as_of <= LIVE_QUOTE_WINDOW
        if live:
            quote = self._fetch_price(symbol, as_of)
        else:
            quote = self._past_price(symbol, as_of)
        with self._lock:
            self._cache[symbol] = _CachedQuote(quote=quote, fetched_for=as_of, live=live)
        return quote

    def _cache_get(self, symbol: str, as_of: datetime) -> Quote | None:
        if not self._cache_ttl:
            return None
        with self._lock:
            entry = self._cache.get(symbol)
        if entry is None:
            return None
        # Only a *forward* move of the clock within the TTL keeps the quote
        # valid; any backwards jump (mode switch, replay) invalidates it.
        delta = as_of - entry.fetched_for
        if not entry.live:
            # A past quote is reused for its own moment only: a clock advance
            # of one minute can cross a bar's end (red-team 0008).
            return entry.quote if delta == timedelta(0) else None
        if timedelta(0) <= delta <= self._cache_ttl:
            return entry.quote
        return None

    def _fetch_price(self, symbol: str, as_of: datetime) -> Quote:
        import yfinance as yf

        try:
            ticker = yf.Ticker(symbol)
        except Exception as exc:  # pragma: no cover - constructor rarely fails
            raise MarketDataError(f"could not open {symbol}: {exc}") from exc

        # Preferred path: the lightweight quote endpoint.
        try:
            last = ticker.fast_info["lastPrice"]
            if last is not None and float(last) > 0:
                return Quote(
                    ticker=symbol,
                    price=float(last),
                    as_of=as_of,
                    currency=str(ticker.fast_info.get("currency") or "USD"),
                    source=self.name,
                )
        except Exception as exc:
            logger.debug("fast_info miss for {}: {}", symbol, exc)

        # Fallback: last close from a short daily history. Slower but survives
        # the quote endpoint being flaky or the symbol being thinly traded.
        try:
            frame = ticker.history(period="5d", interval="1d", auto_adjust=False)
        except Exception as exc:
            raise MarketDataError(f"price lookup failed for {symbol}: {exc}") from exc

        if frame is None or frame.empty:
            raise UnknownTickerError(f"no market data for {symbol!r}")

        # The last row may be today's bar still trading: its close is the
        # current price, and its 00:00 stamp would claim it is older than it is.
        row = frame.iloc[-1]
        return Quote(
            ticker=symbol,
            price=float(row["Close"]),
            as_of=as_of,
            source=self.name,
        )

    def _past_price(self, symbol: str, as_of: datetime) -> Quote:
        """The close of the latest bar, of any interval /ohlcv serves at
        ``as_of``, that had ended by then.

        Not just the daily bar: after the close, today's hourly bars have ended
        while today's daily bar has not, and a fill must never be at a price
        older than what the same world already shows (red-team 0008).
        """
        latest: tuple[datetime, float] | None = None
        for interval in _PAST_QUOTE_INTERVALS:
            try:
                bars = self.get_ohlcv(
                    symbol,
                    start=(as_of - _PAST_QUOTE_LOOKBACK).date(),
                    end=as_of.date() + timedelta(days=1),
                    interval=interval,
                    as_of=as_of,
                )
            except UnknownTickerError:
                continue  # e.g. no hourly history that far back
            ended = bar_end(bars[-1].ts, interval)
            if latest is None or ended > latest[0]:
                latest = (ended, bars[-1].close)
        if latest is None:
            raise UnknownTickerError(
                f"no completed bar for {symbol!r} in the "
                f"{_PAST_QUOTE_LOOKBACK.days} days before {as_of.isoformat()}"
            )
        return Quote(ticker=symbol, price=latest[1], as_of=latest[0], source=self.name)

    # --- history ------------------------------------------------------------

    def _bars(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        import yfinance as yf

        try:
            frame = yf.Ticker(symbol).history(
                start=start.isoformat(),
                end=end.isoformat(),
                interval=interval,
                auto_adjust=False,
            )
        except Exception as exc:
            raise MarketDataError(f"history lookup failed for {symbol}: {exc}") from exc

        if frame is None or frame.empty:
            # "Bad symbol" and "no trading in range" look the same to the
            # caller on purpose: the base answers both with one error, so the
            # answer cannot depend on data after ``as_of`` (red-team 0008).
            return []

        # No look-ahead filter here: the base drops every bar not ended by
        # ``as_of`` (a bar's stamp is its open, not its close).
        bars: list[Bar] = []
        for index, row in frame.iterrows():
            bars.append(
                Bar(
                    ts=_to_utc(index),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                )
            )
        return bars
