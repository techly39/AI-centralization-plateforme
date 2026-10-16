# STATE — rewritten every cycle (budget: ≤ 120 lines, X-013)

**Goal source:** `bible/IDEAS_BOOK.md` (since cycle 41, ADR-046; the old Eras are in `bible/archive/05_ERAS.md`)
**Last cycle:** 37 (plan: the first mission queue, ADR-043). Before: 36 (B-053 + B-054: vet before physics is told, HALT reads `halted` at every stage —
merged 5eb1d6d, 2026-10-13; ADR-032/040 amendment; red-team 0020; ticks nothing). Cycle 35 was
blocked on budget. Cycle 34: R-6a metering physics half (ADR-041).

This file was compacted on 2026-10-13 (Human-directed loop repair). The detailed per-capability
notes it held through cycle 32 are in git (`git show 5bffbfa:state/STATE.md`) and in the ADRs.

## Era I exit criteria — 4 of 7 ticked (ADR-036, `tests/test_runtime_lockstep.py` "Era I exit criteria")
- [x] EC3 look-ahead refused at the agent level · [x] EC5 HALT stops within one tick ·
  [x] EC6 null cap refuses every spending mind (holds only under Q-0005 answer B) ·
  [x] EC4 every (fake) dollar attributed by the meter (M-001, ADR-044, `acceptance/M-001.py`).
- [ ] EC1 1-month pod backtest via the Runtime (real minds, R-8) · [ ] EC2 cassette replay =
  identical ledger (met end to end for scripted minds by R-4b-2a; ticked at R-8) · [ ] EC7
  OpenClaw conformance (M-003 static half; live probes need real minds).
- Tests: **1974 passed + 12 xfailed** (9 old + 3 red-team 0021 lows routed to M-004); smoke green.
  The real-law tripwire pins the committed cap of $50/month (`test_the_real_human_yaml_reads_as_cap_50`).
- **Metered minds (M-001):** provider `fake-metered` (gate: cap numeric + native + a key told by the
  Runtime) → `vet` Σ budgets ≤ cap → one key per agent → `FakeMeteredProvider` bills per turn →
  one sync after the run → `GET /metering/agents`. `docs/metering_v1_runtime.md`.

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
- **Real minds** (ADR-047, `runtime/openrouter.py`, `docs/real_minds_v1.md`): provider `openrouter`
  is metered; one capped `firm-` key per agent, minted under a repo lock after counting the whole
  month at the provider, disabled after the run; daily package `prices-v1` (`runtime/packages.py`);
  pod `specs/real-desk/`; the recorded real month `evidence/real-agents-backtest/` replays at $0.
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

## The Builder's process — Builder v3 since cycle 41 (ADR-046, Human-directed 2026-10-16)
- Goal source: `bible/IDEAS_BOOK.md` (the Human's ideas with status; the Builder's own in Part 4;
  "Next up" is the order). One idea at a time, built until its demo works: `acceptance/<slug>.py`,
  queue entry in `state/missions.json`, plan + "how I understand it" in `state/NOW.md`.
- Review only on the risk tier (money, physics, seal): red-team + auditor, in the foreground. No
  architect, no validator. Lead = opus. The runner still re-runs the suite on `main` and the demo.
- The Human comments in the Console → `$FIRM_HOME/comments.jsonl`; the Builder answers in
  `state/comments.json` at the start of the next session. Nothing waits for the Human.
- Paperwork: `state/PROGRESS.md` (handoff), one journal line, `state/loop_status.json`,
  `state/SHOWCASE.md` per finished idea; ADR only when a rule of the world changes.
- Old paperwork in `state/archive/`, old Bible books in `bible/archive/`.
- Headless: never `cd "<repo>" && …` (refused). Human-only files are drafted in `setup/files/` and
  installed by the Human with `bash setup/install.sh`.

## Next moves
1. The pitch and the gates (Next up 2), or the richer data packages (company data, headlines).
2. Then the multi-manager machine (allocation + drawdown ladder + hiring), the monthly generation,
   the Observatory.
