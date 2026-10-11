"""RED-TEAM 0007 — attacks on the cycle-0015 backtest clock (B-004 slice a, ADR-027).

Claim under attack: a backtest is a fresh database opened by ``run_started``;
its ``BacktestClock`` moves only by ``POST /clock/advance`` (``CONTROL_CLOCK``,
management/system), ``{days, minutes}`` bounded 1 min..366 days, forward from
``ledger_now``, never past the real now, under ``OMS_LOCK``, recorded as
``clock_advanced`` and followed by the pending-order sweep; a restart (lifespan
or CLI) rebuilds the clock from the ledger.

Every attack uses what a firm agent holds (an API key, REST, MCP), plus — where
marked — an interleaving the agent cannot force but can be standing next to (a
management advance landing while its own order is in flight).

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.

Known and NOT reported again: B-005 (market data look-ahead; ADR-027 already
says a backtest is not honest until it lands — the yfinance provider ignores
``as_of``, so a 2024 backtest prices at today's quote).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.clock import BacktestClock, LiveClock, get_clock, set_clock, wall_now
from app.db.models import Agent, AgentRole, Event, Order, OrderStatus
from app.ledger.events import EVENT_CLOCK_ADVANCED, EVENT_RUN_STARTED, ledger_now
from app.marketdata import StaticProvider, set_provider
from app.marketdata.base import Quote, normalise_ticker
from app.oms import monitor
from app.oms.monitor import check_pending_orders
from app.oms.service import OMS_LOCK
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import advance, install_run_clock, start_backtest

START = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)
FUTURE = "2099-01-01T00:00:00+00:00"


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


@pytest.fixture
def backtest(SessionFactory) -> dict:
    """An empty database opened as a backtest at START, seeded with one desk."""
    session = SessionFactory()
    try:
        start_backtest(session, start=START)
        admin, admin_key = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="desk")
        fund_pod(session, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(session), reason="seed")
        pm, pm_key = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
        _, an_key = register_agent(session, name="an", role=AgentRole.analyst, pod_id=pod.id)
        session.commit()
        ids = {"admin_id": admin.id, "pm_id": pm.id, "pod_id": pod.id}
    finally:
        session.close()
    return {"admin": admin_key, "pm": pm_key, "an": an_key, **ids}


@pytest.fixture
def bt_client(backtest, client):
    return client


def _events(db) -> list[Event]:
    db.expire_all()
    return list(db.execute(select(Event).order_by(Event.id)).scalars())


def _advances(db) -> list[Event]:
    return [e for e in _events(db) if e.type == EVENT_CLOCK_ADVANCED]


class StepProvider(StaticProvider):
    """A price that depends on ``as_of``: ``{ticker: [(from_moment, price), ...]}``.

    Honest about time (never serves a price from after ``as_of``), so any
    mismatch between a fill's stamp and its price is the OMS's, not the feed's.
    """

    name = "step-test"

    def __init__(self, steps: dict[str, list[tuple[datetime, float]]]) -> None:
        super().__init__({})
        self.steps = {normalise_ticker(t): sorted(s) for t, s in steps.items()}
        self.on_get = None

    def price_at(self, ticker: str, as_of: datetime) -> float:
        return [p for t, p in self.steps[normalise_ticker(ticker)] if t <= as_of][-1]

    def _quote(self, ticker: str, *, as_of: datetime) -> Quote:
        if self.on_get is not None:
            hook, self.on_get = self.on_get, None
            hook()
        return Quote(ticker=normalise_ticker(ticker), price=self.price_at(ticker, as_of),
                     as_of=as_of, source=self.name)


# =============================================================================
# HELD — who may move time, and how far
# =============================================================================

@pytest.mark.parametrize("who", ["pm", "an"])
@pytest.mark.parametrize("extra", [
    {}, {"X-Role": "management"}, {"X-Agent-Id": "1"}, {"X-Forwarded-For": "127.0.0.1"},
    {"Authorization": "Bearer system"},
])
def test_held_non_management_cannot_advance(bt_client, backtest, db, who, extra):
    before = len(_events(db))
    resp = bt_client.post("/clock/advance", headers={**H(backtest[who]), **extra},
                          json={"days": 1})
    assert resp.status_code == 403
    assert get_clock().now() == START
    assert not _advances(db)
    assert len(_events(db)) == before + 1          # only the permission_denied record


@pytest.mark.parametrize("path", [
    "/clock/advance?days=-1", "/clock/advance/", "/clock//advance", "/Clock/Advance",
])
def test_held_path_variants_neither_bypass_nor_rewind(bt_client, backtest, db, path):
    for who in ("pm", "an"):
        resp = bt_client.post(path, headers=H(backtest[who]), json={"days": 1},
                              follow_redirects=False)
        assert resp.status_code in (307, 403, 404, 405), (path, resp.status_code)
    assert get_clock().now() == START and not _advances(db)


@pytest.mark.parametrize("body", [
    {"days": 10**400}, {"minutes": 2**63}, {"days": 2**53 + 1}, {"days": 1e308},
    {"days": "NaN"}, {"days": "inf"}, {"minutes": -0.5}, {"days": "1e3"}, {"days": "0x1"},
    {"days": None}, {"days": [1]}, {"days": {"$gt": 0}}, {"days": -0.0},
    {"days": 0, "minutes": 0}, {"days": 366, "minutes": 1}, {"minutes": 366 * 1440 + 1},
    {"days": 1, "from": FUTURE}, {"days": 1, "to": FUTURE}, {"days": 1, "previous": FUTURE},
    [1], "1", 1,
])
def test_held_body_tricks_are_422_never_500_and_never_move_time(bt_client, backtest, db, body):
    resp = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json=body)
    assert resp.status_code == 422, (body, resp.status_code, resp.text)
    assert get_clock().now() == START and not _advances(db)


@pytest.mark.parametrize("body,minutes", [
    ({"days": True}, 1440), ({"days": "1"}, 1440), ({"days": 1.0}, 1440),
    ({"minutes": "60"}, 60), ({"days": " 1 "}, 1440), ({"days": "1_0"}, 14400),
])
def test_held_lax_coercions_move_exactly_what_they_say(bt_client, backtest, db, body, minutes):
    """Pydantic lax coercion (accepted policy since red-team 0002): bounded and
    exact — a bool is one day, never an amplifier."""
    resp = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json=body)
    assert resp.status_code == 200, resp.text
    assert get_clock().now() == START + timedelta(minutes=minutes)
    [adv] = _advances(db)
    assert adv.payload_json["minutes"] == minutes


def test_held_maximal_steps_stop_at_the_real_now(SessionFactory, client, db):
    """Management cannot step past today by many maximal steps, nor by one."""
    near = wall_now() - timedelta(days=500)
    session = SessionFactory()
    start_backtest(session, start=near)
    _, admin = register_agent(session, name="management", role=AgentRole.management)
    session.commit()
    session.close()
    codes = [client.post("/clock/advance", headers=H(admin), json={"days": 366}).status_code
             for _ in range(3)]
    assert codes == [200, 409, 409]
    for minutes in (366 * 1440, 200 * 1440, 134 * 1440 + 60 * 24):
        client.post("/clock/advance", headers=H(admin), json={"minutes": minutes})
    assert get_clock().now() <= wall_now()
    assert all(e.ts <= wall_now() for e in _events(db))


def test_held_a_live_run_cannot_be_advanced_by_any_role(client, admin_key, db, frozen_clock):
    resp = client.post("/clock/advance", headers=H(admin_key), json={"minutes": 1})
    assert resp.status_code == 409
    assert get_clock() is frozen_clock and not _advances(db)


# =============================================================================
# HELD — restarts cannot be steered by anything an agent writes
# =============================================================================

def test_held_agent_writes_cannot_forge_clock_events(bt_client, backtest, db):
    """Every agent-written event has a server-chosen type: a message whose
    payload carries ``to``, a task subject 'clock_advanced', a cost report —
    none is read back as time on restart."""
    pm, an = H(backtest["pm"]), H(backtest["an"])
    for body in (
        {"to": "agent:1", "body": "clock_advanced", "thread_id": "run_started",
         "structured_payload": {"type": "clock_advanced", "to": FUTURE, "start": FUTURE}},
        {"to": f"pod:{backtest['pod_id']}", "body": FUTURE},
    ):
        for h in (pm, an):
            bt_client.post("/messages", headers=h, json=body)
    for h in (pm, an):
        r = bt_client.post("/tasks/start", headers=h, json={"subject": "clock_advanced"})
        assert r.status_code == 201, r.text
        bt_client.post("/tasks/end", headers=h, json={
            "task_id": r.json()["id"], "outcome": {"type": "clock_advanced", "to": FUTURE}})
        r = bt_client.post("/costs", headers=h, json={
            "tokens_in": 1, "tokens_out": 1, "usd_cost": 0.01, "task_label": "run_started"})
        assert r.status_code == 201, r.text
    bt_client.post("/orders", headers=pm, json={
        "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "limit",
        "limit_price": 1.0, "justification": FUTURE})
    types = {e.type for e in _events(db)}
    assert EVENT_CLOCK_ADVANCED not in types
    assert [e.type for e in _events(db)].count(EVENT_RUN_STARTED) == 1

    set_clock(LiveClock())                      # the server dies, and comes back
    clock = install_run_clock(db)
    assert isinstance(clock, BacktestClock) and clock.now() == START
    assert ledger_now(db) == START
    assert all(e.ts == START for e in _events(db))


def test_held_restart_resumes_exactly_at_the_ledgers_now(bt_client, backtest, db, prices):
    adm, pm = H(backtest["admin"]), H(backtest["pm"])
    bt_client.post("/clock/advance", headers=adm, json={"days": 2, "minutes": 7})
    bt_client.post("/orders", headers=pm, json={
        "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "t"})
    bt_client.post("/clock/advance", headers=adm, json={"minutes": 1})
    expect = START + timedelta(days=2, minutes=8)
    set_clock(LiveClock())
    install_run_clock(db)
    assert get_clock().now() == expect == ledger_now(db)
    stamps = [e.ts for e in _events(db)]
    assert stamps == sorted(stamps) and max(stamps) == expect


# =============================================================================
# HELD — races between advances, orders and sweeps (no double fill)
# =============================================================================

def test_held_concurrent_advances_are_serial_and_monotonic(backtest, SessionFactory, db):
    def one(_: int) -> None:
        s = SessionFactory()
        try:
            advance(s, minutes=60, actor_agent_id=backtest["admin_id"])
            check_pending_orders(s)
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, range(16)))
    adv = _advances(db)
    assert len(adv) == 16
    assert get_clock().now() == START + timedelta(hours=16)
    tos = [datetime.fromisoformat(e.payload_json["to"]) for e in adv]
    assert tos == sorted(tos) and len(set(tos)) == 16
    for a, b in zip(adv, adv[1:]):
        assert b.payload_json["from"] == a.payload_json["to"]


def test_held_concurrent_advances_fill_a_crossing_order_once(
    bt_client, backtest, SessionFactory, db, prices
):
    placed = bt_client.post("/orders", headers=H(backtest["pm"]), json={
        "ticker": "AAPL", "side": "buy", "qty": 10, "price_type": "limit",
        "limit_price": 150.0, "justification": "dip"}).json()
    prices.set_price("AAPL", 140.0)

    def one(_: int) -> list[int]:
        s = SessionFactory()
        try:
            advance(s, minutes=30, actor_agent_id=backtest["admin_id"])
            return check_pending_orders(s).filled
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        filled = [i for r in pool.map(one, range(6)) for i in r]
    assert filled == [placed["id"]]
    assert [e.type for e in _events(db)].count("order_filled") == 1


def test_held_cancel_racing_an_advance_never_fills_and_cancels(
    bt_client, backtest, db, prices
):
    placed = bt_client.post("/orders", headers=H(backtest["pm"]), json={
        "ticker": "AAPL", "side": "buy", "qty": 10, "price_type": "limit",
        "limit_price": 150.0, "justification": "dip"}).json()
    prices.set_price("AAPL", 140.0)
    bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 1})
    resp = bt_client.delete(f"/orders/{placed['id']}", headers=H(backtest["pm"]))
    assert resp.status_code in (404, 405, 409, 422), resp.text
    db.expire_all()
    assert db.get(Order, placed["id"]).status is OrderStatus.filled


def test_held_unpriceable_pending_order_does_not_break_the_advance(
    bt_client, backtest, db
):
    """A PM parks a limit order on a symbol the feed cannot price: the advance
    still succeeds (no 500 after the clock already moved), the order waits."""
    placed = bt_client.post("/orders", headers=H(backtest["pm"]), json={
        "ticker": "NOPE-ZZ", "side": "buy", "qty": 1, "price_type": "limit",
        "limit_price": 1.0, "justification": "jam the sweep"})
    assert placed.status_code == 201
    resp = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["filled_order_ids"] == []


def test_held_rejection_to_a_deactivated_pm_does_not_break_the_advance(
    bt_client, backtest, db, prices
):
    """A pending order turned unaffordable whose PM was deactivated: the sweep's
    rejection notice still lands, the advance answers 200."""
    pm = H(backtest["pm"])
    lim = bt_client.post("/orders", headers=pm, json={
        "ticker": "AAPL", "side": "buy", "qty": 400, "price_type": "limit",
        "limit_price": 150.0, "justification": "t"}).json()
    bt_client.post("/orders", headers=pm, json={
        "ticker": "MSFT", "side": "buy", "qty": 240, "price_type": "market",
        "justification": "spend the cash"})
    r = bt_client.post(f"/agents/{backtest['pm_id']}/deactivate", headers=H(backtest["admin"]))
    assert r.status_code in (200, 204), r.text
    prices.set_price("AAPL", 140.0)
    resp = bt_client.post("/clock/advance", headers=H(backtest["admin"]), json={"days": 1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rejected_order_ids"] == [lim["id"]]


# =============================================================================
# HOLES
# =============================================================================

# Was HOLE (medium): place_order read the clock and fetched the market price
# BEFORE taking OMS_LOCK; an advance landing in between made the order fill at
# the old now's price, stamped at the new now. Fixed cycle 15: under the lock a
# moved non-live clock re-prices at the new now.
def test_held_market_order_priced_at_old_now_stamped_at_new_now(
    bt_client, backtest, SessionFactory, db
):
    feed = StepProvider({"AAPL": [(START - DAY, 100.0), (START + DAY, 150.0)]})
    set_provider(feed)

    def management_advances_meanwhile() -> None:
        s = SessionFactory()
        try:
            advance(s, minutes=24 * 60, actor_agent_id=backtest["admin_id"])
        finally:
            s.close()

    feed.on_get = management_advances_meanwhile
    resp = bt_client.post("/orders", headers=H(backtest["pm"]), json={
        "ticker": "AAPL", "side": "buy", "qty": 10, "price_type": "market",
        "justification": "in flight across the advance"})
    assert resp.status_code == 201, resp.text
    [fill] = [e for e in _events(db) if e.type == "order_filled"]
    assert fill.ts == START + DAY                         # stamped at the new now ...
    # ... so physics owes the price of that moment (150), not of the old one (100).
    assert fill.payload_json["fill_price"] == feed.price_at("AAPL", fill.ts)


# Was HOLE (medium): check_pending_orders read `now` before taking OMS_LOCK; a
# sweep queued behind a second advance filled at T1's price with a T2 stamp.
# Fixed cycle 15: `now` is read under the lock.
def test_held_sweep_prices_at_a_now_the_clock_has_left(
    bt_client, backtest, SessionFactory, db, monkeypatch
):
    t1, t2 = START + DAY, START + 2 * DAY
    feed = StepProvider({"AAPL": [(START - DAY, 200.0), (t1, 140.0), (t2, 200.0)]})
    set_provider(feed)
    placed = bt_client.post("/orders", headers=H(backtest["pm"]), json={
        "ticker": "AAPL", "side": "buy", "qty": 10, "price_type": "limit",
        "limit_price": 150.0, "justification": "dip"}).json()

    s = SessionFactory()
    advance(s, minutes=24 * 60, actor_agent_id=backtest["admin_id"])   # advance A → T1
    s.close()

    read_now = threading.Event()

    real_ledger_now = monitor.ledger_now

    def spy(session) -> datetime:
        # The sweep's read of now (ledger_now since cycle 17, ADR-029).
        n = real_ledger_now(session)
        read_now.set()
        return n

    monkeypatch.setattr(monitor, "ledger_now", spy)
    out: dict = {}

    def sweep_a() -> None:
        ss = SessionFactory()
        try:
            out["result"] = check_pending_orders(ss)
        finally:
            ss.close()

    with OMS_LOCK:                                   # advance B owns the lock first
        t = threading.Thread(target=sweep_a)
        t.start()
        # With the hole, sweep A reads T1 here and then waits on the lock. Fixed,
        # it reads nothing until it holds the lock, so this wait times out — the
        # property under test is the fill price below, not this timing.
        read_now.wait(0.5)
        s = SessionFactory()
        advance(s, minutes=24 * 60, actor_agent_id=backtest["admin_id"])  # B → T2
        s.close()
    t.join(5)
    monkeypatch.undo()

    fills = [e for e in _events(db) if e.type == "order_filled"]
    for fill in fills:
        assert fill.payload_json["fill_price"] == feed.price_at("AAPL", fill.ts), (
            f"order {placed['id']} filled at {fill.payload_json['fill_price']} "
            f"stamped {fill.ts}, market then {feed.price_at('AAPL', fill.ts)}")
    # The outcome itself (re-audit, cycle 15): sweep A ran, priced at T2 (200,
    # not crossing 150) and left the order pending — not a vacuous empty loop.
    assert not t.is_alive()
    assert out["result"].checked == 1 and out["result"].filled == []
    assert fills == []
    db.expire_all()
    assert db.get(Order, placed["id"]).status == OrderStatus.pending


# Was HOLE (medium): a server already serving a fresh file kept LiveClock after
# `start-backtest` opened a backtest on it; agents' orders were stamped TODAY in
# the backtest ledger and, after a restart, every advance was refused — the run
# bricked with live stamps. Fixed cycle 15: append_event refuses a clock that is
# not its ledger's run clock (503 until the server restarts on the right clock).
def test_held_live_server_on_a_file_turned_backtest_stamps_today(
    client, SessionFactory, db
):
    # 1. The server is up on a fresh, empty file: lifespan finds no run_started.
    assert get_clock().mode == "live"
    # 2. The operator, in another process, opens a backtest on that file and seeds it.
    s = SessionFactory()
    start_backtest(s, start=START)
    admin_agent, admin = register_agent(s, name="management", role=AgentRole.management)
    pod = create_pod(s, name="desk")
    fund_pod(s, pod_id=pod.id, delta=100_000.0,
             actor=get_or_create_system_agent(s), reason="seed")
    _, pm = register_agent(s, name="pm", role=AgentRole.pm, pod_id=pod.id)
    s.commit()
    admin_id = admin_agent.id
    s.close()
    set_clock(LiveClock())               # ... but the server process is still live
    # 3. Agents talk to the running server.
    order = client.post("/orders", headers=H(pm), json={
        "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "t"})
    adv = client.post("/clock/advance", headers=H(admin), json={"days": 1})
    stamps = [e.ts for e in _events(db)]
    assert _events(db)[0].type == EVENT_RUN_STARTED
    assert max(stamps) < START + timedelta(days=2), "a live (today) stamp in a backtest ledger"
    # The stale server writes nothing: 503 (restart) for writes, 409 for the advance.
    assert order.status_code == 503, order.text
    assert adv.status_code == 409, adv.text
    # Not bricked: a restart puts the process on the run's clock and time moves.
    s = SessionFactory()
    install_run_clock(s)
    assert get_clock().now() == START
    advance(s, minutes=24 * 60, actor_agent_id=admin_id)
    s.close()
    assert get_clock().now() == START + DAY
