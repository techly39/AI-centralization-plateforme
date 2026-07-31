"""Fee arithmetic (TRD §8.2), pinned at the unit level.

The API tests prove fees reach the balance; these prove the numbers themselves,
including the rounding rule, so a future change to the fee model breaks here
first — with an obvious message — rather than in a portfolio total.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.oms.money import (
    buy_cost,
    fee_for,
    notional,
    realized_pnl,
    round_money,
    sell_proceeds,
)

FEE = 0.001  # the configured default: 0.1%


def test_default_fee_rate_is_ten_basis_points():
    assert get_settings().oms.fee_rate == FEE


@pytest.mark.parametrize(
    ("qty", "price", "expected_fee"),
    [
        (10, 200.0, 2.0),        # 2_000 × 0.1%
        (1, 1.0, 0.0),           # rounds to zero cents — a fee, not a minimum
        (3, 33.335, 0.10),       # 100.005 × 0.1% = 0.100005 → 0.10
        (1000, 100.0, 100.0),
    ],
)
def test_fee_is_a_fraction_of_notional_rounded_to_cents(qty, price, expected_fee):
    assert fee_for(qty, price, FEE) == expected_fee


def test_buy_costs_notional_plus_fee():
    total, fee = buy_cost(10, 200.0, FEE)
    assert fee == 2.0
    assert total == 2_002.0
    assert total == notional(10, 200.0) + fee


def test_sell_yields_notional_minus_fee():
    proceeds, fee = sell_proceeds(10, 250.0, FEE)
    assert fee == 2.5
    assert proceeds == 2_497.5


def test_both_sides_are_charged():
    """A round trip at an unchanged price must lose exactly two fees."""
    buy_total, buy_fee = buy_cost(10, 200.0, FEE)
    sell_total, sell_fee = sell_proceeds(10, 200.0, FEE)
    assert round_money(sell_total - buy_total) == round_money(-(buy_fee + sell_fee))


def test_realized_pnl_is_net_of_the_exit_fee():
    _, fee = sell_proceeds(4, 250.0, FEE)
    # 4 × (250 − 200) = 200 gross, minus the $1.00 exit fee.
    assert realized_pnl(4, 250.0, 200.0, fee) == 199.0


def test_realized_pnl_can_be_negative():
    _, fee = sell_proceeds(10, 150.0, FEE)
    assert realized_pnl(10, 150.0, 200.0, fee) == -501.5


def test_zero_fee_rate_is_supported():
    total, fee = buy_cost(10, 200.0, 0.0)
    assert (total, fee) == (2_000.0, 0.0)


def test_fee_rate_is_configurable_end_to_end(client, desk, monkeypatch):
    """Changing the configured rate changes what the OMS actually charges."""
    _, _, pm_key = desk
    monkeypatch.setattr(get_settings().oms, "fee_rate", 0.01)  # 1%

    resp = client.post(
        "/orders",
        headers={"X-API-Key": pm_key},
        json={"ticker": "AAPL", "side": "buy", "qty": 10,
              "price_type": "market", "justification": "fee check"},
    )
    assert resp.json()["fee"] == 20.0  # 2_000 × 1%
