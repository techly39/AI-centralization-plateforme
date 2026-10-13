"""Assembling the numbers management runs the firm on (TRD §7 "Metrics").

Every field the TRD asks for, and the supporting figures that make each one
readable:

===========================  ==========================================
total return                 time-weighted, so allocations are not "returns"
Sharpe (daily)               plus its annualised form, for context
max drawdown                 deepest fall of the compounded return index
hit rate                     winning closed trades / closed trades
total usd_cost               self-reported by the agents (see reporting.py)
cost-adjusted P&L            P&L − usd_cost: the number that actually ranks pods
time per subject             from the task log, seconds per subject
tasks opened / closed        from the task log
messages sent                from the bus
===========================  ==========================================

**P&L is defined once, economically**: current portfolio value minus the net
capital management put in. It cannot drift from the ledger, because both halves
come from it. Realised and unrealised P&L are reported alongside as a breakdown,
not as a second definition.

The metrics endpoints are management-only (TRD §7), which the API layer enforces
with the same ``read_cross_pod`` right the events endpoint uses. Nothing here
re-derives that rule — this module computes, the router decides who may look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bus.messages import count_messages_sent_by_pod
from app.config import get_settings
from app.db.models import Cost, Order, OrderSide, OrderStatus, Pod, Task
from app.ledger.events import ledger_now
from app.marketdata import MarketDataProvider, get_provider
from app.metrics.equity import DailyCloseCache, build_equity_curve
from app.metrics.metering import AgentMetered, metered_by_agent
from app.metrics.performance import (
    annualise,
    compound,
    daily_returns,
    hit_rate,
    max_drawdown,
    sharpe_daily,
)
from app.oms.money import round_money
from app.oms.portfolio import build_portfolio


# --- Result shapes ----------------------------------------------------------

@dataclass(slots=True)
class CapitalMetrics:
    net_contributed: float
    cash: float
    positions_value: float
    total_value: float


@dataclass(slots=True)
class PerformanceMetrics:
    total_return: float | None
    sharpe_daily: float | None
    sharpe_annualised: float | None
    max_drawdown: float | None
    hit_rate: float | None
    pnl: float
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    closed_trades: int
    winning_trades: int
    #: Daily equity observations the statistics were computed from. One or zero
    #: means "not enough history yet", which is why the ratios above may be null.
    observations: int
    pricing_errors: list[str] = field(default_factory=list)

    @property
    def fully_priced(self) -> bool:
        return not self.pricing_errors


@dataclass(slots=True)
class CostMetrics:
    #: The authoritative figure the pods are ranked on (ADR-041): for a metered
    #: agent its system-reported cost, for an unmetered one its self-reports.
    total_usd_cost: float
    tokens_in: int
    tokens_out: int
    reports: int
    #: Every self-reported ``Cost`` row of the pod, as before metering existed.
    self_reported_usd_cost: float
    #: Metered agents' system-reported cost; ``None`` if no agent of the pod is
    #: metered (unmeasured, not free), ``0.0`` if metered at nothing.
    metered_usd_cost: float | None
    metered_agents: int
    #: Metered agents' self-reports minus their metered cost: how far they were
    #: wrong about themselves. ``None`` if no agent is metered.
    self_report_gap_usd: float | None


@dataclass(slots=True)
class SubjectTime:
    subject: str
    seconds: float
    tasks: int


@dataclass(slots=True)
class ActivityMetrics:
    tasks_opened: int
    tasks_closed: int
    tasks_open: int
    total_task_seconds: float
    time_per_subject: list[SubjectTime]
    messages_sent: int
    orders_placed: int
    orders_filled: int
    orders_rejected: int
    orders_pending: int
    orders_cancelled: int


@dataclass(slots=True)
class PodMetrics:
    pod_id: int
    pod_name: str | None
    as_of: datetime
    capital: CapitalMetrics
    performance: PerformanceMetrics
    cost: CostMetrics
    activity: ActivityMetrics
    #: P&L net of what the agents cost to run — the TRD's headline number.
    cost_adjusted_pnl: float


# --- Computation ------------------------------------------------------------

def compute_pod_metrics(
    session: Session,
    *,
    pod_id: int,
    provider: MarketDataProvider | None = None,
    closes: DailyCloseCache | None = None,
    now: datetime | None = None,
    metered: dict[int, AgentMetered] | None = None,
) -> PodMetrics:
    """Everything the TRD asks for about one pod, valued at the ledger's now.

    One read of now for the whole report (or the caller's, for a ranking): the
    book, the curve and ``as_of`` are one moment (red-team 0009).
    """
    provider = provider or get_provider()
    if now is None:
        now = ledger_now(session)
    settings = get_settings().metrics

    pod = session.get(Pod, pod_id)
    portfolio = build_portfolio(session, pod_id=pod_id, provider=provider, now=now)

    net_contributed = pod.current_allocation if pod is not None else 0.0
    capital = CapitalMetrics(
        net_contributed=round_money(net_contributed),
        cash=portfolio.cash,
        positions_value=portfolio.positions_value,
        total_value=portfolio.total_value,
    )

    curve = build_equity_curve(
        session, pod_id=pod_id, provider=provider, as_of=now, closes=closes
    )
    returns = daily_returns(curve.points)
    daily = sharpe_daily(returns, risk_free_daily=settings.risk_free_daily)

    realized, fees, wins, closed = _trade_stats(session, pod_id)
    pnl = round_money(capital.total_value - capital.net_contributed)

    performance = PerformanceMetrics(
        total_return=compound(returns) if returns else None,
        sharpe_daily=daily,
        sharpe_annualised=annualise(daily, trading_days=settings.trading_days_per_year),
        max_drawdown=max_drawdown(returns),
        hit_rate=hit_rate(wins=wins, closed=closed),
        pnl=pnl,
        realized_pnl=round_money(realized),
        unrealized_pnl=portfolio.unrealized_pnl,
        fees_paid=round_money(fees),
        closed_trades=closed,
        winning_trades=wins,
        observations=len(curve.points),
        pricing_errors=sorted(set(curve.pricing_errors) | set(portfolio.pricing_errors)),
    )

    cost = _cost_metrics(
        session, pod_id, metered if metered is not None else metered_by_agent(session)
    )
    activity = _activity_metrics(session, pod_id)

    return PodMetrics(
        pod_id=pod_id,
        pod_name=pod.name if pod is not None else None,
        as_of=now,
        capital=capital,
        performance=performance,
        cost=cost,
        activity=activity,
        cost_adjusted_pnl=round_money(pnl - cost.total_usd_cost),
    )


def compute_leaderboard(
    session: Session,
    *,
    provider: MarketDataProvider | None = None,
    now: datetime | None = None,
) -> list[PodMetrics]:
    """Every pod, best cost-adjusted P&L first, all valued at one now.

    One shared price cache across the whole ranking, so a firm of ten pods
    holding the same names downloads each history once rather than ten times.
    """
    provider = provider or get_provider()
    if now is None:
        now = ledger_now(session)
    closes = DailyCloseCache(provider)
    pod_ids = session.execute(select(Pod.id).order_by(Pod.id)).scalars().all()
    metered = metered_by_agent(session)   # one fold for the whole ranking
    rows = [
        compute_pod_metrics(
            session, pod_id=pid, provider=provider, closes=closes, now=now, metered=metered
        )
        for pid in pod_ids
    ]
    return sorted(rows, key=lambda m: m.cost_adjusted_pnl, reverse=True)


# --- Inputs -----------------------------------------------------------------

def _trade_stats(session: Session, pod_id: int) -> tuple[float, float, int, int]:
    """``(realised P&L, fees paid, winning closed trades, closed trades)``.

    A "closed trade" is a filled sell: the moment a thesis stopped being an
    opinion and became a number. Buys are not results, so they are not counted
    either way — that is what keeps the hit rate honest for a pod that is still
    holding everything it bought.
    """
    realized = 0.0
    wins = 0
    closed = 0
    fees = 0.0

    rows = session.execute(
        select(Order).where(
            Order.pod_id == pod_id, Order.status == OrderStatus.filled
        )
    ).scalars()
    for order in rows:
        fees += order.fee or 0.0
        if order.side is not OrderSide.sell or order.realized_pnl is None:
            continue
        closed += 1
        realized += order.realized_pnl
        if order.realized_pnl > 0:
            wins += 1

    return realized, fees, wins, closed


def _cost_metrics(session: Session, pod_id: int, metered: dict[int, AgentMetered]) -> CostMetrics:
    # TOTAL, not SUM: SQLite's integer SUM raises on int64 overflow, which made
    # one agent's absurd report a permanent 500 for management (red-team 0001).
    # TOTAL is a float and never raises. It stays exact below 2**53 tokens —
    # ~9e7 max-size reports from one pod; past that the count rounds, it
    # does not crash. (Report *rate* is unbounded today: see BACKLOG.)
    row = session.execute(
        select(
            func.coalesce(func.sum(Cost.usd_cost), 0.0),
            func.total(Cost.tokens_in),
            func.total(Cost.tokens_out),
            func.count(Cost.id),
        ).where(Cost.pod_id == pod_id)
    ).one()
    self_reported = float(row[0])

    # An agent with any metered row is metered (ADR-041): its self-reports leave
    # the authoritative total and stay as the cross-check. Per agent, not per pod.
    in_pod = {aid: m for aid, m in metered.items() if m.pod_id == pod_id}
    metered_usd: float | None = None
    gap: float | None = None
    authoritative = self_reported
    if in_pod:
        metered_usd = sum(m.usd_micros for m in in_pod.values()) / 1_000_000
        theirs = float(
            session.execute(
                select(func.coalesce(func.sum(Cost.usd_cost), 0.0)).where(
                    Cost.pod_id == pod_id, Cost.agent_id.in_(list(in_pod))
                )
            ).scalar_one()
        )
        # Summed directly, never as ``self_reported - theirs``: past ~2e13 dollars of
        # self-report spam a float subtraction loses cents, and a metered agent's
        # reports could then move its colleagues' share (audit c34 WARN 1).
        unmetered = float(
            session.execute(
                select(func.coalesce(func.sum(Cost.usd_cost), 0.0)).where(
                    Cost.pod_id == pod_id, Cost.agent_id.not_in(list(in_pod))
                )
            ).scalar_one()
        )
        authoritative = unmetered + metered_usd
        gap = theirs - metered_usd
    return CostMetrics(
        total_usd_cost=round_money(authoritative),
        tokens_in=int(row[1]),
        tokens_out=int(row[2]),
        reports=int(row[3]),
        self_reported_usd_cost=round_money(self_reported),
        metered_usd_cost=None if metered_usd is None else round_money(metered_usd),
        metered_agents=len(in_pod),
        self_report_gap_usd=None if gap is None else round_money(gap),
    )


def _activity_metrics(session: Session, pod_id: int) -> ActivityMetrics:
    tasks = session.execute(select(Task).where(Task.pod_id == pod_id)).scalars().all()
    closed = [t for t in tasks if t.ended_at is not None]

    per_subject: dict[str, SubjectTime] = {}
    for task in closed:
        seconds = (task.ended_at - task.started_at).total_seconds()
        entry = per_subject.get(task.subject)
        if entry is None:
            per_subject[task.subject] = SubjectTime(
                subject=task.subject, seconds=seconds, tasks=1
            )
        else:
            entry.seconds += seconds
            entry.tasks += 1

    order_counts = dict(
        session.execute(
            select(Order.status, func.count(Order.id))
            .where(Order.pod_id == pod_id)
            .group_by(Order.status)
        ).all()
    )

    return ActivityMetrics(
        tasks_opened=len(tasks),
        tasks_closed=len(closed),
        tasks_open=len(tasks) - len(closed),
        total_task_seconds=round(sum(s.seconds for s in per_subject.values()), 3),
        # Biggest time sink first: the point of this metric is to show where a
        # pod's hours actually went, and that question is answered by the top of
        # the list.
        time_per_subject=sorted(
            (
                SubjectTime(subject=s.subject, seconds=round(s.seconds, 3), tasks=s.tasks)
                for s in per_subject.values()
            ),
            key=lambda s: s.seconds,
            reverse=True,
        ),
        messages_sent=count_messages_sent_by_pod(session, pod_id),
        orders_placed=sum(order_counts.values()),
        orders_filled=order_counts.get(OrderStatus.filled, 0),
        orders_rejected=order_counts.get(OrderStatus.rejected, 0),
        orders_pending=order_counts.get(OrderStatus.pending, 0),
        orders_cancelled=order_counts.get(OrderStatus.cancelled, 0),
    )
