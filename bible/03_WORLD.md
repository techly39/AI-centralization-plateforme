# 03 — The World: architecture

Living book: the Builder may change it, with a decision logged in `07_DECISIONS.md`.

## 1. Repository map (target)

```
firm app/                      (git: origin = AI-centralization-plateforme)
  CLAUDE.md                    Builder entry point (auto-loaded every session)
  bible/                       this Bible. 00, 01 human-only. 09 = the Builder's own vision.
  governance/                  HUMAN-ONLY. human.yaml (caps, gates), HALT (stop file)
  state/                       Builder's memory + lab notebook (see 06_LOOP.md)
  loop/                        HUMAN-ONLY. run_forever.sh, preflight.py, seal.sh
  .claude/                     Builder tooling: settings.json + hooks (human-only),
                               agents/, commands/, skills/ (Builder may extend)

  app/                         S2 PHYSICS — exists (Phases 0–2 done)
  mcp_server/                  MCP wrapper over app API — exists
  runtime/                     S3 RUNTIME — new (Era I)
  truman/                      Data world — new (Era I)
  quant/                       Quant Lab — new (Era III, minimal pieces earlier)
  ui/                          Observatory — Era II (TRD Phase 4)
  experiments/                 experiment specs (YAML) + result folders
  scripts/                     operator tools — exist
  tests/                       pytest, one suite for the whole repo
  TRD_ai_fund_environment.md   detailed spec for physics (still authoritative for app/)
```

### Dependency law (enforced by `tests/test_boundaries.py` since cycle 10, ADR-022)

```
runtime ──HTTP/MCP──▶ app ──imports──▶ quant, truman   (pure, deterministic libraries)
ui ──HTTP──▶ app
mcp_server ──HTTP──▶ app       (imports only app.config + app.limits — ADR-022)
scripts ──MCP/HTTP──▶ app      (except named in-process probes on a throwaway DB)
nothing imports runtime or legacy;  app never imports runtime, ui, mcp, or any LLM SDK
quant and truman never import app
```

`app/` must never import `anthropic`, `openai`, `openrouter`, or any agent framework.
The test fails the build if it does — statically (every import in the source) and
dynamically (what importing physics actually loads). Every top-level Python directory
must be placed in the law, or the test fails.

## 2. Physics (`app/`) — what exists and what it must grow

**Exists and works (218 tests green at Bible writing; 267 passed + 9 strict xfails at the
Survey, SURVEY §2b):** config, injected clock (live),
append-only event ledger + `rebuild_state()`, registry + API-key auth + permission
matrix, `GET /me`, OMS (market/limit, fees, rejections with auto-message, partial
sells, realised P&L), market data (yfinance + static), bus (agent/pod/broadcast,
`after_id`, `latest`, `before_id`), cost & task self-reporting, metrics (TWR, Sharpe,
max DD, hit rate, cost-adjusted P&L, leaderboard), MCP server with one tool per
endpoint (tested against OpenAPI).

**"Works" with known holes (Survey, `state/SURVEY.md` §2a/§4a/§4b; the full list is the
backlog's physics section), e.g.:** time is the weak spot —
rebuild ≠ live under a backwards clock (B-016), daily bars leak the day's close (B-005;
the test double `HistoricalProvider` leaks the same way, so the suite would certify it),
quotes ignore `as_of`, Sharpe is annualised on calendar days (×0.845, B-017), `/clock`
is 403 for the agents the MCP tool tells to use it (B-020). Pod creation and the `system`
agent write no event, and several tables are not rebuilt from the ledger (B-018).
Non-finite floats (`limit_price=1e309`) reach the ledger as `Infinity` (B-000d); a missing
`pod_id` on register is a 500 (B-019). `mcp_server` imports most of `app/` through one
constant (SURVEY §4a.9 — B-002 places it in the dependency law). The Phase 2 milestone
("re-run the POC through the app") was met **by a hand-written script**, not by an agent
(SURVEY §4b.2): no model has traded through the App yet.

**Must grow (by Era):**

| Capability | Era | Notes |
|---|---|---|
| Halt: `governance/HALT` → all agent writes refused, `GET /halt` | I | **Done cycle 11** (ADR-023, `tests/test_halt.py`): 423 + `halt_refused`, every role; monitor idle. |
| Simulated clock, `/clock/advance`, look-ahead guard, `run_id` scopes | I | TRD Phase 3 |
| Allocation endpoint, meeting packages | I | TRD Phase 3 |
| Truman as a `MarketDataProvider` | I | data world behind the existing interface |
| System-reported costs (from metered keys) override self-reports | I | see §4 |
| World events table (Truman injections, law changes) visible to agents | I | Art. 10.2 |
| Risk engine: drawdown ladder, exposure/concentration limits, reduce-only mode | II | `04_FIRM.md` §5 |
| Allocation algorithm (deterministic) | II | `04_FIRM.md` §6 |
| Generations: epoch boundaries, reset, fitness snapshot | II | `04_FIRM.md` §7 |
| Agent lineage + budgets per agent/pod (compute treasury) | II–IV | |
| Validation gates as physics (capital requires passing) | III | `04_FIRM.md` §4 |
| Strategy registry + sandboxed backtest runs (trial counting) | III | |
| Laws table: firm rules as versioned data the physics reads | V | `04_FIRM.md` §9 |
| Internal credits, contracts, information market | V | |
| Multi-firm, endogenous price impact, exchange/regulator hooks | VI | |

## 3. Runtime (`runtime/`)

A separate process (`uv run fund-runtime`), deterministic, no LLM logic of its own.

- **AgentSpec** (the genome, stored in the App, mirrored to files):
  `id, name, role, pod, parent_id, generation_born, adapter, model, charter (text),
  tools, memory_policy, budget_usd, wake_policy, mutations[]`.
- **Scheduler:** driven by the App clock. In live mode: wake policies (cron-like,
  event-triggered: "new message", "order filled", "world event"). In backtest mode:
  for each `/clock/advance` step, wake the agents whose policy fires, wait until they
  report done (or time out), then advance. This is what makes "6 months in hours" possible.
- **Workflows ("exe"):** each is a deterministic state machine in `runtime/workflows/`:
  `onboarding`, `pitch`, `daily_cycle`, `backtest`, `meeting`, `generation_turnover`,
  `spawn_worker`, `post_mortem`. Workflows call agents; agents never call workflows
  except through App endpoints that enqueue them.
- **Context assembly:** what an agent sees on waking = its charter + `/me` + its memory
  + the workflow's package (e.g. the App's meeting package). Assembled by code, logged.
- **Adapters:** `openclaw` (standard + conformance: `08_OPENCLAW.md`), `native` (see `02_SCALES.md`). Same tool surface, same keys.
- **Recording ("cassettes"):** every LLM request/response of every agent is stored
  (`runs/<run_id>/llm/…` or a table), hashed and linked to events. Uses:
  replay a run exactly without paying, audit why an agent did something, study scales.
- **Halt:** checks `governance/HALT` before every wake and every tool call batch.

## 4. Metering — the cost problem (Requirements §11)

Today the whole fund uses one LLM key, so per-agent cost is a self-reported guess.
Target:

1. **Era I:** each firm agent gets its own **OpenRouter key created with the
   provisioning API**, with a per-key credit limit derived from its budget. The firm's
   total of limits never exceeds `governance/human.yaml: firm.monthly_llm_usd_cap`.
   If the cap is `null`, the Runtime refuses to provision keys or wake agents.
2. A **cost-sync job** (in Runtime) pulls per-key usage and posts it to the App as the
   `system` agent. System-reported cost is authoritative; self-reports stay as a
   cross-check (the gap between them is itself a finding).
3. **Era III+, if needed:** a local OpenAI-compatible **meter proxy** (prefer an existing
   one such as LiteLLM proxy over writing one) for model routing, caching, and
   recording cassettes centrally.
4. The Builder's own usage (Claude Code) is separate: bounded by
   `builder.max_cycles_per_day` in `governance/human.yaml`.

Provisioning credentials (the management key for OpenRouter) live only in a gitignored
local file / env var that the Human creates. If it is missing, the Builder builds and
tests everything against a fake provider and writes the need into `state/QUESTIONS.md`.

## 5. Truman — the data world (`truman/`)

The agents never fetch data themselves (Requirements §9). They get what Truman serves.

- **Data packs**, each versioned and hashed:
  1. prices only (real history, 1999–2026, via yfinance cache stored locally);
  2. fake company data (synthetic fundamentals for invented tickers);
  3. fake headlines + descriptions (scripted news);
  4. everything together; with a configurable **noise level**.
- **Scenarios:** a calendar of world events (`Mon: headline X to everyone; Wed: CEO
  fraud rumour to pod 2 only; Thu: −8% gap`). Deterministic, seeded.
- **Scripted behaviour tests:** "we know what must come out" — a scenario plus
  expected agent behaviour (e.g. after the fraud headline, the exposed PM reduces the
  position within 2 sim-days). Used to test agents, prompts, and models.
- **Bootcamp:** 10–15 economic regimes (2000 dot-com bust, 2008 GFC, 2013 taper,
  2020 crash, 2022 rate shock, a synthetic hyperinflation, a synthetic flat-vol world…),
  each ~6 months of sim time, run in hours of real time.
- **Model exam:** a fixed scenario battery any new model must pass before entering the firm.
- **Look-ahead guard** is physics: Truman serves through the App's `MarketDataProvider`,
  which refuses any timestamp beyond simulated now.

## 6. Quant Lab (`quant/`)

Pure, deterministic Python. Imported by the App, exposed to agents via App endpoints.

- **Strategy interface:** `strategy(data_view_until_t, state) -> target_weights` — the
  strategy is a function, isolated, so it can be backtested on 1999–2026 and on any
  Truman pack (Requirements §5).
- **Backtester:** event-driven over the same fee model as the OMS.
- **Validation metrics:** IC (rank IC, mean, t-stat, by regime), Deflated Sharpe Ratio
  (Bailey & López de Prado) using the **true trial count** recorded by the App,
  capacity estimate (alpha decay vs. capital under a simple impact model), correlation
  to every live pod.
- **Barra-lite factor model:** daily cross-sectional regression on market beta, size,
  value, momentum, low-volatility, sector dummies → factor exposures, factor returns,
  specific return; return attribution per pod (β, factor bets, timing, pure α).
- **Sandbox for agent code:** agents (engineers) submit strategy code; the App runs it
  in a subprocess with no network, CPU/memory/time limits, read-only data view.

## 7. Observatory (`ui/`)

TRD Phase 4 stack (FastAPI + Jinja2 + htmx). Read-only views: message feed, pod
portfolios, cost-adjusted leaderboard, event explorer. Grows to: generation timeline,
lineage tree, social graph of messages, findings browser, run replay.
Human controls (Era II+): halt toggle, approve/reject pitches while the Human still
holds that gate, read `state/REPORT.md`.

## 8. Where things run

Everything runs on the Mac mini with `uv run`. No Docker, no cloud (TRD §12) unless a
decision in `07_DECISIONS.md` changes that. OpenClaw runs on the same machine.
