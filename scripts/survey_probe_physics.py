"""Survey probe: measure what reading the physics code suggested (S-003a, cycle 4).

Each probe turns one suspicion from the code survey into a number, so
``state/SURVEY.md`` says "measured" instead of "I think". A probe *reports*; it
does not assert. Where a probe shows a hole, the fix belongs in a later cycle,
with a real test.

Unlike ``smoke_run.py`` this script imports ``app`` — it inspects the physics
from the inside. It builds its own SQLite file in a temporary directory, and
points ``FUND_DATABASE_URL`` at it *before* the app is imported (the engine is
created at import time), so the Human's ``fund.db`` is never opened.

Usage:
    uv run python scripts/survey_probe_physics.py
"""

from __future__ import annotations

import atexit
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="fund-probe-"))
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
for key in [k for k in os.environ if k.startswith("FUND_")]:
    del os.environ[key]
os.environ["FUND_DATABASE_URL"] = f"sqlite:///{_TMP / 'probe.db'}"
os.environ["FUND_OMS__PENDING_MONITOR_ENABLED"] = "false"
os.environ["FUND_LOGGING__LEVEL"] = "ERROR"
sys.path.insert(0, str(REPO))

from alembic import command  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.clock import LiveClock, set_clock  # noqa: E402
from app.db.base import engine, session_scope  # noqa: E402
from app.db.models import AgentRole, Base, CashBalance, Event, Position  # noqa: E402
from app.ledger.rebuild import rebuild_state  # noqa: E402
from app.main import create_app  # noqa: E402
from app.marketdata import StaticProvider, set_provider  # noqa: E402
from app.metrics.performance import annualise, sharpe_daily  # noqa: E402
from app.registry.pods import create_pod, fund_pod  # noqa: E402
from app.registry.service import get_or_create_system_agent, register_agent  # noqa: E402


class SetClock:
    """A clock the probe moves by hand (the seam Phase 3's backtest clock uses)."""

    mode = "backtest"

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


def report(name: str, finding: str) -> None:
    print(f"[{name}] {finding}")


def probe_migration_drift() -> None:
    """Do the alembic migrations produce the schema the ORM models declare?"""
    command.upgrade(AlembicConfig(str(REPO / "alembic.ini")), "head")
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    report("P1 migration drift", f"{len(diffs)} difference(s) between migrations and models"
           + (": " + "; ".join(str(d)[:120] for d in diffs[:6]) if diffs else ""))


def probe_unledgered_writes() -> None:
    """Which state changes leave no event behind?"""
    with session_scope() as s:
        before = s.scalar(select(func.count(Event.id)))
        create_pod(s, name="probe-pod")
        after_pod = s.scalar(select(func.count(Event.id)))
        get_or_create_system_agent(s)
        after_system = s.scalar(select(func.count(Event.id)))
    report("P2 unledgered writes",
           f"create_pod wrote {after_pod - before} event(s); "
           f"creating the system agent wrote {after_system - after_pod} event(s)")


def probe_replay_order() -> None:
    """Live state is folded in insertion (id) order; rebuild replays in (ts, id) order.

    They agree only while the clock never moves backwards between two events.
    A backtest started after live trading moves it backwards.
    """
    prices = StaticProvider({"AAPL": 100.0})
    set_provider(prices)
    clock = SetClock(datetime(2026, 6, 10, 15, tzinfo=timezone.utc))
    set_clock(clock)
    try:
        with session_scope() as s:
            pod = create_pod(s, name="replay-pod")
            fund_pod(s, pod_id=pod.id, delta=10_000.0,
                     actor=get_or_create_system_agent(s), reason="probe")
            pm, _ = register_agent(s, name="replay-pm", role=AgentRole.pm, pod_id=pod.id)
            pod_id, pm_id = pod.id, pm.id

        from app.db.models import Agent
        from app.oms.service import place_order

        with session_scope() as s:
            place_order(s, actor=s.get(Agent, pm_id), ticker="AAPL", side="buy",
                        qty=10, price_type="market", justification="probe", provider=prices)
        clock.set(datetime(2026, 6, 5, 15, tzinfo=timezone.utc))  # a backtest starts earlier
        with session_scope() as s:
            place_order(s, actor=s.get(Agent, pm_id), ticker="AAPL", side="sell",
                        qty=10, price_type="market", justification="probe", provider=prices)

        with session_scope() as s:
            live_cash = s.get(CashBalance, pod_id).balance
            live_pos = s.get(Position, (pod_id, "AAPL"))
        with session_scope() as s:
            rebuilt = rebuild_state(s)
        rebuilt_cash = rebuilt.cash.get(pod_id)
        rebuilt_pos = rebuilt.positions.get((pod_id, "AAPL"))
        report("P3 replay order",
               f"live cash={live_cash:.2f} pos={'none' if live_pos is None else live_pos.qty}; "
               f"rebuild cash={rebuilt_cash:.2f} pos={'none' if rebuilt_pos is None else rebuilt_pos['qty']}"
               f" -> {'AGREE' if abs(live_cash - rebuilt_cash) < 1e-9 and (live_pos is None) == (rebuilt_pos is None) else 'DISAGREE'}")
    finally:
        set_clock(LiveClock())
        set_provider(None)


def probe_api_edges() -> None:
    """Non-finite limit prices, registering into a missing pod, the clock for non-management."""
    set_provider(StaticProvider({"AAPL": 100.0}))
    try:
        with session_scope() as s:
            admin, admin_key = register_agent(s, name="probe-admin", role=AgentRole.management)
            pod = create_pod(s, name="edge-pod")
            fund_pod(s, pod_id=pod.id, delta=10_000.0,
                     actor=get_or_create_system_agent(s), reason="probe")
            _, pm_key = register_agent(s, name="edge-pm", role=AgentRole.pm, pod_id=pod.id)

        client = TestClient(create_app(), raise_server_exceptions=False)
        pm = {"X-API-Key": pm_key, "Content-Type": "application/json"}
        mgmt = {"X-API-Key": admin_key}

        r = client.post("/orders", headers=pm, content=(
            '{"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "limit", '
            '"limit_price": 1e309, "justification": "probe"}'))
        r_list_pm = client.get("/orders", headers=pm)
        r_list_mgmt = client.get("/orders", headers=mgmt)
        body = r.json() if r.status_code < 500 else {}
        report("P4 limit_price=1e309",
               f"POST /orders -> {r.status_code} (status={body.get('status')}, "
               f"limit_price={body.get('limit_price')!r}, reason={str(body.get('status_reason'))[:60]!r}); "
               f"then GET /orders as PM -> {r_list_pm.status_code}, "
               f"as management -> {r_list_mgmt.status_code}")

        r = client.post("/agents/register", headers=mgmt,
                        json={"name": "ghost-pm", "role": "pm", "pod_id": 999})
        report("P5 register into missing pod", f"POST /agents/register pod_id=999 -> {r.status_code}")

        r = client.post("/agents/register", headers=mgmt,
                        json={"name": "podless-pm", "role": "pm"})
        report("P6 register pm without pod", f"POST /agents/register role=pm, no pod -> {r.status_code}")

        r_pm, r_mgmt = client.get("/clock", headers=pm), client.get("/clock", headers=mgmt)
        report("P7 GET /clock", f"as PM -> {r_pm.status_code}, as management -> {r_mgmt.status_code}")
    finally:
        set_provider(None)


def probe_sharpe_calendar_days() -> None:
    """The equity curve has one point per calendar day; Sharpe is annualised with sqrt(252)."""
    rng = random.Random(4)
    trading = [rng.gauss(0.0005, 0.01) for _ in range(252 * 4)]  # 4 years of trading days
    calendar: list[float] = []
    for i, r in enumerate(trading):
        calendar.append(r)
        if i % 5 == 4:
            calendar.extend([0.0, 0.0])  # weekend: close carried forward, 0% return
    true_ann = annualise(sharpe_daily(trading), trading_days=252)
    app_ann = annualise(sharpe_daily(calendar), trading_days=252)
    report("P8 Sharpe on calendar days",
           f"same returns: trading-day series ann. Sharpe={true_ann:.3f}, "
           f"with weekend zeros (what the curve feeds) ={app_ann:.3f} "
           f"(ratio {app_ann / true_ann:.3f}; sqrt(252/365)={(252 / 365) ** 0.5:.3f}); "
           f"stdev ratio {statistics.stdev(calendar) / statistics.stdev(trading):.3f}")


def probe_mcp_imports() -> None:
    """Does importing the MCP tool module pull the app's database layer in?"""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; import mcp_server.tools; "
         "print(sorted(m for m in sys.modules if m.startswith('app.')))"],
        cwd=REPO, capture_output=True, text=True, env=os.environ.copy(), timeout=60,
    )
    mods = out.stdout.strip() or out.stderr.strip()[-200:]
    report("P9 mcp_server imports", f"app modules loaded by `import mcp_server.tools`: {mods}")


def main() -> int:
    print(f"probe database: {_TMP / 'probe.db'} (deleted on exit)")
    probe_migration_drift()
    probe_unledgered_writes()
    probe_replay_order()
    probe_api_edges()
    probe_sharpe_calendar_days()
    probe_mcp_imports()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
