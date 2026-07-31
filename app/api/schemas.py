"""Pydantic v2 request/response models for the v1 API.

Every endpoint has an explicit schema (TRD Definition of Done). ``from_attributes``
lets response models be built straight from ORM objects.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AgentRole, AgentStatus, OrderSide, OrderStatus, PriceType

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
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: AgentRole
    pod_id: int | None
    research_domains: list[str] | None = None


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
