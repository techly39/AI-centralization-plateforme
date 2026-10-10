"""Market orders end to end: fills, fee math, rejections, sells (TRD §8.1-8.5).

These go through the HTTP API rather than calling the service directly, because
that is how every real client (agents, MCP, the Phase 4 UI) will reach the OMS —
a test that bypasses the router would not prove the permission and pod-scope
wiring works.
"""

from __future__ import annotations

from app.bus.refs import agent_ref
from app.db.models import Message, Order, OrderStatus
from app.ledger.events import (
    EVENT_ORDER_FILLED,
    EVENT_ORDER_PLACED,
    EVENT_ORDER_REJECTED,
    read_events,
)


def _order(client, key, **body):
    payload = {"justification": "test thesis", **body}
    return client.post("/orders", headers={"X-API-Key": key}, json=payload)


# --- Market buy -------------------------------------------------------------

def test_market_buy_fills_immediately(client, desk, db):
    pod_id, pm_id, pm_key = desk

    resp = _order(client, pm_key, ticker="AAPL", side="buy", qty=10,
                  price_type="market")
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["status"] == "filled"
    assert body["fill_price"] == 200.0
    assert body["filled_at"] is not None
    # Fee = 10 × 200 × 0.1% = $2.00
    assert body["fee"] == 2.0
    assert body["pod_id"] == pod_id
    assert body["created_by"] == pm_id

    portfolio = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    # 100000 − (2000 + 2) = 97998
    assert portfolio["cash"] == 97_998.0
    assert portfolio["positions"][0]["ticker"] == "AAPL"
    assert portfolio["positions"][0]["qty"] == 10
    assert portfolio["positions"][0]["avg_cost"] == 200.0


def test_fill_is_recorded_as_events(client, desk, db):
    _, pm_id, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")

    placed = read_events(db, type=EVENT_ORDER_PLACED)
    filled = read_events(db, type=EVENT_ORDER_FILLED)
    assert len(placed) == 1
    assert len(filled) == 1
    assert filled[0].actor_agent_id == pm_id
    assert filled[0].payload_json["fee"] == 2.0
    assert filled[0].payload_json["fill_price"] == 200.0
    assert filled[0].payload_json["side"] == "buy"


def test_lowercase_ticker_is_normalised(client, desk):
    _, _, pm_key = desk
    resp = _order(client, pm_key, ticker="  aapl ", side="buy", qty=1,
                  price_type="market")
    assert resp.status_code == 201
    assert resp.json()["ticker"] == "AAPL"


# --- Rejection (TRD §8.2) ---------------------------------------------------

def test_insufficient_cash_is_rejected_and_messaged(client, desk, db, prices):
    pod_id, pm_id, pm_key = desk
    prices.set_price("AAPL", 200.0)

    # 600 × 200 = 120_000 > the pod's 100_000.
    resp = _order(client, pm_key, ticker="AAPL", side="buy", qty=600,
                  price_type="market")
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["status"] == "rejected"
    assert "120,120.00" in body["status_reason"]  # notional + fee
    assert "100,000.00" in body["status_reason"]

    # Nothing moved.
    portfolio = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    assert portfolio["cash"] == 100_000.0
    assert portfolio["positions"] == []

    # The rejection is on the ledger...
    rejections = read_events(db, type=EVENT_ORDER_REJECTED)
    assert len(rejections) == 1
    assert rejections[0].payload_json["reason"] == "insufficient_cash"
    assert rejections[0].payload_json["shortfall"] == 20_120.0

    # ...and the PM was told, with the numbers, not just prose.
    message = db.query(Message).filter(Message.to_ref == agent_ref(pm_id)).one()
    assert message.structured_payload_json["kind"] == "order_rejected"
    assert message.structured_payload_json["available"] == 100_000.0
    assert message.structured_payload_json["required"] == 120_120.0


def test_rejection_is_exact_at_the_boundary(client, desk, prices):
    """A pod must not be able to spend the fee it cannot pay."""
    _, _, pm_key = desk
    prices.set_price("NVDA", 100.0)

    # 1000 × 100 = 100_000 notional — affordable alone, but the $100 fee is not.
    resp = _order(client, pm_key, ticker="NVDA", side="buy", qty=1000,
                  price_type="market")
    assert resp.json()["status"] == "rejected"

    # 999 × 100 = 99_900 + 99.90 fee = 99_999.90 — just affordable.
    resp = _order(client, pm_key, ticker="NVDA", side="buy", qty=999,
                  price_type="market")
    assert resp.json()["status"] == "filled"


# --- Sells (TRD §8.5) -------------------------------------------------------

def test_partial_sell_books_realized_pnl(client, desk, db, prices):
    pod_id, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")

    prices.set_price("AAPL", 250.0)
    resp = _order(client, pm_key, ticker="AAPL", side="sell", qty=4,
                  price_type="market")
    assert resp.status_code == 201
    body = resp.json()

    assert body["status"] == "filled"
    assert body["fill_price"] == 250.0
    # Fee = 4 × 250 × 0.1% = $1.00; P&L = 4 × (250 − 200) − 1 = $199.00
    assert body["fee"] == 1.0
    assert body["realized_pnl"] == 199.0

    portfolio = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    position = portfolio["positions"][0]
    assert position["qty"] == 6
    assert position["avg_cost"] == 200.0  # a sell must not move the cost basis
    # 97_998 + (1000 − 1) = 98_997
    assert portfolio["cash"] == 98_997.0


def test_selling_out_removes_the_position(client, desk, prices):
    pod_id, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")
    _order(client, pm_key, ticker="AAPL", side="sell", qty=10, price_type="market")

    portfolio = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    assert portfolio["positions"] == []


def test_selling_more_than_held_is_rejected(client, desk, db):
    _, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=5, price_type="market")

    resp = _order(client, pm_key, ticker="AAPL", side="sell", qty=9,
                  price_type="market")
    body = resp.json()
    assert body["status"] == "rejected"
    assert "holds 5" in body["status_reason"]

    rejection = read_events(db, type=EVENT_ORDER_REJECTED)[0]
    assert rejection.payload_json["reason"] == "insufficient_position"


def test_selling_something_never_held_is_rejected(client, desk):
    _, _, pm_key = desk
    resp = _order(client, pm_key, ticker="MSFT", side="sell", qty=1,
                  price_type="market")
    assert resp.json()["status"] == "rejected"


# --- Validation and refusals -----------------------------------------------

def test_market_order_with_limit_price_is_refused(client, desk):
    _, _, pm_key = desk
    resp = _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
                  price_type="market", limit_price=190.0)
    assert resp.status_code == 422


def test_limit_order_without_limit_price_is_refused(client, desk):
    _, _, pm_key = desk
    resp = _order(client, pm_key, ticker="AAPL", side="buy", qty=1,
                  price_type="limit")
    assert resp.status_code == 422


def test_zero_quantity_is_refused(client, desk):
    _, _, pm_key = desk
    resp = _order(client, pm_key, ticker="AAPL", side="buy", qty=0,
                  price_type="market")
    assert resp.status_code == 422


def test_justification_is_required(client, desk):
    _, _, pm_key = desk
    resp = client.post(
        "/orders",
        headers={"X-API-Key": pm_key},
        json={"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market"},
    )
    assert resp.status_code == 422


def test_unknown_ticker_creates_no_order(client, desk, db):
    _, _, pm_key = desk
    resp = _order(client, pm_key, ticker="NOSUCH", side="buy", qty=1,
                  price_type="market")
    assert resp.status_code == 502
    assert db.query(Order).count() == 0


def test_pm_without_a_pod_cannot_trade(client, admin_key):
    key = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": "homeless-pm", "role": "pm"},
    ).json()["api_key"]
    resp = _order(client, key, ticker="AAPL", side="buy", qty=1,
                  price_type="market")
    assert resp.status_code == 403


def test_analyst_cannot_place_orders(client, desk, admin_key, make_pod):
    key = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": "analyst-1", "role": "analyst", "pod_id": 1},
    ).json()["api_key"]
    resp = _order(client, key, ticker="AAPL", side="buy", qty=1,
                  price_type="market")
    assert resp.status_code == 403


def test_management_cannot_place_orders(client, desk, admin_key):
    resp = _order(client, admin_key, ticker="AAPL", side="buy", qty=1,
                  price_type="market")
    assert resp.status_code == 403


def test_orders_are_listed_newest_first(client, desk):
    _, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=1, price_type="market")
    _order(client, pm_key, ticker="NVDA", side="buy", qty=1, price_type="market")

    listed = client.get("/orders", headers={"X-API-Key": pm_key}).json()
    assert [o["ticker"] for o in listed] == ["NVDA", "AAPL"]

    only_filled = client.get(
        "/orders", headers={"X-API-Key": pm_key}, params={"status": "filled"}
    ).json()
    assert len(only_filled) == 2
    assert all(o["status"] == OrderStatus.filled.value for o in only_filled)
