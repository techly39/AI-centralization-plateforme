"""RED-TEAM 0009 — attacks on cycle 0017's "one now" (B-004b, ADR-029).

Claim under attack: every physics reader of time — ``/price``, the ``/ohlcv``
defaults, ``/portfolio``, ``/metrics/pod``, ``/metrics/leaderboard``, the OMS
market-order reference price and the pending-order sweep — answers at
``ledger_now(session)`` = ``max(clock, latest ledger stamp)``: the moment an
agent's next event is stamped with and ``GET /clock`` reports. Price, valuation
and stamp of one act are one moment. An AST test pins every other ``.now()``.

The attacker is a firm agent (API key, REST / MCP) standing next to world events
it cannot cause: a clock step back, a backtest advance (that succeeds, or
fails), an operator's ``fund-env check-orders`` in a second process on the same
database. Where an interleaving needs a precise moment, a spy places the
world event exactly there — the code paths involved hold no lock that would
forbid it (or, across processes, a lock the other process does not share).

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.api.metrics as metrics_api
import app.oms.portfolio as portfolio_mod
import app.oms.service as oms_service
import app.run_clock as run_clock
import tests.test_one_now as law
from app.clock import BacktestClock, LiveClock, get_clock, set_clock
from app.db.models import Agent, AgentRole
from app.ledger.events import EVENT_MESSAGE_SENT, append_event, ledger_now
from app.marketdata import set_provider
from app.oms.monitor import check_pending_orders
from app.oms.service import place_order
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import start_backtest
from tests.support import FrozenClock, HistoricalProvider

UTC = timezone.utc
APP = Path(__file__).resolve().parent.parent / "app"


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


# --- A backtest world --------------------------------------------------------
#: Backtest opens at 15:00 UTC on 6 March 2024: the last ended day is 5 March.
BT_START = datetime(2024, 3, 6, 15, 0, tzinfo=UTC)
ONE_DAY = 24 * 60
BT_NEXT = BT_START + timedelta(minutes=ONE_DAY)
#: AAPL closes 100 + day of month: at BT_START the known close is 105, at BT_NEXT 106.
BT_SERIES = {"AAPL": {date(2024, 3, d): 100.0 + d for d in range(1, 12)}}
CLOSE_AT_START = 105.0
CLOSE_AT_NEXT = 106.0


def _close_known_at(moment: datetime) -> float:
    """The close of the last day that had ended by ``moment`` (ADR-028)."""
    days = BT_SERIES["AAPL"]
    ended = [d for d in days if datetime(d.year, d.month, d.day, tzinfo=UTC)
             + timedelta(days=1) <= moment]
    return days[max(ended)]


@pytest.fixture
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


def _open_backtest(SessionFactory) -> dict[str, object]:
    set_provider(HistoricalProvider(BT_SERIES))
    session = SessionFactory()
    try:
        start_backtest(session, start=BT_START)
        admin, admin_key = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="desk")
        fund_pod(session, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(session), reason="seed")
        pm, pm_key = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
        session.commit()
        return {"admin": admin_key, "admin_id": admin.id, "pm": pm_key,
                "pm_id": pm.id, "pod_id": pod.id}
    finally:
        session.close()


def _market(client, key: str, side: str, qty: float) -> dict:
    resp = client.post("/orders", headers=H(key), json={
        "ticker": "AAPL", "side": side, "qty": qty, "price_type": "market",
        "justification": "red-team 0009"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_in_another_session(SessionFactory, admin_id: int, minutes: int = ONE_DAY) -> None:
    """``POST /clock/advance`` as it runs in a concurrent request thread."""
    s = SessionFactory()
    try:
        run_clock.advance(s, minutes=minutes, actor_agent_id=admin_id)
    finally:
        s.close()


def _advance_in_another_process(SessionFactory, admin_id: int) -> None:
    """The API process advances; *this* process's clock copy does not move.

    Two processes on one SQLite file share the ledger but neither ``OMS_LOCK``
    (a ``threading.RLock``) nor the installed ``BacktestClock``.
    """
    mine = get_clock().now()
    _advance_in_another_session(SessionFactory, admin_id)
    set_clock(BacktestClock(mine))


# =============================================================================
# HOLES
# =============================================================================

# Was HOLE (medium): run_clock.advance moved the process clock before the
# clock_advanced event committed; /clock and /price (no OMS_LOCK) answered at the
# new now in that window, and a failed advance rolled the world back after the
# agent had seen the next day's close. Fixed cycle 17: the event is stamped
# `at=end` and committed first; the clock moves only after the commit.
def test_held_a_failed_advance_has_shown_no_prices(
        monkeypatch, SessionFactory, client, live_afterwards):
    world = _open_backtest(SessionFactory)
    real_append = run_clock.append_event
    seen: dict[str, object] = {}

    def append_then_fail(session, *, type, **kwargs):
        if type == run_clock.EVENT_CLOCK_ADVANCED:
            # An agent polling while the advance is in flight (no lock on reads).
            seen["clock"] = client.get("/clock", headers=H(world["pm"])).json()["now"]
            seen["price"] = client.get("/price/AAPL", headers=H(world["pm"])).json()["price"]
            # e.g. sqlite3.OperationalError: database is locked (busy timeout).
            raise RuntimeError("database is locked")
        return real_append(session, type=type, **kwargs)

    monkeypatch.setattr(run_clock, "append_event", append_then_fail)
    s = SessionFactory()
    try:
        with pytest.raises(RuntimeError):
            run_clock.advance(s, minutes=ONE_DAY, actor_agent_id=world["admin_id"])
    finally:
        s.close()

    after = datetime.fromisoformat(client.get("/clock", headers=H(world["pm"])).json()["now"])
    assert after == BT_START                       # the world never left 6 March
    assert client.get("/price/AAPL", headers=H(world["pm"])).json()["price"] == CLOSE_AT_START
    # The property: nothing was shown at a now the ledger never reached.
    assert datetime.fromisoformat(seen["clock"]) == BT_START
    assert seen["price"] == CLOSE_AT_START


# Was HOLE (low): compute_pod_metrics read ledger_now, then build_portfolio read
# it again; an advance between the two valued the book at the later now. Fixed
# cycle 17: the metrics pass their now to the portfolio.
def test_held_pod_metrics_value_the_book_at_their_as_of(
        monkeypatch, SessionFactory, client, live_afterwards):
    world = _open_backtest(SessionFactory)
    assert _market(client, world["pm"], "buy", 10)["fill_price"] == CLOSE_AT_START

    real = portfolio_mod.ledger_now

    def advance_lands_here(session):
        # A management POST /clock/advance in another request thread, landing
        # between the metrics' read of now and the portfolio's.
        _advance_in_another_session(SessionFactory, world["admin_id"])
        return real(session)

    monkeypatch.setattr(portfolio_mod, "ledger_now", advance_lands_here)
    body = client.get(f"/metrics/pod/{world['pod_id']}", headers=H(world["admin"])).json()
    as_of = datetime.fromisoformat(body["as_of"])
    # The property: the book is valued at the moment the report says it is.
    assert body["capital"]["positions_value"] == pytest.approx(10 * _close_known_at(as_of))


# Was HOLE (low): /metrics/leaderboard read its as_of after computing the rows
# (each pod read its own ledger_now). Fixed cycle 17: one now, read first,
# passed to every pod.
def test_held_leaderboard_as_of_is_the_now_its_rows_were_valued_at(
        monkeypatch, SessionFactory, client, live_afterwards):
    world = _open_backtest(SessionFactory)
    _market(client, world["pm"], "buy", 10)
    real = metrics_api.compute_leaderboard

    def rows_then_advance(session, **kwargs):
        rows = real(session, **kwargs)
        _advance_in_another_session(SessionFactory, world["admin_id"])
        return rows

    monkeypatch.setattr(metrics_api, "compute_leaderboard", rows_then_advance)
    body = client.get("/metrics/leaderboard", headers=H(world["admin"])).json()
    # The rows were valued at BT_START (positions at 105); as_of must say so.
    assert datetime.fromisoformat(body["as_of"]) == BT_START


@pytest.mark.xfail(strict=True, reason=(
    "red-team 0009 LOW: OMS_LOCK is per-process; the sweep reads ledger_now under "
    "it, but another process's committed advance moves the SQL floor before the "
    "fill INSERT: filled at the old now's price, stamped at the new now."))
def test_hole_cross_process_sweep_fills_at_a_price_older_than_its_stamp(
        SessionFactory, client, live_afterwards):
    world = _open_backtest(SessionFactory)
    # Crosses at 105 (6 March's known close), not at 106 (7 March's).
    resp = client.post("/orders", headers=H(world["pm"]), json={
        "ticker": "AAPL", "side": "buy", "qty": 1.0, "price_type": "limit",
        "limit_price": 105.5, "justification": "only below 105.5"})
    assert resp.status_code == 201 and resp.json()["status"] == "pending", resp.text
    order_id = resp.json()["id"]

    class OtherProcessAdvancesMidSweep(HistoricalProvider):
        fired = False

        def _quote(self, symbol, *, as_of):
            if not self.fired:
                self.fired = True
                _advance_in_another_process(SessionFactory, world["admin_id"])
            return super()._quote(symbol, as_of=as_of)

    # `fund-env check-orders` in its own process (its clock copy: 6 March).
    cli = SessionFactory()
    try:
        check_pending_orders(cli, provider=OtherProcessAdvancesMidSweep(BT_SERIES))
    finally:
        cli.close()

    order = next(o for o in client.get("/orders", headers=H(world["pm"])).json()
                 if o["id"] == order_id)
    if order["status"] == "filled":
        stamped = datetime.fromisoformat(order["filled_at"])
        # The property: a fill is priced at the moment it is stamped.
        assert order["fill_price"] == _close_known_at(stamped)


@pytest.mark.xfail(strict=True, reason=(
    "red-team 0009 LOW: same per-process OMS_LOCK gap in place_order: the in-lock "
    "recheck of ledger_now passes, another process's advance commits, the order "
    "is stamped at the new now and filled at the old now's price."))
def test_hole_cross_process_market_order_priced_before_its_stamp(
        monkeypatch, SessionFactory, client, live_afterwards):
    world = _open_backtest(SessionFactory)
    real = oms_service.ledger_now
    calls = {"n": 0}

    def recheck_then_other_process_advances(session):
        calls["n"] += 1
        value = real(session)
        if calls["n"] == 2:  # the read under OMS_LOCK
            _advance_in_another_process(SessionFactory, world["admin_id"])
        return value

    monkeypatch.setattr(oms_service, "ledger_now", recheck_then_other_process_advances)
    fill = _market(client, world["pm"], "buy", 1)
    stamped = datetime.fromisoformat(fill["created_at"])
    assert fill["fill_price"] == _close_known_at(stamped)


# Was HOLE (low): build_portfolio read positions, priced them, then read cash; a
# fill committed in between was counted twice (shares and proceeds). Fixed
# cycle 17: positions and cash are read together under OMS_LOCK, priced after.
def test_held_portfolio_total_counts_a_concurrent_sale_once(
        frozen_clock, SessionFactory, client, desk):
    series = {"AAPL": {date(2026, 6, d): 100.0 + d for d in range(1, 13)}}
    frozen_clock.set(datetime(2026, 6, 10, 15, 0, tzinfo=UTC))
    set_provider(HistoricalProvider(series))
    pod_id, pm_id, pm_key = desk
    _market(client, pm_key, "buy", 10)
    before = client.get(f"/portfolio/{pod_id}", headers=H(pm_key)).json()["total_value"]

    class SaleLandsMidValuation(HistoricalProvider):
        armed = True

        def _quote(self, symbol, *, as_of):
            if self.armed:
                self.armed = False
                s = SessionFactory()
                try:
                    place_order(s, actor=s.get(Agent, pm_id), ticker="AAPL", side="sell",
                                qty=10.0, price_type="market", justification="race")
                finally:
                    s.close()
            return super()._quote(symbol, as_of=as_of)

    set_provider(SaleLandsMidValuation(series))
    during = client.get(f"/portfolio/{pod_id}", headers=H(pm_key)).json()["total_value"]
    set_provider(HistoricalProvider(series))
    after = client.get(f"/portfolio/{pod_id}", headers=H(pm_key)).json()["total_value"]
    # The property: a valuation is the book at one moment — before or after.
    assert during in (pytest.approx(before), pytest.approx(after))


# --- The static law ----------------------------------------------------------

def _law_flags(monkeypatch, root: Path, files: dict[str, str]) -> bool:
    """Does tests/test_one_now.py's law fail on an ``app/`` holding ``files``?"""
    for rel, src in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src)
    monkeypatch.setattr(law, "APP", root)
    try:
        law.test_no_physics_reader_of_now_bypasses_the_ledger()
    except AssertionError:
        return True
    return False


#: Raw reads of time the strengthened detector (commit 9d9484f) did not see.
#: Each is one line a new physics file could hold; none is in app/ today.
#: All seen since cycle 17 (imports, _now/wall_now/current_timestamp attributes,
#: computed getattr, methodcaller).
_DODGES = {
    # Names bound by import: the detector looks at `time.<x>` and `wall_now` only.
    "from_time_import": "from time import time\n"
                        "def price_moment():\n    return time()\n",
    "time_module_alias": "import time as t\n"
                         "def price_moment():\n    return t.time()\n",
    "wall_now_alias": "from app.clock import wall_now as real\n"
                      "def price_moment():\n    return real()\n",
    "wall_now_attribute": "from app import clock\n"
                          "def price_moment():\n    return clock.wall_now()\n",
    # The attribute name spelled at runtime, or by another helper than getattr.
    "getattr_computed": "from app.clock import get_clock\n"
                        "def price_moment():\n    return getattr(get_clock(), 'n' + 'ow')()\n",
    "methodcaller": "from operator import methodcaller\nfrom app.clock import get_clock\n"
                    "def price_moment():\n    return methodcaller('now')(get_clock())\n",
    # The clock's state, not its method (BacktestClock/FrozenClock keep `_now`).
    "private_state": "from app.clock import get_clock\n"
                     "def price_moment():\n    return get_clock()._now\n",
    # The database's own clock: wall time, behind no floor.
    "sql_clock": "from sqlalchemy import func, select\n"
                 "def price_moment(session):\n"
                 "    return session.scalar(select(func.current_timestamp()))\n",
}


# Was HOLE (low): the detector matched only now/utcnow/today, `time.<x>`, the
# name `wall_now` and getattr with a constant. Fixed cycle 17.
@pytest.mark.parametrize("dodge", sorted(_DODGES))
def test_held_the_now_law_sees_a_raw_read_spelled_differently(monkeypatch, tmp_path, dodge):
    assert _law_flags(monkeypatch, tmp_path, {"oms/pricing.py": _DODGES[dodge]})


def test_held_an_allowlisted_file_cannot_grow_a_new_raw_reader(monkeypatch, tmp_path):
    """Counted per read since 9d9484f: one more read in a listed file is red."""
    allowed = law.ALLOWED_TIME_READS["bus/messages.py"][0]
    grown = "from app.clock import get_clock\n" + "".join(
        f"def read_{i}():\n    return get_clock().now()\n" for i in range(allowed + 1)
    )
    assert _law_flags(monkeypatch, tmp_path, {"bus/messages.py": grown})


@pytest.mark.parametrize("source", [
    "f = clock.now",
    "getattr(clock, 'now')()",
    "datetime.utcnow()",
    "time.monotonic()",
    "wall_now()",
    "x = wall_now",
])
def test_held_the_spellings_the_auditor_named_are_seen(monkeypatch, tmp_path, source):
    assert _law_flags(monkeypatch, tmp_path, {"oms/pricing.py": source + "\n"})


# =============================================================================
# HELD
# =============================================================================

LEDGER_DAY = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)
STEPPED_BACK = datetime(2026, 6, 5, 15, 0, tzinfo=UTC)
SERIES = {"AAPL": {date(2026, 6, d): 100.0 + d for d in range(1, 13)}}


class _LiveModeFrozen(FrozenClock):
    """A frozen clock that reports ``live``: place_order skips its in-lock recheck."""

    mode = "live"


@pytest.fixture
def live_mode_frozen() -> Iterator[_LiveModeFrozen]:
    # Installed before the desk is registered, so no stamp is at the real today.
    clock = _LiveModeFrozen(LEDGER_DAY)
    set_clock(clock)
    yield clock
    set_clock(LiveClock())


@pytest.fixture
def stepped_back_live(live_mode_frozen, client, desk) -> tuple[int, str]:
    set_provider(HistoricalProvider(SERIES))
    pod_id, pm_id, pm_key = desk
    _market(client, pm_key, "buy", 10)
    live_mode_frozen.set(STEPPED_BACK)
    now = datetime.fromisoformat(client.get("/clock", headers=H(pm_key)).json()["now"])
    assert now == LEDGER_DAY
    return pm_id, pm_key


def test_held_another_agents_append_mid_pricing_cannot_move_the_floor(
        SessionFactory, client, stepped_back_live):
    """Live path (no recheck), clock behind the ledger: a message stamped while
    the order is priced lands at the held floor, so the order still is too."""
    pm_id, pm_key = stepped_back_live

    class ChatterMidPricing(HistoricalProvider):
        armed = True

        def _quote(self, symbol, *, as_of):
            if self.armed:
                self.armed = False
                s = SessionFactory()
                try:
                    append_event(s, type=EVENT_MESSAGE_SENT, actor_agent_id=pm_id,
                                 payload={"message_id": 0, "to": "broadcast"})
                    s.commit()
                finally:
                    s.close()
            return super()._quote(symbol, as_of=as_of)

    set_provider(ChatterMidPricing(SERIES))
    fill = _market(client, pm_key, "buy", 1)
    assert datetime.fromisoformat(fill["created_at"]) == LEDGER_DAY
    assert fill["fill_price"] == 109.0


def test_held_explicit_ohlcv_end_past_the_ledgers_now_is_clipped(client, stepped_back_live):
    _, pm_key = stepped_back_live
    resp = client.get("/ohlcv/AAPL", headers=H(pm_key),
                      params={"start": "2026-06-01", "end": "2026-06-13"})
    if resp.status_code == 200:
        closes = [b["close"] for b in resp.json()["bars"]]
        assert closes and max(closes) <= 109.0, closes
    else:
        assert resp.status_code in (400, 404), resp.text


def test_held_stepped_back_sweep_fills_at_the_stamp_and_its_price(client, stepped_back_live, db):
    _, pm_key = stepped_back_live
    resp = client.post("/orders", headers=H(pm_key), json={
        "ticker": "AAPL", "side": "buy", "qty": 1.0, "price_type": "limit",
        "limit_price": 110.0, "justification": "fills at 109"})
    order_id = resp.json()["id"]
    check_pending_orders(db)
    order = next(o for o in client.get("/orders", headers=H(pm_key)).json() if o["id"] == order_id)
    assert order["status"] == "filled"
    assert datetime.fromisoformat(order["filled_at"]) == LEDGER_DAY
    assert order["fill_price"] == 109.0


def test_held_ledger_now_compares_stamps_by_time_not_by_text(frozen_clock, db) -> None:
    """Stored stamps are strings in SQLite; the floor must still order them as time."""
    t = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)
    frozen_clock.set(t + timedelta(microseconds=1))
    append_event(db, type=EVENT_MESSAGE_SENT, actor_agent_id=None, payload={})
    db.commit()
    frozen_clock.set(t)
    assert ledger_now(db) == t + timedelta(microseconds=1)
    frozen_clock.set(t + timedelta(seconds=1))
    assert ledger_now(db) == t + timedelta(seconds=1)
    # A non-UTC clock is compared as the same instant, not by its local text.
    frozen_clock.set(datetime(2026, 6, 10, 10, 0, 2, tzinfo=timezone(timedelta(hours=-5))))
    assert ledger_now(db) == t + timedelta(seconds=2)
    frozen_clock.set(datetime(2026, 6, 10, 11, 0, tzinfo=timezone(timedelta(hours=1))))
    assert ledger_now(db) == t + timedelta(microseconds=1)


def test_held_a_clock_file_in_a_subpackage_is_not_allowlisted(monkeypatch, tmp_path) -> None:
    src = "from app.clock import get_clock\ndef f():\n    return get_clock().now()\n"
    assert _law_flags(monkeypatch, tmp_path, {"oms/clock.py": src})
    assert _law_flags(monkeypatch, tmp_path / "b", {"ledger/events_extra.py": src})


def test_held_in_process_advance_cannot_split_price_and_stamp(
        monkeypatch, SessionFactory, client, live_afterwards):
    """Same as the cross-process hole, but in one process: the advance needs
    OMS_LOCK, so it cannot land between the recheck and the stamp."""
    import threading

    world = _open_backtest(SessionFactory)
    real = oms_service.ledger_now
    calls = {"n": 0}
    done = threading.Event()

    def recheck_then_advance_tries(session):
        calls["n"] += 1
        value = real(session)
        if calls["n"] == 2:
            t = threading.Thread(target=lambda: (
                _advance_in_another_session(SessionFactory, world["admin_id"]), done.set()))
            t.start()
            assert not done.wait(0.3)  # blocked on OMS_LOCK
        return value

    monkeypatch.setattr(oms_service, "ledger_now", recheck_then_advance_tries)
    fill = _market(client, world["pm"], "buy", 1)
    assert done.wait(5)
    stamped = datetime.fromisoformat(fill["created_at"])
    assert stamped == BT_START
    assert fill["fill_price"] == _close_known_at(stamped)
