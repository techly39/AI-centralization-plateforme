"""R-6a: the system-reported cost ledger (ADR-041, plan state/plans/0034.md).

Claims under test:

* the ``runtime`` role (and ``system``) may post a cumulative micro-dollar total
  for a key; no firm role may, and a refusal is a 403 plus a logged event;
* a post is one ``cost_metered`` event; a re-post of the same total writes
  nothing; a lower total is refused; a key belongs to the first agent it names;
* a physics identity cannot be metered; an unknown agent is a 404;
* bad bodies (bool, float, negative, over the cap, bad ``key_ref``) are 422;
* HALT refuses the post (423); an agent reads ``key_ref`` as withheld;
* metered cost replaces the agent's self-report in the pod's metrics, per
  agent, never per pod; a pod with no metering is numerically unchanged;
* the ledger is the only store: metrics survive ``rebuild_state``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Agent, AgentRole, Event
from app.ledger.events import (
    EVENT_COST_METERED,
    EVENT_PERMISSION_DENIED,
    append_event,
)
from app.ledger.rebuild import rebuild_state
from app.limits import MAX_METERED_USD_MICROS
from app.metrics.metering import metered_by_agent
from app.metrics.service import compute_pod_metrics
from app.registry.permissions import Action, has_permission


def meter(client, key, agent_id, key_ref="k1", total=1_000_000, **extra):
    return client.post(
        "/metering/usage",
        headers={"X-API-Key": key},
        json={"agent_id": agent_id, "key_ref": key_ref, "usd_micros_total": total, **extra},
    )


def events_of(db, type_):
    db.expire_all()
    return list(db.execute(select(Event).where(Event.type == type_).order_by(Event.id)).scalars())


@pytest.fixture
def two_agents(client, desk, agent_factory):
    """Pod 1 with its PM (A) and an analyst (B)."""
    pod_id, pm_id, pm_key = desk
    analyst_id, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    return {"pod": pod_id, "a": pm_id, "a_key": pm_key, "b": analyst_id, "b_key": analyst_key}


# --- who may post -------------------------------------------------------------

def test_runtime_records_metered_usage_as_one_event(client, db, runtime_key, two_agents):
    resp = meter(client, runtime_key, two_agents["a"], "k1", 2_500_000)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recorded"] is True
    assert body["agent_id"] == two_agents["a"]
    assert body["usd_micros_total"] == 2_500_000
    assert body["event_id"] is not None

    [event] = events_of(db, EVENT_COST_METERED)
    runtime = db.scalar(select(Agent).where(Agent.role == AgentRole.runtime))
    assert event.actor_agent_id == runtime.id
    assert event.payload_json == {
        "agent_id": two_agents["a"], "pod_id": two_agents["pod"],
        "key_ref": "k1", "usd_micros_total": 2_500_000,
    }


@pytest.mark.parametrize("who", ["a_key", "b_key"])
def test_firm_roles_may_not_meter(client, db, two_agents, who):
    resp = meter(client, two_agents[who], two_agents["a"])
    assert resp.status_code == 403
    assert events_of(db, EVENT_COST_METERED) == []
    [denied] = events_of(db, EVENT_PERMISSION_DENIED)
    assert denied.payload_json["action"] == "report_metered_cost"


def test_management_may_not_meter(client, db, admin_key, two_agents):
    assert meter(client, admin_key, two_agents["a"]).status_code == 403
    assert events_of(db, EVENT_COST_METERED) == []
    assert len(events_of(db, EVENT_PERMISSION_DENIED)) == 1


def test_only_runtime_and_system_hold_the_right():
    """Counter-example to "only the runtime": system holds every right (no key in tests)."""
    holders = {r for r in AgentRole if has_permission(r, Action.REPORT_METERED_COST)}
    assert holders == {AgentRole.runtime, AgentRole.system}


# --- what may be metered ------------------------------------------------------

def test_a_physics_identity_cannot_be_metered(client, db, runtime_key, SessionFactory, two_agents):
    from app.registry.service import get_or_create_system_agent
    s = SessionFactory()
    try:
        system_id = get_or_create_system_agent(s).id
        s.commit()
    finally:
        s.close()
    runtime_id = db.scalar(select(Agent.id).where(Agent.role == AgentRole.runtime))
    for target in (system_id, runtime_id):
        assert meter(client, runtime_key, target).status_code == 422, target
    assert events_of(db, EVENT_COST_METERED) == []


def test_unknown_agent_is_404(client, db, runtime_key):
    assert meter(client, runtime_key, 9999).status_code == 404
    assert events_of(db, EVENT_COST_METERED) == []


# --- cumulative, idempotent, one key one agent --------------------------------

def test_a_repost_of_the_same_total_writes_nothing(client, db, runtime_key, two_agents):
    assert meter(client, runtime_key, two_agents["a"], total=500).json()["recorded"] is True
    again = meter(client, runtime_key, two_agents["a"], total=500)
    assert again.status_code == 200
    assert again.json()["recorded"] is False
    assert again.json()["event_id"] is None
    assert len(events_of(db, EVENT_COST_METERED)) == 1


def test_a_higher_total_is_a_new_event_and_counts_once(client, db, runtime_key, two_agents):
    meter(client, runtime_key, two_agents["a"], total=500)
    meter(client, runtime_key, two_agents["a"], total=800)
    assert len(events_of(db, EVENT_COST_METERED)) == 2
    assert metered_by_agent(db)[two_agents["a"]].usd_micros == 800  # not 1300


def test_a_lower_total_is_refused(client, db, runtime_key, two_agents):
    meter(client, runtime_key, two_agents["a"], total=800)
    assert meter(client, runtime_key, two_agents["a"], total=799).status_code == 409
    assert len(events_of(db, EVENT_COST_METERED)) == 1


def test_a_key_belongs_to_one_agent(client, db, runtime_key, two_agents):
    assert meter(client, runtime_key, two_agents["a"], "k1", 100).status_code == 200
    assert meter(client, runtime_key, two_agents["b"], "k1", 100).status_code == 409
    assert meter(client, runtime_key, two_agents["b"], "k2", 100).status_code == 200
    assert len(events_of(db, EVENT_COST_METERED)) == 2


def test_an_agent_may_hold_several_keys_and_they_sum(client, db, runtime_key, two_agents):
    meter(client, runtime_key, two_agents["a"], "k1", 3_000_000)
    meter(client, runtime_key, two_agents["a"], "k2", 2_000_000)
    assert metered_by_agent(db)[two_agents["a"]].usd_micros == 5_000_000


def test_spend_may_land_after_a_deactivation(client, db, admin_key, runtime_key, two_agents):
    gone = client.post(f"/agents/{two_agents['b']}/deactivate", headers={"X-API-Key": admin_key})
    assert gone.status_code == 200, gone.text
    assert meter(client, runtime_key, two_agents["b"], total=42).json()["recorded"] is True


def test_a_podless_agent_is_metered_but_lands_on_no_pod(client, db, admin_key, runtime_key, two_agents):
    """ADR-041 (4): firm-level cost for pod-less agents is B-000k, not yet shown anywhere."""
    admin_id = db.scalar(select(Agent.id).where(Agent.name == "management"))
    assert meter(client, runtime_key, admin_id, "k9", 5_000_000).status_code == 200
    pod = client.get(f"/metrics/pod/{two_agents['pod']}", headers={"X-API-Key": admin_key}).json()
    assert pod["cost"]["metered_usd_cost"] is None
    assert metered_by_agent(db)[admin_id].pod_id is None


@pytest.mark.parametrize(
    "total",
    [True, 1.5, 1.0, -1, MAX_METERED_USD_MICROS + 1, 2**63, "5", None],
)
def test_bad_totals_are_422(client, db, runtime_key, two_agents, total):
    assert meter(client, runtime_key, two_agents["a"], total=total).status_code == 422
    assert events_of(db, EVENT_COST_METERED) == []


@pytest.mark.parametrize(
    "key_ref", ["K1", "sk-or-v1-" + "a" * 60, "", "-lead", "has space", "a" * 65, "é"],
)
def test_bad_key_refs_are_422(client, db, runtime_key, two_agents, key_ref):
    assert meter(client, runtime_key, two_agents["a"], key_ref).status_code == 422
    assert events_of(db, EVENT_COST_METERED) == []


@pytest.mark.parametrize("bad_id", [True, 0, -1, 2**63, 1.5, "1"])
def test_bad_agent_ids_are_422(client, db, runtime_key, bad_id):
    assert meter(client, runtime_key, bad_id).status_code == 422


def test_an_extra_field_is_422(client, db, runtime_key, two_agents):
    assert meter(client, runtime_key, two_agents["a"], pod_id=2).status_code == 422


def test_the_largest_total_is_accepted(client, runtime_key, two_agents):
    assert meter(client, runtime_key, two_agents["a"], total=MAX_METERED_USD_MICROS).status_code == 200


# --- halt, secrecy, rebuild ---------------------------------------------------

def test_metering_is_refused_under_halt(client, db, runtime_key, two_agents, halt_file):
    halt_file.write_text("stop")
    assert meter(client, runtime_key, two_agents["a"]).status_code == 423
    assert events_of(db, EVENT_COST_METERED) == []
    halt_file.unlink()
    assert meter(client, runtime_key, two_agents["a"]).status_code == 200


def test_agents_read_key_ref_as_withheld(client, db, runtime_key, admin_key, two_agents):
    meter(client, runtime_key, two_agents["a"], "secret-label", 100)
    seen = client.get("/events", headers={"X-API-Key": admin_key}, params={"type": EVENT_COST_METERED})
    assert seen.status_code == 200, seen.text
    body = seen.json()
    [row] = body if isinstance(body, list) else body["events"]
    assert row["payload_json"]["key_ref"] == "withheld"
    assert row["payload_json"]["usd_micros_total"] == 100   # only the label is hidden
    assert "secret-label" not in seen.text
    [stored] = events_of(db, EVENT_COST_METERED)
    assert stored.payload_json["key_ref"] == "secret-label"


def test_metered_cost_survives_rebuild_state(client, db, runtime_key, admin_key, two_agents):
    meter(client, runtime_key, two_agents["a"], "k1", 7_000_000)
    before = compute_pod_metrics(db, pod_id=two_agents["pod"]).cost
    rebuild_state(db)
    db.expire_all()
    after = compute_pod_metrics(db, pod_id=two_agents["pod"]).cost
    assert before == after
    assert after.metered_usd_cost == 7.0


# --- the reader is not fooled by what the API would refuse --------------------

def test_a_conflicting_ledger_event_does_not_rebind_a_key(db, two_agents):
    """Events forged straight into the ledger: the first binding wins."""
    for agent, total in ((two_agents["a"], 100), (two_agents["b"], 900)):
        append_event(db, type=EVENT_COST_METERED, actor_agent_id=None, payload={
            "agent_id": agent, "pod_id": two_agents["pod"], "key_ref": "k1",
            "usd_micros_total": total,
        })
    db.commit()
    got = metered_by_agent(db)
    assert got[two_agents["a"]].usd_micros == 100
    assert two_agents["b"] not in got
    assert got.conflicts == 1
