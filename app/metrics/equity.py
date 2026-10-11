"""Reconstructing what a pod was worth on every day of its life.

Return, Sharpe, and drawdown all need a *time series*, and the app stores no
such series — it stores events. So this module builds one on demand:

1. replay the pod's ledger day by day, through the **same reducers** the live
   portfolio uses (:mod:`app.ledger.reducers`), giving cash and positions as of
   each day's close;
2. ask the market data provider for one daily-close series per ticker the pod
   ever held;
3. value each day's holdings at that day's close.

Reusing the reducers matters more than it looks: it means the last point of this
curve is computed by the same arithmetic as ``GET /portfolio``, so the two can
never quietly disagree about what a pod is worth. The final point additionally
prefers a *live* quote over the last daily close, for the same reason — the
metrics page and the portfolio page should show the same total.

Degrading, not failing (the rule the portfolio endpoint already follows): a
ticker whose history cannot be fetched is valued at its average cost and its
symbol is reported in ``pricing_errors``, rather than the whole metrics call
failing because one symbol was delisted.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event
from app.ledger.events import EVENT_ALLOCATION_SET
from app.ledger.reducers import DerivedState, apply_event, reducer_event_types
from app.marketdata import MarketDataError, MarketDataProvider
from app.metrics.performance import EquityPoint

#: Hard stop on how far back a curve is built, so one very old pod cannot turn a
#: metrics call into a multi-thousand-day replay plus that many price lookups.
#: Five years is far longer than any run this app is built for.
MAX_CURVE_DAYS = 5 * 365


@dataclass(slots=True)
class EquityCurve:
    """A pod's daily equity, plus what could not be priced while building it."""

    points: list[EquityPoint] = field(default_factory=list)
    #: Tickers valued at cost because no history was available.
    pricing_errors: list[str] = field(default_factory=list)

    @property
    def fully_priced(self) -> bool:
        return not self.pricing_errors

    @property
    def latest_equity(self) -> float:
        return self.points[-1].equity if self.points else 0.0


class DailyCloseCache:
    """One daily-close series per ticker, fetched once and reused.

    A leaderboard prices every pod in the firm, and pods hold overlapping names.
    Without this, ten pods holding AAPL would mean ten identical history
    downloads. Build one cache per request and pass it around.
    """

    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider
        # ticker -> (sorted dates, closes aligned to them)
        self._series: dict[str, tuple[list[date], list[float]]] = {}
        self._failed: set[str] = set()

    def load(self, ticker: str, *, start: date, end: date, as_of: datetime) -> bool:
        """Fetch ``ticker``'s daily closes if not already held. False on failure."""
        if ticker in self._series:
            return True
        if ticker in self._failed:
            return False
        try:
            bars = self._provider.get_ohlcv(
                ticker,
                start=start,
                # ``end`` is exclusive in the provider interface.
                end=end + timedelta(days=1),
                interval="1d",
                as_of=as_of,
            )
        except MarketDataError:
            self._failed.add(ticker)
            return False

        closes: dict[date, float] = {bar.ts.date(): bar.close for bar in bars}
        if not closes:
            self._failed.add(ticker)
            return False
        days = sorted(closes)
        self._series[ticker] = (days, [closes[d] for d in days])
        return True

    def close_on(self, ticker: str, on: date) -> float | None:
        """The last close at or before ``on`` — markets are shut most days.

        Carrying the previous close forward is what a real mark-to-market does
        on a weekend or holiday; it is not an approximation.
        """
        series = self._series.get(ticker)
        if series is None:
            return None
        days, closes = series
        index = bisect_right(days, on)
        if index == 0:
            return None  # the pod held it before this history begins
        return closes[index - 1]


def build_equity_curve(
    session: Session,
    *,
    pod_id: int,
    provider: MarketDataProvider,
    as_of: datetime,
    closes: DailyCloseCache | None = None,
    live_price: bool = True,
) -> EquityCurve:
    """Daily equity for one pod, from its first event to ``as_of``.

    Args:
        closes: share one across pods when building a leaderboard.
        live_price: value the final day at the current quote rather than the
            last daily close, so metrics agree with ``GET /portfolio``.
    """
    closes = closes or DailyCloseCache(provider)
    events = _pod_events(session, pod_id)
    if not events:
        return EquityCurve()

    snapshots, tickers = _replay_by_day(events, pod_id=pod_id, until=as_of.date())
    if not snapshots:
        return EquityCurve()

    window_start = snapshots[0].on
    window_end = snapshots[-1].on
    pricing_errors = [
        ticker
        for ticker in sorted(tickers)
        if not closes.load(ticker, start=window_start, end=window_end, as_of=as_of)
    ]

    live_quotes = (
        _live_quotes(provider, snapshots[-1].holdings, as_of=as_of)
        if live_price
        else {}
    )

    points: list[EquityPoint] = []
    for i, snapshot in enumerate(snapshots):
        is_last = i == len(snapshots) - 1
        equity = snapshot.cash
        for ticker, (qty, avg_cost) in snapshot.holdings.items():
            price = live_quotes.get(ticker) if is_last else None
            if price is None:
                price = closes.close_on(ticker, snapshot.on)
            if price is None:
                # No history at all, or none yet on this date: carry the position
                # at what it cost. Flagged, never silently mispriced.
                price = avg_cost
                if ticker not in pricing_errors:
                    pricing_errors.append(ticker)
            equity += qty * price
        points.append(
            EquityPoint(on=snapshot.on, equity=equity, net_flow=snapshot.net_flow)
        )

    return EquityCurve(points=points, pricing_errors=sorted(set(pricing_errors)))


# --- Replay internals -------------------------------------------------------

@dataclass(slots=True)
class _DaySnapshot:
    on: date
    cash: float
    #: ticker -> (qty, avg_cost) at that day's close.
    holdings: dict[str, tuple[float, float]]
    net_flow: float


def _pod_events(session: Session, pod_id: int) -> list[Event]:
    """Every state-changing event for one pod, in canonical replay order."""
    rows = (
        session.execute(
            select(Event)
            .where(Event.type.in_(reducer_event_types()))
            .order_by(Event.id)  # append order = live order (ADR-025)
        )
        .scalars()
        .all()
    )
    # ``pod_id`` lives inside the JSON payload; filtering in Python keeps this
    # backend-agnostic (SQLite and Postgres disagree about JSON operators) and
    # the row count is bounded by the fund's own trading history.
    return [e for e in rows if (e.payload_json or {}).get("pod_id") == pod_id]


def _replay_by_day(
    events: list[Event], *, pod_id: int, until: date
) -> tuple[list[_DaySnapshot], set[str]]:
    """Fold events into one snapshot per calendar day, inclusive of empty days."""
    # An event counts from the latest day the ledger had reached when it was
    # appended. On a ledger whose stamps never run backwards (ADR-025) that is
    # just its own day; on an older one it keeps every day's fold a prefix of
    # the live, append-ordered fold.
    by_day: dict[date, list[Event]] = defaultdict(list)
    reached: date | None = None
    for event in events:
        day = event.ts.date()
        reached = day if reached is None or day > reached else reached
        by_day[reached].append(event)

    start = min(by_day)
    if start > until:
        return [], set()
    # A pod that has been idle for years should not cost years of price history.
    start = max(start, until - timedelta(days=MAX_CURVE_DAYS))

    state = DerivedState()
    # Events from before the window still count — they built the position we
    # start the window holding — they just do not get their own snapshot.
    for day in sorted(d for d in by_day if d < start):
        for event in by_day[day]:
            apply_event(state, event)

    snapshots: list[_DaySnapshot] = []
    tickers: set[str] = set()
    cursor = start
    while cursor <= until:
        net_flow = 0.0
        for event in by_day.get(cursor, ()):
            apply_event(state, event)
            if event.type == EVENT_ALLOCATION_SET:
                net_flow += float((event.payload_json or {}).get("delta", 0.0))

        holdings = {
            ticker: (pos["qty"], pos["avg_cost"])
            for (held_pod, ticker), pos in state.positions.items()
            if held_pod == pod_id
        }
        tickers.update(holdings)
        snapshots.append(
            _DaySnapshot(
                on=cursor,
                cash=state.cash.get(pod_id, 0.0),
                holdings=holdings,
                net_flow=net_flow,
            )
        )
        cursor += timedelta(days=1)

    return snapshots, tickers


def _live_quotes(
    provider: MarketDataProvider,
    holdings: dict[str, tuple[float, float]],
    *,
    as_of: datetime,
) -> dict[str, float]:
    """Current quotes for today's holdings; missing ones fall back to closes."""
    quotes: dict[str, float] = {}
    for ticker in holdings:
        try:
            quotes[ticker] = provider.get_price(ticker, as_of=as_of).price
        except MarketDataError:
            continue
    return quotes
