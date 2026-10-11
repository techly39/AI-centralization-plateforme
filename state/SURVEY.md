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

### 2b. Everything else — tests, scripts, docs, legacy, root (S-003b, cycle 5)

Every file read (~6 800 lines). Measurements: `uv run python scripts/survey_probe_repo.py`
(the probe itself imports no `app` and writes nothing — R2's `pytest --collect-only` subprocess
does import it; opens `fund.db` only `mode=ro&immutable=1`, prints no key) —
results quoted as **R1–R4**.

**Tests** — 276 collected = 267 + 9 strict-xfail (R2). Per area:

| Area | Files (tests collected) | TRD demand | Verdict |
|---|---|---|---|
| Phase 0 | `test_permissions` (36), `test_registry` (10), `test_ledger_replay` (3), `test_config` (6), `test_clock_and_health` (3) | permissions, ledger replay | ✅ |
| Phase 1 | `test_oms_market_orders` (18), `_limit_orders` (14), `_fees` (12), `_permissions` (7), `_replay_consistency` (3), `_concurrency` (1), `test_portfolio` (11), `test_marketdata` (18) | market fill, limit fill, rejection, partial sell, fee math | ✅ all five |
| Phase 2 | `test_messaging` (22), `test_reporting` (13), `test_metrics` (14), `test_performance_math` (16), `test_mcp_server` (11), `test_poc_milestone` (2) | bus, costs, metrics, MCP; POC re-run | ✅ — but see the milestone note below |
| Red team | `test_redteam_0001` (43), `_0002` (13) | — (Bible) | 56 tests = 20% of the suite; 9 strict xfails = the open holes |
| Fixtures | `conftest.py`, `support.py` (`FrozenClock`, `HistoricalProvider`) | — | in-memory SQLite + StaticPool, offline prices, scheduler off: no test touches the network or `fund.db` |

What the suite does **not** guard (no test anywhere): the dependency law (B-002); a clock that
moves backwards (B-016); bar-*end* look-ahead (B-005); determinism of a run; "the app starts"
(only `smoke_run.py`, outside the suite — X-004); endpoint coverage is asserted for MCP tools
only, never measured for tests (no coverage tool installed).

**Scripts** — `agent_console.py` (769), `setup_demo_firm.py` (136), `smoke_run.py` (143) import
`mcp` + stdlib only: true clients, as `scripts/README.md` says. `survey_probe_physics.py` and
`survey_probe_repo.py` are Builder measurement tools. ✅

**Docs** — `oms_migration.md` (POC → Phase 1 mapping) ✅ accurate.
`phase2_bus_costs_mcp.md` ✅ except one sentence made false in cycle 2: "it imports nothing from
`app` except the settings object" (P9). Root `README.md`: Phase 0–2 status accurate; its Layout
omits `bible/ state/ governance/ loop/ scripts/ experiments/`, and lists `ui/` as if it existed.

**Legacy** — `legacy/README.md` + `legacy/oms_poc/` (`OMS.py` 322, requirements, `Portfolio.json`,
a pending-order template, one processed order + result, a 148-byte log). Not imported anywhere. **Keep** (05_ERAS: archive unless there is a
reason): `test_poc_milestone.py` cites its fills as the milestone's ground truth, and
`Logs/oms.log` records where the OpenClaw POC lived —
`~/.openclaw/workspace/OCT/AI Hedgefund POC/OMS/` — a lead for S-005.

**Root files** — `pyproject.toml`, `uv.lock`, `alembic.ini`, `config.yaml`, `.python-version`,
`.gitignore` ✅ (`httpx` listed in both main and dev deps — harmless). Odd files:

| File | Tracked | What it is | S-004 verdict |
|---|---|---|---|
| `test_api.py` | yes | Human's manual try-out script (its own header says "in no case a viable test"); `requests` is not a declared dependency, only transitive via yfinance (R3); outside `testpaths`, never collected (R2). **Contains a hard-coded API key** — §4b.1 | remove from the tree |
| `.vscode/settings.json` | yes | one personal editor setting | untrack, ignore `.vscode/` |
| `ui/` | no (empty dir) | Phase 4 placeholder; git cannot see it | delete locally; README stops listing it |
| `.DS_Store`, `legacy/.DS_Store` | no (ignored) | Finder junk | delete locally |
| `agents.local.json` | no (ignored, mode 600) | demo agent keys from `setup_demo_firm.py` (not read) | keep — the Human's |
| `fund.db` | no (ignored) | the Human's August history | keep, never write |

R4: no tracked file is excluded by the current `.gitignore`.

## 3. What works (evidence)
- Suite: 267 passed + 9 strict-xfail (cycles 1–3, ≥3 runs each).
- Starts and serves outside pytest: `scripts/smoke_run.py` 12/12 (§1).
- Schema from migrations == schema from models (P1).
- Identity cannot be forged: attribution of orders, costs, tasks, messages comes from the API key,
  never the body (read: `oms/service.py`, `metrics/reporting.py`, `bus/messages.py`); red-team
  0001/0002 found no impersonation or permission bypass.
- One money implementation: live fills and `rebuild_state` share `ledger/reducers.py`.
- The suite is hermetic: in-memory DB per test, offline prices, no scheduler (§2b); every TRD
  Phase 0–2 test demand has named tests.

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

### 4b. Everything else (S-003b)
1. **A live management key is committed and pushed** (R1, measured). `test_api.py:10` holds an
   `fk_…` key whose SHA-256 matches agent `id=1 name='management' role=management
   status=active` in the Human's `fund.db`; the file is in one commit, reachable from origin.
   Blast radius is small — the key opens only the Human's local August database, through a
   server bound to 127.0.0.1, holding fake money — but anyone with repo access holds a
   management identity for that DB, and the pattern (a key pasted into a tracked file) is
   exactly what must never happen once firm agents hold keys. Removing it from `main` does not
   revoke it (history keeps it; no force-push, Art. 7). Revocation means writing `fund.db` —
   the Human's call (Q-0003). Origin's visibility (public/private) not verified: `gh repo view`
   needs a permission prompt in loop mode. → **S-004** (remove), **B-022** (secret-scan test).
2. **The Phase 2 milestone is scripted, not agent-run** (read). TRD: "re-run the existing
   OpenClaw single-pod POC **through the app only**". `test_poc_milestone.py` replays the POC's
   four fills as HTTP calls written by hand — no OpenClaw, no model. It proves the app can carry
   the POC's day; it does not prove an agent can. Honest status: Phase 2 milestone **met by
   script**; the agent half is Era I's (B-012/B-014/B-015).
3. **The test price feed has the same look-ahead as yfinance** (read). `tests/support.py`
   `HistoricalProvider.get_price` returns the close of `as_of.date()` at any hour (`:82`) and stamps
   it with the requested time (`:85`); `get_ohlcv` stamps bars at 00:00 (`:104`) and filters
   `ts <= as_of` (`:114`) — §4a.2/§4a.3 in the test double. Its docstring promises "a test cannot
   accidentally prove something using tomorrow's price" — true for tomorrow, not for today's
   close. Metrics tests and the POC milestone run on it. → **into B-005**: fix the double with the
   real providers, or tests will certify the leak.
4. **Tests that encode a decision still open** (read). `test_clock_and_health.py:22`
   (`test_clock_forbidden_for_analyst`) is TRD §7 written as a test; if B-020's ADR widens the read,
   that test changes *with the ADR as its reason*, not to go green. `test_performance_math.py:89`
   checks √252 on `annualise` alone — still right after B-017 if the curve moves to trading days.
5. **Stale words** (read). `docs/phase2_bus_costs_mcp.md:139-140` (MCP imports only settings — false
   since cycle 2); README Layout (§2b); `bible/03_WORLD.md:43` and `bible/05_ERAS.md:33` say "218
   tests" (276 collected). → S-004 (docs), S-006 (Bible).

Smaller: `conftest.py` `make_pod` inserts pods directly with the system clock (`:145`), bypassing
`create_pod` — consistent with P2 (pods unledgered) today, but B-018 must update it if pod
creation becomes an event; `test_marketdata.py:245` uses the system clock to build "the future"
(fine while the clock is live).

## 5. What's dead

### 5a. Physics (S-003a)
Exported, never called: `registry.service.count_agents`, `metrics.reporting.list_costs`,
`list_tasks`, `oms.service.get_order`, `EquityCurve.latest_equity`. `list_tasks`/`list_costs`
are not dead ideas — they are a **missing endpoint**: an agent that restarts cannot find its
own open task ids. Keep; expose in Era I (→ **B-021**). Nothing to delete in `app/`.

### 5b. Everything else (S-003b)
No dead code in `tests/` or `scripts/` (every helper in `support.py`/`conftest.py` is used).
Dead weight: `test_api.py` (never collected, superseded by `agent_console.py` and the smoke
script), empty `ui/`, `.DS_Store` ×2. `legacy/` is archive, not dead (§2b).

## 6. Risks (physics)
- Floats for money everywhere (cash, qty, prices). Fine at today's scale; P3-style replay
  checks compare floats with tolerances. Revisit if a `Decimal` boundary is ever needed.
- The engine and settings are module-level singletons built at import; anything that imports
  `app` binds to `FUND_DATABASE_URL` *at that moment* (why the probe sets env vars first).
- The ledger is append-only by convention, not by mechanism (no trigger, no hash chain).
  Agents cannot write SQL, so this is a Builder-discipline risk, not an agent one.
- Credentials in tracked files (§4b.1). Today: one key, local DB, fake money. In Era I every firm
  agent holds a key and an OpenRouter key exists — nothing in the repo stops a paste. → B-022.
- Test doubles inherit the physics' assumptions (§4b.3): a fix to a provider that skips the
  double leaves the suite certifying the old behaviour.

## 7. Surprises
- The physics is better than "Phase 2 done" suggests: one money implementation, one permission
  matrix, one visibility predicate, nulls instead of fake zeros — the conventions in CLAUDE.md
  are real in the code.
- Its weak spot is **time**: three of the nine findings (replay order, daily-bar look-ahead,
  live price ignoring `as_of`) only bite once the clock can move — Era I's first job.
- The one real secret leak was in the file the Bible flagged only as "odd" (`test_api.py`).
- "Phase 2 milestone done" meant "done by a hand-written script"; no model has yet traded
  through this app.

## 8. What this changes in the backlog
New: B-016 replay order · B-017 Sharpe annualisation · B-018 rebuild scope · B-019 register
pod validation · B-020 clock readable by all roles · B-021 own tasks/costs endpoint.
Widened: B-000d (all non-finite floats), B-005 (bar-end look-ahead; quote `as_of`), B-002
(`mcp_server` placement). Rest of repo (tests, scripts, docs, legacy, root files) → S-003b.

S-003b (cycle 5): New **B-022** secret-scan test. **S-004** now has a concrete list (§2b table +
§4b.5 docs). Widened: B-005 (`tests/support.py` `HistoricalProvider`), B-018 (`conftest.make_pod`),
B-020 (`test_clock_forbidden_for_analyst` changes only with the ADR). New question **Q-0003**
(revoke the committed key). S-006 gets the "218 tests" corrections.
