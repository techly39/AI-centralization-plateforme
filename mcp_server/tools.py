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
    KEY_REF_PATTERN,
    MAX_ID,
    MAX_METERED_USD_MICROS,
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


#: A strategy-v1 rule as a tool argument (app/strategy/rule.py is the law; the API validates it).
RuleArg = Annotated[dict, Field(description=(
    "A strategy-v1 rule, a JSON object: {\"universe\": [tickers, 2..50], \"signal\": "
    "\"momentum\" | \"mean_reversion\" | \"low_volatility\", \"lookback\": days 2..250, "
    "\"rebalance_every\": days 1..63, \"top_n\": names held, \"side\": \"long_only\" | "
    "\"long_short\", \"gross\": 0..2}. Every rebalance it ranks the universe by the signal "
    "and holds the top_n (and shorts the bottom top_n for long_short), equal weights."))]


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

    # --- Strategy science: research and pitches ------------------------------

    @api_tool(server, method="POST", path="/research/backtests")
    async def run_research_backtest(
        rule: RuleArg,
        start: Annotated[str | None, Field(description="YYYY-MM-DD. Default: a year before end.")] = None,
        end: Annotated[str | None, Field(description=(
            "YYYY-MM-DD, exclusive. Default and latest: the first held-out day (the most recent "
            "days are kept for judging pitches)."))] = None,
    ) -> Any:
        """Backtest a strategy rule on past data and get its numbers (Sharpe, return, drawdown,
        rank IC, predictions, turnover). Fees included.

        Every backtest is counted for your pod, forever: when your PM pitches, the deflated
        Sharpe is penalised by the number of things your pod tried. Test ideas, not noise.
        """
        return await call("POST", "/research/backtests",
                          body={"rule": rule, "start": start, "end": end})

    @api_tool(server, method="GET", path="/research/backtests")
    async def list_research_backtests(
        pod_id: Annotated[int | None, Field(description="Default: your own pod.", ge=1, le=MAX_ID)] = None,
    ) -> Any:
        """Every research backtest of your pod so far, oldest first, with its attempt number."""
        return await call("GET", "/research/backtests", params={"pod_id": pod_id})

    @api_tool(server, method="POST", path="/pitches")
    async def submit_pitch(
        hypothesis: Annotated[str, Field(description=(
            "The economic idea: why this edge exists and the mechanism behind it. Recorded and "
            "read by the firm; a correlation without a mechanism is not a hypothesis."))],
        data_needed: Annotated[str, Field(description="The data the strategy needs.")],
        team: Annotated[str, Field(description="The team you ask for, and why.")],
        budget_usd: Annotated[float, Field(description="Thinking budget you ask for, USD.", ge=0)],
        rule: RuleArg,
    ) -> Any:
        """Pitch a strategy for your pod. PMs only.

        The fund runs your rule on the held-out days (the most recent ones, which research could
        not backtest on) and the validation gates judge it: rank IC over many predictions,
        deflated Sharpe (penalised by every attempt your pod made, this pitch included),
        capacity (the capital at which trading costs eat half the edge) and correlation with
        the other pods' pitches. The answer says whether the strategy is eligible for capital.
        A pitch is itself an attempt.
        """
        return await call("POST", "/pitches", body={
            "hypothesis": hypothesis, "data_needed": data_needed, "team": team,
            "budget_usd": budget_usd, "rule": rule})

    @api_tool(server, method="GET", path="/pitches")
    async def list_pitches(
        pod_id: Annotated[int | None, Field(description="Default: your own pod.", ge=1, le=MAX_ID)] = None,
    ) -> Any:
        """Every pitch of your pod, oldest first, each with the gates' verdict."""
        return await call("GET", "/pitches", params={"pod_id": pod_id})

    @api_tool(server, method="GET", path="/pitches/{pitch_id}")
    async def get_pitch(
        pitch_id: Annotated[int, Field(description="The pitch's id.", ge=1, le=MAX_ID)],
    ) -> Any:
        """One pitch and its verdict, gate by gate."""
        return await call("GET", f"/pitches/{pitch_id}")

    # --- Capital: the centre's allocation and the risk ladder ------------------

    @api_tool(server, method="GET", path="/capital")
    async def get_capital(
        pod_id: Annotated[int | None, Field(description="Default: your own pod.", ge=1, le=MAX_ID)] = None,
    ) -> Any:
        """Your pod's capital from the centre, its risk-ladder stage and its latest score.

        An eligible pitch earns a seed; an algorithm re-weighs capital every few days by each pod's
        forward record (net of thinking cost, per unit of risk, cut for copying an older pod and for
        drawdown). The ladder, from your pod's high-water mark: 5% down → half your capital goes
        back; 7.5% → you may only sell; 10% → the pod is closed. The law is in the answer.
        """
        return await call("GET", "/capital", params={"pod_id": pod_id})

    @api_tool(server, method="GET", path="/mandate")
    async def get_mandate() -> Any:
        """Once your pod is seeded: the orders that bring your book to what your funded rule holds
        today (sells first, sized to your equity). Nothing is placed: send each with place_order.
        404 while your pod has no seed."""
        return await call("GET", "/mandate")

    # --- Generations: the lessons the firm keeps --------------------------------

    @api_tool(server, method="GET", path="/library")
    async def read_library() -> Any:
        """The firm's library of lessons, oldest first: every PM who was let go (its pod closed by
        the risk ladder, or no seed earned in its month), why, and what the pod tried: its
        pitches and the gates they failed, its research, its P&L, its thinking cost."""
        return await call("GET", "/library")

    # --- Vacancies: a closed pod, and the hire that replaces it ----------------

    @api_tool(server, method="GET", path="/vacancies")
    async def list_vacancies() -> Any:
        """Every vacancy: each pod the risk ladder closed, its post-mortem, the hire the hiring law
        names (pod, PM, model, budget), and whether it is filled. Management only."""
        return await call("GET", "/vacancies")

    @api_tool(server, method="GET", path="/vacancies/{vacancy_id}")
    async def get_vacancy(
        vacancy_id: Annotated[int, Field(description="The vacancy's id.", ge=1, le=MAX_ID)],
    ) -> Any:
        """One vacancy and the post-mortem of the pod it replaces: the dead pod's rule and
        hypothesis, its forward days, the drawdowns that closed it, the capital in and out. Yours
        to read if your pod was hired into it."""
        return await call("GET", f"/vacancies/{vacancy_id}")

    @api_tool(server, method="POST", path="/vacancies/{vacancy_id}/fill")
    async def fill_vacancy(
        vacancy_id: Annotated[int, Field(description="The open vacancy to fill.", ge=1, le=MAX_ID)],
    ) -> Any:
        """Hire as the law says: a new pod and a new PM. The answer holds the PM's key, once.
        Refused at the firm's pod limit. Needs the right to register agents."""
        return await call("POST", f"/vacancies/{vacancy_id}/fill")

    @api_tool(server, method="POST", path="/vacancies/{vacancy_id}/refuse")
    async def refuse_hire(
        vacancy_id: Annotated[int, Field(description="The open vacancy.", ge=1, le=MAX_ID)],
        reason: Annotated[str, Field(description="Why the hire cannot be made now.",
                                     min_length=1, max_length=200)],
    ) -> Any:
        """Refuse a hire for now (its thinking budget does not fit the cap). The vacancy stays
        open, the refusal is in the ledger. Needs the right to register agents."""
        return await call("POST", f"/vacancies/{vacancy_id}/refuse", body={"reason": reason})

    # --- Management: the firm's manager above the pods ------------------------

    @api_tool(server, method="GET", path="/board")
    async def read_board() -> Any:
        """The firm's board: every pod not closed (cash, positions, exposures, the capital the
        centre put in, its risk stage and drawdown, its thinking cost, last month's fitness, its
        design), the centre's cash and thinking cost, the open vacancies and the direction.
        Management only."""
        return await call("GET", "/board")

    @api_tool(server, method="POST", path="/vacancies/{vacancy_id}/pick")
    async def pick_hire(
        vacancy_id: Annotated[int, Field(description="The open vacancy (read_board, list_vacancies).",
                                         ge=1, le=MAX_ID)],
        candidate: Annotated[str, Field(description="A candidate's id from its list (c1, c2, ...).",
                                        min_length=1, max_length=16)],
        brief: Annotated[str, Field(description="What the new PM is told from you on its first "
                                                "morning.", max_length=2000)] = "",
    ) -> Any:
        """Pick who fills a freed place: one of the candidates its vacancy lists, once, before
        the morning it is filled. If you do not pick, the law's default (c1) is hired. You never
        hire, fire or move capital yourself. The manager only."""
        return await call("POST", f"/vacancies/{vacancy_id}/pick",
                          body={"candidate": candidate, "brief": brief})

    @api_tool(server, method="GET", path="/direction")
    async def get_direction() -> Any:
        """The firm's direction, as its manager last wrote it (null while none is written)."""
        return await call("GET", "/direction")

    @api_tool(server, method="POST", path="/direction")
    async def set_direction(
        text: Annotated[str, Field(description="The firm's direction, in your words: every PM "
                                               "reads it.", min_length=1, max_length=2000)],
    ) -> Any:
        """Write the firm's direction: every PM reads it in its capital view. The manager only."""
        return await call("POST", "/direction", body={"text": text})

    # --- Data: the world's news, handed by role ---------------------------------

    @api_tool(server, method="GET", path="/headlines")
    async def read_headlines(
        days: Annotated[int, Field(description="The last days whose news is out: 1 = yesterday's.",
                                   ge=1, le=31)] = 3,
        ticker: Annotated[str | None, Field(description="Only the headlines about one ticker.",
                                            max_length=16)] = None,
    ) -> Any:
        """The world's headlines, oldest first: about one company or the whole market. A day's
        news is out at its close, with its prices. Only for a mind given the headlines right
        (get_data_rights)."""
        return await call("GET", "/headlines", params={"days": days, "ticker": ticker})

    @api_tool(server, method="GET", path="/reports")
    async def read_reports(
        days: Annotated[int, Field(description="The last days whose reports are out (a quarter "
                                               "is 91).", ge=1, le=400)] = 91,
        ticker: Annotated[str | None, Field(description="Only one company's reports.",
                                            max_length=16)] = None,
    ) -> Any:
        """Companies' quarterly reports, oldest first: revenue, earnings per share against what
        was expected, guidance. A day's reports are out at its close. Only for a mind given the
        company right (get_data_rights)."""
        return await call("GET", "/reports", params={"days": days, "ticker": ticker})

    @api_tool(server, method="GET", path="/data/rights")
    async def get_data_rights() -> Any:
        """What you may read: prices always; headlines and company reports only if granted."""
        return await call("GET", "/data/rights")

    # --- Debate: a pitch argued before its seed ---------------------------------

    @api_tool(server, method="GET", path="/debates")
    async def read_debates(
        status: Annotated[Literal["open", "all"], Field(
            description="open: those still argued; all: every one.")] = "open",
    ) -> Any:
        """The pitches argued before their seed (yours: your own pod's), oldest first: the pitch
        (hypothesis, rule, the gates' numbers), the day its debate closes, the thread, the
        manager's verdict, what the centre did."""
        return await call("GET", "/debates", params={"status": status})

    @api_tool(server, method="GET", path="/debates/{pitch_id}")
    async def read_debate(
        pitch_id: Annotated[int, Field(description="The pitch in debate.", ge=1, le=MAX_ID)],
    ) -> Any:
        """One pitch's debate: the pitch, its thread, the verdict."""
        return await call("GET", f"/debates/{pitch_id}")

    @api_tool(server, method="POST", path="/debates/{pitch_id}/argue")
    async def argue_pitch(
        pitch_id: Annotated[int, Field(description="The pitch in debate.", ge=1, le=MAX_ID)],
        text: Annotated[str, Field(description="Your argument: everyone in the debate reads it.",
                                   min_length=1, max_length=2000)],
    ) -> Any:
        """Write in a pitch's debate thread while it is open (a reviewer in any; a PM in its own
        pod's). At most five posts each."""
        return await call("POST", f"/debates/{pitch_id}/argue", body={"text": text})

    @api_tool(server, method="POST", path="/debates/{pitch_id}/verdict")
    async def rule_pitch(
        pitch_id: Annotated[int, Field(description="The pitch in debate.", ge=1, le=MAX_ID)],
        verdict: Annotated[Literal["seed", "hold"], Field(
            description="seed: the law's seed is paid the next morning; hold: the seed is "
                        "refused and the PM reads your reason.")],
        reason: Annotated[str, Field(description="Why (required for a hold): the PM reads it.",
                                     max_length=1000)] = "",
    ) -> Any:
        """Rule once on a pitch in debate, while it is open. No verdict: the seed is paid when
        the debate closes. You never name an amount and never seed what the gates or the centre
        refuse. The manager only."""
        return await call("POST", f"/debates/{pitch_id}/verdict",
                          body={"verdict": verdict, "reason": reason})

    # --- Team: the analysts a PM builds its pod with ---------------------------

    @api_tool(server, method="GET", path="/team")
    async def get_team(
        pod_id: Annotated[int | None, Field(description="Default: your own pod.", ge=1, le=MAX_ID)] = None,
    ) -> Any:
        """Your pod's team: the team law (how many analysts, which models, the team budget), every
        analyst place (waiting for the morning's hire, working, let go) with its charter, model,
        budget and what it has spent, the budget left, and every request that was refused."""
        return await call("GET", "/team", params={"pod_id": pod_id})

    @api_tool(server, method="POST", path="/team/analysts")
    async def request_analyst(
        charter: Annotated[str, Field(description=(
            "Who the analyst is and what it must do, in your words: it is all it is told about "
            "its job."), min_length=1, max_length=2000)],
        model: Annotated[str, Field(description="A model from the team law's pool (get_team).",
                                    min_length=1, max_length=100)],
        budget_usd: Annotated[float, Field(description=(
            "Its thinking budget, USD: its key's limit, taken from your pod's team budget."),
            gt=0, le=50)],
    ) -> Any:
        """Ask for an analyst for your pod. PMs only. If granted, it is hired the next morning into
        your pod. It can research (its backtests count as your pod's attempts when you pitch),
        read the library and message you; it cannot pitch or trade. Everything it thinks is paid
        by your pod: it lowers your fitness and capital score. A refusal says why."""
        return await call("POST", "/team/analysts", body={
            "charter": charter, "model": model, "budget_usd": budget_usd})

    @api_tool(server, method="POST", path="/team/analysts")
    async def request_analyst_with_data(
        charter: Annotated[str, Field(description=(
            "Who the analyst is and what it must do, in your words: it is all it is told about "
            "its job."), min_length=1, max_length=2000)],
        model: Annotated[str, Field(description="A model from the team law's pool (get_team).",
                                    min_length=1, max_length=100)],
        budget_usd: Annotated[float, Field(description=(
            "Its thinking budget, USD: its key's limit, taken from your pod's team budget."),
            gt=0, le=50)],
        data: Annotated[list[Literal["headlines", "company"]], Field(description=(
            "What it reads beyond prices, from the team law's list (get_team): 'headlines', "
            "'company' (quarterly reports). You need not read them yourself."),
            min_length=1, max_length=2)],
    ) -> Any:
        """Ask for an analyst for your pod who reads data beyond prices (headlines, company
        reports). PMs only. Otherwise exactly request_analyst: hired the next morning into your
        pod, paid by your pod. A refusal says why."""
        return await call("POST", "/team/analysts", body={
            "charter": charter, "model": model, "budget_usd": budget_usd, "data": data})

    @api_tool(server, method="POST", path="/team/places/{place_id}/let-go")
    async def let_go_analyst(
        place_id: Annotated[int, Field(description="The team place (get_team).", ge=1, le=MAX_ID)],
    ) -> Any:
        """Let your analyst go (it stops working and spending), or withdraw a request not yet
        filled. PMs only, your own pod's places."""
        return await call("POST", f"/team/places/{place_id}/let-go")

    @api_tool(server, method="GET", path="/team/places")
    async def list_team_places() -> Any:
        """Every team place of the firm, oldest first. Management only."""
        return await call("GET", "/team/places")

    @api_tool(server, method="POST", path="/team/places/{place_id}/fill")
    async def fill_team_place(
        place_id: Annotated[int, Field(description="The open team place.", ge=1, le=MAX_ID)],
    ) -> Any:
        """Hire the analyst a team place names, into its PM's pod. The answer holds its key, once.
        Needs the right to register agents."""
        return await call("POST", f"/team/places/{place_id}/fill")

    @api_tool(server, method="POST", path="/team/places/{place_id}/refuse")
    async def refuse_team_hire(
        place_id: Annotated[int, Field(description="The open team place.", ge=1, le=MAX_ID)],
        reason: Annotated[str, Field(description="Why the hire cannot be made now.",
                                     min_length=1, max_length=200)],
    ) -> Any:
        """Refuse a team hire for now (its key does not fit the cap). The place stays open.
        Needs the right to register agents."""
        return await call("POST", f"/team/places/{place_id}/refuse", body={"reason": reason})

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

    @api_tool(server, method="GET", path="/metering/agents")
    async def get_metered_costs() -> Any:
        """What each metered agent cost, by the system's meter. Management only.

        Next to each agent's own self-reported cost and the gap between the two. The meter
        is the number pods are ranked on once the run's costs are synced (until then a ranking
        still uses self-reports); a self-report is only the cross-check.
        """
        return await call("GET", "/metering/agents")

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

    @api_tool(server, method="POST", path="/metering/usage")
    async def report_metered_usage(
        agent_id: Annotated[int, Field(description="The agent the key was minted for.", ge=1, le=MAX_ID, strict=True)],
        key_ref: Annotated[str, Field(description="The key's opaque label (lower-case letters, digits, - _; at most 64).", pattern=KEY_REF_PATTERN)],
        usd_micros_total: Annotated[int, Field(description="What the key has cost in total so far, in micro-dollars (cumulative, not a delta).", ge=0, le=MAX_METERED_USD_MICROS, strict=True)],
    ) -> Any:
        """Post a provisioned key's cumulative cost for an agent. The Runtime's identity only (no firm agent).

        System-reported cost replaces the agent's self-report in the metrics. A
        key belongs to the first agent it names; a total never goes down;
        re-posting the same total changes nothing.
        """
        return await call(
            "POST",
            "/metering/usage",
            body={"agent_id": agent_id, "key_ref": key_ref, "usd_micros_total": usd_micros_total},
        )

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
