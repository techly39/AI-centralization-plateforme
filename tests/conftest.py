"""Shared test fixtures.

Each test runs against a fresh in-memory SQLite database (StaticPool so every
connection sees the same in-memory schema). The API's ``get_session`` dependency
is overridden to use this test database, and a management "admin" agent is seeded
so protected endpoints can be exercised.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from datetime import datetime, timezone

from app.db.base import get_session
from app.db.models import AgentRole, Base, Pod
from app.main import create_app
from app.registry.service import register_agent


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
