"""A made-up market from a short recipe: families of names, each with a fate (idea: a dead pod is
replaced; the capital machine's demos).

A hosted world (``runtime/world.py``) must be rebuilt from its cassette alone, so a market with a
planted law is described, not shipped: a seed, the days, and families such as "20 names whose
momentum keeps paying" or "10 names whose sector collapses from the pivot day on". This module
turns the recipe into daily bars (stdlib ``random``, the seed alone), served by
:class:`app.marketdata.bars_provider.BarsProvider` under the same law as every feed.

Every name's daily log-return before the pivot is ``mu + noise·ε``, where its drift ``mu`` wanders
slowly (an AR(1), persistence 0.99, stationary sd ``planted``): 20-day momentum predicts, so a
momentum pitch is eligible on the days before the pivot. From the pivot on, by fate:

* ``edge``  — the same law goes on (the edge persists);
* ``noise`` — ``noise·ε`` from the first day (no edge ever; ``mu`` still drawn, never used);
* ``sink``  — ``-rate + 0.3·noise·ε``: the sector bleeds ``rate`` a day;
* ``crash`` — ``0.3·noise·ε``, except three days of −5 % starting ``rate`` days after the pivot;
* ``dip``   — about 6 % down in two weeks (−0.45 % a day), then +0.04 % a day, both nearly
  without noise.

With a ``news`` block (idea: data packages) the world also writes dated items: each day a few
noise headlines from templates, a quarterly report per name (revenue, earnings against what was
expected, guidance), and a few planted *causes*. A cause adds ``shock`` to its name's log-return on
its day and ``drift`` on each of the next ``days``; nothing else moves any price, so a noise
headline moves nothing. The items come from their own random stream: a recipe's bars without
causes are exactly its bars without news, and a recipe without news is exactly as before.

The recipe is the world: whoever holds it knows every future close and which item is a cause. It
lives with the operator (the environment, the cassette), never with an agent.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.marketdata.base import Bar, Item

MAX_NAMES = 400
MAX_DAYS = 4000


class Family(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    #: The family's names are ``<prefix>00``, ``<prefix>01``, ...
    prefix: str = Field(pattern=r"^[A-Z]{1,3}$")
    width: int = Field(ge=1, le=100)
    fate: Literal["edge", "noise", "sink", "crash", "dip"]
    #: ``sink``: the daily fall; ``crash``: the days after the pivot the crash starts.
    rate: float = Field(default=0.0, ge=0.0, le=500.0)


class Cause(BaseModel):
    """A planted cause: an item that moves its name's later prices."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    #: ``fraud``: a headline; ``earnings_miss``: the name's quarterly report, far below expected.
    kind: Literal["fraud", "earnings_miss"]
    ticker: str = Field(pattern=r"^[A-Z]{1,3}[0-9]{2}$")
    #: The day it is published: its effect starts on that day's bar.
    on: date
    #: Added to the name's log-return on its day, then ``drift`` on each of the next ``days``.
    shock: float = Field(default=-0.08, ge=-0.5, le=0.5)
    drift: float = Field(default=-0.01, ge=-0.1, le=0.1)
    days: int = Field(default=5, ge=0, le=60)


class News(BaseModel):
    """The world's news: noise headlines, quarterly reports, and the planted causes."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    #: Noise headlines a day (the world's noise level).
    per_day: int = Field(default=3, ge=0, le=20)
    #: Every name publishes a quarterly report.
    reports: bool = True
    causes: tuple[Cause, ...] = Field(default=(), max_length=20)


class MadeUpMarket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    seed: int = Field(ge=0, le=2**31)
    #: The first day with a bar, and the day the fates begin.
    origin: date
    pivot: date
    #: Days of bars from ``origin``.
    days: int = Field(ge=30, le=MAX_DAYS)
    #: Daily sd of the noise; stationary sd of each name's drift.
    noise: float = Field(default=0.010, gt=0.0, lt=0.2)
    planted: float = Field(default=0.004, ge=0.0, lt=0.1)
    families: tuple[Family, ...] = Field(min_length=1, max_length=20)
    #: The world's dated items; none in a recipe that names none (every older world).
    news: News | None = None

    @model_validator(mode="after")
    def _sane(self) -> MadeUpMarket:
        if not self.origin < self.pivot <= self.origin + timedelta(days=self.days):
            raise ValueError("the pivot lies after the origin and within the days")
        if sum(f.width for f in self.families) > MAX_NAMES:
            raise ValueError(f"at most {MAX_NAMES} names")
        if len({f.prefix for f in self.families}) != len(self.families):
            raise ValueError("each family has its own prefix")
        names = set(_names(self))
        for cause in self.news.causes if self.news is not None else ():
            if cause.ticker not in names:
                raise ValueError(f"cause on {cause.ticker!r}: no such name in the families")
            if not self.origin < cause.on < self.origin + timedelta(days=self.days):
                raise ValueError(f"cause on {cause.ticker!r}: its day lies within the days")
        if self.news is not None and len({(c.ticker, c.on) for c in self.news.causes}) != len(
                self.news.causes):
            raise ValueError("one cause per name and day")
        return self


def _names(market: MadeUpMarket) -> list[str]:
    return [f"{fam.prefix}{k:02d}" for fam in market.families for k in range(fam.width)]


def returns(market: MadeUpMarket) -> dict[str, list[float]]:
    """Every name's daily log-returns, in the recipe's order: one random stream, the seed alone."""
    rng = random.Random(market.seed)
    pivot = (market.pivot - market.origin).days
    innovation = market.planted * math.sqrt(1 - 0.99**2)
    out: dict[str, list[float]] = {}
    for fam in market.families:
        for k in range(fam.width):
            mu, path = rng.gauss(0, market.planted), []
            for d in range(market.days):
                mu = 0.99 * mu + innovation * rng.gauss(0, 1)
                eps = rng.gauss(0, 1)
                if fam.fate == "noise":
                    path.append(market.noise * eps)
                elif d < pivot or fam.fate == "edge":
                    path.append(mu + market.noise * eps)
                elif fam.fate == "sink":
                    path.append(-fam.rate + 0.3 * market.noise * eps)
                elif fam.fate == "crash":
                    crash = pivot + int(fam.rate)
                    path.append(-0.05 if crash <= d < crash + 3 else 0.3 * market.noise * eps)
                elif d < pivot + 14:
                    path.append(-0.0045 + 0.05 * market.noise * eps)
                else:
                    path.append(0.0004 + 0.05 * market.noise * eps)
            out[f"{fam.prefix}{k:02d}"] = path
    for cause in market.news.causes if market.news is not None else ():
        path, d = out[cause.ticker], (cause.on - market.origin).days
        path[d] += cause.shock
        for later in range(d + 1, min(d + 1 + cause.days, market.days)):
            path[later] += cause.drift
    return out


def bars(market: MadeUpMarket) -> dict[str, list[Bar]]:
    """The recipe's daily bars: opens at the previous close, a small wick, $50M a day of volume."""
    out = {}
    for name, path in returns(market).items():
        price, rows = 40.0 + 3 * (sum(map(ord, name)) % 7), []
        for d, r in enumerate(path):
            opened, price = price, price * math.exp(r)
            ts = datetime.combine(market.origin + timedelta(d), datetime.min.time(), UTC)
            rows.append(Bar(ts=ts, open=opened, high=max(opened, price) * 1.002,
                            low=min(opened, price) * 0.998, close=price, volume=5e7 / price))
        out[name] = rows
    return out


# --- the news -----------------------------------------------------------------------------------

#: Noise headlines about one name: (title, body). None of them moves a price.
_NAME_NOISE = (
    ("{t} to present at an industry conference next week",
     "Management will outline the product roadmap; no new guidance is expected."),
    ("{t} names a new independent board member",
     "The director has a background in operations; the board now has nine members."),
    ("{t} launches an updated product line",
     "The launch was announced in a short press release; pricing was not disclosed."),
    ("Broker reiterates its neutral rating on {t}",
     "The note kept its price target unchanged and called the valuation fair."),
    ("{t} shares active in early trading",
     "Volume picked up in the first hour with no news from the company."),
    ("{t} recalls a small batch of products",
     "The company said the recall is limited and will not affect its results."),
    ("{t} settles a small patent dispute",
     "Terms were not disclosed; the company called the amount immaterial."),
    ("{t} opens a new regional office",
     "The office will host about forty staff in sales and support."),
    ("Rumour: {t} in early talks over a partnership",
     "Neither side commented; people familiar with the matter called the talks preliminary."),
    ("{t} upgrades its customer software platform",
     "The company said the migration went as planned."),
)
#: Noise headlines about the market as a whole.
_MARKET_NOISE = (
    ("Markets steady ahead of central bank minutes",
     "Traders expect no change to policy; volumes are in line with the monthly average."),
    ("Sector roundup: a quiet session across industries",
     "Most sectors closed within a narrow range."),
    ("Survey: business confidence little changed",
     "The monthly index moved less than a point."),
)
_CAUSE_HEADLINE = {
    "fraud": ("{t}: short seller alleges accounting fraud; the regulator opens an inquiry",
              "A research firm says {t} overstated its revenue for several quarters; the "
              "regulator confirmed an inquiry. The company denies any wrongdoing."),
}
QUARTER = 91


def _report(ticker: str, day: date, q: int, revenue: float, expected: float, eps: float,
            guidance: str) -> tuple[str, str, dict[str, Any]]:
    figures = {"quarter": q, "revenue_musd": round(revenue, 1), "eps": round(eps, 2),
               "expected_eps": round(expected, 2), "guidance": guidance}
    return (f"{ticker} quarterly report (quarter {q})",
            f"Revenue ${figures['revenue_musd']:.1f}M; earnings per share "
            f"${figures['eps']:.2f} against ${figures['expected_eps']:.2f} expected; "
            f"guidance {guidance}.", figures)


def items(market: MadeUpMarket) -> list[Item]:
    """Every item of the recipe's news, in publishing order, from its own random stream."""
    if market.news is None:
        return []
    news, names = market.news, _names(market)
    rng = random.Random(f"news:{market.seed}")
    raw: list[tuple[date, str, str | None, str, str, dict[str, Any] | None]] = []
    for d in range(market.days):
        day = market.origin + timedelta(d)
        for _ in range(news.per_day):
            if rng.random() < 0.15:
                title, body = rng.choice(_MARKET_NOISE)
                raw.append((day, "headline", None, title, body, None))
            else:
                t = rng.choice(names)
                title, body = rng.choice(_NAME_NOISE)
                raw.append((day, "headline", t, title.format(t=t), body.format(t=t), None))
    misses = {c.ticker: c for c in news.causes if c.kind == "earnings_miss"}
    if news.reports:
        for t in names:
            offset, revenue = rng.randrange(QUARTER), rng.uniform(200, 5000)
            expected = rng.uniform(0.5, 3.0)
            for q, d in enumerate(range(offset, market.days, QUARTER), start=1):
                revenue *= math.exp(rng.gauss(0.01, 0.03))
                expected *= math.exp(rng.gauss(0.01, 0.02))
                eps = expected * (1 + rng.gauss(0, 0.03))
                guidance = rng.choices(("maintained", "raised", "lowered"), (8, 1, 1))[0]
                day = market.origin + timedelta(d)
                miss = misses.get(t)
                if miss is not None and abs((day - miss.on).days) <= QUARTER // 2:
                    # The miss is this quarter's report, on its own day, the company's own numbers.
                    del misses[t]
                    raw.append((miss.on, "report", t, *_report(t, miss.on, q, revenue * 0.93,
                                                               expected, expected * 0.7,
                                                               "lowered")))
                    continue
                raw.append((day, "report", t, *_report(t, day, q, revenue, expected, eps,
                                                       guidance)))
    for c in news.causes:
        if c.kind == "fraud":
            title, body = _CAUSE_HEADLINE["fraud"]
            raw.append((c.on, "headline", c.ticker, title.format(t=c.ticker),
                        body.format(t=c.ticker), None))
        elif c.ticker in misses:      # no scheduled quarter of its own (reports off, the edge)
            q = 1 + (c.on - market.origin).days // QUARTER
            r = random.Random(f"miss:{market.seed}:{c.ticker}:{c.on}")
            revenue, expected = r.uniform(200, 5000), r.uniform(0.5, 3.0)
            raw.append((c.on, "report", c.ticker, *_report(c.ticker, c.on, q, revenue * 0.93,
                                                           expected, expected * 0.7, "lowered")))
    # Ordered by day, then by what any reader can see: the id says nothing a reader cannot read.
    raw.sort(key=lambda x: (x[0], x[1], x[2] or "", x[3], x[4]))
    out, n, last = [], 0, None
    for day, kind, t, title, body, figures in raw:
        n = n + 1 if day == last else 1
        last = day
        out.append(Item(id=f"{day:%Y%m%d}-{n:03d}", kind=kind, published=day, ticker=t,  # type: ignore[arg-type]
                        title=title, body=body, figures=figures))
    return out
