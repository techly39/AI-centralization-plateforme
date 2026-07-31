# AI Fund Environment ("The App")

The deterministic **environment** for a simulated multi-agent hedge fund. It owns
all state, communication, order execution, and metrics. AI agents are *external
clients* that talk to it only through its REST API (and, from Phase 2, an MCP
server). The app itself contains **zero AI logic and zero trading intelligence**.

See [TRD_ai_fund_environment.md](TRD_ai_fund_environment.md) for the full spec.

## Status

**Phase 0 — Skeleton (complete).** Config, DB models, live clock, append-only
event ledger with `rebuild_state()`, agent registry, API-key auth, and the
permission matrix.

**Phase 1 — OMS + market data (complete).** `MarketDataProvider` over yfinance
(with an offline `static` provider for development), the full deterministic OMS —
market fills, limit orders with a background monitor, fee math, rejections with
an auto-message to the PM, partial sells with realised P&L — and the portfolio
endpoint. The old file-based OMS was migrated; see
[docs/oms_migration.md](docs/oms_migration.md).

Phases 2-4 (messaging, cost/task reporting, MCP server, metrics, backtest clock,
UI) are not built yet — see the TRD's phase plan.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12 is fetched automatically).

```bash
uv sync                        # create the venv and install deps
uv run fund-env init-db        # create fund.db and bring the schema to the latest migration
uv run fund-env seed-admin     # create the first management agent; prints its API key ONCE
uv run fund-env serve          # start the API on http://127.0.0.1:8000
```

Then open http://127.0.0.1:8000/docs for the interactive API docs.

Authenticate every request with the header `X-API-Key: <key>`.

### Setting up a trading desk

A PM can only trade on behalf of a pod, and a pod needs cash. Both are operator
commands until the management allocation API arrives in Phase 3.

```bash
uv run fund-env create-pod --name "alpha" --allocation 1000000
# note the pod id it prints, then register a PM against it:
curl -X POST http://127.0.0.1:8000/agents/register \
  -H "X-API-Key: <management key>" -H "Content-Type: application/json" \
  -d '{"name": "pm-alpha", "role": "pm", "pod_id": 1}'
```

With the PM's key you can trade:

```bash
# A market buy. Returns 201 — read "status": filled | pending | rejected.
curl -X POST http://127.0.0.1:8000/orders \
  -H "X-API-Key: <pm key>" -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","side":"buy","qty":10,"price_type":"market",
       "justification":"AI hardware re-rating thesis"}'

curl -H "X-API-Key: <pm key>" http://127.0.0.1:8000/portfolio/1
curl -H "X-API-Key: <pm key>" "http://127.0.0.1:8000/orders?status=pending"
curl -H "X-API-Key: <pm key>" http://127.0.0.1:8000/price/AAPL
```

### Working offline

To run without hitting Yahoo Finance, set the static provider in `config.yaml`:

```yaml
marketdata:
  provider: "static"
  static_prices: {AAPL: 200.0, MSFT: 380.0}
```

### Other operator commands

```bash
uv run fund-env fund-pod --pod-id 1 --delta 250000 --reason "Q3 top-up"
uv run fund-env check-orders     # run one pending-limit-order sweep right now
uv run fund-env rebuild-state    # recompute positions/cash from the event ledger
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
  scheduler.py    APScheduler background jobs (pending-order monitor)
  ledger/         append-only event store, reducers, rebuild_state(), incremental apply
  registry/       agent identity, API-key auth, permission matrix, pods
  marketdata/     MarketDataProvider interface + yfinance and static implementations
  oms/            order management: service, monitor, portfolio, fee math
  api/            routers, one file per domain
  bus/            notifications now; full messaging in Phase 2
  metrics/        (Phase 2)
mcp_server/       MCP wrapper (Phase 2)
ui/               server-rendered UI (Phase 4)
docs/             design notes (oms_migration.md)
legacy/           the pre-Phase-1 file-based OMS, kept for reference only
tests/
```
