# Technical Requirements Document — AI Fund Environment ("The App")

Version 1.0 — This document is the source of truth. Claude Code must follow it. Anything not listed in a phase's scope is out of scope for that phase.

---

## 1. Purpose

A standalone application that is the **environment** of a simulated multi-agent hedge fund. It owns all state, communication, order execution, and metrics. AI agents (running on OpenClaw, Claude Agent SDK, or any other framework) are **external clients** that interact with it exclusively through its API/MCP tools. The app contains **zero AI logic and zero trading intelligence**.

## 2. Non-negotiable principles

1. **API-first.** All functionality is exposed through a REST API. The UI, the agents, and the management layer are all clients of the same API. No logic in the UI.
2. **Everything through the bus.** Any action crossing a pod boundary (message, order, allocation change, metric read) goes through the app and is logged. No side channels.
3. **Deterministic core.** OMS, ledger, clock, and permissions are plain deterministic code. No LLM calls anywhere inside the app.
4. **Append-only history.** State changes are recorded as immutable events. Current state is derived, never overwritten in place.
5. **Time is injected.** All components read time from the app's internal clock service, never from the system clock directly.

## 3. Technology stack (fixed — do not substitute)

- Language: **Python 3.12+**
- API framework: **FastAPI** with **Pydantic v2** models for every request/response
- Database: **SQLite** via **SQLAlchemy 2.0** (single file `fund.db`; design so Postgres migration is possible later, but do not add Postgres now)
- Agent integration: **MCP server** (Python `mcp` SDK) wrapping the REST API — every public endpoint gets a corresponding MCP tool
- Market data: **yfinance** for delayed live prices AND historical OHLCV for backtests (abstract behind a `MarketDataProvider` interface so it can be swapped later)
- Background jobs: **APScheduler** (pending-order monitor, scheduled meetings)
- UI (Phase 4 only): server-rendered **FastAPI + Jinja2 + htmx**. No React, no separate frontend build.
- Tests: **pytest**. Config: single `config.yaml` loaded with Pydantic Settings. Dependency management: **uv**.
- Auth: static API keys per agent (see §6). No OAuth, no user accounts.

## 4. Repository layout

```
fund-env/
  app/
    main.py            # FastAPI entrypoint
    config.py
    clock.py           # time service (live | simulated)
    db/                # SQLAlchemy models + migrations (alembic)
    ledger/            # event store + derived state (portfolio, cash)
    oms/               # order management system
    bus/               # messaging + directory
    registry/          # agent identity + permissions
    metrics/           # cost/activity/performance aggregation
    marketdata/        # MarketDataProvider interface + yfinance impl
    api/               # routers, one file per domain
  mcp_server/          # MCP wrapper over the REST API
  ui/                  # Phase 4
  tests/
  config.yaml
```

## 5. Core domain model (SQLite tables — minimum fields)

- **agents**: id, name, role (`analyst | pm | management | system`), pod_id (nullable for management), api_key_hash, charter_ref, status, created_at
- **pods**: id, name, status, current_allocation (virtual cash), created_at
- **events** (append-only ledger): id, ts (clock time), actor_agent_id, type, payload_json. Every state change in the system is an event.
- **orders**: id, pod_id, created_by, ticker, side (`buy | sell`), qty, price_type (`market | limit`), limit_price, status (`pending | filled | rejected | cancelled`), justification, created_at, filled_at, fill_price
- **positions** (derived, rebuildable from events): pod_id, ticker, qty, avg_cost
- **cash_balances** (derived): pod_id, balance
- **messages**: id, ts, from_agent, to (agent_id | pod_id | `broadcast`), thread_id, body, structured_payload_json (nullable)
- **costs**: id, ts, agent_id, pod_id, tokens_in, tokens_out, usd_cost, task_label — reported by agents via API (see §7)
- **tasks**: id, pod_id, agent_id, subject, started_at, ended_at, outcome_json — self-reported work log
- **allocations**: id, ts, pod_id, delta, new_total, set_by, reason

Rule for Claude Code: derived tables must be rebuildable by replaying `events`. Provide a `rebuild_state()` maintenance command.

## 6. Identity & permissions

- Each agent gets an API key at registration. Every request is authenticated.
- Permission matrix enforced in the API layer (not in prompts):

| Action | analyst | pm | management |
|---|---|---|---|
| send message (any agent/pod) | ✅ | ✅ | ✅ |
| list_agents / directory | ✅ | ✅ | ✅ |
| read market data | ✅ | ✅ | ✅ |
| read own pod portfolio | ✅ | ✅ | ✅ |
| place/cancel orders | ❌ | ✅ (own pod) | ❌ |
| read other pods' metrics/logs | ❌ | ❌ | ✅ |
| set_allocation | ❌ | ❌ | ✅ |
| broadcast to a pod | ❌ | ✅ (own pod) | ✅ |
| register/deactivate agents | ❌ | ❌ | ✅ |

- Violations return HTTP 403 and are logged as events.

## 7. API surface (v1 — exact endpoints)

All endpoints also exposed as MCP tools with identical names.

**Registry**: `POST /agents/register` (management only), `GET /agents` (directory: id, name, role, pod, research_domains), `POST /agents/{id}/deactivate`

**Messaging**: `POST /messages` (to agent, pod, or broadcast; optional thread_id), `GET /messages?since=&thread=&mine=true` (polling; no websockets in v1)

**Market data**: `GET /price/{ticker}`, `GET /ohlcv/{ticker}?start=&end=&interval=` — served according to current clock mode (live price in live mode; historical price at simulated "now" in backtest mode, with hard guarantee of no future data leakage)

**OMS**: `POST /orders` (pm only; body = ticker, side, qty, price_type, limit_price?, justification), `DELETE /orders/{id}` (cancel pending), `GET /orders?pod=&status=`, `GET /portfolio/{pod_id}` (positions + cash + unrealized P&L)

**Costs & tasks (self-reporting)**: `POST /costs` (tokens + usd per work unit), `POST /tasks/start`, `POST /tasks/end` — agent charters must instruct agents to call these; the app cannot measure external token usage itself

**Metrics (management only)**: `GET /metrics/pod/{id}` → returns: total return, Sharpe (daily), max drawdown, hit rate, total usd_cost, cost-adjusted P&L (P&L − usd_cost), time per subject, tasks opened/closed, messages sent
`GET /metrics/leaderboard`

**Allocation (management only)**: `POST /allocations` (pod_id, delta, reason)

**Clock (system/management only; `GET /clock` is readable by every agent and reports the ledger's now, max(clock, latest stamp) — ADR-026)**: `GET /clock`, `POST /clock/advance` (backtest runs only: `{days, minutes}`, 1 minute..366 days per step, never past the real now; then the pending-order sweep; live → 409 — ADR-027). *No `POST /clock/mode`* (ADR-027): the mode is a fact of the run's database, fixed by `fund-env start-backtest` on an empty database.

**Meetings (Phase 3)**: `POST /meetings/schedule`, `GET /meetings/{id}/package` → assembled context: week's metrics, allocations, firm charter text, flagged anomalies

## 8. OMS behavior (deterministic)

1. Receive order → authenticate + permission check → fetch price from MarketDataProvider (via clock).
2. Cash check: cost = price × qty (+ flat simulated fee, configurable, default 0.1%). Insufficient → status `rejected`, message auto-sent back to the PM with balance details.
3. `market` → fill immediately at current price; emit events; update derived state.
4. `limit` → status `pending`; monitor job checks every N minutes (config; in backtest mode, checked at every clock advance). Fill when price crosses limit (re-validate cash at fill time). Cancellable by the PM.
5. Sells: verify position qty; partial sells allowed; realized P&L recorded as an event.

## 9. Clock & backtest mode

- `clock.now()` is the only time source for OMS, scheduler, metrics, and market data.
- **Live mode**: wraps real time; prices from yfinance delayed feed.
- **Backtest mode**: time starts at a configured historical datetime and advances only via `/clock/advance`. Market data endpoints return data as of simulated now, and must reject any request for data beyond simulated now (look-ahead guard). Pending-order monitor runs on every advance. *(ADR-028: the guard is in the `MarketDataProvider` base, whose `get_price`/`get_ohlcv` no subclass may override. "Beyond now" means not yet **known**: a bar is served once it has ended (a daily bar's close at its next midnight), a quote stamped after now — or not a positive finite number — is refused (502). A window starting after now is still 400. yfinance answers a past now from its last completed daily bar; its current quote answers only a now within 60 s of the real one, and a backtest is kept at least that far behind.)*
- Mode switching wipes nothing: live and backtest runs are separate `run_id` scopes on all tables. *(ADR-027: a run is a database. A backtest is a fresh database whose ledger opens with `run_started {mode, start}`; its clock is the latest `run_started.start` / `clock_advanced.to`, rebuilt on every process start. Separate files are the separate scopes — no query can forget a `run_id` filter.)*

## 10. Observability

- Structured JSON logging (loguru) for every request: who, what, when, result.
- `GET /events?actor=&type=&since=` for querying the ledger (management only for cross-pod).
- Every LLM-facing artifact (order justification, message, task outcome) stored as structured JSON — never free text only.

## 11. Build phases (strict order — do not start a phase before the previous one's tests pass)

**Phase 0 — Skeleton**: repo layout, config, DB models, clock service (live mode only), event ledger + `rebuild_state()`, agent registry + API-key auth + permission matrix. Tests: permissions, ledger replay.

**Phase 1 — OMS + market data**: MarketDataProvider (yfinance), full OMS (§8), portfolio endpoint. Tests: market fill, limit fill, rejection, partial sell, fee math.

**Phase 2 — Bus + costs + MCP**: messaging + directory, cost/task self-reporting, metrics endpoints, MCP server exposing all tools. Milestone: re-run the existing OpenClaw single-pod POC **through the app only**.

**Phase 3 — Clock backtest mode + meetings**: simulated clock, look-ahead guard, `/clock/advance`, meeting packages, allocation endpoint. Milestone: one pod completes a 1-month backtest in under 10 minutes of real time.

**Phase 4 — UI (read-only)**: message feed, portfolio table per pod, cost-adjusted P&L leaderboard, event explorer. Nothing else.

## 12. Explicit non-goals for v1

No real-money brokerage. No websockets. No user accounts / multi-tenant. No React/SPA. No Docker/Kubernetes (plain `uv run`). No Postgres. No agent code inside this repo (pods live in separate projects). No evolution logic (Layer 3 mechanics come after Phase 4, as clients of the API — not inside the app).

## 13. Definition of done (global)

- All endpoints have Pydantic schemas, permission checks, and pytest coverage.
- `rebuild_state()` reproduces identical derived state from events.
- A backtest run is fully reproducible given the same inputs.
- The MCP server exposes every endpoint and a fresh Claude Agent SDK agent can register, read the directory, message another agent, and place an order without any code change to the app.
