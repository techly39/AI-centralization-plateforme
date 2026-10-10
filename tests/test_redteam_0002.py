"""RED-TEAM 0002 — attacks on the cycle-0002 token-cap fix (B-000c).

Surface: ``POST /costs`` now refuses tokens_in/tokens_out above
``MAX_TOKENS_PER_REPORT`` and ``_cost_metrics`` sums tokens with SQLite TOTAL.
Each attack uses only what a firm agent holds: an API key, REST, MCP tools.

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.

usd_cost inf/NaN/1e308 holes are tracked in test_redteam_0001.py (B-000d) and
deliberately not repeated here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Cost
from app.metrics.reporting import MAX_TOKENS_PER_REPORT
from tests.test_redteam_0001 import H, mcp_as, two_desks  # noqa: F401  (fixtures)


def _cost(client, key, tokens_in, tokens_out=0):
    return client.post("/costs", headers=H(key),
                       json={"tokens_in": tokens_in, "tokens_out": tokens_out, "usd_cost": 0.0})


# =============================================================================
# HELD — the cap itself
# =============================================================================

@pytest.mark.parametrize("field", ["tokens_in", "tokens_out"])
def test_held_cap_boundary_is_exact(client, two_desks, field):
    """Exactly the cap is accepted; one over is refused, in both directions."""
    _, key = two_desks["an1"]
    ok = {"tokens_in": 0, "tokens_out": 0, "usd_cost": 0.0, field: MAX_TOKENS_PER_REPORT}
    over = {**ok, field: MAX_TOKENS_PER_REPORT + 1}
    assert client.post("/costs", headers=H(key), json=ok).status_code == 201
    assert client.post("/costs", headers=H(key), json=over).status_code == 422


@pytest.mark.parametrize("value", [
    1e8 + 1.0,             # integral float just above the cap
    1e8 + 0.5,             # fractional float near the cap
    "1e8",                 # scientific string
    "0x7fffffffffffffff",  # hex string
    "100000001",           # numeric string above the cap
    -0.0 - 1,              # negative float
])
def test_held_coercion_cannot_slip_past_cap(client, two_desks, admin_key, value):
    """Lax pydantic coercion (float/str -> int) is checked against the cap
    *after* coercion, so no encoding of a big number gets in."""
    _, key = two_desks["an1"]
    assert _cost(client, key, value).status_code == 422
    assert client.get("/metrics/pod/1", headers=H(admin_key)).json()["cost"]["reports"] == 0


def test_held_coerced_values_stay_bounded(client, two_desks, admin_key):
    """Accepted coercions (bool, numeric strings, integral floats, '1_000') all
    land as ints <= cap; the pod's totals are exact and the leaderboard is up.
    Note (not a hole): ``true`` is accepted as 1 token — lax typing, but no
    advantage over just sending 1."""
    _, key = two_desks["an1"]
    accepted = [True, "100000000", 1e8, " 5 ", "1_000"]
    for v in accepted:
        assert _cost(client, key, v).status_code == 201, v
    resp = client.get("/metrics/pod/1", headers=H(admin_key))
    assert resp.status_code == 200
    assert resp.json()["cost"]["tokens_in"] == 1 + 100_000_000 + 100_000_000 + 5 + 1000
    assert client.get("/metrics/leaderboard", headers=H(admin_key)).status_code == 200


def test_held_many_max_reports_sum_exactly(client, two_desks, admin_key):
    """Volume attack: many reports at the cap. TOTAL is a float, but stays exact
    far below 2**53 (~9e7 max-cap reports needed to lose a token)."""
    _, key = two_desks["an1"]
    n = 60
    for _ in range(n):
        assert _cost(client, key, MAX_TOKENS_PER_REPORT, MAX_TOKENS_PER_REPORT).status_code == 201
    cost = client.get("/metrics/pod/1", headers=H(admin_key)).json()["cost"]
    assert cost["tokens_in"] == n * MAX_TOKENS_PER_REPORT
    assert cost["tokens_out"] == n * MAX_TOKENS_PER_REPORT
    assert isinstance(cost["tokens_in"], int)
    assert client.get("/metrics/leaderboard", headers=H(admin_key)).status_code == 200


@pytest.mark.anyio
async def test_held_mcp_tool_cannot_bypass_cap(two_desks, mcp_as, SessionFactory):
    """The MCP tool's own schema has ge=0 but no upper bound; it forwards to
    POST /costs, whose schema refuses. Nothing is stored."""
    _, key = two_desks["an1"]
    server, transport = mcp_as(key)
    for v in (MAX_TOKENS_PER_REPORT + 1, 2**63, 2**64):
        try:
            res = await server.call_tool("report_cost",
                                         {"tokens_in": 0, "tokens_out": v, "usd_cost": 0.0})
            assert getattr(res, "is_error", False)
        except Exception as exc:
            assert "422" in str(exc) or "validation" in str(exc).lower()
    assert all(p == "/costs" for p in transport.paths)
    session = SessionFactory()
    try:
        assert session.scalar(select(func.count(Cost.id))) == 0
    finally:
        session.close()


def test_held_podless_reporter_does_not_break_leaderboard(client, two_desks, admin_key):
    """Management (pod_id NULL) reports cost; the NULL-pod row must not crash or
    leak into any pod's totals."""
    assert _cost(client, admin_key, MAX_TOKENS_PER_REPORT, MAX_TOKENS_PER_REPORT).status_code == 201
    rows = client.get("/metrics/leaderboard", headers=H(admin_key)).json()["rows"]
    assert {r["pod_id"] for r in rows} == {1, 2}
    for pod in (1, 2):
        assert client.get(f"/metrics/pod/{pod}", headers=H(admin_key)).json()["cost"]["reports"] == 0


# =============================================================================
# HOLE — /metrics/pod/{id} path param overflow
# =============================================================================

@pytest.mark.xfail(strict=True, reason="red-team 0002: GET /metrics/pod/{2**63} raises "
                   "OverflowError in session.get (500, not 404/422); pod_id path param unbounded")
def test_hole_metrics_pod_id_beyond_int64_500(client, two_desks, admin_key):
    """Management-only (READ_CROSS_POD runs first, so other roles get 403), and no
    data is corrupted — but an unhandled 500 on attacker-chosen input. The same
    unbounded-int path pattern likely exists on other ``/{id}`` routes."""
    c = TestClient(client.app, raise_server_exceptions=False)
    for pod_id in (2**63, 10**20):
        resp = c.get(f"/metrics/pod/{pod_id}", headers=H(admin_key))
        assert resp.status_code in (404, 422), (pod_id, resp.status_code)
