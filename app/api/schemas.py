"""Pydantic v2 request/response models for the v1 API.

Every endpoint has an explicit schema (TRD Definition of Done). ``from_attributes``
lets response models be built straight from ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AgentRole, AgentStatus

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
