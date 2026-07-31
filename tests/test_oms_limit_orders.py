"""Limit orders: queuing, crossing, re-validation at fill, cancellation (§8.4).

The monitor is called explicitly here rather than waiting on the scheduler —
that is exactly how Phase 3's ``POST /clock/advance`` will drive it, so these
tests cover the backtest path too.
"""

from __future__ import annotations

from app.db.models import OrderStatus
from app.ledger.events import EVENT_ORDER_CANCELLED, EVENT_ORDER_FILLED, read_events
from app.oms.monitor import check_pending_orders


def _order(client, key, **body):
    payload = {"justification": "test thesis", **body}
    return client.post("/orders", headers={"X-API-Key": key}, json=payload)


# --- Queuing ----------------------------------------------------------------

def test_limit_order_is_queued_not_filled(client, desk, prices):
    pod_id, _, pm_key = desk
    prices.set_price("AAPL", 200.0)

    resp = _order(client, pm_key, ticker="AAPL", side="buy", qty=10,
                  price_type="limit", limit_price=180.0)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["fill_price"] is None

    # Cash is untouched while the order waits — the app does not reserve funds.
    portfolio = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    assert portfolio["cash"] == 100_000.0


def test_unaffordable_limit_order_is_rejected_at_placement(client, desk):
    _, _, pm_key = desk
    resp = _order(client, pm_key, ticker="AAPL", side="buy", qty=1000,
                  price_type="limit", limit_price=180.0)
    assert resp.json()["status"] == "rejected"


# --- Crossing ---------------------------------------------------------------

def test_buy_limit_fills_when_price_falls_to_it(client, desk, db, prices):
    pod_id, _, pm_key = desk
    order_id = _order(client, pm_key, ticker="AAPL", side="buy", qty=10,
                      price_type="limit", limit_price=180.0).json()["id"]

    # Still above the limit: nothing happens.
    prices.set_price("AAPL", 190.0)
    result = check_pending_orders(db)
    assert result.checked == 1
    assert result.filled == []

    # Market reaches the limit exactly.
    prices.set_price("AAPL", 180.0)
    result = check_pending_orders(db)
    assert result.filled == [order_id]

    order = client.get("/orders", headers={"X-API-Key": pm_key}).json()[0]
    assert order["status"] == "filled"
    assert order["fill_price"] == 180.0
    assert order["fee"] == 1.8  # 10 × 180 × 0.1%


def test_gap_through_the_limit_fills_at_the_better_market_price(client, desk, db, prices):
    _, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10,
           price_type="limit", limit_price=180.0)

    prices.set_price("AAPL", 150.0)  # gapped straight through
    check_pending_orders(db)

    order = client.get("/orders", headers={"X-API-Key": pm_key}).json()[0]
    assert order["fill_price"] == 150.0


def test_sell_limit_fills_when_price_rises_to_it(client, desk, db, prices):
    pod_id, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")

    _order(client, pm_key, ticker="AAPL", side="sell", qty=4,
           price_type="limit", limit_price=260.0)

    prices.set_price("AAPL", 250.0)
    assert check_pending_orders(db).filled == []

    prices.set_price("AAPL", 265.0)
    assert len(check_pending_orders(db).filled) == 1

    portfolio = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    assert portfolio["positions"][0]["qty"] == 6


def test_only_one_price_lookup_per_ticker_per_sweep(client, desk, db, prices, monkeypatch):
    _, _, pm_key = desk
    for limit in (150.0, 155.0, 160.0):
        _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
               price_type="limit", limit_price=limit)

    calls: list[str] = []
    original = prices.get_price

    def counting_get_price(ticker, *, as_of):
        calls.append(ticker)
        return original(ticker, as_of=as_of)

    monkeypatch.setattr(prices, "get_price", counting_get_price)
    check_pending_orders(db, provider=prices)
    assert calls == ["AAPL"]


# --- Re-validation at fill time (TRD §8.4) ----------------------------------

def test_pending_buy_is_rejected_if_cash_ran_out_meanwhile(client, desk, db, prices):
    """The classic hole: a limit order placed when the pod was rich, filling
    after the pod spent everything. It must reject, not overdraw."""
    pod_id, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=400,
           price_type="limit", limit_price=200.0)

    # Spend nearly all the cash on something else.
    prices.set_price("NVDA", 100.0)
    assert _order(client, pm_key, ticker="NVDA", side="buy", qty=950,
                  price_type="market").json()["status"] == "filled"

    prices.set_price("AAPL", 200.0)
    result = check_pending_orders(db)
    assert result.filled == []
    assert len(result.rejected) == 1

    order = next(
        o for o in client.get("/orders", headers={"X-API-Key": pm_key}).json()
        if o["ticker"] == "AAPL"
    )
    assert order["status"] == "rejected"
    assert "insufficient" in order["status_reason"].lower() or "holds" in order["status_reason"]

    portfolio = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    assert portfolio["cash"] >= 0


def test_pending_sell_is_rejected_if_shares_were_sold_meanwhile(client, desk, db, prices):
    _, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")
    _order(client, pm_key, ticker="AAPL", side="sell", qty=10,
           price_type="limit", limit_price=260.0)
    # Dump the position at market before the limit order gets its chance.
    _order(client, pm_key, ticker="AAPL", side="sell", qty=10, price_type="market")

    prices.set_price("AAPL", 300.0)
    result = check_pending_orders(db)
    assert len(result.rejected) == 1


def test_missing_price_leaves_the_order_pending(client, desk, db, prices):
    _, _, pm_key = desk
    order_id = _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
                      price_type="limit", limit_price=180.0).json()["id"]

    empty = type(prices)({})  # a provider that knows no prices at all
    result = check_pending_orders(db, provider=empty)
    assert result.unpriced == ["AAPL"]
    assert result.filled == []

    still_pending = client.get("/orders", headers={"X-API-Key": pm_key}).json()[0]
    assert still_pending["id"] == order_id
    assert still_pending["status"] == "pending"


# --- Cancellation -----------------------------------------------------------

def test_pm_can_cancel_a_pending_order(client, desk, db):
    _, _, pm_key = desk
    order_id = _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
                      price_type="limit", limit_price=180.0).json()["id"]

    resp = client.delete(f"/orders/{order_id}", headers={"X-API-Key": pm_key})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert len(read_events(db, type=EVENT_ORDER_CANCELLED)) == 1

    # A cancelled order is invisible to the monitor.
    assert check_pending_orders(db).checked == 0


def test_cancelling_a_filled_order_is_a_conflict(client, desk):
    _, _, pm_key = desk
    order_id = _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
                      price_type="market").json()["id"]
    resp = client.delete(f"/orders/{order_id}", headers={"X-API-Key": pm_key})
    assert resp.status_code == 409


def test_cancelling_an_unknown_order_is_404(client, desk):
    _, _, pm_key = desk
    assert client.delete("/orders/999", headers={"X-API-Key": pm_key}).status_code == 404


def test_a_pm_cannot_cancel_another_pods_order(
    client, desk, make_pod, fund_pod_cash, pm_factory, db
):
    _, _, pm_key = desk
    order_id = _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
                      price_type="limit", limit_price=180.0).json()["id"]

    make_pod(2)
    fund_pod_cash(2, 50_000.0)
    _, other_key = pm_factory("pm-2", 2)

    resp = client.delete(f"/orders/{order_id}", headers={"X-API-Key": other_key})
    assert resp.status_code == 403
    # The order is untouched.
    assert client.get("/orders", headers={"X-API-Key": pm_key}).json()[0][
        "status"
    ] == OrderStatus.pending.value


def test_monitor_can_be_scoped_to_one_pod(
    client, desk, make_pod, fund_pod_cash, pm_factory, db, prices
):
    pod_1, _, pm_key = desk
    make_pod(2)
    fund_pod_cash(2, 50_000.0)
    _, key_2 = pm_factory("pm-2", 2)

    _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
           price_type="limit", limit_price=250.0)
    _order(client, key_2, ticker="AAPL", side="buy", qty=1,
           price_type="limit", limit_price=250.0)

    result = check_pending_orders(db, pod_id=2)
    assert result.checked == 1
    assert len(result.filled) == 1
    assert len(read_events(db, type=EVENT_ORDER_FILLED)) == 1
