# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 11 (B-003 halt in physics — merged ffc418a, 2026-10-11)

## What is true now
- **Halt is physics** (ADR-023, `tests/test_halt.py`, `tests/test_redteam_0003.py`): while
  `governance/HALT` exists, every write from every authenticated agent → 423 + `halt_refused`
  {method, route template, role}; reads work; `GET /halt` + MCP `get_halt`; the pending monitor
  checks under `OMS_LOCK` and fills nothing. The path is a constant (no setting can move it).
  Tests point it at a temp file via an autouse fixture. Runtime half (wakes stop within a tick)
  waits for B-009.
- **The dependency law is enforced** (`tests/test_boundaries.py`, ADR-022).
- Physics (`app/`) has TRD Phases 0–2 + halt. **334 passed + 9 xfailed**. Smoke 12/12.
  No model has traded through the App yet. Era I deliverables 1–2 of 8 done; exit criteria 0 of 7.
- **Backlog order (ADR-021):** physics-hole gate before any agent wakes. Next: B-000d + B-016 →
  B-020 → B-004 → B-005 → … Red-team 0003 holes: both fixed; 0001/0002 holes still open (9 xfail).
- Weak spot is **time**: B-016 replay order, B-005 daily-bar look-ahead, quote ignores `as_of`,
  B-017 Sharpe ×0.845, B-020 `/clock` 403 for agents told to use it.
- **The Human (2026-10-11):** accepted P-0001 (guard matches path tokens) and P-0002 (`git rm`
  allowed); fixed the runner (a run counts only if `loop_status.json` advances; usage limits wait
  30 min); handles Q-0003/Q-0004 themself. Still open: Q-0001 (budget), Q-0002 (provisioning key).
- **OpenClaw** 2026.5.12, mapped; firm in its own profile (ADR-019). Nothing in OpenClaw changed.
- No Runtime, Truman, Quant Lab or Observatory yet. `bible/09_BUILDER_VISION.md` not yet written.
- **Headless limits:** the guard still blocks any Bash command whose text contains a protected
  path token (e.g. the halt path string inside a python heredoc) — use Edit/Write for those.
  `cp`/`sed -i`/compound `cd … && git push` need approval; `git push origin main <branch>` as a
  bare command works. pytest summary: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. B-000d + B-016: finite floats at every input and in `append_event`; replay order = live order
   under a backwards clock (time-travel invariant suite as the test shape).
2. S-004b (quick, unblocked by P-0002): `git rm test_api.py`, untrack `.vscode/`.
3. B-020 clock-vs-agents ADR, then B-004 simulated clock.
