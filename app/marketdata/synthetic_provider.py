"""A keyed, offline market: every bar a pure function of (key, symbol, day).

The backtest's own world (B-004c, ADR-030). The real feed cannot be the ground
of a determinism test — it needs the network, its history is revised, and Yahoo
answers the same question differently on different days. This one can:

* **A pure function.** Day ``D``'s log-return for ``symbol`` comes from
  ``HMAC-SHA256(key, f"return:{symbol}:{D}")`` (Box-Muller on two 53-bit
  uniforms), so the answer does not depend on which days were asked before, in
  what order, by how many processes. No ``random`` module state, no clock, no I/O.
* **A secret world.** The formula is published law; the key is not. Whoever
  knows the key knows every future close, so it is ≥ 128 random bits that no
  agent-visible surface carries (red-team 0010: a small integer seed was
  brute-forced from three served volumes). Wicks and volumes come from a second
  HMAC domain (``noise:``), so the noise agents see is no window onto the returns.
* **A walk with a past.** Closes compound from :data:`ORIGIN` at the configured
  start price (geometric Brownian motion, one step per calendar day — the
  synthetic market never closes). A day's open is the previous close; high and
  low widen the body by a hashed fraction; volume is hashed too.
* **Daily bars only.** ``1wk`` (Monday-anchored) and ``1mo`` aggregate them;
  ``1h`` is refused: there is no intraday path, and inventing one per route
  would be two routes showing two markets (red-team 0008's arbitrage).
* **The same law as every feed.** A quote is the close of the latest day that
  had *ended* by ``as_of``, stamped at that day's end; the base
  (:class:`~app.marketdata.base.MarketDataProvider`) drops unended bars and
  refuses anything stamped later.

Only configured symbols exist; any other is unknown. Bit-identical across runs
on one machine; across platforms ``math.exp`` may differ in the last ulp.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
from datetime import date, datetime, time, timedelta, timezone

from app.marketdata.base import (
    Bar,
    InvalidRequestError,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    normalise_ticker,
)

#: The first day the synthetic market has a bar for. Its open is the start price.
ORIGIN = date(2000, 1, 1)

#: Daily drift and volatility of the log-price (≈ 11 % a year before the
#: volatility drag, ≈ 29 % volatility annualised over 365 days).
DEFAULT_DRIFT = 0.0003
DEFAULT_VOLATILITY = 0.015

#: The shortest world key accepted: 128 bits, out of any brute-force reach.
MIN_KEY_BYTES = 16

#: The formula's version, recorded with every run: changing how bars are
#: derived from the key is a new law, and an old run names the one it lived.
LAW = "hmac-sha256-gbm/1"

#: A world is named by ``HMAC-SHA256(key, FINGERPRINT_MESSAGE)``, first 128 bits.
FINGERPRINT_MESSAGE = b"fingerprint:v1"
FINGERPRINT_HEX = 32

_TWO_53 = float(1 << 53)


def _uniforms(key: bytes, domain: str, symbol: str, day: date) -> tuple[float, ...]:
    """Four independent uniforms in (0, 1) for one (domain, symbol, day) of a world."""
    message = f"{domain}:{symbol}:{day.isoformat()}".encode()
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return tuple(
        ((int.from_bytes(digest[i : i + 8], "big") >> 11) + 0.5) / _TWO_53
        for i in range(0, 32, 8)
    )


class SyntheticProvider(MarketDataProvider):
    """A deterministic random walk per configured symbol, keyed by a secret."""

    name = "synthetic"

    def __init__(
        self,
        key: bytes,
        symbols: dict[str, float],
        *,
        drift: float = DEFAULT_DRIFT,
        volatility: float = DEFAULT_VOLATILITY,
    ) -> None:
        if not isinstance(key, bytes) or len(key) < MIN_KEY_BYTES:
            raise ValueError(
                f"a world key is at least {MIN_KEY_BYTES} random bytes "
                "(e.g. secrets.token_bytes(32)); a short seed can be brute-forced"
            )
        if not (math.isfinite(drift) and abs(drift) < 0.1):
            raise ValueError(f"drift must be finite and |drift| < 0.1, got {drift!r}")
        if not (math.isfinite(volatility) and 0 <= volatility < 0.5):
            raise ValueError(f"volatility must be in [0, 0.5), got {volatility!r}")
        starts: dict[str, float] = {}
        for raw, price in symbols.items():
            price = float(price)
            if not (math.isfinite(price) and price > 0):
                raise ValueError(f"start price for {raw!r} must be positive and finite")
            starts[normalise_ticker(raw)] = price
        if not starts:
            raise ValueError("a synthetic world needs at least one symbol")
        self._key = key
        self._starts = starts
        self._drift = drift
        self._volatility = volatility
        self._lock = threading.Lock()
        #: Per symbol, closes[i] is the close of ORIGIN + i days, extended lazily.
        self._closes: dict[str, list[float]] = {s: [] for s in starts}

    # --- the walk -------------------------------------------------------------

    def _close_through(self, symbol: str, day: date) -> list[float]:
        """The closes from ORIGIN through ``day`` (computed once, then cached)."""
        if symbol not in self._starts:
            raise UnknownTickerError(f"no synthetic symbol {symbol!r}")
        needed = (day - ORIGIN).days + 1
        with self._lock:
            closes = self._closes[symbol]
            price = closes[-1] if closes else self._starts[symbol]
            mu = self._drift - self._volatility**2 / 2
            while len(closes) < needed:
                day = ORIGIN + timedelta(days=len(closes))
                u1, u2, _, _ = _uniforms(self._key, "return", symbol, day)
                z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
                price = price * math.exp(mu + self._volatility * z)
                closes.append(price)
            return closes

    def _day_bar(self, symbol: str, day: date, closes: list[float]) -> Bar:
        i = (day - ORIGIN).days
        close = closes[i]
        open_ = closes[i - 1] if i else self._starts[symbol]
        u3, u4, _, _ = _uniforms(self._key, "noise", symbol, day)
        wick = self._volatility * u3 / 2
        return Bar(
            ts=datetime.combine(day, time(), tzinfo=timezone.utc),
            open=open_,
            high=max(open_, close) * (1 + wick),
            low=min(open_, close) * (1 - wick),
            close=close,
            volume=float(int(1e5 + 9e5 * u4)),
        )

    def _daily(self, symbol: str, first: date, stop: date) -> list[Bar]:
        """Daily bars for days in ``[first, stop)``, never before ORIGIN."""
        first = max(first, ORIGIN)
        if stop <= first:
            return []
        closes = self._close_through(symbol, stop - timedelta(days=1))
        return [
            self._day_bar(symbol, first + timedelta(days=k), closes)
            for k in range((stop - first).days)
        ]

    # --- the world's record -----------------------------------------------------

    def world(self) -> dict[str, object]:
        """Everything that fixes this market, the key only as a fingerprint.

        The fingerprint is its own HMAC domain (``fingerprint:``), so it is no
        window onto any ``return:`` or ``noise:`` value; and the key is ≥ 128
        bits, so it cannot be searched for from the fingerprint either.
        """
        fingerprint = hmac.new(self._key, FINGERPRINT_MESSAGE, hashlib.sha256)
        return {
            "provider": self.name,
            "reproducible": True,
            "law": LAW,
            "origin": ORIGIN.isoformat(),
            "drift": self._drift,
            "volatility": self._volatility,
            "symbols": dict(sorted(self._starts.items())),
            "key_fingerprint": fingerprint.hexdigest()[:FINGERPRINT_HEX],
        }

    # --- the provider interface ------------------------------------------------

    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        # The latest day whose bar had ended (its next midnight UTC) by as_of.
        day = as_of.astimezone(timezone.utc).date() - timedelta(days=1)
        if day < ORIGIN:
            raise UnknownTickerError(f"no synthetic close for {symbol!r} before {ORIGIN}")
        bar = self._daily(symbol, day, day + timedelta(days=1))[0]
        return Quote(
            ticker=symbol,
            price=bar.close,
            as_of=bar.ts + timedelta(days=1),
            source=self.name,
        )

    def _bars(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        interval: str,
        as_of: datetime,
    ) -> list[Bar]:
        if interval == "1d":
            return self._daily(symbol, start, end)
        if interval == "1wk":
            anchors = _anchors(start, end, lambda d: d - timedelta(days=d.weekday()),
                               lambda d: d + timedelta(days=7))
        elif interval == "1mo":
            anchors = _anchors(start, end, lambda d: d.replace(day=1), _next_month)
        else:
            raise InvalidRequestError(
                f"the synthetic market has daily bars only (1d, 1wk, 1mo), not {interval!r}"
            )
        bars = []
        for first, stop in anchors:
            # A period still running at as_of is skipped here, not computed and
            # dropped by the base: no day after as_of's is ever evaluated.
            if datetime.combine(stop, time(), tzinfo=timezone.utc) > as_of:
                continue
            days = self._daily(symbol, first, stop)
            if not days:
                continue
            bars.append(
                Bar(
                    ts=datetime.combine(first, time(), tzinfo=timezone.utc),
                    open=days[0].open,
                    high=max(b.high for b in days),
                    low=min(b.low for b in days),
                    close=days[-1].close,
                    volume=sum(b.volume for b in days),
                )
            )
        return bars


def _next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _anchors(start, end, floor, step) -> list[tuple[date, date]]:  # noqa: ANN001
    """``(first, stop)`` periods whose first day falls in ``[start, end)``."""
    periods = []
    first = floor(start)
    if first < start:
        first = step(first)
    while first < end:
        periods.append((first, step(first)))
        first = step(first)
    return periods
