"""The seeded synthetic market (B-004c, ADR-030): a pure function of (seed, symbol, day)."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import MarketDataConfig
from app.marketdata import base as md_base
from app.marketdata import InvalidRequestError, SyntheticProvider, UnknownTickerError
from app.marketdata.synthetic_provider import ORIGIN

SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0}
NOON = datetime(2024, 3, 13, 12, 0, tzinfo=timezone.utc)  # a Wednesday


def daily(provider, start, end, as_of=NOON, symbol="SYNA"):
    return provider.get_ohlcv(symbol, start=start, end=end, interval="1d", as_of=as_of)


def test_same_seed_same_bars_whatever_was_asked_first():
    late_first = SyntheticProvider(7, SYMBOLS)
    daily(late_first, date(2024, 3, 1), date(2024, 3, 13))
    early_only = SyntheticProvider(7, SYMBOLS)
    assert daily(early_only, date(2024, 2, 1), date(2024, 3, 13)) == daily(
        late_first, date(2024, 2, 1), date(2024, 3, 13)
    )


def test_another_seed_is_another_market():
    a = daily(SyntheticProvider(1, SYMBOLS), date(2024, 3, 1), date(2024, 3, 13))
    b = daily(SyntheticProvider(2, SYMBOLS), date(2024, 3, 1), date(2024, 3, 13))
    assert [x.close for x in a] != [x.close for x in b]


def test_symbols_walk_independently():
    p = SyntheticProvider(1, {"SYNA": 100.0, "SYNB": 100.0})
    a = daily(p, date(2024, 3, 1), date(2024, 3, 13), symbol="SYNA")
    b = daily(p, date(2024, 3, 1), date(2024, 3, 13), symbol="SYNB")
    assert [x.close for x in a] != [x.close for x in b]


def test_the_walk_is_pinned():
    """A golden value: any change to the formula (hash, Box-Muller, drift) shows here.

    Changing it changes every synthetic backtest ever run — that is an ADR, not
    a test edit.
    """
    bar = daily(SyntheticProvider(0, {"SYNA": 100.0}), date(2024, 1, 2), date(2024, 1, 3))[0]
    assert bar.close == pytest.approx(GOLDEN_SEED0_SYNA_2024_01_02, rel=1e-12)


GOLDEN_SEED0_SYNA_2024_01_02 = 524.2858206783762


def test_bars_are_well_formed_and_chained():
    bars = daily(SyntheticProvider(3, SYMBOLS), date(2023, 12, 1), date(2024, 3, 13))
    assert len(bars) == (date(2024, 3, 13) - date(2023, 12, 1)).days
    for prev, bar in zip(bars, bars[1:]):
        assert bar.ts - prev.ts == timedelta(days=1)
        assert bar.open == prev.close
    for bar in bars:
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        assert all(math.isfinite(v) and v > 0 for v in values)
        assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        assert bar.ts.tzinfo is not None and bar.ts.time() == datetime.min.time()


def test_the_first_bar_opens_at_the_start_price():
    p = SyntheticProvider(3, SYMBOLS)
    first = daily(p, ORIGIN - timedelta(days=5), ORIGIN + timedelta(days=1),
                  as_of=datetime(2000, 1, 2, tzinfo=timezone.utc))
    assert [b.ts.date() for b in first] == [ORIGIN] and first[0].open == 100.0


def test_a_quote_is_the_last_ended_close_stamped_at_its_end():
    p = SyntheticProvider(3, SYMBOLS)
    quote = p.get_price("syna", as_of=NOON)
    yesterday = daily(p, date(2024, 3, 12), date(2024, 3, 14))
    assert [b.ts.date() for b in yesterday] == [date(2024, 3, 12)]  # today not ended
    assert quote.price == yesterday[0].close
    assert quote.as_of == datetime(2024, 3, 13, tzinfo=timezone.utc)
    assert quote.source == "synthetic" and quote.ticker == "SYNA"


def test_a_quote_at_midnight_sees_the_day_that_just_ended():
    p = SyntheticProvider(3, SYMBOLS)
    midnight = datetime(2024, 3, 13, tzinfo=timezone.utc)
    quote = p.get_price("SYNA", as_of=midnight)
    assert quote.as_of == midnight
    assert quote.price == daily(p, date(2024, 3, 12), date(2024, 3, 13), as_of=midnight)[0].close


def test_a_quote_does_not_depend_on_the_as_of_timezone():
    p = SyntheticProvider(3, SYMBOLS)
    est = timezone(timedelta(hours=-5))
    assert p.get_price("SYNA", as_of=NOON) == p.get_price("SYNA", as_of=NOON.astimezone(est))


def test_weeks_and_months_aggregate_the_days():
    p = SyntheticProvider(3, SYMBOLS)
    days = daily(p, date(2024, 1, 1), date(2024, 3, 1))
    weeks = p.get_ohlcv("SYNA", start=date(2024, 1, 1), end=date(2024, 3, 1),
                        interval="1wk", as_of=NOON)
    first_week = days[:7]  # 2024-01-01 is a Monday
    assert weeks[0].ts.date() == date(2024, 1, 1)
    assert weeks[0].open == first_week[0].open and weeks[0].close == first_week[-1].close
    assert weeks[0].high == max(b.high for b in first_week)
    assert weeks[0].low == min(b.low for b in first_week)
    assert weeks[0].volume == sum(b.volume for b in first_week)
    assert all(w.ts.weekday() == 0 for w in weeks)
    months = p.get_ohlcv("SYNA", start=date(2024, 1, 1), end=date(2024, 3, 14),
                         interval="1mo", as_of=NOON)
    # March has not ended at NOON: only January and February are served.
    assert [m.ts.date() for m in months] == [date(2024, 1, 1), date(2024, 2, 1)]
    assert months[1].close == days[-1].close


def test_a_week_still_running_is_not_served():
    p = SyntheticProvider(3, SYMBOLS)
    weeks = p.get_ohlcv("SYNA", start=date(2024, 3, 4), end=date(2024, 3, 14),
                        interval="1wk", as_of=NOON)
    assert [w.ts.date() for w in weeks] == [date(2024, 3, 4)]


def test_there_are_no_intraday_bars():
    with pytest.raises(InvalidRequestError, match="daily bars only"):
        SyntheticProvider(3, SYMBOLS).get_ohlcv(
            "SYNA", start=date(2024, 3, 1), end=date(2024, 3, 13), interval="1h", as_of=NOON
        )


def test_only_configured_symbols_exist():
    p = SyntheticProvider(3, SYMBOLS)
    with pytest.raises(UnknownTickerError):
        p.get_price("AAPL", as_of=NOON)
    with pytest.raises(UnknownTickerError):
        daily(p, date(2024, 3, 1), date(2024, 3, 13), symbol="AAPL")


def test_nothing_before_the_origin():
    p = SyntheticProvider(3, SYMBOLS)
    with pytest.raises(UnknownTickerError):
        p.get_price("SYNA", as_of=datetime(2000, 1, 1, 12, tzinfo=timezone.utc))


def test_the_provider_answers_under_the_look_ahead_law():
    """It is a sealed MarketDataProvider: its entries are the base's."""
    for name in ("get_price", "get_ohlcv"):
        assert getattr(SyntheticProvider, name) is getattr(md_base.MarketDataProvider, name)


@pytest.mark.parametrize("kwargs", [
    {"seed": -1}, {"seed": 1.5}, {"seed": True},
    {"symbols": {"SYNA": 0.0}}, {"symbols": {"SYNA": float("nan")}},
    {"symbols": {"SYNA": float("inf")}}, {"symbols": {"": 1.0}},
    {"drift": float("nan")}, {"drift": 0.5}, {"volatility": -0.1},
    {"volatility": float("inf")},
])
def test_refuses_a_bad_world(kwargs):
    args = {"seed": 1, "symbols": SYMBOLS} | kwargs
    seed, symbols = args.pop("seed"), args.pop("symbols")
    with pytest.raises((ValueError, InvalidRequestError)):
        SyntheticProvider(seed, symbols, **args)


def test_config_selects_it(monkeypatch):
    from app import marketdata

    cfg = MarketDataConfig(provider="synthetic", synthetic_seed=5,
                           synthetic_symbols={"ZZZ": 10.0})
    monkeypatch.setattr(marketdata, "get_settings",
                        lambda: type("S", (), {"marketdata": cfg})())
    provider = marketdata._build_default_provider()
    assert isinstance(provider, SyntheticProvider) and provider.seed == 5
    assert provider.get_price("ZZZ", as_of=NOON).source == "synthetic"
