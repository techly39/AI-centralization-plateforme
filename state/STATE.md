# STATE — rewritten every cycle

**Era:** ½ — The Survey (Launch Pad: Survey → I → II, then the Builder authors the roadmap)
**Last cycle:** 6 (S-004a cleanup edits — merged 0678d62, 2026-10-11)

## What is true now
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server (20 tools). **267 passed + 9 xfailed**.
- **The physics is mapped** (`state/SURVEY.md` §2a): every module of `app/`, `mcp_server/`,
  `migrations/` against the TRD. Migrations == models (0 diffs). All §7 v1 endpoints exist
  except Phase 3's (`/clock/*` writes, `/allocations`, meetings); no `run_id` column anywhere.
- **The weak spot is time.** Measured (`scripts/survey_probe_physics.py`, P1–P9): rebuild ≠ live
  if the clock goes backwards (B-016); daily bars leak the day's close (B-005); live quote ignores
  `as_of`; annual Sharpe ×0.845 (B-017); `/clock` 403 for the agents told to use it (B-020, needs
  an ADR vs TRD §7). Also: pod creation unledgered (B-018), register 500 (B-019), no "my tasks"
  endpoint (B-021), `mcp_server` imports all of `app` (B-002).
- **The whole repo is mapped** (SURVEY §2b, `scripts/survey_probe_repo.py` R1–R4). The suite is
  hermetic and covers every TRD Phase 0–2 test demand; it does not guard the dependency law,
  backwards clocks, bar-end look-ahead or determinism. Its price double `HistoricalProvider` has
  the same look-ahead as yfinance (→ B-005). Phase 2 milestone was met **by script**, not by an agent.
- **The live management key is out of `main`'s tree** (cycle 6: redacted in `test_api.py`,
  which now reads `FUND_API_KEY`) but still in git history and still valid in `fund.db`;
  revocation = the Human's (Q-0003); scan test = B-022. README Layout + phase2 MCP note fixed.
- **Headless mode cannot delete tracked files** (`git rm` not on the allow list). S-004b
  (remove `test_api.py`, untrack `.vscode/`) waits on P-0002; never route around it.
- The system starts outside pytest: `uv run python scripts/smoke_run.py` 12/12 PASS.
- Toolchain in SURVEY §1 (macOS 26.5.2 arm64, uv 0.11.14, Python 3.12.13, OpenClaw 2026.5.12,
  **mcp 2.0.0**). `fund.db` at repo root is the Human's August history — never run the CLI
  against it; use the smoke/probe scripts or `FUND_DATABASE_URL`.
- `main` = origin/main. Branches `cycle/0001..0006-*` pushed.
- **9 open value-bound holes** (strict xfail) + the new survey items. Identity/permissions hold.
- No Runtime, no Truman, no Quant Lab, no Observatory yet.
- `firm.monthly_llm_usd_cap` is `null` → firm agents may not run live. Build against fakes.
- Guard hook blocks non-read Bash containing protected dir words (incl. `loop` in
  `state/loop_status.json`) and `cd`; loop-mode permissions deny `VAR=x cmd`, `--include=*.py`
  globs and multi-op lines; `git rm` needs approval. The guard also blocks commit messages whose
  prose names a protected dir. Use Read/Write tools, one simple command per call. P-0001/P-0002.

## Next 3 moves
1. S-005 OpenClaw survey (backup first, change nothing; POC lead:
   `~/.openclaw/workspace/OCT/AI Hedgefund POC/`; look for the "chat restricted to central pod" cause).
   Check first that the backup (`tar`/`cp`) and `openclaw` reads are allowed headless.
2. S-006 Bible corrections (living books + PROPOSALS for protected), then S-007 and close Era ½
   (S-004b listed as residue if P-0002 is still open).
3. First Era I moves, in order: B-016 + B-020 before B-004 (clock).
