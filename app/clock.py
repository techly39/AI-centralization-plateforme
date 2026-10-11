"""Time service — the single source of "now" for the whole app (TRD §9).

Every component (ledger, OMS, scheduler, metrics, market data) must read time
from here and never from ``datetime.now()`` directly. Two clocks exist:

* :class:`LiveClock` — real wall-clock time, the default for every process;
* :class:`BacktestClock` — a simulated now that only moves when told to.

Which one a process runs on is a fact of its database, not a setting
(ADR-027): :mod:`app.run_clock` installs a ``BacktestClock`` when the ledger
starts with ``run_started`` and moves it only through ``clock_advanced``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """A time source. Implementations decide what "now" means."""

    mode: str

    def now(self) -> datetime:
        """Current time as a timezone-aware UTC datetime."""
        ...


class LiveClock:
    """Wraps real wall-clock time in UTC."""

    mode = "live"

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class BacktestClock:
    """A simulated now. Only :mod:`app.run_clock` moves it, and only forward.

    It holds no history of its own: the ledger's ``run_started`` and
    ``clock_advanced`` events are the truth, and this object is the process's
    copy of their latest value (rebuilt from them on every start).
    """

    mode = "backtest"

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("a backtest clock needs a timezone-aware UTC time")
        self._now = now.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def move_to(self, moment: datetime) -> None:
        self._now = moment


def wall_now() -> datetime:
    """The real now, whatever clock is installed.

    For one purpose only: a backtest may not run past it, because the world
    has no data from the future to show (ADR-027). Never a stamp, never a price.
    """
    return LiveClock().now()


# Process-wide clock instance, swapped via ``set_clock`` when a backtest run is
# installed; callers always go through ``get_clock``.
_clock: Clock = LiveClock()


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock
