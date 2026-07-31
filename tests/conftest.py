"""Shared test fixtures.

Each test runs against a fresh in-memory SQLite database (StaticPool so every
connection sees the same in-memory schema). The API's ``get_session`` dependency
is overridden to use this test database, and a management "admin" agent is seeded
so protected endpoints can be exercised.

Two global services are neutralised for the whole suite by autouse fixtures:

* the **market data provider** is replaced with an offline
  :class:`~app.marketdata.StaticProvider`, so no test ever touches the network
  and prices only move when a test moves them;
* the **background scheduler** is switched off, so a sweep never fires against
  the real ``fund.db`` while tests run.

Both are restored afterwards, so importing the app for real still behaves
normally.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from datetime import datetime, timezone

from app.config import get_settings
from app.db.base import get_session
from app.db.models import AgentRole, Base, Pod
from app.main import create_app
from app.marketdata import StaticProvider, set_provider
from app.registry.pods import fund_pod
from app.registry.service import get_or_create_system_agent, register_agent

#: Starting prices every test begins from. Tests move them with ``prices.set_price``.
DEFAULT_PRICES = {"AAPL": 200.0, "MSFT": 400.0, "NVDA": 100.0}


@pytest.fixture(scope="session", autouse=True)
def quiet_logs() -> None:
    """Keep the app's INFO-level JSON logs out of test failure output.

    Warnings and errors still surface, so a genuinely noisy failure is still
    visible; the per-request audit lines are not what you want to read when an
    assertion breaks.
    """
    import sys

    from loguru import logger

    from app import logging_setup

    logger.remove()
    logger.add(sys.stderr, level="WARNING", serialize=False)
    logging_setup._configured = True


@pytest.fixture(autouse=True)
def prices() -> Iterator[StaticProvider]:
    """Offline, controllable market data for every test."""
    provider = StaticProvider(dict(DEFAULT_PRICES))
    set_provider(provider)
    yield provider
    set_provider(None)


@pytest.fixture(autouse=True)
def no_background_jobs() -> Iterator[None]:
    """Keep APScheduler out of the test process."""
    oms_cfg = get_settings().oms
    previous = oms_cfg.pending_monitor_enabled
    oms_cfg.pending_monitor_enabled = False
    yield
    oms_cfg.pending_monitor_enabled = previous


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def SessionFactory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def db(SessionFactory) -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_key(SessionFactory) -> str:
    """Seed a management agent and return its API key."""
    session = SessionFactory()
    try:
        _, api_key = register_agent(
            session, name="management", role=AgentRole.management
        )
        session.commit()
    finally:
        session.close()
    return api_key


@pytest.fixture
def make_pod(SessionFactory):
    """Factory to create a pod with an explicit id (pods must exist before
    agents/orders/allocations reference them — the FK is enforced)."""

    def _make(pod_id: int, name: str | None = None) -> int:
        session = SessionFactory()
        try:
            session.add(
                Pod(
                    id=pod_id,
                    name=name or f"pod-{pod_id}",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        finally:
            session.close()
        return pod_id

    return _make


@pytest.fixture
def fund_pod_cash(SessionFactory):
    """Factory: give a pod virtual cash the way the app really does it.

    Goes through the allocation event, not a direct write to ``cash_balances``,
    so tests exercise the same path production uses (and a ``rebuild_state``
    over the test data reproduces the balance).
    """

    def _fund(pod_id: int, amount: float) -> float:
        session = SessionFactory()
        try:
            pod = fund_pod(
                session,
                pod_id=pod_id,
                delta=amount,
                actor=get_or_create_system_agent(session),
                reason="test funding",
            )
            session.commit()
            return pod.current_allocation
        finally:
            session.close()

    return _fund


@pytest.fixture
def pm_factory(client, admin_key):
    """Factory: register a PM attached to a pod and return ``(id, api_key)``."""

    def _make(name: str, pod_id: int) -> tuple[int, str]:
        resp = client.post(
            "/agents/register",
            headers={"X-API-Key": admin_key},
            json={"name": name, "role": "pm", "pod_id": pod_id},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        return body["id"], body["api_key"]

    return _make


@pytest.fixture
def desk(client, make_pod, fund_pod_cash, pm_factory):
    """A ready-to-trade desk: pod 1, funded with $100k, with PM ``pm-1``.

    Most OMS tests want exactly this, so it lives here instead of in five
    copies. Returns ``(pod_id, pm_id, pm_key)``.
    """
    pod_id = make_pod(1)
    fund_pod_cash(pod_id, 100_000.0)
    pm_id, pm_key = pm_factory("pm-1", pod_id)
    return pod_id, pm_id, pm_key


@pytest.fixture
def client(SessionFactory) -> Iterator[TestClient]:
    app = create_app()

    def _override_get_session() -> Iterator[Session]:
        session = SessionFactory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
