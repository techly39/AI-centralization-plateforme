"""Metrics endpoints and the equity curve behind them (TRD §7).

The statistics themselves are pinned in ``test_performance_math.py``. What is
tested here is everything between the ledger and those formulas: that a pod's
history is reconstructed correctly day by day, that self-reported cost actually
lands on the headline number, and that only management can look.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.clock import get_clock
from app.marketdata import set_provider
from app.metrics.equity import build_equity_curve
from tests.support import HistoricalProvider, straight_line

DAY_ONE = date(2026, 6, 1)


@pytest.fixture
def history(frozen_clock):
    """A market with a real past, installed as the app's provider.

    AAPL rises 100 → 110 over four sessions; MSFT is flat at 400.
    """
    provider = HistoricalProvider(
        {
            "AAPL": straight_line(DAY_ONE, [100.0, 105.0, 102.0, 110.0]),
            "MSFT": straight_line(DAY_ONE, [400.0, 400.0, 400.0, 400.0]),
        }
    )
    frozen_clock.set(datetime(DAY_ONE.year, DAY_ONE.month, DAY_ONE.day, 15, 0, tzinfo=timezone.utc))
    set_provider(provider)
    yield provider
    set_provider(None)


@pytest.fixture
def desk(history, client, make_pod, fund_pod_cash, pm_factory):
    """The shared ``desk`` fixture, but funded *after* the clock is frozen.

    Ordering matters more here than anywhere else in the suite: an equity curve
    is a replay of the ledger by date, so a pod funded under the live clock and
    then measured under a frozen one has its own funding in its future. Declaring
    ``history`` first is what guarantees the whole desk exists on day one.
    """
    pod_id = make_pod(1)
    fund_pod_cash(pod_id, 100_000.0)
    pm_id, pm_key = pm_factory("pm-1", pod_id)
    return pod_id, pm_id, pm_key


def order(client, key, **body):
    resp = client.post(
        "/orders", headers={"X-API-Key": key}, json={"justification": "test", **body}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def metrics(client, key, pod_id):
    resp = client.get(f"/metrics/pod/{pod_id}", headers={"X-API-Key": key})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- The equity curve -------------------------------------------------------

def test_curve_follows_the_market_day_by_day(
    client, db, desk, history, frozen_clock
):
    """Buy on day one, hold, and the curve should track the price each day."""
    pod_id, _, pm_key = desk
    order(client, pm_key, ticker="AAPL", side="buy", qty=100, price_type="market")

    frozen_clock.advance(days=3)
    curve = build_equity_curve(
        db, pod_id=pod_id, provider=history, as_of=get_clock().now()
    )

    assert [p.on for p in curve.points] == [DAY_ONE + timedelta(days=i) for i in range(4)]
    # Cash after 100 shares at $100 plus the 0.1% fee: 100000 - 10000 - 10 = 89990.
    assert curve.points[0].equity == pytest.approx(89_990.0 + 100 * 100.0)
    assert curve.points[1].equity == pytest.approx(89_990.0 + 100 * 105.0)
    assert curve.points[3].equity == pytest.approx(89_990.0 + 100 * 110.0)
    assert curve.fully_priced


def test_curve_records_the_allocation_as_a_flow_not_a_gain(
    client, db, desk, history, frozen_clock, fund_pod_cash
):
    pod_id, _, _ = desk
    frozen_clock.advance(days=1)
    fund_pod_cash(pod_id, 50_000.0)
    frozen_clock.advance(days=1)

    curve = build_equity_curve(
        db, pod_id=pod_id, provider=history, as_of=get_clock().now()
    )
    flows = {p.on: p.net_flow for p in curve.points}
    assert flows[DAY_ONE] == 100_000.0          # the desk fixture's own funding
    assert flows[DAY_ONE + timedelta(days=1)] == 50_000.0
    assert flows[DAY_ONE + timedelta(days=2)] == 0.0


def test_an_unpriceable_holding_is_carried_at_cost_and_flagged(
    client, db, desk, history, frozen_clock
):
    """One dead symbol must not blank out the whole report."""
    pod_id, _, pm_key = desk
    history.set_price("ZZZZ", DAY_ONE, 50.0)
    order(client, pm_key, ticker="ZZZZ", side="buy", qty=10, price_type="market")

    # Now the symbol goes dark: rebuild the provider without it.
    dark = HistoricalProvider({"AAPL": straight_line(DAY_ONE, [100.0, 105.0])})
    frozen_clock.advance(days=1)
    curve = build_equity_curve(db, pod_id=pod_id, provider=dark, as_of=get_clock().now())

    assert curve.pricing_errors == ["ZZZZ"]
    assert not curve.fully_priced
    # 10 shares still valued, at the $50 they cost.
    assert curve.points[-1].equity == pytest.approx(99_499.5 + 10 * 50.0)


def test_a_pod_with_no_history_has_an_empty_curve(db, make_pod, history):
    make_pod(9)
    curve = build_equity_curve(
        db, pod_id=9, provider=history, as_of=get_clock().now()
    )
    assert curve.points == []


# --- The pod metrics endpoint ----------------------------------------------

def test_pod_metrics_reports_return_sharpe_and_drawdown(
    client, admin_key, desk, history, frozen_clock
):
    pod_id, _, pm_key = desk
    order(client, pm_key, ticker="AAPL", side="buy", qty=100, price_type="market")
    frozen_clock.advance(days=3)

    body = metrics(client, admin_key, pod_id)
    perf = body["performance"]

    assert body["capital"]["net_contributed"] == 100_000.0
    assert body["capital"]["total_value"] == pytest.approx(89_990.0 + 11_000.0)
    # Gained $1,000 on the position, paid $10 in fees.
    assert perf["pnl"] == pytest.approx(990.0)
    assert perf["unrealized_pnl"] == pytest.approx(1_000.0)
    assert perf["fees_paid"] == pytest.approx(10.0)
    assert perf["observations"] == 4

    # Time-weighted return is growth from the *first close*, so it is not
    # pnl/contributed: day one's entry fee was paid before there was a prior
    # equity to measure against, and no return series can include it. 99,990
    # on day one grows to 100,990 on day four.
    assert perf["total_return"] == pytest.approx(100_990.0 / 99_990.0 - 1, rel=1e-9)
    assert perf["sharpe_daily"] is not None
    assert perf["max_drawdown"] < 0  # the dip on day three
    assert perf["fully_priced"]


def test_statistics_are_null_not_zero_on_the_first_day(
    client, admin_key, desk, history
):
    """One observation is not a flat return — it is no return yet."""
    pod_id, _, pm_key = desk
    order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")

    perf = metrics(client, admin_key, pod_id)["performance"]
    assert perf["observations"] == 1
    assert perf["total_return"] is None
    assert perf["sharpe_daily"] is None
    assert perf["hit_rate"] is None


def test_hit_rate_counts_closed_trades_only(
    client, admin_key, desk, history, frozen_clock
):
    pod_id, _, pm_key = desk
    order(client, pm_key, ticker="AAPL", side="buy", qty=100, price_type="market")
    order(client, pm_key, ticker="MSFT", side="buy", qty=10, price_type="market")

    frozen_clock.advance(days=3)  # AAPL 100 -> 110, MSFT flat
    order(client, pm_key, ticker="AAPL", side="sell", qty=50, price_type="market")
    order(client, pm_key, ticker="MSFT", side="sell", qty=10, price_type="market")

    perf = metrics(client, admin_key, pod_id)["performance"]
    assert perf["closed_trades"] == 2
    assert perf["winning_trades"] == 1     # AAPL up, MSFT flat minus its fee
    assert perf["hit_rate"] == pytest.approx(0.5)
    assert perf["realized_pnl"] > 0


# --- Cost and activity ------------------------------------------------------

def test_cost_reports_reduce_the_headline_number(
    client, admin_key, desk, history, frozen_clock
):
    pod_id, _, pm_key = desk
    order(client, pm_key, ticker="AAPL", side="buy", qty=100, price_type="market")
    frozen_clock.advance(days=3)

    before = metrics(client, admin_key, pod_id)
    assert before["cost"]["reports"] == 0
    assert before["cost_adjusted_pnl"] == before["performance"]["pnl"]

    client.post(
        "/costs",
        headers={"X-API-Key": pm_key},
        json={"tokens_in": 50_000, "tokens_out": 8_000, "usd_cost": 12.50,
              "task_label": "research"},
    )

    after = metrics(client, admin_key, pod_id)
    assert after["cost"]["total_usd_cost"] == 12.50
    assert after["cost"]["tokens_in"] == 50_000
    assert after["cost"]["reports"] == 1
    assert after["cost_adjusted_pnl"] == pytest.approx(after["performance"]["pnl"] - 12.50)


def test_activity_counts_tasks_time_per_subject_and_messages(
    client, admin_key, desk, agent_factory, history, frozen_clock
):
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    def work(key, subject, minutes):
        task_id = client.post(
            "/tasks/start", headers={"X-API-Key": key}, json={"subject": subject}
        ).json()["id"]
        frozen_clock.advance(minutes=minutes)
        client.post(
            "/tasks/end",
            headers={"X-API-Key": key},
            json={"task_id": task_id, "outcome": {"summary": "done"}},
        )

    work(analyst_key, "earnings review", 30)
    work(analyst_key, "earnings review", 20)
    work(pm_key, "position sizing", 10)
    # One left open, to prove open and closed are counted separately.
    client.post("/tasks/start", headers={"X-API-Key": pm_key}, json={"subject": "idea log"})

    client.post(
        "/messages",
        headers={"X-API-Key": analyst_key},
        json={"to": f"agent:{pm_id}", "body": "buy AAPL"},
    )

    activity = metrics(client, admin_key, pod_id)["activity"]
    assert activity["tasks_opened"] == 4
    assert activity["tasks_closed"] == 3
    assert activity["tasks_open"] == 1
    # Biggest time sink first, so the report answers "where did the hours go".
    assert [s["subject"] for s in activity["time_per_subject"]] == [
        "earnings review",
        "position sizing",
    ]
    assert activity["time_per_subject"][0]["seconds"] == 3000.0
    assert activity["time_per_subject"][0]["tasks"] == 2
    assert activity["messages_sent"] == 1


def test_order_counts_include_rejections(client, admin_key, desk, history):
    pod_id, _, pm_key = desk
    order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")
    order(client, pm_key, ticker="AAPL", side="buy", qty=1_000_000, price_type="market")
    order(client, pm_key, ticker="AAPL", side="buy", qty=1, price_type="limit",
          limit_price=1.0)

    activity = metrics(client, admin_key, pod_id)["activity"]
    assert activity["orders_placed"] == 3
    assert activity["orders_filled"] == 1
    assert activity["orders_rejected"] == 1
    assert activity["orders_pending"] == 1


# --- Leaderboard ------------------------------------------------------------

def test_leaderboard_ranks_by_cost_adjusted_pnl(
    client, admin_key, desk, agent_factory, make_pod, fund_pod_cash, history,
    frozen_clock,
):
    """The pod that made more money can still rank lower if it cost more."""
    pod_1, _, key_1 = desk
    make_pod(2)
    fund_pod_cash(2, 100_000.0)
    _, key_2 = agent_factory("pm-2", "pm", 2)

    order(client, key_1, ticker="AAPL", side="buy", qty=100, price_type="market")
    order(client, key_2, ticker="AAPL", side="buy", qty=50, price_type="market")
    frozen_clock.advance(days=3)

    # Pod 1 gains twice as much but burns far more on tokens.
    client.post("/costs", headers={"X-API-Key": key_1},
                json={"tokens_in": 0, "tokens_out": 0, "usd_cost": 900.0})
    client.post("/costs", headers={"X-API-Key": key_2},
                json={"tokens_in": 0, "tokens_out": 0, "usd_cost": 10.0})

    resp = client.get("/metrics/leaderboard", headers={"X-API-Key": admin_key})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]

    assert [r["pod_id"] for r in rows] == [2, pod_1]
    assert rows[1]["pnl"] > rows[0]["pnl"]                       # pod 1 earned more
    assert rows[0]["cost_adjusted_pnl"] > rows[1]["cost_adjusted_pnl"]  # ...and still lost


def test_leaderboard_includes_pods_that_have_done_nothing(
    client, admin_key, make_pod, history
):
    make_pod(7)
    rows = client.get(
        "/metrics/leaderboard", headers={"X-API-Key": admin_key}
    ).json()["rows"]
    assert [r["pod_id"] for r in rows] == [7]
    assert rows[0]["total_return"] is None


# --- Access -----------------------------------------------------------------

def test_metrics_are_management_only(client, desk, agent_factory, history):
    pod_id, _, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    for key in (pm_key, analyst_key):
        assert client.get(f"/metrics/pod/{pod_id}", headers={"X-API-Key": key}).status_code == 403
        assert client.get("/metrics/leaderboard", headers={"X-API-Key": key}).status_code == 403


def test_metrics_for_an_unknown_pod_is_a_404(client, admin_key, history):
    assert client.get("/metrics/pod/404", headers={"X-API-Key": admin_key}).status_code == 404
