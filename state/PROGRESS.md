Cycle: 0040 · Mission: M-002 (A run is a self-contained proof object) · Branch: mission/M-002-proof-object
Done so far: Gate 2 done — architect plan saved verbatim in `state/missions/M-002.md` (commit 0c732d7;
missions.json updated: estimate 3, physics true, new demo with `--world`). `acceptance/M-002.py` +
`specs/desk-month/world.json` committed red (c6f8cf1): fails Part A, `backtest` has no `--world`.
Branch pushed. No product code written yet (M1 not started).
Next: build M1 per the plan (tests first): cassette v2 writer/reader (`runtime/cassette.py`), `WakeRecord.model`/
`tools_sha256`, `Tape` fields + NOTE 5, `RunRecord.agents`, `specs_from_cassette`, move `_conduct` etc. to
`runtime/conduct.py` (keep aliases in cli), `replay` reads specs+parameters from the file and loses
--specs/--input/--days-per-step/--max-tool-calls. Restate the old v1/flag tests (never loosen).
Then M2 (runtime/world.py, backtest --world, fund-env export-ledger, alembic script_location fix),
M3 (runtime/verify.py, rows files + locate in app/ledger/compare.py), M4 (smoke, B-051, ADR-045, docs, validator/red-team/auditor).
Watch out:
- Stop hook reads `state/loop_status.json` and `state/PROGRESS.md`: both must name the cycle before a session ends.
- NEVER `git add -A`: stage by path. Guard blocks Bash heredocs that write, `sed -i`, `python -c`, and
  commands naming the law directory (use Read/Write/Edit).
- `timeout` is not on this mac; push is a bare `git push origin <branch>`.
- The architect's first run (c39) was lost because it ran in the background and the turn ended: launch
  subagents with run_in_background=false when the next step depends on them.
- M-001 refuses `--cassette` on a metered run: cost_metered stays out of scope (plan).
Acceptance: fails (red-first, Part A: `--world` unrecognized). Suite last known: 1974 passed / 12 xfailed.
