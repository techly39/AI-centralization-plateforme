"""Halt in physics (Constitution Art. 5, 03_WORLD §2, backlog B-003).

When the Human creates ``governance/HALT`` the world stops changing: every
state-changing request from every agent is refused with 423 and a
``halt_refused`` event, reads keep working (agents and the Observatory can still
see the world), ``GET /halt`` says so, and the pending-order monitor fills
nothing. Deleting the file resumes the world without a restart.

The "every write" claim is checked against the app's own route table, not a
hand-written list, so a write endpoint added later is covered the day it lands.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import AgentRole, Event, Message, Order, OrderStatus
from app.ledger.events import EVENT_HALT_REFUSED
from app.main import create_app
from app.oms.monitor import check_pending_orders
from app.registry.halt import is_halted
from app.registry.permissions import Action, has_permission

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


@pytest.fixture
def halt_file(tmp_path: Path) -> Iterator[Path]:
    """Point physics at a HALT file the test owns (absent until created)."""
    cfg = get_settings().governance
    previous = cfg.halt_file
    cfg.halt_file = tmp_path / "HALT"
    yield cfg.halt_file
    cfg.halt_file = previous


def _write_routes() -> list[tuple[str, str]]:
    # From the OpenAPI schema, like tests/test_mcp_server.py: app.routes nests
    # included routers in this FastAPI version, so walking it finds nothing.
    routes = []
    for path, operations in create_app().openapi()["paths"].items():
        for method in operations:
            if method.upper() not in READ_METHODS:
                routes.append((method.upper(), path))
    return sorted(routes)


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _count(db, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where))


def test_the_write_surface_is_not_empty():
    # Guards the parametrised test below against silently testing nothing.
    assert {("POST", "/orders"), ("POST", "/messages"), ("DELETE", "/orders/{order_id}")} <= set(
        _write_routes()
    )


def test_a_relative_halt_path_is_anchored_at_the_repo_root_not_the_cwd():
    from app.config import REPO_ROOT, GovernanceConfig

    assert GovernanceConfig().halt_file == REPO_ROOT / "governance" / "HALT"
    assert GovernanceConfig(halt_file="governance/HALT").halt_file == REPO_ROOT / "governance" / "HALT"
    assert GovernanceConfig(halt_file="/tmp/X").halt_file == Path("/tmp/X")


def test_halt_is_off_without_the_file(client, admin_key, halt_file):
    assert not is_halted()
    resp = client.get("/halt", headers={"X-API-Key": admin_key})
    assert resp.status_code == 200
    assert resp.json() == {"halted": False}


def test_every_role_may_read_the_halt_state():
    for role in AgentRole:
        assert has_permission(role, Action.READ_HALT), role


@pytest.mark.parametrize("role", ["analyst", "pm", "management"])
def test_get_halt_reports_halted_to_every_role(
    client, agent_factory, make_pod, halt_file, role
):
    pod_id = make_pod(1)
    _, key = agent_factory(f"{role}-x", role, pod_id if role != "management" else None)
    halt_file.write_text("stop\n")
    resp = client.get("/halt", headers={"X-API-Key": key})
    assert resp.status_code == 200
    assert resp.json() == {"halted": True}


@pytest.mark.parametrize(("method", "path"), _write_routes())
def test_every_write_route_is_refused_while_halted(
    client, admin_key, db, halt_file, method, path
):
    halt_file.write_text("")  # an empty file halts too: existence is the switch
    before = db.scalar(select(func.max(Event.id))) or 0
    resp = client.request(
        method, _concrete(path), headers={"X-API-Key": admin_key}, json={}
    )
    assert resp.status_code == 423, resp.text
    assert "halted" in resp.json()["detail"].lower()
    db.expire_all()
    events = db.scalars(select(Event).where(Event.id > before)).all()
    refused = [e for e in events if e.type == EVENT_HALT_REFUSED]
    assert len(refused) == 1
    assert refused[0].payload_json["method"] == method
    assert refused[0].payload_json["path"] == _concrete(path)
    assert refused[0].payload_json["role"] == "management"
    # The refusal is the only thing that happened.
    assert [e.type for e in events] == [EVENT_HALT_REFUSED]


def test_a_halted_pm_cannot_trade_and_nothing_changes(client, desk, db, halt_file):
    pod_id, _, pm_key = desk
    halt_file.touch()
    headers = {"X-API-Key": pm_key}
    order = {"ticker": "AAPL", "side": "buy", "qty": 10, "price_type": "market", "justification": "t"}
    assert client.post("/orders", headers=headers, json=order).status_code == 423
    msg = {"to": "broadcast", "body": "buy everything"}
    assert client.post("/messages", headers=headers, json=msg).status_code == 423
    assert _count(db, Order) == 0
    assert _count(db, Message) == 0
    # Reads still work: an agent can see the world it may not change.
    assert client.get(f"/portfolio/{pod_id}", headers=headers).status_code == 200
    assert client.get("/orders", headers=headers).status_code == 200


def test_halt_is_checked_on_every_request_not_cached(client, desk, halt_file):
    _, _, pm_key = desk
    headers = {"X-API-Key": pm_key}
    order = {"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market", "justification": "t"}
    assert client.post("/orders", headers=headers, json=order).status_code == 201
    halt_file.touch()
    assert client.post("/orders", headers=headers, json=order).status_code == 423
    halt_file.unlink()
    assert client.post("/orders", headers=headers, json=order).status_code == 201


def test_unauthenticated_write_while_halted_is_still_401(client, halt_file, db):
    halt_file.touch()
    resp = client.post("/orders", headers={"X-API-Key": "nope"}, json={})
    assert resp.status_code == 401
    assert _count(db, Event, Event.type == EVENT_HALT_REFUSED) == 0


def test_pending_monitor_fills_nothing_while_halted(client, desk, db, prices, halt_file):
    _, _, pm_key = desk
    order = {
        "ticker": "AAPL",
        "side": "buy",
        "qty": 5,
        "price_type": "limit",
        "limit_price": 150.0,
        "justification": "t",
    }
    resp = client.post("/orders", headers={"X-API-Key": pm_key}, json=order)
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["id"]
    prices.set_price("AAPL", 140.0)  # the market crosses the limit

    halt_file.touch()
    result = check_pending_orders(db)
    assert not result
    db.expire_all()
    assert db.get(Order, order_id).status is OrderStatus.pending

    halt_file.unlink()
    result = check_pending_orders(db)
    assert result.filled == [order_id]
