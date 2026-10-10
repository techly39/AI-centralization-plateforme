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

**Phase 2 — Bus + costs + MCP (complete).** The message bus (agent-to-agent,
pod, and broadcast, with polling), cost and work self-reporting, management
metrics — time-weighted return, Sharpe, max drawdown, hit rate, and
cost-adjusted P&L — and an MCP server exposing every endpoint as a tool. The
design decisions are in [docs/phase2_bus_costs_mcp.md](docs/phase2_bus_costs_mcp.md).

Phases 3-4 (backtest clock, meetings, allocation endpoint, read-only UI) are not
built yet — see the TRD's phase plan.

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

The key is the identity, so an agent that has one needs nothing else to find out
who it is:

```bash
# id, name, role, pod — the arguments every other endpoint asks for.
curl -H "X-API-Key: <key>" http://127.0.0.1:8000/me
```

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

### Talking, reporting, and being measured

Agents communicate only through the app, so there is one record of everything
said. Addresses are `agent:<id>`, `pod:<id>`, or `broadcast`:

```bash
# Send. Analysts and PMs may address any agent or pod; only PMs (own pod) and
# management may broadcast.
curl -X POST http://127.0.0.1:8000/messages \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"to":"agent:3","body":"JPM screens cheapest","thread_id":"jpm",
       "structured_payload":{"ticker":"JPM","conviction":0.8}}'

# Poll. Remember the highest id you saw and pass it back as after_id.
curl -H "X-API-Key: <key>" "http://127.0.0.1:8000/messages?after_id=42"

# Catch up instead: the newest page in one call, then walk back with before_id.
curl -H "X-API-Key: <key>" "http://127.0.0.1:8000/messages?latest=true&limit=50"
curl -H "X-API-Key: <key>" "http://127.0.0.1:8000/messages?before_id=17&limit=50"
```

Every page comes back oldest-first. `after_id` and `latest`/`before_id` read in
opposite directions, so asking for both at once is a 422 rather than a silently
half-honoured request.

The app cannot see what an agent costs to run, so agents report it themselves —
their charters must tell them to, or the pod's returns get measured against a
cost of zero:

```bash
curl -X POST http://127.0.0.1:8000/costs -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"tokens_in":84000,"tokens_out":6200,"usd_cost":1.34,"task_label":"value screen"}'

curl -X POST http://127.0.0.1:8000/tasks/start -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" -d '{"subject":"value screen"}'
curl -X POST http://127.0.0.1:8000/tasks/end -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"task_id":1,"outcome":{"summary":"four names off their highs"}}'
```

Management reads the results. Statistics with too little history come back as
`null` rather than `0` — a one-day-old pod has no Sharpe ratio:

```bash
curl -H "X-API-Key: <management key>" http://127.0.0.1:8000/metrics/pod/1
curl -H "X-API-Key: <management key>" http://127.0.0.1:8000/metrics/leaderboard
```

Pods are ranked by **cost-adjusted P&L** — profit minus what the agents cost to
run. A desk that earns more than a rival can still rank below it.

### Connecting an agent over MCP

The MCP server is a separate process that wraps this API and exposes every
endpoint as a tool. Start the API first, then:

```bash
FUND_MCP__API_KEY=<the agent's key> uv run fund-env-mcp
```

Run **one MCP server per agent**, each with its own key — the key is the identity
every action is attributed to. The tool list is the same for every role; the API
returns 403 to whoever is out of bounds, so there is only ever one permission
matrix. Point any MCP client (OpenClaw, the Claude Agent SDK, Claude Desktop) at
that command over stdio.

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
  clock.py        time service (live mode only until Phase 3)
  cli.py          init-db / seed-admin / create-pod / serve / rebuild-state
  db/             SQLAlchemy 2.0 Base, session, models, UTC datetime column type
  scheduler.py    APScheduler background jobs (pending-order monitor)
  ledger/         append-only event store, reducers, rebuild_state(), incremental apply
  registry/       agent identity, API-key auth, permission matrix, pods
  marketdata/     MarketDataProvider interface + yfinance and static implementations
  oms/            order management: service, monitor, portfolio, fee math
  bus/            messaging: addressing, visibility, system notifications
  metrics/        cost/task reporting, equity curve, performance stats, leaderboard
  api/            routers, one file per domain
mcp_server/       MCP wrapper over the API — one tool per endpoint
ui/               server-rendered UI (Phase 4)
docs/             design notes (oms_migration.md, phase2_bus_costs_mcp.md)
legacy/           the pre-Phase-1 file-based OMS, kept for reference only
tests/
```
