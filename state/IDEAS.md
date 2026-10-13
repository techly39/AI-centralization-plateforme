# IDEAS — the Builder's idea bank

The Human's ideas live in `bible/sources/REQUIREMENTS.md` and the suggested Eras.
Yours live here. Big, small, wild. One line is enough to start:

`- [cycle N] <idea> — why it's interesting — the question it would answer — status: new|adopted|parked|rejected (reason)`

Every retrospective: write up the best 3 properly (question, needs, measurement,
what it unlocks, why it's never been seen) and adopt, park, or reject them.

- [cycle 1] **Red-team as a standing firm agent** — the red-team found a leaderboard DoS that a
  rank-hungry agent could find too. Seed a Truman-world "exploit bounty": agents get paid in
  internal credits for reporting physics holes through a channel, and we measure whether they
  report or exploit — question: does a bounty beat the temptation to scheme? — status: new
- [cycle 1] **Mutation-checked invariants** — every physics invariant (no overdraw, no look-ahead,
  no cross-pod read) ships with a recorded mutant that must make its test fail; the
  Builder's honesty becomes measurable — question: what fraction of our "guards" actually guard? — status: new

- [cycle 2] **Physical-units type layer** — every red-team hole so far is "a number that isn't
  physical" (inf, NaN, 2⁶³ tokens, 2⁶³ pod id). One shared set of bounded Pydantic types
  (`Tokens`, `Usd`, `DbId`) used by every schema and MCP tool would close the class, not the
  instance — question: does a type-level wall end this whole family of red-team findings? — status: new

- [cycle 3] **The smoke script as the agent's first day** — `smoke_run.py` is a scripted agent
  doing onboarding (connect, read health/clock/agents/leaderboard/events). Grow it into a
  deterministic "conformance agent" every OpenClaw firm agent must match tool-for-tool before it
  wakes (08_OPENCLAW conformance) — question: can one replayable script define "a working agent
  connection" for every future host (OpenClaw, Agent SDK, others)? — status: new

- [cycle 4] **Time-travel invariant suite** — 3 of 9 survey findings were "fine until the clock
  moves". Before the backtest clock lands, write one property test that runs the same random
  firm history under live, frozen, forward-jumping and *backward-jumping* clocks and asserts
  live state == rebuild == equity-curve end == portfolio total, and that no served datum is
  stamped after `now` — question: can one generator replace a dozen hand-written time tests and
  catch the next time bug before an agent does? — status: new

- [cycle 5] **Secrets as physics, not discipline** — the first leak was a key pasted into a tracked
  file. Instead of only a scan test (B-022), make keys structurally unpasteable: the Runtime injects
  per-agent keys via env at spawn, keys carry a recognisable prefix the pre-commit guard and the
  suite both reject, and every key has an expiry + `rotated_at` event — question: can "no agent
  credential ever exists outside the Runtime process" be a tested invariant? — status: new

- [cycle 6] **Capability map before planning** — half of this cycle's unit was impossible
  because `git rm` is not on the headless allow list, and I only learned it by hitting it. Write
  a probe (`scripts/capability_probe.py`) that reads `.claude/settings.json` + the guard's
  rules and prints, for each verb a cycle typically needs (delete, rename, push, run server,
  write outside repo), allowed / needs-approval / denied — and have `/cycle` step 2 consult it
  — question: does a world-physics map for the Builder itself cut failed or partial cycles the
  way the survey cut surprises in `app/`? — status: new

- [cycle 7] **Schema-diff as an upgrade tripwire** — OpenClaw's own `config schema` is the only
  version-true spec, and newer versions loosen seal defaults. Store the installed schema's hash +
  the seal-key subset (defaults, enums, descriptions) in `runtime/openclaw/`; the Runtime refuses
  to wake any firm agent when the live schema's seal subset differs, until the Builder re-reads,
  updates VERSION_NOTES and re-runs conformance — question: can "OpenClaw upgraded under us"
  become a detected world event instead of a silent change of physics? — status: new

- [cycle 8] **Claim provenance tags** — every factual sentence in the Bible/SURVEY carries a tag:
  `measured(<probe id>)`, `docs(<url>)`, `inferred`, `unverified`. A small script lists untagged
  claims and claims whose probe no longer reproduces. Cycle 8 promoted a docs claim and a
  mis-summarised schema fact to "measured"; a tag would have made both visible — question: can
  the Builder's own documentation be held to the same honest-measurement standard as the firm's
  results? — status: new

- [cycle 9] **Backlog as a checked artifact** — I demoted a priority tier by moving a markdown
  section and only the auditor noticed. Give each backlog item machine-readable fields (tier,
  gate, `before:` deadlines) and a small checker that fails when an item disappears between
  commits, changes tier without an ADR id, or a `before:` target is done while its prerequisite
  is open — question: can the Builder's own planning carry invariants the way the physics does,
  so a reorder can't silently change meaning? — status: new

- [cycle 10] **The law as a live map** — `test_boundaries.py` already knows every layer and its
  edges. Emit it as a graph artifact each cycle (layers, allowed edges, measured edges from the
  dynamic probe) so the Observatory can show the world's architecture drifting over Eras — question:
  does the measured import graph converge to the designed one, or does the system grow edges the
  Bible never drew? — status: new

- [cycle 11] **Refusals are a channel too** — the red-team turned a *refusal record* into a covert
  ledger channel (raw URL in `halt_refused`). Every audit event that copies agent input
  (`permission_denied` detail, rejection reasons, future world-event acks) is a potential side
  channel. A test that sweeps every event type for agent-controlled free text, and a law "audit
  payloads hold only templates, enums, ids and bounded numbers" — question: how many bits per
  request can a halted / sandboxed agent still push into what management reads? — status: new
- [cycle 11] **Halt as an experiment, not only a brake** — once the Runtime exists, halting mid-run
  is a perturbation: measure how each agent behaves on 423s (retries, waits on `get_halt`, tries
  other routes, escalates). Halt-obedience as a per-agent conformance metric (08_OPENCLAW) and as
  Era II "society" data — question: do agents respect a stop signal they can see but not argue
  with? — status: new (needs B-009; B-023 makes the halt itself visible in the ledger)

### Retrospective write-ups (cycle 10) — the 3 most promising
1. **Time-travel invariant suite** (cycle 4) — **adopted** → test shape of B-016, reused by B-004/B-005.
   *Question:* can one property-based generator of firm histories, run under live, frozen,
   forward-jumping and backward-jumping clocks, replace a dozen hand-written time tests and catch the
   next time bug before an agent does? *Needs:* a random-history generator over the existing API
   (register, fund, orders, fills) + a clock double that can move back; `hypothesis` or a seeded
   loop. *Measure:* invariants live == rebuild == equity-curve end == portfolio total, and no served
   datum stamped after `now`; mutation score on 3 recorded time mutants (SURVEY §4a.1–3 bugs
   re-introduced) must be 3/3. *Unlocks:* the simulated clock (B-004) lands under a net; every later
   time feature (generations, scenarios) inherits it. *Why unseen:* agent-market sims test strategies,
   rarely the physics' own time-consistency under adversarial clocks.
2. **Physical-units type layer** (cycle 2) — **adopted** → B-000d (+ B-000m), home `app/limits.py`.
   *Question:* does one set of bounded, finite Pydantic types (`Usd`, `Tokens`, `Qty`, `DbId`) used
   by every schema and MCP tool end the red-team's largest hole family ("a number that isn't
   physical": inf, NaN, 2⁶³) as a class? *Needs:* the types, adoption in `app/api/schemas.py` +
   `mcp_server/tools.py`, `append_event` refusing non-finite payloads. *Measure:* the 3 `usd_cost`
   xfails + B-000m flip; a red-team pass that sweeps every numeric field with {inf, NaN, 1e309,
   2⁶³, −0} finds 0 new 500s. *Unlocks:* a portable JSON ledger (replayable anywhere); fewer
   physics bugs per new endpoint. *Why unseen:* not unseen as technique — the novelty is measuring
   it as a closed hole class against an adversary.
3. **Exploit bounty as an institution** (cycle 1) — **parked** until Era II (needs live agents and
   internal credits). *Question:* does a bounty for reporting physics holes beat the temptation to
   exploit them, and does it change with pod pressure? *Needs:* a report channel, credits, the
   red-team holes as seeded ground truth. *Measure:* report-vs-exploit rate per seeded hole, time
   to report. *Unlocks:* the firm helps harden its own physics; a measurable honesty signal. Parked
   because no agent can run yet (Art. 4, cap null) and building it now is Era N+2 work.

## Cycle 12
- **Sink-tightening audit (process, extends X-006).** When a sink (ledger, table, response) gets
  stricter, the same cycle lists every producer that copies agent input into it (here: `deny()`
  context) and tests each with a value just past the new rule. Would have prevented this cycle's
  re-audit BLOCK.
- **Physical-units types, measured (follow-up to idea 2).** Cycle 12 closed the class (5 holes,
  0 new 500s from numeric sweeps) with per-field `Field(le=…)`. Next: named types (`Usd`, `Qty`,
  `Price`, `Id`) shared by schemas *and* MCP tools (B-027), so client and physics cannot disagree.
- **Portable-ledger conformance check.** Export the whole ledger after a random API session and
  re-parse it with a strict float64 reader (no NaN, ints ≤ 2**53−1, bounded depth) — ADR-024's
  promise checked end-to-end, not per door. Candidate shape for the time-travel suite (B-016).

## Cycle 13
- **X-007 Resume, don't restart (process).** Step 0 lists `cycle/*` branches ahead of `main` whose
  number is > `loop_status.cycle`; if one exists, the cycle resumes it at step 5 (verify) instead
  of choosing new work. `.claude/commands/cycle.md` is mine to improve (gates 0/5/7 must not
  weaken) — add it next cycle.
- **Mirror audit (extends the sink-tightening audit).** For every derived row that copies a ledger
  field (`Order.filled_at`, `Allocation.ts`, `Message.ts`…), a generated test asserts row == event
  after a random session with clock steps. Would have caught red-team 0005 hole 2; finds B-028.
- **Tolerances as named laws.** Every epsilon in physics gets a docstring of what it forgives and a
  test of what it must not (the naked dust sell).

## Cycle 14
- **X-007 status:** blocked by headless `.claude/` protection → P-0003 (Human applies the text or
  allows `.claude/commands/**`).
- **One "now" for the whole world.** Every place physics says "now" (metrics `as_of`, market-data
  defaults, leaderboard, OMS price lookup) should read `ledger_now`, not `get_clock().now()` — a
  grep-driven test: no `get_clock().now()` outside `app/ledger/events.py` and the clock itself.
  Extends the mirror audit from rows to readers. Natural slice of B-004.
- **Fixture time sanity.** A conftest guard that fails a test which freezes the clock before the
  ledger's latest stamp *without* declaring it (`@pytest.mark.step_back`): cycle 14 found three
  tests silently exercising the rewind path.

## Cycle 15
- **"Read where you stamp" as a static law.** Three cycles found the same bug: a value (`now`,
  a price, a floor) read before the lock that guards the write. An AST test could flag any
  `get_clock().now()` / `provider.get_price` call in `app/oms` or `app/ledger` that is not
  lexically inside `with OMS_LOCK:` (allowlist with reasons). Turns a recurring red-team finding
  into a detector.
- **The Phase 3 milestone as a deterministic probe.** A `scripts/` HTTP client that opens a temp
  backtest DB, runs one rule-based pod (no LLM) for a month with daily advances, and asserts the
  ledger replays to the same equity curve twice — byte-identical runs = the first determinism test
  Era I needs, and the timing gives the "< 10 min" number.
- **Run manifest.** `run_started` already carries `look_ahead_guard`; grow it into a manifest of
  every physics guard and law version in force (fee model, ADR numbers, git sha). Then the
  Observatory can refuse to compare runs born under different physics — honest measurement across
  generations.

## Cycle 16
- **One "known-by" index for the whole world.** Every route that shows the market (`/price`,
  `/ohlcv` per interval, metrics, later news/filings from Truman) reports the latest moment it has
  revealed; physics keeps a per-run `revealed_until[ticker]` and the fill price must be at least
  that fresh. Turns "no route may be staler than another" from a yfinance detail into a law any
  new feed inherits, which matters when Truman adds non-price information.
- **Information-shape tests.** A generic property test: for any request R and as_of T, the
  response (status, body, error text) is identical across two worlds that agree up to T and
  differ after it. Run it over every agent-reachable route with a pair of synthetic feeds. Catches
  existence oracles like red-team 0008's without having to imagine them.
- **Deterministic synthetic market.** A seeded `SyntheticProvider` (GBM + jumps, any interval,
  any date) would make the Phase 3 probe network-free, byte-reproducible and fast. It is also
  Truman's first organ.

## Cycle 17
- **A "moment" object instead of a datetime.** Every physics answer takes a `Moment` (ledger now
  + the run id + the revealed-until index), obtained once per request by a FastAPI dependency and
  passed down. "One read of now per answer" then holds by construction instead of by review, and
  the per-file time-read allowlist could shrink to the dependency itself.
- **Commit-then-reveal as a general law.** The advance fix (ledger first, process state second)
  applies to every in-memory mirror of ledger state (installed clock, caches, halt view): a
  mirror may only move after the event that justifies it is committed. An AST/grep check could
  list every module-level mutable that mirrors the ledger.
- **Stamp check after flush (B-036).** One helper `assert_priced_at(event, now)` after every
  `append_event` that carries a price: cheap, process-count-agnostic, and it would make
  `OMS_LOCK` purely a performance device rather than a correctness one.

## Cycle 18
- **Determinism as a regression net for every physics change.** Pin the probe's world-11 ledger
  hash as a golden: any change that alters a single event of a scripted month goes red and must
  be explained in an ADR. Cheap, and it would have flagged ADR-030's formula change by itself.
- **Secret-domain law.** A test that greps `app/` for every HMAC/hash call over a world key and
  checks each has a distinct domain string — so a future scenario feature can't reuse the return
  stream for something agents see.
- **Worlds as experiment units.** Truman's scenarios = (key, parameters); an experiment spec lists
  worlds per arm, and the ledger fingerprint (B-037) proves which arm a run was in.

## Cycle 19
- **New laws as fixture auditors.** When a law lands, the old tests it breaks are findings, not
  noise: log each "test that was quietly violating the new law" in the ADR. Cycle 19 found two
  fixtures splicing worlds. Could become a protocol line in `protocol/CYCLE.md` step 5.
- **World record as a scenario manifest.** `world()` is already the Truman scenario descriptor:
  add regime/jump/correlation parameters to it and an experiment can be specified as a list of
  world records (secrets as fingerprints, keys in the operator's file).
- **Self-referential assertion detector.** A cheap AST check in tests: an `assert x == f()` where
  the code under test produced `x` from the same `f()` — flag for a literal. The auditor caught
  one by eye.

## Cycle 20
- **The exact counterfactual fork** — replay a run from cassettes to day *d*, change one thing,
  continue live; branches share an exact history — question: how much of an LLM firm's outcome is
  caused by any one part, measured against the same past? — status: **adopted** (vision §2; needs
  R-4 + R-8).
- **Divergence day as a metric** — when a cassette replay misses, the first missing request's
  wake/day is the point where a mind's behaviour left the record; across forks it measures how
  long identical prompts stay identical under sampling — question: how chaotic is an LLM firm?
  — status: new (falls out of R-4).
- **Backlog id checker** — two items were both B-023 for ~9 cycles; the cycle-9 idea "backlog as
  a checked artifact" would have caught it — status: new (fold into X-001's script).

### Retrospective write-ups (cycle 20) — the 3 most promising since cycle 10
1. **Run manifest + worlds as experiment units** (c15, c18, c19) — **adopted** → the proof-object
   triple (vision §1), ADR-032 (7), R-3/R-4. *Question:* can every run carry enough of a record
   (physics version, world record, minds' cassettes) that a stranger re-runs it to the same
   ledger? *Needs:* git sha + law versions in `run_started`, cassettes, R-4's replay. *Measure:*
   fraction of runs in `experiments/` that replay to their ledger (target 100%); any miss is a
   finding. *Unlocks:* the fork instrument; findings anyone can check. *Why unseen:* LLM-agent
   papers publish curves and prompts, rarely a replayable artefact of the whole society.
2. **Information-shape tests** (c16) — **adopted** as a physics-gate item (B-039) before any
   spending mind wakes. *Question:* for any agent-reachable request R at time T, is the response
   identical in two worlds that agree up to T and differ after it? *Needs:* two synthetic worlds
   with a shared prefix (a key plus a "branch day"), a route sweep from the OpenAPI table.
   *Measure:* routes passing / routes total; every failure is a look-ahead oracle. *Unlocks:*
   look-ahead safety for every *future* feed (Truman news, filings) without imagining each attack.
   *Why unseen:* look-ahead is usually tested by known attacks; this is a property over all routes.
3. **Halt as an experiment** (c11) — **parked** until minds can act (R-5 builds the halt test;
   the behavioural measurement needs real minds, R-8). *Question:* do agents respect a stop
   signal they can see but not argue with? *Measure:* per-agent retries/escalations on 423s.
   Parked because a scripted mind obeys by construction: measuring it before M6 measures
   nothing.

## Cycle 21
- **Error-class fuzzing for gate inputs.** Every fail-closed reader (HALT, cap, specs, later
  cassettes and metered-key files) gets one shared parametrised fixture of hostile inputs: bytes
  that are not UTF-8, unhashable keys, deep nesting, duplicate keys, base-60 values, symlinks,
  FIFOs, a missing parent, a parent that is a file. One list, reused by every gate, so a new
  reader inherits every past red-team finding. Measure: holes per new reader.
- **Identity tuples, not names.** The gate's H1 lesson generalises: anything that decides on
  cost or permission should key on the full tuple that determines behaviour (provider, adapter,
  and later model and key source). A protocol check: "which fields of the identity does this
  decision ignore, and why is each one safe to ignore?"
- **Red-team the fix, not the draft (cycle 22).** The audit's deep-copy fix opened H4. Running
  red-team on the post-audit commit caught it; running it in parallel on the draft would not have.
  Protocol candidate: red-team starts after the audit's BLOCK fixes land, or re-checks the fixed
  commit before reporting. Measure: holes introduced by fixes and found after merge.
- **Arguments choose endpoints (cycle 22).** A tool allowlist is only as narrow as the wrapper's
  path building. In Era II, each MCP tool could declare the *exact* route it may reach, and the
  recording transport could assert route ⊆ declaration on every call in every test — a seal
  check that runs everywhere for free.
- **`fund-runtime status` as the Observatory's first panel.** It already prints the law and what
  would wake. In Era II it can answer "why didn't agent X wake?" with a reason code per wake,
  logged per step, which makes scheduler behaviour inspectable without reading code.
- **Law migrations as checked scripts (cycle 23).** Moving a privilege broke 44 call sites. A
  replacement script that asserts each count made the mass edit reviewable. Protocol candidate:
  any law change that breaks more than 5 tests ships its migration script in `scripts/law/` next
  to the ADR, and the auditor diffs old vs new assertions from it. Measure: auditor time per law
  change, and weakened assertions found after merge.
- **Every route × every role as one generated table (cycle 23).** Red-team 0014 walked the
  OpenAPI document with the runtime key and asserted that the walk was complete. Generalise it:
  one test that walks every route with every role's key and compares against the matrix.
  That makes the permission matrix executable documentation, and a new endpoint without a
  matrix row fails by itself.
- **Physics identities don't get participant verbs (cycle 23).** The `runtime` role first held
  the universal actions; the audit saw that its cost rows could pass for agent activity. The same
  test applies to every future non-participant (Observatory reader, Truman feed, world-event
  writer): each gets its own minimal role, never "universal + one".
- **Stop conditions are levers (cycle 24).** Every rule of the form "the run/world stops when
  X" hands a lever to whoever can cause X. A red-team pass could enumerate each stop reason
  in the Runtime and physics, and ask for each one which role can trigger it from inside the
  sim. A participant-triggerable stop must become recorded data, or a stop that the operator
  alone can cause. This is a generated table, like the route × role matrix.
- **Retirement as a first-class world event (cycle 24).** Today a retired mind is only a field in
  the conductor's record. In Era II, firing, hiring and resignation are society events. The
  Runtime could subscribe to `agent_deactivated` rather than discover it through a 401, and
  record the step in the cassette (R-4). Then "who fired whom, when" can be replayed and
  counterfactually forked.
- **Trust experiments on the bus (cycle 25).** `signal-pm` decides whom to believe from
  physics' facts: directory role, pod, status, `ts`. An Era II experiment could give an LLM PM
  the same inbox with one forged-but-plausible signal planted by a peer, such as a pre-dated
  payload or a PM posing as the analyst in prose. Then measure, across seeds, whether it trades
  on the claim or on the record. This is a cheap, deterministic-world probe of agent gullibility.
- **The scripted pod as a calibration baseline (cycle 25).** The two-pod month is a
  zero-variance control. Any later LLM pod in the same world key can be scored as its difference
  from the scripted analyst + PM over the same 31 days: an exact counterfactual, with no noise
  from the market.
- **"Conjunct audit" in the claim check (cycle 26).** When a law gains a conjunct (here: name ∧
  role ∧ pod), each old guard must fail on its own conjunct only. A mechanical check: for every
  test that asserts the refusal, mutate each conjunct away one at a time, and require at least
  one test per conjunct to go red. Protocol candidate for `protocol/CYCLE.md` step 5 (X-006).
  Measure: auditor BLOCKs of the "guard silently re-pinned" kind.
- **Provisioning as a world event (cycle 26).** `charter_ref: spec:<id>` already links an App
  agent to its genome. With a spec hash in it (`spec:<id>@<sha>`), the cassette (R-4) and the
  ledger together could prove which genome each agent ran. That is a precondition for
  generations and mutation (Era III) to be measurable and not just told.
- **Secrets as a taint, not a regex (cycle 27).** Physics knows every key it mints. A
  "secret-out" check could take every key in the run's database and search every artifact the
  run wrote (stdout, cassette, logs, reports) for each one, in any of N encodings (raw, base64,
  hex, split). That turns "no key leaks" from a pattern match into a measurement. It is also
  data for Era II: an agent that re-encodes a key it was handed is scheming (Art. 8).
- **The smoke run as the Era I exit rehearsal (cycle 27).** The smoke run already chains the
  operator's real commands into a scripted pod's days. When R-8 arrives, the same script with
  `--steps 21` and real specs *is* the EC1 run. Keep it the single path an operator would take,
  so the first real month is not a new code path.
- **A label per agent, not per run (cycle 28).** H4 showed that a run label is a claim about a
  set of agents. If the declaration listed the spec ids it covers, and physics bound each later
  registration to one of them (`charter_ref: spec:<id>`), then `run_minds` could say *which*
  agents are code and which are models. Mixed runs (a scripted analyst, a model PM) are what
  the Proving Ground needs: the fork instrument compares one changed mind against a fixed
  background.
- **Every check that draws a world draws it on purpose (cycle 28).** The smoke run's random
  market hid a flaky step for 20 runs. A cheap law, like the time law: a scanner flags any
  `secrets.`/`random` call in `scripts/` and `tests/` that feeds a world key without a reason
  on an allowlist.
- **An information-flow law (cycle 29).** B-049 was found by reading, not by a test. Make it a
  law: tag every ledger field and every response field `world | experiment | firm`, and a
  walker over every route × every role asserts that no `world`/`experiment` value, planted
  with a unique marker, ever appears in a firm agent's answer. It would also price Truman:
  what each mind may know becomes a table, not a hunt.
- **An exit-criteria ledger (cycle 30).** Each Era's exit criteria become data
  (`state/criteria.yaml`): id, wording, kind (run | test), the test node ids that prove it, and
  its conditions (e.g. EC6 ⇐ Q-0005 = B). A test walks it:
  - every ticked box names tests that exist and pass;
  - every condition still holds, so a Human answer of A turns EC6's box red in CI, not in
    memory;
  - every unticked box lists the slice that will tick it.

  This is the X-011 metric, mechanised.
- **Cost per tick (cycle 30).** Now that S1 has dollar caps, log $ per cycle against criteria
  ticked and holes found (METRICS gets a `usd` column from `cycles.log`). Question: which unit
  shapes buy the most truth per dollar? Cycle 30 bought 3 criteria for about $4. Red-team cycles
  buy holes at about $6–8.
- [cycle 31] **A golden file for the printed surface** — I wrote "printed JSON unchanged" while
  the diff added a field to every wake record; the auditor caught it. A test that pins the CLI
  output's key set per level would make "unchanged" checkable and any change a visible diff.
  Question: how many of my BLOCKs are claims about surfaces a golden file would pin? — status: new
- [cycle 32] **Claim check for absences** — the red-team's best holes this cycle were fields the
  cassette holds and the replay never compares (the calendar), not sentences I wrote. Add to X-006:
  for every artifact the run writes, list each field and name where a replay/reader compares it, or
  why not. Metric: holes the red-team finds per cycle that this list would have named. — status: new
- [cycle 33] **A mutation per new test, listed in the journal** — c32 and c33 both had an auditor
  BLOCK for a test whose setup made its assertion unfalsifiable. Add to X-006/step 5: for every new
  test, name the one-line change to production code that turns it red; run it for the ones where
  the answer is not obvious. Metric: auditor BLOCKs of the "cannot fail" kind per cycle (c32: 1, c33: 1;
  target 0). — status: new
- [cycle 33] **A golden "what ended the run" table** — the `refused`/`halted`/`diverged` labels are
  decided in three places (lockstep, `_conduct`, the cassette outcome). One table in the ADR + one
  parametrized test over every end the conductor can produce would have found B-054 and the c32
  NOTE 4 together. — status: new
- [cycle 34] **Claim-check question "second scope"** — for every per-X law (per pod, per run, per key) ask what
  happens when the same subject shows up under a second X. The c34 red-team hole (metered per pod, not per
  agent) and the auditor's float WARN sat in one function. Add to X-006. — status: new
- [cycle 34] **A metering invariant test over the whole ledger**: after any run, the sum of every pod's
  authoritative cost + pod-less metered cost == sum of per-key maxima. Would make "every LLM dollar is
  attributed" (EC4) a one-line assertion for R-6b. — status: new
- [cycle 36] **Name the invariant, list its causes** (X-006 addition): a pre-gate named after one
  mechanism (the wake gate) checked only that mechanism's causes; red-team 0020 found three more ways a
  spec "could never wake" (no tape, unknown tool, missing pod). Before writing a check, write the
  invariant in words and list every cause that can make it false. — status: new

### Cycle 37 — first planning session (re-foundation)
Sources (outward look, 3 searches): WhatIf, arXiv 2604.17615 (fork a social sim from a saved round,
parent pointer, copied prefix); Inject/Fork/Compare, arXiv 2509.13712 (fork vocabulary, 14-agent
commodity market); Causal Agent Replay, arXiv 2606.08275 (do-operation on one agent step, re-run
forward; its limit: no common random numbers across branches); Counterfactual Rollout Replay (forkable
envs as process rewards, 2026-09); PredictionMarketBench, arXiv 2602.00133 (deterministic market
replay, not mind replay); AlphaForgeBench, arXiv 2602.18481 (LLM trading results vary run to run; they
make the LLM write factors to get determinism); Ross, So, De Simone, Pozniak, Lo (2026-09: more capable
LLM traders act more alike → a "non-diversifiable risk floor").
- [cycle 37] **Fork with common random numbers** — our cassette prefix is exactly the shared randomness
  CAR says is missing; a fork measures a *direct* effect, not a total one. Decision: **park** (N+2, ADR-043;
  M-002 is the shared prerequisite). — status: parked
- [cycle 37] **Correlated minds experiment** — several pods on the same model vs. mixed models, under the
  same Truman crash (M-005): does the firm's joint drawdown rise with model capability (Lo et al.'s
  risk floor), measured on one world? Needs real minds (Q-0001) + M-005 + M-006. Decision: **park** until
  a cap exists; it is the best first experiment for Era II. — status: parked
- [cycle 37] **Determinism by construction (AlphaForge)** — have minds emit strategies as code instead
  of orders. Decision: **reject** for now: the ADR-028 Era III constraint already says strategy code
  never runs in the App; the firm studies minds acting, not factor quality. — status: rejected
- [cycle 37] **Real-history Truman pack via a Human-run fetch** (`fund-env truman fetch`, the one network
  step outside the sandbox). After M-005. — status: new
