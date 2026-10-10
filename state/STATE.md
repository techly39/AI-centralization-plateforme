# STATE — rewritten every cycle

**Era:** ½ — The Survey (Launch Pad: Survey → I → II, then the Builder authors the roadmap)
**Last cycle:** 2 (token-overflow DoS fix, merged 685eaf0, 2026-10-11)

## What is true now
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server. **267 passed + 9 xfailed**, green 3× on branch + 1× on main.
- `main` = origin/main. Branches `cycle/0001-*` and `cycle/0002-*` pushed.
- The leaderboard DoS is closed (B-000c, ADR-018): tokens per report ≤ 1e8 (API, MCP, in-process),
  pod sums use `TOTAL`. Red-team re-attacked it: 12 held.
- **9 open value-bound holes** (strict xfail): `usd_cost` inf/NaN/1e308 (B-000d), message bodies
  not on the ledger (B-000e), squattable 'system' name (B-000f), payload size caps (B-000g),
  MCP path escaping (B-000h), int64 path params → 500 (B-000m, new). Identity/permissions hold.
- No Runtime, no Truman, no Quant Lab, no Observatory yet.
- `firm.monthly_llm_usd_cap` is `null` → firm agents may not run live. Build against fakes.
- Guard hook blocks any non-read Bash containing protected dir words (incl. `loop` in
  `state/loop_status.json`, and `cd`). Use Read/Write tools and relative paths; P-0001 proposes a fix.

## Next 3 moves
1. S-001 Toolchain + run check (serve + MCP connect, Node/openclaw/claude versions) — the Survey
   has waited two cycles for physics bugs; it goes next.
2. S-003 Repo survey → S-004 cleanup → S-005 OpenClaw survey (backup first, change nothing).
3. B-000d `usd_cost` bounds — possibly as the "physical-units types" idea, closing B-000m too.
