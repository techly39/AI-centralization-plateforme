"""``python -m mcp_server`` — same entry point as the ``fund-env-mcp`` script."""

from mcp_server.server import main

if __name__ == "__main__":
    raise SystemExit(main())
