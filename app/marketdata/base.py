"""The ``MarketDataProvider`` interface and its value objects (TRD §3, §7).

Everything in the app that needs a price goes through this interface, never
through yfinance directly. That is what makes the data source swappable (a
recorded-fixture provider for backtests, a paid feed later) and what makes the
OMS testable without touching the network.

Two rules every implementation must honour:

1. **Time is injected.** Callers pass ``as_of`` (always ``clock.now()``); the
   provider must never read the system clock to decide what "now" is.
2. **No look-ahead.** A provider must never return data timestamped after
   ``as_of``. In live mode that is trivially true; in backtest mode (Phase 3) it
   is the guarantee the whole simulation rests on, so the check lives here in
   the shared base rather than in each implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

# Intervals we accept on /ohlcv. Kept deliberately small: these are the ones
# yfinance serves reliably and the ones a daily-horizon fund actually needs.
Interval = Literal["1d", "1wk", "1mo", "1h"]
VALID_INTERVALS: frozenset[str] = frozenset({"1d", "1wk", "1mo", "1h"})


# --- Errors -----------------------------------------------------------------

class MarketDataError(Exception):
    """Base class for every market-data failure (mapped to HTTP 502)."""


class UnknownTickerError(MarketDataError):
    """The symbol does not exist or has no data at all (mapped to HTTP 404)."""


class LookAheadError(MarketDataError):
    """Data beyond the clock's "now" was requested (mapped to HTTP 400).

    This is a programming/simulation error, not a transport failure: something
    asked to see the future. Failing loudly is the point.
    """


class InvalidRequestError(MarketDataError):
    """Malformed request (bad interval, end before start) — mapped to HTTP 400."""


# --- Value objects ----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Quote:
    """A single price observation."""

    ticker: str
    price: float
    #: When the price itself is from — for a delayed live feed this is the
    #: provider's stamp, not the moment we asked.
    as_of: datetime
    currency: str = "USD"
    #: Free-form provider tag ("yfinance", "fake") for audit trails.
    source: str = "unknown"


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV candle."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


# --- Interface --------------------------------------------------------------

class MarketDataProvider(ABC):
    """Abstract price source. Implementations must be side-effect free."""

    #: Short name recorded on quotes and in logs.
    name: str = "abstract"

    @abstractmethod
    def get_price(self, ticker: str, *, as_of: datetime) -> Quote:
        """Latest price for ``ticker`` at or before ``as_of``.

        Raises:
            UnknownTickerError: symbol unknown / no data.
            MarketDataError: upstream failure.
        """

    @abstractmethod
    def get_ohlcv(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        """Candles in ``[start, end)`` — never any bar stamped after ``as_of``."""


def normalise_ticker(ticker: str) -> str:
    """Canonical symbol form used everywhere (storage, cache keys, positions).

    One normalisation point avoids the classic bug where ``aapl`` and ``AAPL``
    become two different positions in the same pod.
    """
    cleaned = (ticker or "").strip().upper()
    if not cleaned:
        raise InvalidRequestError("ticker must not be empty")
    if len(cleaned) > 16:
        raise InvalidRequestError(f"ticker too long: {cleaned!r}")
    return cleaned


def validate_window(start: date, end: date, interval: str, as_of: datetime) -> None:
    """Shared guard for OHLCV requests: interval, ordering, and look-ahead."""
    if interval not in VALID_INTERVALS:
        raise InvalidRequestError(
            f"interval must be one of {sorted(VALID_INTERVALS)}, got {interval!r}"
        )
    if end < start:
        raise InvalidRequestError("end must not be before start")
    # ``end`` is exclusive, so requesting up to and including "today at as_of"
    # is legal; anything strictly beyond the simulated now is not.
    if start > as_of.date():
        raise LookAheadError(
            f"start {start.isoformat()} is after the clock's now "
            f"({as_of.date().isoformat()}) — no look-ahead"
        )
