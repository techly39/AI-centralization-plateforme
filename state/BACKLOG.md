# BACKLOG — ordered. Each item serves an exit criterion of the current Era.

## Physics bugs (Art. 8 — Builder's bugs; priority 2, same tier as B-002/B-003 — ADR-021)
**Gate:** every open hole below is fixed, or accepted by an ADR with its reason, before any
agent wakes (before B-012's first live conformance probe and before B-015). Order inside the
tier: B-002 + B-003 first, B-000d with or before B-016 (both touch `append_event`), B-000e with
B-018, the rest when cheap or blocking.
Each red-team hole has a strict-xfail test in `tests/test_redteam_000N.py`; fix = remove the marker.
Open strict xfails: 8 (0001: payload size ×2, message content, system squat, MCP path; 0004: fee,
feed price ×2).
- [ ] **B-025** (low, not agent-reachable) Non-finite or absurd prices from the world: a
      NaN/inf provider price (yfinance can) or `config.yaml` value (`fee_rate`, `static_prices`)
      → `append_event` raises → POST /orders 500; in the background sweep one such fill rolls back
      **every pod's fills that tick**, every tick (`app/oms/monitor.py`). Fix: providers refuse
      non-finite prices (→ clean `price_unavailable` rejection); settings `allow_inf_nan=False` +
      upper bounds; sweep isolates per-order failures. Red-team 0004 xfail
      `test_hole_non_finite_feed_price_is_a_500`. With B-005/B-008.
- [ ] **B-026** (low) Fee rounds to cents per order → any order under $5 notional pays $0.00;
      splitting a trade dodges fees; 5e-324-share orders fill. Fix: round fee up (min $0.01/fill)
      and/or a minimum order notional — an honest-measurement law (cost-adjusted ranking). Red-team
      0004 xfail `test_hole_small_orders_pay_no_fee`.
- [ ] **B-027** (low) MCP tool int args (`order_id`, `task_id`, ids, cursors) carry no `ge`/`le`;
      mirror `MAX_ID` from `app/limits.py` so client and physics agree (re-audit note, cycle 12).
      Also `fund-pod --pod-id` / `--delta` unbounded in the CLI (operator-only; ledger refuses
      non-finite).
- [ ] **B-000e** Message `body` + `structured_payload` on the `message_sent` ledger event, so the
      messages table is rebuildable (CLAUDE.md: every state change is an event). With B-018.
- [ ] **B-019** (low) `POST /agents/register` with a missing `pod_id` → 500 (FK error unhandled);
      PM without pod accepted (can never trade). → 404/422. SURVEY §4a.6, probe P5/P6.
- [ ] **B-000n** (low) Cost-report rate is unbounded per agent (spam inflates rows; token totals
      lose exactness past ~9e7 max-size reports). Decide on a per-agent rate law. With B-013.
- [ ] **B-000f** 'system' identity looked up by role/reserved name, not a squattable name.
- [ ] **B-000g** Byte-size caps on `structured_payload` and task `outcome` (depth is capped since
      cycle 12, size is not — 2 xfails in red-team 0001).
- [ ] **B-000h** MCP client: URL-escape path params.
- [ ] **B-000b** A test that proves `OMS_LOCK` is load-bearing (F-0001), e.g. race injected between
      cash read and write, or run against a row-locking backend; or document the lock as defence-in-depth.
- [ ] **B-000j** Decide whether `state/loop_status.json` is tracked (runner state) — auditor note.
- [x] **B-000c** (high) Token-sum overflow DoS — cycle 2: per-report cap 1e8 + `TOTAL` sum (ADR-018).
- [x] **B-000d** Portable JSON — cycle 12 (ADR-024): bounded floats, walked free JSON (finite,
      ints ≤ 2**53−1, depth ≤ 32), NaN-safe 422, `append_event` refuses; red-team 0004: 4 holes fixed.
- [x] **B-000m** Int ids ≥ 2⁶³ → 500 — cycle 12: every agent-supplied id is 1..2**53−1 (ADR-024).

## Era I — The Desk (current; order per ADR-021: seal → time → clock → the rest)
- [x] **B-002** Dependency-law test — cycle 10 (ADR-022; `app/limits.py`; 2 detectors).
- [x] **B-003** Halt in physics — cycle 11 (ADR-023; 423 + `halt_refused`, route-template path;
      monitor checks under `OMS_LOCK`; `GET /halt` + `get_halt`; red-team 0003: 2 holes fixed).
- [ ] **B-023** (low) Halt observability: halt start/end are not ledger events, so the ledger
      cannot explain why fills paused. Option: the App appends `halt_observed` / `halt_lifted`
      the first time a request/sweep sees the file change state. With B-007 (world events).
- [ ] **B-024** (low) `test_held_monitor_sweep_queued_on_lock_does_not_fill_after_halt` waits a
      fixed 1 s; give the monitor a test hook (or a lock-acquired event) so it needn't.
- [x] **B-016** Replay order = live order — cycle 13 (ADR-025): monotonic ts held in the INSERT,
      every replay folds by id, sell beyond/without position raises; red-team 0005: 2 holes fixed.
- [ ] **B-028** (low) `Message.ts`, `Cost.ts`, `Task.started_at/ended_at` take the raw clock,
      not their event's held stamp (red-team 0005; orders fixed cycle 13). Copy `event.ts` like
      `fund_pod`/OMS do. With B-000e (message event carries body).
- [ ] **B-029** (low, operator-only) A forward clock step is permanent under ADR-025 (f): guard
      (refuse or log) a clock far ahead of the ledger floor. Live runs only since ADR-027 (a
      backtest's steps are bounded and recorded).
- [ ] **B-030** (low) `GET /events` pages only by `since` (ts ≥) with cap 1000: a long held
      stretch gives >1000 events on one stamp and management cannot page past them → add an
      id cursor (`after_id`). Also: market price + `now` read before `OMS_LOCK`, so an order
      queued behind a sweep fills at a quote one sweep stale (red-team 0005 notes) — fixed for
      non-live clocks in cycle 15 (re-price under the lock); live keeps the gap. With B-005.
- [x] **B-020** Clock vs agents — cycle 14 (ADR-026): every agent reads `/clock`; `now` is the
      ledger's now (`ledger_now`); control stays closed. Red-team 0006: 1 low hole fixed.
- [x] **B-004a** Backtest clock — cycle 15 (ADR-027): a run is a database (`start-backtest`,
      `run_started`), `POST /clock/advance` (`CONTROL_CLOCK`), sweep on advance, restart resume,
      `append_event` refuses a wrong-run clock. Red-team 0007: 3 medium holes fixed.
- [ ] **B-005** TRD Phase 3b: look-ahead guard on every market-data route + red-team pass.
      **Next — a backtest is not honest until this lands** (`run_started.look_ahead_guard: false`;
      flip `LOOK_AHEAD_GUARD` in `app/run_clock.py`; red-team 0007 confirmed yfinance `get_price`
      ignores `as_of`, so a 2024 run fills at today's quote).
      Must filter bars by their **end** time (a daily bar stamped 00:00 carries that day's close,
      SURVEY §4a.2) and never stamp a quote with the requested time (§4a.3). Fix the test double
      `tests/support.py` `HistoricalProvider` the same way (§4b.3), or the suite certifies the leak.
- [ ] **B-004b** One "now" for physics: metrics `as_of`, market-data defaults, leaderboard read
      `ledger_now`, not `get_clock().now()` (IDEAS c14); a grep test pins it. Then the Phase 3
      milestone: one pod, 1-month backtest, < 10 min real time (a scripted probe, no LLM).
- [ ] **B-032** Clock control belongs to the Runtime, not to a firm agent: before any LLM
      management agent wakes, move `CONTROL_CLOCK` from `management` to a Runtime/operator
      identity (ADR-027; Art. 10 — the world's time is not a participant's lever).
- [ ] **B-033** (low, operator-only) `advance` moves the clock before its commit; if the commit
      fails, non-OMS writers may already hold stamps at `end` with no `clock_advanced` explaining
      them (auditor WARN, cycle 15). Also: two concurrent `start-backtest` on one empty file, or a
      stale live write between its emptiness check and `run_started` (run check and insert are two
      statements). Fix: one statement, or a file lock for `start-backtest`. Mode check is a string
      (`!= "backtest"`) — an explicit allowed set if a third clock type appears.
- [ ] **B-034** (low) Operator CLI commands ignore `governance/HALT` (pre-existing; `start-backtest`
      copies it). Decide: the Human's own hands (ADR-023 says not gated) vs a Runtime script
      calling the CLI — if the Runtime ever does, gate it.
- [ ] **B-031** (low) `mode` on `/clock` lets agents tell live from backtest (ADR-026 accepts it).
      If an experiment needs agents blind to the mode, withhold it by role in one place, with the
      Runtime/Truman controlling what an agent perceives (auditor note, cycle 14).
- [ ] **B-021** `GET /tasks` + `GET /costs` (own; cross-pod for management) + MCP tools —
      `list_tasks`/`list_costs` exist unused; a restarted agent cannot find its open task ids.
- [ ] **B-017** Sharpe annualisation: equity curve is per calendar day, `annualise` uses √252 →
      reported annual Sharpe ×0.845 ≈ √(5/7) of the true value (P8, synthetic series). Prefer
      trading-day points (√365 on calendar points is still ≈1.017× off); `sharpe_daily` must say
      which day it means. Honest-measurement bug (Art. 9).
- [ ] **B-018** Decide rebuild scope: pod creation + `system` agent write no event (P2);
      `pods.current_allocation`, `allocations`, `orders`, `messages`, `costs`, `tasks`, `agents`
      are not rebuilt. ADR: which tables are derived, which are records; before Era II generations.
      `conftest.make_pod` inserts pods directly with the system clock — update it with the ADR.
- [ ] **B-006** TRD Phase 3c: `POST /allocations`, meeting schedule + package endpoints.
      `fund_pod` (to be reused) validates nothing: add finite `delta`, no withdrawal beyond cash.
- [ ] **B-007** World events table + `system` announcements (law changes, Truman events).
- [ ] **B-008** Truman v1: local cache of real daily history, prices-only pack, one scripted
      scenario, served via `MarketDataProvider`; pack hashing. Must not reuse yfinance's
      `_fetch_price` path (SURVEY §4a.3).
- [ ] **B-000i** `.gitignore`: cassettes + `experiments/*/runs/` before Era I records anything
      (first writer expected: B-010 cassettes; earlier if an experiment run lands first).
- [ ] **B-009** Runtime skeleton (`runtime/`, `uv run fund-runtime`): AgentSpec, scheduler on
      the App clock, halt + cap checks, fake LLM provider for tests.
- [ ] **B-010** Runtime: cassette recording + replay mode.
- [ ] **B-011** Runtime: `daily_cycle` and `backtest` workflows.
- [ ] **B-022** Secret-scan test: no tracked file contains an `fk_…` key, an OpenRouter
      `sk-or-…` key or another credential pattern (SURVEY §4b.1). Before any firm agent holds a key
      (i.e. before B-012/B-013). Reuse `survey_probe_openclaw.SECRET_VALUE` + filename check
      (cycle 7: a pattern list without `xai-` missed a real key file). Auditor notes (cycle 7):
      the filename heuristic flags `keynote.md`-style names (refine before reusing); URL
      redaction misses `user:pass@`; `relative_to(state)` crashes for a workspace outside the
      state dir.
- [ ] **B-012** `openclaw` adapter to the `08_OPENCLAW.md` standard: render config + workspace
      (bootstrap files the installed version supports) from AgentSpec, own agentDir + local auth
      profile + metered key, `fund-env-mcp` per agent key via env, deny-by-default tools, no
      bindings, `firm-` namespace; OCT POC charters → AgentSpec templates.
      Cycle 7 (VERSION_NOTES): target the `firm` profile (ADR-019); MCP servers are global only
      → one named server per agent + allowlist glob of its own server; key via SecretRef, not
      a literal; check which bootstrap files 2026.5.12 loads (`TOOLS.md`/`HEARTBEAT.md`?).
      Backup step: `openclaw backup` (exists in 2026.5.12) or tar under `umask 077` — the
      cycle-7 tarball came out 644 (Q-0004). Plan `doctor` (conformance check 5): firm profile only.
- [ ] **B-023** Render every seal key explicitly, never rely on a default (newer OpenClaw
      loosens them): `tools.web.*` off, `tools.sessions.visibility: self`,
      `tools.agentToAgent.enabled: false`, `tools.profile: minimal`, per-agent deny list,
      `subagents.allowAgents: []`. Conformance check reads `openclaw config schema` of the
      installed version and fails on any seal key missing from the rendered config.
- [ ] **B-012a** Adapter written against mcp 2.x (`is_error`, not `isError`); Runtime stops
      `fund-env serve` with SIGINT (rc 0) — SURVEY §1 findings.
- [ ] **B-012b** Conformance suite: `fund-runtime openclaw doctor` static checks + live probes
      (skipped while firm cap is null); integration tests skip when OpenClaw is absent.
- [ ] **B-000l** MCP API base URL must be loopback (conformance check for Era I).
- [ ] **B-013** Metering v1: provisioned per-agent keys (fake provider in tests), cost-sync job →
      system-reported costs; system cost overrides self-report in metrics.
- [ ] **B-000k** Costs from pod-less agents (management) appear on no leaderboard → firm-level spend.
      Before B-015 (every LLM dollar attributed — Era I exit criterion).
- [ ] **B-014** Verify "chat restricted to central pod" with a two-pod test. Cycle 7 lead:
      cross-agent `sessions_spawn` needs `subagents.allowAgents` (default same-agent only).
- [ ] **B-015** Era I milestone run: 1 pod, 1-month backtest < 10 min, replay identical.
      Needs a firm cap → ask in QUESTIONS when reached.

## Residue of Era ½ (closed cycle 9, ADR-021)
- [ ] **S-004b** Cleanup, the deletions — **blocked on P-0002** (headless `git rm` needs
      approval): `git rm test_api.py`; `git rm --cached .vscode/settings.json` + ignore `.vscode/`;
      local empty `ui/` and `.DS_Store` ×3 (untracked, ignored — harmless). Do not route around
      the denial. Run it the cycle P-0002 is answered.
- [ ] **S-001r** `git --version`, `claude --version`, origin visibility — need loop-mode
      permission prompts; capture in an interactive session or when allowed.
- Done: S-001 (c3), S-002 (c1; .gitignore gap → B-000i), S-003a (c4), S-003b (c5),
  S-004a (c6; keep `legacy/`), S-005 (c7; `doctor` deliberately not run), S-006 (c8),
  S-007 (c9: SURVEY §10, exit criteria ticked, this reorder). Details: JOURNAL + git.

## Era ∞ (≤ 1 cycle in 5 during the Launch Pad)
- [ ] **X-006** (retrospective c10) Counter-example check before the auditor: in `cycle.md`
      step 5, list every "covers / finds / never / all / 0 found" claim in the diff and plant a
      counter-example for each. 5/10 cycles needed a BLOCK for an overstated claim; metric =
      auditor BLOCK rate over cycles 11–20 (baseline 50%). Cycle 11: done by hand, still
      BLOCKed (1/1). Add a second question: "what in this diff can an unprotected file or env var
      change?" (the configurable halt path), and "is every check inside the lock it protects?"
- [ ] **X-004** Run `scripts/smoke_run.py` in the cycle's verify gate (step 5) — needs a
      `.claude/commands/cycle.md` edit; cheap (~5 s) and catches "tests green, app won't start".
- [ ] **X-005** Capability probe for the Builder's own permissions (IDEAS cycle 6) — plan units
      against the headless allow list instead of hitting it.
- [ ] **X-001** `state/METRICS.md` summariser script (success rate, turns, durations).
- [ ] **X-002** Skill: `.claude/skills/new-endpoint/` — checklist for schema + permission +
      MCP tool + tests + docs, from the repo's existing patterns.
- [ ] **X-003** Suite-stability + mutation check: run the suite N× and flag flaky tests; for each
      invariant-guarding test, a recorded mutant that must make it fail (F-0001).
