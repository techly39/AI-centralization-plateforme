# STATE — rewritten every cycle (budget: ≤ 120 lines, X-013)

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 36 (B-053 + B-054: vet before physics is told, HALT reads `halted` at every stage —
merged 5eb1d6d, 2026-10-13; ADR-032/040 amendment; red-team 0020; ticks nothing). Cycle 35 was
blocked on budget. Cycle 34: R-6a metering physics half (ADR-041).

This file was compacted on 2026-10-13 (Human-directed loop repair). The detailed per-capability
notes it held through cycle 32 are in git (`git show 5bffbfa:state/STATE.md`) and in the ADRs.

## Era I exit criteria — 3 of 7 ticked (ADR-036, `tests/test_runtime_lockstep.py` "Era I exit criteria")
- [x] EC3 look-ahead refused at the agent level · [x] EC5 HALT stops within one tick ·
  [x] EC6 null cap refuses every spending mind (holds only under Q-0005 answer B).
- [ ] EC1 1-month pod backtest via the Runtime (real minds, R-8) · [ ] EC2 cassette replay =
  identical ledger (met end to end for scripted minds by R-4b-2a; ticked at R-8) · [ ] EC4
  metering (R-6) · [ ] EC7 OpenClaw conformance (R-7/R-8).
- Tests: **1846 passed + 9 xfailed** (+3 = red-team 0020 open lows: B-055 ×2, B-056); smoke 32/32
  (a real two-server record → replay → compare).

## What is true now — the Runtime (`runtime/`, ADR-032 + amendments a–p, ADR-033, -037, -038, -040)
- **Replay CLI + ledger comparison** (R-4b-2a, ADR-040, `tests/test_replay_cli.py`,
  `tests/test_ledger_compare.py`): `fund-runtime replay --cassette PATH --specs DIR` (steps from the
  recording; input/days/budget flags must match, a mismatch is `diverged`; exit 0 = every wake matched,
  **not** an identical ledger). `fund-env compare-ledgers RECORDED REPLAYED` (`app/ledger/compare.py`,
  read-only, raw rows, one allowed difference: the `run_minds_declared` payload → `{"minds":["cassette"]}`)
  is the only check of the ledger. A setup refusal in a replay ends `refused`; a retired mind `diverged`.
- **Pre-gate + HALT label** (B-053/B-054, c36, ADR-032/040 amendment, `tests/test_redteam_0020.py`):
  `_conduct` reads the law once; `runtime.provision.vet` (network-free, `provision`'s own checks) and a
  cassette-outside-replay check refuse before `/run/minds` is declared. HALT at the law read, the
  declaration, provisioning (`cli._is_halt`, exact reasons), between wakes, or the advance (423) → `halted`.
  Known gap B-055: directory/pod/tool refusals still come after the declaration (zero-cost labels only).
- **Replay** (R-4b-1, ADR-038, `runtime/replay.py`, `tests/test_cassette_replay.py`,
  `tests/test_redteam_0018.py`): `cassette.read` accepts only the canonical v1 document;
  `Recording.load` → `Tape`s; `run_backtest(replay=)` ends at the first wake that leaves the
  recording (`diverged:<id>:<step>:<seq>:<kind>` or `diverged:clock:…`). The scripted 31-day
  month replays into a fresh DB with the same ledger, same transcripts, zero usage.
  Not done (R-4b-2b): cassette v2, hash links, size cap. Label `cassette` (Q-0006).
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

## What is true now — physics (`app/`, TRD Phases 0–2 + ADR-022…031, -034, -041)
- **Metering v1, physics half** (R-6a, ADR-041, `tests/test_metering*.py`, `test_runtime_metering.py`,
  `test_redteam_0019.py`): `POST /metering/usage` (right `REPORT_METERED_COST`: runtime + system only),
  cumulative µ$ per key, one key = first agent, `cost_metered` event (ledger only, `key_ref` withheld).
  A metered agent's cost replaces its self-report in pod metrics/leaderboard (per agent;
  `self_report_gap_usd`). `runtime/metering.py`: `FakeProvisioner`, `sync_costs`. The gate is untouched:
  nothing spends yet. Not shown anywhere: reader `conflicts`/`malformed` counts; pod-less agents (B-000k).
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
1. **B-056** (physics 500 on register into a missing pod; small, `app/registry`, red-team) — or fold it
   into R-6b's red-team if budget is tight. B-055 (reads before the declaration) can wait.
2. **R-6b** (EC4, ADR-041 §8): the gate lets a `metered` provider wake under a numeric cap;
   `provision` mints one key per agent (limit ≤ `MAX_METERED_USD_MICROS`, total ≤ cap, fail closed);
   a `FakeMeteredProvider` charges `FakeProvisioner`; `sync_costs` runs after the last step only;
   `compare-ledgers` handles the trailing `cost_metered` block by type (own ADR); a loud failure on a
   422 label; the end-to-end EC4 test and the tick. Tick-check (X-011).
3. **R-4b-2b**: cassette v2, c32 NOTE 5, reader size cap, `replay --cassette OUT`. Then R-3c
   `daily_cycle`. EC2 stays open until R-8. Cycle 40 is the retrospective (re-read Constitution + Genesis).
   X-006 additions to keep: "what does the artifact hold that the reader never compares?" and (new,
   IDEAS c33) "name the one-line production change that turns each new test red".
