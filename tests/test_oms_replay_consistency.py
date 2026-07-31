"""The invariant everything else rests on: live state == replayed state.

The OMS updates ``positions`` and ``cash_balances`` incrementally as orders fill
(:mod:`app.ledger.apply`), while ``rebuild_state`` recomputes them from the
whole event history. The TRD's Definition of Done requires those to agree. If
they ever disagree, the portfolio a PM sees is fiction — so this file trades a
realistic sequence and then checks the two paths agree to the cent.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import CashBalance, Position
from app.ledger.rebuild import rebuild_state


def _order(client, key, **body):
    resp = client.post(
        "/orders", headers={"X-API-Key": key},
        json={"justification": "sequence", **body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _snapshot(db) -> tuple[dict, dict]:
    cash = {
        row.pod_id: row.balance
        for row in db.execute(select(CashBalance)).scalars()
    }
    positions = {
        (row.pod_id, row.ticker): (row.qty, row.avg_cost)
        for row in db.execute(select(Position)).scalars()
    }
    return cash, positions


def test_rebuild_reproduces_state_after_a_full_trading_sequence(
    client, desk, db, prices
):
    pod_id, _, pm_key = desk

    # Buys at two prices (so avg_cost is a real weighted average), a partial
    # sell, a full exit, a rejection, a queued limit order, and a cancellation.
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")
    prices.set_price("AAPL", 240.0)
    _order(client, pm_key, ticker="AAPL", side="buy", qty=5, price_type="market")
    _order(client, pm_key, ticker="NVDA", side="buy", qty=50, price_type="market")

    prices.set_price("AAPL", 260.0)
    _order(client, pm_key, ticker="AAPL", side="sell", qty=6, price_type="market")
    _order(client, pm_key, ticker="NVDA", side="sell", qty=50, price_type="market")

    _order(client, pm_key, ticker="MSFT", side="buy", qty=10_000,
           price_type="market")  # rejected: too expensive
    queued = _order(client, pm_key, ticker="MSFT", side="buy", qty=1,
                    price_type="limit", limit_price=300.0)
    client.delete(f"/orders/{queued['id']}", headers={"X-API-Key": pm_key})

    live_cash, live_positions = _snapshot(db)

    replayed = rebuild_state(db)
    db.commit()
    rebuilt_cash, rebuilt_positions = _snapshot(db)

    assert live_cash == rebuilt_cash
    assert live_positions == rebuilt_positions
    assert replayed.cash[pod_id] == live_cash[pod_id]

    # And the numbers are the ones we can compute by hand:
    #   funding                                  +100_000.00
    #   buy  10 AAPL @200  = 2_000.00 + 2.00 fee  −2_002.00
    #   buy   5 AAPL @240  = 1_200.00 + 1.20 fee  −1_201.20
    #   buy  50 NVDA @100  = 5_000.00 + 5.00 fee  −5_005.00
    #   sell  6 AAPL @260  = 1_560.00 − 1.56 fee  +1_558.44
    #   sell 50 NVDA @100  = 5_000.00 − 5.00 fee  +4_995.00
    assert round(live_cash[pod_id], 2) == 98_345.24
    # avg cost = (10×200 + 5×240) / 15 = 213.333…
    qty, avg_cost = live_positions[(pod_id, "AAPL")]
    assert qty == 9
    assert round(avg_cost, 4) == 213.3333
    assert (pod_id, "NVDA") not in live_positions


def test_rebuild_after_a_rejected_order_changes_nothing(client, desk, db):
    _, _, pm_key = desk
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10, price_type="market")
    _order(client, pm_key, ticker="AAPL", side="buy", qty=10_000, price_type="market")

    before = _snapshot(db)
    rebuild_state(db)
    db.commit()
    assert _snapshot(db) == before


def test_two_pods_do_not_leak_into_each_other(
    client, desk, make_pod, fund_pod_cash, pm_factory, db
):
    pod_1, _, key_1 = desk
    make_pod(2)
    fund_pod_cash(2, 50_000.0)
    _, key_2 = pm_factory("pm-2", 2)

    _order(client, key_1, ticker="AAPL", side="buy", qty=10, price_type="market")
    _order(client, key_2, ticker="AAPL", side="buy", qty=5, price_type="market")

    cash, positions = _snapshot(db)
    assert cash[1] == 97_998.0
    assert cash[2] == 48_999.0  # 50_000 − 1_000 notional − 1.00 fee
    assert positions[(1, "AAPL")][0] == 10
    assert positions[(2, "AAPL")][0] == 5

    rebuild_state(db)
    db.commit()
    assert _snapshot(db) == (cash, positions)
