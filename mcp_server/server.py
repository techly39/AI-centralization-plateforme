"""Entry point for the MCP server (TRD §3, Phase 2).

Run it over stdio, which is how MCP clients (OpenClaw, the Claude Agent SDK,
Claude Desktop) launch a local server:

    FUND_MCP__API_KEY=<the agent's key> uv run fund-env-mcp

It talks to a **running** fund API — start that first with ``uv run fund-env
serve``. The two are separate processes on purpose: the API is the environment
and owns the data; this is one agent's doorway into it, holding one API key and
therefore one identity. Run one MCP server per agent, each with its own key, and
the ledger attributes every action correctly with no extra bookkeeping.
"""

from __future__ import annotations

import sys

from app.config import get_settings
from mcp_server.client import FundClient
from mcp_server.tools import build_server


class MissingAPIKeyError(RuntimeError):
    """No API key was configured, so the server has no identity to act as."""


def build_from_settings() -> tuple[FundClient, object]:
    """Wire a client and server from ``config.yaml`` plus ``FUND_MCP__*`` env vars."""
    cfg = get_settings().mcp
    if not cfg.api_key:
        raise MissingAPIKeyError(
            "No API key configured for the MCP server. Set FUND_MCP__API_KEY to "
            "the key of the agent this server acts as — it is what the fund uses "
            "to decide what you may do and who to attribute your actions to.\n"
            "Get one with: uv run fund-env seed-admin (management), or ask "
            "management to register your agent."
        )
    client = FundClient(
        base_url=cfg.api_base_url,
        api_key=cfg.api_key,
        timeout_seconds=cfg.timeout_seconds,
    )
    return client, build_server(client)


def main() -> int:
    try:
        _, server = build_from_settings()
    except MissingAPIKeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Blocks until the client disconnects. stdout is the MCP transport, so
    # nothing may be printed to it — diagnostics go to stderr.
    server.run("stdio")  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
