# STATE — rewritten every cycle

**Era:** ½ — The Survey (Launch Pad: Survey → I → II, then the Builder authors the roadmap)
**Last cycle:** 1 (git hygiene, merged f45eecf, 2026-10-11)

## What is true now
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server. **250 passed + 10 xfailed**, green 4 runs in a row.
- Everything is committed and pushed (`main` = origin/main). The Bible + harness are in git history.
- The concurrency flake is fixed (F-0001). `OMS_LOCK` is currently defence-in-depth on SQLite;
  no test proves it is needed (B-000b).
- Red-team pass on Phase 2 (F-0002): identity/permissions hold; **10 value-bound holes** are open,
  each a strict-xfail test. Worst: any agent can permanently 500 the leaderboard (B-000c).
- No Runtime, no Truman, no Quant Lab, no Observatory yet.
- `firm.monthly_llm_usd_cap` is `null` → firm agents may not run live. Build against fakes.
- Guard hook blocks any non-read Bash containing the words for the protected dirs (even prose,
  even `cd`). Use the Read tool and relative paths; P-0001 proposes a fix.

## Next 3 moves
1. B-000c Leaderboard token-overflow DoS (high physics bug) — small, test already written.
2. S-001 Toolchain + run check (serve + MCP connect, Node/openclaw/claude versions).
3. S-003 Repo survey → S-004 cleanup → S-005 OpenClaw survey (backup first, change nothing).
