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

* the wake gate before anything else; a spec with ``wake_policy: never`` and a
  workflow input that is not plain JSON are refused; the mind is built from the
  spec by :mod:`runtime.registry`, never handed in;
* the key must be the agent the spec describes: ``/me``'s name, role and pod must
  equal the spec's, or the wake is refused (``identity_mismatch``);
* a reply is recorded only if its call ids are new in this wake and its
  arguments are plain JSON; otherwise the wake ends ``error``/``bad_reply``;
* **HALT is re-read before every model turn and before every tool call** (03 §3
  asks for every batch; Art. 5.2 allows nothing beyond the current tool call);
* a per-wake **tool-call budget**; a batch that would pass it does not run;
* the mind is shown deep copies, and its reply is copied on receipt, so nothing
  a mind holds can rewrite the transcript afterwards.

A wake ends when the mind replies with no tool calls (``done``), or with
``halted``, ``tool_budget``, ``refused`` or ``error`` (the provider raised or
returned something that is not a :class:`CompletionResponse`). Every turn ends
in one of those or in at least one tool call, so the budget bounds the loop. An
``Exception`` from the provider ends the wake with a record; one from a tool
function becomes a tool error for the mind and is counted in the record's
``tool_failures``, so a tool bug is not mistaken for physics refusing. The
adapter's own bugs still raise. Each model turn asked leaves an :class:`Exchange` (R-4a);
:mod:`runtime.cassette` writes the record to a file.
There is no wall-clock timeout yet: a script that never returns hangs its wake.
Timeouts arrive with the first provider that can hang on the network (R-6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from mcp_server.client import FundClient
from mcp_server.tools import build_server
from runtime.gate import decide_batch, decide_wake
from runtime.cassette import request_sha256, tools_sha256
from runtime.metering import Meter
from runtime.providers import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from runtime.registry import ProviderRefused, build_provider
from runtime.replay import Tape
from runtime.spec import AgentSpec

#: Tool calls one wake may make unless the caller says otherwise.
DEFAULT_MAX_TOOL_CALLS = 64


@dataclass(frozen=True)
class Exchange:
    """One model turn the mind was asked for (R-4a). The request is not stored: it is the
    transcript before the ``seq``-th assistant message plus the wake's tools and
    ``spec.model``, and ``request_sha256`` names it. The response is that assistant message."""
    seq: int
    #: Taken from the request *before* the mind saw it (a mind can edit what it is handed).
    request_sha256: str
    #: What the provider said it used. ``None``: the reply was not accepted (the provider
    #: raised, or ``bad_reply``), so no assistant message answers this exchange.
    usage: Usage | None


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
    #: Calls whose tool function itself raised (a bug in the tool layer), as
    #: opposed to physics refusing or the App being unreachable (both a
    #: ``ToolError``): all reach the mind as tool errors, so the record keeps
    #: them apart (R-2 re-audit NOTE 1).
    tool_failures: int = 0
    #: One per model turn asked, in order (R-4a). Empty for a wake refused before any turn.
    exchanges: tuple[Exchange, ...] = ()
    #: The model the wake asked (``spec.model``); ``None``: a scripted mind, or the wake was
    #: refused before any turn (cassette v2, M-002).
    model: str | None = None
    #: ``cassette.tools_sha256`` of the tools every request of the wake carried; ``None`` only
    #: for a wake refused before its tools were listed.
    tools_sha256: str | None = None


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
    tape: Tape | None = None,
    meter: Meter | None = None,
) -> WakeRecord:
    """Wake the mind ``spec`` describes once, acting as ``client``'s agent. ``tape`` is the
    recording a ``cassette`` mind replays (R-4b); the registry builds the mind from it.
    ``meter`` is the mind's own key at the provisioner, for a ``fake-metered`` mind (ADR-044)."""
    if type(max_tool_calls) is not int or max_tool_calls < 0:
        raise ValueError("max_tool_calls is a non-negative int")
    if spec.adapter != "native":
        return WakeRecord(spec.id, "refused", "wrong_adapter", 0)
    if spec.wake_policy == "never":  # red-team 0013 H8: a spec kept on file stays asleep
        return WakeRecord(spec.id, "refused", "wake_policy_never", 0)
    decision = decide_wake(spec.provider, spec.adapter, metered=meter is not None)
    if not decision.allowed:
        return WakeRecord(spec.id, "refused", decision.reason, 0)
    try:
        provider = build_provider(spec, tape, meter)
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
    tools_digest = tools_sha256(tools)

    if type(workflow_input) is not dict or not _is_json(workflow_input):
        return WakeRecord(spec.id, "refused", "bad_input", 0)  # red-team 0013 H7

    me = await _execute(server, None, ToolCall(id="context:me", name="whoami"))
    if me.is_error:
        return WakeRecord(spec.id, "refused", "no_identity", 0)
    identity = json.loads(me.content)
    # Red-team 0013 H2/H3: the key must be the agent the spec describes — its
    # name too, since agents are provisioned from specs (ADR-032 (n)).
    if (identity.get("name"), identity.get("role"), identity.get("pod_id")) != (
            spec.name, spec.role, spec.pod):
        return WakeRecord(spec.id, "refused", "identity_mismatch", 0)
    transcript: list[Message] = [
        Message(role="system", content=spec.charter),
        Message(role="user", content=json.dumps(
            {"me": identity, "input": workflow_input}, sort_keys=True)),
    ]

    made = 0
    used_ids: set[str] = set()
    failures: list[str] = []
    exchanges: list[Exchange] = []

    def end(ended: str, reason: str | None = None) -> WakeRecord:
        return WakeRecord(spec.id, ended, reason or ended, made, tuple(transcript),
                          len(failures), tuple(exchanges), spec.model, tools_digest)

    while True:
        if not decide_batch().allowed:  # no thinking after HALT: R-6's think costs money
            return end("halted")
        # The mind gets copies: nothing it holds can rewrite the record (audit c22 WARN 2).
        request = CompletionRequest(messages=[m.model_copy(deep=True) for m in transcript],
                                    tools=[t.model_copy(deep=True) for t in tools],
                                    model=spec.model)
        digest = request_sha256(request)  # R-4a: before the mind can touch what it was handed
        seq = len(exchanges)
        try:
            response = provider.complete(request)
        except Exception as exc:  # a mind's crash is a recorded end (SystemExit still escapes)
            exchanges.append(Exchange(seq, digest, None))
            return end("error", f"provider_error:{type(exc).__name__}")
        # A reply enters the record only as a copy, only if it is plain JSON, and only if
        # every call id is new in this wake (red-team 0013 H4–H6). Otherwise the wake ends
        # here and the reply is not recorded: a record must always serialise.
        try:
            if type(response) is not CompletionResponse:
                raise TypeError(type(response).__name__)
            response = response.model_copy(deep=True)
            ids = [c.id for c in response.tool_calls]
            if len(set(ids)) != len(ids) or used_ids & set(ids):
                raise ValueError("a tool-call id is used twice")
            if not _is_json(response.model_dump()):  # the whole reply, not only arguments
                raise ValueError("the reply is not plain JSON")
        except Exception:
            exchanges.append(Exchange(seq, digest, None))
            return end("error", "bad_reply")
        exchanges.append(Exchange(seq, digest, response.usage))
        used_ids |= set(ids)
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
            transcript.append(await _execute(server, visible, call, failures))
            made += 1


async def _execute(server: Any, visible: frozenset[str] | None, call: ToolCall,
                   failures: list[str] | None = None) -> Message:
    """Run one call through the MCP tool; a refusal, a tool error or an exception
    from the tool function becomes a tool error message. The id of a call whose
    tool function raised is also appended to ``failures``.

    ``visible=None`` is the adapter's own read (``whoami`` for the context).
    """
    def error(text: str) -> Message:
        return Message(role="tool", content=text, tool_call_id=call.id, is_error=True)

    if visible is not None and call.name not in visible:
        return error(f"tool {call.name!r} is not in your tool list")
    try:
        result = await server.call_tool(call.name, dict(call.arguments))
    except ToolError as exc:
        # The MCP server wraps whatever the tool function raised in a ToolError. A
        # ToolError under it is the tool speaking (physics refused, the App was
        # unreachable); a ValidationError is the mind's bad arguments; no cause is
        # an unknown tool. Anything else is a bug under the tool.
        if exc.__cause__ is not None and not isinstance(exc.__cause__, (ToolError, ValidationError)):
            if failures is not None:
                failures.append(call.id)
        return error(str(exc))
    except Exception as exc:  # a bug in the server itself: the mind is told, the wake goes on
        if failures is not None:
            failures.append(call.id)
        return error(f"the tool failed: {type(exc).__name__}")
    texts = [b.text for b in getattr(result, "content", None) or []
             if getattr(b, "type", "") == "text"]
    if getattr(result, "is_error", True) is not False:
        return error("\n".join(texts) or "the tool failed")
    return Message(role="tool", content=_payload(texts), tool_call_id=call.id)


def _is_json(value: Any) -> bool:
    """True if ``value`` survives a strict JSON round trip unchanged (no NaN, no
    tuples, no non-string keys, no objects), so a record holding it serialises exactly."""
    try:
        return json.loads(json.dumps(value, allow_nan=False)) == value
    except (TypeError, ValueError, RecursionError):
        return False


def _payload(texts: list[str]) -> str:
    """One JSON document per result. ``build_server``'s tools answer in one block (a
    list as one array, ADR-032 (k)); several blocks from any other tool are joined
    as a list."""
    try:
        parsed = [json.loads(t) for t in texts]
    except ValueError:
        return json.dumps("\n".join(texts))
    return json.dumps(parsed[0] if len(parsed) == 1 else parsed, sort_keys=True)
