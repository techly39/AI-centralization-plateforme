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

The recipe is the world: whoever holds it knows every future close. It lives with the operator
(the environment, the cassette), never with an agent.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.marketdata.base import Bar

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

    @model_validator(mode="after")
    def _sane(self) -> MadeUpMarket:
        if not self.origin < self.pivot <= self.origin + timedelta(days=self.days):
            raise ValueError("the pivot lies after the origin and within the days")
        if sum(f.width for f in self.families) > MAX_NAMES:
            raise ValueError(f"at most {MAX_NAMES} names")
        if len({f.prefix for f in self.families}) != len(self.families):
            raise ValueError("each family has its own prefix")
        return self


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
