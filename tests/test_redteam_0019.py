"""Red-team pass 0019 — R-6a physics metering: ``POST /metering/usage``, ``cost_metered`` events,
``metered_by_agent``, the metered override in ``_cost_metrics`` and the leaderboard, the MCP tool
``report_metered_usage`` (ADR-041, cycle 34).

The attacker is any firm agent (analyst, pm, management) with its own key, and — for the reader
— whatever lands in the ledger as a ``cost_metered`` row (the reader claims it is "not fooled by
events forged into the ledger"). The aim: post, rebind, lower or inflate metered cost; read a
``key_ref``; hide or inflate a metered agent's cost by self-reporting; crash or poison the
metrics/leaderboard; double-count under retries or races; write under HALT.

HOLES are plain failing tests: each passes once the Builder fixes it. HELD guards are plain
tests that pass: attacks that failed and must keep failing.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select

from app.db.models import Agent, AgentRole, Base, Event
from app.ledger.events import EVENT_COST_METERED, EVENT_PERMISSION_DENIED, append_event
from app.limits import MAX_METERED_USD_MICROS
from app.metrics.metering import metered_by_agent
from tests.test_metering import meter


# --- rig -------------------------------------------------------------------------------

@pytest.fixture
def engine(tmp_path):
    """File-backed SQLite for this module (one connection per thread, like production), so the
    race tests test the lock and not the StaticPool fixture (see test_oms_concurrency)."""
    eng = create_engine(
        f"sqlite:///{tmp_path / 'rt0019.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def world(client, desk, make_pod, fund_pod_cash, agent_factory, admin_key, runtime_key):
    """Pod 1: PM A + analyst B. Pod 2: PM C. Management M (pod-less). The runtime."""
    pod1, a_id, a_key = desk
    b_id, b_key = agent_factory("analyst-1", "analyst", pod1)
    pod2 = make_pod(2)
    fund_pod_cash(pod2, 100_000.0)
    c_id, c_key = agent_factory("pm-2", "pm", pod2)
    return {
        "pod1": pod1, "pod2": pod2,
        "a": a_id, "a_key": a_key, "b": b_id, "b_key": b_key, "c": c_id, "c_key": c_key,
        "admin": admin_key, "rt": runtime_key,
    }


def H(key: str) -> dict:
    return {"X-API-Key": key}


def selfreport(client, key, usd):
    r = client.post("/costs", headers=H(key), json={"tokens_in": 1, "tokens_out": 1, "usd_cost": usd})
    assert r.status_code == 201, r.text


def cost_of(client, admin_key, pod_id) -> dict:
    r = client.get(f"/metrics/pod/{pod_id}", headers=H(admin_key))
    assert r.status_code == 200, r.text
    return r.json()["cost"]


def metered_events(SessionFactory) -> list[Event]:
    with SessionFactory() as s:
        return list(s.execute(
            select(Event).where(Event.type == EVENT_COST_METERED).order_by(Event.id)).scalars())


def forge(SessionFactory, payload) -> None:
    """A ``cost_metered`` row written straight into the ledger, bypassing the API."""
    with SessionFactory() as s:
        append_event(s, type=EVENT_COST_METERED, actor_agent_id=None, payload=payload)
        s.commit()


# =====================================================================================
# HOLES
# =====================================================================================

# HELD (was a candidate hole): an out-of-range ``agent_id`` in a ``cost_metered`` row would reach
# ``Cost.agent_id.in_(...)`` as a SQL bind and raise ``OverflowError`` in every metrics read, because
# ``_valid`` checks only ``type(agent_id) is int``. It does not reach the reader today:
# ``append_event`` refuses any int beyond 2**53-1 in a payload. A row written by raw SQL could
# still bring it in. Defence in depth (not filed as a hole): bound agent_id/pod_id to 1..MAX_ID in
# ``_valid``.
@pytest.mark.parametrize("agent_id", [2**63, 2**70, -(2**63) - 1])
def test_held_an_out_of_range_agent_id_never_reaches_the_ledger(client, SessionFactory, world,
                                                                agent_id):
    with pytest.raises(ValueError):
        forge(SessionFactory, {"agent_id": agent_id, "pod_id": world["pod1"], "key_ref": "forged",
                               "usd_micros_total": 1_000_000})
    board = client.get("/metrics/leaderboard", headers=H(world["admin"]))
    assert board.status_code == 200, board.text


# HOLE rt0019-1 (low): the metered override is applied per pod named in the *event*, not per
# agent. ``_cost_metrics`` removes a metered agent's self-reports only from the pod that its
# ``cost_metered`` row names (``in_pod``). If the row names another pod than the one holding the
# agent's ``Cost`` rows, the agent counts as metered in pod 2 *and* keeps its self-reports in
# pod 1, so its cost is counted twice, once as self-reported and once as metered. That breaks the
# ADR-041 law ("an agent with any metered row is metered, and its Cost rows leave the
# authoritative total"). Today only a forged row (or a future pod-move endpoint, plan RISKS "Pod
# drift") produces the split, because the writer snapshots ``target.pod_id``. Fix: decide "is
# metered" by agent over the whole fold (subtract ``Cost`` rows where
# ``agent_id IN all metered ids`` in every pod), or take the pod from the registry rather than the
# payload, and keep the per-pod dollars by event pod.
def test_hole_a_metered_agents_self_reports_leave_every_pods_total(client, SessionFactory, world):
    selfreport(client, world["a_key"], 100.0)          # A's own Cost row, in pod 1
    forge(SessionFactory, {"agent_id": world["a"], "pod_id": world["pod2"], "key_ref": "k-split",
                           "usd_micros_total": 5_000_000})
    p1 = cost_of(client, world["admin"], world["pod1"])
    p2 = cost_of(client, world["admin"], world["pod2"])
    assert p1["total_usd_cost"] + p2["total_usd_cost"] == pytest.approx(5.0), (
        f"agent {world['a']} is metered at $5 but the firm counts "
        f"${p1['total_usd_cost'] + p2['total_usd_cost']}: pod 1 still ranks on its $100 "
        f"self-report (pod1={p1}, pod2={p2})")


# =====================================================================================
# HELD — who may post
# =====================================================================================

@pytest.mark.parametrize("who", ["a_key", "b_key", "c_key", "admin"])
@pytest.mark.parametrize("target", ["a", "b", "c", "self"])
def test_held_no_firm_role_can_post_metering_for_anyone(client, SessionFactory, world, who, target):
    me = client.get("/me", headers=H(world[who])).json()["id"] if target == "self" else world[target]
    for body in (
        {"agent_id": me, "key_ref": "k1", "usd_micros_total": 1},
        {"agent_id": me, "key_ref": "k1", "usd_micros_total": 0},
        {"agent_id": me, "key_ref": "BAD\n", "usd_micros_total": True},   # bad body: still 403
    ):
        r = client.post("/metering/usage", headers=H(world[who]), json=body)
        assert r.status_code == 403, (who, target, body, r.text)
    assert metered_events(SessionFactory) == []


def test_held_a_firm_agent_cannot_lower_or_rebind_a_runtime_key(client, SessionFactory, world):
    assert meter(client, world["rt"], world["a"], "k1", 9_000_000).status_code == 200
    for who in ("a_key", "b_key", "c_key", "admin"):
        for agent, total in ((world["a"], 0), (world["c"], 9_000_000), (world["c"], 10**12)):
            r = meter(client, world[who], agent, "k1", total)
            assert r.status_code == 403
    [only] = metered_events(SessionFactory)
    assert only.payload_json["agent_id"] == world["a"]


def test_held_the_permission_denied_row_carries_no_body(client, SessionFactory, world):
    meter(client, world["b_key"], world["a"], "probe-label-xyz", 5)
    with SessionFactory() as s:
        [denied] = s.execute(select(Event).where(Event.type == EVENT_PERMISSION_DENIED)).scalars()
    assert "probe-label-xyz" not in str(denied.payload_json)


def test_held_runtime_cannot_meter_itself_or_system(client, SessionFactory, world):
    from app.registry.service import get_or_create_system_agent
    with SessionFactory() as s:
        sys_id = get_or_create_system_agent(s).id
        s.commit()
        rt_id = s.scalar(select(Agent.id).where(Agent.role == AgentRole.runtime))
    for target in (rt_id, sys_id):
        assert meter(client, world["rt"], target, "k-phys", 1).status_code == 422
    assert metered_events(SessionFactory) == []


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/costs", {"tokens_in": 1, "tokens_out": 1, "usd_cost": 1.0}),
    ("POST", "/messages", {"to": "pod:1", "body": "hi"}),
    ("POST", "/orders", {"pod_id": 1, "ticker": "AAPL", "side": "buy", "qty": 1}),
    ("POST", "/tasks/start", {"subject": "x"}),
    ("GET", "/events", None),
    ("GET", "/metrics/leaderboard", None),
    ("GET", "/metrics/pod/1", None),
    ("GET", "/portfolio/1", None),
    ("GET", "/messages", None),
    ("GET", "/agents", None),
    ("GET", "/price/AAPL", None),
])
def test_held_the_runtime_key_answers_no_participant_route(client, world, method, path, body):
    r = client.request(method, path, headers=H(world["rt"]), json=body)
    assert r.status_code == 403, (method, path, r.status_code, r.text)


# =====================================================================================
# HELD — key_ref coercion and anchors
# =====================================================================================

@pytest.mark.parametrize("key_ref", [
    "k1\n", "k1\r\n", "\nk1", "k1\x00", "k1 ", " k1", "k​1", "ｋ1", "kı",
    "١", "K1", "k1\t", "k1/..", "k1;drop", "a" * 64 + "\n",
])
def test_held_key_ref_anchors_are_strict(client, SessionFactory, world, key_ref):
    r = meter(client, world["rt"], world["a"], key_ref, 1)
    assert r.status_code == 422, (repr(key_ref), r.text)
    assert metered_events(SessionFactory) == []


@pytest.mark.parametrize("field,value", [
    ("usd_micros_total", 1e12), ("usd_micros_total", "1000"), ("usd_micros_total", False),
    ("usd_micros_total", [1]), ("usd_micros_total", {"$numberLong": "1"}),
    ("usd_micros_total", 10**400), ("agent_id", False), ("agent_id", 1e0), ("key_ref", 1),
    ("key_ref", ["k1"]), ("key_ref", None),
])
def test_held_coercions_are_refused(client, SessionFactory, world, field, value):
    body = {"agent_id": world["a"], "key_ref": "k1", "usd_micros_total": 1, field: value}
    r = client.post("/metering/usage", headers=H(world["rt"]), json=body)
    assert r.status_code == 422, (field, value, r.text)
    assert metered_events(SessionFactory) == []


# =====================================================================================
# HELD — cumulative law, retries and races
# =====================================================================================

def test_held_concurrent_identical_posts_write_one_event(client, SessionFactory, world):
    def post(_):
        return meter(client, world["rt"], world["a"], "k-race", 3_000_000)

    with ThreadPoolExecutor(max_workers=12) as pool:
        answers = list(pool.map(post, range(24)))
    assert all(r.status_code == 200 for r in answers), [r.text for r in answers]
    assert sum(r.json()["recorded"] for r in answers) == 1
    assert len(metered_events(SessionFactory)) == 1
    with SessionFactory() as s:
        assert metered_by_agent(s)[world["a"]].usd_micros == 3_000_000


def test_held_concurrent_posts_for_rival_agents_bind_the_key_once(client, SessionFactory, world):
    targets = [world["a"], world["b"], world["c"]] * 8

    def post(agent):
        return meter(client, world["rt"], agent, "k-contested", 1_000_000)

    with ThreadPoolExecutor(max_workers=12) as pool:
        answers = list(pool.map(post, targets))
    ok = [r for r in answers if r.status_code == 200 and r.json()["recorded"]]
    assert len(ok) == 1
    assert {r.status_code for r in answers} <= {200, 409}
    rows = metered_events(SessionFactory)
    assert len(rows) == 1
    with SessionFactory() as s:
        got = metered_by_agent(s)
    assert sum(m.usd_micros for m in got.values()) == 1_000_000


def test_held_concurrent_rising_totals_never_count_more_than_the_max(client, SessionFactory, world):
    totals = list(range(1, 41))

    def post(t):
        return meter(client, world["rt"], world["a"], "k-rise", t)

    with ThreadPoolExecutor(max_workers=12) as pool:
        answers = list(pool.map(post, totals))
    assert {r.status_code for r in answers} <= {200, 409}
    stored = [e.payload_json["usd_micros_total"] for e in metered_events(SessionFactory)]
    assert stored == sorted(stored) and len(set(stored)) == len(stored)   # strictly rising
    with SessionFactory() as s:
        assert metered_by_agent(s)[world["a"]].usd_micros == max(stored) == 40


def test_held_halt_blocks_metering_and_a_later_sync_catches_up(client, SessionFactory, world,
                                                              halt_file):
    meter(client, world["rt"], world["a"], "k-h", 100)
    halt_file.write_text("stop")
    assert meter(client, world["rt"], world["a"], "k-h", 500).status_code == 423
    assert meter(client, world["rt"], world["b"], "k-h2", 500).status_code == 423
    assert len(metered_events(SessionFactory)) == 1
    halt_file.unlink()
    assert meter(client, world["rt"], world["a"], "k-h", 500).status_code == 200
    with SessionFactory() as s:
        assert metered_by_agent(s)[world["a"]].usd_micros == 500


# =====================================================================================
# HELD — self-report masking and the per-agent split
# =====================================================================================

def test_held_a_metered_agent_cannot_move_its_pod_total_by_self_reporting(client, world):
    meter(client, world["rt"], world["a"], "k1", 5_000_000)
    selfreport(client, world["b_key"], 2.0)                # unmetered podmate: counts
    before = cost_of(client, world["admin"], world["pod1"])["total_usd_cost"]
    for usd in (0.0, 1_000_000.0, 1_000_000.0, 0.01, 123.456789):
        selfreport(client, world["a_key"], usd)
    after = cost_of(client, world["admin"], world["pod1"])
    assert before == after["total_usd_cost"] == 7.0
    assert after["self_reported_usd_cost"] == pytest.approx(2_000_125.47)


def test_held_metering_one_agent_leaves_a_rival_pods_self_reports(client, world):
    selfreport(client, world["c_key"], 30.0)
    meter(client, world["rt"], world["a"], "k1", 1_000_000)
    p2 = cost_of(client, world["admin"], world["pod2"])
    assert (p2["total_usd_cost"], p2["metered_usd_cost"], p2["metered_agents"]) == (30.0, None, 0)


def test_held_the_leaderboard_ranks_on_metered_cost_not_the_self_report(client, world):
    selfreport(client, world["a_key"], 0.0)                # A claims free
    selfreport(client, world["c_key"], 50.0)               # C honest
    meter(client, world["rt"], world["a"], "k1", 90_000_000)
    rows = client.get("/metrics/leaderboard", headers=H(world["admin"])).json()["rows"]
    order = [r["pod_id"] for r in rows]
    assert order == [world["pod2"], world["pod1"]]
    by_pod = {r["pod_id"]: r for r in rows}
    assert by_pod[world["pod1"]]["total_usd_cost"] == 90.0


# =====================================================================================
# HELD — the reader against forged rows
# =====================================================================================

@pytest.mark.parametrize("payload", [
    {"agent_id": True, "pod_id": 1, "key_ref": "f", "usd_micros_total": 10**6},
    {"agent_id": 2, "pod_id": True, "key_ref": "f", "usd_micros_total": 10**6},
    {"agent_id": 2, "pod_id": "1", "key_ref": "f", "usd_micros_total": 10**6},
    {"agent_id": 2, "pod_id": 1.0, "key_ref": "f", "usd_micros_total": 10**6},
    {"agent_id": 2.0, "pod_id": 1, "key_ref": "f", "usd_micros_total": 10**6},
    {"agent_id": 2, "pod_id": 1, "key_ref": 5, "usd_micros_total": 10**6},
    {"agent_id": 2, "pod_id": 1, "key_ref": "f", "usd_micros_total": MAX_METERED_USD_MICROS + 1},
    {"agent_id": 2, "pod_id": 1, "key_ref": "f", "usd_micros_total": -1},
    {"agent_id": 2, "pod_id": 1, "key_ref": "f", "usd_micros_total": 1e6},
    {"agent_id": 2, "pod_id": 1, "key_ref": "f", "usd_micros_total": True},
    {"agent_id": 2, "pod_id": 1, "key_ref": "f"},
    {"pod_id": 1, "key_ref": "f", "usd_micros_total": 10**6},
    {},
])
def test_held_malformed_forged_rows_are_ignored(client, SessionFactory, world, payload):
    forge(SessionFactory, payload)
    with SessionFactory() as s:
        got = metered_by_agent(s)
    assert dict(got) == {} and got.malformed == 1
    board = client.get("/metrics/leaderboard", headers=H(world["admin"]))
    assert board.status_code == 200
    # The writer reads the same: the runtime can still bind "f" to anyone, from zero.
    assert meter(client, world["rt"], world["c"], "f", 1).status_code == 200


def test_held_many_keys_at_the_cap_stay_exact_and_finite(client, SessionFactory, world):
    """Ledger portability: 10_000 keys x 10**12 = 10**16 micro-dollars, beyond 2**53."""
    with SessionFactory() as s:
        for i in range(10_000):
            append_event(s, type=EVENT_COST_METERED, actor_agent_id=None, payload={
                "agent_id": world["a"], "pod_id": world["pod1"], "key_ref": f"m{i}",
                "usd_micros_total": MAX_METERED_USD_MICROS})
        s.commit()
        got = metered_by_agent(s)
    assert got[world["a"]].usd_micros == 10**16          # Python ints: exact
    cost = cost_of(client, world["admin"], world["pod1"])
    assert cost["total_usd_cost"] == 1e10
    r = client.get("/metrics/leaderboard", headers=H(world["admin"]))
    assert r.status_code == 200 and "NaN" not in r.text and "Infinity" not in r.text


# =====================================================================================
# HELD — key_ref never reaches an agent
# =====================================================================================

def test_held_key_ref_reaches_no_agent_read(client, world):
    meter(client, world["rt"], world["a"], "zz-secret-label", 5_000_000)
    meter(client, world["rt"], world["a"], "zz-secret-label", 6_000_000)
    meter(client, world["rt"], world["c"], "zz-secret-label", 7_000_000)   # 409 detail
    reads = [
        ("admin", "/events"), ("admin", f"/events?type={EVENT_COST_METERED}"),
        ("admin", "/events?type=permission_denied"), ("admin", "/metrics/leaderboard"),
        ("admin", f"/metrics/pod/{world['pod1']}"), ("a_key", f"/metrics/pod/{world['pod1']}"),
        ("a_key", "/messages"), ("admin", "/agents"), ("a_key", "/me"),
    ]
    for who, path in reads:
        r = client.get(path, headers=H(world[who]))
        assert "zz-secret-label" not in r.text, (who, path)


@pytest.mark.anyio
async def test_held_the_mcp_tool_bounds_match_the_api_schema():
    from mcp_server.client import FundClient
    from mcp_server.tools import build_server

    server = build_server(FundClient(base_url="http://unused", api_key="unused"))
    [tool] = [t for t in await server.list_tools() if t.name == "report_metered_usage"]
    props = tool.input_schema["properties"]
    from app.api.schemas import MeteredUsageIn
    api = MeteredUsageIn.model_json_schema()["properties"]
    for name in ("agent_id", "usd_micros_total"):
        assert (props[name].get("minimum"), props[name].get("maximum")) == (
            api[name].get("minimum"), api[name].get("maximum")), name
    assert props["key_ref"]["pattern"] == api["key_ref"]["pattern"]
