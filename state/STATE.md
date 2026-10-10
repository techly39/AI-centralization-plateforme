# STATE — rewritten every cycle

**Era:** ½ — The Survey (Launch Pad: Survey → I → II, then the Builder authors the roadmap)
**Last cycle:** 3 (S-001 toolchain inventory + run check, merged b77ed42, 2026-10-11)

## What is true now
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server (20 tools). **267 passed + 9 xfailed**.
- **The system starts outside pytest:** `uv run python scripts/smoke_run.py` builds a temp DB with
  the CLI, serves the API, connects an MCP client with a seeded key and reads 5 tools — 12/12 PASS.
  Stop the server with SIGINT (rc 0), not SIGTERM (rc 143).
- Toolchain recorded in `state/SURVEY.md` §1 (macOS 26.5.2 arm64, uv 0.11.14, Python 3.12.13,
  Node 22.22.2, OpenClaw 2026.5.12, Claude Code 2.1.296, **mcp 2.0.0** — 2.x field names, e.g. `is_error`).
  git version not captured (permission prompt).
- `fund.db` at repo root is the Human's August history — never run the CLI against it; use the
  smoke script or `FUND_DATABASE_URL`.
- `main` = origin/main. Branches `cycle/0001..0003-*` pushed.
- **9 open value-bound holes** (strict xfail): B-000d, e, f, g, h, m. Identity/permissions hold.
- No Runtime, no Truman, no Quant Lab, no Observatory yet.
- `firm.monthly_llm_usd_cap` is `null` → firm agents may not run live. Build against fakes.
- Guard hook blocks any non-read Bash containing protected dir words (incl. `loop` in
  `state/loop_status.json`, and `cd`); loop-mode permissions also deny `VAR=x cmd` and multi-op
  lines. Use Read/Write tools, one simple command per call. P-0001 proposes a guard fix.

## Next 3 moves
1. S-003 Repo survey: read every file, map to TRD + Bible → SURVEY §2–5.
2. S-004 cleanup → S-005 OpenClaw survey (backup first, change nothing).
3. B-000d `usd_cost` bounds — possibly as the "physical-units types" idea, closing B-000m too.
