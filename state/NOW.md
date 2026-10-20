# The firm lives a quarter: four real PMs compete for the same capital for three simulated months, pods die and are replaced, and the Human gets a quarter report

## How I understand it
Every part of the multi-manager machine works on its own: pitch and gates, seed, the algorithm that
re-weighs capital, the drawdown ladder, the hire that fills a dead pod's place. But each was shown
with one mind or with scripted pods. A real multi-manager is many PMs pulling at one pot of money.
This idea is the first firm-scale run:
- One made-up market, four sectors with different fates: one has an edge that lasts, one is pure
  noise, one slowly sinks, one crashes mid-quarter. Nobody inside knows which is which.
- Four real PMs (Haiku 5.5, each with its own capped key), each given one sector. They research
  (every backtest counted), pitch, and the gates judge. An eligible pitch gets a seed and its pod
  trades its rule forward.
- Every five days the algorithm moves capital by each pod's score, net of what its PM's thinking
  cost. The ladder halves, freezes and closes what bleeds; each close opens a vacancy and the next
  morning a new PM is hired, reads the post-mortem and pitches in its place.
- Nobody arranges any of it: the laws and the minds decide. The Human gets a **quarter report**:
  capital per pod week by week, who died and why, who was hired, each pod's P&L net of thinking.

## What done looks like
`uv run python acceptance/firm_quarter.py` ($0, offline):
- A (scripted minds, the same market): the edge pod is seeded and raised; the noise pod is not
  seeded; the sinking and crashing pods are closed and replaced by hires; a pod whose gross return
  beats another's, but whose thinking cost eats the difference, ranks below it (and the cheap one
  above it); the live-pod limit holds; rebuilding from the ledger gives the same books.
- B0 (scripted, through the Runtime, in a hosted world built from the recipe): the same deaths and
  hires; `replay --verify` IDENTICAL. (Built, cycle 53.)
- B (recorded, four real PMs plus their hires): `replay --verify` says IDENTICAL; the quarter
  report prints from the recording; every seed, raise, cut, close and hire is consistent with the
  laws; each mind's cost, charged by the system, is shown against its key.

## Plan
1. A quarter world recipe: four sectors of the made-up market (edge, noise, sink, crash), four
   pods, each PM's mandate naming its sector. Reuse the hosted world and the pitch desk charter.
2. Fixes the run stands on: a seeded pod's later pitches get a capital answer ("already running
   your seeded pitch" or what changed); the hiring law announced to agents as a system event.
3. The quarter report: a pure function of the ledger (capital per pod per week, closes, hires,
   P&L gross and net of thinking cost), printed by the demo, readable from the API.
4. Demo part A with scripted minds; tests for the report and the fixes.
5. Before spending: check a scripted mind reading only its tools sees every consequence of its
   acts. Budget the real run (PMs × steps; at most about $3 of the cap), check cassette size.
6. Record the real quarter, commit under `evidence/firm-quarter/`, a FINDINGS entry.
7. Red-team, auditor, merge.
Cut: session 1 = steps 1-4; session 2 = steps 5-6; session 3 = step 7.
Left out: a manager mind; PMs building their own teams; firing a PM who never earns a seed;
the debate; the monthly generation.

Changed while building (cycle 53):
- The two fixes are switched on by the run's capital law ("tell PMs", off by default), because
  the recorded hire of cycle 51 read its pitches and its capital every day: any new answer there
  would make its replay diverge. A world turns it on in its recipe, which now carries the world's
  own laws (capital, hiring) over config.yaml.
- The hiring law is announced in each PM's capital view (every PM reads it every morning), not
  as a ledger event no PM can read.
- The quarter report is an operator command (`fund-env quarter-report`), not an agent tool: a
  new tool changes the full tool list a recorded scripted mind was shown, and its replay breaks.

## Risk
Money (seeds, re-weighing, the ladder), agent creation and key minting under the cap: red-team +
auditor before merge. Holes left unless the run reaches them: empty pods count toward the
live-pod limit; the hire check lives in the router, not the permissions table.

## Progress
- cycle 52: planned.
- cycle 53: built steps 1-4 and the hosted rehearsal. Demo part A passes (scripted quarter: edge
  raised, noise never seeded, sink and crash closed and replaced by hires that earn seeds, a
  costly mind's rank turned by its thinking cost, money kept, report printed); B0 passes
  (hosted, IDENTICAL). Fails only on B: the real quarter is not recorded yet.
- cycle 54: before spending, the demo checks that each PM sees every consequence of its acts
  through its own tools the next morning (judged, seeded, raised, cut, halved, reduce-only,
  closed, hired); one gap found and closed: a closed pod's PM is now told "closed" on every
  pitch. The hosted world's pods and sectors got neutral names (the old ones told the minds
  each sector's fate). The real run's checks judge the laws, not the fates (a seed only for an
  eligible pitch, the ladder at its thresholds, one vacancy a close, the live-pod limit, no
  trading after a close, no key past its limit), and are shown to catch three forged records;
  the quarter report now prints from a recording alone. Real quarter recorded (see Progress).
  Found: a real run posts thinking cost only after its last step, so its re-weighings see none.
