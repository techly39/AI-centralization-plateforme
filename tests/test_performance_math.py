"""The performance formulas, pinned (TRD §7).

These are the numbers management will use to close a pod down, so each one is
tested against a case whose answer can be worked out by hand. The most important
assertions here are the ones about what *should not* count: capital handed to a
pod is not a return, and a statistic with too little data is null, not zero.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.metrics.performance import (
    EquityPoint,
    annualise,
    compound,
    daily_returns,
    hit_rate,
    max_drawdown,
    sharpe_daily,
)

START = date(2026, 6, 1)


def curve(*pairs: tuple[float, float]) -> list[EquityPoint]:
    """``curve((100, 0), (110, 0))`` → two days of equity with their flows."""
    return [
        EquityPoint(on=START + timedelta(days=i), equity=equity, net_flow=flow)
        for i, (equity, flow) in enumerate(pairs)
    ]


# --- Returns ----------------------------------------------------------------

def test_simple_daily_returns():
    assert daily_returns(curve((100.0, 0.0), (110.0, 0.0), (99.0, 0.0))) == pytest.approx(
        [0.10, -0.10]
    )


def test_capital_added_is_not_a_return():
    """A pod handed $50 did not earn 50%. This is the whole reason for TWR."""
    # Day 2: equity jumps 100 -> 150, but 50 of that was an allocation.
    assert daily_returns(curve((100.0, 0.0), (150.0, 50.0))) == pytest.approx([0.0])


def test_capital_withdrawn_is_not_a_loss():
    assert daily_returns(curve((100.0, 0.0), (60.0, -40.0))) == pytest.approx([0.0])


def test_a_pod_with_no_capital_has_no_return_rather_than_a_made_up_one():
    # Dividing by a zero starting equity would produce infinity, not information.
    assert daily_returns(curve((0.0, 0.0), (100.0, 100.0))) == []


def test_single_observation_yields_no_returns():
    assert daily_returns(curve((100.0, 0.0))) == []


def test_total_return_compounds():
    # +10% then +10% is +21%, not +20%.
    assert compound([0.1, 0.1]) == pytest.approx(0.21)
    assert compound([]) == 0.0


# --- Sharpe -----------------------------------------------------------------

def test_sharpe_is_mean_over_volatility():
    returns = [0.01, -0.01, 0.02, 0.00]
    expected = (sum(returns) / 4) / _sample_stdev(returns)
    assert sharpe_daily(returns) == pytest.approx(expected)


def test_sharpe_subtracts_the_risk_free_rate():
    returns = [0.01, 0.02, 0.03]
    assert sharpe_daily(returns, risk_free_daily=0.01) < sharpe_daily(returns)


def test_sharpe_is_null_when_it_cannot_be_computed():
    assert sharpe_daily([]) is None
    assert sharpe_daily([0.01]) is None          # one point has no volatility
    assert sharpe_daily([0.01, 0.01, 0.01]) is None  # flat: undefined, not infinite


def test_annualisation_scales_by_root_trading_days():
    assert annualise(0.1, trading_days=252) == pytest.approx(0.1 * math.sqrt(252))
    assert annualise(None) is None


# --- Drawdown ---------------------------------------------------------------

def test_max_drawdown_measures_peak_to_trough():
    # +20%, then -50% from that peak.
    assert max_drawdown([0.2, -0.5]) == pytest.approx(-0.5)


def test_max_drawdown_of_a_rising_series_is_zero():
    assert max_drawdown([0.01, 0.02, 0.03]) == 0.0


def test_max_drawdown_finds_the_worst_fall_not_the_last_one():
    # Down 30%, recovers, then down 10%. The reported number is the 30%.
    assert max_drawdown([-0.3, 0.5, -0.1]) == pytest.approx(-0.3)


def test_max_drawdown_is_null_without_data():
    assert max_drawdown([]) is None


# --- Hit rate ---------------------------------------------------------------

def test_hit_rate_counts_only_closed_trades():
    assert hit_rate(wins=3, closed=5) == pytest.approx(0.6)


def test_hit_rate_is_null_before_anything_closed():
    """An open position is not a result yet; calling it 0% would be a lie."""
    assert hit_rate(wins=0, closed=0) is None


def _sample_stdev(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
