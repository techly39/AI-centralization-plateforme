# SURVEY — Era ½ (written section by section; complete when every section is filled)

Sections: 1 Toolchain · 2 What exists · 3 What works · 4 What's broken · 5 What's dead ·
6 Risks · 7 Surprises · 8 What this changes in the backlog.

## 1. Toolchain (cycle 3, 2026-10-11)

| Tool | Version | Notes |
|---|---|---|
| macOS | 26.5.2 (25F84), arm64 | Mac mini |
| uv | 0.11.14 (Homebrew) | |
| Python (project venv) | 3.12.13 (uv-managed) | `.python-version` pins 3.12 — matches the TRD |
| Python (system `python3`) | 3.14.4 | only the guard hook uses it (stdlib only) |
| SQLite | 3.50.4 in the venv's `sqlite3`; CLI 3.51.0 | `TOTAL()` (ADR-018) available in both |
| Node / npm | v22.22.2 / 10.9.7 | needed by OpenClaw |
| OpenClaw | 2026.5.12 (f066dd2), `/opt/homebrew/bin/openclaw` | details → S-005 / `runtime/openclaw/VERSION_NOTES.md` |
| Claude Code | 2.1.296 (inferred from the install path, not `--version`) | `claude --version` needs a permission prompt in loop mode |
| git | not captured | `git --version` needs a permission prompt in loop mode |
| origin | github.com/techly39/AI-centralization-plateforme | `main` = origin/main at cycle start |

Key Python deps (locked): fastapi 0.139.2 · pydantic 2.13.4 · sqlalchemy 2.0.51 · alembic 1.18.5 ·
apscheduler 3.11.3 · **mcp 2.0.0** · yfinance 1.5.2 · pytest 9.1.1 · uvicorn 0.51.0 · httpx 0.28.1.
All match the TRD stack.

### Run check — evidence

`uv run python scripts/smoke_run.py` (new this cycle; temp dir, never touches `fund.db`):

```
[PASS] fund-env init-db — Database schema is up to date (alembic head).
[PASS] fund-env seed-admin
[PASS] fund-env create-pod — Pod created: id=1 name=smoke-pod allocation=$1,000,000.00
[PASS] fund-env serve answers /health — http://127.0.0.1:59846
[PASS] GET /docs
[PASS] MCP handshake + list_tools — 20 tools
[PASS] MCP call get_health / get_clock / list_agents / get_leaderboard / list_events
[PASS] server stopped cleanly on SIGINT — rc=0
```

So: the CLI builds a schema from zero through all alembic migrations, the API serves, and an
MCP client (the same path OpenClaw will use) authenticates with a seeded key and reads through
every layer. The physics runs outside pytest.

### Findings from the run check
- **mcp 2.0 renamed result fields** (`CallToolResult.isError` → `is_error`). Any client code or
  doc written against mcp 1.x idioms will break silently-ish; `agent_console.py` only reads
  `.content`, so it is unaffected. Watch for this in the OpenClaw adapter (B-012).
- `scripts/README.md` said "19 tools"; there are 20 (fixed).
- Stopping `uv run fund-env serve`: SIGTERM → rc=143 (128+15; which process reports it — `uv` or
  uvicorn — is unverified), SIGINT → rc=0 (measured). The script and the Runtime (B-009) stop
  the server with SIGINT.
- The live clock reports UTC (`2026-10-10T23:33Z` while local time was 01:33 CEST) — correct.
- `fund.db` at the repo root holds the Human's August history (167 kB, last write 2026-08-02).
  The Builder must never run the CLI against it by default — use `FUND_DATABASE_URL` or the smoke script.
- Loop-mode permission prompts block `VAR=x cmd`, `git --version`, `claude --version` and
  multi-op shell lines; plus the guard's `loop` substring rule (P-0001). Survey tooling should be
  scripts run as one `uv run python …` command.

## 2. What exists

### 2a. Physics — `app/`, `mcp_server/`, `migrations/` (S-003a, cycle 4)

Every file read (~7 000 lines). Measurements: `uv run python scripts/survey_probe_physics.py`
(temp DB, never `fund.db`); results quoted as **P1–P9** below.

| Module | Lines | TRD | What it is | Status vs TRD |
|---|---|---|---|---|
| `main.py`, `cli.py`, `config.py`, `logging_setup.py` | 485 | §3, §4, §10 | FastAPI app + request-audit middleware; argparse CLI (`init-db`, `seed-admin`, `create-pod`, `fund-pod`, `check-orders`, `rebuild-state`, `serve`); `config.yaml` < `FUND_*` env | ✅ — but the audit log has no *who* (agent id), which §10 asks for |
| `clock.py` | 46 | §9 | `Clock` protocol, `LiveClock`, `get/set_clock` | live only (Phase 3) |
| `scheduler.py` | 87 | §3, §8.4 | APScheduler: pending-limit sweep, live mode only | ✅ |
| `db/` | 427 | §5 | ORM models for all 10 TRD tables; `UTCDateTime` (aware UTC in/out); engine built **at import time** | ✅ all tables; **no `run_id` column anywhere** (§9) |
| `ledger/` | 359 | §5, P4 | `append_event`, reducers (`allocation_set`, `order_filled`), incremental `apply_event_to_db`, `rebuild_state()` | ✅ for `positions` + `cash_balances` only (see §4) |
| `registry/` | 423 | §6 | agents, pods, SHA-256 API keys, `has_permission` matrix (exactly TRD §6 + `READ_MESSAGES`/`REPORT_*` universal), `require`/`deny` → 403 + `permission_denied` event | ✅ |
| `oms/` | 1047 | §8 | market/limit orders, fee 0.1% both sides, rejection = stored order + system message, partial sells, realised P&L, `OMS_LOCK`, pending monitor, portfolio view | ✅ all five §8 rules |
| `marketdata/` | 466 | §3, §7, §9 | `MarketDataProvider` ABC, `StaticProvider`, `YFinanceProvider` (clock-keyed cache) | ✅ live; look-ahead guard is OHLCV-only and wrong for daily bars (§4) |
| `bus/` | 541 | §7 | `agent:<id>`/`pod:<id>`/`broadcast`, PM broadcast → own pod, one visibility predicate, `after_id`/`before_id`/`latest` cursors | ✅ no restriction to a "central pod" exists in physics (answers 04_FIRM §11 row "chat seems restricted": not here — look in OpenClaw config, S-005) |
| `metrics/` | 1020 | §7 | self-reported costs/tasks; TWR, Sharpe, max DD, hit rate, cost-adjusted P&L, leaderboard from a per-day ledger replay | ✅ fields; Sharpe scale is off (§4) |
| `api/` | 1198 | §7 | 8 routers, 20 operations | all §7 v1 endpoints except Phase 3 ones (`POST /clock/mode`, `/clock/advance`, `/allocations`, meetings); extra: `GET /me` |
| `mcp_server/` | 711 | §3, §13 | one tool per operation (20), `TOOL_ROUTES` checked against OpenAPI by the suite; stdio; one key = one identity | ✅ — names differ from paths (`whoami` ↔ `/me`), TRD said "identical names" |
| `migrations/` | 343 | §4 | 3 alembic revisions (initial, Phase 1 order fields + indexes, Phase 2 indexes) | ✅ **P1: 0 differences** between `alembic upgrade head` and the ORM models |

Missing against the TRD (all known Phase 3/4 work, already in BACKLOG B-004…B-006): backtest
clock + `/clock/*`, `run_id` scopes, allocation endpoint, meetings, UI. Missing and *not*
in the backlog: an endpoint for an agent to read its own tasks/costs (see §5).

## 3. What works (evidence)
- Suite: 267 passed + 9 strict-xfail (cycles 1–3, ≥3 runs each).
- Starts and serves outside pytest: `scripts/smoke_run.py` 12/12 (§1).
- Schema from migrations == schema from models (P1).
- Identity cannot be forged: attribution of orders, costs, tasks, messages comes from the API key,
  never the body (read: `oms/service.py`, `metrics/reporting.py`, `bus/messages.py`); red-team
  0001/0002 found no impersonation or permission bypass.
- One money implementation: live fills and `rebuild_state` share `ledger/reducers.py`.

## 4. What's broken

### 4a. Physics (S-003a) — new findings, each measured or read with file:line
1. **Rebuild ≠ live when the clock moves backwards** (P3, measured). Live state is folded in
   insertion order (`ledger/apply.py`); `rebuild_state` and the equity curve replay in
   `(ts, id)` order (`ledger/rebuild.py:25`, `metrics/equity.py:199`). Buy at 10 June, then a
   backtest clock at 5 June sells: live has no position, rebuild has **10 phantom shares**.
   Second cause (auditor): the sell reducer silently drops a position that goes *negative*
   (`ledger/reducers.py:90-92`, `qty <= 1e-9`), so an impossible history is erased instead of
   caught. Mostly latent — Phase 3 (`run_id` scopes, backtests after live) is when the clock goes
   back — but `LiveClock` reads `datetime.now` (`clock.py:32`), which is not monotonic, so an NTP
   step back between two fills could trigger it live. Plain id-order replay is not enough: the
   equity curve buckets events into days by `ts` (`metrics/equity.py:215`). → **B-016**
2. **Look-ahead through daily bars** (read). `YFinanceProvider.get_ohlcv` drops bars with
   `ts > as_of` (`yfinance_provider.py:165`), but a daily bar is stamped at its *open*
   (00:00 exchange time) and carries that day's *close*. At simulated 12:00 on day D the agent
   sees D's close. `StaticProvider` has the same comparison (`static_provider.py:70`) but leaks
   nothing (its bars are flat at the current quote). The equity curve is exposed only when it
   uses closes for "today" (`live_price=False`, or backtest — `equity.py:154-167`). Any Truman
   provider built on this guard inherits the leak. Guard must use the bar's *end* time. → **into B-005**
3. **Live price ignores `as_of` and misstates its timestamp** (read).
   `YFinanceProvider._fetch_price` returns today's quote for any `as_of` and stamps it
   `as_of=<requested time>` (`yfinance_provider.py:100-106`), contradicting `Quote.as_of`
   ("the provider's stamp, not the moment we asked"). Harmless live; in a backtest it would be
   silent look-ahead. B-008 (Truman provider) must not reuse this path. → **into B-005/B-008**
4. **Annualised Sharpe understated ~15%** (P8, measured). The equity curve has one point per
   *calendar* day (`metrics/equity.py:234-255`; weekends = carried close = 0% return), but
   `annualise` scales by √252 *trading* days. On a synthetic seeded series (not fund data):
   1.487 true vs **1.256** reported — ×0.845 ≈ √(5/7). `sharpe_daily` is per calendar day too.
   √365 on the calendar series would give ≈1.017× the truth, not exactly 1 — trading-day points
   are the cleaner fix. Rankings are unchanged (monotone), absolute values are wrong — an
   honest-measurement bug (Art. 9). → **B-017**
5. **Pod creation and the `system` agent leave no event** (P2, measured: 0 events each).
   `registry/pods.py:27`, `registry/service.py:101`. `pods.current_allocation` and the
   `allocations` rows are mutated in place and not rebuilt by `rebuild_state`; nor are
   `orders`, `messages` (B-000e), `costs`, `tasks`, `agents`. TRD §5 only demands positions +
   cash be rebuildable; CLAUDE.md says "every state change is an event". Decide the scope of
   rebuild before Era II's generations reset state. → **B-018**
6. **`POST /agents/register` with a missing `pod_id` → 500** (P5). FK `IntegrityError` is
   unhandled (raised by the flush at `registry/service.py:58`). Management-only, low. A PM with **no** pod is accepted
   (P6, 201) and can never trade. → **B-019**
7. **Non-finite `limit_price` is stored and then misreported** (P4). `1e309` parses to `inf`,
   passes `gt=0`, is stored as a rejected order — and the API returns `limit_price: null`, so it
   reads back as if it were a market order. The `order_placed` event payload holds the `inf`
   too, which Python's JSON writes as non-standard `Infinity` — the ledger itself is no longer
   portable JSON. Same root cause as B-000d (`allow_inf_nan`). → **widen B-000d**
8. **Agents are told to use a clock they may not read** (P7). `GET /clock` needs
   `read_cross_pod` (`api/clock.py:22`; TRD §7 says management/system), so an analyst or PM gets
   403 — but the MCP `get_clock` tool tells *every* agent "use this rather than your own clock"
   (`mcp_server/tools.py:471-478`). In backtest mode a PM would have no legitimate way to learn the
   simulated date. The TRD is explicit here, so this is a decision, not a bug fix: either widen
   the read (needs an ADR against TRD §7) or correct the tool's docstring. → **B-020**
9. **`mcp_server` imports the whole physics** (P9: 35 `app.*` modules incl. `app.db.base`, which
   builds an engine on the fund DB URL at import). Cause: `tools.py:30` imports
   `MAX_TOKENS_PER_REPORT` from `app.metrics.reporting`. Contradicts `mcp_server/client.py`'s
   docstring ("Nothing in this package imports app"). The dependency law (03_WORLD §1) does not
   place `mcp_server` yet — B-002 must. → **into B-002**

Smaller notes (no backlog item; fix when touching the file): request audit log has no agent id
(`main.py:62`); `cancel_order` docstring says management may cancel, the code forbids it
(`oms/service.py:478`); `monitor.py` docstring calls `<=`/`>=` "strict inequalities";
`GET /events` returns the *oldest* `limit` events with only a time cursor — needs `after_id`
before backtests (same reason the bus has one); `_pod_events` loads every fill of every pod to
filter one pod in Python (`metrics/equity.py:196`) — O(pods × fills) per leaderboard call;
`count_messages_sent_by_pod` attributes by the sender's *current* pod; `fund_pod` validates
nothing (withdrawal beyond cash, non-finite `delta` — `registry/pods.py:45-80`) and B-006 plans
to reuse it unchanged; Starlette deprecates `HTTP_422_UNPROCESSABLE_ENTITY` (12 suite warnings).

## 5. What's dead

### 5a. Physics (S-003a)
Exported, never called: `registry.service.count_agents`, `metrics.reporting.list_costs`,
`list_tasks`, `oms.service.get_order`, `EquityCurve.latest_equity`. `list_tasks`/`list_costs`
are not dead ideas — they are a **missing endpoint**: an agent that restarts cannot find its
own open task ids. Keep; expose in Era I (→ **B-021**). Nothing to delete in `app/`.

## 6. Risks (physics)
- Floats for money everywhere (cash, qty, prices). Fine at today's scale; P3-style replay
  checks compare floats with tolerances. Revisit if a `Decimal` boundary is ever needed.
- The engine and settings are module-level singletons built at import; anything that imports
  `app` binds to `FUND_DATABASE_URL` *at that moment* (why the probe sets env vars first).
- The ledger is append-only by convention, not by mechanism (no trigger, no hash chain).
  Agents cannot write SQL, so this is a Builder-discipline risk, not an agent one.

## 7. Surprises
- The physics is better than "Phase 2 done" suggests: one money implementation, one permission
  matrix, one visibility predicate, nulls instead of fake zeros — the conventions in CLAUDE.md
  are real in the code.
- Its weak spot is **time**: three of the nine findings (replay order, daily-bar look-ahead,
  live price ignoring `as_of`) only bite once the clock can move — Era I's first job.

## 8. What this changes in the backlog
New: B-016 replay order · B-017 Sharpe annualisation · B-018 rebuild scope · B-019 register
pod validation · B-020 clock readable by all roles · B-021 own tasks/costs endpoint.
Widened: B-000d (all non-finite floats), B-005 (bar-end look-ahead; quote `as_of`), B-002
(`mcp_server` placement). Rest of repo (tests, scripts, docs, legacy, root files) → S-003b.
