"""A run's time is a fact of its ledger (ADR-027, TRD §9, B-004 slice a).

**A run is a database.** A live run is any database whose ledger does not open
with ``run_started``; a backtest run is a *fresh* database whose first event is
``run_started {mode: "backtest", start}``. Live and backtest stamps therefore
never share a ledger, so the ADR-025 floor and ``ledger_now`` are per run by
construction — there is no ``run_id`` column a query could forget to filter on.

**Backtest time moves only forward, only by ``clock_advanced``.** The
:class:`~app.clock.BacktestClock` a process runs on is its copy of the latest
``run_started.start`` / ``clock_advanced.to``; :func:`install_run_clock`
rebuilds it from the ledger on every start, so a restart resumes where the run
was. :func:`advance` is the one way to move it: bounded per step
(:data:`~app.limits.MAX_ADVANCE_MINUTES`), never backwards, never past the real
now (the world has no data from the future to show).

Who may advance is a permission (``Action.CONTROL_CLOCK``, never universal);
what an advance does next — the pending-order sweep — is the caller's
(:mod:`app.api.clock`), the same sweep the live scheduler runs on a timer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import BacktestClock, get_clock, set_clock, wall_now
from app.db.models import Base, Event
from app.ledger.events import (
    EVENT_CLOCK_ADVANCED,
    EVENT_RUN_STARTED,
    append_event,
    ledger_now,
)
from app.limits import MAX_ADVANCE_MINUTES
from app.marketdata.base import LIVE_QUOTE_WINDOW
from app.oms.service import OMS_LOCK


#: Does market data refuse anything not known by the simulated now? Yes since
#: B-005 (ADR-028): the guard is in the ``MarketDataProvider`` base. Runs opened
#: before it record ``False`` in their ``run_started``, so no reader mistakes
#: them for honest backtests.
LOOK_AHEAD_GUARD = True

#: How far behind the real now a backtest's clock must stay: within it, a live
#: feed answers with its current quote, which a simulated "earlier" must not see.
#: Strictly: the feed's window is inclusive, so the edge itself is refused
#: (red-team 0008).
_REAL_NOW_MARGIN = LIVE_QUOTE_WINDOW


class RunClockError(Exception):
    """The clock cannot do that in this run (live mode, a bad step, a used DB)."""


def start_backtest(session: Session, *, start: datetime) -> BacktestClock:
    """Open a backtest run in an empty database, its clock at ``start``.

    Refuses a database holding anything at all: a backtest that inherited a
    live ledger would inherit its stamps (the floor) and its agents' history.
    The caller commits.
    """
    if start.tzinfo is None:
        raise RunClockError("start must carry a timezone (use UTC, e.g. ...Z)")
    start = start.astimezone(timezone.utc)
    if start >= wall_now() - _REAL_NOW_MARGIN:
        raise RunClockError(
            "a backtest must start in the past (at least "
            f"{_REAL_NOW_MARGIN.seconds} s ago): the future has no data"
        )
    for table in Base.metadata.sorted_tables:
        if session.scalar(select(func.count()).select_from(table)):
            raise RunClockError(
                f"this database is not empty ({table.name} has rows): a backtest "
                "is its own database — point FUND_DATABASE_URL at a new file"
            )
    clock = BacktestClock(start)
    set_clock(clock)
    append_event(
        session,
        type=EVENT_RUN_STARTED,
        actor_agent_id=None,
        payload={
            "mode": clock.mode,
            "start": _iso(start),
            "look_ahead_guard": LOOK_AHEAD_GUARD,
        },
    )
    return clock


def install_run_clock(session: Session) -> BacktestClock | None:
    """Put this process on its database's clock; ``None`` for a live run.

    A live run leaves the installed clock alone (the default is live; tests
    install their own). A backtest run gets a ``BacktestClock`` at the latest
    ``run_started.start`` / ``clock_advanced.to`` in the ledger.
    """
    first = session.scalar(select(Event).order_by(Event.id).limit(1))
    if first is None or first.type != EVENT_RUN_STARTED:
        return None
    latest = session.scalar(
        select(Event)
        .where(Event.type.in_((EVENT_RUN_STARTED, EVENT_CLOCK_ADVANCED)))
        .order_by(Event.id.desc())
        .limit(1)
    )
    payload = latest.payload_json
    moment = payload["to"] if latest.type == EVENT_CLOCK_ADVANCED else payload["start"]
    clock = BacktestClock(datetime.fromisoformat(moment))
    set_clock(clock)
    return clock


def advance(
    session: Session, *, minutes: int, actor_agent_id: int
) -> tuple[datetime, datetime]:
    """Move a backtest clock ``minutes`` forward and record it; commits.

    Returns ``(from, to)``. Under ``OMS_LOCK``, so no order is priced or filled
    while the world's now is moving.
    """
    clock = get_clock()
    if not isinstance(clock, BacktestClock):
        raise RunClockError(
            f"the clock is in {clock.mode} mode: only a backtest run's clock is "
            "advanced; live time is the world's own"
        )
    if not 0 < minutes <= MAX_ADVANCE_MINUTES:
        raise RunClockError(f"a step is 1..{MAX_ADVANCE_MINUTES} minutes")
    with OMS_LOCK:
        # From the ledger's now, not the copy: another process on this database
        # (an operator command) may have stamped later than this one's clock.
        start = ledger_now(session)
        end = start + timedelta(minutes=minutes)
        if end >= wall_now() - _REAL_NOW_MARGIN:
            raise RunClockError(
                "a backtest cannot pass the real now (less "
                f"{_REAL_NOW_MARGIN.seconds} s): the world has no data from the "
                "future to show"
            )
        previous = clock.now()
        clock.move_to(end)
        try:
            append_event(
                session,
                type=EVENT_CLOCK_ADVANCED,
                actor_agent_id=actor_agent_id,
                payload={"from": _iso(start), "to": _iso(end), "minutes": minutes},
            )
            session.commit()
        except Exception:
            session.rollback()
            clock.move_to(previous)
            raise
    return start, end


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()
