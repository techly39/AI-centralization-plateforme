"""The ``MarketDataProvider`` interface and its value objects (TRD §3, §7).

Everything in the app that needs a price goes through this interface, never
through yfinance directly. That is what makes the data source swappable (a
recorded-fixture provider for backtests, a paid feed later) and what makes the
OMS testable without touching the network.

Two rules every implementation must honour:

1. **Time is injected.** Callers pass ``as_of`` (always ``ledger_now(session)``,
   ADR-029); the
   provider must never read the system clock to decide what "now" is.
2. **No look-ahead** (ADR-028, B-005). Nothing known only after ``as_of`` is
   served: a bar is visible once it has *ended* (:func:`bar_end`), not once it
   has opened — a daily bar stamped 00:00 carries that day's close — and a quote
   stamped after ``as_of`` is refused. In a backtest this is the guarantee the
   whole simulation rests on, so it is enforced here, in the base, and nowhere
   else: :meth:`MarketDataProvider.get_price` and
   :meth:`MarketDataProvider.get_ohlcv` are the only public entries, and a
   subclass may not override them — it implements ``_quote`` / ``_bars``.
"""

from __future__ import annotations

import calendar
import math
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

# Intervals we accept on /ohlcv. Kept deliberately small: these are the ones
# yfinance serves reliably and the ones a daily-horizon fund actually needs.
Interval = Literal["1d", "1wk", "1mo", "1h"]
VALID_INTERVALS: frozenset[str] = frozenset({"1d", "1wk", "1mo", "1h"})

#: How close to the real now an ``as_of`` must be for a live feed's *current*
#: quote to answer it. Further back, a live feed answers from history. A
#: backtest's clock is kept at least this far behind the real now
#: (:mod:`app.run_clock`), so it is always answered from history (ADR-028).
LIVE_QUOTE_WINDOW = timedelta(seconds=60)


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


class FeedDataError(MarketDataError):
    """The feed answered with something physics refuses (mapped to HTTP 502).

    A quote stamped after the ``as_of`` it answers (data from the future), or a
    price that is not a positive finite number. The caller asked nothing wrong;
    the feed failed it — so ``POST /orders`` answers ``price_unavailable`` (502,
    nothing stored) and the sweep leaves an order pending, exactly as for an
    outage.
    """


# --- Value objects ----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Quote:
    """A single price observation."""

    ticker: str
    price: float
    #: The latest moment the price can be from — never after the ``as_of``
    #: asked. A past close is stamped at its bar's end; a live feed's current
    #: quote, which carries no stamp of its own, at the moment asked (an upper
    #: bound: a delayed quote is older).
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


@dataclass(frozen=True, slots=True)
class Item:
    """One dated item of a world's news (idea: data packages), as physics serves it. Published at
    its day's 00:00 UTC: it exists from that moment on, never before. Nothing in it says whether
    it moves a price."""

    id: str
    kind: Literal["headline", "report"]
    published: date
    ticker: str | None
    title: str
    body: str
    #: A report's numbers: quarter, revenue (USD millions), eps, expected eps, guidance.
    figures: dict[str, Any] | None = None

    @property
    def at(self) -> datetime:
        return datetime.combine(self.published, time(), tzinfo=UTC)


# --- Interface --------------------------------------------------------------

#: The public entries a subclass may not override: the look-ahead guard is in
#: them, and an override would be a provider that skips it.
_GUARDED = ("get_price", "get_ohlcv", "get_news")


def _refuse_override(owner: str, method: str) -> TypeError:
    return TypeError(
        f"{owner} replaces {method}: implement _quote / _bars instead — the "
        "look-ahead guard lives in the base (ADR-028)"
    )


class _SealedEntries(ABCMeta):
    """Refuses assigning or deleting a guarded entry on a provider class after
    it is created (red-team 0008)."""

    def __setattr__(cls, name: str, value: object) -> None:
        if name in _GUARDED:
            raise _refuse_override(cls.__name__, name)
        super().__setattr__(name, value)

    def __delattr__(cls, name: str) -> None:
        if name in _GUARDED:
            raise _refuse_override(cls.__name__, name)
        super().__delattr__(name)


class MarketDataProvider(metaclass=_SealedEntries):
    """Abstract price source. Implementations must be side-effect free.

    An implementation writes :meth:`_quote` and :meth:`_bars`; callers use
    :meth:`get_price` and :meth:`get_ohlcv`, which apply the look-ahead law to
    whatever the implementation returns. A subclass whose ``get_price`` or
    ``get_ohlcv`` resolves anywhere but here (its own, or a mixin's) is a
    ``TypeError`` at class creation; so is assigning one later, on the class or
    on an instance. This closes the ordinary routes, not every route: Python
    has no true ``final``, and code running inside the App's process is past
    the seal anyway — agent code never runs there (ADR-028 amendment).
    """

    #: Short name recorded on quotes and in logs.
    name: str = "abstract"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        for method in _GUARDED:
            owner = next(k for k in cls.__mro__ if method in k.__dict__)
            if owner is not MarketDataProvider:
                raise _refuse_override(cls.__name__, method)

    def __setattr__(self, name: str, value: object) -> None:
        if name in _GUARDED:
            raise _refuse_override(type(self).__name__, name)
        super().__setattr__(name, value)

    def get_price(self, ticker: str, *, as_of: datetime) -> Quote:
        """Latest price for ``ticker`` known at ``as_of``.

        Raises:
            UnknownTickerError: symbol unknown / no data at ``as_of``.
            FeedDataError: the feed answered from after ``as_of``, or with a
                price that is not a positive finite number.
            MarketDataError: upstream failure.
        """
        symbol = normalise_ticker(ticker)
        _require_aware(as_of)
        quote = self._quote(symbol, as_of=as_of)
        if quote.as_of > as_of:
            raise FeedDataError(
                f"{self.name} answered {symbol} at {as_of.isoformat()} with a "
                f"quote from {quote.as_of.isoformat()} — no look-ahead"
            )
        if not (math.isfinite(quote.price) and quote.price > 0):
            raise FeedDataError(f"{self.name} gave {symbol} a price of {quote.price!r}")
        return quote

    def get_ohlcv(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        """Candles in ``[start, end)`` that had *ended* by ``as_of``.

        A bar still open at ``as_of`` — today's daily bar at noon — is not
        served: its close is not known yet.

        The answer may depend only on what was known by ``as_of`` (red-team
        0008): the implementation is never asked about a day after ``as_of``'s,
        and a window with no ended bar is one :class:`UnknownTickerError` whose
        message names only the request — whether the ticker lists, resumes or
        never existed later is not knowable, so it must not be tellable.

        Raises:
            UnknownTickerError: no bar in the window had ended by ``as_of``.
        """
        symbol = normalise_ticker(ticker)
        _require_aware(as_of)
        validate_window(start, end, interval, as_of)
        known_end = min(end, as_of.date() + timedelta(days=1))
        bars = self._bars(symbol, start=start, end=known_end, interval=interval, as_of=as_of)
        ended = [bar for bar in bars if bar_end(bar.ts, interval) <= as_of]
        if not ended:
            raise UnknownTickerError(
                f"no {interval} bar for {symbol!r} in [{start.isoformat()}, "
                f"{end.isoformat()}) had ended by {as_of.isoformat()}"
            )
        return ended

    def get_news(self, *, kind: Literal["headline", "report"], as_of: datetime, since: date,
                 ticker: str | None = None) -> list[Item]:
        """The world's items of ``kind`` published from ``since`` up to ``as_of`` (about
        ``ticker``, when given), oldest first. An item published after ``as_of`` does not exist:
        it is never served, whatever the implementation returns."""
        _require_aware(as_of)
        symbol = None if ticker is None else normalise_ticker(ticker)
        return [item for item in self._news(since=since, as_of=as_of)
                if item.kind == kind and since <= item.published and item.at <= as_of
                and (symbol is None or item.ticker == symbol)]

    def _news(self, *, since: date, as_of: datetime) -> list[Item]:
        """The implementation's items from ``since`` to ``as_of`` (the base filters again).
        A world with no news has none."""
        return []

    def world(self) -> dict[str, object]:
        """The market this provider serves, as a JSON record a run's ledger keeps.

        ``run_started`` carries it, and a backtest database refuses to start
        under a provider whose record differs (B-037): one run, one world. A
        ``reproducible`` world names everything needed to serve the same bars
        again — except any secret, which appears only as a one-way fingerprint
        (management reads ``/events``). The default is honest for any feed
        whose answers are not a function of its record (a live feed, a table
        tests can move).
        """
        return {"provider": self.name, "reproducible": False}

    @abstractmethod
    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        """The implementation's price for a normalised ``symbol`` at ``as_of``.

        Stamp it honestly (see :attr:`Quote.as_of`); the base refuses a stamp
        after ``as_of``.
        """

    @abstractmethod
    def _bars(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        """The implementation's candles for a validated window.

        May include bars that had not ended by ``as_of``; the base drops them.
        """


def bar_end(ts: datetime, interval: str) -> datetime:
    """The first moment a bar opened at ``ts`` is complete — its close known.

    Conservative by construction: a daily bar ends at the next midnight of its
    stamp, though the exchange closed hours earlier. Serving a close late is a
    small cost; serving it early is look-ahead.
    """
    if interval == "1h":
        return ts + timedelta(hours=1)
    if interval == "1d":
        return ts + timedelta(days=1)
    if interval == "1wk":
        return ts + timedelta(weeks=1)
    if interval == "1mo":
        year, month = (ts.year + 1, 1) if ts.month == 12 else (ts.year, ts.month + 1)
        day = min(ts.day, calendar.monthrange(year, month)[1])
        return ts.replace(year=year, month=month, day=day)
    raise InvalidRequestError(f"no bar length for interval {interval!r}")


def _require_aware(as_of: datetime) -> None:
    if as_of.tzinfo is None:
        raise InvalidRequestError("as_of must carry a timezone (UTC)")


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
