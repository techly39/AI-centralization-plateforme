"""RED-TEAM 0001 — attacks on the Phase 2 surface (bus, self-reporting, metrics, MCP).

Written by the red-team subagent for cycle 0001. Each test is one attack made
with exactly what a firm agent holds: an API key, the REST API, and the MCP tools.

* Plain tests are attacks the physics **refused**. They stay as regression guards.
* ``xfail(strict=True)`` tests are **holes**: the attack worked. The marker
  records the hole honestly; when the Builder fixes it the test starts passing,
  strict mode turns that into a failure, and the marker must be removed.
"""

from __future__ import annotations

import math

import httpx
import pytest
from sqlalchemy import select

from app.db.models import AgentRole, Event
from app.ledger.events import EVENT_MESSAGE_SENT, EVENT_PERMISSION_DENIED
from app.main import create_app
from app.registry.service import get_or_create_system_agent
from mcp_server import FundClient, build_server


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def send(client, key, **body):
    return client.post("/messages", headers=H(key), json=body)


def inbox(client, key, **params):
    resp = client.get("/messages", headers=H(key), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def two_desks(client, make_pod, fund_pod_cash, pm_factory, agent_factory):
    """Two funded pods, each with a PM and an analyst."""
    make_pod(1)
    make_pod(2)
    fund_pod_cash(1, 100_000.0)
    fund_pod_cash(2, 100_000.0)
    pm1 = pm_factory("pm-1", 1)
    pm2 = pm_factory("pm-2", 2)
    an1 = agent_factory("analyst-1", "analyst", 1)
    an2 = agent_factory("analyst-2", "analyst", 2)
    return {"pm1": pm1, "pm2": pm2, "an1": an1, "an2": an2}


# =============================================================================
# HELD — impersonation / reading as someone else
# =============================================================================

def test_held_cannot_spoof_sender_field(client, two_desks):
    _, an1_key = two_desks["an1"]
    pm2_id, _ = two_desks["pm2"]
    for extra in ({"from_agent": pm2_id}, {"from": "agent:1"}, {"sender": 1}):
        resp = send(client, an1_key, to="pod:2", body="hi", **extra)
        assert resp.status_code == 422, extra


def test_held_cannot_read_other_pods_dm_or_pod_channel(client, two_desks):
    pm1_id, pm1_key = two_desks["pm1"]
    _, an1_key = two_desks["an1"]
    _, pm2_key = two_desks["pm2"]
    _, an2_key = two_desks["an2"]

    dm = send(client, an1_key, to=f"agent:{pm1_id}", body="secret DM",
              thread_id="alpha-thesis").json()
    chan = send(client, pm1_key, to="pod:1", body="secret pod note",
                thread_id="alpha-thesis").json()

    for key in (pm2_key, an2_key):
        for params in ({}, {"thread": "alpha-thesis"}, {"latest": True},
                       {"before_id": 10_000}, {"after_id": 0},
                       {"since": "2000-01-01T00:00:00Z"}):
            ids = {m["id"] for m in inbox(client, key, **params)}
            assert dm["id"] not in ids and chan["id"] not in ids, params


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "False"])
def test_held_mine_false_requires_management(client, two_desks, db, value):
    _, pm2_key = two_desks["pm2"]
    _, an2_key = two_desks["an2"]
    for key in (pm2_key, an2_key):
        resp = client.get("/messages", headers=H(key), params={"mine": value})
        assert resp.status_code == 403
    denials = db.scalars(
        select(Event).where(Event.type == EVENT_PERMISSION_DENIED)
    ).all()
    assert any(e.payload_json.get("action") == "read_cross_pod" for e in denials)


def test_held_deactivated_key_is_dead(client, two_desks, admin_key):
    an2_id, an2_key = two_desks["an2"]
    assert client.post(f"/agents/{an2_id}/deactivate", headers=H(admin_key)).status_code == 200
    assert client.get("/messages", headers=H(an2_key)).status_code == 401
    assert send(client, an2_key, to="pod:2", body="still here?").status_code == 401
    assert client.post("/costs", headers=H(an2_key),
                       json={"tokens_in": 0, "tokens_out": 0, "usd_cost": 0}).status_code == 401


# =============================================================================
# HELD — broadcast / chat restrictions
# =============================================================================

@pytest.mark.parametrize("to", ["broadcast", "Broadcast", " BROADCAST "])
def test_held_analyst_cannot_broadcast(client, two_desks, to):
    _, an1_key = two_desks["an1"]
    assert send(client, an1_key, to=to, body="all hands").status_code == 403


def test_held_pm_broadcast_is_scoped_to_own_pod(client, two_desks):
    _, pm1_key = two_desks["pm1"]
    _, pm2_key = two_desks["pm2"]
    resp = send(client, pm1_key, to="broadcast", body="to the firm?")
    assert resp.status_code == 201
    assert resp.json()["to"] == "pod:1"
    assert resp.json()["id"] not in {m["id"] for m in inbox(client, pm2_key)}


def test_held_no_central_pod_restriction_cross_pod_chat_works(client, two_desks):
    """04_FIRM.md asks whether chat is restricted to a central pod. It is not."""
    pm1_id, pm1_key = two_desks["pm1"]
    _, an2_key = two_desks["an2"]
    resp = send(client, an2_key, to=f"agent:{pm1_id}", body="cross-pod hello")
    assert resp.status_code == 201
    assert resp.json()["id"] in {m["id"] for m in inbox(client, pm1_key)}
    assert send(client, an2_key, to="pod:1", body="to pod 1").status_code == 201


@pytest.mark.parametrize("to", ["agent:0", "agent:-1", "pod:abc", "agent:1;DROP", "*",
                                "pod:1,pod:2", "agent:1 pod:2"])
def test_held_malformed_refs_refused(client, two_desks, to):
    _, an1_key = two_desks["an1"]
    assert send(client, an1_key, to=to, body="x").status_code == 422


# =============================================================================
# HELD — forging cost / task reports for someone else
# =============================================================================

@pytest.mark.parametrize("extra", [{"agent_id": 1}, {"pod_id": 2}, {"usd_cost": -5.0},
                                   {"tokens_in": -1}, {"tokens_out": -1}])
def test_held_cost_report_cannot_be_redirected_or_negative(client, two_desks, extra):
    _, an1_key = two_desks["an1"]
    body = {"tokens_in": 1, "tokens_out": 1, "usd_cost": 1.0, **extra}
    assert client.post("/costs", headers=H(an1_key), json=body).status_code == 422


def test_held_cannot_close_or_rewrite_rivals_task(client, two_desks):
    _, pm2_key = two_desks["pm2"]
    _, an1_key = two_desks["an1"]
    tid = client.post("/tasks/start", headers=H(pm2_key), json={"subject": "s"}).json()["id"]
    resp = client.post("/tasks/end", headers=H(an1_key),
                       json={"task_id": tid, "outcome": {"x": 1}})
    assert resp.status_code == 403
    # owner closes it; a second close (history rewrite) is refused
    assert client.post("/tasks/end", headers=H(pm2_key),
                       json={"task_id": tid, "outcome": {"x": 1}}).status_code == 200
    assert client.post("/tasks/end", headers=H(pm2_key),
                       json={"task_id": tid, "outcome": {"x": 2}}).status_code == 409


def test_held_cost_lands_on_reporters_pod_only(client, two_desks, admin_key):
    _, an1_key = two_desks["an1"]
    client.post("/costs", headers=H(an1_key),
                json={"tokens_in": 10, "tokens_out": 10, "usd_cost": 50.0})
    m2 = client.get("/metrics/pod/2", headers=H(admin_key)).json()
    m1 = client.get("/metrics/pod/1", headers=H(admin_key)).json()
    assert m2["cost"]["total_usd_cost"] == 0.0
    assert m1["cost"]["total_usd_cost"] == 50.0


# =============================================================================
# HELD — management-only views
# =============================================================================

@pytest.mark.parametrize("path", ["/metrics/leaderboard", "/metrics/pod/1",
                                  "/metrics/pod/2", "/events"])
def test_held_non_management_cannot_see_metrics_or_ledger(client, two_desks, path):
    for who in ("pm1", "an1"):
        _, key = two_desks[who]
        assert client.get(path, headers=H(key)).status_code == 403


# =============================================================================
# HOLES — metrics manipulation via self-reported cost
# =============================================================================

def test_held_metrics_token_overflow_dos(client, two_desks, admin_key):
    """Was a hole (cycle 0001): any role reported two in-range token counts
    whose SUM overflowed int64, and ``_cost_metrics`` raised on every call —
    management lost /metrics/leaderboard and /metrics/pod/1 for the run.
    Fixed in cycle 0002: one report is capped at MAX_TOKENS_PER_REPORT, so the
    attack is refused at the door and the leaderboard stays up."""
    _, an1_key = two_desks["an1"]
    for _ in range(2):
        r = client.post("/costs", headers=H(an1_key),
                        json={"tokens_in": 2**63 - 1, "tokens_out": 0, "usd_cost": 0.0})
        assert r.status_code == 422
    resp = client.get("/metrics/leaderboard", headers=H(admin_key))
    assert resp.status_code == 200
    assert client.get("/metrics/pod/1", headers=H(admin_key)).status_code == 200


def test_held_metrics_survive_token_rows_whose_sum_exceeds_int64(
    client, two_desks, admin_key, SessionFactory
):
    """Second wall behind the cap: rows that got in another way (a future
    system cost-sync, a hand-edited db) must not take the metrics down either."""
    from app.db.models import Agent, Cost
    from app.clock import get_clock

    an1_id, _ = two_desks["an1"]
    session = SessionFactory()
    try:
        agent = session.get(Agent, an1_id)
        for _ in range(2):
            session.add(Cost(ts=get_clock().now(), agent_id=agent.id, pod_id=agent.pod_id,
                             tokens_in=2**63 - 1, tokens_out=0, usd_cost=0.0))
        session.commit()
    finally:
        session.close()
    assert client.get("/metrics/leaderboard", headers=H(admin_key)).status_code == 200
    resp = client.get("/metrics/pod/1", headers=H(admin_key))
    assert resp.status_code == 200
    assert resp.json()["cost"]["tokens_in"] >= 2**63


def test_held_metrics_cost_overflows_to_infinity(client, two_desks, admin_key):
    """Was a hole (cycle 0001): two 1e308 reports summed to inf and the headline
    ranking number rendered as ``null`` ('not enough data', not 'infinite cost').
    Fixed in cycle 0012: one report is capped at MAX_USD_PER_REPORT (ADR-024)."""
    _, an1_key = two_desks["an1"]
    for _ in range(2):
        client.post("/costs", headers=H(an1_key),
                    json={"tokens_in": 1, "tokens_out": 1, "usd_cost": 1e308})
    rows = client.get("/metrics/leaderboard", headers=H(admin_key)).json()["rows"]
    row = next(r for r in rows if r["pod_id"] == 1)
    assert row["total_usd_cost"] is not None and math.isfinite(row["total_usd_cost"])
    assert row["cost_adjusted_pnl"] is not None


def test_held_cost_accepts_infinity_literal(client, two_desks):
    """Was a hole (cycle 0001): 'Infinity' was stored. Fixed in cycle 0012 (ADR-024)."""
    _, an1_key = two_desks["an1"]
    resp = client.post(
        "/costs",
        headers={**H(an1_key), "Content-Type": "application/json"},
        content='{"tokens_in": 1, "tokens_out": 1, "usd_cost": Infinity}',
    )
    assert resp.status_code == 422


def test_held_cost_nan_crashes_server(client, two_desks):
    """Was a hole (cycle 0001): the 422 echoed NaN and failed to render (500).
    Fixed in cycle 0012: the validation handler spells it as text (ADR-024)."""
    _, an1_key = two_desks["an1"]
    resp = client.post(
        "/costs",
        headers={**H(an1_key), "Content-Type": "application/json"},
        content='{"tokens_in": 1, "tokens_out": 1, "usd_cost": NaN}',
    )
    assert resp.status_code == 422


def test_held_cost_tokens_beyond_int64_422(client, two_desks):
    """Was a hole (cycle 0001): unhandled OverflowError (500). Fixed in cycle
    0002 by the same per-report cap as the overflow DoS above."""
    _, an1_key = two_desks["an1"]
    resp = client.post("/costs", headers=H(an1_key),
                       json={"tokens_in": 2**64, "tokens_out": 0, "usd_cost": 0.0})
    assert resp.status_code == 422


# =============================================================================
# HOLES — payload size caps
# =============================================================================

@pytest.mark.xfail(strict=True, reason="red-team 0001: structured_payload is unbounded, "
                   "bypassing the 20k body cap (pod-inbox / context-window flooding)")
def test_hole_message_structured_payload_bypasses_body_cap(client, two_desks):
    _, an1_key = two_desks["an1"]
    resp = send(client, an1_key, to="pod:2", body="see payload",
                structured_payload={"blob": "A" * 2_000_000})
    assert resp.status_code == 422


@pytest.mark.xfail(strict=True, reason="red-team 0001: task outcome JSON is unbounded "
                   "(2 MB accepted into tasks table and ledger)")
def test_hole_task_outcome_unbounded(client, two_desks):
    _, an1_key = two_desks["an1"]
    tid = client.post("/tasks/start", headers=H(an1_key), json={"subject": "s"}).json()["id"]
    resp = client.post("/tasks/end", headers=H(an1_key),
                       json={"task_id": tid, "outcome": {"blob": "A" * 2_000_000}})
    assert resp.status_code == 422


# =============================================================================
# HOLE — ledger completeness
# =============================================================================

@pytest.mark.xfail(strict=True, reason="red-team 0001: message_sent event omits body and "
                   "structured_payload; messages table is not reconstructable from the ledger")
def test_hole_message_content_not_on_ledger(client, two_desks, db):
    """A row edited or deleted in ``messages`` is undetectable: the ledger only
    records that *a* message with that id was sent, not what it said."""
    _, an1_key = two_desks["an1"]
    msg = send(client, an1_key, to="pod:2", body="I said this",
               structured_payload={"ticker": "AAPL"}).json()
    event = db.scalar(select(Event).where(
        Event.type == EVENT_MESSAGE_SENT,
        Event.payload_json["message_id"].as_integer() == msg["id"],
    ))
    assert event.payload_json.get("body") == "I said this"
    assert event.payload_json.get("structured_payload") == {"ticker": "AAPL"}


# =============================================================================
# HELD (was a HOLE until cycle 23, B-000f) — identity: squatting the built-in 'system' name
# =============================================================================

def test_hole_system_identity_name_squat(client, make_pod, admin_key, db):
    """``get_or_create_system_agent`` looked the identity up by *name*. On a fresh
    fund (no pod funded yet) management registered an ordinary analyst called
    ``system``; from then on every OMS rejection notice and allocation event was
    attributed to that analyst. Since ADR-033 the name is reserved (409) and the
    identity is found by role. The test keeps its name: it is the 0001 guard."""
    make_pod(1)
    resp = client.post("/agents/register", headers=H(admin_key),
                       json={"name": "system", "role": "analyst", "pod_id": None})
    assert resp.status_code == 409, resp.text      # the name is reserved (ADR-033)
    squatter_id = resp.json().get("id") if resp.status_code == 201 else None
    system = get_or_create_system_agent(db)
    assert system.role is AgentRole.system
    assert system.id != squatter_id


# =============================================================================
# MCP — tools doing more than their endpoint
# =============================================================================

class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.paths: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return await self.inner.handle_async_request(request)


@pytest.fixture
def mcp_as(client):
    from app.db.base import get_session

    app = create_app()
    app.dependency_overrides[get_session] = client.app.dependency_overrides[get_session]

    def _make(api_key: str):
        transport = _RecordingTransport(httpx.ASGITransport(app=app))
        fc = FundClient(base_url="http://fund.test", api_key=api_key, transport=transport)
        return build_server(fc), transport

    return _make


@pytest.mark.anyio
async def test_held_mcp_get_messages_mine_false_refused_for_pm(two_desks, mcp_as):
    _, pm1_key = two_desks["pm1"]
    server, _ = mcp_as(pm1_key)
    try:
        result = await server.call_tool("get_messages", {"mine": False})
        assert result.is_error
    except Exception as exc:  # ToolError surfaces the API's 403
        assert "403" in str(exc)


@pytest.mark.anyio
# Was a strict xfail (B-000h); fixed in cycle 22 (mcp_server.tools._segment, red-team 0013 H1). Guard.
async def test_hole_mcp_path_traversal_reaches_other_endpoint(two_desks, mcp_as):
    """No privilege gain (same key, the API still checks it), but a tool reaches
    an endpoint other than the one recorded in TOOL_ROUTES, so the MCP-mirrors-API
    guarantee and any per-tool auditing are false."""
    _, pm1_key = two_desks["pm1"]
    server, transport = mcp_as(pm1_key)
    try:
        await server.call_tool("get_price", {"ticker": "../health"})
    except Exception:
        pass
    assert transport.paths and all(p.startswith("/price/") for p in transport.paths)
