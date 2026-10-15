"""M-001, milestone 3: ``GET /metering/agents`` — what each metered agent cost, by the meter (ADR-044).

Claims under test:

* each agent with a ``cost_metered`` row is listed with its metered micro-dollars, its own
  self-report and the gap between them; the total is the sum of the keys' maxima;
* the read is management's (and the physics roles'): a firm role gets 403 and a logged event;
* forged ledger rows are counted (``conflicts``, ``malformed``), never believed;
* with nothing metered the total is ``null``, not 0 (unmeasured is not free);
* no ``key_ref`` is ever returned;
* the whole-ledger invariant: Σ authoritative cost over pods and pod-less agents == Σ per-key
  maxima, with duplicate and out-of-order posts and a pod-less metered agent.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Event
from app.ledger.events import EVENT_COST_METERED, EVENT_PERMISSION_DENIED, append_event
from app.metrics.metering import metered_by_agent
from tests.test_metering import events_of, meter, two_agents  # noqa: F401 - fixtures


def _read(client, key):
    return client.get("/metering/agents", headers={"X-API-Key": key})


def _report(client, key, usd):
    return client.post("/costs", headers={"X-API-Key": key},
                       json={"tokens_in": 10, "tokens_out": 5, "usd_cost": usd})


def test_metering_agents_lists_each_metered_agent_with_its_gap(
        client, db, runtime_key, admin_key, two_agents) -> None:
    a, b = two_agents["a"], two_agents["b"]
    assert _report(client, two_agents["a_key"], 0.5).status_code in (200, 201)
    assert meter(client, runtime_key, a, "k1", 2_500_000).status_code == 200
    assert meter(client, runtime_key, a, "k1", 2_750_000).status_code == 200     # cumulative
    assert meter(client, runtime_key, b, "k2", 1_000_000).status_code == 200
    resp = _read(client, admin_key)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = {r["agent_id"]: r for r in body["agents"]}
    assert set(rows) == {a, b}
    assert rows[a]["metered_usd_micros"] == 2_750_000 and rows[a]["metered_usd"] == 2.75
    assert rows[a]["self_reported_usd"] == 0.5 and rows[a]["self_report_gap_usd"] == -2.25
    assert rows[b]["self_reported_usd"] == 0.0 and rows[b]["self_report_gap_usd"] == -1.0
    assert rows[a]["pod_id"] == two_agents["pod"]
    assert body["total_usd_micros"] == 3_750_000 and (body["conflicts"], body["malformed"]) == (0, 0)


def test_metering_agents_counts_forged_conflicts_and_malformed_rows(
        client, db, runtime_key, admin_key, two_agents) -> None:
    a, b = two_agents["a"], two_agents["b"]
    meter(client, runtime_key, a, "k1", 1_000_000)
    runtime = events_of(db, EVENT_COST_METERED)[0].actor_agent_id
    # Forged straight into the ledger: the key rebinds to b; and a row with no total.
    append_event(db, type=EVENT_COST_METERED, actor_agent_id=runtime,
                 payload={"agent_id": b, "pod_id": two_agents["pod"], "key_ref": "k1",
                          "usd_micros_total": 9_000_000})
    append_event(db, type=EVENT_COST_METERED, actor_agent_id=runtime,
                 payload={"agent_id": a, "key_ref": "k9"})
    db.commit()
    body = _read(client, admin_key).json()
    assert (body["conflicts"], body["malformed"]) == (1, 1)
    assert body["total_usd_micros"] == 1_000_000 and [r["agent_id"] for r in body["agents"]] == [a]


@pytest.mark.parametrize("who", ["a_key", "b_key"])
def test_metering_agents_is_management_only(client, db, two_agents, who) -> None:
    assert _read(client, two_agents[who]).status_code == 403
    [denied] = events_of(db, EVENT_PERMISSION_DENIED)
    assert denied.payload_json["action"] == "read_cross_pod"


def test_the_runtime_identity_does_not_read_it(client, runtime_key, two_agents) -> None:
    """The Runtime writes the meter's totals; it holds no cross-pod read (narrowest key)."""
    assert _read(client, runtime_key).status_code == 403


def test_metering_agents_with_no_metering_is_null_not_zero(client, admin_key, two_agents) -> None:
    body = _read(client, admin_key).json()
    assert body == {"agents": [], "total_usd_micros": None, "conflicts": 0, "malformed": 0}


def test_metering_agents_never_returns_a_key_ref(client, runtime_key, admin_key, two_agents) -> None:
    meter(client, runtime_key, two_agents["a"], "secret-looking-key-ref", 5)
    assert "secret-looking-key-ref" not in _read(client, admin_key).text
    assert "key_ref" not in _read(client, admin_key).text


def test_whole_ledger_invariant(client, db, runtime_key, admin_key, two_agents) -> None:
    """Σ authoritative (pods + pod-less metered) == Σ per-key maxima — not "pods cover every dollar"."""
    from app.metrics.service import compute_pod_metrics
    a, b = two_agents["a"], two_agents["b"]
    podless = client.post("/agents/register", headers={"X-API-Key": admin_key},
                          json={"name": "mgmt-2", "role": "management"}).json()["id"]
    posts = [(a, "k1", 3_000_000), (a, "k1", 3_000_000), (b, "k2", 400_000),   # a duplicate post
             (a, "k1", 3_500_000), (podless, "k3", 1_250_000), (b, "k4", 100_000)]
    for agent, key, total in posts:
        assert meter(client, runtime_key, agent, key, total).status_code == 200
    assert meter(client, runtime_key, a, "k1", 3_000_000).status_code == 409   # out of order
    top = {}
    for e in events_of(db, EVENT_COST_METERED):
        top[e.payload_json["key_ref"]] = max(top.get(e.payload_json["key_ref"], 0),
                                             e.payload_json["usd_micros_total"])
    body = _read(client, admin_key).json()
    assert sum(top.values()) == body["total_usd_micros"] == 3_500_000 + 400_000 + 1_250_000 + 100_000
    in_pods = sum(round(compute_pod_metrics(db, pod_id=two_agents["pod"]).cost.metered_usd_cost
                        * 1_000_000) for _ in [0])
    podless_micros = metered_by_agent(db)[podless].usd_micros
    assert in_pods + podless_micros == body["total_usd_micros"]
