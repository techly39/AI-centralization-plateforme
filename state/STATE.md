# STATE — rewritten every cycle

**Era:** ½ — The Survey (Launch Pad: Survey → I → II, then the Builder authors the roadmap)
**Last cycle:** 8 (S-006 Bible corrections — merged 60811d1, 2026-10-11)

## What is true now
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server (20 tools). **267 passed + 9 xfailed**.
- **The Bible matches the Survey** (cycle 8, ADR-020: corrections annotate, never rewrite):
  03 §2 lists the known holes, 04 §11 points the "chat restricted" lead at OpenClaw (B-014),
  05 notes the counts and the script-met Phase 2 milestone, 08 §1–2/§5 say docs ≠ installed,
  `config schema` first, `doctor` only after backup on the firm profile, backups born private.
  00/01 read: nothing to propose.
- **The physics is mapped** (`state/SURVEY.md` §2a). Weak spot is **time**: rebuild ≠ live under
  a backwards clock (B-016), daily-bar look-ahead (B-005), quote ignores `as_of`, Sharpe ×0.845
  (B-017), `/clock` 403 for agents told to use it (B-020). Also B-018/B-019/B-021, B-002.
  No model has traded through the App yet (Phase 2 milestone was a script).
- **OpenClaw is mapped** (SURVEY §9, `runtime/openclaw/VERSION_NOTES.md`). Installed
  **2026.5.12**; online docs describe ≥ 2026.9. Global-only seal keys: `tools.web`,
  `tools.sessions`, `tools.agentToAgent`, `mcp.servers` (`tools.profile` has a per-agent
  override — corrected cycle 8) → ADR-019: firm in its own profile, unverified until B-012.
  Backup `~/firm-openclaw-backups/20261011T0129Z-cycle0007.tar.gz` (mode 644 — Q-0004).
  Nothing in OpenClaw changed; `doctor` not run.
- **The Human's OpenClaw** (hands off): 4 agents, web on for all, no tool/sandbox policy,
  `pm`/`analyst` read through to `main`'s auth, an xAI key in a plain workspace file (Q-0004).
- **The live management key** is out of `main`'s tree but in history and valid in `fund.db` (Q-0003).
- **Headless limits:** `git rm`, `chmod`, compound shell commands need approval (P-0002);
  never route around them. S-004b waits on P-0002.
- `uv run python scripts/smoke_run.py` 12/12 PASS (cycle 3).
- `main` = origin/main. Branches `cycle/0001..0008-*` pushed.
- No Runtime, no Truman, no Quant Lab, no Observatory yet. `firm.monthly_llm_usd_cap` null.
- Guard hook blocks Bash naming protected paths (incl. grep/ls on `bible/00_*`, `governance/`,
  and `loop` inside `state/loop_status.json`) and `cd` — use Read/Write, one simple command per
  call; pytest summary: `uv run pytest -p no:warnings -o addopts="" -q`. P-0001/P-0002.

## Next 3 moves
1. S-007 close Era ½: SURVEY complete per 05 Era ½ §7, IDEAS seeded, backlog reordered,
   S-004b as known residue if P-0002 open, note the VERSION_NOTES exit criterion was reworded
   during its own Era (cycle 8), tick the Era ½ exit criteria with evidence.
2. Era I: B-016 (replay order) + B-020 (clock ADR) before B-004 (simulated clock).
3. Then B-002 (boundary test) and B-003 (halt in physics) — the seal before any agent wakes.
