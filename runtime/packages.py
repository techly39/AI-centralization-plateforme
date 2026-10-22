"""The day's data package: what the Runtime hands a mind each morning (idea: the backtest with
real AI agents, "each AI receives a predetermined data package").

A package is built **by the Runtime, through the mind's own key**, from physics' answers at the
world's now: the look-ahead guard holds for it exactly as for any tool call, so no package can
show tomorrow. It is put in the wake's context (the first user message, beside ``me`` and
``input``), so it is part of every request the mind is asked, and so of the request hashes a
cassette records: a replay rebuilds it from the replayed world and must get the same bytes.

Packages are versioned by name; a run records the name it used (cassette ``parameters``).

* ``prices-v1`` — for every ticker of the workflow input's ``universe`` (sorted), the daily bars
  of the last :data:`LOOKBACK_DAYS` days up to today, as rows ``[day, open, high, low, close,
  volume]``. A ticker physics refuses is listed under ``unavailable`` with its status.
* ``headlines-v1`` — ``prices-v1`` and ``headlines``: the world's headlines of today and the
  :data:`HEADLINE_DAYS` ``- 1`` days before (idea: data packages).
* ``company-v1`` — ``prices-v1`` and ``reports``: the latest quarterly report of every ticker of
  the universe published in the last :data:`REPORT_DAYS` days.
* ``everything-v1`` — ``prices-v1`` with both.
  A section is read through the mind's own key, so physics decides it: a mind without the right
  gets ``refused: {section: physics' reason}`` instead (the refusal is physics', 403 and logged).

Boundary law: physics is reached only through :class:`FundClient`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from mcp_server.client import FundAPIError, FundClient

#: Every package a run may name. Adding one is a change a cassette records by name.
PACKAGES = frozenset({"prices-v1", "headlines-v1", "company-v1", "everything-v1"})
#: Each package's sections beyond prices.
SECTIONS: dict[str, tuple[str, ...]] = {
    "prices-v1": (), "headlines-v1": ("headlines",), "company-v1": ("reports",),
    "everything-v1": ("headlines", "reports")}
LOOKBACK_DAYS = 30
HEADLINE_DAYS = 3
REPORT_DAYS = 91
COLUMNS = ("day", "open", "high", "low", "close", "volume")


class PackageError(ValueError):
    """The run asks for a package it cannot have (an unknown name, no universe)."""


def check(name: str, workflow_input: Any) -> list[str]:
    """The universe a run with package ``name`` serves, or :class:`PackageError`. Asked before
    anything is contacted."""
    if name not in PACKAGES:
        raise PackageError(f"no data package named {name!r} (known: {', '.join(sorted(PACKAGES))})")
    universe = workflow_input.get("universe") if isinstance(workflow_input, dict) else None
    if (not isinstance(universe, list) or not universe
            or not all(type(t) is str and t.strip() and t not in {".", ".."} for t in universe)):
        raise PackageError(f"package {name!r} needs the workflow input's `universe`: a list of tickers")
    return sorted(set(universe))


async def build(name: str, client: FundClient, at: str, universe: Sequence[str]) -> dict[str, Any]:
    """The package ``name`` for the day of ``at`` (the world's now, ISO-8601), read as ``client``."""
    if name not in PACKAGES:
        raise PackageError(f"no data package named {name!r}")
    today = date.fromisoformat(at[:10])
    start = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    bars: dict[str, list[list[Any]]] = {}
    unavailable: dict[str, int] = {}
    for ticker in sorted(universe):
        try:
            answer = await client.get(f"/ohlcv/{quote(ticker, safe='')}", start=start, interval="1d")
        except FundAPIError as exc:
            unavailable[ticker] = exc.status_code
            continue
        rows = answer.get("bars") if isinstance(answer, dict) else None
        bars[ticker] = [[str(b.get("ts", ""))[:10], *(b.get(c) for c in COLUMNS[1:])]
                        for b in rows or [] if isinstance(b, dict)]
    package: dict[str, Any] = {"name": name, "day": today.isoformat(), "columns": list(COLUMNS),
                               "bars": bars}
    if unavailable:
        package["unavailable"] = unavailable
    wanted = set(universe)
    for section in SECTIONS[name]:
        path, days = (("/headlines", HEADLINE_DAYS) if section == "headlines"
                      else ("/reports", REPORT_DAYS))
        try:
            answer = await client.get(path, days=days)
        except FundAPIError as exc:
            if exc.status_code == 401:
                raise           # its key is dead: the caller refuses the wake
            package.setdefault("refused", {})[section] = exc.detail
            continue
        found = answer.get(section) if isinstance(answer, dict) else None
        found = [x for x in found or [] if isinstance(x, dict)]
        if section == "reports":
            latest: dict[str, Any] = {}
            for report in found:            # oldest first: the last one standing is the latest
                if report.get("ticker") in wanted:
                    latest[report["ticker"]] = report
            found = [latest[t] for t in sorted(latest)]
        package[section] = found
    return package
