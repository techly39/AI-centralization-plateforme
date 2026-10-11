"""RED-TEAM 0003 — attacks on the halt in physics (cycle 0011, ADR-023).

Written by the red-team subagent. Each test is one attack made with exactly what
a firm agent holds: an API key and the REST API. The goal of every attack is a
halted world that still changes, or a halt that misbehaves.

* Plain tests are attacks the physics **refused**. They stay as regression guards.
* ``xfail(strict=True)`` tests are **holes**: the attack worked. The marker
  records the hole honestly; when the Builder fixes it the test starts passing,
  strict mode turns that into a failure, and the marker must be removed.

The halt file is always a tmp path (never the real repo halt file, which would
stop the Builder's loop).
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import func, select

from app.db.models import Event, Order, OrderStatus
from app.ledger.events import EVENT_HALT_REFUSED
from app.oms.monitor import check_pending_orders


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


# ``halt_file`` is the autouse fixture in tests/conftest.py: a tmp path
# monkeypatched onto ``app.registry.halt.HALT_FILE``, absent until created.


# =============================================================================
# HOLES FOUND THIS CYCLE — both fixed in cycle 0011, kept as regression guards
# =============================================================================

def test_held_halt_refusal_is_not_a_covert_channel_into_the_ledger(
    client, agent_factory, make_pod, admin_key, db, halt_file
):
    # Found as a hole in cycle 0011 (medium): the halt_refused payload stored the
    # raw request path, and the auth gate runs before path params are validated,
    # so DELETE /orders/<8 KB of text> wrote agent-chosen text into the ledger in
    # a halted world, readable by management via GET /events. Fixed in the same
    # cycle (payload stores the route template); kept as a regression guard.
    make_pod(1)
    _, analyst_key = agent_factory("an-1", "analyst", 1)
    halt_file.touch()

    secret = "SELL-NVDA-AT-OPEN-" + "x" * 8000
    # Not a valid order id: FastAPI resolves the auth dependency (and so the
    # halt gate) before it validates `order_id: int`.
    resp = client.delete(f"/orders/{secret}", headers=H(analyst_key))
    assert resp.status_code == 423

    # Messages are refused; the refusal must not carry the text in instead ...
    resp = client.get(
        "/events", headers=H(admin_key), params={"type": EVENT_HALT_REFUSED}
    )
    assert resp.status_code == 200, resp.text
    events = resp.json()
    assert len(events) == 1  # the refusal itself is recorded, as designed
    assert events[0]["payload_json"]["path"] == "/orders/{order_id}"
    leaked = [e for e in events if "SELL-NVDA-AT-OPEN" in str(e["payload_json"])]
    # ... physics should not store agent-chosen free text (or 8 KB of it).
    assert leaked == []


# Found as a hole in cycle 0011 (low): the monitor checked the halt BEFORE taking
# OMS_LOCK, so a sweep queued behind the lock woke up and filled crossing orders
# in a world halted while it waited. Fixed in the same cycle (check under the
# lock); kept as a regression guard.
def test_held_monitor_sweep_queued_on_lock_does_not_fill_after_halt(
    client, desk, SessionFactory, db, halt_file, prices, monkeypatch
):
    from app.oms import monitor as monitor_mod
    from app.oms.service import OMS_LOCK

    _, _, pm_key = desk
    order = {
        "ticker": "AAPL",
        "side": "buy",
        "qty": 5,
        "price_type": "limit",
        "limit_price": 150.0,
        "justification": "t",
    }
    resp = client.post("/orders", headers=H(pm_key), json=order)
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["id"]

    prices.set_price("AAPL", 140.0)  # the market crosses the limit

    # Observe (without changing) the monitor's halt check, to know when the
    # sweep is past it.
    checked = threading.Event()
    real_is_halted = monitor_mod.is_halted

    def observed_is_halted() -> bool:
        value = real_is_halted()
        checked.set()
        return value

    monkeypatch.setattr(monitor_mod, "is_halted", observed_is_halted)

    outcome: dict = {}

    def sweep() -> None:
        session = SessionFactory()
        try:
            outcome["result"] = check_pending_orders(session)
        finally:
            session.close()

    with OMS_LOCK:  # something else holds the book (another sweep, an order)
        worker = threading.Thread(target=sweep)
        worker.start()
        # The fixed monitor checks under the lock, so this wait times out; the
        # sweep is then queued on the lock, which is the case under attack.
        checked.wait(timeout=1)
        halt_file.touch()  # the Human halts while the sweep is queued
    worker.join(timeout=10)
    assert not worker.is_alive()

    assert halt_file.exists()
    db.expire_all()
    assert db.get(Order, order_id).status is OrderStatus.pending, outcome


# =============================================================================
# HELD — method / path tricks against the gate
# =============================================================================

@pytest.mark.parametrize("override", ["GET", "HEAD", "OPTIONS"])
def test_held_method_override_headers_are_ignored(client, desk, db, halt_file, override):
    _, _, pm_key = desk
    halt_file.touch()
    headers = {
        **H(pm_key),
        "X-HTTP-Method-Override": override,
        "X-HTTP-Method": override,
        "X-Method-Override": override,
    }
    order = {"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market", "justification": "t"}
    assert client.post("/orders", headers=headers, json=order).status_code == 423
    assert db.scalar(select(func.count()).select_from(Order)) == 0


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "PUT", "PATCH"])
def test_held_read_methods_on_write_paths_do_not_reach_handlers(
    client, desk, db, halt_file, method
):
    _, _, pm_key = desk
    halt_file.touch()
    order = {"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market", "justification": "t"}
    resp = client.request(method, "/orders", headers=H(pm_key), json=order)
    assert resp.status_code == 405
    assert db.scalar(select(func.count()).select_from(Order)) == 0


async def _raw_asgi(app, method: str, path: str, key: str, body: bytes) -> int:
    """Send one request straight through ASGI, method string untouched."""
    sent: list[dict] = []
    done = False

    async def receive():  # noqa: ANN202
        nonlocal done
        if done:
            return {"type": "http.disconnect"}
        done = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):  # noqa: ANN001, ANN202
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"x-api-key", key.encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


@pytest.mark.parametrize("method", ["post", "Post", "POST "])
def test_held_odd_case_methods_never_reach_a_write_handler(
    client, desk, db, halt_file, method
):
    import anyio

    _, _, pm_key = desk
    halt_file.touch()
    body = b'{"ticker":"AAPL","side":"buy","qty":1,"price_type":"market","justification":"t"}'
    status = anyio.run(_raw_asgi, client.app, method, "/orders", pm_key, body)
    assert status in (405, 423)
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_held_trailing_slash_and_dot_segments_do_not_bypass(client, desk, db, halt_file):
    _, _, pm_key = desk
    halt_file.touch()
    order = {"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market", "justification": "t"}
    for path in ("/orders/", "//orders", "/orders/../orders", "/ORDERS"):
        resp = client.post(path, headers=H(pm_key), json=order, follow_redirects=True)
        assert resp.status_code in (404, 405, 423), (path, resp.status_code)
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_held_malformed_body_is_rejected_before_any_state_change(client, desk, db, halt_file):
    _, _, pm_key = desk
    halt_file.touch()
    resp = client.post(
        "/orders",
        headers={**H(pm_key), "content-type": "application/json"},
        content=b"{not json",
    )
    assert resp.status_code in (422, 423)
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_held_halt_refused_events_do_not_break_rebuild_state(
    client, desk, db, halt_file, SessionFactory
):
    from app.ledger.rebuild import rebuild_state

    pod_id, _, pm_key = desk
    order = {"ticker": "AAPL", "side": "buy", "qty": 3, "price_type": "market", "justification": "t"}
    assert client.post("/orders", headers=H(pm_key), json=order).status_code == 201
    halt_file.touch()
    for _ in range(5):
        assert client.post("/orders", headers=H(pm_key), json=order).status_code == 423
    before = client.get(f"/portfolio/{pod_id}", headers=H(pm_key)).json()

    session = SessionFactory()
    try:
        rebuild_state(session)
        session.commit()
    finally:
        session.close()
    after = client.get(f"/portfolio/{pod_id}", headers=H(pm_key)).json()
    assert after["cash"] == before["cash"]
    assert after["positions"] == before["positions"]
    db.expire_all()
    assert db.scalar(
        select(func.count()).select_from(Event).where(Event.type == EVENT_HALT_REFUSED)
    ) == 5
