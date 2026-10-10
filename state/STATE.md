# STATE — rewritten every cycle

**Era:** ½ — The Survey (Launch Pad: Survey → I → II, then the Builder authors the roadmap)
**Last cycle:** 0 (Bible installed by the Human, 2026-10-11)

## What is true now
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server. 218 tests green.
- **Phase 2 is NOT committed** (git HEAD = "Phase 1: OMS + market data"). Uncommitted:
  `app/bus/*`, `app/metrics/*`, `app/api/{messages,metrics,reporting}.py`, `mcp_server/*`,
  `scripts/`, migration `c7d2f5a83e14`, docs, and the new Bible/harness files.
- No Runtime, no Truman, no Quant Lab, no Observatory yet.
- `firm.monthly_llm_usd_cap` is `null` → firm agents may not run live. Build against fakes.
- The OCT POC (OpenClaw agents: Orchestrator, PM, Analyst; Telegram) exists outside this repo.

## Next 3 moves
1. S-001 Toolchain + run check.
2. S-002 Commit Phase 2 + Bible/harness, push.
3. S-003 Repo survey → S-004 cleanup → S-005 OpenClaw survey (backup first, change nothing).
