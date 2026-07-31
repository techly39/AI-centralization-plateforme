"""``GET /portfolio/{pod_id}``: valuation, P&L, and who is allowed to look."""

from __future__ import annotations

from app.marketdata import StaticProvider, set_provider


def _order(client, key, **body):
    return client.post(
        "/orders", headers={"X-API-Key": key},
        json={"justification": "portfolio test", **body},
    )


def test_empty_pod_reports_only_cash(client, desk):
    pod_id, _, pm_key = desk
    body = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    assert body["cash"] == 100_000.0
    assert body["positions"] == []
    assert body["total_value"] == 100_000.0
    assert body["unrealized_pnl"] == 0.0
    assert body["fully_priced"] is True


def test_unrealized_pnl_tracks_the_market(client, desk, prices):
    pod_id, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")

    prices.set_price("AAPL", 230.0)
    body = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()

    position = body["positions"][0]
    assert position["avg_cost"] == 200.0
    assert position["cost_basis"] == 2_000.0
    assert position["last_price"] == 230.0
    assert position["market_value"] == 2_300.0
    assert position["unrealized_pnl"] == 300.0

    assert body["cash"] == 97_998.0
    assert body["positions_value"] == 2_300.0
    assert body["total_value"] == 100_298.0
    assert body["unrealized_pnl"] == 300.0


def test_positions_are_sorted_and_complete(client, desk):
    pod_id, _, pm_key = desk
    _order(client, pm_key, ticker="NVDA", side="buy", qty=5, price_type="market")
    _order(client, pm_key, ticker="AAPL", side="buy", qty=5, price_type="market")

    body = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key}).json()
    assert [p["ticker"] for p in body["positions"]] == ["AAPL", "NVDA"]


def test_an_unpriceable_position_degrades_instead_of_failing(client, desk):
    """One dead quote must not blind the PM to the rest of the book."""
    pod_id, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")
    _order(client, pm_key, ticker="NVDA", side="buy", qty=10, price_type="market")

    # AAPL still quotes; NVDA has gone dark.
    set_provider(StaticProvider({"AAPL": 200.0}))

    resp = client.get(f"/portfolio/{pod_id}", headers={"X-API-Key": pm_key})
    assert resp.status_code == 200
    body = resp.json()

    assert body["fully_priced"] is False
    assert body["pricing_errors"] == ["NVDA"]

    by_ticker = {p["ticker"]: p for p in body["positions"]}
    assert by_ticker["AAPL"]["market_value"] == 2_000.0
    assert by_ticker["NVDA"]["last_price"] is None
    assert by_ticker["NVDA"]["market_value"] is None
    # The totals count only what could be valued, so they stay truthful.
    assert body["positions_value"] == 2_000.0


# --- Access control (TRD §6) ------------------------------------------------

def test_analyst_can_read_its_own_pods_portfolio(client, desk, admin_key):
    pod_id, _, _ = desk
    key = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": "analyst-1", "role": "analyst", "pod_id": pod_id},
    ).json()["api_key"]
    assert client.get(
        f"/portfolio/{pod_id}", headers={"X-API-Key": key}
    ).status_code == 200


def test_a_pm_cannot_read_another_pods_portfolio(
    client, desk, make_pod, fund_pod_cash, pm_factory
):
    make_pod(2)
    fund_pod_cash(2, 10_000.0)
    _, other_key = pm_factory("pm-2", 2)

    assert client.get(
        "/portfolio/1", headers={"X-API-Key": other_key}
    ).status_code == 403


def test_management_can_read_any_pods_portfolio(client, desk, admin_key):
    pod_id, _, _ = desk
    assert client.get(
        f"/portfolio/{pod_id}", headers={"X-API-Key": admin_key}
    ).status_code == 200


def test_cross_pod_denial_is_logged_as_an_event(
    client, desk, make_pod, fund_pod_cash, pm_factory, db
):
    from app.ledger.events import EVENT_PERMISSION_DENIED, read_events

    make_pod(2)
    fund_pod_cash(2, 10_000.0)
    _, other_key = pm_factory("pm-2", 2)
    client.get("/portfolio/1", headers={"X-API-Key": other_key})

    denials = read_events(db, type=EVENT_PERMISSION_DENIED)
    assert len(denials) == 1
    assert denials[0].payload_json["pod_id"] == 1


# --- Order listing scope ----------------------------------------------------

def test_orders_default_to_your_own_pod(
    client, desk, make_pod, fund_pod_cash, pm_factory
):
    _, _, pm_key = desk
    make_pod(2)
    fund_pod_cash(2, 10_000.0)
    _, key_2 = pm_factory("pm-2", 2)

    _order(client, pm_key, ticker="AAPL", side="buy", qty=1, price_type="market")
    _order(client, key_2, ticker="NVDA", side="buy", qty=1, price_type="market")

    mine = client.get("/orders", headers={"X-API-Key": pm_key}).json()
    assert [o["ticker"] for o in mine] == ["AAPL"]

    theirs = client.get("/orders", headers={"X-API-Key": key_2}).json()
    assert [o["ticker"] for o in theirs] == ["NVDA"]


def test_management_sees_every_pods_orders(
    client, desk, admin_key, make_pod, fund_pod_cash, pm_factory
):
    _, _, pm_key = desk
    make_pod(2)
    fund_pod_cash(2, 10_000.0)
    _, key_2 = pm_factory("pm-2", 2)

    _order(client, pm_key, ticker="AAPL", side="buy", qty=1, price_type="market")
    _order(client, key_2, ticker="NVDA", side="buy", qty=1, price_type="market")

    everything = client.get("/orders", headers={"X-API-Key": admin_key}).json()
    assert {o["ticker"] for o in everything} == {"AAPL", "NVDA"}


def test_a_pm_asking_for_another_pods_orders_is_denied(
    client, desk, make_pod, fund_pod_cash, pm_factory
):
    make_pod(2)
    fund_pod_cash(2, 10_000.0)
    _, key_2 = pm_factory("pm-2", 2)
    resp = client.get("/orders", headers={"X-API-Key": key_2}, params={"pod": 1})
    assert resp.status_code == 403
