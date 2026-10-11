"""Phase 2's milestone: the OpenClaw single-pod POC, re-run **through the app only**.

The original proof of concept (kept in ``legacy/oms_poc/``) was a folder. An
agent wrote a JSON file of four buys, a script scanned the directory, shelled out
for prices, and rewrote ``Portfolio.json``. It worked, and none of it was
observable: no identities, no permissions, no record of *why*, no idea what the
agents had cost to run.

This test performs the same day's work with nothing but HTTP calls:

* management registers the desk and its agents;
* an analyst opens a work log, researches, reports what it cost, and messages
  the PM a structured recommendation;
* the PM reads its inbox, places the same four orders with justifications, and
  reports its own cost;
* management reads the metrics it could not previously have had.

The assertions that matter are the ones the POC could not have made: that every
order has a stated reason, that the audit trail contains the whole session, and
that the pod's P&L can be compared with what it cost to produce.

Note the one number that legitimately differs from ``legacy/Portfolio.json``:
the POC charged no commission, and the app charges the configured 0.1%. The
positions are identical; the cash is lower by exactly the fees.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import Event, Order
from app.marketdata import set_provider
from tests.support import HistoricalProvider

#: The POC's own fills, from legacy/oms_poc/Processed orders/*.result.json.
POC_FILLS = [
    ("JPM", 100, 297.81, "Best value in the group with 14.3x P/E, 11.6% off high, "
                         "and 12-14% analyst upside."),
    ("JNJ", 100, 226.71, "Defensive healthcare quality 10% off high with 10-15% "
                         "analyst upside."),
    ("UNH", 50, 393.85, "Healthcare leader pulled back from $404 high; Medicare "
                        "Advantage recovery intact."),
    ("WMT", 200, 131.45, "Consumer defensive anchor with Buy consensus, resilient "
                         "earnings, and best inflation hedge."),
]
STARTING_CASH = 1_000_000.0
#: The POC's closing cash, with no commission charged.
POC_CLOSING_CASH = 901_565.4998

TRADING_DAY = date(2026, 5, 16)


@pytest.fixture
def poc_market(frozen_clock):
    """The prices the POC actually filled at, on the day it ran.

    At 08:35 UTC the last price anyone knew was the previous day's close, so
    the fills are that day's bar (ADR-028); keyed on the trading day itself,
    they would be a close not known until midnight.
    """
    frozen_clock.set(datetime(2026, 5, 16, 8, 35, tzinfo=timezone.utc))
    provider = HistoricalProvider(
        {ticker: {TRADING_DAY - timedelta(days=1): price}
         for ticker, _, price, _ in POC_FILLS}
    )
    set_provider(provider)
    yield provider
    set_provider(None)


def api(client, key):
    """A tiny helper so the test reads as a sequence of agent actions."""

    class Caller:
        def get(self, path, **params):
            resp = client.get(path, headers={"X-API-Key": key}, params=params)
            assert resp.status_code == 200, resp.text
            return resp.json()

        def post(self, path, expect=201, **body):
            resp = client.post(path, headers={"X-API-Key": key}, json=body)
            assert resp.status_code == expect, resp.text
            return resp.json()

    return Caller()


def test_the_poc_runs_end_to_end_through_the_api(
    client, admin_key, poc_market, frozen_clock, make_pod, fund_pod_cash, db
):
    management = api(client, admin_key)

    # --- Management sets up the desk ----------------------------------------
    pod_id = make_pod(1, name="healthcare-value")
    fund_pod_cash(pod_id, STARTING_CASH)

    pm = management.post(
        "/agents/register", name="pm-alpha", role="pm", pod_id=pod_id,
        charter_ref="charters/pm-alpha.md",
    )
    analyst = management.post(
        "/agents/register", name="analyst-alpha", role="analyst", pod_id=pod_id,
        research_domains=["financials", "healthcare", "consumer staples"],
    )
    pm_api = api(client, pm["api_key"])
    analyst_api = api(client, analyst["api_key"])

    # The directory is how agents find each other — no hard-coded ids anywhere.
    directory = {a["name"]: a for a in analyst_api.get("/agents")}
    assert directory["pm-alpha"]["role"] == "pm"

    # --- The analyst works, and says what it cost ---------------------------
    task = analyst_api.post("/tasks/start", subject="value screen")

    for ticker, _, _, _ in POC_FILLS:
        quote = analyst_api.get(f"/price/{ticker}")
        assert quote["ticker"] == ticker

    frozen_clock.advance(minutes=42)
    analyst_api.post(
        "/tasks/end", expect=200, task_id=task["id"],
        outcome={
            "summary": "Four defensive names off their highs.",
            "candidates": [t for t, _, _, _ in POC_FILLS],
        },
    )
    analyst_api.post(
        "/costs", tokens_in=84_000, tokens_out=6_200, usd_cost=1.34,
        task_label="value screen",
    )

    recommendation = analyst_api.post(
        "/messages",
        to=f"agent:{directory['pm-alpha']['id']}",
        thread_id="2026-05-16-screen",
        body="Four names screen well; sizes below.",
        structured_payload={
            "orders": [
                {"ticker": t, "qty": q, "justification": j}
                for t, q, _, j in POC_FILLS
            ]
        },
    )

    # --- The PM acts on it --------------------------------------------------
    inbox = pm_api.get("/messages")
    assert [m["id"] for m in inbox] == [recommendation["id"]]
    proposed = inbox[0]["structured_payload"]["orders"]
    assert len(proposed) == 4

    pm_task = pm_api.post("/tasks/start", subject="position sizing")
    for line in proposed:
        placed = pm_api.post(
            "/orders",
            ticker=line["ticker"], side="buy", qty=line["qty"],
            price_type="market", justification=line["justification"],
        )
        assert placed["status"] == "filled", placed["status_reason"]

    frozen_clock.advance(minutes=8)
    pm_api.post(
        "/tasks/end", expect=200, task_id=pm_task["id"],
        outcome={"summary": "All four filled at market.", "orders": 4},
    )
    pm_api.post(
        "/costs", tokens_in=21_500, tokens_out=1_900, usd_cost=0.38,
        task_label="position sizing",
    )

    # --- The portfolio matches the POC, position for position ---------------
    portfolio = pm_api.get(f"/portfolio/{pod_id}")
    held = {p["ticker"]: p for p in portfolio["positions"]}
    for ticker, qty, price, _ in POC_FILLS:
        assert held[ticker]["qty"] == qty
        assert held[ticker]["avg_cost"] == pytest.approx(price, abs=0.01)

    # Cash differs from the POC's by exactly the commission it never charged.
    fees = sum(round(qty * price * 0.001, 2) for _, qty, price, _ in POC_FILLS)
    assert portfolio["cash"] == pytest.approx(POC_CLOSING_CASH - fees, abs=0.01)
    assert portfolio["total_value"] == pytest.approx(STARTING_CASH - fees, abs=0.01)

    # --- What the POC could never have told anyone --------------------------
    orders = pm_api.get("/orders")
    assert len(orders) == 4
    # Every trade carries a stated reason. This is the point of the whole system.
    assert all(o["justification"] for o in orders)
    assert all(o["fee"] > 0 for o in orders)

    report = management.get(f"/metrics/pod/{pod_id}")
    assert report["cost"]["total_usd_cost"] == pytest.approx(1.72)
    assert report["cost"]["tokens_in"] == 105_500
    assert report["activity"]["tasks_opened"] == 2
    assert report["activity"]["tasks_closed"] == 2
    assert report["activity"]["orders_filled"] == 4
    assert report["activity"]["messages_sent"] == 1
    assert {s["subject"] for s in report["activity"]["time_per_subject"]} == {
        "value screen",
        "position sizing",
    }
    # P&L is the fees so far; cost-adjusted P&L also carries what the agents cost.
    assert report["performance"]["pnl"] == pytest.approx(-fees, abs=0.01)
    assert report["cost_adjusted_pnl"] == pytest.approx(-fees - 1.72, abs=0.01)

    # --- And the whole session is on the ledger -----------------------------
    types = [e.type for e in db.execute(select(Event).order_by(Event.id)).scalars()]
    for expected in (
        "allocation_set", "agent_registered", "task_started", "task_ended",
        "cost_reported", "message_sent", "order_placed", "order_filled",
    ):
        assert expected in types, f"{expected} missing from the audit trail"

    assert db.scalar(select(Order).where(Order.ticker == "JPM")).justification


def test_the_poc_desk_cannot_be_traded_by_the_analyst(
    client, admin_key, poc_market, make_pod, fund_pod_cash
):
    """The POC had no identities at all: anything that could write a file could trade.

    Now the analyst that produced the research cannot place the order, and the
    refusal is recorded against it.
    """
    pod_id = make_pod(1, name="healthcare-value")
    fund_pod_cash(pod_id, STARTING_CASH)
    management = api(client, admin_key)
    analyst = management.post(
        "/agents/register", name="analyst-alpha", role="analyst", pod_id=pod_id
    )

    resp = client.post(
        "/orders",
        headers={"X-API-Key": analyst["api_key"]},
        json={"ticker": "JPM", "side": "buy", "qty": 100, "price_type": "market",
              "justification": "I found it, I should trade it"},
    )
    assert resp.status_code == 403

    denials = management.get("/events", type="permission_denied")
    assert denials[-1]["actor_agent_id"] == analyst["id"]
