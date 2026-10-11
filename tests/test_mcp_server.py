"""The MCP surface (TRD §3, Definition of Done).

Two things have to be true, and this file tests both:

1. **Every endpoint has a tool.** Checked against the app's own OpenAPI schema,
   so adding a route without a tool fails the suite rather than being discovered
   by an agent that cannot do its job.
2. **The tools actually work, through the real API.** The client is pointed at
   the FastAPI app over an in-process ASGI transport, so these tests exercise
   routing, authentication, permissions, and JSON shapes end to end — everything
   a real MCP client would hit except the socket.

The Definition of Done says a fresh agent must be able to "register, read the
directory, message another agent, and place an order without any code change to
the app". That exact sequence is :func:`test_a_fresh_agent_can_work_through_mcp`.
"""

from __future__ import annotations

import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.main import create_app
from mcp_server import TOOL_ROUTES, FundAPIError, FundClient, build_server


@pytest.fixture
def mcp_client_factory(SessionFactory, client):
    """Build a :class:`FundClient` speaking to the test app as a given agent."""
    from app.db.base import get_session

    app = create_app()
    app.dependency_overrides[get_session] = client.app.dependency_overrides[get_session]

    def _make(api_key: str) -> FundClient:
        return FundClient(
            base_url="http://fund.test",
            api_key=api_key,
            transport=httpx.ASGITransport(app=app),
        )

    return _make


async def call(server, tool, /, **arguments):
    """Invoke a tool the way an MCP client does, and return its parsed result.

    ``tool`` is positional-only because several tools take an argument called
    ``name``, and a keyword collision here would be a confusing way to fail.
    """
    result = await server.call_tool(tool, arguments)
    assert not result.is_error, _text_of(result)
    return _payload(result)


async def call_expecting_error(server, tool, /, **arguments) -> str:
    """Call a tool that should fail, and return the message the agent would see.

    ``MCPServer.call_tool`` re-raises ``ToolError``; the protocol layer above it
    is what turns that into ``CallToolResult(is_error=True)``. Either way the
    agent receives this text, which is what the assertions care about.
    """
    try:
        result = await server.call_tool(tool, arguments)
    except ToolError as exc:
        return str(exc)
    assert result.is_error, f"expected {tool} to fail, got: {_text_of(result)}"
    return _text_of(result)


def _payload(result):
    """Parse a tool result.

    MCP returns a list-valued result as one content block per element, so a list
    of two rows arrives as two blocks rather than one JSON array. Single results
    are unwrapped; anything else comes back as a list.
    """
    parsed = [
        json.loads(block.text)
        for block in result.content
        if getattr(block, "type", "") == "text"
    ]
    return parsed[0] if len(parsed) == 1 else parsed


def _text_of(result) -> str:
    return "\n".join(
        block.text for block in result.content if getattr(block, "type", "") == "text"
    )


@pytest.fixture(scope="module")
def tool_routes() -> dict:
    """``TOOL_ROUTES`` is filled in when a server is built, so build one."""
    build_server(FundClient(base_url="http://unused", api_key="unused"))
    return dict(TOOL_ROUTES)


# --- Coverage ---------------------------------------------------------------

def _endpoints() -> set[tuple[str, str]]:
    spec = create_app().openapi()
    return {
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
    }


def test_every_endpoint_has_a_tool(tool_routes):
    """TRD §7: "All endpoints also exposed as MCP tools"."""
    covered = {(route.method, route.path) for route in tool_routes.values()}
    missing = _endpoints() - covered
    assert not missing, (
        "these endpoints have no MCP tool — an agent cannot reach them: "
        f"{sorted(missing)}"
    )


def test_no_tool_points_at_an_endpoint_that_does_not_exist(tool_routes):
    """The other direction: a renamed route must not leave a dead tool behind."""
    stale = {(r.method, r.path) for r in tool_routes.values()} - _endpoints()
    assert not stale, f"tools wired to non-existent endpoints: {sorted(stale)}"


@pytest.mark.anyio
async def test_every_tool_is_described_for_the_agent_reading_it():
    """A tool with no description is a tool an LLM will misuse."""
    server = build_server(FundClient(base_url="http://unused", api_key="unused"))
    for tool in await server.list_tools():
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) > 30, f"{tool.name}'s description is too thin"


# --- Behaviour --------------------------------------------------------------

@pytest.mark.anyio
async def test_a_fresh_agent_can_work_through_mcp(
    mcp_client_factory, admin_key, make_pod, fund_pod_cash
):
    """The TRD's Definition of Done, executed: register, directory, message, order."""
    pod_id = make_pod(1)
    fund_pod_cash(pod_id, 100_000.0)

    async with mcp_client_factory(admin_key) as admin_conn:
        management = build_server(admin_conn)

        created = await call(
            management, "register_agent", name="pm-mcp", role="pm", pod_id=pod_id
        )
        pm_key = created["api_key"]

        analyst = await call(
            management, "register_agent", name="analyst-mcp", role="analyst",
            pod_id=pod_id, research_domains=["banks"],
        )

        async with mcp_client_factory(pm_key) as pm_conn:
            pm = build_server(pm_conn)

            directory = await call(pm, "list_agents")
            assert {"pm-mcp", "analyst-mcp"} <= {a["name"] for a in directory}

            sent = await call(
                pm, "send_message",
                to=f"agent:{analyst['id']}",
                body="Cover JPM for tomorrow.",
                structured_payload={"ticker": "JPM"},
            )
            assert sent["to"] == f"agent:{analyst['id']}"

            order = await call(
                pm, "place_order",
                ticker="AAPL", side="buy", qty=10, price_type="market",
                justification="MCP end-to-end check",
            )
            assert order["status"] == "filled"

            portfolio = await call(pm, "get_portfolio", pod_id=pod_id)
            assert portfolio["positions"][0]["ticker"] == "AAPL"


@pytest.mark.anyio
async def test_whoami_bootstraps_an_agent_that_knows_only_its_key(
    mcp_client_factory, admin_key, make_pod, fund_pod_cash
):
    """The identity an agent needs, from the key alone — no prompt, no guessing.

    ``whoami`` has to be enough on its own: the pod id it returns is what
    ``get_portfolio`` wants, so an agent told nothing about itself can still
    reach its own book.
    """
    pod_id = make_pod(1)
    fund_pod_cash(pod_id, 10_000.0)

    async with mcp_client_factory(admin_key) as admin_conn:
        created = await call(
            build_server(admin_conn), "register_agent",
            name="pm-mcp", role="pm", pod_id=pod_id, research_domains=["banks"],
        )

    async with mcp_client_factory(created["api_key"]) as conn:
        server = build_server(conn)
        me = await call(server, "whoami")
        assert me == {
            "id": created["id"],
            "name": "pm-mcp",
            "role": "pm",
            "pod_id": pod_id,
            "research_domains": ["banks"],
            "status": "active",
        }

        portfolio = await call(server, "get_portfolio", pod_id=me["pod_id"])
        assert portfolio["pod_id"] == pod_id


@pytest.mark.anyio
async def test_reading_the_end_of_the_bus_takes_one_call(
    mcp_client_factory, admin_key, make_pod
):
    """An agent joining mid-run must not have to page from message 1."""
    pod_id = make_pod(1)
    async with mcp_client_factory(admin_key) as admin_conn:
        admin = build_server(admin_conn)
        pm = await call(admin, "register_agent", name="pm-mcp", role="pm", pod_id=pod_id)
        for i in range(5):
            await call(admin, "send_message", to=f"agent:{pm['id']}", body=f"note {i}")

    async with mcp_client_factory(pm["api_key"]) as conn:
        server = build_server(conn)

        tail = await call(server, "get_messages", latest=True, limit=2)
        assert [m["body"] for m in tail] == ["note 3", "note 4"]

        older = await call(server, "get_messages", before_id=tail[0]["id"], limit=2)
        assert [m["body"] for m in older] == ["note 1", "note 2"]

        # Contradictory cursors reach the agent as the API's own 422 text.
        both = await call_expecting_error(
            server, "get_messages", after_id=1, before_id=9
        )
        assert "422" in both and "after_id" in both


@pytest.mark.anyio
async def test_permissions_are_the_apis_not_the_tools(
    mcp_client_factory, admin_key, make_pod, fund_pod_cash
):
    """The analyst is offered every tool and refused by the API, not by MCP.

    That is the design: one permission matrix, enforced in one place. If MCP
    filtered the tool list instead, the two would drift.
    """
    pod_id = make_pod(1)
    fund_pod_cash(pod_id, 50_000.0)

    async with mcp_client_factory(admin_key) as admin_conn:
        analyst = await call(
            build_server(admin_conn), "register_agent",
            name="analyst-mcp", role="analyst", pod_id=pod_id,
        )

    async with mcp_client_factory(analyst["api_key"]) as conn:
        server = build_server(conn)
        assert "place_order" in {t.name for t in await server.list_tools()}

        message = await call_expecting_error(
            server, "place_order",
            ticker="AAPL", side="buy", qty=1, price_type="market",
            justification="not my job",
        )
        # The API's own wording reaches the agent, so it can tell *why* it failed.
        assert "403" in message and "place_order" in message

        assert "403" in await call_expecting_error(server, "get_leaderboard")


@pytest.mark.anyio
async def test_a_rejected_order_is_a_result_not_a_tool_failure(
    mcp_client_factory, admin_key, make_pod, fund_pod_cash
):
    """Rejection is a business outcome (HTTP 201), so the tool must succeed."""
    pod_id = make_pod(1)
    fund_pod_cash(pod_id, 100.0)

    async with mcp_client_factory(admin_key) as admin_conn:
        pm = await call(
            build_server(admin_conn), "register_agent",
            name="pm-mcp", role="pm", pod_id=pod_id,
        )

    async with mcp_client_factory(pm["api_key"]) as conn:
        order = await call(
            build_server(conn), "place_order",
            ticker="AAPL", side="buy", qty=1000, price_type="market",
            justification="way too big",
        )
        assert order["status"] == "rejected"
        assert "insufficient" in order["status_reason"] or "holds" in order["status_reason"]


@pytest.mark.anyio
async def test_a_halted_world_tells_the_agent_why(
    mcp_client_factory, admin_key, make_pod, fund_pod_cash, halt_file
):
    """A halt is a tool failure the agent can read, and ``get_halt`` explains it."""
    pod_id = make_pod(1)
    fund_pod_cash(pod_id, 100_000.0)

    async with mcp_client_factory(admin_key) as admin_conn:
        pm = await call(
            build_server(admin_conn), "register_agent",
            name="pm-mcp", role="pm", pod_id=pod_id,
        )

    halt_file.touch()
    async with mcp_client_factory(pm["api_key"]) as conn:
        server = build_server(conn)
        message = await call_expecting_error(
            server, "place_order",
            ticker="AAPL", side="buy", qty=1, price_type="market", justification="t",
        )
        assert "423" in message and "halted" in message
        assert await call(server, "get_halt") == {"halted": True}
        assert (await call(server, "get_portfolio", pod_id=pod_id))["pod_id"] == pod_id


@pytest.mark.anyio
async def test_optional_arguments_are_omitted_not_sent_as_null(
    mcp_client_factory, admin_key, make_pod
):
    """A skipped filter must not become the literal string 'None' in the query.

    FastAPI would reject ``?actor=None`` with a 422, so this passing is the
    proof that unset arguments are dropped rather than stringified.
    """
    make_pod(1)
    async with mcp_client_factory(admin_key) as conn:
        server = build_server(conn)
        # No filters at all, then one filter set: both must be accepted.
        await call(server, "list_events")
        filtered = await call(server, "list_events", type="agent_registered")
        assert filtered  # the admin's own registration is in there


@pytest.mark.anyio
async def test_self_reporting_round_trip(mcp_client_factory, admin_key, make_pod):
    pod_id = make_pod(1)
    async with mcp_client_factory(admin_key) as admin_conn:
        pm = await call(
            build_server(admin_conn), "register_agent",
            name="pm-mcp", role="pm", pod_id=pod_id,
        )

    async with mcp_client_factory(pm["api_key"]) as conn:
        server = build_server(conn)
        task = await call(server, "start_task", subject="earnings review")
        closed = await call(
            server, "end_task", task_id=task["id"],
            outcome={"summary": "JPM cheapest", "recommendation": "buy"},
        )
        assert closed["outcome"]["recommendation"] == "buy"
        assert closed["seconds"] is not None

        cost = await call(
            server, "report_cost", tokens_in=1000, tokens_out=200, usd_cost=0.02,
            task_label="earnings review",
        )
        assert cost["usd_cost"] == 0.02


@pytest.mark.anyio
async def test_an_unreachable_api_says_so_plainly(admin_key):
    """The failure an operator will actually hit: the server is not running."""
    client = FundClient(base_url="http://127.0.0.1:1", api_key=admin_key, timeout_seconds=1)
    try:
        with pytest.raises(FundAPIError) as caught:
            await client.get("/health")
        assert "could not reach the fund API" in str(caught.value)
    finally:
        await client.aclose()


@pytest.fixture
def anyio_backend():
    return "asyncio"
