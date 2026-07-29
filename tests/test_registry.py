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
