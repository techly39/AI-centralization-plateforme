"""Time service — the single source of "now" for the whole app (TRD §9).

Every component (ledger, OMS, scheduler, metrics, market data) must read time
from here and never from ``datetime.now()`` directly. Phase 0 ships **live mode
only**; the ``Clock`` interface is shaped so a ``BacktestClock`` can be dropped in
during Phase 3 without touching callers.
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


# Process-wide clock instance. Later phases swap this via ``set_clock`` when the
# operator flips to backtest mode; callers always go through ``get_clock``.
_clock: Clock = LiveClock()


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock
