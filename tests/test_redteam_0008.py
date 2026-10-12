"""RED-TEAM 0008 — attacks on the cycle-0016 look-ahead guard (B-005, ADR-028).

Claim under attack: nothing not yet known at the simulated now is served. Bars
are visible once ended (``bar_end``); a quote stamped after ``as_of`` is refused
(``FeedDataError``); ``get_price`` / ``get_ohlcv`` are final in the base; yfinance
answers a past ``as_of`` from daily history; a backtest stays at least
``LIVE_QUOTE_WINDOW`` behind the real now.

The attacker is a firm agent in a backtest: an API key (PM / analyst), REST /
MCP (MCP is a thin wrapper over the same routes), and whatever the feed
answers. No network: yfinance is replaced by an offline stub that honours the
``start`` / ``end`` window and stamps bars the way Yahoo does (exchange-local
midnight for daily / weekly / monthly, the bar's open for hourly).

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

import pytest

from app.clock import LiveClock, set_clock
from app.db.models import AgentRole
from app.marketdata import (
    Bar,
    FeedDataError,
    MarketDataProvider,
    Quote,
    StaticProvider,
    UnknownTickerError,
    set_provider,
)
from app.oms.monitor import check_pending_orders
from app.registry.pods import create_pod, fund_pod
from app.registry.service import (
    get_or_create_system_agent,
    register_agent,
    seed_runtime_agent,
)
from app.run_clock import start_backtest

UTC = timezone.utc
#: Wednesday 2024-03-06 (EST, UTC-5). NYSE: 09:30-16:00 ET = 14:30-21:00 UTC.
DAY = date(2024, 3, 6)
YESTERDAY = DAY - timedelta(days=1)
NOON = datetime(2024, 3, 6, 12, 0, tzinfo=UTC)
#: When DAY's daily bar ends by ADR-028: next New York midnight = 05:00 UTC.
DAY_BAR_END = datetime(2024, 3, 7, 5, 0, tzinfo=UTC)

#: Closes. The 1h series is DAY's session rising from 190 to 250; DAY's daily
#: close is therefore 250. The live quote is a tell: 999 means "the real today".
DAILY = {date(2024, 3, 4): 170.0, YESTERDAY: 180.0, DAY: 250.0}
HOURLY_ET = [(f"2024-03-06 {h:02d}:30", 190.0 + 10 * i) for i, h in enumerate(range(9, 16))]
WEEKLY = {date(2024, 2, 26): 175.0, date(2024, 3, 4): 250.0}
MONTHLY = {date(2024, 2, 1): 175.0, date(2024, 3, 1): 250.0}
LIVE_TELL = 999.0


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


# --- an offline yfinance that behaves like Yahoo -----------------------------

def _frame(rows: list[tuple[str, float]], tz: str):
    import pandas as pd

    closes = [c for _, c in rows]
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes,
         "Volume": [1] * len(rows)},
        index=pd.to_datetime([ts for ts, _ in rows]).tz_localize(tz),
    )


def _daily_rows(series: dict[date, float]) -> list[tuple[str, float]]:
    return [(d.isoformat(), c) for d, c in sorted(series.items())]


class _StubTicker:
    """``yf.Ticker``: ``history`` honours [start, end) like Yahoo; ``fast_info``
    is the real present."""

    def __init__(self, frames: dict[str, object]) -> None:
        self._frames = frames

    @property
    def fast_info(self):
        return {"lastPrice": LIVE_TELL, "currency": "USD"}

    def history(self, *, interval: str = "1d", start=None, end=None, period=None, **_):
        import pandas as pd

        frame = self._frames.get(interval)
        if frame is None or frame.empty:
            return pd.DataFrame()
        if start is None:
            return frame
        local = frame.index.tz_localize(None).normalize()
        keep = (local >= pd.Timestamp(start)) & (local < pd.Timestamp(end))
        return frame[keep]


def _install_yfinance(monkeypatch, universe: dict[str, dict[str, object]]) -> None:
    module = types.ModuleType("yfinance")
    module.Ticker = lambda symbol: _StubTicker(universe.get(symbol.upper(), {}))
    monkeypatch.setitem(sys.modules, "yfinance", module)


def _jpm_frames(tz: str = "America/New_York") -> dict[str, object]:
    return {
        "1d": _frame(_daily_rows(DAILY), tz),
        "1h": _frame(HOURLY_ET, tz),
        "1wk": _frame(_daily_rows(WEEKLY), tz),
        "1mo": _frame(_daily_rows(MONTHLY), tz),
    }


@pytest.fixture
def yf_stub(monkeypatch) -> None:
    _install_yfinance(monkeypatch, {"JPM": _jpm_frames()})


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


def _open_backtest(SessionFactory, start: datetime) -> dict[str, object]:
    session = SessionFactory()
    try:
        start_backtest(session, start=start)
        _, admin = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="desk")
        fund_pod(session, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(session), reason="seed")
        _, pm = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
        _, runtime = seed_runtime_agent(session)
        session.commit()
        return {"admin": admin, "pm": pm, "runtime": runtime, "pod_id": pod.id}
    finally:
        session.close()


def _market_buy(client, key: str, qty: float = 100) -> dict:
    return client.post("/orders", headers=H(key), json={
        "ticker": "JPM", "side": "buy", "qty": qty, "price_type": "market",
        "justification": "red-team"}).json()


# =============================================================================
# HOLES
# =============================================================================

# Fixed cycle 16 (was HIGH — stale-quote arbitrage: /ohlcv?interval=1h served
# today's ended hourly bars while fills used yesterday's daily close; a PM read
# 250 after the close and bought at 180). A past quote is now the latest bar of
# any interval /ohlcv serves that had ended (yfinance_provider._past_price).
def test_hole_fill_price_older_than_what_the_same_feed_already_serves(
        yf_stub, SessionFactory, client):
    set_provider(_yf(ttl=0))
    keys = _open_backtest(SessionFactory, datetime(2024, 3, 6, 22, 0, tzinfo=UTC))

    hourly = client.get("/ohlcv/JPM", headers=H(keys["pm"]),
                        params={"interval": "1h"}).json()["bars"]
    known_now = hourly[-1]["close"]
    assert known_now == 250.0                       # the session's close, known by 22:00 UTC
    fill = _market_buy(client, keys["pm"])
    assert fill["status"] == "filled"

    # The property: a fill is never at a price older than what the same world
    # already shows the agent at that now.
    assert fill["fill_price"] == known_now


# Fixed cycle 16 (was MEDIUM — the quote cache was keyed on clock distance only,
# so a quote read at 04:59 UTC was reused after a 1-minute advance crossed DAY's
# daily bar end). A past quote is now reused for its exact as_of only. The
# ticker has daily bars only: with hourly bars, DAY's 250 is already known at
# 04:59 (the fix above) and the cache would have nothing stale to serve.
def test_hole_cached_quote_outlives_the_bar_that_replaced_it(monkeypatch, SessionFactory, client):
    _install_yfinance(monkeypatch, {"JPM": {"1d": _jpm_frames()["1d"]}})
    set_provider(_yf(ttl=60))                       # config.yaml's default
    keys = _open_backtest(SessionFactory, DAY_BAR_END - timedelta(minutes=1))
    assert client.get("/price/JPM", headers=H(keys["pm"])).json()["price"] == 180.0

    assert client.post("/clock/advance", headers=H(keys["runtime"]),
                       json={"minutes": 1}).status_code == 200
    daily = client.get("/ohlcv/JPM", headers=H(keys["pm"])).json()["bars"]
    assert daily[-1]["close"] == 250.0              # DAY's bar has ended, and is served
    fill = _market_buy(client, keys["pm"])
    assert fill["fill_price"] == daily[-1]["close"]


# Fixed cycle 16 (was MEDIUM — existence oracle: 200 [] vs 404 depended on rows
# after as_of, so bisecting `end` found a future listing day). The base never
# asks the feed about a day after as_of's, and "no ended bar" is one 404 whose
# message names only the request.
def test_hole_answer_depends_on_data_after_as_of(monkeypatch):
    listed_later = {"1d": _frame([("2024-04-15", 50.0), ("2024-04-16", 55.0)],
                                 "America/New_York")}
    _install_yfinance(monkeypatch, {"NEWCO": listed_later})
    window = {"start": DAY - timedelta(days=30), "end": date(2024, 6, 1),
              "interval": "1d", "as_of": NOON}

    def outcome(symbol: str) -> str:
        try:
            return f"bars:{len(_yf(ttl=0).get_ohlcv(symbol, **window))}"
        except UnknownTickerError as exc:
            # The message must not tell them apart either.
            return f"unknown:{str(exc).replace(symbol, '<T>')}"

    # At NOON, NEWCO's future listing is not knowable: it must look like NOPE.
    assert outcome("NEWCO") == outcome("NOPE")


# Fixed cycle 16 (was LOW — the 'final' check looked only at cls.__dict__ at
# creation). Now: resolved through the MRO at creation, and refused on the class
# (metaclass) and on an instance. object.__setattr__ still bypasses the instance
# check — Python has no true final; in-process code is past the seal (ADR-028).
@pytest.mark.parametrize("dodge", ["mixin", "setattr_on_class", "instance_attribute"])
def test_hole_guarded_entry_can_still_be_replaced(dodge):
    def leaky(self_or_symbol, *args, **kwargs):
        as_of = kwargs["as_of"]
        return Quote(ticker="AAPL", price=1.0, as_of=as_of + timedelta(days=1))

    with pytest.raises((TypeError, FeedDataError)):
        if dodge == "mixin":
            class Mixin:
                def get_price(self, ticker, *, as_of):
                    return leaky(self, ticker, as_of=as_of)

            feed = type("Mixed", (Mixin, StaticProvider), {})({"AAPL": 1.0})
        elif dodge == "setattr_on_class":
            cls = type("Patched", (StaticProvider,), {})
            cls.get_price = leaky
            feed = cls({"AAPL": 1.0})
        else:
            feed = StaticProvider({"AAPL": 1.0})
            feed.get_price = lambda ticker, *, as_of: leaky(ticker, as_of=as_of)
        feed.get_price("AAPL", as_of=NOON)


# Fixed cycle 16 (was LOW — off-by-equality: start_backtest allowed exactly
# wall - 60 s, which the feed's inclusive window answers live). Both run-clock
# checks are now strict.
def test_hole_backtest_at_the_live_window_edge_gets_the_live_quote(
        yf_stub, SessionFactory, monkeypatch):
    import app.marketdata.yfinance_provider as yfp
    import app.run_clock as run_clock

    wall = NOON + timedelta(days=1)
    monkeypatch.setattr(run_clock, "wall_now", lambda: wall)
    monkeypatch.setattr(yfp, "wall_now", lambda: wall)
    start = wall - timedelta(seconds=60)
    session = SessionFactory()
    try:
        try:
            start_backtest(session, start=start)
        except run_clock.RunClockError:
            return                                   # refused: the edge is closed
        session.commit()
    finally:
        session.close()
    assert _yf(ttl=0).get_price("JPM", as_of=start).price != LIVE_TELL


# =============================================================================
# HELD
# =============================================================================

def _yf(*, ttl: float):
    from app.marketdata import YFinanceProvider

    return YFinanceProvider(cache_ttl_seconds=ttl)


def test_held_a_grandchild_provider_cannot_override_the_guard():
    class Child(StaticProvider):
        pass

    for method in ("get_price", "get_ohlcv"):
        with pytest.raises(TypeError, match="look-ahead guard"):
            type("Grandchild", (Child,), {method: lambda self, *a, **k: None})


@pytest.mark.parametrize("interval, as_of, visible", [
    # Hourly: DAY's first bar opens 14:30 UTC and is served only from 15:30.
    ("1h", datetime(2024, 3, 6, 15, 29, tzinfo=UTC), []),
    ("1h", datetime(2024, 3, 6, 15, 30, tzinfo=UTC), [190.0]),
    # Daily: DAY's bar (NY midnight = 05:00 UTC) until the next NY midnight.
    ("1d", DAY_BAR_END - timedelta(microseconds=1), [170.0, 180.0]),
    ("1d", DAY_BAR_END, [170.0, 180.0, 250.0]),
    # Weekly: the week of Mon 03-04 is hidden on Friday after the close.
    ("1wk", datetime(2024, 3, 8, 23, 0, tzinfo=UTC), [175.0]),
    # Monthly: March is hidden on March 29.
    ("1mo", datetime(2024, 3, 29, 23, 0, tzinfo=UTC), [175.0]),
])
def test_held_no_interval_serves_a_bar_before_it_ends(yf_stub, interval, as_of, visible):
    window = {"start": date(2024, 2, 1), "end": date(2024, 12, 31), "interval": interval,
              "as_of": as_of}
    if not visible:
        # No ended bar is one uniform 404, not 200 [] (see the existence oracle).
        with pytest.raises(UnknownTickerError):
            _yf(ttl=0).get_ohlcv("JPM", **window)
        return
    bars = _yf(ttl=0).get_ohlcv("JPM", **window)
    assert [b.close for b in bars] == visible
    assert all(b.ts < as_of for b in bars)


def test_held_tokyo_daily_bar_is_hidden_until_tokyo_midnight(monkeypatch):
    # JST midnight of DAY = 15:00 UTC the day before; the bar ends at DAY 15:00 UTC.
    _install_yfinance(monkeypatch, {"7203.T": {"1d": _frame(_daily_rows(DAILY), "Asia/Tokyo")}})
    end_of_day = datetime(2024, 3, 6, 15, 0, tzinfo=UTC)
    feed = _yf(ttl=0)
    assert feed.get_price("7203.T", as_of=end_of_day - timedelta(seconds=1)).price == 180.0
    assert feed.get_price("7203.T", as_of=end_of_day).price == 250.0


def test_held_the_cache_never_answers_an_earlier_now(yf_stub, monkeypatch):
    """A quote fetched live at the real now, or for a later simulated now, is
    never reused for an earlier one (backward jump = miss)."""
    import app.marketdata.yfinance_provider as yfp

    wall = DAY_BAR_END + timedelta(days=1)
    monkeypatch.setattr(yfp, "wall_now", lambda: wall)
    feed = _yf(ttl=3600)
    assert feed.get_price("JPM", as_of=wall).price == LIVE_TELL
    earlier = feed.get_price("JPM", as_of=NOON)
    assert (earlier.price, earlier.as_of <= NOON) == (180.0, True)
    assert feed.get_price("JPM", as_of=NOON - timedelta(seconds=1)).as_of <= NOON


def test_held_ohlcv_through_the_api_in_a_backtest(yf_stub, SessionFactory, client):
    """Every route shape an agent controls: start after now is 400; an `end` far
    in the future, the default window, and each interval serve nothing unended."""
    set_provider(_yf(ttl=0))
    keys = _open_backtest(SessionFactory, NOON)
    pm = H(keys["pm"])
    assert client.get("/ohlcv/JPM", headers=pm,
                      params={"start": "2024-03-07"}).status_code == 400
    for params in ({}, {"end": "2030-01-01"}, {"start": "2024-03-06", "end": "2030-01-01"},
                   {"interval": "1h", "end": "2030-01-01"},
                   {"interval": "1wk", "start": "2024-02-01", "end": "2030-01-01"},
                   {"interval": "1mo", "start": "2024-02-01", "end": "2030-01-01"}):
        resp = client.get("/ohlcv/JPM", headers=pm, params=params)
        closes = [b["close"] for b in resp.json().get("bars", [])]
        assert 250.0 not in closes, params
    price = client.get("/price/JPM", headers=pm).json()
    assert price["price"] == 180.0
    assert datetime.fromisoformat(price["as_of"]) <= NOON


def test_held_portfolio_and_metrics_do_not_value_at_an_unknown_close(
        yf_stub, SessionFactory, client):
    set_provider(_yf(ttl=0))
    keys = _open_backtest(SessionFactory, NOON)
    assert _market_buy(client, keys["pm"], qty=10)["fill_price"] == 180.0
    folio = client.get(f"/portfolio/{keys['pod_id']}", headers=H(keys["pm"])).json()
    assert [p["last_price"] for p in folio["positions"]] == [180.0]
    assert folio["positions_value"] == 1_800.0
    # Metrics are cross-pod (management); the curve's last point and the
    # capital block must use the same known close, not DAY's 250.
    metrics = client.get(f"/metrics/pod/{keys['pod_id']}", headers=H(keys["admin"]))
    assert metrics.status_code == 200
    assert metrics.json()["capital"]["positions_value"] == 1_800.0


class _FutureFeed(MarketDataProvider):
    name = "future"

    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        return Quote(ticker=symbol, price=1.0, as_of=as_of + timedelta(seconds=1),
                     source=self.name)

    def _bars(self, symbol, *, start, end, interval, as_of) -> list[Bar]:
        return []


def test_held_the_sweep_never_fills_at_a_future_stamped_quote(client, db, desk):
    _, _, pm_key = desk
    resp = client.post("/orders", headers=H(pm_key), json={
        "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "limit",
        "limit_price": 10_000.0, "justification": "t"})
    assert resp.status_code == 201 and resp.json()["status"] == "pending"
    result = check_pending_orders(db, provider=_FutureFeed())
    assert result.filled == [] and result.unpriced == ["AAPL"]
