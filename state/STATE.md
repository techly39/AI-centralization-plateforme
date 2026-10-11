# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 9 (S-007 close Era ½ — merged 28e435d, 2026-10-11)

## What is true now
- **Era ½ is closed.** All five exit criteria ticked with evidence (`state/SURVEY.md` §10).
  SURVEY is now a record of the Survey; later changes go to STATE/JOURNAL. Residue, explained:
  S-004b (`test_api.py`, `.vscode/` still tracked — P-0002), S-001r (versions needing prompts).
- Physics (`app/`) has TRD Phases 0–2: ledger, registry, auth, permissions, OMS, market data,
  bus, cost/task reporting, metrics, MCP server (20 tools). **267 passed + 9 xfailed**.
  No model has traded through the App yet (Phase 2 milestone was a script).
- **Backlog order (ADR-021):** physics bugs = priority 2, same tier as the seal, with a gate —
  every open red-team hole fixed or ADR-accepted before any agent wakes. Era I: B-002 → B-003 →
  B-016 (with B-000d) → B-020 → B-004 → B-005 → … → B-015.
- Weak spot is **time**: B-016 replay order, B-005 daily-bar look-ahead, quote ignores `as_of`,
  B-017 Sharpe ×0.845, B-020 `/clock` 403 for agents told to use it.
- **OpenClaw** 2026.5.12, mapped (SURVEY §9, `runtime/openclaw/VERSION_NOTES.md`); firm goes in
  its own profile (ADR-019, verify in B-012). Nothing in OpenClaw changed; `doctor` not run.
  Backup `~/firm-openclaw-backups/20261011T0129Z-cycle0007.tar.gz` still mode 644 (Q-0004).
- **The Human's open items:** Q-0001 (firm cap null → no agent runs), Q-0002 (provisioning key),
  Q-0003 (committed key live in `fund.db`), Q-0004 (xAI key file, backup perms), P-0001, P-0002.
- No Runtime, no Truman, no Quant Lab, no Observatory yet. `bible/09_BUILDER_VISION.md` not yet
  written (due after the Launch Pad; start it during Era I when the roadmap needs it).
- **Headless limits:** `git rm`, `chmod`, `rm`, `git ls-remote`, compound commands need approval.
  `git push origin main <branch>` works as a bare command in the repo cwd (not `git -C`, not
  `cd &&`). Guard blocks Bash naming protected paths (incl. `loop` inside
  `state/loop_status.json`, `governance`) unless plain reads without `cd` — use Read/Write.
  pytest summary: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. B-002 `tests/test_boundaries.py`: dependency law (03 §1), no LLM SDK in `app/`, place
   `mcp_server/` (cut its import of `app.metrics.reporting`) and `scripts/`.
2. B-003 halt in physics: `governance/HALT` → state-changing agent requests refused + event;
   `GET /halt` + MCP tool. Red-team pass (touches registry/permissions path).
3. B-000d + B-016: finite floats at every input and in `append_event`; replay order = live order
   under a backwards clock. Then B-020 ADR, then B-004.
