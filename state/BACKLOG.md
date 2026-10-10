# BACKLOG — ordered. Each item serves an exit criterion of the current Era.

## Era ½ — The Survey (first run: clean and understand — NO features)
- [ ] **S-001** Toolchain + run check: versions (macOS, uv, Python, Node, openclaw, claude),
      `uv run pytest`, `fund-env serve` starts, MCP server connects (`scripts/agent_console.py`).
- [ ] **S-002** Git hygiene: commit Phase 2 (`Phase 2: bus + costs + MCP`), then the
      Bible/harness (`Bible + Builder harness`) as separate commits; push `main` to origin.
      `.gitignore` covers secrets, `*.db`, cassettes/run artefacts.
- [ ] **S-003** Repo survey: read every file; map to TRD + Bible; list dead code, stale docs,
      odd files (`test_api.py` at root, empty `ui/`, `.DS_Store`, `legacy/`), gaps.
- [ ] **S-004** Cleanup commits (deletions/moves/renames/doc fixes only, each with a reason).
- [ ] **S-005** OpenClaw survey per `bible/08_OPENCLAW.md` §1–2: back up `~/.openclaw` to
      `~/firm-openclaw-backups/`, `openclaw --version`, read that version's docs, write
      `runtime/openclaw/VERSION_NOTES.md`, list agents/bindings/models (no secrets), inventory
      OCT POC workspaces. Change nothing in OpenClaw.
- [ ] **S-006** Correct the Bible where reality differs (living books + PROPOSALS for protected).
- [ ] **S-007** Write `state/SURVEY.md`; seed `state/IDEAS.md`; re-order this backlog.

## Era I — The Desk
- [ ] **B-002** `tests/test_boundaries.py`: dependency law from `bible/03_WORLD.md` §1;
      `app/` imports no LLM SDK / agent framework.
- [ ] **B-003** Halt in physics: `governance/HALT` → every state-changing agent request
      refused (409/423 + logged event); `GET /halt`; MCP tool; tests.
- [ ] **B-004** TRD Phase 3a: simulated clock, `POST /clock/mode`, `POST /clock/advance`,
      `run_id` scopes; pending-order monitor runs on every advance.
- [ ] **B-005** TRD Phase 3b: look-ahead guard on every market-data route + red-team pass.
- [ ] **B-006** TRD Phase 3c: `POST /allocations`, meeting schedule + package endpoints.
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
