Cycle: 0039 · Mission: M-002 (A run is a self-contained proof object) · Branch: mission/M-002-proof-object
Done so far: M-002 set `active`, branch created from main, `M-002: start` committed (12c2696).
The `architect` was launched for Gate 2 (plan) but its plan had NOT arrived when this session ended:
nothing is saved in `state/missions/M-002.md`, `acceptance/M-002.py` does not exist, no code written.
Next: (1) if `state/missions/M-002.md` is missing, launch the `architect` again (brief: missions.json
entry M-002 + notes, protocol/MISSIONS.md, runtime/cassette.py, replay.py, cli.py, app/ledger/compare.py,
scripts/smoke_run.py, ADR-044 §6; ask for cassette v2 design + v1 handling, `replay --cassette X --verify`
verdict IDENTICAL / DIVERGED at <wake/step>, setup errors never read as diverged, acceptance spec that
fails if the feature is broken, milestones, RED-TEAM yes/no, claim list, B-051 fold decision).
(2) save its plan verbatim to `state/missions/M-002.md`, commit `M-002: plan`.
(3) write `acceptance/M-002.py`, see it fail for the right reason, commit
`M-002: acceptance (fails before the work)`, push the branch. Then build the milestones.
Watch out:
- Stop hook reads `state/loop_status.json` and `state/PROGRESS.md`: both must name this cycle before
  a session ends (loop_status is `progress`, cycle 39).
- Still NEVER `git add -A`: stage by path. Guard blocks Bash heredocs, `sed -i`, `python -c`, and
  commands naming the law directory (use Read/Write/Edit).
- M-001 refuses `--cassette` on a metered run; the `cost_metered` compare block is M-002's only if its
  cassette carries a metered run (ADR-044 §6) — the plan should say out of scope unless cheap.
Acceptance: acceptance/M-002.py not written yet (nothing to run). Suite last known: 1974 passed / 12 xfailed.
