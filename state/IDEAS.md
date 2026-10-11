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
