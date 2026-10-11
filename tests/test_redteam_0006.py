"""RED-TEAM 0006 — attacks on the cycle-0014 universal clock read (B-020, ADR-026).

Claim under attack: ``GET /clock`` is now readable by every authenticated agent
through a new universal ``Action.READ_CLOCK``; it returns ``{mode, now}`` and
nothing else; it writes nothing; clock *control* does not exist on the surface,
and when B-004 builds it, it stays system/management-only.

Every attack uses only what a firm agent holds: an API key, REST, MCP tools —
plus, where marked, a *world event* (the clock stepping back) that the agent
cannot cause but can be standing next to.

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from app.db.models import AgentRole, Event
from app.ledger.events import EVENT_PERMISSION_DENIED
from app.registry import permissions
from app.registry.permissions import Action, has_permission
from tests.test_redteam_0001 import H, two_desks  # noqa: F401  (fixtures)

T0 = datetime(2019, 3, 4, 14, 30, tzinfo=timezone.utc)
FUTURE = "2099-01-01T00:00:00Z"


def _events(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count(Event.id)))


def _denials(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count(Event.id)).where(Event.type == EVENT_PERMISSION_DENIED))


def _api_routes(app) -> list[APIRoute]:
    """Every APIRoute, including those behind FastAPI's included-router wrappers.

    None of the app's routers uses a prefix, so the inner path is the served path;
    the openapi check below pins that assumption.
    """
    out: list[APIRoute] = []
    stack = list(app.routes)
    while stack:
        r = stack.pop()
        if isinstance(r, APIRoute):
            out.append(r)
        elif hasattr(r, "original_router"):
            stack.extend(r.original_router.routes)
    served = {p for p in app.openapi()["paths"]}
    assert {r.path for r in out if r.include_in_schema} == served
    return out


def _required_actions(route: APIRoute) -> set[Action]:
    """Every Action a route's dependency tree passes to ``require(...)``."""
    found: set[Action] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        for cell in getattr(dep.call, "__closure__", None) or ():
            if isinstance(cell.cell_contents, Action):
                found.add(cell.cell_contents)
        stack.extend(dep.dependencies)
    return found


# =============================================================================
# HELD — the read reaches nothing but {mode, now}
# =============================================================================

@pytest.mark.parametrize("path", [
    "/clock?mode=backtest", "/clock?now=" + FUTURE, "/clock?advance=10000",
    "/clock?days=1&as_of=" + FUTURE, "/clock?pod_id=2", "/clock?role=system",
])
def test_held_query_strings_on_the_clock_read_change_nothing(
    frozen_clock, client, two_desks, db, path
):
    frozen_clock.set(T0)
    before = _events(db)
    for who in ("pm1", "an1"):
        resp = client.get(path, headers=H(two_desks[who][1]))
        assert resp.status_code == 200, (path, resp.status_code)
        assert resp.json() == {"mode": "frozen", "now": T0.isoformat().replace("+00:00", "Z")}
    # The clock did not move and nothing was written.
    assert client.get("/clock", headers=H(two_desks["an1"][1])).json()["now"].startswith("2019-03-04")
    assert _events(db) == before


@pytest.mark.parametrize("method,path", [
    ("GET", "/clock/advance"), ("GET", "/clock/mode"), ("GET", "/clock/now"),
    ("GET", "/clock/%2e%2e/events"), ("GET", "/CLOCK"),
    ("GET", "/clock;mode=backtest"), ("GET", "/clock%00"), ("GET", "/clock/x/y"),
    ("HEAD", "/clock/advance"), ("OPTIONS", "/clock"), ("DELETE", "/clock"),
    ("POST", "/clock/"), ("PUT", "/clock/advance"),
])
def test_held_route_tricks_reach_nothing_else(client, two_desks, db, method, path):
    """Trailing paths, traversal, case, params, odd verbs: none lands on a handler
    other than the read, and none returns ledger/metrics content."""
    before = _events(db)
    for who in ("pm1", "an1"):
        resp = client.request(method, path, headers=H(two_desks[who][1]),
                              json={"now": FUTURE, "mode": "backtest"},
                              follow_redirects=False)
        if resp.status_code == 200:
            # Only the clock read itself may answer 200 (e.g. a normalised path).
            assert set(resp.json()) == {"mode", "now"}, (method, path, resp.text)
        else:
            assert resp.status_code in (307, 404, 405), (method, path, resp.status_code)
            if resp.status_code == 307:
                # A slash redirect may only point back at the read.
                assert resp.headers["location"].rstrip("/").endswith("/clock")
    # Unmatched routes never reach auth, so they cannot spam the ledger either.
    assert _events(db) == before


def test_held_trailing_slash_redirect_lands_on_the_read_only(client, two_desks):
    resp = client.get("/clock/", headers=H(two_desks["an1"][1]))
    assert resp.status_code == 200
    assert set(resp.json()) == {"mode", "now"}


def test_held_head_on_clock_is_not_a_write_and_writes_nothing(client, two_desks, db, halt_file):
    halt_file.write_text("stop\n")
    before = _events(db)
    resp = client.head("/clock", headers=H(two_desks["an1"][1]))
    assert resp.status_code in (200, 405)
    assert _events(db) == before


def test_held_unauthenticated_and_forged_keys_get_401_not_time(client, two_desks, db):
    pm_key = two_desks["pm1"][1]
    before = _events(db)
    for key in ("", " ", pm_key + "x", pm_key.upper(), pm_key[:-1], "system", "management"):
        resp = client.get("/clock", headers={"X-API-Key": key})
        assert resp.status_code == 401, key
        assert "now" not in resp.text
    # Key in the query string or a bearer header is not a key.
    assert client.get(f"/clock?api_key={pm_key}").status_code == 401
    assert client.get("/clock", headers={"Authorization": f"Bearer {pm_key}"}).status_code == 401
    assert _events(db) == before


# =============================================================================
# HELD — READ_CLOCK grants nothing anywhere else
# =============================================================================

def test_held_read_clock_gates_exactly_one_route_and_it_is_a_get(client):
    """No other route (and no write) is admitted by READ_CLOCK."""
    routes = [r for r in _api_routes(client.app) if Action.READ_CLOCK in _required_actions(r)]
    assert [(r.path, sorted(r.methods)) for r in routes] == [("/clock", ["GET"])]


def test_held_no_write_route_is_gated_by_a_universal_action_it_should_not_be(client):
    """Future guard (B-004): a write under /clock must never sit behind READ_CLOCK,
    nor behind any universal action — control is a privilege."""
    for r in _api_routes(client.app):
        if not r.path.startswith("/clock"):
            continue
        if r.methods - {"GET", "HEAD", "OPTIONS"}:
            needed = _required_actions(r)
            assert needed, (r.path, "write route under /clock with no require()")
            assert not needed & permissions._UNIVERSAL, (r.path, needed)


@pytest.mark.parametrize("method,path", [
    ("POST", "/clock/advance"), ("POST", "/clock/mode"), ("POST", "/clock/reset"),
    ("PUT", "/clock"), ("PATCH", "/clock"), ("POST", "/clock"),
])
def test_held_non_management_cannot_control_the_clock_now_or_later(
    client, two_desks, method, path
):
    """Behavioural twin of the guard above: today 404/405; after B-004, 403."""
    for who in ("pm1", "an1"):
        resp = client.request(method, path, headers=H(two_desks[who][1]),
                              json={"now": FUTURE, "mode": "backtest", "days": 1})
        assert resp.status_code in (403, 404, 405), (method, path, resp.status_code)


def test_held_universal_set_adds_no_privilege_beyond_reads_and_self_reports():
    """READ_CLOCK did not drag in a privilege, and no role lost one."""
    assert permissions._UNIVERSAL == {
        Action.READ_MESSAGES, Action.REPORT_COST, Action.REPORT_TASK,
        Action.READ_HALT, Action.READ_CLOCK,
    }
    for role in (AgentRole.analyst, AgentRole.pm):
        for priv in (Action.READ_CROSS_POD, Action.SET_ALLOCATION,
                     Action.REGISTER_AGENTS, Action.DEACTIVATE_AGENTS):
            assert not has_permission(role, priv), (role, priv)
    assert not has_permission(AgentRole.analyst, Action.PLACE_ORDER)
    assert not has_permission(AgentRole.analyst, Action.BROADCAST)
    assert all(has_permission(AgentRole.system, a) for a in Action)


@pytest.mark.parametrize("path", ["/events", "/metrics/leaderboard", "/metrics/pod/2"])
def test_held_cross_pod_reads_stay_closed_after_the_clock_left_read_cross_pod(
    client, two_desks, path
):
    """/clock used to share READ_CROSS_POD; the split must not have widened it."""
    for who in ("pm1", "an1"):
        assert client.get(path, headers=H(two_desks[who][1])).status_code == 403


# =============================================================================
# HELD — deny-event spam and halt gate
# =============================================================================

def test_held_clock_reads_cannot_spam_the_ledger(client, two_desks, db, halt_file):
    """Before ADR-026 every analyst read logged a permission_denied event (a free
    ledger-write per request). Now: 200 reads, 0 events, halted or not."""
    an_key = two_desks["an1"][1]
    before, denials = _events(db), _denials(db)
    for _ in range(100):
        assert client.get("/clock", headers=H(an_key)).status_code == 200
    halt_file.write_text("stop\n")
    for _ in range(100):
        assert client.get("/clock", headers=H(an_key)).status_code == 200
    assert _events(db) == before
    assert _denials(db) == denials


# =============================================================================
# HELD — side channels: the read is the same for every pod
# =============================================================================

def test_held_clock_is_identical_for_every_pod_and_role(
    frozen_clock, client, two_desks, admin_key
):
    """No pod-specific field, no role-specific field: one world, one now."""
    frozen_clock.set(T0)
    bodies = {who: client.get("/clock", headers=H(two_desks[who][1])).json()
              for who in ("pm1", "an1", "pm2")}
    bodies["admin"] = client.get("/clock", headers=H(admin_key)).json()
    assert len({tuple(sorted(b.items())) for b in bodies.values()}) == 1


def test_held_other_pods_activity_does_not_move_the_clock_read(
    frozen_clock, client, two_desks
):
    """pm2 trading / messaging leaves pm1's clock read untouched (frozen world)."""
    frozen_clock.set(T0)
    first = client.get("/clock", headers=H(two_desks["pm1"][1])).json()
    for _ in range(5):
        client.post("/orders", headers=H(two_desks["pm2"][1]), json={
            "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
            "justification": "noise"})
    assert client.get("/clock", headers=H(two_desks["pm1"][1])).json() == first


# =============================================================================
# HOLE (low) — after a world clock step-back, GET /clock and the ledger disagree,
# and the disagreement leaks the ledger's high-water mark (any pod's activity).
#
# ADR-025 floors every event stamp at the latest ledger ts. GET /clock returns
# the raw clock. After the world clock steps back (a world event an agent can be
# standing next to — B-004's rewind, an NTP correction, a second backtest on the
# same DB), an agent that reads /clock and then acts sees its order stamped LATER
# than the now it was just told: ADR-026's evidence ("a PM's order is stamped
# with the now it read") no longer holds, and the gap tells it that some other
# pod wrote to the ledger at a time the agent's "now" has not reached yet — in a
# backtest, a date in the simulated future. Fix options: /clock reports
# max(clock, ledger floor); or B-004 forbids a clock step behind the floor.
# =============================================================================

@pytest.mark.xfail(strict=True, reason="HOLE rt-0006: /clock ignores the ledger floor (B-004)")
def test_hole_clock_read_agrees_with_ledger_stamp_after_step_back(
    frozen_clock, client, two_desks
):
    base = frozen_clock.now()          # fixtures already stamped the ledger here
    later = base + timedelta(days=30)
    frozen_clock.set(later)
    # Another pod acts in the "future".
    r = client.post("/orders", headers=H(two_desks["pm2"][1]), json={
        "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "pm2 at a later date"})
    assert r.status_code == 201, r.text
    # World event: the clock steps back.
    frozen_clock.set(base)
    pm1 = H(two_desks["pm1"][1])
    told = datetime.fromisoformat(client.get("/clock", headers=pm1).json()["now"])
    r = client.post("/orders", headers=pm1, json={
        "ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "what time is it really"})
    assert r.status_code == 201, r.text
    stamped = datetime.fromisoformat(r.json()["created_at"])
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    assert told == base
    # The hole: pm1's stamp is pm2's later date, so the gap between the now it was
    # told and the stamp it got reveals another pod's activity in pm1's "future".
    assert stamped == told, (told, stamped, later)
