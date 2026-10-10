"""Registry lifecycle: register, directory, deactivate, and audit events."""

from __future__ import annotations

from app.ledger.events import (
    EVENT_AGENT_DEACTIVATED,
    EVENT_AGENT_REGISTERED,
    read_events,
)
from app.registry.security import generate_api_key, hash_api_key


def test_generated_keys_are_unique_and_hash_stably() -> None:
    k1, k2 = generate_api_key(), generate_api_key()
    assert k1 != k2
    assert k1.startswith("fk_")
    assert hash_api_key(k1) == hash_api_key(k1)
    assert hash_api_key(k1) != hash_api_key(k2)


def test_register_returns_key_and_logs_event(client, admin_key, db, make_pod) -> None:
    make_pod(1)
    resp = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": "pm-1", "role": "pm", "pod_id": 1},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["api_key"].startswith("fk_")
    assert body["role"] == "pm"
    assert body["pod_id"] == 1

    registrations = read_events(db, type=EVENT_AGENT_REGISTERED)
    # One for the seeded admin, one for pm-1.
    assert {e.payload_json["name"] for e in registrations} == {"management", "pm-1"}


def test_duplicate_name_conflicts(client, admin_key) -> None:
    payload = {"name": "dup", "role": "analyst"}
    first = client.post("/agents/register", headers={"X-API-Key": admin_key}, json=payload)
    assert first.status_code == 201
    second = client.post("/agents/register", headers={"X-API-Key": admin_key}, json=payload)
    assert second.status_code == 409


def test_cannot_register_system_role(client, admin_key) -> None:
    resp = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": "sys", "role": "system"},
    )
    assert resp.status_code == 422  # 'system' is not a registerable role


def test_deactivate_flow(client, admin_key, db) -> None:
    created = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": "analyst-1", "role": "analyst"},
    ).json()
    agent_id, agent_key = created["id"], created["api_key"]

    # The agent can authenticate before deactivation...
    assert client.get("/agents", headers={"X-API-Key": agent_key}).status_code == 200

    resp = client.post(
        f"/agents/{agent_id}/deactivate", headers={"X-API-Key": admin_key}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"

    # ...and is rejected after (inactive keys don't authenticate).
    assert client.get("/agents", headers={"X-API-Key": agent_key}).status_code == 401
    assert len(read_events(db, type=EVENT_AGENT_DEACTIVATED)) == 1


def test_deactivate_missing_is_404(client, admin_key) -> None:
    resp = client.post("/agents/9999/deactivate", headers={"X-API-Key": admin_key})
    assert resp.status_code == 404


# --- GET /me ----------------------------------------------------------------
#
# An agent that cannot ask who it is has to be told in its prompt, and that copy
# drifts. These tests pin the one property that makes /me worth having: what it
# returns is the database row behind the key, whoever is holding it.

def test_me_returns_the_identity_behind_the_key(client, admin_key, make_pod) -> None:
    make_pod(1)
    created = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={
            "name": "pm-1",
            "role": "pm",
            "pod_id": 1,
            "research_domains": ["banks"],
        },
    ).json()

    resp = client.get("/me", headers={"X-API-Key": created["api_key"]})
    assert resp.status_code == 200
    assert resp.json() == {
        "id": created["id"],
        "name": "pm-1",
        "role": "pm",
        "pod_id": 1,
        "research_domains": ["banks"],
        "status": "active",
    }


def test_me_needs_no_privilege_beyond_being_authenticated(
    client, admin_key, agent_factory, make_pod
) -> None:
    """Every role can read its own row — including the analyst, who may do least."""
    make_pod(1)
    analyst_id, analyst_key = agent_factory("analyst-1", "analyst", 1)

    assert client.get("/me", headers={"X-API-Key": analyst_key}).json()["id"] == analyst_id
    # Management belongs to no pod, and says so rather than guessing.
    assert client.get("/me", headers={"X-API-Key": admin_key}).json()["pod_id"] is None


def test_me_is_not_a_way_around_authentication(client) -> None:
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"X-API-Key": "fk_nonsense"}).status_code == 401


def test_me_agrees_with_the_directory(client, admin_key, agent_factory, make_pod) -> None:
    """The two views of identity must not diverge — same row, same answer."""
    make_pod(1)
    agent_id, agent_key = agent_factory("analyst-1", "analyst", 1)

    directory = client.get("/agents", headers={"X-API-Key": agent_key}).json()
    mine = client.get("/me", headers={"X-API-Key": agent_key}).json()
    assert mine == next(row for row in directory if row["id"] == agent_id)
