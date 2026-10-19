"""The allocation algorithm and the drawdown ladder: pure functions of a pod's forward record and the
law (:class:`app.config.CapitalConfig`). No clock, no I/O, no randomness: a reallocation event holds
:func:`reallocate`'s whole input, so anyone can redo it and get the same moves.

**The score** of a pod, on its forward daily returns since its seed (``n`` of them; fewer than
``min_track_days``, or no variation: null, and its capital stays):

* cost-adjusted, risk-adjusted: ``sharpe = (mean - cost per day) / sd × √252``, the cost per day
  being the thinking cost metered since the seed, over ``n`` days, as a share of the pod's equity;
  and how sure that is: ``t = (mean - cost per day) / sd × √n``, the t-statistic of the net mean;
* penalised by correlation with the rest of the book: ``× (1 - ρ)``, ``ρ`` the highest correlation
  of its returns with any **older** live pod's on their shared days (null and no penalty with fewer
  than ``min_track_days`` shared days). Older, because a new pod must bring what the book lacks:
  a copy is penalised, never the original it copies;
* penalised by drawdown: ``× (1 - drawdown / close_at)``.

The **viability** is ``t`` times both penalties (a ``t`` at or below zero is not shrunk).

**The targets.** The firm's equity is the centre's cash plus every live pod's equity; the
algorithm may put ``deploy_share`` of it into pods. A pod with no score keeps its equity; so does
one whose viability is positive but below ``raise_at`` (not yet sure). A pod whose viability is
not positive is taken down toward ``min_pod_usd`` (never below, never up). The pods at or above
``raise_at`` share what is left in proportion to their viability, each at least ``min_pod_usd``.
A raise never takes a pod above ``max_pod_share`` of the firm (a pod already above it is not cut
for that); a halved or reduce-only pod is never raised. One step moves a pod by at most ``+max_raise`` /
``-max_cut`` of its equity, and a move smaller than ``min_move`` of it is not made. Cuts are made
first; raises are paid from the centre's cash and the cuts, the most viable pod first, while the
cash lasts.

**The ladder**: drawdown from the high-water mark of the pod's forward return index (the index
starts at 1 at the seed; a flow of capital is not a gain or a loss), the worst the pod has lived on
any day (:func:`worst_drawdown`). ``halve_at`` → half its capital back to the centre;
``reduce_only_at`` → it may only sell; ``close_at`` → closed. Stages only climb.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.config import CapitalConfig

ANNUALISE = math.sqrt(252)
STAGES = ("active", "halved", "reduce_only", "closed")
#: A pod the ladder has cut is not raised back by the re-weighing (red-team: a strong record would
#: undo half the halving in the very sweep that made it).
NEVER_RAISED = ("halved", "reduce_only")


@dataclass(frozen=True)
class PodTrack:
    """One live pod as the algorithm sees it."""

    pod_id: int
    #: Seniority: the id of the pod's seed event (smaller = older).
    seeded: int
    stage: str
    equity: float
    #: ISO days of the forward returns, and the returns (net of fees, flows taken out).
    days: tuple[str, ...]
    returns: tuple[float, ...]
    #: Thinking cost metered since the seed, USD.
    cost_usd: float
    #: From the high-water mark, a fraction >= 0.
    drawdown: float

    def as_input(self) -> dict[str, Any]:
        return {"pod_id": self.pod_id, "seeded": self.seeded, "stage": self.stage,
                "equity": self.equity, "days": list(self.days), "returns": list(self.returns),
                "cost_usd": self.cost_usd, "drawdown": self.drawdown}

    @classmethod
    def from_input(cls, row: dict[str, Any]) -> PodTrack:
        return cls(pod_id=int(row["pod_id"]), seeded=int(row["seeded"]), stage=str(row["stage"]),
                   equity=float(row["equity"]), days=tuple(row["days"]),
                   returns=tuple(float(r) for r in row["returns"]),
                   cost_usd=float(row["cost_usd"]), drawdown=float(row["drawdown"]))


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _sd(xs: Sequence[float]) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def _correlation(mine: PodTrack, older: Sequence[PodTrack], law: CapitalConfig
                 ) -> tuple[int | None, float | None]:
    """The older pod this one moves most like, and how much (null: too few shared days)."""
    best: tuple[int | None, float | None] = (None, None)
    own = dict(zip(mine.days, mine.returns))
    for other in older:
        theirs = dict(zip(other.days, other.returns))
        shared = sorted(set(own) & set(theirs))
        if len(shared) < law.min_track_days:
            continue
        rho = _pearson([own[d] for d in shared], [theirs[d] for d in shared])
        if rho is not None and (best[1] is None or rho > best[1]):
            best = (other.pod_id, rho)
    return best


def score(pod: PodTrack, older: Sequence[PodTrack], law: CapitalConfig) -> dict[str, Any]:
    """The pod's score row: every number behind its viability (null where there is too little)."""
    n = len(pod.returns)
    row: dict[str, Any] = {"pod_id": pod.pod_id, "days": n, "mean": None, "sd": None,
                           "cost_per_day": None, "sharpe": None, "corr_with": None, "corr": None,
                           "drawdown": pod.drawdown, "viability": None}
    if n < law.min_track_days:
        row["note"] = f"fewer than {law.min_track_days} forward days: no score, capital stays"
        return row
    mean, sd = _mean(pod.returns), _sd(pod.returns)
    row["mean"], row["sd"] = mean, sd
    if sd <= 0 or pod.equity <= 0:
        row["note"] = "no variation in its returns: no score, capital stays"
        return row
    cost_per_day = pod.cost_usd / n / pod.equity
    sharpe = (mean - cost_per_day) / sd * ANNUALISE
    t = (mean - cost_per_day) / sd * math.sqrt(n)
    corr_with, corr = _correlation(pod, older, law)
    corr_factor = 1.0 - max(corr or 0.0, 0.0)
    dd_factor = max(0.0, 1.0 - pod.drawdown / law.close_at)
    viability = t * corr_factor * dd_factor if t > 0 else t
    row.update(cost_per_day=cost_per_day, sharpe=sharpe, t=t, corr_with=corr_with, corr=corr,
               corr_factor=corr_factor, dd_factor=dd_factor, viability=viability)
    return row


def reallocate(pods: Sequence[PodTrack], *, centre_cash: float, law: CapitalConfig
               ) -> dict[str, Any]:
    """Every live pod's score, target and move. ``move`` > 0 is paid by the centre, < 0 goes back."""
    live = sorted(pods, key=lambda p: p.seeded)
    rows = {p.pod_id: score(p, live[:k], law) for k, p in enumerate(live)}
    equity = {p.pod_id: p.equity for p in live}
    firm = centre_cash + sum(equity.values())
    pool = law.deploy_share * firm

    target: dict[int, float] = {}
    positive: dict[int, float] = {}
    for p in live:
        v = rows[p.pod_id]["viability"]
        if v is None or 0 < v < law.raise_at:
            target[p.pod_id] = p.equity
        elif v <= 0:
            target[p.pod_id] = min(p.equity, max(law.min_pod_usd, 0.0))
        else:
            positive[p.pod_id] = v
    rest = pool - sum(target.values())
    total = sum(positive.values())
    for pod_id, v in positive.items():
        target[pod_id] = max(law.min_pod_usd, v / total * rest if rest > 0 else 0.0)

    moves: dict[int, float] = {}
    for p in live:
        t = target[p.pod_id]
        if t > p.equity:
            t = min(t, max(p.equity, law.max_pod_share * firm))
            if p.stage in NEVER_RAISED:
                t = p.equity
        t = min(max(t, p.equity * (1.0 - law.max_cut)), p.equity * (1.0 + law.max_raise))
        move = t - p.equity
        moves[p.pod_id] = 0.0 if abs(move) < law.min_move * p.equity else move

    cash = centre_cash + sum(-m for m in moves.values() if m < 0)
    raises = sorted((p for p in live if moves[p.pod_id] > 0),
                    key=lambda p: (-rows[p.pod_id]["viability"], p.seeded))
    for p in raises:
        paid = min(moves[p.pod_id], max(cash, 0.0))
        if paid < law.min_move * p.equity:
            paid = 0.0
        moves[p.pod_id] = paid
        cash -= paid

    out = []
    for p in live:
        row = rows[p.pod_id]
        row.update(equity=p.equity, target=target[p.pod_id], move=moves[p.pod_id])
        out.append(row)
    return {"firm_equity": firm, "centre_cash": centre_cash, "pool": pool, "pods": out}


# --- the drawdown ladder --------------------------------------------------------------------------

def drawdown(returns: Sequence[float]) -> tuple[float, float, float]:
    """``(index, high-water mark, drawdown)`` of the return index that starts at 1."""
    index = peak = 1.0
    for r in returns:
        index *= 1.0 + r
        peak = max(peak, index)
    return index, peak, (1.0 - index / peak) if peak > 0 else 0.0


def worst_drawdown(returns: Sequence[float]) -> float:
    """The deepest fall from the high-water mark the return index lived through, on any day."""
    index = peak = 1.0
    worst = 0.0
    for r in returns:
        index *= 1.0 + r
        peak = max(peak, index)
        if peak > 0:
            worst = max(worst, 1.0 - index / peak)
    return worst


def stage_for(dd: float, law: CapitalConfig) -> str:
    """The ladder's stage for a drawdown alone."""
    if dd >= law.close_at:
        return "closed"
    if dd >= law.reduce_only_at:
        return "reduce_only"
    if dd >= law.halve_at:
        return "halved"
    return "active"


def climb(current: str, dd: float, law: CapitalConfig) -> str:
    """The pod's next stage: stages only climb."""
    return max(current, stage_for(dd, law), key=STAGES.index)
