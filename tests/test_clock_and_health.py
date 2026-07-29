"""Clock read endpoint and health check."""

from __future__ import annotations


def test_health_is_public(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["clock_mode"] == "live"


def test_clock_requires_management(client, admin_key) -> None:
    # No auth -> 401.
    assert client.get("/clock").status_code == 401
    # Management -> 200 with live mode.
    resp = client.get("/clock", headers={"X-API-Key": admin_key})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"


def test_clock_forbidden_for_analyst(client, admin_key) -> None:
    analyst_key = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": "analyst-1", "role": "analyst"},
    ).json()["api_key"]
    assert client.get("/clock", headers={"X-API-Key": analyst_key}).status_code == 403
