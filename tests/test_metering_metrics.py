"""R-6a: metered cost overrides self-report in the metrics (ADR-041).

The law: an agent with any metered row is *metered*; its self-reported ``Cost``
rows leave the authoritative total and stay as a cross-check
(``self_report_gap_usd``). An unmetered agent keeps its self-reports. The
override is per agent, never per pod.
"""

from __future__ import annotations

import pytest

from tests.test_metering import meter


def selfreport(client, key, usd):
    r = client.post("/costs", headers={"X-API-Key": key},
                    json={"tokens_in": 10, "tokens_out": 5, "usd_cost": usd})
    assert r.status_code == 201, r.text


def cost_of(client, admin_key, pod_id) -> dict:
    r = client.get(f"/metrics/pod/{pod_id}", headers={"X-API-Key": admin_key})
    assert r.status_code == 200, r.text
    return r.json()["cost"]


def board(client, admin_key) -> list[dict]:
    r = client.get("/metrics/leaderboard", headers={"X-API-Key": admin_key})
    assert r.status_code == 200, r.text
    return r.json()["rows"]


@pytest.fixture
def pair(client, desk, agent_factory):
    pod_id, pm_id, pm_key = desk
    an_id, an_key = agent_factory("analyst-1", "analyst", pod_id)
    return {"pod": pod_id, "a": pm_id, "a_key": pm_key, "b": an_id, "b_key": an_key}


def test_metered_cost_overrides_the_agents_self_report(client, admin_key, runtime_key, pair):
    selfreport(client, pair["a_key"], 100.0)
    meter(client, runtime_key, pair["a"], "k1", 5_000_000)
    cost = cost_of(client, admin_key, pair["pod"])
    assert cost["total_usd_cost"] == 5.0
    assert cost["self_reported_usd_cost"] == 100.0
    assert cost["metered_usd_cost"] == 5.0
    assert cost["metered_agents"] == 1
    assert cost["self_report_gap_usd"] == 95.0


def test_a_self_report_of_zero_cannot_hide_metered_cost(client, admin_key, runtime_key, pair):
    selfreport(client, pair["a_key"], 0.0)
    meter(client, runtime_key, pair["a"], "k1", 7_000_000)
    cost = cost_of(client, admin_key, pair["pod"])
    assert cost["total_usd_cost"] == 7.0
    assert cost["self_report_gap_usd"] == -7.0


def test_a_metered_agent_cannot_add_cost_by_self_reporting(client, admin_key, runtime_key, pair):
    meter(client, runtime_key, pair["a"], "k1", 1_000_000)
    selfreport(client, pair["a_key"], 500.0)
    assert cost_of(client, admin_key, pair["pod"])["total_usd_cost"] == 1.0


def test_override_is_per_agent_not_per_pod(client, admin_key, runtime_key, pair):
    selfreport(client, pair["a_key"], 100.0)
    selfreport(client, pair["b_key"], 2.0)
    meter(client, runtime_key, pair["a"], "k1", 5_000_000)
    cost = cost_of(client, admin_key, pair["pod"])
    assert cost["total_usd_cost"] == 7.0          # A metered 5 + B unmetered self-report 2
    assert cost["metered_agents"] == 1
    assert cost["self_reported_usd_cost"] == 102.0


def test_unmetered_pod_metrics_are_unchanged(client, admin_key, pair):
    selfreport(client, pair["a_key"], 12.5)
    cost = cost_of(client, admin_key, pair["pod"])
    assert cost["total_usd_cost"] == 12.5
    assert cost["self_reported_usd_cost"] == 12.5
    assert cost["metered_usd_cost"] is None
    assert cost["self_report_gap_usd"] is None
    assert cost["metered_agents"] == 0


def test_metered_at_zero_is_zero_not_null(client, admin_key, runtime_key, pair):
    meter(client, runtime_key, pair["a"], "k1", 0)
    cost = cost_of(client, admin_key, pair["pod"])
    assert cost["metered_usd_cost"] == 0.0
    assert cost["metered_agents"] == 1


def test_metered_dollars_land_on_the_agents_pod(client, admin_key, runtime_key, pair, make_pod, pm_factory):
    make_pod(2)
    other_id, _ = pm_factory("pm-2", 2)
    meter(client, runtime_key, pair["a"], "k1", 3_000_000)
    meter(client, runtime_key, other_id, "k2", 4_000_000)
    assert cost_of(client, admin_key, pair["pod"])["total_usd_cost"] == 3.0
    assert cost_of(client, admin_key, 2)["total_usd_cost"] == 4.0


def test_leaderboard_ranks_by_metered_cost(client, admin_key, runtime_key, pair, make_pod,
                                           pm_factory, fund_pod_cash):
    """Self-reports would rank pod 1 first; the metered costs rank pod 2 first."""
    make_pod(2)
    fund_pod_cash(2, 100_000.0)
    p2_id, p2_key = pm_factory("pm-2", 2)
    selfreport(client, pair["a_key"], 1.0)      # pod 1 claims to be cheap...
    selfreport(client, p2_key, 50.0)            # ...pod 2 claims to be dear
    meter(client, runtime_key, pair["a"], "k1", 90_000_000)   # truth: pod 1 cost $90
    meter(client, runtime_key, p2_id, "k2", 10_000_000)       # truth: pod 2 cost $10
    rows = board(client, admin_key)
    assert [r["pod_id"] for r in rows] == [2, 1]
    by_pod = {r["pod_id"]: r for r in rows}
    assert by_pod[1]["total_usd_cost"] == 90.0
    assert by_pod[2]["total_usd_cost"] == 10.0
    assert by_pod[1]["metered_usd_cost"] == 90.0
