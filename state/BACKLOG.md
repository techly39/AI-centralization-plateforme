# BACKLOG — ordered. Each item serves an exit criterion of the current Era.

## Physics bugs (Art. 8 — Builder's bugs; priority 2, allowed during the Survey)
Each red-team hole has a strict-xfail test in `tests/test_redteam_0001.py`; fix = remove the marker.
- [x] **B-000c** (high) Token-sum overflow DoS — cycle 2: per-report cap 1e8 + `TOTAL` sum (ADR-018).
      Also closed the tokens > int64 part of B-000d.
- [ ] **B-000d** Non-finite floats: reject inf/NaN/1e308 on **every** float input → clean 422
      (3 xfail tests on `usd_cost`; SURVEY §4a.7: `limit_price=1e309` is stored and read back as
      `null`, and its event payload is written as non-standard JSON `Infinity`). Likely one fix:
      `allow_inf_nan=False` on the API schemas, plus `append_event` refusing non-finite payloads
      so the ledger stays portable JSON. Consider IDEAS "physical-units types".
- [ ] **B-019** (low) `POST /agents/register` with a missing `pod_id` → 500 (FK error unhandled);
      PM without pod accepted (can never trade). → 404/422. SURVEY §4a.6, probe P5/P6.
- [ ] **B-000m** (low) Integer path params ≥ 2⁶³ → 500 (`GET /metrics/pod/{2**63}`; likely every
      `/{id}` route) → `tests/test_redteam_0002.py::test_hole_metrics_pod_id_beyond_int64_500`.
- [ ] **B-000n** (low) Cost-report rate is unbounded per agent (spam inflates rows; token totals
      lose exactness past ~9e7 max-size reports). Decide on a per-agent rate law.
- [ ] **B-000e** Message `body` + `structured_payload` on the `message_sent` ledger event, so the
      messages table is rebuildable (CLAUDE.md: every state change is an event).
- [ ] **B-000f** 'system' identity looked up by role/reserved name, not a squattable name.
- [ ] **B-000g** Size caps on `structured_payload` and task `outcome`.
- [ ] **B-000h** MCP client: URL-escape path params.
- [ ] **B-000b** A test that proves `OMS_LOCK` is load-bearing (F-0001), e.g. race injected between
      cash read and write, or run against a row-locking backend; or document the lock as defence-in-depth.
- [ ] **B-000i** `.gitignore`: cassettes + `experiments/*/runs/` before Era I records anything.
- [ ] **B-000j** Decide whether `state/loop_status.json` is tracked (runner state) — auditor note.
- [ ] **B-000k** Costs from pod-less agents (management) appear on no leaderboard → firm-level spend.
- [ ] **B-000l** MCP API base URL must be loopback (conformance check for Era I).

## Era ½ — The Survey (first run: clean and understand — NO features)
- [x] **S-001** Toolchain + run check — cycle 3: SURVEY §1; `scripts/smoke_run.py` 12/12 PASS.
      Leftover: `git --version` not captured (loop-mode permission prompt) → note in S-007.
- [x] **S-002** Git hygiene — cycle 1: Phase 2 + Bible/harness committed and pushed; flaky
      concurrency test fixed (F-0001); red-team pass recorded (F-0002).
      Remaining .gitignore gap → B-000i.
- [x] **S-003a** Repo survey, physics: `app/`, `mcp_server/`, `migrations/` — cycle 4: SURVEY §2a–8,
      9 findings (P1–P9 via `scripts/survey_probe_physics.py`) → B-016…B-021, B-000d/B-002/B-005 widened.
- [ ] **S-003b** Repo survey, the rest: `tests/`, `scripts/`, `docs/`, `legacy/`, root files; map to
      TRD + Bible; odd files (`test_api.py` at root, empty `ui/`, `.DS_Store`, `legacy/`).
      Auditor already spotted: `legacy/oms_poc/Logs/oms.log`, `legacy/oms_poc/Processed orders/*.json`,
      `.vscode/settings.json` tracked. Also: 03_WORLD §2 says "218 tests" (now 267+9) → S-006.
- [ ] **S-004** Cleanup commits (deletions/moves/renames/doc fixes only, each with a reason).
- [ ] **S-005** OpenClaw survey per `bible/08_OPENCLAW.md` §1–2: back up `~/.openclaw` to
      `~/firm-openclaw-backups/`, `openclaw --version`, read that version's docs, write
      `runtime/openclaw/VERSION_NOTES.md`, list agents/bindings/models (no secrets), inventory
      OCT POC workspaces. Change nothing in OpenClaw.
- [ ] **S-006** Correct the Bible where reality differs (living books + PROPOSALS for protected).
- [ ] **S-007** Write `state/SURVEY.md`; seed `state/IDEAS.md`; re-order this backlog.

## Era I — The Desk
- [ ] **B-002** `tests/test_boundaries.py`: dependency law from `bible/03_WORLD.md` §1;
      `app/` imports no LLM SDK / agent framework. Place `mcp_server/` in the law: today
      `import mcp_server.tools` loads 35 `app.*` modules incl. the DB engine, via one constant
      (`MAX_TOKENS_PER_REPORT`) — SURVEY §4a.9. Place `scripts/` too (clients vs the one
      in-process probe, `survey_probe_physics.py`).
- [ ] **B-003** Halt in physics: `governance/HALT` → every state-changing agent request
      refused (409/423 + logged event); `GET /halt`; MCP tool; tests.
- [ ] **B-004** TRD Phase 3a: simulated clock, `POST /clock/mode`, `POST /clock/advance`,
      `run_id` scopes; pending-order monitor runs on every advance. Needs B-016 first.
- [ ] **B-016** Replay order = live order: `rebuild_state` + equity curve replay `(ts, id)`, live
      folds by `id`; a backwards clock gives 10 phantom shares on rebuild (SURVEY §4a.1, P3).
      Shape: per-`run_id` ledgers with timestamps enforced monotonic at `append_event` (id order
      alone doesn't fix the equity curve's day buckets); sell reducer must raise on a sell beyond
      the position, not drop it. Test with a clock that moves back. Before B-004.
- [ ] **B-020** Clock vs agents: MCP `get_clock` tells all agents to use it; PM/analyst get 403
      (P7) — and TRD §7 says `/clock` is system/management only. Decide by ADR: widen the read
      (agents need the simulated date in backtests) or fix the tool docstring. Before B-004.
- [ ] **B-005** TRD Phase 3b: look-ahead guard on every market-data route + red-team pass.
      Must filter bars by their **end** time (a daily bar stamped 00:00 carries that day's close,
      SURVEY §4a.2) and never stamp a quote with the requested time (§4a.3).
- [ ] **B-006** TRD Phase 3c: `POST /allocations`, meeting schedule + package endpoints.
      `fund_pod` (to be reused) validates nothing: add finite `delta`, no withdrawal beyond cash.
- [ ] **B-017** Sharpe annualisation: equity curve is per calendar day, `annualise` uses √252 →
      reported annual Sharpe ×0.845 ≈ √(5/7) of the true value (P8, synthetic series). Prefer
      trading-day points (√365 on calendar points is still ≈1.017× off); `sharpe_daily` must say
      which day it means. Honest-measurement bug (Art. 9).
- [ ] **B-018** Decide rebuild scope: pod creation + `system` agent write no event (P2);
      `pods.current_allocation`, `allocations`, `orders`, `messages`, `costs`, `tasks`, `agents`
      are not rebuilt. ADR: which tables are derived, which are records; before Era II generations.
- [ ] **B-021** `GET /tasks` + `GET /costs` (own; cross-pod for management) + MCP tools —
      `list_tasks`/`list_costs` exist unused; a restarted agent cannot find its open task ids.
- [ ] **B-007** World events table + `system` announcements (law changes, Truman events).
- [ ] **B-008** Truman v1: local cache of real daily history, prices-only pack, one scripted
      scenario, served via `MarketDataProvider`; pack hashing.
- [ ] **B-009** Runtime skeleton (`runtime/`, `uv run fund-runtime`): AgentSpec, scheduler on
      the App clock, halt + cap checks, fake LLM provider for tests.
- [ ] **B-010** Runtime: cassette recording + replay mode.
- [ ] **B-011** Runtime: `daily_cycle` and `backtest` workflows.
- [ ] **B-012** `openclaw` adapter to the `08_OPENCLAW.md` standard: render config + workspace
      (bootstrap files the installed version supports) from AgentSpec, own agentDir + local auth
      profile + metered key, `fund-env-mcp` per agent key via env, deny-by-default tools, no
      bindings, `firm-` namespace; OCT POC charters → AgentSpec templates.
- [ ] **B-012a** Adapter written against mcp 2.x (`is_error`, not `isError`); Runtime stops
      `fund-env serve` with SIGINT (rc 0) — SURVEY §1 findings.
- [ ] **B-012b** Conformance suite: `fund-runtime openclaw doctor` static checks + live probes
      (skipped while firm cap is null); integration tests skip when OpenClaw is absent.
- [ ] **B-013** Metering v1: provisioned per-agent keys (fake provider in tests), cost-sync job →
      system-reported costs; system cost overrides self-report in metrics.
- [ ] **B-014** Verify "chat restricted to central pod" with a two-pod test.
- [ ] **B-015** Era I milestone run: 1 pod, 1-month backtest < 10 min, replay identical.
      Needs a firm cap → ask in QUESTIONS when reached.

## Era ∞ (≤ 1 cycle in 5 during the Launch Pad)
- [ ] **X-001** `state/METRICS.md` summariser script (success rate, turns, durations).
- [ ] **X-002** Skill: `.claude/skills/new-endpoint/` — checklist for schema + permission +
      MCP tool + tests + docs, from the repo's existing patterns.
- [ ] **X-004** Run `scripts/smoke_run.py` in the cycle's verify gate (step 5) — needs a
      `.claude/commands/cycle.md` edit; cheap (~5 s) and catches "tests green, app won't start".
- [ ] **X-003** Suite-stability + mutation check: run the suite N× and flag flaky tests; for each
      invariant-guarding test, a recorded mutant that must make it fail (F-0001).
