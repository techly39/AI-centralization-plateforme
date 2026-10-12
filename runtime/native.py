"""The ``native`` adapter: one wake of one mind over the published tools (ADR-032 (2), R-2).

A mind acts only through the tool list :func:`mcp_server.build_server` publishes
— the list an OpenClaw agent will get through the same server (R-7), which is how
"same tools for every adapter" is meant to hold. Each call runs the MCP tool function, which calls the API
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
* **HALT is re-read before every model turn and before every tool call** (03 §3
  asks for every batch; Art. 5.2 allows nothing beyond the current tool call);
* a per-wake **tool-call budget**; a batch that would pass it does not run;
* the mind is shown deep copies, and its reply is copied on receipt, so nothing
  a mind holds can rewrite the transcript afterwards.

A wake ends when the mind replies with no tool calls (``done``), or with
``halted``, ``tool_budget``, ``refused`` or ``error`` (the provider raised or
returned something that is not a :class:`CompletionResponse`). Every turn ends
in one of those or in at least one tool call, so the budget bounds the loop. An
exception from the provider or a tool function becomes a record or a tool error;
the adapter's own bugs still raise. R-4 writes the record to a cassette.
There is no wall-clock timeout yet: a script that never returns hangs its wake.
Timeouts arrive with the first provider that can hang on the network (R-6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.client import FundClient
from mcp_server.tools import build_server
from runtime.gate import decide_batch, decide_wake
from runtime.providers import CompletionRequest, CompletionResponse, Message, ToolCall, ToolSpec
from runtime.registry import ProviderRefused, build_provider
from runtime.spec import AgentSpec

#: Tool calls one wake may make unless the caller says otherwise.
DEFAULT_MAX_TOOL_CALLS = 64


@dataclass(frozen=True)
class WakeRecord:
    spec_id: str
    #: ``done`` | ``halted`` | ``tool_budget`` | ``refused`` | ``error``
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

    def end(ended: str, reason: str | None = None) -> WakeRecord:
        return WakeRecord(spec.id, ended, reason or ended, made, tuple(transcript))

    while True:
        if not decide_batch().allowed:  # no thinking after HALT: R-6's think costs money
            return end("halted")
        # The mind gets copies: nothing it holds can rewrite the record (audit c22 WARN 2).
        request = CompletionRequest(messages=[m.model_copy(deep=True) for m in transcript],
                                    tools=[t.model_copy(deep=True) for t in tools],
                                    model=spec.model)
        try:
            response = provider.complete(request)
        except Exception as exc:  # a mind's crash is a recorded end, never a lost wake
            return end("error", f"provider_error:{type(exc).__name__}")
        if type(response) is not CompletionResponse:
            return end("error", "bad_reply")
        response = response.model_copy(deep=True)
        transcript.append(Message(role="assistant", content=response.content,
                                  tool_calls=response.tool_calls))
        batch = response.tool_calls
        if not batch:
            return end("done")
        if made + len(batch) > max_tool_calls:
            return end("tool_budget")
        for call in batch:
            # Art. 5.2: nothing beyond the current tool call — HALT is read before each one.
            if not decide_batch().allowed:
                return end("halted")
            transcript.append(await _execute(server, visible, call))
            made += 1


async def _execute(server: Any, visible: frozenset[str] | None, call: ToolCall) -> Message:
    """Run one call through the MCP tool; a refusal, a tool error or an exception
    from the tool function becomes a tool error message.

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
    except Exception as exc:  # e.g. the App unreachable: the mind is told, the wake goes on
        return error(f"the tool failed: {type(exc).__name__}")
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
