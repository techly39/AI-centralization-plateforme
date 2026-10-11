"""Clock read endpoint and health check.

Every authenticated agent may read the clock (ADR-026, B-020): in backtest mode
the fund's "now" is a simulated date, and an agent that cannot learn it has no
honest way to reason about time. Clock *control* is a different matter — none
exists on the surface yet (B-004 gates it to system/management).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.db.models import AgentRole, Event
from app.registry.permissions import Action, has_permission

ROLES = ["analyst", "pm", "management"]


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def _key(agent_factory, make_pod, role: str) -> str:
    pod_id = make_pod(1)
    _, key = agent_factory(f"{role}-clock", role, pod_id if role != "management" else None)
    return key


def test_health_is_public(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["clock_mode"] == "live"


def test_clock_requires_authentication(client, admin_key) -> None:
    assert client.get("/clock").status_code == 401
    assert client.get("/clock", headers=H("not-a-key")).status_code == 401
    resp = client.get("/clock", headers=H(admin_key))
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"


def test_every_role_may_read_the_clock() -> None:
    for role in AgentRole:
        assert has_permission(role, Action.READ_CLOCK), role


@pytest.mark.parametrize("role", ROLES)
def test_every_role_reads_the_clocks_now(
    frozen_clock, client, agent_factory, make_pod, role
) -> None:
    key = _key(agent_factory, make_pod, role)
    # After the fixtures' stamps: an earlier moment is a step back, where /clock
    # reports the held ledger time (tests/test_redteam_0006.py).
    moment = datetime(2026, 9, 4, 14, 30, tzinfo=timezone.utc)
    frozen_clock.set(moment)
    resp = client.get("/clock", headers=H(key))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"mode", "now"}
    assert body["mode"] == "frozen"
    assert datetime.fromisoformat(body["now"]) == moment


def test_the_clock_a_pm_reads_is_the_one_its_orders_are_stamped_with(
    frozen_clock, client, desk, prices
) -> None:
    _, _, pm_key = desk
    frozen_clock.set(datetime(2026, 6, 2, 15, 0, tzinfo=timezone.utc))
    now = datetime.fromisoformat(client.get("/clock", headers=H(pm_key)).json()["now"])
    order = client.post("/orders", headers=H(pm_key), json={
        "ticker": "AAPL", "side": "buy", "qty": 1.0,
        "price_type": "market", "justification": "what time is it",
    })
    assert order.status_code == 201, order.text
    assert datetime.fromisoformat(order.json()["created_at"]) == now


@pytest.mark.parametrize("role", ROLES)
def test_reading_the_clock_writes_nothing(client, agent_factory, make_pod, db, role) -> None:
    key = _key(agent_factory, make_pod, role)
    before = db.scalar(select(func.count(Event.id)))
    for _ in range(3):
        assert client.get("/clock", headers=H(key)).status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count(Event.id))) == before


@pytest.mark.parametrize("role", ROLES)
def test_the_clock_reads_during_halt(client, agent_factory, make_pod, halt_file, role) -> None:
    key = _key(agent_factory, make_pod, role)
    halt_file.write_text("stop\n")
    assert client.get("/clock", headers=H(key)).status_code == 200


def test_a_deactivated_agent_cannot_read_the_clock(client, admin_key, agent_factory, make_pod):
    agent_id, key = agent_factory("an-gone", "analyst", make_pod(1))
    resp = client.post(f"/agents/{agent_id}/deactivate", headers=H(admin_key))
    assert resp.status_code == 200, resp.text
    assert client.get("/clock", headers=H(key)).status_code == 401
