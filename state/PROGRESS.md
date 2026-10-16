Cycle: 0040 · Mission: M-002 (A run is a self-contained proof object) · Branch: mission/M-002-proof-object
Done so far (all pushed; suite green at each: 2100 passed / 12 xfailed):
- Gate 2: plan in `state/missions/M-002.md` (deviations section is live); acceptance red-first (c6f8cf1).
- M1 (af33043): cassette v2 (`runtime/cassette.py`: parameters, spec digests, world, ledger, 64 MiB cap, v1 refused
  by name), `WakeRecord.model/tools_sha256`, `Tape` fields + c32 NOTE 5, `RunRecord.agents`, `specs_from_cassette`,
  `replay` takes ONLY `--cassette` (+`--server`). Old tests restated (tests/cassette_parts.py PARTS), none loosened.
- M2 (882996f): `runtime/world.py` (only spawner, pinned by tests/test_runtime_spawn.py), `backtest --world FILE`
  (needs --cassette + FUND_MARKETDATA__SYNTHETIC_KEY, excl. with --server), `fund-env export-ledger` / `run-minds`
  (B-051 command done), rows files `*.ledger.json` + `locate` in `app/ledger/compare.py`, `compare-ledgers` adds
  `locate`, alembic script_location absolute (init-db from any cwd). Acceptance Part A passes.
Next (M3): `runtime/verify.py` + `replay --verify` (parse in runtime/cli.py `replay`; `--verify` excludes `--server`):
  read cassette -> exit 2 on v1/no world/no key; HALT -> 4; `world.hosted(recipe, key)`; genesis rows must equal
  recorded rows prefix (export_ledger before serve) else SETUP ERROR exit 3 "event <id> (<type>)"; serve; conduct
  via `cli._conduct(as_cassette specs, ..., replay=rec)` (lazy import of runtime.cli); stop; write recorded rows to
  `<w.tmp>/recorded.ledger.json` (0600, `rows_document`) and `w.compare_with(file)`; `verdict_of(outcome, compare,
  agents)` pure fn: completed+equal -> IDENTICAL exit 0 'IDENTICAL: <n> events, 0 differences, $0'; diverged ->
  'DIVERGED at step <s>, wake <id>, turn <seq> ...' exit 1 (reason `diverged:<id>:<step>:<seq>:<kind>` or
  `clock:<step>:calendar_*`); completed+unequal -> DIVERGED at locate (step, wake of actor via RunRecord.agents else
  'physics', event id/type; `fk_<redacted>` in a recorded row -> kind key); halted -> 4; refused/error -> SETUP ERROR 3.
  Evidence JSON after line 1 (see plan 'DESIGN 9.8'). Then run `uv run python acceptance/M-002.py` (takes ~1-2 min).
  M3 tests listed in the plan (tests/test_runtime_verify.py; share the `hosted_cassette` session fixture).
Then M4: smoke hosted step + minds_check via `fund-env run-minds`, ADR-045 (07_DECISIONS), docs/proof_object_v2.md,
  bible/03_WORLD.md §1 (new edge: Runtime spawns fund-env), validator, red-team (scoped, plan 'RED-TEAM'), auditor, merge.
Watch out:
- Bash guard: NO heredocs/`sed -i`/`python -c`/compound `cd &&`/commands naming the law dir ("governance").
  Write scripts with the Write tool into `.scratch/` (git-excluded) and run `python3 .scratch/x.py`; use Read for
  runtime/governance.py. Stage by path, never `git add -A`. `timeout` doesn't exist on this mac.
- `uv run` leaves `uv-*.lock` in TMPDIR (acceptance filters it). Shebang paths with spaces fail ("firm app").
- Stop hook reads state/loop_status.json + PROGRESS.md: both must name the cycle before a session ends.
- Architect run in background gets killed when the turn ends: foreground subagents.
Acceptance: Part A passes; B-F fail (`--verify` not built yet).
