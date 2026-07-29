# AI Fund Environment ("The App")

The deterministic **environment** for a simulated multi-agent hedge fund. It owns
all state, communication, order execution, and metrics. AI agents are *external
clients* that talk to it only through its REST API (and, from Phase 2, an MCP
server). The app itself contains **zero AI logic and zero trading intelligence**.

See [TRD_ai_fund_environment.md](TRD_ai_fund_environment.md) for the full spec.

## Status

**Phase 0 — Skeleton (complete).** Config, DB models, live clock, append-only
event ledger with `rebuild_state()`, agent registry, API-key auth, and the
permission matrix. Endpoints: agent register/deactivate/directory, event query,
clock read.

Later phases (OMS, market data, messaging, MCP, metrics, backtest, UI) are not
built yet — see the TRD's phase plan.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12 is fetched automatically).

```bash
uv sync                       # create the venv and install deps
uv run fund-env init-db       # create fund.db and its tables
uv run fund-env seed-admin     # create the first management agent; prints its API key ONCE
uv run fund-env serve          # start the API on http://127.0.0.1:8000
```

Then open http://127.0.0.1:8000/docs for the interactive API docs.

Authenticate every request with the header `X-API-Key: <key>`.

```bash
# List the agent directory (any authenticated agent):
curl -H "X-API-Key: <key>" http://127.0.0.1:8000/agents
```

## Tests

```bash
uv run pytest
```

## Layout

```
app/
  main.py         FastAPI entrypoint
  config.py       config.yaml + env loader (Pydantic Settings)
  clock.py        time service (live mode only in Phase 0)
  cli.py          init-db / seed-admin / serve
  db/             SQLAlchemy 2.0 Base, session, models
  ledger/         append-only event store + rebuild_state()
  registry/       agent identity, API-key auth, permission matrix
  api/            routers, one file per domain
  oms/ bus/ metrics/ marketdata/   (placeholders for later phases)
mcp_server/       MCP wrapper (Phase 2)
ui/               server-rendered UI (Phase 4)
tests/
```
