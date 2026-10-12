"""The Phase 3 milestone probe (B-004c, ADR-030): one scripted pod lives a month, twice.

TRD Phase 3's milestone is "a 1-month backtest in under 10 minutes"; the Era I
exit criterion is "one pod runs end-to-end". This is the first time both happen,
and the first **determinism test**: the same world, run twice in two fresh
databases, must leave the same ledger behind — event for event, stamp for stamp,
payload for payload — and the same equity curve.

The pod is scripted, not an LLM: a moving-average rule that only speaks HTTP
(``/clock``, ``/ohlcv``, ``/price``, ``/portfolio``, ``POST /orders``), the way a
real agent would. Management advances the clock one day per step. Nothing reads
the network: the market is a :class:`~app.marketdata.SyntheticProvider`.

What the test must not be is vacuous, so it also proves the pod really traded,
the curve really moved, and another world key gives another month.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.clock import LiveClock, set_clock
from app.config import get_settings
from app.db.base import get_session
from app.db.models import AgentRole, Base, CashBalance, Event, Position
from app.ledger.events import EVENT_CLOCK_ADVANCED, EVENT_ORDER_FILLED
from app.ledger.rebuild import rebuild_state
from app.main import create_app
from app.marketdata import SyntheticProvider, set_provider
from app.registry import halt
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import start_backtest
from tests.support import world_key

START = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
DAYS = 31
SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0, "SYNC": 20.0}
CAPITAL = 100_000.0
#: TRD Phase 3: a 1-month backtest in under 10 minutes.
BUDGET_SECONDS = 600


@dataclass
class ProbeRun:
    curve: list[tuple[str, float]]
    ledger: list[tuple]
    derived: tuple
    metrics: dict
    seconds: float


def _fresh_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class ScriptedPM:
    """A PM with no model: 5-day vs 20-day average, one third of the book per name."""

    def __init__(self, client: TestClient, key: str, pod_id: int) -> None:
        self.client, self.headers, self.pod_id = client, {"X-API-Key": key}, pod_id

    def get(self, path: str, **params):
        resp = self.client.get(path, headers=self.headers, params=params)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def portfolio(self) -> dict:
        return self.get(f"/portfolio/{self.pod_id}")

    def act(self) -> None:
        book = self.portfolio()
        held = {p["ticker"]: p["qty"] for p in book["positions"]}
        sleeve = book["total_value"] / len(SYMBOLS)
        for ticker in SYMBOLS:
            closes = [b["close"] for b in self.get(f"/ohlcv/{ticker}", interval="1d")["bars"]]
            fast, slow = sum(closes[-5:]) / 5, sum(closes[-20:]) / 20
            price = self.get(f"/price/{ticker}")["price"]
            if fast > slow and not held.get(ticker):
                qty = math.floor(min(sleeve, self.portfolio()["cash"]) * 0.99 / price)
                if qty:
                    self.order(ticker, "buy", qty, f"5d avg {fast:.2f} > 20d avg {slow:.2f}")
            elif fast < slow and held.get(ticker):
                self.order(ticker, "sell", held[ticker], f"5d avg {fast:.2f} < 20d avg {slow:.2f}")

    def order(self, ticker: str, side: str, qty: float, why: str) -> None:
        resp = self.client.post("/orders", headers=self.headers, json={
            "ticker": ticker, "side": side, "qty": qty, "price_type": "market",
            "justification": why,
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "filled", resp.json()


def run_month(world: int) -> ProbeRun:
    """A fresh database, a fresh copy of test world ``world``, one scripted pod, 31 days."""
    began = time.perf_counter()
    _, Sessions = _fresh_database()
    # The world first: the run records it and is served only in it (B-037).
    set_provider(SyntheticProvider(world_key(world), SYMBOLS))
    session = Sessions()
    try:
        start_backtest(session, start=START)
        _, admin = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="probe-desk")
        fund_pod(session, pod_id=pod.id, delta=CAPITAL,
                 actor=get_or_create_system_agent(session), reason="probe capital")
        _, pm_key = register_agent(session, name="pm-probe", role=AgentRole.pm, pod_id=pod.id)
        session.commit()
        pod_id = pod.id
    finally:
        session.close()

    app = create_app()

    def _session():
        s = Sessions()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    curve: list[tuple[str, float]] = []
    with TestClient(app) as client:
        pm = ScriptedPM(client, pm_key, pod_id)
        for _ in range(DAYS):
            pm.act()
            book = pm.portfolio()
            assert book["fully_priced"], book
            curve.append((book["as_of"], book["total_value"]))
            resp = client.post("/clock/advance", headers={"X-API-Key": admin},
                               json={"days": 1})
            assert resp.status_code == 200, resp.text
        management = ScriptedPM(client, admin, pod_id)  # metrics are management's view
        metrics = management.get(f"/metrics/pod/{pod_id}")

    session = Sessions()
    try:
        ledger = [
            (e.id, e.ts.isoformat(), e.actor_agent_id, e.type, e.payload_json)
            for e in session.execute(select(Event).order_by(Event.id)).scalars()
        ]
        live = _derived(session)
        rebuild_state(session)
        assert _derived(session) == live, "the ledger does not rebuild the book"
        session.rollback()
    finally:
        session.close()
    return ProbeRun(curve, ledger, live, metrics, time.perf_counter() - began)


def _derived(session) -> tuple:
    cash = sorted((c.pod_id, c.balance) for c in session.execute(select(CashBalance)).scalars())
    positions = sorted(
        (p.pod_id, p.ticker, p.qty, p.avg_cost)
        for p in session.execute(select(Position)).scalars()
    )
    return cash, positions


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """World 11 twice, world 12 once — each in its own fresh database.

    Module-scoped (three months of trading, once), so it owns what the autouse
    per-test fixtures would otherwise: the halt file and the background jobs.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(halt, "HALT_FILE", tmp_path_factory.mktemp("probe") / "HALT")
        mp.setattr(get_settings().oms, "pending_monitor_enabled", False)
        try:
            yield {"a": run_month(11), "b": run_month(11), "other": run_month(12)}
        finally:
            set_provider(None)
            set_clock(LiveClock())


def test_the_month_ran_end_to_end_in_time(runs):
    run = runs["a"]
    assert len(run.curve) == DAYS
    stamps = [datetime.fromisoformat(ts) for ts, _ in run.curve]
    assert stamps == [START + timedelta(days=d) for d in range(DAYS)]
    advances = [e for e in run.ledger if e[3] == EVENT_CLOCK_ADVANCED]
    assert len(advances) == DAYS
    assert run.seconds < BUDGET_SECONDS, f"a month took {run.seconds:.1f} s"


def test_the_pod_really_traded_and_the_curve_really_moved(runs):
    run = runs["a"]
    fills = [e for e in run.ledger if e[3] == EVENT_ORDER_FILLED]
    sides = {e[4]["side"] for e in fills}
    assert len(fills) >= 3 and sides == {"buy", "sell"}, [e[4] for e in fills]
    values = {v for _, v in run.curve}
    assert len(values) > DAYS // 2
    assert run.metrics["activity"]["orders_filled"] == len(fills)
    assert run.metrics["performance"]["fees_paid"] > 0


def test_the_same_world_twice_leaves_the_same_ledger(runs):
    a, b = runs["a"], runs["b"]
    assert len(a.ledger) == len(b.ledger)
    for x, y in zip(a.ledger, b.ledger):
        assert x == y, f"first divergence at event {x[0]}:\n{x}\n{y}"


def test_the_same_world_twice_gives_the_same_curve_and_book(runs):
    a, b = runs["a"], runs["b"]
    assert a.curve == b.curve
    assert a.derived == b.derived
    assert a.metrics == b.metrics


def test_another_world_is_another_month(runs):
    assert runs["other"].curve != runs["a"].curve
    assert runs["other"].ledger != runs["a"].ledger
