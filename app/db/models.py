"""ORM models — the SQLite schema from TRD §5.

Notes for future maintainers:
- ``events`` is append-only and is the system's source of truth. ``positions``
  and ``cash_balances`` are *derived*: they can be dropped and rebuilt by
  replaying ``events`` (see :func:`app.ledger.rebuild.rebuild_state`).
- Domain timestamps (``ts``/``created_at``) are always written from the injected
  clock in the service layer, never from a database default — time is injected
  (TRD principle 5). They use :class:`~app.db.types.UTCDateTime`, so what comes
  back out of the database is aware UTC and directly comparable with
  ``clock.now()``; see that module for why the plain ``DateTime`` is a trap.
- Every table was declared in Phase 0 so the schema would be stable from the
  start; behaviour arrives phase by phase. Live as of Phase 2: agents, pods,
  events, orders, positions, cash_balances, messages, costs, tasks. Still
  awaiting its endpoint: allocations (Phase 3, though the rows are already
  written by the operator CLI).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime


# --- Enums ------------------------------------------------------------------
# native_enum=False stores the value as a portable VARCHAR + CHECK constraint,
# which behaves identically on SQLite and Postgres.

class AgentRole(str, enum.Enum):
    analyst = "analyst"
    pm = "pm"
    management = "management"
    system = "system"


class AgentStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class OrderSide(str, enum.Enum):
    buy = "buy"
    sell = "sell"


class PriceType(str, enum.Enum):
    market = "market"
    limit = "limit"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    filled = "filled"
    rejected = "rejected"
    cancelled = "cancelled"


def _role_enum() -> Enum:
    return Enum(AgentRole, native_enum=False, length=16, validate_strings=True)


# --- Core tables ------------------------------------------------------------

class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    role: Mapped[AgentRole] = mapped_column(_role_enum(), nullable=False)
    pod_id: Mapped[int | None] = mapped_column(
        ForeignKey("pods.id"), nullable=True
    )
    api_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    charter_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    research_domains: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, native_enum=False, length=16),
        nullable=False,
        default=AgentStatus.active,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    pod: Mapped["Pod | None"] = relationship(back_populates="agents")


class Pod(Base):
    __tablename__ = "pods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    current_allocation: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    agents: Mapped[list[Agent]] = relationship(back_populates="pod")


class Event(Base):
    """Append-only ledger. Every state change in the system is one row here."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    actor_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


# --- OMS tables (behaviour: Phase 1) ---------------------------------------

class Order(Base):
    """One PM submission for one ticker.

    The row is the current *state* of the order; the *history* of how it got
    there lives in ``events`` (``order_placed`` / ``order_filled`` /
    ``order_rejected`` / ``order_cancelled``). ``fee`` and ``realized_pnl``
    duplicate what the fill event already records — deliberately, so that
    ``GET /orders`` can answer "what did this cost me" without replaying the
    ledger. The event stays the source of truth.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pod_id: Mapped[int] = mapped_column(
        ForeignKey("pods.id"), nullable=False, index=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, native_enum=False, length=8), nullable=False
    )
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    price_type: Mapped[PriceType] = mapped_column(
        Enum(PriceType, native_enum=False, length=8), nullable=False
    )
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=12),
        nullable=False,
        default=OrderStatus.pending,
        index=True,
    )
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    filled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Simulated commission actually charged on the fill.
    fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Sells only: proceeds minus the weighted-average cost of the shares sold.
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Why the order was rejected or cancelled, in plain words, for the PM.
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# --- Derived tables (rebuildable from events) ------------------------------

class Position(Base):
    __tablename__ = "positions"

    pod_id: Mapped[int] = mapped_column(
        ForeignKey("pods.id"), primary_key=True
    )
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class CashBalance(Base):
    __tablename__ = "cash_balances"

    pod_id: Mapped[int] = mapped_column(
        ForeignKey("pods.id"), primary_key=True
    )
    balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


# --- Messaging / cost / task (behaviour: Phase 2) --------------------------

class Message(Base):
    """One thing an agent said, to one audience (TRD §5, §7).

    ``to_ref`` is a tagged union — ``agent:<id>``, ``pod:<id>``, or the literal
    ``broadcast``. The format and its parser live in :mod:`app.bus.refs`; it is
    indexed because the visibility filter behind ``GET /messages`` matches on it
    for every read an agent makes while polling.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    from_agent: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    to_ref: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    structured_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Cost(Base):
    """What one unit of an agent's work cost, as reported by that agent.

    The app cannot measure external token usage (TRD §7), so these numbers are
    self-reported. ``agent_id``/``pod_id`` come from the authenticated caller,
    never from the request body — see :mod:`app.metrics.reporting`.
    """

    __tablename__ = "costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    pod_id: Mapped[int | None] = mapped_column(
        ForeignKey("pods.id"), nullable=True, index=True
    )
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usd_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    task_label: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Task(Base):
    """A self-reported work log entry. ``ended_at is None`` means still open."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pod_id: Mapped[int | None] = mapped_column(
        ForeignKey("pods.id"), nullable=True, index=True
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    outcome_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# --- Allocation (behaviour: Phase 3) ---------------------------------------


class Allocation(Base):
    __tablename__ = "allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    pod_id: Mapped[int] = mapped_column(ForeignKey("pods.id"), nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    new_total: Mapped[float] = mapped_column(Float, nullable=False)
    set_by: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
