# STATE — rewritten every cycle (budget: ≤ 120 lines, X-013)

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 32 (R-4b-1: a replay drives the minds from a cassette — merged a1f72a2, 2026-10-13)
**Cycle 33 was interrupted** by a usage limit (429) after its architect plan, before any commit:
branch `cycle/0033-replay-cli` is empty and the plan was lost. Resume it at step 2 (X-012).

This file was compacted on 2026-10-13 (Human-directed loop repair). The detailed per-capability
notes it held through cycle 32 are in git (`git show 5bffbfa:state/STATE.md`) and in the ADRs.

## Era I exit criteria — 3 of 7 ticked (ADR-036, `tests/test_runtime_lockstep.py` "Era I exit criteria")
- [x] EC3 look-ahead refused at the agent level · [x] EC5 HALT stops within one tick ·
  [x] EC6 null cap refuses every spending mind (holds only under Q-0005 answer B).
- [ ] EC1 1-month pod backtest via the Runtime (real minds, R-8) · [ ] EC2 cassette replay =
  identical ledger (test half met in code by R-4b-1; ticked at R-8) · [ ] EC4 metering (R-6) ·
  [ ] EC7 OpenClaw conformance (R-7/R-8).
- Tests: **1555 passed + 6 xfailed**; smoke 21/21.

## What is true now — the Runtime (`runtime/`, ADR-032 + amendments a–p, ADR-033, -037, -038)
- **Replay** (R-4b-1, ADR-038, `runtime/replay.py`, `tests/test_cassette_replay.py`,
  `tests/test_redteam_0018.py`): `cassette.read` accepts only the canonical v1 document;
  `Recording.load` → `Tape`s; `run_backtest(replay=)` ends at the first wake that leaves the
  recording (`diverged:<id>:<step>:<seq>:<kind>` or `diverged:clock:…`). The scripted 31-day
  month replays into a fresh DB with the same ledger, same transcripts, zero usage. In process
  only. Not done: CLI, cassette v2, smoke step, hash links, size cap. Label `cassette` (Q-0006).
- **Cassettes** (R-4a, ADR-037, `tests/test_cassette.py`): `fund-runtime backtest --cassette PATH`
  writes a redacted, 0600, exclusive `*.cassette.json`; every `WakeRecord` has `exchanges`
  (seq, request_sha256, usage). Gitignored.
- **One operator command** (R-3b-2c-1, ADR-032 (o)): `fund-runtime backtest --specs DIR --steps N
  …`; keys from env only, loopback server only, output redacted, exit 0 only for `completed`.
  `specs/desk-month/` = analyst + PM pod; the smoke run lives it 5 days on a real server.
- **Physics records the run's minds** (R-3b-2c-2, ADR-032 (p), `tests/test_run_minds.py`):
  `POST /run/minds` once, before any firm act or advance; kinds ∈ `{scripted, cassette, model}`.
  M1 closed for scripted minds.
- **Provisioning from specs** (R-3b-2b-1, ADR-032 (n)): caller-held registrar key; names folded,
  reserved and taken names refused before any registration; name/role/pod bound at wake.
- **Pods + conductor** (R-3b-1/2a, ADR-032 (j)(k)(l)(m)): lockstep `run_backtest` — HALT read,
  every mind wakes in id order, HALT again, the runtime key advances. A refused wake ends the run;
  a deactivated mind is retired. MCP list answers are always one array.
- **Clock identity** (R-3a, ADR-033): role `runtime` = READ_HALT/READ_CLOCK/CONTROL_CLOCK only;
  management lost CONTROL_CLOCK; `system`/`runtime` names reserved; key rotation (B-041).
- **Scripted mind + native adapter** (R-2): HALT before every model turn and tool call; replies
  must be plain JSON; MCP path values escaped.
- **Gates** (R-1): HALT first, then the cap, fresh, fail-closed; only `{scripted, cassette}` ×
  `{native}` wake under any cap until R-6. `fund-runtime status` prints the law.
- Boundary law: runtime imports no `app` module beyond `{app, app.config, app.limits}`.

## What is true now — physics (`app/`, TRD Phases 0–2 + ADR-022…031, -034)
- Withheld from agents: `run_started.world`, `run_minds_declared.minds` (ADR-034). Ticker
  universe still probeable by 200/404 (B-052).
- A run records its world and lives in only one (ADR-031); a keyed synthetic market makes a
  backtest reproducible (ADR-030); the world has one now, `ledger_now` (ADR-029); the look-ahead
  guard (ADR-028); a run is a database with its own clock (ADR-027); every agent reads the clock
  (ADR-026); replay order = live order (ADR-025); portable JSON ledger (ADR-024); halt is physics
  (ADR-023); dependency law (ADR-022).
- Physics-hole gate (ADR-021): red-teams 0003–0018 fixed. 6 strict xfails open (B-000g ×2,
  B-000e, B-026, B-036 ×2). Low untested items: B-019, B-000n, B-000b, B-025, B-028–B-030, B-033,
  B-035, B-038, B-040.
- Time debts: B-017 Sharpe ×0.845, B-028 row stamps, B-029 live forward step, B-036.
- Era III constraint (ADR-028 amendment): agent strategy code never runs inside the App process.
- Not yet: Truman, Quant Lab, Observatory, live scheduler (R-3c), stored RunRecords.

## The Builder's process
- Protocol in `protocol/CYCLE.md` (Builder-owned); `.claude/` and `loop/` sealed. Team (ADR-035):
  lead sonnet, lead_hard opus (diagnosis, every 10th, after a failure), architect / auditor /
  red-team opus. $8/cycle, $30/run, $35/day, 8 cycles/day.
- 2026-10-13 loop repair (Human-directed): the runner now logs a usage-limit cut-off as
  `result=limit` (counts dollars, not a failure, not a cycle slot); the architect's plan is saved
  and committed before the build (X-012); STATE.md has a line budget (X-013).
- Retrospective c21–30: direction right, pace slow; drift = tick-blindness → X-011 (step 2).
- Human: accepted P-0001/2/3. Open: Q-0001 (budget, blocks R-8 only), Q-0002, Q-0005, Q-0006.
- OpenClaw 2026.5.12 mapped; firm in its own profile (ADR-019); nothing in OpenClaw changed.
- **Headless limits:** the guard blocks Bash heredocs, `sed -i`, `git -C`, `git worktree add` /
  `git archive` after `cd`, `python -c` with `#`, `>>` after `cd` → write scripts to `/tmp/*.py`
  with Write and run `uv run --project "<repo>" python -I /tmp/x.py "<repo>"`; edit with Edit;
  `cd "<repo>" && git add … && git commit …` works. `git push origin main <branch>` only as a bare
  command. pytest: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. **Cycle 33 = R-4b-2** (resume the empty branch at step 2): `fund-runtime replay --cassette PATH
   --specs DIR` (end-to-end ledger comparison; only allowed difference: the `run_minds_declared`
   payload), cassette v2 (run parameters, spec digests, each wake's model), a cassette step in
   the smoke run, a replay setup error that does not read as `diverged` (audit c32 NOTE 4).
   Claim-check question (X-006): what does the artifact hold that the reader never compares?
2. **B-053**: a pre-gate before provisioning in `fund-runtime backtest` (red-team).
3. R-6 metering v1 (EC4). R-3c `daily_cycle`. Tick-check (X-011): EC2 stays open until R-8.
