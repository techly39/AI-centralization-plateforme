Cycle 0053 · building: the firm lives a quarter · branch: idea/firm-quarter
Done this session:
- A scripted quarter on one made-up market (edge, noise, sink, crash; two free sectors for hires):
  the edge pod is raised, the noise pod is never seeded, the sinking and crashing pods are closed
  and replaced the same morning by hires who earn seeds; a costly mind ($400 a morning) scores
  higher than a cheaper pod before thinking cost and lower after it; money adds up; the books
  rebuild from the ledger.
- PMs are now told what happened: a seeded pod's later pitch gets an answer ("your pod already
  runs pitch #N"), and every PM's capital view carries the hiring law. This is a switch in the
  run's capital law, off by default, so the cycle-51 recording still replays identically.
- A world's recipe can now carry its own laws; the quarter is a hosted world, and a scripted
  rehearsal through the Runtime gives the same deaths and hires and replays IDENTICAL.
- The quarter report (week-by-week equity, P&L gross and net of thinking, re-weighings, deaths,
  hires): `fund-env quarter-report`.
Next: the real quarter. First list every consequence of a PM's act and check a scripted mind sees
each through its tools. Then write the world (`acceptance/firm_quarter.py --write-world DIR
openrouter`), give the specs a model and budget, check the month's cap, and record 30 steps of
3 days (about 160 wakes, about $1-1.5). Make the report print from the recording; FINDINGS entry.
Watch out: a new agent tool breaks replay of any recording whose mind had no tool list (the
cycle-51 hire), which is why the report is an operator command. Real-sized thinking cost barely
moves a score (cents against a $200k seed); the demo uses a stand-in price to show the law.
Demo: fails only on B (the real quarter is not recorded yet); A and B0 pass; all earlier demos
and the full suite pass.
