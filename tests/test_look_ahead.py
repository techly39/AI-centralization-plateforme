"""The look-ahead guard (ADR-028, B-005, TRD Phase 3b).

Nothing known only after ``as_of`` is served by any provider: a bar is visible
once it has *ended*, a quote stamped after ``as_of`` is refused, and so is a
price that is not a positive finite number. The guard is in the
``MarketDataProvider`` base and a subclass cannot override it; yfinance answers
a past ``as_of`` from history, never with today's quote; the test double obeys
the same law; and a backtest stays out of the window where a live quote answers.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

import pytest

from app.clock import LiveClock, set_clock
from app.db.models import AgentRole
from app.marketdata import (
    Bar,
    FeedDataError,
    InvalidRequestError,
    MarketDataProvider,
    Quote,
    StaticProvider,
    bar_end,
    set_provider,
)
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import LOOK_AHEAD_GUARD, start_backtest
from tests.support import HistoricalProvider

#: Noon on a Wednesday, well in the past: a backtest's kind of now.
NOON = datetime(2024, 3, 6, 12, 0, tzinfo=timezone.utc)
DAY = NOON.date()
YESTERDAY = DAY - timedelta(days=1)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


class Rogue(MarketDataProvider):
    """A feed that answers whatever a test tells it to: price, stamp, bars."""

    name = "rogue"

    def __init__(self, *, price: float = 100.0, ahead: timedelta = timedelta(0),
                 bars: list[Bar] | None = None) -> None:
        self.price, self.ahead, self.bars = price, ahead, bars or []

    def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
        return Quote(ticker=symbol, price=self.price, as_of=as_of + self.ahead,
                     source=self.name)

    def _bars(self, symbol: str, *, start: date, end: date, interval: str,
              as_of: datetime) -> list[Bar]:
        return list(self.bars)


def _bar(ts: datetime, close: float) -> Bar:
    return Bar(ts=ts, open=close, high=close, low=close, close=close, volume=0.0)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)


# --- the law is in the base, and cannot be skipped ---------------------------

@pytest.mark.parametrize("method", ["get_price", "get_ohlcv"])
def test_a_provider_cannot_override_the_guarded_entries(method):
    with pytest.raises(TypeError, match="look-ahead guard"):
        type("Skipper", (StaticProvider,), {method: lambda self, *a, **k: None})


def test_a_quote_from_after_as_of_is_refused():
    with pytest.raises(FeedDataError, match="look-ahead"):
        Rogue(ahead=timedelta(microseconds=1)).get_price("AAPL", as_of=NOON)
    assert Rogue().get_price("aapl", as_of=NOON).as_of == NOON


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 0.0, -1.0])
def test_a_price_that_is_not_positive_and_finite_is_refused(bad):
    with pytest.raises(FeedDataError):
        Rogue(price=bad).get_price("AAPL", as_of=NOON)


def test_a_naive_as_of_is_refused():
    with pytest.raises(InvalidRequestError):
        Rogue().get_price("AAPL", as_of=NOON.replace(tzinfo=None))
    with pytest.raises(InvalidRequestError):
        Rogue().get_ohlcv("AAPL", start=YESTERDAY, end=DAY, interval="1d",
                          as_of=NOON.replace(tzinfo=None))


def test_a_bar_is_served_only_once_it_has_ended():
    feed = Rogue(bars=[_bar(_midnight(YESTERDAY), 1.0), _bar(_midnight(DAY), 2.0)])
    window = {"start": YESTERDAY, "end": DAY + timedelta(days=1), "interval": "1d"}
    # Noon on DAY: today's bar opened at 00:00 and carries today's close — unknown.
    assert [b.close for b in feed.get_ohlcv("X", as_of=NOON, **window)] == [1.0]
    end_of_day = _midnight(DAY + timedelta(days=1))
    assert [b.close for b in feed.get_ohlcv(
        "X", as_of=end_of_day - timedelta(microseconds=1), **window)] == [1.0]
    assert [b.close for b in feed.get_ohlcv("X", as_of=end_of_day, **window)] == [1.0, 2.0]


@pytest.mark.parametrize("ts, interval, end", [
    (datetime(2024, 3, 6, 14, tzinfo=timezone.utc), "1h",
     datetime(2024, 3, 6, 15, tzinfo=timezone.utc)),
    (datetime(2024, 3, 6, tzinfo=timezone.utc), "1d", datetime(2024, 3, 7, tzinfo=timezone.utc)),
    (datetime(2024, 3, 4, tzinfo=timezone.utc), "1wk", datetime(2024, 3, 11, tzinfo=timezone.utc)),
    (datetime(2024, 3, 1, tzinfo=timezone.utc), "1mo", datetime(2024, 4, 1, tzinfo=timezone.utc)),
    (datetime(2023, 12, 1, tzinfo=timezone.utc), "1mo", datetime(2024, 1, 1, tzinfo=timezone.utc)),
    (datetime(2024, 1, 31, tzinfo=timezone.utc), "1mo", datetime(2024, 2, 29, tzinfo=timezone.utc)),
])
def test_bar_end(ts, interval, end):
    assert bar_end(ts, interval) == end


def test_bar_end_refuses_an_unknown_interval():
    with pytest.raises(InvalidRequestError):
        bar_end(NOON, "3s")


def test_the_feed_is_never_asked_about_a_day_after_as_of():
    """The base clips the window it hands an implementation, so no answer can
    depend on rows after ``as_of``'s day (red-team 0008, existence oracle)."""

    class Recording(MarketDataProvider):
        name = "recording"
        asked: list[date] = []

        def _quote(self, symbol: str, *, as_of: datetime) -> Quote:
            raise NotImplementedError

        def _bars(self, symbol, *, start, end, interval, as_of) -> list[Bar]:
            self.asked.append(end)
            return [Bar(ts=_midnight(YESTERDAY), open=1.0, high=1.0, low=1.0,
                        close=1.0, volume=0.0)]

    feed = Recording()
    feed.get_ohlcv("JPM", start=DAY - timedelta(days=5), end=date(2030, 1, 1),
                   interval="1d", as_of=NOON)
    assert feed.asked == [DAY + timedelta(days=1)]


# --- the test double obeys the same law ---------------------------------------

def test_the_test_double_does_not_know_todays_close_at_noon():
    feed = HistoricalProvider({"JPM": {YESTERDAY: 180.0, DAY: 190.0}})
    quote = feed.get_price("JPM", as_of=NOON)
    assert (quote.price, quote.as_of) == (180.0, _midnight(DAY))
    assert feed.get_price("JPM", as_of=_midnight(DAY + timedelta(days=1))).price == 190.0


# --- yfinance answers the past from history -----------------------------------

class _Ticker:
    """A yfinance ``Ticker`` stub whose live quote is a tell: 999 means 'today'."""

    def __init__(self, frame):
        self._frame = frame

    @property
    def fast_info(self):
        return {"lastPrice": 999.0, "currency": "USD"}

    def history(self, *, interval="1d", **_kwargs):
        # Daily bars only: passing them off as hourly ones (05:00 UTC, ended
        # 06:00) is a shape Yahoo never returns, and since cycle 16 a past
        # quote reads hourly bars too.
        import pandas as pd

        return self._frame if interval == "1d" else pd.DataFrame()


@pytest.fixture
def stub_yfinance(monkeypatch):
    import sys
    import types

    import pandas as pd

    frame = pd.DataFrame(
        {"Open": [1.0, 2.0, 3.0], "High": [1.0, 2.0, 3.0], "Low": [1.0, 2.0, 3.0],
         "Close": [170.0, 180.0, 190.0], "Volume": [10, 20, 30]},
        # Exchange midnight (New York), as yfinance stamps daily bars.
        index=pd.to_datetime([str(DAY - timedelta(days=2)), str(YESTERDAY), str(DAY)])
        .tz_localize("America/New_York"),
    )
    module = types.ModuleType("yfinance")
    module.Ticker = lambda _symbol: _Ticker(frame)
    monkeypatch.setitem(sys.modules, "yfinance", module)


def test_yfinance_answers_the_past_from_history(stub_yfinance):
    from app.marketdata import YFinanceProvider

    quote = YFinanceProvider(cache_ttl_seconds=0).get_price("JPM", as_of=NOON)
    # Not today's quote (999), not today's close (190): yesterday's, stamped
    # when yesterday's bar ended (New York midnight = 05:00 UTC in March).
    assert quote.price == 180.0
    assert quote.as_of == datetime(2024, 3, 6, 5, 0, tzinfo=timezone.utc)


def test_yfinance_live_quote_answers_only_the_real_now(stub_yfinance, monkeypatch):
    import app.marketdata.yfinance_provider as yfp

    monkeypatch.setattr(yfp, "wall_now", lambda: NOON + timedelta(seconds=60))
    assert yfp.YFinanceProvider(cache_ttl_seconds=0).get_price("JPM", as_of=NOON).price == 999.0
    monkeypatch.setattr(yfp, "wall_now", lambda: NOON + timedelta(seconds=61))
    assert yfp.YFinanceProvider(cache_ttl_seconds=0).get_price("JPM", as_of=NOON).price == 180.0


# --- through the API ----------------------------------------------------------

def test_a_feed_answering_from_the_future_is_502_and_stores_nothing(client, db, admin_key):
    session = db
    pod = create_pod(session, name="desk")
    fund_pod(session, pod_id=pod.id, delta=10_000.0,
             actor=get_or_create_system_agent(session), reason="seed")
    _, pm = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
    session.commit()
    set_provider(Rogue(ahead=timedelta(days=1)))
    assert client.get("/price/AAPL", headers=H(admin_key)).status_code == 502
    resp = client.post("/orders", headers=H(pm), json={
        "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "t"})
    assert resp.status_code == 502 and "no price" in resp.json()["detail"]
    assert client.get("/orders", headers=H(pm)).json() == []


@pytest.fixture
def honest_backtest(SessionFactory) -> Iterator[dict[str, str]]:
    session = SessionFactory()
    try:
        start_backtest(session, start=NOON)
        _, admin = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="desk")
        fund_pod(session, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(session), reason="seed")
        _, pm = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
        session.commit()
    finally:
        session.close()
    set_provider(HistoricalProvider({"JPM": {YESTERDAY: 180.0, DAY: 190.0}}))
    yield {"admin": admin, "pm": pm}
    set_clock(LiveClock())


def test_a_backtest_is_honest_now(honest_backtest, client, db):
    """At simulated noon a PM sees, and trades at, yesterday's close; today's
    close appears only once the clock has passed the end of today."""
    assert LOOK_AHEAD_GUARD is True
    pm, admin = honest_backtest["pm"], honest_backtest["admin"]
    assert client.get("/price/JPM", headers=H(pm)).json()["price"] == 180.0
    bars = client.get("/ohlcv/JPM", headers=H(pm)).json()["bars"]
    assert [b["close"] for b in bars] == [180.0]
    fill = client.post("/orders", headers=H(pm), json={
        "ticker": "JPM", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "t"}).json()
    assert (fill["status"], fill["fill_price"]) == ("filled", 180.0)

    assert client.post("/clock/advance", headers=H(admin),
                       json={"minutes": 12 * 60}).status_code == 200
    assert client.get("/price/JPM", headers=H(pm)).json()["price"] == 190.0
    bars = client.get("/ohlcv/JPM", headers=H(pm)).json()["bars"]
    assert [b["close"] for b in bars] == [180.0, 190.0]
