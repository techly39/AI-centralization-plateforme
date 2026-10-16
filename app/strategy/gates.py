"""The validation gates: physics' verdict on a strategy's held-out record (idea: validation gates
before capital). Pure functions of an :class:`~app.strategy.rule.Evaluation`, the pod's attempt
count, the other pods' return streams and the law (:class:`app.config.GatesConfig`).

Each gate answers ``pass``, ``fail`` or ``null`` (not enough history to say: null, not 0), with its
number and its threshold, so the Human can read why:

* **ic** — mean Spearman rank IC between the rule's scores and each ticker's return until the next
  rebalance, over every rebalance; passes when the mean is at least ``min_ic`` *and* there are at
  least ``min_predictions`` predictions (IC 3 % on a handful of calls is luck, not skill).
* **deflated_sharpe** — Bailey & López de Prado (2014). The benchmark is the Sharpe the best of
  ``N`` luckless strategies would show over the same ``T`` days, ``SR0 = E[max of N standard
  normals] / sqrt(T)`` (each try's Sharpe treated as an independent estimate of zero, variance
  ``1/T``); the gate is the probability, correcting for skew and fat tails, that the true Sharpe
  is above it. ``N`` is every research backtest and every pitch the pod ever made, so attempts
  cannot be hidden. ``N = 1`` gives ``SR0 = 0`` (the plain probabilistic Sharpe).
* **capacity** — square-root impact: a trade of ``|Δw| C`` dollars in a name with daily volatility
  ``σ`` and average daily dollar volume ``V`` costs ``k σ sqrt(|Δw| C / V)`` of what it trades, so
  the daily cost is ``sqrt(C) · A`` (``A`` from the evaluation); the capacity is the capital
  ``C`` at which that cost eats ``capacity_edge_share`` of the mean daily net return. No edge:
  capacity 0. No trade: null.
* **correlation** — the highest Pearson correlation of daily returns with any other pod's latest
  pitch on the shared days. No other pod (or too few shared days): null, which does not block.

Eligible = ic, deflated_sharpe and capacity pass and correlation does not fail.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import NormalDist
from typing import Any

from app.config import GatesConfig
from app.strategy.rule import Evaluation

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def _finite(x: float | None) -> float | None:
    return x if x is not None and math.isfinite(x) else None


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: Sequence[float]) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _ranks(xs: Sequence[float]) -> list[float]:
    """Average ranks (ties share the mean of their positions)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0
        i = j + 1
    return ranks


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = _mean(xs), _mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return _finite(sxy / math.sqrt(sxx * syy))


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    return pearson(_ranks(xs), _ranks(ys))


def expected_max_normal(n: int) -> float:
    """E[max of n independent standard normals], the Bailey–López de Prado approximation."""
    if n <= 1:
        return 0.0
    return ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n)
            + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * math.e)))


def performance(evaluation: Evaluation) -> dict[str, Any]:
    """The plain numbers of a window: what a research backtest answers. Null when too short."""
    r = evaluation.returns
    days = evaluation.days
    out: dict[str, Any] = {
        "start": evaluation.start.isoformat(),
        "end": evaluation.end.isoformat(),
        "days": len(r),
        "rebalances": evaluation.rebalances,
        "turnover": evaluation.turnover,
        "total_return": None,
        "annual_return": None,
        "annual_volatility": None,
        "sharpe": None,
        "max_drawdown": None,
        "mean_ic": None,
        "ic_t_stat": None,
        "predictions": 0,
        "warnings": list(evaluation.warnings),
    }
    if r:
        equity, peak, worst = 1.0, 1.0, 0.0
        for x in r:
            equity *= 1.0 + x
            peak = max(peak, equity)
            worst = min(worst, equity / peak - 1.0)
        out["total_return"] = _finite(equity - 1.0)
        out["max_drawdown"] = _finite(worst)
    span_years = ((days[-1] - days[0]).days + 1) / 365.25 if days else 0.0
    if len(r) >= 2 and span_years > 0:
        per_year = len(r) / span_years
        sd = _std(r)
        out["annual_return"] = _finite(_mean(r) * per_year)
        out["annual_volatility"] = _finite(sd * math.sqrt(per_year))
        if sd > 0:
            out["sharpe"] = _finite(_mean(r) / sd * math.sqrt(per_year))
    ics, count = _ics(evaluation)
    out["predictions"] = count
    if ics:
        out["mean_ic"] = _finite(_mean(ics))
        if len(ics) >= 2 and _std(ics) > 0:
            out["ic_t_stat"] = _finite(_mean(ics) / (_std(ics) / math.sqrt(len(ics))))
    return out


def _ics(evaluation: Evaluation) -> tuple[list[float], int]:
    ics: list[float] = []
    count = 0
    for p in evaluation.predictions:
        ic = spearman(p.scores, p.forward)
        if ic is not None:
            ics.append(ic)
            count += len(p.scores)
    return ics, count


def _row(gate: str, result: str, value: float | None, threshold: float | None, **detail: Any
         ) -> dict[str, Any]:
    return {"gate": gate, "result": result, "value": _finite(value), "threshold": threshold,
            **detail}


def ic_gate(evaluation: Evaluation, law: GatesConfig) -> dict[str, Any]:
    ics, count = _ics(evaluation)
    if not ics:
        return _row("ic", "null", None, law.min_ic, predictions=0,
                    min_predictions=law.min_predictions)
    mean_ic = _mean(ics)
    ok = mean_ic >= law.min_ic and count >= law.min_predictions
    return _row("ic", "pass" if ok else "fail", mean_ic, law.min_ic, predictions=count,
                min_predictions=law.min_predictions, rebalances=len(ics))


def deflated_sharpe(returns: Sequence[float], attempts: int) -> dict[str, float] | None:
    """The deflated Sharpe ratio of a daily return series after ``attempts`` tries, or None."""
    t = len(returns)
    if t < 3:
        return None
    m = _mean(returns)
    var = sum((x - m) ** 2 for x in returns) / t
    if var <= 0:
        return None
    sd = math.sqrt(var)
    # Moments of the standardised series: scale-free, so tiny returns cannot underflow them to 0/0.
    z = [(x - m) / sd for x in returns]
    skew = sum(v**3 for v in z) / t
    kurt = sum(v**4 for v in z) / t
    sr = m / _std(returns)
    sr0 = expected_max_normal(attempts) / math.sqrt(t)
    spread = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if spread <= 0:
        return None
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(spread)
    return {"sharpe_daily": sr, "benchmark_daily": sr0, "probability": _N.cdf(z),
            "skew": skew, "kurtosis": kurt}


def dsr_gate(evaluation: Evaluation, attempts: int, law: GatesConfig) -> dict[str, Any]:
    d = (deflated_sharpe(evaluation.returns, attempts)
         if len(evaluation.returns) >= law.min_periods else None)
    if d is None:
        return _row("deflated_sharpe", "null", None, law.min_deflated_sharpe, attempts=attempts,
                    days=len(evaluation.returns), min_periods=law.min_periods)
    return _row("deflated_sharpe", "pass" if d["probability"] >= law.min_deflated_sharpe else "fail",
                d["probability"], law.min_deflated_sharpe, attempts=attempts,
                days=len(evaluation.returns), sharpe_daily=_finite(d["sharpe_daily"]),
                benchmark_daily=_finite(d["benchmark_daily"]))


def capacity_gate(evaluation: Evaluation, law: GatesConfig) -> dict[str, Any]:
    a = law.impact_coefficient * evaluation.impact_per_sqrt_dollar
    r = evaluation.returns
    edge = _mean(r) if r else 0.0
    if a <= 0 or not r:
        return _row("capacity", "null", None, law.min_capacity_usd, edge_daily=_finite(edge))
    capital = 0.0 if edge <= 0 else (law.capacity_edge_share * edge / a) ** 2
    # Judged as the gross exposure that capital carries, not the capital itself: capital scales as
    # 1/gross, so a strategy cannot buy capacity by turning its leverage knob down.
    usd = capital * evaluation.rule.gross
    return _row("capacity", "pass" if usd >= law.min_capacity_usd else "fail", usd,
                law.min_capacity_usd, edge_daily=_finite(edge))


def correlation_gate(evaluation: Evaluation,
                     others: Mapping[str, tuple[Sequence[date], Sequence[float]]],
                     law: GatesConfig) -> dict[str, Any]:
    mine = dict(zip(evaluation.days, evaluation.returns))
    found: dict[str, float | None] = {}
    for name in sorted(others):
        days, returns = others[name]
        theirs = dict(zip(days, returns))
        shared = sorted(set(mine) & set(theirs))
        found[name] = (pearson([mine[d] for d in shared], [theirs[d] for d in shared])
                       if len(shared) >= law.min_periods else None)
    known = {k: v for k, v in found.items() if v is not None}
    if not known:
        return _row("correlation", "null", None, law.max_correlation, against=found)
    worst = max(known.values())
    return _row("correlation", "pass" if worst <= law.max_correlation else "fail", worst,
                law.max_correlation, against=found)


def judge(evaluation: Evaluation, *, attempts: int,
          others: Mapping[str, tuple[Sequence[date], Sequence[float]]],
          law: GatesConfig) -> dict[str, Any]:
    """Every gate's row and the verdict. ``attempts`` ≥ 1 counts this pitch itself."""
    if attempts < 1:
        raise ValueError("attempts counts this pitch itself: at least 1")
    gates = [ic_gate(evaluation, law), dsr_gate(evaluation, attempts, law),
             capacity_gate(evaluation, law), correlation_gate(evaluation, others, law)]
    by = {g["gate"]: g["result"] for g in gates}
    eligible = (all(by[g] == "pass" for g in ("ic", "deflated_sharpe", "capacity"))
                and by["correlation"] != "fail")
    return {"eligible": eligible, "gates": gates, "performance": performance(evaluation)}
