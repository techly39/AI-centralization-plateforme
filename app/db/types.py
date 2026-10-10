"""Column types that keep the database's promises about time.

The whole app reads time from one clock, which always returns **timezone-aware
UTC** (TRD principle 5). SQLite has no time zone type: hand it an aware datetime
and it silently stores the wall-clock part and throws the offset away, so the
value you read back is naive. Subtract one from the other and Python raises
``can't subtract offset-naive and offset-aware datetimes`` — in whichever code
path happens to load a row before comparing it, which is a miserable way to find
out.

:class:`UTCDateTime` closes that gap at the boundary: aware UTC in, aware UTC
out, every time, on every table. Anything that survives a round trip through the
database is therefore directly comparable with ``clock.now()``.

Storage is unchanged — the same naive-UTC string SQLAlchemy already wrote — so
existing rows load correctly and no data migration is needed. On Postgres this
maps to ``TIMESTAMP WITH TIME ZONE`` and the conversions become no-ops, which is
the point of doing it here rather than in each caller.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A ``DateTime`` that always hands back an aware UTC value."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # Nobody should be writing naive times — everything goes through the
            # clock — but if something does, treat it as UTC rather than as
            # local time. Guessing the host's zone is how a backtest ends up an
            # hour off in summer.
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(
        self, value: Any, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):  # pragma: no cover - driver-dependent
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
