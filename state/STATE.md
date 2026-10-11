# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 10 (B-002 dependency-law test + retrospective — merged 86e2486, 2026-10-11)

## What is true now
- **The dependency law is enforced** (`tests/test_boundaries.py`, ADR-022): static AST scan +
  dynamic `sys.modules` probe; every top-level Python dir is placed. `mcp_server` imports only
  `app.config` + `app.limits` (new pure constants module) — it no longer loads the DB engine.
  Known scanner limits are listed in ADR-022 (computed/aliased/keyword dynamic imports).
- Physics (`app/`) has TRD Phases 0–2. **283 passed + 9 xfailed**. Smoke run 12/12.
  No model has traded through the App yet. Era I exit criteria: 0 of 7 ticked.
- **Backlog order (ADR-021):** physics bugs = priority 2 with a gate (every open red-team hole
  fixed or ADR-accepted before any agent wakes). Era I: B-003 → B-000d + B-016 → B-020 → B-004 →
  B-005 → … → B-015.
- Weak spot is **time**: B-016 replay order, B-005 daily-bar look-ahead, quote ignores `as_of`,
  B-017 Sharpe ×0.845, B-020 `/clock` 403 for agents told to use it.
- **Retrospective (cycle 10):** 10/10 merged; 5/10 needed an auditor BLOCK, all overstated
  claims → X-006 (counter-example check before audit). World more truthful, not more capable:
  the next 10 cycles must get a pod acting in simulated time against a fake provider.
- **OpenClaw** 2026.5.12, mapped (SURVEY §9, `runtime/openclaw/VERSION_NOTES.md`); firm in its own
  profile (ADR-019). Nothing in OpenClaw changed. Backup still mode 644 (Q-0004).
- **The Human's open items:** Q-0001…Q-0004, P-0001, P-0002 (none answered in 10 cycles).
- No Runtime, Truman, Quant Lab or Observatory yet. `bible/09_BUILDER_VISION.md` not yet written.
- **Headless limits:** `git rm`, `chmod`, `rm`, `git ls-remote`, heredocs (`cat <<EOF`) need
  approval or are rejected. `git push origin main <branch>` works as a bare command in the repo
  cwd. Guard blocks Bash naming protected paths (incl. `loop` in `state/loop_status.json`,
  `governance`) — use Read/Write. pytest summary: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. B-003 halt in physics: `governance/HALT` → state-changing agent requests refused + event;
   `GET /halt` + MCP tool. Red-team pass (touches the registry/permissions path).
2. B-000d + B-016: finite floats at every input and in `append_event`; replay order = live order
   under a backwards clock (consider the time-travel invariant suite as the test shape).
3. B-020 clock-vs-agents ADR, then B-004 simulated clock.
