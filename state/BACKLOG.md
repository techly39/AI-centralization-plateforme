# BACKLOG — ordered. Each item serves an exit criterion of the current Era.

## Physics bugs (Art. 8 — Builder's bugs; priority 2, same tier as B-002/B-003 — ADR-021)
**Gate:** every open hole below is fixed, or accepted by an ADR with its reason, before any
agent wakes (before B-012's first live conformance probe and before B-015). Order inside the
tier: B-002 + B-003 first, B-000d with or before B-016 (both touch `append_event`), B-000e with
B-018, the rest when cheap or blocking.
Each red-team hole has a strict-xfail test in `tests/test_redteam_0001.py`; fix = remove the marker.
- [ ] **B-000d** Non-finite floats: reject inf/NaN/1e308 on **every** float input → clean 422
      (3 xfail tests on `usd_cost`; SURVEY §4a.7: `limit_price=1e309` is stored and read back as
      `null`, and its event payload is written as non-standard JSON `Infinity`). Likely one fix:
      `allow_inf_nan=False` on the API schemas, plus `append_event` refusing non-finite payloads
      so the ledger stays portable JSON. Consider IDEAS "physical-units types". Before B-016
      touches `append_event`, or together with it.
- [ ] **B-000e** Message `body` + `structured_payload` on the `message_sent` ledger event, so the
      messages table is rebuildable (CLAUDE.md: every state change is an event). With B-018.
- [ ] **B-019** (low) `POST /agents/register` with a missing `pod_id` → 500 (FK error unhandled);
      PM without pod accepted (can never trade). → 404/422. SURVEY §4a.6, probe P5/P6.
- [ ] **B-000m** (low) Integer path params ≥ 2⁶³ → 500 (`GET /metrics/pod/{2**63}`; likely every
      `/{id}` route) → `tests/test_redteam_0002.py::test_hole_metrics_pod_id_beyond_int64_500`.
- [ ] **B-000n** (low) Cost-report rate is unbounded per agent (spam inflates rows; token totals
      lose exactness past ~9e7 max-size reports). Decide on a per-agent rate law. With B-013.
- [ ] **B-000f** 'system' identity looked up by role/reserved name, not a squattable name.
- [ ] **B-000g** Size caps on `structured_payload` and task `outcome`.
- [ ] **B-000h** MCP client: URL-escape path params.
- [ ] **B-000b** A test that proves `OMS_LOCK` is load-bearing (F-0001), e.g. race injected between
      cash read and write, or run against a row-locking backend; or document the lock as defence-in-depth.
- [ ] **B-000j** Decide whether `state/loop_status.json` is tracked (runner state) — auditor note.
- [x] **B-000c** (high) Token-sum overflow DoS — cycle 2: per-report cap 1e8 + `TOTAL` sum (ADR-018).

## Era I — The Desk (current; order per ADR-021: seal → time → clock → the rest)
- [x] **B-002** Dependency-law test — cycle 10 (ADR-022; `app/limits.py`; 2 detectors).
- [ ] **B-003** Halt in physics: `governance/HALT` → every state-changing agent request
      refused (409/423 + logged event); `GET /halt`; MCP tool; tests.
- [ ] **B-016** Replay order = live order: `rebuild_state` + equity curve replay `(ts, id)`, live
      folds by `id`; a backwards clock gives 10 phantom shares on rebuild (SURVEY §4a.1, P3).
      Shape: per-`run_id` ledgers with timestamps enforced monotonic at `append_event` (id order
      alone doesn't fix the equity curve's day buckets); sell reducer must raise on a sell beyond
      the position, not drop it. Test with a clock that moves back. Before B-004.
      Consider IDEAS "time-travel invariant suite" (cycle 4) as its test shape.
- [ ] **B-020** Clock vs agents: MCP `get_clock` tells all agents to use it; PM/analyst get 403
      (P7) — and TRD §7 says `/clock` is system/management only. Decide by ADR: widen the read
      (agents need the simulated date in backtests) or fix the tool docstring. Before B-004.
      `test_clock_forbidden_for_analyst` changes only with that ADR as its reason (§4b.4).
- [ ] **B-004** TRD Phase 3a: simulated clock, `POST /clock/mode`, `POST /clock/advance`,
      `run_id` scopes; pending-order monitor runs on every advance. Needs B-016 + B-020 first.
- [ ] **B-005** TRD Phase 3b: look-ahead guard on every market-data route + red-team pass.
      Must filter bars by their **end** time (a daily bar stamped 00:00 carries that day's close,
      SURVEY §4a.2) and never stamp a quote with the requested time (§4a.3). Fix the test double
      `tests/support.py` `HistoricalProvider` the same way (§4b.3), or the suite certifies the leak.
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
      auditor BLOCK rate over cycles 11–20 (baseline 50%).
- [ ] **X-004** Run `scripts/smoke_run.py` in the cycle's verify gate (step 5) — needs a
      `.claude/commands/cycle.md` edit; cheap (~5 s) and catches "tests green, app won't start".
- [ ] **X-005** Capability probe for the Builder's own permissions (IDEAS cycle 6) — plan units
      against the headless allow list instead of hitting it.
- [ ] **X-001** `state/METRICS.md` summariser script (success rate, turns, durations).
- [ ] **X-002** Skill: `.claude/skills/new-endpoint/` — checklist for schema + permission +
      MCP tool + tests + docs, from the repo's existing patterns.
- [ ] **X-003** Suite-stability + mutation check: run the suite N× and flag flaky tests; for each
      invariant-guarding test, a recorded mutant that must make it fail (F-0001).
