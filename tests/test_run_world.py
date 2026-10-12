"""A run records its world, and lives in only one (B-037 slice a, ADR-031).

ADR-030 made a backtest's market a pure function of a secret key; this makes
the ledger say *which* market: ``run_started`` carries the provider's
``world()`` record — the synthetic key only as a one-way fingerprint — and a
backtest database refuses a server or operator command whose market differs,
so no ledger is ever two worlds spliced together.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cli
from app.clock import BacktestClock, LiveClock, set_clock
from app.db.base import get_session
from app.db.models import AgentRole, Event
from app.ledger.events import EVENT_RUN_STARTED, append_event
from app.main import create_app
from app.marketdata import StaticProvider, SyntheticProvider, set_provider
from app.registry.service import register_agent
from app.run_clock import RunClockError, install_run_clock, start_backtest
from tests.support import world_key

START = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


def _synthetic(n: int = 1, symbols: dict[str, float] = SYMBOLS) -> SyntheticProvider:
    provider = SyntheticProvider(world_key(n), symbols)
    set_provider(provider)
    return provider


def _open_run(SessionFactory) -> str:
    """Open a backtest in the installed provider's world; return management's key."""
    session = SessionFactory()
    try:
        start_backtest(session, start=START)
        _, admin = register_agent(session, name="management", role=AgentRole.management)
        session.commit()
        return admin
    finally:
        session.close()


def _run_started(db) -> dict:
    db.expire_all()
    first = db.scalar(select(Event).order_by(Event.id).limit(1))
    assert first.type == EVENT_RUN_STARTED
    return first.payload_json


# --- the record -----------------------------------------------------------------

def test_a_synthetic_world_names_its_law_parameters_and_key_fingerprint():
    record = SyntheticProvider(world_key(1), {"synb": 50.0, "SYNA": 100.0}).world()
    expected_fingerprint = hmac.new(
        world_key(1), b"fingerprint:v1", hashlib.sha256
    ).hexdigest()[:32]
    assert record == {
        "provider": "synthetic",
        "reproducible": True,
        "law": "hmac-sha256-gbm/1",
        "origin": "2000-01-01",
        "drift": 0.0003,
        "volatility": 0.015,
        "symbols": {"SYNA": 100.0, "SYNB": 50.0},
        "key_fingerprint": expected_fingerprint,
    }


def test_the_fingerprint_names_the_key_and_nothing_else():
    a, again, b = (SyntheticProvider(world_key(n), SYMBOLS) for n in (1, 1, 2))
    a.get_price("SYNA", as_of=START)                 # serving does not change the record
    assert a.world() == again.world()
    assert a.world()["key_fingerprint"] != b.world()["key_fingerprint"]
    text = json.dumps(a.world())
    assert world_key(1).hex() not in text
    assert world_key(1).hex()[:32] not in text


def test_a_feed_that_is_not_a_function_of_its_record_says_so():
    assert StaticProvider({"AAPL": 1.0}).world() == {"provider": "static", "reproducible": False}


# --- the ledger keeps it ----------------------------------------------------------

def test_run_started_carries_the_world(SessionFactory, db):
    provider = _synthetic(1)
    _open_run(SessionFactory)
    assert _run_started(db)["world"] == provider.world()


def test_the_same_world_restarts(SessionFactory, db):
    _synthetic(1)
    _open_run(SessionFactory)
    set_clock(LiveClock())
    _synthetic(1)                                    # a fresh process, the same key
    assert install_run_clock(db).now() == START


@pytest.mark.parametrize(
    "other, differs",
    [
        (lambda: _synthetic(2), "key_fingerprint"),
        (lambda: _synthetic(1, {"SYNA": 100.0}), "symbols"),
        (lambda: set_provider(StaticProvider({"SYNA": 1.0})), "provider"),
    ],
    ids=["another-key", "other-symbols", "another-provider"],
)
def test_another_world_does_not_start(SessionFactory, db, other, differs):
    _synthetic(1)
    _open_run(SessionFactory)
    set_clock(LiveClock())
    other()
    with pytest.raises(RunClockError, match=differs):
        install_run_clock(db)


def test_a_run_from_before_worlds_were_recorded_still_starts(db):
    set_clock(BacktestClock(START))
    append_event(db, type=EVENT_RUN_STARTED, actor_agent_id=None,
                 payload={"mode": "backtest", "start": START.isoformat(),
                          "look_ahead_guard": True})
    db.commit()
    assert install_run_clock(db).now() == START


def test_the_server_refuses_to_serve_a_run_in_another_world(SessionFactory):
    _synthetic(1)
    _open_run(SessionFactory)
    set_clock(LiveClock())
    _synthetic(2)
    app = create_app()

    def _session():
        s = SessionFactory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    with pytest.raises(RunClockError, match="another world"):
        with TestClient(app):
            pass


def test_an_operator_command_refuses_a_run_in_another_world(
    SessionFactory, db, monkeypatch, capsys
):
    @contextmanager
    def scope() -> Iterator:
        s = SessionFactory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)
    _synthetic(1)
    assert cli.main(["start-backtest", "--start", START.isoformat()]) == 0
    set_clock(LiveClock())
    _synthetic(2)
    assert cli.main(["create-pod", "--name", "desk", "--allocation", "1000"]) == 1
    assert "another world" in capsys.readouterr().err
    db.expire_all()
    assert [e.type for e in db.execute(select(Event)).scalars()] == [EVENT_RUN_STARTED]


def test_start_backtest_without_a_world_key_is_an_error_not_a_traceback(
    SessionFactory, db, monkeypatch, capsys
):
    from app.config import get_settings

    @contextmanager
    def scope() -> Iterator:
        s = SessionFactory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(get_settings().marketdata, "provider", "synthetic")
    monkeypatch.setattr(get_settings().marketdata, "synthetic_key", None)
    set_provider(None)                               # build from (keyless) config
    assert cli.main(["start-backtest", "--start", START.isoformat()]) == 1
    assert "no world key" in capsys.readouterr().err
    db.expire_all()
    assert db.scalar(select(Event).limit(1)) is None


def test_management_sees_the_fingerprint_never_the_key(SessionFactory):
    provider = _synthetic(1)
    admin = _open_run(SessionFactory)
    app = create_app()

    def _session():
        s = SessionFactory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as client:
        resp = client.get("/events", headers={"X-API-Key": admin})
    assert resp.status_code == 200, resp.text
    assert provider.world()["key_fingerprint"] in resp.text
    assert world_key(1).hex()[:32] not in resp.text
