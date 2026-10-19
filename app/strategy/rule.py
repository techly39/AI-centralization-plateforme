"""strategy-v1: a strategy written as a rule, and its pure evaluation (idea: the pitch and the gates).

A strategy is **data, not code** in this first language: a small rule any agent can write and
anyone can rerun on any stretch of any world ("a strategy is an isolated function": data →
strategy → result). No agent code runs anywhere; the rule is read by the deterministic code below.

    {"language": "strategy-v1", "universe": ["SYNA", "SYNB", "SYNC"],
     "signal": "momentum", "lookback": 20, "rebalance_every": 5,
     "top_n": 1, "side": "long_only", "gross": 1.0}

The law of evaluation, one rebalance at a time:

* **Days.** Only days every ticker of the universe has a bar for count (a calendar shared by the
  whole universe). The window ``[start, end)`` holds the decision days; a day's position earns
  the close-to-close return to the next shared day, so a window of ``D`` days has ``D - 1``
  returns, every one realised inside the window.
* **Scores** at day ``t`` use closes up to ``t`` only (never a later bar):
  ``momentum`` = ``close_t / close_{t-L} - 1``; ``mean_reversion`` = minus that;
  ``low_volatility`` = minus the standard deviation of the last ``L`` daily returns.
  A ticker with fewer than ``L`` earlier shared days has no score and the book stays flat.
* **Weights.** Every ``rebalance_every`` decision days: rank by score (ties broken by ticker
  name), hold the top ``top_n`` at ``+gross / top_n`` each (``long_only``), or the top ``top_n`` at
  ``+gross / (2 top_n)`` and the bottom ``top_n`` at ``-gross / (2 top_n)`` (``long_short``). Weights
  are held constant until the next rebalance.
* **Costs.** A rebalance pays ``fee_rate × turnover`` (the OMS's fee, the sum of absolute weight
  changes) out of the next day's return. Market impact is not charged here: it is what the
  capacity gate measures (:mod:`app.strategy.gates`).
* **Predictions** (for the IC). At each rebalance where every ticker has a score and a later
  rebalance (or the window's last day) exists, each ticker's score is paired with its return
  from this rebalance to the next: one prediction per ticker.

Bit-identical for identical inputs; no clock, no I/O, no randomness.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.marketdata import Bar, MarketDataError, normalise_ticker

LANGUAGE = "strategy-v1"
SIGNALS = ("momentum", "mean_reversion", "low_volatility")
MAX_UNIVERSE = 50
MAX_LOOKBACK = 250
MAX_REBALANCE_EVERY = 63
#: A book a hundred times smaller than its capital is not a strategy (red-team, cycle 46).
MIN_GROSS = 0.01
#: Trailing shared days behind each trade's volatility and dollar volume (the capacity gate).
IMPACT_WINDOW = 20


class StrategyRule(BaseModel):
    """One strategy-v1 rule. Unknown fields are refused, so a rule means exactly what it says."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    language: Literal["strategy-v1"] = LANGUAGE
    universe: list[str] = Field(min_length=2, max_length=MAX_UNIVERSE)
    signal: Literal["momentum", "mean_reversion", "low_volatility"]
    lookback: int = Field(ge=2, le=MAX_LOOKBACK, description="Days of history behind a score.")
    rebalance_every: int = Field(ge=1, le=MAX_REBALANCE_EVERY, description="Days between rebalances.")
    top_n: int = Field(ge=1, le=MAX_UNIVERSE, description="Names held long (and short, for long_short).")
    side: Literal["long_only", "long_short"] = "long_only"
    gross: float = Field(default=1.0, ge=MIN_GROSS, le=2.0, description="Sum of absolute weights.")

    @field_validator("universe")
    @classmethod
    def _tickers(cls, universe: list[str]) -> list[str]:
        try:
            tickers = [normalise_ticker(t) for t in universe]
        except MarketDataError as exc:
            raise ValueError(str(exc)) from None
        if any(t in {".", ".."} or "/" in t for t in tickers):
            raise ValueError("a ticker is a symbol, not a path")
        if len(set(tickers)) != len(tickers):
            raise ValueError("the universe lists a ticker twice")
        return sorted(tickers)

    @model_validator(mode="after")
    def _legs_fit(self) -> StrategyRule:
        legs = 2 if self.side == "long_short" else 1
        if legs * self.top_n > len(self.universe):
            raise ValueError(f"top_n={self.top_n} needs at least {legs * self.top_n} tickers")
        return self


@dataclass(frozen=True)
class Prediction:
    """One rebalance's scores paired with what each ticker did until the next rebalance."""

    day: date
    scores: tuple[float, ...]
    forward: tuple[float, ...]


@dataclass(frozen=True)
class Evaluation:
    """What a rule did over a window. ``returns[i]`` was earned on ``days[i]``, net of fees."""

    rule: StrategyRule
    start: date
    end: date
    days: tuple[date, ...]
    returns: tuple[float, ...]
    gross_returns: tuple[float, ...]
    predictions: tuple[Prediction, ...]
    turnover: float
    rebalances: int
    #: ``Σ σ |Δw|^1.5 / sqrt(dollar volume)`` over every trade, per return day: the strategy's
    #: square-root impact per sqrt-dollar of capital (see :func:`app.strategy.gates.capacity`).
    impact_per_sqrt_dollar: float
    warnings: tuple[str, ...] = field(default=())


class EvaluationError(ValueError):
    """The bars cannot carry the rule over the window (a ticker missing, too few shared days)."""


def _shared_calendar(rule: StrategyRule, bars: Mapping[str, Sequence[Bar]]) -> list[date]:
    missing = [t for t in rule.universe if not bars.get(t)]
    if missing:
        raise EvaluationError(f"no bars for {', '.join(missing)}")
    days: set[date] | None = None
    for ticker in rule.universe:
        own = {b.ts.date() for b in bars[ticker]}
        days = own if days is None else days & own
    return sorted(days or ())


def _std(xs: Sequence[float]) -> float:
    n = len(xs)
    mean = sum(xs) / n
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0


def _score(rule: StrategyRule, close: Mapping[date, float], calendar: Sequence[date],
           i: int) -> float | None:
    """The rule's score for one ticker on ``calendar[i]``, from closes up to that day only."""
    if i < rule.lookback:
        return None
    if rule.signal == "low_volatility":
        closes = [close[calendar[j]] for j in range(i - rule.lookback, i + 1)]
        return -_std([b / a - 1.0 for a, b in zip(closes, closes[1:])])
    change = close[calendar[i]] / close[calendar[i - rule.lookback]] - 1.0
    return change if rule.signal == "momentum" else -change


def _targets(rule: StrategyRule, scores: Mapping[str, float]) -> dict[str, float]:
    """The weights a rebalance sets from a full set of scores (ties broken by ticker name)."""
    ranked = sorted(rule.universe, key=lambda t: (-scores[t], t))
    weights = dict.fromkeys(rule.universe, 0.0)
    if rule.side == "long_only":
        for t in ranked[: rule.top_n]:
            weights[t] = rule.gross / rule.top_n
    else:
        leg = rule.gross / (2 * rule.top_n)
        for t in ranked[: rule.top_n]:
            weights[t] = leg
        for t in ranked[-rule.top_n :]:
            weights[t] = -leg
    return weights


def evaluate(
    rule: StrategyRule,
    bars: Mapping[str, Sequence[Bar]],
    *,
    start: date,
    end: date,
    fee_rate: float,
) -> Evaluation:
    """Run ``rule`` over the decision days in ``[start, end)``. ``bars`` may hold earlier days
    (they feed the scores) and must hold every ticker of the universe; later days are ignored."""
    if not start < end:
        raise EvaluationError("the window is empty: start must be before end")
    calendar = [d for d in _shared_calendar(rule, bars) if d < end]
    close: dict[str, dict[date, float]] = {}
    dollar_volume: dict[str, dict[date, float]] = {}
    for ticker in rule.universe:
        close[ticker] = {b.ts.date(): b.close for b in bars[ticker]}
        dollar_volume[ticker] = {b.ts.date(): b.close * b.volume for b in bars[ticker]}
    if any(close[t][d] <= 0 or not math.isfinite(close[t][d]) for t in rule.universe for d in calendar):
        raise EvaluationError("a close is not a positive finite price")
    first = next((i for i, d in enumerate(calendar) if d >= start), len(calendar))
    if len(calendar) - first < 2:
        raise EvaluationError(f"fewer than two shared trading days in [{start}, {end})")

    def series(ticker: str, upto: int, length: int) -> list[float]:
        return [close[ticker][calendar[j]] for j in range(upto - length, upto + 1)]

    def score(ticker: str, i: int) -> float | None:
        return _score(rule, close[ticker], calendar, i)

    def targets(scores: dict[str, float]) -> dict[str, float]:
        return _targets(rule, scores)

    def impact(ticker: str, i: int, trade: float) -> float:
        if i < IMPACT_WINDOW:
            return 0.0
        closes = series(ticker, i, IMPACT_WINDOW)
        sigma = _std([b / a - 1.0 for a, b in zip(closes, closes[1:])])
        adv = sum(dollar_volume[ticker][calendar[j]] for j in range(i - IMPACT_WINDOW + 1, i + 1))
        adv /= IMPACT_WINDOW
        return sigma * abs(trade) ** 1.5 / math.sqrt(adv) if adv > 0 else 0.0

    decision = list(range(first, len(calendar)))
    weights = dict.fromkeys(rule.universe, 0.0)
    days: list[date] = []
    net: list[float] = []
    gross: list[float] = []
    rebalance_at: list[int] = []
    scored: dict[int, tuple[float, ...]] = {}
    turnover = 0.0
    impact_sum = 0.0
    for k, i in enumerate(decision[:-1]):
        fee = 0.0
        if k % rule.rebalance_every == 0:
            scores = {t: score(t, i) for t in rule.universe}
            new = (targets(scores) if all(s is not None for s in scores.values())
                   else dict.fromkeys(rule.universe, 0.0))
            if all(s is not None for s in scores.values()):
                scored[i] = tuple(scores[t] for t in rule.universe)
            change = {t: new[t] - weights[t] for t in rule.universe}
            moved = sum(abs(c) for c in change.values())
            turnover += moved
            fee = fee_rate * moved
            impact_sum += sum(impact(t, i, c) for t, c in change.items() if c)
            weights = new
            rebalance_at.append(i)
        nxt = calendar[i + 1]
        r = sum(w * (close[t][nxt] / close[t][calendar[i]] - 1.0) for t, w in weights.items() if w)
        days.append(nxt)
        gross.append(r)
        net.append(r - fee)

    last = decision[-1]
    predictions = []
    for n, i in enumerate(rebalance_at):
        if i not in scored:
            continue
        j = rebalance_at[n + 1] if n + 1 < len(rebalance_at) else last
        if j <= i:
            continue
        forward = tuple(close[t][calendar[j]] / close[t][calendar[i]] - 1.0 for t in rule.universe)
        predictions.append(Prediction(day=calendar[i], scores=scored[i], forward=forward))

    warnings = []
    if not scored:
        warnings.append(f"no rebalance had {rule.lookback} earlier shared days: the book stayed flat")
    return Evaluation(
        rule=rule,
        start=start,
        end=end,
        days=tuple(days),
        returns=tuple(net),
        gross_returns=tuple(gross),
        predictions=tuple(predictions),
        turnover=turnover,
        rebalances=len(rebalance_at),
        impact_per_sqrt_dollar=impact_sum / len(days),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class Holding:
    """What a rule holds going forward: the weights its latest rebalance set (idea: capital follows
    results — a pod trades its rule on days that had not happened when it was judged)."""

    #: The last shared day whose close is known: the day the weights are held from.
    day: date
    #: The decision day of the latest rebalance (``start``'s first shared day, then every
    #: ``rebalance_every`` shared days), whose closes set the weights.
    rebalanced_on: date
    weights: dict[str, float]


def holding(rule: StrategyRule, bars: Mapping[str, Sequence[Bar]], *, start: date) -> Holding:
    """The weights ``rule`` holds after the last shared day of ``bars``, its rebalances counted from
    the first shared day on or after ``start`` — the same law as :func:`evaluate`, whose decision
    days these are. Flat when the latest rebalance had not ``lookback`` earlier shared days."""
    calendar = _shared_calendar(rule, bars)
    first = next((i for i, d in enumerate(calendar) if d >= start), None)
    if first is None:
        raise EvaluationError(f"no shared trading day on or after {start}")
    close = {t: {b.ts.date(): b.close for b in bars[t]} for t in rule.universe}
    if any(close[t][d] <= 0 or not math.isfinite(close[t][d]) for t in rule.universe
           for d in calendar):
        raise EvaluationError("a close is not a positive finite price")
    last = len(calendar) - 1
    at = first + (last - first) // rule.rebalance_every * rule.rebalance_every
    scores = {t: _score(rule, close[t], calendar, at) for t in rule.universe}
    weights = (_targets(rule, scores) if all(s is not None for s in scores.values())
               else dict.fromkeys(rule.universe, 0.0))
    return Holding(day=calendar[last], rebalanced_on=calendar[at], weights=weights)
