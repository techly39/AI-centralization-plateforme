# Designs reproduce: a freed place is filled by a child of the month's fittest pod, its parent's model and rule with one change, its parent named, and the firm watches its own diversity

## How I understand it
Every month the firm now lets its failures go and hires into their places, but every hire is the
same fixed design (the law's one charter, models in turn). Selection removes what fails; nothing
carries what works forward. Evolution needs both. Here:
- **A pod's design is on the record**: its PM's model and charter, and the rule it pitched. Today
  the founding PMs' models live only in the Runtime's files, so the registrar declares them.
- **The parent.** At a month's end, the fittest pod of that generation (P&L net of thinking,
  above zero, still alive) becomes the parent of every hire into a place freed that month.
- **The child** gets the parent's model and rule with **exactly one change**, drawn by the law
  from a seed (another model of the pool, or one setting of the rule moved one step: its lookback,
  rebalance or number of names). It knows its parent and is handed the inherited rule as a
  starting point; it still has to pitch and pass the gates, and its pitch counts its family's
  research attempts (the best of a family has been tried by the family).
- **No fit pod** (nobody earned more than they thought) → the plain hire, as today.
- **Diversity.** Each month's end counts the distinct designs alive and the biggest family's share
  of live pods; if one family holds every live pod, that is written as a finding.
- The generation report shows the family tree.

## What done looks like
`uv run python acceptance/designs_reproduce.py` ($0, offline):
- A (scripted, three months of one made-up market): the edge pod is the fittest; the hires into
  the freed places are its children, each with one change, parent named in the ledger and in the
  child's own tools; a child's pitch counts its lineage's attempts; a month with no fit pod hires
  the plain design; a world built to collapse writes the diversity finding and the default world
  does not; with the law off nothing changes; rebuild from the ledger gives the same books.
- B0 (scripted, hosted, through the Runtime): the same, `replay --verify` IDENTICAL.
- B (recorded, real Haiku PMs): the hires are the edge pod's children; IDENTICAL for $0; the
  report prints the family tree.

## Plan
1. The founding design on the record: the registrar declares each PM's model and charter.
2. The reproduction law (`reproduction:` section, recipe-nameable, off by default so every
   older recording replays as it was): parent choice, the one change from a seed, written in the
   vacancy; the parent named; the child's tools show its parent and inherited rule.
3. Lineage attempts counted at a child's pitch (the deflated Sharpe's number of tries).
4. Diversity at each month's end, the finding on collapse; the family tree in the report.
5. Fix inside: one advance across two month ends makes one generation; a pod closed by a failed
   hire missing from its month's table.
6. Demo A + B0 (session 1-2). Visibility check, the real run with the command the demo checks,
   red-team, auditor, merge (session 3).
Left out: crossover, rewriting charters, capital reset (2c), a manager mind.

## Risk
Hiring under the cap, the gates' count of attempts, a law of physics: red-team + auditor before merge.

## Progress
- cycle 60: planned.
- cycle 61: physics built (founding model at registration, the reproduction law, the child's one
  change, its family's attempts at its pitches, diversity and the collapse finding, the family
  tree; both month-table holes fixed). Demo A passes in four worlds. Found: a child pitching its
  inherited rule is refused by the correlation gate (a copy of its living parent). Next: B0.
- cycle 62: B0 passes (the hosted months through the Runtime, the law on: both hires into freed
  places are children of pod-1, each handed its parent, change and rule; IDENTICAL). The family
  tree now reads only the ledger, so a recording draws it. Rehearsal made with the real run's very
  command; real run recording.
