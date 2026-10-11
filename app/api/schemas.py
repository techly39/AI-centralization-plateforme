"""Pydantic v2 request/response models for the v1 API.

Every endpoint has an explicit schema (TRD Definition of Done). ``from_attributes``
lets response models be built straight from ORM objects.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AgentRole, AgentStatus, OrderSide, OrderStatus, PriceType
from app.limits import MAX_TOKENS_PER_REPORT

# Roles an operator/management may assign via the API. 'system' is internal-only
# and is created by the bootstrap CLI, never over HTTP.
RegisterableRole = Literal["analyst", "pm", "management"]


class AgentRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role: RegisterableRole
    pod_id: int | None = None
    charter_ref: str | None = Field(default=None, max_length=256)
    research_domains: list[str] | None = None


class AgentCreatedResponse(BaseModel):
    """Returned once at registration; carries the plaintext key exactly once."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: AgentRole
    pod_id: int | None
    status: AgentStatus
    created_at: datetime
    api_key: str = Field(description="Plaintext key — store it now; not retrievable later.")


class DirectoryEntry(BaseModel):
    """One row of the shared directory (TRD §7).

    ``status`` is included so an agent choosing who to message can tell a live
    colleague from a decommissioned one, instead of addressing the void.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: AgentRole
    pod_id: int | None
    research_domains: list[str] | None = None
    status: AgentStatus


class DeactivateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: AgentStatus


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor_agent_id: int | None
    type: str
    payload_json: dict


class ClockOut(BaseModel):
    mode: str
    now: datetime


# --- Market data (TRD §7) ---------------------------------------------------

class PriceOut(BaseModel):
    ticker: str
    price: float
    as_of: datetime = Field(description="When the price itself is from.")
    currency: str
    source: str = Field(description="Which provider served it, for the audit trail.")


class BarOut(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVOut(BaseModel):
    ticker: str
    interval: str
    start: date
    end: date
    #: Never contains a bar stamped after the clock's now (look-ahead guard).
    bars: list[BarOut]


# --- OMS (TRD §7, §8) -------------------------------------------------------

class OrderCreateRequest(BaseModel):
    """Body of ``POST /orders``.

    There is no ``pod_id``: an order always belongs to the placing PM's own pod
    (TRD §6). ``justification`` is required — an order with no stated reason is
    not reviewable, and reviewability is the point of the whole environment.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=16)
    side: Literal["buy", "sell"]
    qty: float = Field(gt=0, description="Number of shares. Fractional allowed.")
    price_type: Literal["market", "limit"]
    limit_price: float | None = Field(
        default=None, gt=0, description="Required for limit orders, forbidden otherwise."
    )
    justification: str = Field(min_length=1, max_length=4000)


class OrderOut(BaseModel):
    """An order's current state.

    ``status`` is the field that matters: ``rejected`` is a normal answer to a
    perfectly well-formed request (no cash, no shares) and comes back with HTTP
    201, because the order exists — read ``status_reason`` for why.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    pod_id: int
    created_by: int
    ticker: str
    side: OrderSide
    qty: float
    price_type: PriceType
    limit_price: float | None
    status: OrderStatus
    justification: str | None
    created_at: datetime
    filled_at: datetime | None
    fill_price: float | None
    fee: float | None
    realized_pnl: float | None
    status_reason: str | None


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    qty: float
    avg_cost: float
    cost_basis: float
    #: Null when the price could not be read on this call — see pricing_errors.
    last_price: float | None
    market_value: float | None
    unrealized_pnl: float | None


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pod_id: int
    as_of: datetime
    cash: float
    positions: list[PositionOut]
    positions_value: float
    total_value: float
    unrealized_pnl: float
    pricing_errors: list[str]
    fully_priced: bool = Field(
        description="False when at least one position could not be valued."
    )


# --- Messaging (TRD §7) -----------------------------------------------------

class MessageSendRequest(BaseModel):
    """Body of ``POST /messages``.

    ``to`` is one of three forms — ``agent:<id>``, ``pod:<id>``, or
    ``broadcast``. Any role may address an agent or a pod; ``broadcast`` reaches
    the whole firm for management and is scoped to their own pod for a PM
    (TRD §6). The message that comes back tells you the audience it actually got.
    """

    model_config = ConfigDict(extra="forbid")

    to: str = Field(
        min_length=1,
        max_length=32,
        examples=["agent:3", "pod:1", "broadcast"],
    )
    body: str = Field(min_length=1, max_length=20_000)
    thread_id: str | None = Field(
        default=None,
        max_length=64,
        description="Group a conversation. Reuse the id you were replied to on.",
    )
    structured_payload: dict | None = Field(
        default=None,
        description=(
            "Machine-readable version of the message. TRD §10: an agent should "
            "be able to act on the content without parsing the prose."
        ),
    )


class MessageOut(BaseModel):
    """A stored message.

    ``to_ref``/``structured_payload_json`` are the column names; the wire uses
    the friendlier ``to``/``structured_payload``, which is what an agent writes
    when sending. The aliases keep both halves of the round trip identical.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    ts: datetime
    from_agent: int
    to: str = Field(
        validation_alias="to_ref",
        description="The audience that actually received it.",
    )
    thread_id: str | None
    body: str
    structured_payload: dict | None = Field(
        default=None,
        validation_alias="structured_payload_json",
    )


# --- Cost & task self-reporting (TRD §7) ------------------------------------

class CostReportRequest(BaseModel):
    """Body of ``POST /costs``.

    There is no ``agent_id`` or ``pod_id``: the report is always about the
    authenticated caller, charged to the pod the registry says it belongs to.
    An agent cannot bill its spending to someone else.
    """

    model_config = ConfigDict(extra="forbid")

    tokens_in: int = Field(ge=0, le=MAX_TOKENS_PER_REPORT)
    tokens_out: int = Field(ge=0, le=MAX_TOKENS_PER_REPORT)
    usd_cost: float = Field(ge=0.0)
    task_label: str | None = Field(
        default=None,
        max_length=128,
        description="What the spend was for. Reuse a small, stable vocabulary.",
    )


class CostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    agent_id: int
    pod_id: int | None
    tokens_in: int
    tokens_out: int
    usd_cost: float
    task_label: str | None


class TaskStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(
        min_length=1,
        max_length=256,
        description=(
            "The grouping key for the 'time per subject' metric. Reuse stable "
            "subjects ('earnings review') rather than writing a new sentence "
            "each time, or the metric fragments into noise."
        ),
    )


class TaskEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int
    outcome: dict = Field(
        description=(
            "Structured result — TRD §10 requires JSON, not free text alone. "
            'Put any prose under a key, e.g. {"summary": "...", "conviction": 0.7}.'
        )
    )


class TaskOut(BaseModel):
    """A work log entry. Built explicitly by the router, because ``seconds`` is
    derived from the row rather than stored on it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pod_id: int | None
    agent_id: int
    subject: str
    started_at: datetime
    ended_at: datetime | None
    #: How long it took. Null while the task is still open.
    seconds: float | None = None
    outcome: dict | None = None


# --- Metrics (TRD §7, management only) --------------------------------------

class CapitalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    net_contributed: float = Field(
        description="Sum of every allocation ever made to this pod."
    )
    cash: float
    positions_value: float
    total_value: float


class PerformanceOut(BaseModel):
    """Nulls are deliberate: a statistic with too little history is not zero."""

    model_config = ConfigDict(from_attributes=True)

    total_return: float | None = Field(
        description="Time-weighted, so allocations do not count as returns."
    )
    sharpe_daily: float | None
    sharpe_annualised: float | None
    max_drawdown: float | None = Field(
        description="Negative fraction; -0.23 means a 23% peak-to-trough fall."
    )
    hit_rate: float | None = Field(description="Winning closed trades / closed trades.")
    pnl: float = Field(description="Total value − net capital contributed.")
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    closed_trades: int
    winning_trades: int
    observations: int = Field(description="Daily equity points behind the statistics.")
    pricing_errors: list[str]
    fully_priced: bool


class CostSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_usd_cost: float
    tokens_in: int
    tokens_out: int
    reports: int = Field(
        description="How many cost reports arrived. Zero means unmeasured, not free."
    )


class SubjectTimeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject: str
    seconds: float
    tasks: int


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tasks_opened: int
    tasks_closed: int
    tasks_open: int
    total_task_seconds: float
    time_per_subject: list[SubjectTimeOut]
    messages_sent: int
    orders_placed: int
    orders_filled: int
    orders_rejected: int
    orders_pending: int
    orders_cancelled: int


class PodMetricsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pod_id: int
    pod_name: str | None
    as_of: datetime
    capital: CapitalOut
    performance: PerformanceOut
    cost: CostSummaryOut
    activity: ActivityOut
    cost_adjusted_pnl: float = Field(
        description="P&L − usd_cost. The number pods are ranked on."
    )


class LeaderboardRowOut(BaseModel):
    """The comparison view: one line per pod, best cost-adjusted P&L first."""

    model_config = ConfigDict(from_attributes=True)

    pod_id: int
    pod_name: str | None
    total_value: float
    pnl: float
    total_usd_cost: float
    cost_adjusted_pnl: float
    total_return: float | None
    sharpe_daily: float | None
    max_drawdown: float | None
    hit_rate: float | None
    orders_filled: int
    messages_sent: int


class LeaderboardOut(BaseModel):
    as_of: datetime
    rows: list[LeaderboardRowOut]
