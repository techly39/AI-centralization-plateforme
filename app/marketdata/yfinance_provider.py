"""yfinance-backed :class:`MarketDataProvider` (TRD §3).

Delayed live quotes and historical OHLCV. This is the only module in the app
allowed to import ``yfinance``; everything else depends on the interface in
:mod:`app.marketdata.base`.

Caching: a quote is reused while the *clock* has moved less than
``marketdata.cache_ttl_seconds`` since it was fetched. Keying the cache on the
injected clock rather than wall time keeps it correct in backtest mode too — a
clock advance of a day invalidates every entry, so a simulation can never be
served a stale live price.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.marketdata.base import (
    Bar,
    MarketDataError,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    normalise_ticker,
    validate_window,
)


@dataclass(frozen=True, slots=True)
class _CachedQuote:
    quote: Quote
    fetched_for: datetime  # the ``as_of`` the fetch was made against


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

    def get_price(self, ticker: str, *, as_of: datetime) -> Quote:
        symbol = normalise_ticker(ticker)

        cached = self._cache_get(symbol, as_of)
        if cached is not None:
            return cached

        quote = self._fetch_price(symbol, as_of)
        with self._lock:
            self._cache[symbol] = _CachedQuote(quote=quote, fetched_for=as_of)
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

        row = frame.iloc[-1]
        return Quote(
            ticker=symbol,
            price=float(row["Close"]),
            as_of=_to_utc(frame.index[-1]),
            source=self.name,
        )

    # --- history ------------------------------------------------------------

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
            # Empty can mean "bad symbol" or "no trading days in range"; the
            # caller cares about the difference, so probe once.
            raise UnknownTickerError(
                f"no OHLCV data for {symbol!r} between "
                f"{start.isoformat()} and {end.isoformat()}"
            )

        bars: list[Bar] = []
        for index, row in frame.iterrows():
            ts = _to_utc(index)
            if ts > as_of:
                continue  # look-ahead guard: never emit a bar from the future
            bars.append(
                Bar(
                    ts=ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                )
            )
        return bars
