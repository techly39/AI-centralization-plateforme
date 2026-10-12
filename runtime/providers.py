"""The seam every mind plugs into (ADR-032 (3)): ``LLMProvider.complete``.

A provider turns one request (messages + the tool schema the adapter built
from the published MCP tool list) into one response (text and/or tool calls,
plus usage). Three providers are planned: ``scripted`` (R-2,
:mod:`runtime.scripted`: a deterministic policy in code, no model, no network),
``cassette`` (R-4: replays a recorded exchange, refuses on a miss) and
``metered`` (R-6: one OpenRouter key per agent). Which name builds which class
is :mod:`runtime.registry`'s closed table.

``Usage.cost_usd`` is what a provider says it spent. It is never the meter:
system-reported cost overrides it (R-6).

``spends_money`` is a description for reports. The wake gate never reads it:
what may run under the cap is decided by name, in :mod:`runtime.gate`.

The request/response shapes are the minimum R-2 needs. Cassettes (R-4) will
hash requests; that format is decided there.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ToolSpec(_Model):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolCall(_Model):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(_Model):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    #: For ``role="assistant"``: the calls the mind asked for in this turn.
    tool_calls: list[ToolCall] = Field(default_factory=list)
    #: For ``role="tool"``: the call this message answers.
    tool_call_id: str | None = None
    #: For ``role="tool"``: the call failed or was refused; ``content`` says why.
    is_error: bool = False


class Usage(_Model):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


class CompletionRequest(_Model):
    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    model: str | None = None


class CompletionResponse(_Model):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)


@runtime_checkable
class LLMProvider(Protocol):
    #: The name the AgentSpec uses and the gate decides on.
    name: str
    spends_money: bool

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...
