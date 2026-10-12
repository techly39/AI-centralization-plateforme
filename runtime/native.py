"""The ``native`` adapter: one wake of one mind over the published tools (ADR-032 (2), R-2).

A mind acts only through the tool list :func:`mcp_server.build_server` publishes
— the same tools an OpenClaw agent gets — so "same tools for every adapter"
holds by construction. Each call runs the MCP tool function, which calls the API
over HTTP with the agent's own key; physics decides what is allowed (403s reach
the mind as tool errors). The adapter only decides *what the mind sees*:

* **tools** — the published list, narrowed by ``spec.tools`` (an unknown name in
  the spec refuses the wake). A call to a tool outside the mind's list is
  answered with an error and reaches no endpoint.
* **context** — assembled by code: the charter as the system message, then one
  user message holding ``/me`` (read by code through ``whoami``) and the
  workflow input, as sorted JSON. It is the start of the returned transcript.

And it enforces the Runtime's own limits (03 §3):

* the wake gate before anything else; the mind is built from the spec by
  :mod:`runtime.registry`, never handed in;
* **HALT is re-read before every tool-call batch**; a halted batch does not run;
* a per-wake **tool-call budget**; a batch that would pass it does not run.

A wake ends when the mind replies with no tool calls (``done``), or with
``halted``, ``tool_budget`` or ``refused``. Every turn ends in one of those or in
at least one tool call, so the budget bounds the loop. Every exit returns a
:class:`WakeRecord`; R-4 writes it to a cassette. Wall-clock timeouts arrive
with the first provider that can hang (R-6); a script cannot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.client import FundClient
from mcp_server.tools import build_server
from runtime.gate import decide_batch, decide_wake
from runtime.providers import CompletionRequest, Message, ToolCall, ToolSpec
from runtime.registry import ProviderRefused, build_provider
from runtime.spec import AgentSpec

#: Tool calls one wake may make unless the caller says otherwise.
DEFAULT_MAX_TOOL_CALLS = 64


@dataclass(frozen=True)
class WakeRecord:
    spec_id: str
    #: ``done`` | ``halted`` | ``tool_budget`` | ``refused``
    ended: str
    #: Why: the gate's or registry's reason code, or the same word as ``ended``.
    reason: str
    #: Tool calls the mind made that were executed (refused calls included).
    tool_calls: int
    #: Context first (system, user), then every turn and result, in order.
    transcript: tuple[Message, ...] = ()


async def published_tools(client: FundClient) -> list[ToolSpec]:
    """The tool list ``build_server`` publishes, as the provider sees it."""
    return _tool_specs(await build_server(client).list_tools())


def _tool_specs(tools: Any) -> list[ToolSpec]:
    return [
        ToolSpec(name=t.name, description=t.description or "", input_schema=t.input_schema)
        for t in tools
    ]


async def wake(
    spec: AgentSpec,
    client: FundClient,
    *,
    workflow_input: dict[str, Any],
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> WakeRecord:
    """Wake the mind ``spec`` describes once, acting as ``client``'s agent."""
    if type(max_tool_calls) is not int or max_tool_calls < 0:
        raise ValueError("max_tool_calls is a non-negative int")
    if spec.adapter != "native":
        return WakeRecord(spec.id, "refused", "wrong_adapter", 0)
    decision = decide_wake(spec.provider, spec.adapter)
    if not decision.allowed:
        return WakeRecord(spec.id, "refused", decision.reason, 0)
    try:
        provider = build_provider(spec)
    except ProviderRefused as exc:
        return WakeRecord(spec.id, "refused", exc.reason, 0)

    server = build_server(client)
    tools = _tool_specs(await server.list_tools())
    if spec.tools is not None:
        published = {t.name for t in tools}
        if not set(spec.tools) <= published:
            return WakeRecord(spec.id, "refused", "unknown_tool", 0)
        tools = [t for t in tools if t.name in spec.tools]
    visible = frozenset(t.name for t in tools)

    me = await _execute(server, None, ToolCall(id="context:me", name="whoami"))
    if me.is_error:
        return WakeRecord(spec.id, "refused", "no_identity", 0)
    transcript: list[Message] = [
        Message(role="system", content=spec.charter),
        Message(role="user", content=json.dumps(
            {"me": json.loads(me.content), "input": workflow_input}, sort_keys=True)),
    ]

    made = 0
    while True:
        response = provider.complete(
            CompletionRequest(messages=list(transcript), tools=tools, model=spec.model))
        transcript.append(Message(role="assistant", content=response.content,
                                  tool_calls=response.tool_calls))
        batch = response.tool_calls
        if not batch:
            return WakeRecord(spec.id, "done", "done", made, tuple(transcript))
        if made + len(batch) > max_tool_calls:
            return WakeRecord(spec.id, "tool_budget", "tool_budget", made, tuple(transcript))
        if not decide_batch().allowed:
            return WakeRecord(spec.id, "halted", "halted", made, tuple(transcript))
        for call in batch:
            transcript.append(await _execute(server, visible, call))
        made += len(batch)


async def _execute(server: Any, visible: frozenset[str] | None, call: ToolCall) -> Message:
    """Run one call through the MCP tool; every failure becomes a tool error message.

    ``visible=None`` is the adapter's own read (``whoami`` for the context).
    """
    def error(text: str) -> Message:
        return Message(role="tool", content=text, tool_call_id=call.id, is_error=True)

    if visible is not None and call.name not in visible:
        return error(f"tool {call.name!r} is not in your tool list")
    try:
        result = await server.call_tool(call.name, dict(call.arguments))
    except ToolError as exc:
        return error(str(exc))
    texts = [b.text for b in getattr(result, "content", None) or []
             if getattr(b, "type", "") == "text"]
    if getattr(result, "is_error", True) is not False:
        return error("\n".join(texts) or "the tool failed")
    return Message(role="tool", content=_payload(texts), tool_call_id=call.id)


def _payload(texts: list[str]) -> str:
    """One JSON document per result. MCP splits a list result into one block per item."""
    try:
        parsed = [json.loads(t) for t in texts]
    except ValueError:
        return json.dumps("\n".join(texts))
    return json.dumps(parsed[0] if len(parsed) == 1 else parsed, sort_keys=True)
