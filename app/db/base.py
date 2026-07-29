"""SQLAlchemy 2.0 engine, session factory, and declarative base.

Kept database-agnostic on purpose: everything goes through ``database_url`` so a
future move from SQLite to Postgres is a config change, not a code change. The
SQLite-specific bits (file URL handling, ``PRAGMA foreign_keys=ON``) are guarded
so they simply do not run on other backends.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import REPO_ROOT, get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _resolve_url(database_url: str) -> str:
    """Make a relative SQLite file path absolute against the repo root.

    ``sqlite:///fund.db`` otherwise resolves relative to the process's current
    working directory, which makes "where is my data" depend on where you happen
    to launch from. Anchoring to the repo root keeps it predictable.
    """
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        path = database_url[len(prefix):]
        if path and path != ":memory:" and not path.startswith("/"):
            return f"{prefix}{(REPO_ROOT / path).as_posix()}"
    return database_url


def _make_engine(database_url: str) -> Engine:
    resolved = _resolve_url(database_url)
    connect_args: dict[str, object] = {}
    if resolved.startswith("sqlite"):
        # Allow the connection to be shared across threads (FastAPI/APScheduler).
        connect_args["check_same_thread"] = False
    engine = create_engine(resolved, connect_args=connect_args, future=True)

    if resolved.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


# Module-level singletons, built from the active settings.
_settings = get_settings()
engine: Engine = _make_engine(_settings.database_url)
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, future=True
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context: commit on success, rollback on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session.

    The request handler is responsible for committing (via the service layer);
    this just guarantees rollback-on-error and close.
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
