"""Cost, activity, and performance aggregation (TRD §4, §7).

Where to look:

* :mod:`app.metrics.reporting` — the write side: agents self-report cost and
  work (``POST /costs``, ``/tasks/start``, ``/tasks/end``).
* :mod:`app.metrics.performance` — the statistics, as pure functions.
* :mod:`app.metrics.equity` — rebuilding a pod's daily equity from the ledger.
* :mod:`app.metrics.service` — assembling one pod's metrics and the leaderboard.

Nothing in this package writes derived trading state; it reads the ledger and
the self-reported tables and computes. The one number the whole firm is ranked
on — cost-adjusted P&L — is defined in :mod:`app.metrics.service`.
"""

from app.metrics.equity import DailyCloseCache, EquityCurve, build_equity_curve
from app.metrics.performance import (
    EquityPoint,
    annualise,
    compound,
    daily_returns,
    hit_rate,
    max_drawdown,
    sharpe_daily,
)
from app.metrics.reporting import (
    ReportingError,
    TaskAlreadyEndedError,
    TaskNotFoundError,
    TaskOwnershipError,
    end_task,
    list_costs,
    list_tasks,
    report_cost,
    start_task,
    task_duration_seconds,
)
from app.metrics.service import (
    ActivityMetrics,
    CapitalMetrics,
    CostMetrics,
    PerformanceMetrics,
    PodMetrics,
    SubjectTime,
    compute_leaderboard,
    compute_pod_metrics,
)

__all__ = [
    "ActivityMetrics",
    "CapitalMetrics",
    "CostMetrics",
    "DailyCloseCache",
    "EquityCurve",
    "EquityPoint",
    "PerformanceMetrics",
    "PodMetrics",
    "ReportingError",
    "SubjectTime",
    "TaskAlreadyEndedError",
    "TaskNotFoundError",
    "TaskOwnershipError",
    "annualise",
    "build_equity_curve",
    "compound",
    "compute_leaderboard",
    "compute_pod_metrics",
    "daily_returns",
    "end_task",
    "hit_rate",
    "list_costs",
    "list_tasks",
    "max_drawdown",
    "report_cost",
    "sharpe_daily",
    "start_task",
    "task_duration_seconds",
]
