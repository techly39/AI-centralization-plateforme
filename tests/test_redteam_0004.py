"""RED-TEAM 0004 — attacks on the cycle-0012 finite-numbers fix (B-000d, ADR-024).

Claim under attack: no NaN / ±Infinity / overflowing number from an agent can
reach a table or the ledger; float request fields are capped (``app/limits.py``);
free JSON (``structured_payload``, task ``outcome``) is walked; the 422 handler
never 500s; ``append_event`` refuses non-finite payloads.

Every attack uses only what a firm agent holds: an API key, REST, MCP tools.

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.

Fixed in cycle 0012, before merge (ADR-024): the int64-id test (now bounded by
``MAX_ID``) and the five ``test_held_*`` tests under the three HOLE headings below
were holes — deep free JSON (stored, then every
read of it a 500), integers beyond ±2**53 in free JSON, and the recursive
walker's RecursionError. One iterative walker (``app.finite.json_problem``) now
refuses all three, in the schemas and in ``append_event``.
"""

from __future__ import annotations

import json
import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Cost, Event, Message, Order, Task
from app.limits import MAX_ORDER_QTY, MAX_PRICE, MAX_USD_PER_REPORT
from tests.test_redteam_0001 import H, mcp_as, two_desks  # noqa: F401  (fixtures)

#: pydantic-core's serializer gives up ("Circular reference detected (depth
#: exceeded)") a little below 256 levels; the request validator and the walker
#: both accept far deeper. 300 sits safely in the gap.
POISON_DEPTH = 300


def _raw(client, key, method, path, body: str):
    return client.request(method, path, content=body,
                          headers={**H(key), "Content-Type": "application/json"})


def _nest(depth: int, leaf: str = "1") -> str:
    return '{"a":' * depth + leaf + "}" * depth


def _counts(db) -> tuple[int, ...]:
    db.expire_all()
    return tuple(db.scalar(select(func.count()).select_from(t))
                 for t in (Event, Cost, Order, Message, Task))


def _soft(client) -> TestClient:
    """A client that turns server exceptions into the 500 a real agent sees."""
    return TestClient(client.app, raise_server_exceptions=False)


def _ledger_is_standard_json(db) -> None:
    db.expire_all()
    for ev in db.scalars(select(Event)):
        json.dumps(ev.payload_json, allow_nan=False)


async def _tool_refused(server, name: str, args: dict) -> bool:
    try:
        res = await server.call_tool(name, args)
    except Exception:  # ToolError / validation error from the tool schema
        return True
    return bool(getattr(res, "is_error", False))


# =============================================================================
# HOLE (high) — deep free JSON is stored, then poisons every read that renders it
# =============================================================================

@pytest.mark.parametrize("target", ["own_pod", "rival_pm", "management"])
def test_held_deep_structured_payload_poisons_recipient_inbox(client, two_desks, admin_key,
                                                              target):
    """An analyst can address its own pod, a rival pod's PM, or management
    (cross-pod chat is allowed). After one message, the victim's default inbox
    read is a 500 until someone pages around it with after_id/before_id. The
    sender's own POST also returns 500 even though the row was committed."""
    c = _soft(client)
    _, an1 = two_desks["an1"]
    me = c.get("/me", headers=H(admin_key)).json()["id"]
    to, victim = {"own_pod": ("pod:1", two_desks["pm1"][1]),
                  "rival_pm": (f"agent:{two_desks['pm2'][0]}", two_desks["pm2"][1]),
                  "management": (f"agent:{me}", admin_key)}[target]
    _raw(c, an1, "POST", "/messages",
         f'{{"to": "{to}", "body": "x", "structured_payload": {_nest(POISON_DEPTH)}}}')
    assert c.get("/messages", headers=H(victim)).status_code == 200


def test_held_deep_task_outcome_poisons_the_event_log(client, two_desks, admin_key, db):
    c = _soft(client)
    _, an1 = two_desks["an1"]
    tid = c.post("/tasks/start", headers=H(an1), json={"subject": "s"}).json()["id"]
    resp = _raw(c, an1, "POST", "/tasks/end",
                f'{{"task_id": {tid}, "outcome": {_nest(POISON_DEPTH)}}}')
    assert resp.status_code == 422, "accepted (or 500 after commit)"
    for q in ("/events", "/events?type=task_ended"):
        assert c.get(q, headers=H(admin_key)).status_code == 200


@pytest.mark.anyio
async def test_held_mcp_deep_payload_breaks_victims_get_messages(two_desks, mcp_as):
    deep: dict = {}
    cur = deep
    for _ in range(POISON_DEPTH):
        cur["a"] = {}
        cur = cur["a"]
    attacker, _ = mcp_as(two_desks["an1"][1])
    victim, _ = mcp_as(two_desks["pm1"][1])
    await _tool_refused(attacker, "send_message",
                        {"to": "pod:1", "body": "x", "structured_payload": deep})
    assert not await _tool_refused(victim, "get_messages", {})


# =============================================================================
# HOLE (medium) — overflowing integers in free JSON reach the ledger
# =============================================================================

def test_held_huge_int_in_free_json_reaches_ledger(client, two_desks, db):
    _, an1 = two_desks["an1"]
    tid = client.post("/tasks/start", headers=H(an1), json={"subject": "s"}).json()["id"]
    resp = _raw(client, an1, "POST", "/tasks/end",
                f'{{"task_id": {tid}, "outcome": {{"conviction": 1{"0" * 400}}}}}')
    db.expire_all()
    ended = db.scalars(select(Event).where(Event.type == "task_ended")).all()
    assert resp.status_code == 422 and not ended
    # What the ledger would hold, as any float64 consumer reads it:
    # float(10**400) -> OverflowError; JSON.parse -> Infinity.


# =============================================================================
# HOLE (low) — 500s on agent input that write nothing
# =============================================================================

def test_held_walker_recursion_is_a_500(client, two_desks, db):
    c = _soft(client)
    _, an1 = two_desks["an1"]
    before = _counts(db)
    resp = _raw(c, an1, "POST", "/messages",
                f'{{"to": "pod:1", "body": "x", "structured_payload": {_nest(1000)}}}')
    assert _counts(db) == before
    assert resp.status_code in (400, 413, 422), resp.status_code


@pytest.mark.parametrize("attack", ["task_id_body", "cancel_order_path", "after_id_query"])
def test_held_int64_overflow_ids_from_non_management(client, two_desks, attack):
    """Was a hole; fixed in cycle 0012 before merge by ``MAX_ID`` on every id."""
    c = _soft(client)
    an1, pm1 = two_desks["an1"][1], two_desks["pm1"][1]
    big = 2**63
    resp = {
        "task_id_body": lambda: _raw(c, an1, "POST", "/tasks/end",
                                     f'{{"task_id": {big}, "outcome": {{}}}}'),
        "cancel_order_path": lambda: c.delete(f"/orders/{big}", headers=H(pm1)),
        "after_id_query": lambda: c.get(f"/messages?after_id={big}", headers=H(an1)),
    }[attack]()
    assert resp.status_code in (404, 422), resp.status_code


@pytest.mark.xfail(strict=True, reason="red-team 0004 LOW: fee is rounded to cents per order, so "
                   "any order with notional < $5 at 0.1% pays $0.00; splitting trades evades fees "
                   "(and 1e-300-share orders are accepted and fill)")
def test_hole_small_orders_pay_no_fee(client, two_desks):
    _, pm1 = two_desks["pm1"]
    resp = client.post("/orders", headers=H(pm1), json={
        "ticker": "AAPL", "side": "buy", "qty": 0.024, "price_type": "market",
        "justification": "split"})
    assert resp.status_code == 201 and resp.json()["status"] == "filled"
    assert resp.json()["fee"] > 0, "traded $4.80 of AAPL for free"


@pytest.mark.xfail(strict=True, reason="red-team 0004 LOW (feed, not agent): a NaN/inf price "
                   "from the provider passes assert_affordable (NaN > cash is False) and then "
                   "append_event raises ValueError -> 500 on POST /orders; should be a clean "
                   "price_unavailable rejection. /price also serves price: null")
@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_hole_non_finite_feed_price_is_a_500(client, two_desks, prices, db, bad):
    c = _soft(client)
    _, pm1 = two_desks["pm1"]
    prices.set_price("MSFT", bad)
    resp = c.post("/orders", headers=H(pm1), json={
        "ticker": "MSFT", "side": "buy", "qty": 1, "price_type": "market", "justification": "t"})
    assert resp.status_code != 500
    _ledger_is_standard_json(db)


# =============================================================================
# HELD — float fields
# =============================================================================

@pytest.mark.parametrize("token", ['"inf"', '"Infinity"', '"-inf"', '"nan"', '"NaN"', '"1e309"'])
@pytest.mark.parametrize("field", ["qty", "limit_price", "usd_cost"])
def test_held_non_finite_strings_refused(client, two_desks, db, token, field):
    """Pydantic lax mode parses numeric strings; allow_inf_nan=False still bites."""
    _, an1 = two_desks["an1"]
    _, pm1 = two_desks["pm1"]
    before = _counts(db)
    if field == "usd_cost":
        resp = _raw(client, an1, "POST", "/costs",
                    f'{{"tokens_in": 1, "tokens_out": 1, "usd_cost": {token}}}')
    else:
        vals = {"qty": "1", "limit_price": "100", field: token}
        resp = _raw(client, pm1, "POST", "/orders",
                    '{"ticker": "AAPL", "side": "buy", "price_type": "limit", "justification": "t",'
                    f' "qty": {vals["qty"]}, "limit_price": {vals["limit_price"]}}}')
    assert resp.status_code == 422
    json.loads(resp.text)
    assert _counts(db) == before


@pytest.mark.parametrize("value", [f"1{'0' * 400}", str(2**1024), "1e400", "-1e400"])
@pytest.mark.parametrize("field", ["qty", "usd_cost", "tokens_in"])
def test_held_overflowing_numbers_for_numeric_fields(client, two_desks, db, value, field):
    """int -> float conversion overflow and float literals past 1e308 are 422s."""
    _, an1 = two_desks["an1"]
    _, pm1 = two_desks["pm1"]
    before = _counts(db)
    if field == "qty":
        resp = _raw(client, pm1, "POST", "/orders",
                    '{"ticker": "AAPL", "side": "buy", "price_type": "market",'
                    f' "justification": "t", "qty": {value}}}')
    else:
        body = {"tokens_in": "1", "tokens_out": "1", "usd_cost": "1"}
        body[field] = value
        resp = _raw(client, an1, "POST", "/costs",
                    "{" + ", ".join(f'"{k}": {v}' for k, v in body.items()) + "}")
    assert resp.status_code == 422, resp.text
    json.loads(resp.text)
    assert _counts(db) == before


def test_held_int_beyond_python_digit_limit_is_a_clean_400(client, two_desks, db):
    """>4300-digit ints trip Python's int parsing limit inside json.loads; Starlette
    turns that into 400, not 500, and nothing is written."""
    c = _soft(client)
    _, an1 = two_desks["an1"]
    before = _counts(db)
    resp = _raw(c, an1, "POST", "/messages",
                f'{{"to": "pod:1", "body": "x", "structured_payload": {{"x": 1{"0" * 5000}}}}}')
    assert resp.status_code == 400
    assert _counts(db) == before


def test_held_duplicate_keys_cannot_smuggle_nan(client, two_desks, db):
    """json.loads keeps the last duplicate; the walker sees what is stored."""
    _, an1 = two_desks["an1"]
    ok = _raw(client, an1, "POST", "/messages",
              '{"to": "pod:1", "body": "x", "structured_payload": {"x": NaN, "x": 1}}')
    assert ok.status_code == 201 and ok.json()["structured_payload"] == {"x": 1}
    bad = _raw(client, an1, "POST", "/messages",
               '{"to": "pod:1", "body": "x", "structured_payload": {"x": 1, "x": NaN}}')
    assert bad.status_code == 422
    order = _raw(client, two_desks["pm1"][1], "POST", "/orders",
                 '{"ticker": "AAPL", "side": "buy", "price_type": "market", "justification": "t",'
                 ' "qty": 1, "qty": Infinity}')
    assert order.status_code == 422
    _ledger_is_standard_json(db)


# =============================================================================
# HELD — the 422 handler with deep / hostile echoes
# =============================================================================

@pytest.mark.parametrize("depth", [300, 600, 800])
def test_held_deep_rejected_input_still_renders_a_422(client, two_desks, db, depth):
    """A deep NaN-bottomed dict (walker error) and a deep list (dict_type error,
    the whole input echoed) both come back as standard-JSON 422s."""
    c = _soft(client)
    _, an1 = two_desks["an1"]
    before = _counts(db)
    for payload in (_nest(depth, "NaN"), "[" * depth + "]" * depth):
        resp = _raw(c, an1, "POST", "/messages",
                    f'{{"to": "pod:1", "body": "x", "structured_payload": {payload}}}')
        assert resp.status_code == 422, resp.status_code
        json.loads(resp.text)
    assert _counts(db) == before


# =============================================================================
# HELD — money arithmetic at the caps
# =============================================================================

def test_held_orders_at_caps_are_rejected_for_cash_and_stay_finite(client, two_desks, db):
    """qty=MAX_ORDER_QTY at MAX_PRICE gives a 1e16 notional: finite, and simply
    unaffordable. Nothing non-finite reaches orders or the ledger."""
    _, pm1 = two_desks["pm1"]
    for body in (
        {"price_type": "market"},
        {"price_type": "limit", "limit_price": MAX_PRICE},
    ):
        resp = client.post("/orders", headers=H(pm1), json={
            "ticker": "AAPL", "side": "buy", "qty": MAX_ORDER_QTY, "justification": "t", **body})
        assert resp.status_code in (201, 422), resp.text
        if resp.status_code == 201:
            assert resp.json()["status"] in ("rejected", "pending")
    sell = client.post("/orders", headers=H(pm1), json={
        "ticker": "AAPL", "side": "sell", "qty": MAX_ORDER_QTY, "price_type": "limit",
        "limit_price": MAX_PRICE, "justification": "t"})
    assert sell.status_code in (201, 422) and sell.json().get("status") != "filled"
    portfolio = client.get("/portfolio/1", headers=H(pm1)).json()
    assert portfolio["cash"] == 100_000.0
    _ledger_is_standard_json(db)


def test_held_subnormal_qty_stays_finite_everywhere(client, two_desks, admin_key, db):
    _, pm1 = two_desks["pm1"]
    for qty in (5e-324, 1e-300):
        resp = client.post("/orders", headers=H(pm1), json={
            "ticker": "AAPL", "side": "buy", "qty": qty, "price_type": "market",
            "justification": "t"})
        assert resp.status_code == 201
    assert client.get("/portfolio/1", headers=H(pm1)).status_code == 200
    lb = client.get("/metrics/leaderboard", headers=H(admin_key))
    assert lb.status_code == 200
    json.loads(lb.text)
    _ledger_is_standard_json(db)


def test_held_many_max_usd_reports_sum_finitely(client, two_desks, admin_key):
    _, an1 = two_desks["an1"]
    n = 50
    for _ in range(n):
        assert client.post("/costs", headers=H(an1), json={
            "tokens_in": 0, "tokens_out": 0, "usd_cost": MAX_USD_PER_REPORT}).status_code == 201
    cost = client.get("/metrics/pod/1", headers=H(admin_key)).json()["cost"]
    assert cost["total_usd_cost"] == n * MAX_USD_PER_REPORT
    rows = client.get("/metrics/leaderboard", headers=H(admin_key)).json()["rows"]
    row = next(r for r in rows if r["pod_id"] == 1)
    assert row["cost_adjusted_pnl"] is not None and math.isfinite(row["cost_adjusted_pnl"])


# =============================================================================
# HELD — MCP path
# =============================================================================

@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "args"), [
    ("place_order", {"ticker": "AAPL", "side": "buy", "qty": math.inf, "price_type": "market",
                     "justification": "t"}),
    ("place_order", {"ticker": "AAPL", "side": "buy", "qty": math.nan, "price_type": "market",
                     "justification": "t"}),
    ("place_order", {"ticker": "AAPL", "side": "buy", "qty": 1.0, "price_type": "limit",
                     "limit_price": math.inf, "justification": "t"}),
    ("report_cost", {"tokens_in": 0, "tokens_out": 0, "usd_cost": math.nan}),
    ("report_cost", {"tokens_in": 0, "tokens_out": 0, "usd_cost": 1e308}),
    ("send_message", {"to": "pod:1", "body": "x", "structured_payload": {"x": math.inf}}),
    ("send_message", {"to": "pod:1", "body": "x", "structured_payload": {"x": [math.nan]}}),
])
async def test_held_mcp_cannot_send_non_finite(two_desks, mcp_as, SessionFactory, tool, args):
    key = two_desks["pm1"][1] if tool == "place_order" else two_desks["an1"][1]
    server, _ = mcp_as(key)
    assert await _tool_refused(server, tool, args)
    session = SessionFactory()
    try:
        for model in (Order, Cost, Message):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        for ev in session.scalars(select(Event)):
            json.dumps(ev.payload_json, allow_nan=False)
    finally:
        session.close()
