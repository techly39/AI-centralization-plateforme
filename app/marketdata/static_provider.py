"""An offline provider serving prices from a fixed table.

Two real uses:

* **Local runs without a network.** Set ``marketdata.provider: "static"`` in
  ``config.yaml`` and the whole app — orders, fills, portfolios — works with no
  external calls, which is the fastest way to try a change end to end.
* **Deterministic tests.** Prices can be moved from test code via
  :meth:`set_price`, which is how the limit-order tests make a price "cross".

It is not a simulation: prices only change when something sets them. A static
price has no time of its own, so a quote is stamped at the moment asked.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

from app.marketdata.base import (
    Bar,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    normalise_ticker,
)


class StaticProvider(MarketDataProvider):
    """Prices come from an in-memory dict; unknown symbols raise."""

    name = "static"

    def __init__(self, prices: dict[str, float] | None = None) -> None:
        self._lock = threading.Lock()
        self._prices: dict[str, float] = {
            normalise_ticker(k): float(v) for k, v in (prices or {}).items()
        }

    def set_price(self, ticker: str, price: float) -> None:
        with self._lock:
            self._prices[normalise_ticker(ticker)] = float(price)

    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        with self._lock:
            price = self._prices.get(symbol)
        if price is None:
            raise UnknownTickerError(f"no static price configured for {symbol!r}")
        return Quote(ticker=symbol, price=price, as_of=as_of, source=self.name)

    def _bars(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        """Flat daily candles at the configured price — shape, not realism."""
        quote = self.get_price(symbol, as_of=as_of)

        bars: list[Bar] = []
        cursor = start
        while cursor < end:
            ts = datetime.combine(cursor, datetime.min.time(), tzinfo=as_of.tzinfo)
            bars.append(
                Bar(
                    ts=ts,
                    open=quote.price,
                    high=quote.price,
                    low=quote.price,
                    close=quote.price,
                    volume=0.0,
                )
            )
            cursor += timedelta(days=1)
        return bars
