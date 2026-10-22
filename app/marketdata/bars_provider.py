"""A market made of given daily bars: a made-up world, an exported history, a data package.

The demos of the capital machine need markets with a planted law (an edge that persists, one that
dies, two names that move as one, a sector that collapses); the keyed random walk
(:mod:`app.marketdata.synthetic_provider`) has one law for every name. This provider serves whatever
daily bars it is given, under the same law as every feed: the base drops a bar that had not ended
by ``as_of`` (:mod:`app.marketdata.base`), and a quote is the close of the latest day whose bar had
ended, stamped at that day's end.

The bars are the world: whoever holds them knows every future close. ``world()`` records only a
fingerprint (SHA-256 of the canonical bars), so a run names the market it lived in without carrying
it, and refuses to resume under different bars. Daily bars only.

It may also hold the world's news (dated items, :class:`app.marketdata.base.Item`), served by the
base under the same law: an item published after the world's now does not exist. A market with
news records the news' fingerprint too; one without records exactly what it always did.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone

from app.marketdata.base import (
    Bar,
    InvalidRequestError,
    Item,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    normalise_ticker,
)

FINGERPRINT_HEX = 32


class BarsProvider(MarketDataProvider):
    """Daily bars from a table, one bar per (ticker, day), each stamped at its day's 00:00 UTC."""

    name = "bars"

    def __init__(self, bars: Mapping[str, Sequence[Bar]], news: Sequence[Item] = ()) -> None:
        table: dict[str, tuple[list[date], list[Bar]]] = {}
        for raw, rows in bars.items():
            symbol = normalise_ticker(raw)
            if symbol in table:
                raise ValueError(f"{symbol!r} is given twice")
            ordered = sorted(rows, key=lambda b: b.ts)
            days = [b.ts.astimezone(timezone.utc).date() for b in ordered]
            if not ordered:
                raise ValueError(f"{symbol!r} has no bars")
            if len(set(days)) != len(days):
                raise ValueError(f"{symbol!r} has two bars for one day")
            for bar, day in zip(ordered, days):
                if bar.ts != datetime.combine(day, time(), tzinfo=timezone.utc):
                    raise ValueError(f"{symbol!r}: a daily bar is stamped at its day's 00:00 UTC")
                prices = (bar.open, bar.high, bar.low, bar.close)
                if not all(math.isfinite(p) and p > 0 for p in prices):
                    raise ValueError(f"{symbol!r} {day}: prices must be positive and finite")
                if not (math.isfinite(bar.volume) and bar.volume >= 0):
                    raise ValueError(f"{symbol!r} {day}: volume must be finite and not negative")
            table[symbol] = (days, ordered)
        if not table:
            raise ValueError("a bars market needs at least one ticker")
        self._table = table
        canonical = json.dumps(
            {s: [[d.isoformat(), b.open, b.high, b.low, b.close, b.volume]
                 for d, b in zip(days, rows)] for s, (days, rows) in sorted(table.items())},
            separators=(",", ":"), sort_keys=True)
        self._fingerprint = hashlib.sha256(canonical.encode()).hexdigest()[:FINGERPRINT_HEX]
        self._items = sorted(news, key=lambda x: x.published)
        self._published = [x.published for x in self._items]
        self._news_fingerprint = None if not self._items else hashlib.sha256(json.dumps(
            [[x.id, x.kind, x.published.isoformat(), x.ticker, x.title, x.body, x.figures]
             for x in self._items], separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()[:FINGERPRINT_HEX]

    def world(self) -> dict[str, object]:
        """The market's fingerprint and its tickers; never a bar."""
        record: dict[str, object] = {"provider": self.name, "reproducible": True,
                                     "symbols": sorted(self._table),
                                     "bars_fingerprint": self._fingerprint}
        if self._news_fingerprint is not None:
            record["news_fingerprint"] = self._news_fingerprint
        return record

    def _news(self, *, since: date, as_of: datetime) -> list[Item]:
        last = as_of.astimezone(timezone.utc).date()
        return self._items[bisect_left(self._published, since):bisect_right(self._published, last)]

    def _series(self, symbol: str) -> tuple[list[date], list[Bar]]:
        series = self._table.get(symbol)
        if series is None:
            raise UnknownTickerError(f"no bars for {symbol!r} in this market")
        return series

    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        days, rows = self._series(symbol)
        # The latest day whose bar had ended (its next midnight UTC) by as_of.
        last = as_of.astimezone(timezone.utc).date() - timedelta(days=1)
        i = bisect_right(days, last)
        if i == 0:
            raise UnknownTickerError(f"no close for {symbol!r} by {as_of.isoformat()}")
        bar = rows[i - 1]
        return Quote(ticker=symbol, price=bar.close, as_of=bar.ts + timedelta(days=1),
                     source=self.name)

    def _bars(self, symbol: str, *, start: date, end: date, interval: str,
              as_of: datetime) -> list[Bar]:
        if interval != "1d":
            raise InvalidRequestError(f"a bars market has daily bars only, not {interval!r}")
        days, rows = self._series(symbol)
        return rows[bisect_left(days, start):bisect_left(days, end)]
