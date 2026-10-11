"""Market data: the interface contract, the endpoints, and the look-ahead guard.

No test here touches the network. The yfinance provider is exercised against a
stubbed ``yfinance`` module so its parsing and error mapping are covered without
making the suite depend on Yahoo being up — a test that fails because a website
is slow teaches nobody anything.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.marketdata import (
    InvalidRequestError,
    LookAheadError,
    StaticProvider,
    UnknownTickerError,
    normalise_ticker,
    validate_window,
)

NOW = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)


# --- Shared contract --------------------------------------------------------

def test_tickers_are_normalised():
    assert normalise_ticker("  aapl\n") == "AAPL"
    with pytest.raises(InvalidRequestError):
        normalise_ticker("   ")
    with pytest.raises(InvalidRequestError):
        normalise_ticker("A" * 17)


def test_window_validation_rejects_unknown_intervals():
    with pytest.raises(InvalidRequestError):
        validate_window(date(2026, 1, 1), date(2026, 2, 1), "3s", NOW)


def test_window_validation_rejects_reversed_ranges():
    with pytest.raises(InvalidRequestError):
        validate_window(date(2026, 2, 1), date(2026, 1, 1), "1d", NOW)


def test_window_validation_rejects_the_future():
    """The guarantee Phase 3's backtests depend on, enforced from day one."""
    with pytest.raises(LookAheadError):
        validate_window(date(2026, 8, 5), date(2026, 8, 10), "1d", NOW)


# --- Static provider --------------------------------------------------------

def test_static_provider_serves_and_updates_prices():
    provider = StaticProvider({"aapl": 200.0})
    assert provider.get_price("AAPL", as_of=NOW).price == 200.0
    provider.set_price("AAPL", 210.0)
    assert provider.get_price("aapl", as_of=NOW).price == 210.0


def test_static_provider_raises_for_unknown_symbols():
    with pytest.raises(UnknownTickerError):
        StaticProvider().get_price("AAPL", as_of=NOW)


def test_static_provider_never_returns_bars_after_now():
    provider = StaticProvider({"AAPL": 200.0})
    bars = provider.get_ohlcv(
        "AAPL",
        start=NOW.date() - timedelta(days=3),
        end=NOW.date() + timedelta(days=3),
        interval="1d",
        as_of=NOW,
    )
    assert bars
    assert all(bar.ts <= NOW for bar in bars)


# --- yfinance provider (against a stub) -------------------------------------

class _FakeFastInfo(dict):
    pass


class _FakeTicker:
    def __init__(self, last_price=None, frame=None, raises=False):
        self._last_price = last_price
        self._frame = frame
        self._raises = raises

    @property
    def fast_info(self):
        if self._raises or self._last_price is None:
            raise KeyError("exchangeTimezoneName")
        return _FakeFastInfo({"lastPrice": self._last_price, "currency": "USD"})

    def history(self, **_kwargs):
        if self._frame is None:
            import pandas as pd

            return pd.DataFrame()
        return self._frame


@pytest.fixture
def stub_yfinance(monkeypatch):
    """Install a fake ``yfinance`` module the provider will import."""
    import sys
    import types

    module = types.ModuleType("yfinance")
    holder: dict[str, object] = {}

    def Ticker(symbol):  # noqa: N802 - mirrors the real API's name
        return holder.get("ticker", _FakeTicker())

    module.Ticker = Ticker
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return holder


@pytest.fixture
def real_now_is_now(monkeypatch):
    """Make NOW the real now, so the provider's live quote may answer it.

    Before ADR-028 these tests asked yfinance's *current* quote for a NOW months
    in the past and got it — the look-ahead of SURVEY §4a.3. A live quote now
    answers only an ``as_of`` at the real now; older ones come from history.
    """
    import app.marketdata.yfinance_provider as yfp

    monkeypatch.setattr(yfp, "wall_now", lambda: NOW)


def test_yfinance_provider_prefers_the_quote_endpoint(stub_yfinance, real_now_is_now):
    from app.marketdata import YFinanceProvider

    stub_yfinance["ticker"] = _FakeTicker(last_price=123.45)
    quote = YFinanceProvider(cache_ttl_seconds=0).get_price("aapl", as_of=NOW)
    assert quote.ticker == "AAPL"
    assert quote.price == 123.45
    assert quote.source == "yfinance"


def test_yfinance_provider_falls_back_to_history(stub_yfinance, real_now_is_now):
    import pandas as pd

    from app.marketdata import YFinanceProvider

    frame = pd.DataFrame(
        {"Close": [98.0, 99.5]},
        index=pd.to_datetime(["2026-07-29", "2026-07-30"]).tz_localize("UTC"),
    )
    stub_yfinance["ticker"] = _FakeTicker(last_price=None, frame=frame)
    quote = YFinanceProvider(cache_ttl_seconds=0).get_price("AAPL", as_of=NOW)
    # Live: the last row is today's bar still trading, its close the current
    # price — stamped at the moment asked, not at the bar's 00:00 open.
    assert quote.price == 99.5
    assert quote.as_of == NOW


def test_yfinance_reports_unknown_tickers_live(stub_yfinance, real_now_is_now):
    from app.marketdata import YFinanceProvider

    stub_yfinance["ticker"] = _FakeTicker(last_price=None, frame=None)
    with pytest.raises(UnknownTickerError):
        YFinanceProvider(cache_ttl_seconds=0).get_price("NOPE", as_of=NOW)


def test_yfinance_provider_reports_unknown_tickers(stub_yfinance):
    from app.marketdata import YFinanceProvider

    stub_yfinance["ticker"] = _FakeTicker(last_price=None, frame=None)
    with pytest.raises(UnknownTickerError):
        YFinanceProvider(cache_ttl_seconds=0).get_price("NOPE", as_of=NOW)


def test_quote_cache_is_driven_by_the_clock_not_wall_time(stub_yfinance, real_now_is_now):
    from app.marketdata import YFinanceProvider

    provider = YFinanceProvider(cache_ttl_seconds=60)
    stub_yfinance["ticker"] = _FakeTicker(last_price=100.0)
    assert provider.get_price("AAPL", as_of=NOW).price == 100.0

    # Price moves upstream, but the clock has barely advanced: cached.
    stub_yfinance["ticker"] = _FakeTicker(last_price=150.0)
    assert provider.get_price("AAPL", as_of=NOW + timedelta(seconds=30)).price == 100.0

    # Clock advances past the TTL: refetched.
    assert provider.get_price("AAPL", as_of=NOW + timedelta(seconds=90)).price == 150.0

    # A clock that jumps backwards (mode switch, replay) must invalidate too.
    # (A step back within the live window: a day back is answered from history
    # since ADR-028, which test_yfinance_answers_the_past_from_history covers.)
    stub_yfinance["ticker"] = _FakeTicker(last_price=42.0)
    assert provider.get_price("AAPL", as_of=NOW - timedelta(seconds=30)).price == 42.0


def test_yfinance_history_drops_bars_after_as_of(stub_yfinance):
    import pandas as pd

    from app.marketdata import YFinanceProvider

    frame = pd.DataFrame(
        {
            "Open": [1.0, 2.0, 3.0],
            "High": [1.0, 2.0, 3.0],
            "Low": [1.0, 2.0, 3.0],
            "Close": [1.0, 2.0, 3.0],
            "Volume": [10, 20, 30],
        },
        index=pd.to_datetime(
            ["2026-07-29", "2026-07-30", "2026-07-31"]
        ).tz_localize("UTC"),
    )
    stub_yfinance["ticker"] = _FakeTicker(frame=frame, last_price=1.0)
    bars = YFinanceProvider(cache_ttl_seconds=0).get_ohlcv(
        "AAPL",
        start=date(2026, 7, 29),
        end=date(2026, 8, 1),
        interval="1d",
        as_of=NOW,  # 2026-07-30 15:00 UTC
    )
    # Only 07-29 had ended. The 07-30 bar (opened 00:00, carrying that day's
    # close) used to be served at 15:00 — the leak of SURVEY §4a.2 (ADR-028).
    assert [bar.close for bar in bars] == [1.0]


# --- Endpoints --------------------------------------------------------------

def test_price_endpoint_serves_every_role(client, admin_key):
    for role in ("analyst", "pm", "management"):
        key = admin_key if role == "management" else client.post(
            "/agents/register",
            headers={"X-API-Key": admin_key},
            json={"name": f"{role}-md", "role": role},
        ).json()["api_key"]
        resp = client.get("/price/AAPL", headers={"X-API-Key": key})
        assert resp.status_code == 200, resp.text
        assert resp.json()["price"] == 200.0


def test_price_endpoint_requires_authentication(client):
    assert client.get("/price/AAPL").status_code == 401


def test_unknown_ticker_is_404(client, admin_key):
    resp = client.get("/price/NOSUCH", headers={"X-API-Key": admin_key})
    assert resp.status_code == 404


def test_ohlcv_endpoint_returns_bars(client, admin_key):
    resp = client.get(
        "/ohlcv/AAPL",
        headers={"X-API-Key": admin_key},
        params={"start": "2026-07-01", "end": "2026-07-05", "interval": "1d"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert len(body["bars"]) == 4


def test_ohlcv_rejects_a_bad_interval(client, admin_key):
    resp = client.get(
        "/ohlcv/AAPL", headers={"X-API-Key": admin_key}, params={"interval": "7s"}
    )
    assert resp.status_code == 400


def test_ohlcv_rejects_a_future_window(client, admin_key):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).date()
    resp = client.get(
        "/ohlcv/AAPL",
        headers={"X-API-Key": admin_key},
        params={"start": future.isoformat(), "end": (future + timedelta(days=5)).isoformat()},
    )
    assert resp.status_code == 400
