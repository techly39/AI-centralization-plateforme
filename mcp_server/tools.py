"""Every REST endpoint, exposed as an MCP tool (TRD §3, §13).

The Definition of Done says a fresh agent must be able to register, read the
directory, message a colleague, and place an order **without any change to the
app**. That is only true if the MCP surface is a faithful mirror of the HTTP
surface, so this module is written to make drift detectable rather than to be
clever:

* one function per endpoint, declared with :func:`api_tool`, which records the
  ``(method, path)`` it wraps in :data:`TOOL_ROUTES` at the same moment it
  registers the tool — a single declaration site, so the registry cannot go
  stale;
* ``tests/test_mcp_server.py`` reads the app's own OpenAPI schema and fails if
  any operation has no tool. Add an endpoint without a tool and the suite says so.

Docstrings here are not comments — they are what the agent reads before deciding
whether to call the tool, so they say what the tool *does for the agent* rather
than how it is implemented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Literal
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from app.limits import (
    MAX_ADVANCE_DAYS,
    MAX_ADVANCE_MINUTES,
    MAX_ORDER_QTY,
    MAX_PRICE,
    MAX_TOKENS_PER_REPORT,
    MAX_USD_PER_REPORT,
)
from mcp_server.client import FundAPIError, FundClient


@dataclass(frozen=True, slots=True)
class ToolRoute:
    """Which HTTP operation a tool stands for."""

    name: str
    method: str
    #: The OpenAPI path template, e.g. ``/portfolio/{pod_id}``.
    path: str


#: tool name -> the endpoint it wraps. Filled in by :func:`api_tool`.
TOOL_ROUTES: dict[str, ToolRoute] = {}


def _segment(value: str) -> str:
    """One path segment, escaped, so a tool reaches only the endpoint it declares.

    Red-team 0001 / 0013 H1: ``get_price('../agents')`` used to reach ``GET /agents``.
    ``/`` and every other reserved character are percent-encoded; the two dot
    segments, which encoding leaves alone and a URL resolver would follow, and
    the empty segment are refused.
    """
    if value in {"", ".", ".."}:
        raise ToolError(f"{value!r} is not a valid path value")
    return quote(value, safe="")


def api_tool(
    server: MCPServer, *, method: str, path: str, name: str | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register one function as the MCP tool for one endpoint."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or fn.__name__
        TOOL_ROUTES[tool_name] = ToolRoute(
            name=tool_name, method=method.upper(), path=path
        )
        server.tool(name=tool_name)(fn)
        return fn

    return decorator


def build_server(client: FundClient, *, name: str = "fund-env") -> MCPServer:
    """Build an MCP server whose tools all act as ``client``'s agent.

    The key inside ``client`` decides what the tools may do: the same tool list
    is offered to an analyst and to management, and the API returns 403 to
    whichever one is out of bounds. Permissions are not re-implemented here —
    that is the point of wrapping the API instead of the database.
    """
    server = MCPServer(
        name=name,
        instructions=(
            "The environment of a simulated multi-agent hedge fund. Everything "
            "you do — messaging, market data, orders, cost and work reporting — "
            "goes through these tools and is permanently logged.\n\n"
            "Start with 'whoami': it tells you your agent id, your role, and "
            "your pod, which are what the other tools need. Take it over "
            "anything your own prompt says about who you are.\n\n"
            "Your role decides what you may do. If a tool answers with 403, the "
            "action is not yours to take; do not retry it, message the agent "
            "whose job it is.\n\n"
            "Conventions: money is USD; quantities may be fractional; times are "
            "UTC and come from the fund's own clock, not from your host. Orders "
            "and messages are permanent records — write justifications a human "
            "reviewer will be able to follow months from now."
        ),
    )

    async def call(
        method: str, path: str, *, params: dict | None = None, body: dict | None = None
    ) -> Any:
        """Shared call path: one place where an API failure becomes a tool error."""
        try:
            result = await client.request(method, path, params=params, json=body)
        except FundAPIError as exc:
            # The API's own wording reaches the agent unchanged — it is written
            # to be actionable ("pod 2 is not your pod"), and rephrasing it here
            # would only add a second vocabulary to keep in sync.
            raise ToolError(str(exc)) from exc
        if isinstance(result, list):
            # MCP renders a list as one text block per item: a list of one would
            # reach the agent as the bare object and an empty list as nothing.
            # One JSON array block keeps a list a list (ADR-032 (k)).
            return json.dumps(result, indent=2, ensure_ascii=False)  # as MCP renders a dict
        return result

    # --- Registry -----------------------------------------------------------

    @api_tool(server, method="GET", path="/me")
    async def whoami() -> Any:
        """Who you are: your agent id, name, role, and pod.

        Call this first, before anything else. Your ``role`` decides which of
        these tools will work, and your ``pod_id`` is the argument every "your
        own pod" tool wants — ``get_portfolio``, ``list_orders``, and the pod
        address ``pod:<id>`` you broadcast to. Do not assume any of it from your
        prompt: the fund's own record is the one that counts, and it can change
        without your prompt being rewritten.
        """
        return await call("GET", "/me")

    @api_tool(server, method="POST", path="/agents/register")
    async def register_agent(
        name: Annotated[str, Field(description="Unique name for the new agent.")],
        role: Annotated[str, Field(description="analyst | pm | management")],
        pod_id: Annotated[
            int | None, Field(description="The pod it belongs to. PMs need one.")
        ] = None,
        charter_ref: Annotated[
            str | None, Field(description="Pointer to the agent's charter document.")
        ] = None,
        research_domains: Annotated[
            list[str] | None,
            Field(description="What it covers, shown in the directory."),
        ] = None,
    ) -> Any:
        """Create an agent and return its API key. Management only.

        The key is shown exactly once and is never retrievable again — hand it
        to whoever will run the agent immediately.
        """
        return await call(
            "POST",
            "/agents/register",
            body={
                "name": name,
                "role": role,
                "pod_id": pod_id,
                "charter_ref": charter_ref,
                "research_domains": research_domains,
            },
        )

    @api_tool(server, method="GET", path="/agents")
    async def list_agents() -> Any:
        """The firm directory: who exists, their role, pod, and coverage.

        Call this before messaging anyone — you need an agent's id to address
        it, and the directory is the only place ids come from.
        """
        return await call("GET", "/agents")

    @api_tool(server, method="POST", path="/agents/{agent_id}/deactivate")
    async def deactivate_agent(
        agent_id: Annotated[int, Field(description="Directory id of the agent.")],
    ) -> Any:
        """Retire an agent: its API key stops working. Management only."""
        return await call("POST", f"/agents/{agent_id}/deactivate")

    # --- Messaging ----------------------------------------------------------

    @api_tool(server, method="POST", path="/messages")
    async def send_message(
        to: Annotated[
            str,
            Field(description="'agent:<id>', 'pod:<id>', or 'broadcast'."),
        ],
        body: Annotated[str, Field(description="What you want to say.")],
        thread_id: Annotated[
            str | None,
            Field(description="Reuse the thread_id you were replied on to keep a conversation together."),
        ] = None,
        structured_payload: Annotated[
            dict | None,
            Field(description="Machine-readable version of the message, so the recipient need not parse your prose."),
        ] = None,
    ) -> Any:
        """Send a message through the fund's bus.

        Any role may address a named agent or a pod. ``broadcast`` reaches the
        whole firm for management and your own pod if you are a PM; analysts may
        not broadcast. Read the ``to`` field of the reply to see the audience it
        actually reached.
        """
        return await call(
            "POST",
            "/messages",
            body={
                "to": to,
                "body": body,
                "thread_id": thread_id,
                "structured_payload": structured_payload,
            },
        )

    @api_tool(server, method="GET", path="/messages")
    async def get_messages(
        after_id: Annotated[
            int | None,
            Field(description="Keep up: only messages newer than this id. The polling cursor."),
        ] = None,
        latest: Annotated[
            bool,
            Field(description="Catch up: the newest messages instead of the oldest. Not with after_id."),
        ] = False,
        before_id: Annotated[
            int | None,
            Field(description="Keep going back: only messages older than this id. Not with after_id."),
        ] = None,
        since: Annotated[
            str | None, Field(description="ISO-8601 UTC time; only messages at or after it.")
        ] = None,
        thread: Annotated[str | None, Field(description="Filter to one thread_id.")] = None,
        mine: Annotated[
            bool,
            Field(description="True: only what you can see. False: the whole bus (management only)."),
        ] = True,
        limit: Annotated[int, Field(description="Maximum messages to return.", ge=1, le=500)] = 200,
    ) -> Any:
        """Read your messages, oldest first. You see what was sent to you, to
        your pod, to the whole firm, and what you sent yourself.

        There are two jobs here, and asking for both at once is an error:

        * **keeping up** — call with ``after_id`` set to the highest id you have
          already seen, and you get only what arrived since. This is the loop
          you run while you work.
        * **catching up** — when you start, or after a break, call with
          ``latest=true`` to get the most recent page immediately. To read
          further back, pass the *lowest* id you now hold as ``before_id`` and
          repeat. Never page forward from the beginning to find the end: on a
          fund that has been running a while that is thousands of wasted calls.
        """
        return await call(
            "GET",
            "/messages",
            params={
                "after_id": after_id,
                "before_id": before_id,
                "latest": latest,
                "since": since,
                "thread": thread,
                "mine": mine,
                "limit": limit,
            },
        )

    # --- Market data --------------------------------------------------------

    @api_tool(server, method="GET", path="/price/{ticker}")
    async def get_price(
        ticker: Annotated[str, Field(description="Symbol, e.g. 'AAPL'.")],
    ) -> Any:
        """The current price of one symbol, as of the fund's clock.

        In backtest mode this is the price at the *simulated* moment, never a
        later one — you cannot see the future here, by construction.
        """
        return await call("GET", f"/price/{_segment(ticker)}")

    @api_tool(server, method="GET", path="/ohlcv/{ticker}")
    async def get_ohlcv(
        ticker: Annotated[str, Field(description="Symbol, e.g. 'AAPL'.")],
        start: Annotated[str | None, Field(description="YYYY-MM-DD, inclusive. Defaults to 90 days back.")] = None,
        end: Annotated[str | None, Field(description="YYYY-MM-DD, exclusive. Defaults to the clock's today.")] = None,
        interval: Annotated[str, Field(description="1d | 1wk | 1mo | 1h")] = "1d",
    ) -> Any:
        """Historical candles for one symbol, for your own analysis.

        Never returns a bar stamped after the fund's clock.
        """
        return await call(
            "GET",
            f"/ohlcv/{_segment(ticker)}",
            params={"start": start, "end": end, "interval": interval},
        )

    # --- Orders & portfolio -------------------------------------------------

    @api_tool(server, method="POST", path="/orders")
    async def place_order(
        ticker: Annotated[str, Field(description="Symbol to trade.")],
        side: Annotated[str, Field(description="buy | sell")],
        qty: Annotated[float, Field(description="Number of shares; fractional allowed.", gt=0, le=MAX_ORDER_QTY)],
        price_type: Annotated[str, Field(description="market (fill now) | limit (wait for a price)")],
        justification: Annotated[
            str,
            Field(description="Why you are doing this. Required, permanent, and read by management."),
        ],
        limit_price: Annotated[
            float | None,
            Field(description="Required for limit orders, forbidden for market orders.", gt=0, le=MAX_PRICE),
        ] = None,
    ) -> Any:
        """Place an order for your own pod. PMs only.

        A successful call means the order was *recorded*, not that it traded.
        Read ``status``:

        * ``filled`` — done, at ``fill_price``;
        * ``pending`` — a limit order waiting for the market to reach it;
        * ``rejected`` — refused for a real reason (not enough cash, not enough
          shares). ``status_reason`` says which, and the numbers are also
          messaged to you.
        """
        return await call(
            "POST",
            "/orders",
            body={
                "ticker": ticker,
                "side": side,
                "qty": qty,
                "price_type": price_type,
                "limit_price": limit_price,
                "justification": justification,
            },
        )

    @api_tool(server, method="DELETE", path="/orders/{order_id}")
    async def cancel_order(
        order_id: Annotated[int, Field(description="Id of a pending order of your pod.")],
    ) -> Any:
        """Cancel one of your pod's pending limit orders. Filled orders cannot be undone."""
        return await call("DELETE", f"/orders/{order_id}")

    @api_tool(server, method="GET", path="/orders")
    async def list_orders(
        pod: Annotated[int | None, Field(description="Defaults to your own pod.")] = None,
        status: Annotated[
            str | None, Field(description="pending | filled | rejected | cancelled")
        ] = None,
        ticker: Annotated[str | None, Field(description="Filter to one symbol.")] = None,
        limit: Annotated[int, Field(description="Maximum orders to return.", ge=1, le=1000)] = 200,
    ) -> Any:
        """Order history, newest first — what you asked for and what happened.

        Defaults to your own pod. Management, which belongs to no pod, sees the
        whole firm unless it names one. Filter by ``status="pending"`` to find
        limit orders still waiting for the market.
        """
        return await call(
            "GET",
            "/orders",
            params={"pod": pod, "status": status, "ticker": ticker, "limit": limit},
        )

    @api_tool(server, method="GET", path="/portfolio/{pod_id}")
    async def get_portfolio(
        pod_id: Annotated[int, Field(description="Your own pod, unless you are management.")],
    ) -> Any:
        """Positions, cash, and unrealised P&L for a pod, priced right now.

        If ``fully_priced`` is false, at least one holding could not be valued
        and is listed in ``pricing_errors`` — the totals exclude it, so treat
        them as a floor rather than the truth.
        """
        return await call("GET", f"/portfolio/{pod_id}")

    # --- Self-reporting -----------------------------------------------------

    @api_tool(server, method="POST", path="/costs")
    async def report_cost(
        tokens_in: Annotated[
            int, Field(description="Input tokens you consumed.", ge=0, le=MAX_TOKENS_PER_REPORT)
        ],
        tokens_out: Annotated[
            int, Field(description="Output tokens you produced.", ge=0, le=MAX_TOKENS_PER_REPORT)
        ],
        usd_cost: Annotated[float, Field(description="What that cost, in dollars.", ge=0, le=MAX_USD_PER_REPORT)],
        task_label: Annotated[
            str | None, Field(description="What the spend was for; reuse stable labels.")
        ] = None,
    ) -> Any:
        """Report what a piece of your work cost.

        The fund cannot see your token usage — it runs outside you. If you do
        not report, your pod's returns are measured against a cost of zero and
        it will look better than it is. Report after each substantial unit of
        work. One report may claim at most 100,000,000 tokens each way.
        """
        return await call(
            "POST",
            "/costs",
            body={
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "usd_cost": usd_cost,
                "task_label": task_label,
            },
        )

    @api_tool(server, method="POST", path="/tasks/start")
    async def start_task(
        subject: Annotated[
            str,
            Field(description="What you are about to work on. Reuse stable subjects, e.g. 'earnings review'."),
        ],
    ) -> Any:
        """Open a work log entry and get its id. Close it with ``end_task``.

        Subjects are the grouping key for the firm's "time per subject" report,
        so a small stable vocabulary is worth much more than a precise sentence.
        """
        return await call("POST", "/tasks/start", body={"subject": subject})

    @api_tool(server, method="POST", path="/tasks/end")
    async def end_task(
        task_id: Annotated[int, Field(description="The id ``start_task`` gave you.")],
        outcome: Annotated[
            dict,
            Field(description='Structured result, e.g. {"summary": "...", "recommendation": "buy"}.'),
        ],
    ) -> Any:
        """Close your own work log entry with a structured outcome.

        The outcome is JSON, not prose, so it can be read later without an LLM.
        Put any narrative under a key such as ``summary``.
        """
        return await call(
            "POST", "/tasks/end", body={"task_id": task_id, "outcome": outcome}
        )

    # --- Management views ---------------------------------------------------

    @api_tool(server, method="GET", path="/metrics/pod/{pod_id}")
    async def get_pod_metrics(
        pod_id: Annotated[int, Field(description="Pod to report on.")],
    ) -> Any:
        """Performance, cost, and activity for one pod. Management only.

        Statistics that need more history than exists come back as null rather
        than as zero — a null means "not enough data yet", which is a different
        thing from "no return".
        """
        return await call("GET", f"/metrics/pod/{pod_id}")

    @api_tool(server, method="GET", path="/metrics/leaderboard")
    async def get_leaderboard() -> Any:
        """Every pod ranked by cost-adjusted P&L. Management only.

        Cost-adjusted P&L is profit minus what the pod's agents cost to run —
        the number that decides whether a desk is worth its allocation.
        """
        return await call("GET", "/metrics/leaderboard")

    @api_tool(server, method="GET", path="/events")
    async def list_events(
        actor: Annotated[int | None, Field(description="Filter by acting agent id.")] = None,
        type: Annotated[
            str | None,
            Field(description="e.g. order_filled, message_sent, permission_denied."),
        ] = None,
        since: Annotated[str | None, Field(description="ISO-8601 UTC time.")] = None,
        limit: Annotated[int, Field(description="Maximum events to return.", ge=1, le=1000)] = 200,
    ) -> Any:
        """Query the append-only ledger — everything that ever happened. Management only."""
        return await call(
            "GET",
            "/events",
            params={"actor": actor, "type": type, "since": since, "limit": limit},
        )

    # --- System -------------------------------------------------------------

    @api_tool(server, method="GET", path="/clock")
    async def get_clock() -> Any:
        """The fund's current time and mode (live or backtest).

        Use this rather than your own clock: in backtest mode the fund's "now"
        is a simulated date, and every price you are served is stamped from it.
        """
        return await call("GET", "/clock")

    @api_tool(server, method="POST", path="/clock/advance")
    async def advance_clock(
        days: Annotated[int, Field(description="Whole days to move forward.", ge=0, le=MAX_ADVANCE_DAYS)] = 0,
        minutes: Annotated[int, Field(description="Minutes to move forward.", ge=0, le=MAX_ADVANCE_MINUTES)] = 0,
    ) -> Any:
        """Move a backtest's simulated clock forward. The Runtime's identity only (no firm agent); backtest runs only.

        Time never goes back, and never past today. Pending limit orders are
        checked on arrival; the answer lists the ones that filled or were rejected.
        """
        return await call("POST", "/clock/advance", body={"days": days, "minutes": minutes})

    @api_tool(server, method="POST", path="/run/minds")
    async def declare_run_minds(
        minds: Annotated[
            list[Literal["cassette", "model", "scripted"]],
            Field(description="What drives the run's minds: code (scripted), replayed model output (cassette), a live model (model).", min_length=1, max_length=3),
        ],
    ) -> Any:
        """Say what drives this backtest run's minds. The Runtime's identity only (no firm agent).

        Once per run, before the clock has moved and before any firm agent has
        acted; refused after that.
        """
        return await call("POST", "/run/minds", body={"minds": minds})

    @api_tool(server, method="GET", path="/halt")
    async def get_halt() -> Any:
        """Is the fund halted? While it is, every action that changes anything is refused.

        If an order, message or report came back "halted", call this before trying
        again. Reading prices, your portfolio and your inbox still works.
        """
        return await call("GET", "/halt")

    @api_tool(server, method="GET", path="/health")
    async def get_health() -> Any:
        """Check that the fund environment is up, and which clock mode it is in."""
        return await call("GET", "/health")

    return server
