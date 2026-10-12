"""Red-team pass 0017 — ``POST /run/minds`` and ``run_minds()`` (ADR-032 (p), cycle 28).

The attacker is a firm agent (management, pm, analyst) or an operator mistake.
The aim: make a run read ``scripted`` when something else drove it, make an honest
run read ``None`` or the wrong kinds, declare as a firm agent, get two
declarations read, or get a 500.

HOLES are strict ``xfail``s: each one passes once the Builder fixes the physics.
HELD guards are plain tests: attacks that failed and must keep failing.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.run_clock as rc
from app.db.models import Agent, AgentRole
from app.ledger.events import EVENT_RUN_MINDS_DECLARED, append_event
from app.registry.service import deactivate_agent, register_agent, rotate_runtime_key
from mcp_server import FundClient
from mcp_server.tools import build_server
from tests.test_run_minds import (  # noqa: F401 - fixtures
    H,
    _declarations,
    _minds,
    _runtime_id,
    client,
    on_run_clock,
)
from tests.test_runtime_lockstep import _app, world  # noqa: F401 - fixtures


def _declare(client, world, minds=("scripted",)):
    return client.post("/run/minds", headers=H(world["clock"]), json={"minds": list(minds)})


def _agent_id(SessionFactory, name: str) -> int:
    with SessionFactory() as s:
        return s.scalar(select(Agent.id).where(Agent.name == name))


# =====================================================================================
# HOLES
# =====================================================================================

# Fixed in cycle 28 (ADR-032 (p) red-team amendment): after its commit, declare_minds
# re-reads the ledger and answers 409 unless its event is the trusted one. The hole
# tests are now guards and keep their names.

# HOLE rt0017-1 (medium): a firm write in the check/append gap voids the declaration
# in the ledger, but the endpoint still answered 201.
def test_hole_a_declaration_that_lost_the_race_is_not_answered_201(
        SessionFactory, world, client, monkeypatch):
    """A pre-existing firm agent (the world's pm-1) posts a message — a write that
    takes no lock — while the declaration is between its check and its append."""
    real = rc._acted_before

    def gap(session, before_id):
        seen = real(session, before_id)
        if before_id is None:  # declare_minds' check has just passed
            assert client.post("/messages", headers=H(world["pm"][1]),
                               json={"to": "broadcast", "body": "in the gap"}).status_code == 201
        return seen

    monkeypatch.setattr(rc, "_acted_before", gap)
    resp = _declare(client, world)
    monkeypatch.undo()
    assert _minds(SessionFactory) is None  # the ledger says: not trusted
    # The hole: the conductor was told it declared.
    assert resp.status_code == 409, resp.text


# HOLE rt0017-2 (low): a second declaration that slipped past the once-check (a second
# process: OMS_LOCK is per process) was answered 201 with its own kinds. Fixed as rt0017-1.
def test_hole_a_second_declaration_that_slipped_in_is_not_answered_201(
        SessionFactory, world, client, monkeypatch):
    rid = _runtime_id(SessionFactory)
    real = rc._acted_before

    def other_process(session, before_id):
        if before_id is None:  # after the once-check passed: another process declares
            append_event(session, type=EVENT_RUN_MINDS_DECLARED, actor_agent_id=rid,
                         payload={"minds": ["scripted"]})
            session.commit()
        return real(session, before_id)

    monkeypatch.setattr(rc, "_acted_before", other_process)
    resp = _declare(client, world, ["model"])
    monkeypatch.undo()
    assert _minds(SessionFactory) == ("scripted",)
    assert len(_declarations(SessionFactory)) == 2
    # The hole: 201 {"minds": ["model"]} for a declaration that is never read.
    assert resp.status_code == 409, resp.text


# HOLE rt0017-3 (low): a lone surrogate (\ud800) in any string field made the 422
# handler raise UnicodeEncodeError, a 500. Fixed: app.finite.json_safe replaces it.
def test_hole_a_lone_surrogate_gets_a_422_not_a_500(SessionFactory, world):
    raw = b'{"minds": ["\\ud800"], "to": "broadcast", "body": "\\ud800"}'
    with TestClient(_app(SessionFactory), raise_server_exceptions=False) as c:
        for key, path in ((world["clock"], "/run/minds"), (world["pm"][1], "/messages")):
            resp = c.post(path, content=raw,
                          headers={**H(key), "content-type": "application/json"})
            assert resp.status_code == 422, (path, resp.status_code)
    assert _declarations(SessionFactory) == []


# HOLE rt0017-4 (medium): the declaration names kinds, not agents; an agent older than
# it acted under its label. Fixed: run_minds covers only agents registered after the
# declaration (an older agent may only register).
def test_hole_an_agent_older_than_the_declaration_does_not_act_under_its_label(
        SessionFactory, world, client):
    assert _declare(client, world).status_code == 201
    # The conductor's own minds come after the declaration, made by the registrar:
    made = client.post("/agents/register", headers=H(world["admin"]),
                       json={"name": "pm-made", "role": "analyst", "pod_id": 1})
    assert made.status_code == 201, made.text
    # ...but pm-1, seeded before the run, is driven by something no one declared:
    assert client.post("/messages", headers=H(world["pm"][1]),
                       json={"to": "broadcast", "body": "a model wrote this"}).status_code == 201
    assert _minds(SessionFactory) != ("scripted",)


# =====================================================================================
# HELD
# =====================================================================================

@pytest.mark.parametrize("who", ["admin", "pm"])
def test_held_firm_agents_cannot_declare_over_http(SessionFactory, world, client, who):
    key = world["admin"] if who == "admin" else world["pm"][2]
    for minds in (["scripted"], ["model"], ["cassette", "scripted"]):
        assert client.post("/run/minds", headers=H(key), json={"minds": minds}).status_code == 403
    assert _declarations(SessionFactory) == [] and _minds(SessionFactory) is None


def test_held_an_analyst_cannot_declare(SessionFactory, world, client):
    resp = client.post("/agents/register", headers=H(world["admin"]),
                       json={"name": "an-1", "role": "analyst", "pod_id": 1})
    assert resp.status_code == 201
    key = resp.json()["api_key"]
    assert client.post("/run/minds", headers=H(key), json={"minds": ["scripted"]}).status_code == 403
    assert _declarations(SessionFactory) == []


def test_held_the_mcp_tool_refuses_a_firm_agent_and_carries_the_runtimes_word(
        SessionFactory, world):
    app = _app(SessionFactory)

    async def go() -> tuple[bool, object]:
        async def call(key: str, minds):
            async with FundClient(base_url="http://fund.test", api_key=key,
                                  transport=httpx.ASGITransport(app=app)) as conn:
                server = build_server(conn)
                try:
                    result = await server.call_tool("declare_run_minds", {"minds": minds})
                except Exception as exc:  # noqa: BLE001 - ToolError is the refusal
                    return True, str(exc)
                return result.is_error, result
        # (A firm agent's refused call before the declaration would spoil the run by
        # design, so the runtime declares first and the pm tries after.)
        lookalike = await call(world["clock"], ["ѕcripted"])  # Cyrillic dze
        runtime = await call(world["clock"], ["scripted"])
        pm = await call(world["pm"][1], ["model"])
        return pm, lookalike, runtime

    with TestClient(app):  # the lifespan installs the run's clock
        pm, lookalike, runtime = asyncio.run(go())
    assert pm[0] and lookalike[0] and not runtime[0], (pm, lookalike, runtime)
    [event] = _declarations(SessionFactory)
    assert event.payload_json == {"minds": ["scripted"]}
    assert event.actor_agent_id == _runtime_id(SessionFactory)


@pytest.mark.parametrize("raw", [
    '{"minds": ["\\u0455cripted"]}',          # Cyrillic lookalike
    '{"minds": ["scripted\\u0000"]}',         # NUL suffix
    '{"minds": ["scripted\\u200b"]}',         # zero-width space
    '{"minds": ["SCRIPTED"]}',
    '{"minds": [" scripted"]}',
    '{"minds": [true]}',
    '{"minds": [1e999]}',
    '{"minds": {"0": "scripted"}}',
    '{"minds": [["scripted"]]}',
    '{"minds": ' + "[" * 3000 + "]" * 3000 + "}",
    '{"minds": [' + ",".join(['"model"'] * 50_000) + "]}",
    '{"minds": ["scripted"], "minds_verified": true}',
    "[]", "null",
])
def test_held_odd_json_is_refused_and_writes_nothing(SessionFactory, world, client, raw):
    resp = client.post("/run/minds", content=raw.encode(),
                       headers={**H(world["clock"]), "content-type": "application/json"})
    assert resp.status_code == 422, resp.text[:200]
    assert _declarations(SessionFactory) == []
    assert _declare(client, world).status_code == 201  # and the run can still declare


def test_held_a_deactivated_agents_earlier_act_still_spoils_the_declaration(
        SessionFactory, world, client, on_run_clock):
    assert client.post("/messages", headers=H(world["pm"][1]),
                       json={"to": "broadcast", "body": "early"}).status_code == 201
    with SessionFactory() as s:  # the operator's hand, actor null
        deactivate_agent(s, agent_id=_agent_id(SessionFactory, "pm-1"))
        s.commit()
    assert _declare(client, world).status_code == 409
    assert _minds(SessionFactory) is None


def test_held_operator_setup_with_a_null_actor_does_not_spoil_but_firm_setup_does(
        SessionFactory, world, client, on_run_clock):
    with SessionFactory() as s:
        register_agent(s, name="seeded", role=AgentRole.analyst, pod_id=1)  # actor null
        s.commit()
    assert _declare(client, world).status_code == 201
    assert _minds(SessionFactory) == ("scripted",)


def test_held_a_rotated_runtime_key_cannot_declare_and_the_rotation_does_not_spoil(
        SessionFactory, world, client, on_run_clock):
    with SessionFactory() as s:
        _, new_key = rotate_runtime_key(s)
        s.commit()
    assert _declare(client, world).status_code == 401
    resp = client.post("/run/minds", headers=H(new_key), json={"minds": ["model"]})
    assert resp.status_code == 201
    assert _minds(SessionFactory) == ("model",)


def test_held_a_firm_agent_under_halt_cannot_declare_and_its_refusal_counts(
        SessionFactory, world, client, halt_file):
    halt_file.write_text("stop")
    assert client.post("/run/minds", headers=H(world["pm"][1]),
                       json={"minds": ["scripted"]}).status_code == 423
    assert _declare(client, world).status_code == 423
    halt_file.unlink()
    # The pm's halt_refused names it: the run was touched, so no label (fails closed).
    assert _declare(client, world).status_code == 409
    assert _minds(SessionFactory) is None


def test_held_firm_acts_after_the_declaration_never_void_it(SessionFactory, world, client):
    """The acts are a covered agent's, one registered after the declaration. As first
    written they were pm-1's, older than the declaration: the rt0017-4 fix makes that
    void the label, by design (cycle 28)."""
    assert _declare(client, world, ["cassette", "scripted"]).status_code == 201
    made = client.post("/agents/register", headers=H(world["admin"]),
                       json={"name": "pm-made", "role": "pm", "pod_id": 1})
    assert made.status_code == 201, made.text
    key = made.json()["api_key"]
    assert client.post("/messages", headers=H(key),
                       json={"to": "broadcast", "body": "late"}).status_code == 201
    assert client.post("/run/minds", headers=H(key),
                       json={"minds": ["model"]}).status_code == 403
    assert client.post("/clock/advance", headers=H(world["clock"]),
                       json={"days": 1}).status_code == 200
    assert _declare(client, world, ["model"]).status_code == 409
    assert _minds(SessionFactory) == ("cassette", "scripted")


def test_held_a_forged_declaration_by_a_firm_or_null_actor_is_never_read(
        SessionFactory, world, on_run_clock):
    pm = _agent_id(SessionFactory, "pm-1")
    with SessionFactory() as s:
        for actor in (None, pm):
            append_event(s, type=EVENT_RUN_MINDS_DECLARED, actor_agent_id=actor,
                         payload={"minds": ["scripted"]})
        s.commit()
        assert rc.run_minds(s) is None


def test_held_a_live_run_never_reads_a_declaration(SessionFactory):
    from app.clock import LiveClock, set_clock
    from app.registry.service import seed_runtime_agent
    set_clock(LiveClock())
    with SessionFactory() as s:
        rid = seed_runtime_agent(s)[0].id
        append_event(s, type=EVENT_RUN_MINDS_DECLARED, actor_agent_id=rid,
                     payload={"minds": ["scripted"]})
        s.commit()
        assert rc.run_minds(s) is None
