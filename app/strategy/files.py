"""Bars as a file: the plain JSON a strategy can be rerun on outside any database or feed.

The rows are the ``prices-v1`` package's (``[day, open, high, low, close, volume]``), so a day's
data package, an exported history or a made-up world are all the same file:
``{"SYNA": [["2024-01-02", 100.0, 101.0, 99.0, 100.5, 120000.0], ...], ...}``, or a whole package
(``{"name": "prices-v1", "bars": {...}}``).
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, time
from pathlib import Path

from app.marketdata import Bar

MAX_BARS_FILE_BYTES = 64 * 1024 * 1024


class BarsFileError(ValueError):
    """The file is not a bars document."""


def read_bars(path: Path) -> dict[str, list[Bar]]:
    if path.stat().st_size > MAX_BARS_FILE_BYTES:
        raise BarsFileError(f"{path}: larger than {MAX_BARS_FILE_BYTES} bytes")
    try:
        doc = json.loads(path.read_text())
    except ValueError as exc:
        raise BarsFileError(f"{path}: not JSON ({exc})") from None
    if isinstance(doc, dict) and isinstance(doc.get("bars"), dict):
        doc = doc["bars"]
    if not isinstance(doc, dict) or not doc:
        raise BarsFileError(f"{path}: wants {{ticker: [[day, open, high, low, close, volume], ...]}}")
    out: dict[str, list[Bar]] = {}
    for ticker, rows in doc.items():
        if not isinstance(rows, list):
            raise BarsFileError(f"{path}: {ticker!r} is not a list of rows")
        bars = []
        for row in rows:
            if (not isinstance(row, list) or len(row) != 6 or not isinstance(row[0], str)
                    or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                               and math.isfinite(x) for x in row[1:])):
                raise BarsFileError(f"{path}: {ticker!r} has a row that is not "
                                    "[day, open, high, low, close, volume]")
            day = date.fromisoformat(row[0][:10])
            bars.append(Bar(ts=datetime.combine(day, time(), UTC), open=float(row[1]),
                            high=float(row[2]), low=float(row[3]), close=float(row[4]),
                            volume=float(row[5])))
        if len({b.ts for b in bars}) != len(bars):
            raise BarsFileError(f"{path}: {ticker!r} has two rows for one day")
        out[ticker.strip().upper()] = sorted(bars, key=lambda b: b.ts)
    return out
