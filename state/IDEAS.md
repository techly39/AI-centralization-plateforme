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
