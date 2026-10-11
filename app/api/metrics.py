"""Metrics endpoints (TRD §7) — management only.

The TRD puts these behind ``read_cross_pod``, the same right that gates the
event log: reading how another desk is doing is a management prerogative, and a
PM who could see the leaderboard mid-run would be trading against it rather than
against the market.

Both endpoints reach the market (they value positions and rebuild an equity
curve), so they can be slow on a cold cache and they degrade rather than fail —
a name that cannot be priced shows up in ``pricing_errors`` with the affected
statistics still computed from what could be valued.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import IdPath, LeaderboardOut, LeaderboardRowOut, PodMetricsOut
from app.db.base import get_session
from app.db.models import Agent, Pod
from app.ledger.events import ledger_now
from app.metrics.service import PodMetrics, compute_leaderboard, compute_pod_metrics
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _row(metrics: PodMetrics) -> LeaderboardRowOut:
    return LeaderboardRowOut(
        pod_id=metrics.pod_id,
        pod_name=metrics.pod_name,
        total_value=metrics.capital.total_value,
        pnl=metrics.performance.pnl,
        total_usd_cost=metrics.cost.total_usd_cost,
        cost_adjusted_pnl=metrics.cost_adjusted_pnl,
        total_return=metrics.performance.total_return,
        sharpe_daily=metrics.performance.sharpe_daily,
        max_drawdown=metrics.performance.max_drawdown,
        hit_rate=metrics.performance.hit_rate,
        orders_filled=metrics.activity.orders_filled,
        messages_sent=metrics.activity.messages_sent,
    )


@router.get("/pod/{pod_id}", response_model=PodMetricsOut)
def read_pod_metrics(
    pod_id: IdPath,
    _: Agent = Depends(require(Action.READ_CROSS_POD)),
    session: Session = Depends(get_session),
) -> PodMetricsOut:
    """Performance, cost, and activity for one pod."""
    if session.get(Pod, pod_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no pod with id {pod_id}")
    return PodMetricsOut.model_validate(compute_pod_metrics(session, pod_id=pod_id))


@router.get("/leaderboard", response_model=LeaderboardOut)
def read_leaderboard(
    _: Agent = Depends(require(Action.READ_CROSS_POD)),
    session: Session = Depends(get_session),
) -> LeaderboardOut:
    """Every pod ranked by cost-adjusted P&L — profit net of what it cost to run."""
    rows = [_row(m) for m in compute_leaderboard(session)]
    return LeaderboardOut(as_of=ledger_now(session), rows=rows)
