"""Permission matrix (TRD §6): unit-level and enforced at the API boundary."""

from __future__ import annotations

import pytest

from app.db.models import AgentRole
from app.ledger.events import EVENT_PERMISSION_DENIED, read_events
from app.registry.permissions import Action, has_permission


# --- Matrix unit tests ------------------------------------------------------

@pytest.mark.parametrize(
    ("role", "action", "allowed"),
    [
        (AgentRole.analyst, Action.PLACE_ORDER, False),
        (AgentRole.analyst, Action.REGISTER_AGENTS, False),
        (AgentRole.analyst, Action.SET_ALLOCATION, False),
        (AgentRole.analyst, Action.LIST_AGENTS, True),
        (AgentRole.pm, Action.PLACE_ORDER, True),
        (AgentRole.pm, Action.BROADCAST, True),
        (AgentRole.pm, Action.REGISTER_AGENTS, False),
        (AgentRole.pm, Action.READ_CROSS_POD, False),
        (AgentRole.management, Action.REGISTER_AGENTS, True),
        (AgentRole.management, Action.SET_ALLOCATION, True),
        (AgentRole.management, Action.READ_CROSS_POD, True),
        (AgentRole.management, Action.PLACE_ORDER, False),
        (AgentRole.system, Action.PLACE_ORDER, True),
        # Phase 2: broadcasting is restricted, but reading your own inbox and
        # reporting your own cost and work are not privileges (TRD §7).
        (AgentRole.analyst, Action.BROADCAST, False),
        (AgentRole.analyst, Action.SEND_MESSAGE, True),
        (AgentRole.management, Action.BROADCAST, True),
    ],
)
def test_matrix(role: AgentRole, action: Action, allowed: bool) -> None:
    assert has_permission(role, action) is allowed


@pytest.mark.parametrize(
    "action",
    [
        Action.READ_MESSAGES,
        Action.REPORT_COST,
        Action.REPORT_TASK,
        Action.READ_HALT,
        Action.READ_CLOCK,
    ],
)
@pytest.mark.parametrize(
    "role", [AgentRole.analyst, AgentRole.pm, AgentRole.management, AgentRole.system]
)
def test_every_agent_may_read_its_inbox_and_report_its_own_work(
    role: AgentRole, action: Action
) -> None:
    assert has_permission(role, action) is True


def test_no_role_is_missing_from_the_matrix() -> None:
    """A new role must be granted permissions deliberately, not by accident.

    ``has_permission`` returns False for an unknown role, so a role added to the
    enum and forgotten here would silently be able to do nothing — a confusing
    failure. Failing loudly in the suite instead is cheaper than debugging it.
    """
    for role in AgentRole:
        assert any(has_permission(role, action) for action in Action), (
            f"role {role.value!r} has no permissions at all — was it added to "
            "AgentRole without being added to the matrix?"
        )


# --- API-level enforcement --------------------------------------------------

def _register(client, admin_key, name, role):
    resp = client.post(
        "/agents/register",
        headers={"X-API-Key": admin_key},
        json={"name": name, "role": role},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


def test_unauthenticated_is_401(client) -> None:
    assert client.get("/agents").status_code == 401


def test_bad_key_is_401(client) -> None:
    resp = client.get("/agents", headers={"X-API-Key": "fk_nope"})
    assert resp.status_code == 401


def test_management_can_register(client, admin_key) -> None:
    key = _register(client, admin_key, "analyst-1", "analyst")
    assert key.startswith("fk_")


def test_analyst_cannot_register(client, admin_key) -> None:
    analyst_key = _register(client, admin_key, "analyst-1", "analyst")
    resp = client.post(
        "/agents/register",
        headers={"X-API-Key": analyst_key},
        json={"name": "sneaky", "role": "analyst"},
    )
    assert resp.status_code == 403


def test_pm_cannot_read_events(client, admin_key) -> None:
    pm_key = _register(client, admin_key, "pm-1", "pm")
    assert client.get("/events", headers={"X-API-Key": pm_key}).status_code == 403


def test_analyst_can_read_directory(client, admin_key) -> None:
    analyst_key = _register(client, admin_key, "analyst-1", "analyst")
    resp = client.get("/agents", headers={"X-API-Key": analyst_key})
    assert resp.status_code == 200
    names = {a["name"] for a in resp.json()}
    assert {"management", "analyst-1"} <= names


def test_denial_is_logged_as_event(client, admin_key, db) -> None:
    analyst_key = _register(client, admin_key, "analyst-1", "analyst")
    client.post(
        "/agents/register",
        headers={"X-API-Key": analyst_key},
        json={"name": "x", "role": "analyst"},
    )
    denials = read_events(db, type=EVENT_PERMISSION_DENIED)
    assert len(denials) == 1
    assert denials[0].payload_json["action"] == Action.REGISTER_AGENTS.value
