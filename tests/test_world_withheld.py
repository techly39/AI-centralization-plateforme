"""B-049 (ADR-034): the operator's facts about the experiment are withheld from every agent.

Claims under test:

* management's ``GET /events`` (every filter, and ``list_events`` over MCP) reads
  ``run_started.world`` and ``run_minds_declared.minds`` as ``"withheld"``: no
  law, drift, volatility, symbol list or fingerprint reaches a firm agent through
  the ledger (what an agent can estimate from served bars is its own work);
* the ledger keeps the full record: a read never rewrites the row, a restart in the
  same world still starts and one in another world is still refused, and
  ``run_minds()`` still reads the kinds;
* every other field and every other event type passes through unchanged;
* ``EventOut`` is the only response shape that carries an event payload, so the
  rule has one home.
"""

from __future__ import annotations

import inspect
import json
import secrets
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select

import app.api.schemas as schemas
from app.api.schemas import EventOut
from app.clock import LiveClock, set_clock
from app.db.models import Event
from app.ledger.events import (
    AGENT_WITHHELD_FIELDS,
    EVENT_AGENT_REGISTERED,
    EVENT_RUN_MINDS_DECLARED,
    EVENT_RUN_STARTED,
    WITHHELD,
    agent_payload,
)
from app.marketdata import SyntheticProvider
from app.run_clock import RunClockError, run_minds
from mcp_server import FundClient, build_server
from tests.test_mcp_server import call
from tests.test_redteam_0011 import SYMBOLS, _open_world, _restart
from tests.test_runtime_lockstep import _app

FILTERS = ({}, {"type": EVENT_RUN_STARTED}, {"type": EVENT_RUN_MINDS_DECLARED},
           {"limit": 1000}, {"since": "2000-01-01T00:00:00Z"})


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


@pytest.fixture
def opened(SessionFactory):
    """A synthetic backtest with management, a PM, an analyst and a declared mind kind."""
    secret = secrets.token_bytes(32)
    provider = SyntheticProvider(secret, SYMBOLS)
    world = _open_world(SessionFactory, provider)
    world["provider"] = provider
    with TestClient(_app(SessionFactory)) as client:
        assert client.post("/run/minds", headers=H(world["runtime"]),
                           json={"minds": ["scripted"]}).status_code == 201
        world["client"] = client
        yield world


def _first(SessionFactory, type: str) -> Event:
    with SessionFactory() as s:
        return s.scalar(select(Event).where(Event.type == type).order_by(Event.id).limit(1))


def _secrets_of(world: dict) -> list[str]:
    """Every spelling of the law a reader could match on."""
    record = world["provider"].world()
    out = [record["key_fingerprint"], record["law"], "key_fingerprint", "drift", "volatility"]
    out += [json.dumps(record[k]) for k in ("drift", "volatility")]
    return out


# --- the agent's read ----------------------------------------------------------------------

def test_management_reads_the_world_and_the_minds_as_withheld(opened):
    for params in FILTERS:
        r = opened["client"].get("/events", headers=H(opened["admin"]), params=params)
        assert r.status_code == 200, (params, r.text)
        for e in r.json():
            if e["type"] == EVENT_RUN_STARTED:
                assert e["payload_json"]["world"] == WITHHELD
                assert e["payload_json"]["mode"] == "backtest"  # the rest passes through
            if e["type"] == EVENT_RUN_MINDS_DECLARED:
                assert e["payload_json"] == {"minds": WITHHELD}
        for spelling in _secrets_of(opened):
            assert spelling not in r.text, (params, spelling)


def test_both_withheld_events_are_in_the_read(opened):
    """The negative test above is not vacuous: management does read both events."""
    r = opened["client"].get("/events", headers=H(opened["admin"]), params={"limit": 1000})
    types = [e["type"] for e in r.json()]
    assert EVENT_RUN_STARTED in types and EVENT_RUN_MINDS_DECLARED in types


def test_the_symbol_list_is_withheld_with_the_world(opened):
    r = opened["client"].get("/events", headers=H(opened["admin"]),
                             params={"type": EVENT_RUN_STARTED})
    assert "SYNB" not in r.text and "SYNC" not in r.text


@pytest.mark.anyio
async def test_list_events_over_mcp_is_withheld_too(SessionFactory, opened):
    transport = httpx.ASGITransport(app=_app(SessionFactory))
    async with FundClient(base_url="http://fund.test", api_key=opened["admin"],
                          transport=transport) as conn:
        events = await call(build_server(conn), "list_events", limit=1000)
    assert {e["type"] for e in events} >= {EVENT_RUN_STARTED, EVENT_RUN_MINDS_DECLARED}
    blob = json.dumps(events)
    for spelling in _secrets_of(opened):
        assert spelling not in blob


# --- the ledger keeps the record -----------------------------------------------------------

def test_a_read_never_rewrites_the_ledger(SessionFactory, opened):
    for _ in range(2):
        opened["client"].get("/events", headers=H(opened["admin"]), params={"limit": 1000})
    with SessionFactory() as s:
        assert run_minds(s) == ("scripted",)
    # a write after the reads commits whatever the read session might have dirtied (the PM
    # predates the declaration, so its act also voids the label: red-team 0017 H4)
    assert opened["client"].post("/messages", headers=H(opened["pm"]),
                                 json={"to": "broadcast", "body": "after"}).status_code == 201
    assert _first(SessionFactory, EVENT_RUN_STARTED).payload_json["world"] \
        == opened["provider"].world()
    assert _first(SessionFactory, EVENT_RUN_MINDS_DECLARED).payload_json == {"minds": ["scripted"]}


def test_validating_an_orm_event_leaves_it_whole(SessionFactory, opened):
    """Planted counter-example: an in-place rewrite would be flushed by the next commit."""
    with SessionFactory() as s:
        event = s.scalar(select(Event).where(Event.type == EVENT_RUN_STARTED))
        assert EventOut.model_validate(event).payload_json["world"] == WITHHELD
        assert event.payload_json["world"] == opened["provider"].world()
        assert event not in s.dirty


def test_the_world_check_still_reads_the_full_record(db, opened):
    _restart(db, opened["provider"])  # same world: starts
    with pytest.raises(RunClockError):
        _restart(db, SyntheticProvider(secrets.token_bytes(32), SYMBOLS))


# --- the rule ------------------------------------------------------------------------------

def test_agent_payload_withholds_only_the_named_fields():
    world = {"law": "x", "drift": 0.1}
    payload = {"mode": "backtest", "start": "s", "world": world}
    out = agent_payload(EVENT_RUN_STARTED, payload)
    assert out == {"mode": "backtest", "start": "s", "world": WITHHELD}
    assert payload["world"] is world  # never mutated
    assert agent_payload(EVENT_AGENT_REGISTERED, {"world": 1}) == {"world": 1}
    assert agent_payload(EVENT_RUN_STARTED, None) == {}
    assert agent_payload(EVENT_RUN_STARTED, {"mode": "live"}) == {"mode": "live"}  # pre-ADR-031


def test_every_withheld_event_type_is_a_real_event_type():
    import app.ledger.events as events
    names = {v for k, v in vars(events).items() if k.startswith("EVENT_") and isinstance(v, str)}
    assert set(AGENT_WITHHELD_FIELDS) <= names
    assert all(AGENT_WITHHELD_FIELDS.values())


def test_event_out_is_the_only_shape_carrying_a_payload():
    """Another response model with ``payload_json`` would bypass the rule."""
    carriers = [name for name, obj in inspect.getmembers(schemas, inspect.isclass)
                if issubclass(obj, BaseModel) and obj.__module__ == schemas.__name__
                and "payload_json" in obj.model_fields]
    assert carriers == ["EventOut"]
