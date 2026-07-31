"""Background jobs (TRD §3: APScheduler).

Phase 1 registers exactly one job: the pending-limit-order sweep. It runs on a
wall-clock timer and only in **live** mode. In backtest mode there is no wall
clock to run on — simulated time moves only when someone calls
``POST /clock/advance``, so Phase 3 will call
:func:`app.oms.monitor.check_pending_orders` from there instead. Same function,
different trigger.

The job opens its own short session (it is not inside a request) and never lets
an exception escape: a scheduler thread that dies takes every future sweep with
it, so failures are logged and the next tick tries again.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from app.clock import get_clock
from app.config import get_settings
from app.db.base import session_scope
from app.oms.monitor import check_pending_orders

_scheduler: BackgroundScheduler | None = None

PENDING_ORDER_JOB_ID = "oms.pending_orders"


def run_pending_order_sweep() -> None:
    """One sweep, with its own session and its own error containment."""
    try:
        with session_scope() as session:
            check_pending_orders(session)
    except Exception as exc:  # noqa: BLE001 - the scheduler thread must survive
        logger.opt(exception=exc).error("pending-order sweep failed")


def start_scheduler() -> BackgroundScheduler | None:
    """Start background jobs if the configuration and clock mode call for them.

    Returns the scheduler, or ``None`` when nothing needed starting (monitor
    disabled, or the clock is not in live mode).
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    if not settings.oms.pending_monitor_enabled:
        logger.info("pending-order monitor disabled by config")
        return None
    if get_clock().mode != "live":
        logger.info(
            "pending-order monitor not started: clock mode is {} — pending orders "
            "are checked on each clock advance instead",
            get_clock().mode,
        )
        return None

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_pending_order_sweep,
        trigger="interval",
        minutes=settings.oms.pending_check_minutes,
        id=PENDING_ORDER_JOB_ID,
        # If the process was busy and ticks piled up, run once, not N times.
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "pending-order monitor started (every {} min)",
        settings.oms.pending_check_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    """Stop background jobs; safe to call when none were started."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("scheduler stopped")
