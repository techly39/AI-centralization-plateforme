# STATE — rewritten every cycle

**Era:** ½ — The Survey (Launch Pad: Survey → I → II, then the Builder authors the roadmap)
**Last cycle:** 7 (S-005 OpenClaw survey — merged ccc1864, 2026-10-11)

## What is true now
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server (20 tools). **267 passed + 9 xfailed**.
- **The physics is mapped** (`state/SURVEY.md` §2a). Weak spot is **time**: rebuild ≠ live under
  a backwards clock (B-016), daily-bar look-ahead (B-005), quote ignores `as_of`, Sharpe ×0.845
  (B-017), `/clock` 403 for agents told to use it (B-020). Also B-018/B-019/B-021, B-002.
- **The whole repo is mapped** (SURVEY §2b): suite hermetic, covers TRD Phase 0–2 test demands,
  not the dependency law / backwards clocks / look-ahead / determinism.
- **OpenClaw is mapped** (SURVEY §9, `runtime/openclaw/VERSION_NOTES.md`, probe O1–O6).
  Installed **2026.5.12**; online docs describe ≥ 2026.9 (`agents.entries`, looser defaults) —
  the installed `openclaw config schema` is the source of truth. Seal keys `tools.web`,
  `tools.sessions`, `tools.agentToAgent`, `tools.profile`, `mcp.servers` are **global only** →
  ADR-019: firm agents go in their own profile (`--profile firm`), unverified until B-012.
  Backup: `~/firm-openclaw-backups/20261011T0129Z-cycle0007.tar.gz` (mode 644 — Q-0004).
  Nothing in OpenClaw was changed; `doctor` not run.
- **The Human's OpenClaw** (hands off): 4 agents, web on for all, no tool/sandbox policy,
  `pm`/`analyst` read through to `main`'s auth, an xAI key in a plain workspace file (Q-0004).
- **The live management key** is out of `main`'s tree but in history and valid in `fund.db` (Q-0003).
- **Headless limits:** `git rm` and `chmod` need approval (P-0002); never route around them.
  S-004b waits on P-0002.
- The system starts outside pytest: `uv run python scripts/smoke_run.py` 12/12 PASS.
- `main` = origin/main. Branches `cycle/0001..0007-*` pushed.
- No Runtime, no Truman, no Quant Lab, no Observatory yet. `firm.monthly_llm_usd_cap` null.
- Guard hook blocks non-read Bash naming protected dirs (incl. `loop` in
  `state/loop_status.json`) and `cd`; `ls governance/` blocked — use Read for HALT. Use
  Read/Write tools, one simple command per call. P-0001/P-0002.

## Next 3 moves
1. S-006 Bible corrections (living books directly, PROPOSALS for protected): "218 tests",
   08 §1 (docs ≠ installed version; `doctor` may migrate), 08 §2 (backup born private,
   firm profile per ADR-019).
2. S-007 close Era ½: SURVEY complete, IDEAS seeded, backlog reordered (S-004b as residue
   if P-0002 open).
3. First Era I moves, in order: B-016 + B-020 before B-004 (clock).
