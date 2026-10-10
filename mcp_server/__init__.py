"""MCP wrapper over the fund's REST API (TRD §3, §13).

An MCP client (OpenClaw, the Claude Agent SDK, Claude Desktop) launches
:mod:`mcp_server.server` over stdio and gets one tool per API endpoint. Nothing
in this package contains fund logic: :mod:`mcp_server.tools` declares the tools,
:mod:`mcp_server.client` makes the HTTP calls, and the app on the other end
decides what is allowed. That is what makes the two surfaces impossible to drift
apart — there is only one implementation, and this is not it.
"""

from mcp_server.client import API_KEY_HEADER, FundAPIError, FundClient
from mcp_server.tools import TOOL_ROUTES, ToolRoute, build_server

__all__ = [
    "API_KEY_HEADER",
    "TOOL_ROUTES",
    "FundAPIError",
    "FundClient",
    "ToolRoute",
    "build_server",
]
