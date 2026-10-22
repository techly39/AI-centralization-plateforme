# A manager chooses the hires: one manager mind reads every pod, picks who fills a freed place among the hires the law allows, briefs the new PM and sets the firm's direction; it never moves capital, hires or fires by itself

## How I understand it
Today every hire is the law's alone: a freed place goes to the fittest pod's child (or a plain
hire). The Human's firm has management above the pods: it sees every pod and sets the direction,
while the algorithm moves the money. This slice gives the firm its first manager mind:
- **The board.** The manager reads every pod: cash, positions, exposures, capital from the centre,
  stage and drawdown, thinking cost, last month's fitness, its design (model, family). No PM sees it.
- **The choice.** When a place is freed, physics lists the hires the law allows: the default (the
  law's own hire), a child of each other fit pod, a plain hire on each model of the pool, each
  saying exactly what it would be. The place waits one day: the manager may pick one and write a
  brief; silent, the default stands. The Runtime hires exactly the pick the next morning.
- **The direction.** The manager writes the firm's direction; every PM reads it in its capital
  view. The new PM also reads its brief.
- **What it cannot do.** Move capital, hire, fire, register or deactivate anyone, trade, pitch:
  it is a new role (`manager`), not the registrar, and only the operator's registrar can make one.
- **Its cost.** It has no pod: its thinking is the centre's cost, never a pod's fitness.
Whether a real manager picks better than the law is the finding.

## What done looks like
`uv run python acceptance/manager_chooses_hires.py` ($0, offline):
- A (scripted): September with two fit pods and a failing one; at the month's end the failing
  PM goes, the place lists its candidates; the manager picks the other fit pod's child with a
  brief (the 'yes' case) and the Runtime hires exactly that the next morning, the new PM reading
  brief and direction; in a second world a silent manager leaves the default (the 'no' case);
  refused by name: a pick not on the list, a second pick, a pick after the hire, a PM or analyst
  reading the board or picking, the manager filling, registering, deactivating, trading; the
  manager's thinking is the centre's; law off → today's hires; rebuild gives the same books.
- B0: the same through the Runtime with the real run's very command, replay IDENTICAL.
- B (recorded): a real Haiku manager over a generation run; physics' answers checked; replay $0.

## Plan
1. A `management:` law (off by default; frozen into the first vacancy like reproduction).
2. Role `manager` + action `manage_firm` in the permission matrix; only the operator's registrar
   registers one, podless. No register / deactivate / allocation / orders / pitches.
3. `app/capital/management.py`: the board, the candidates (reproduction's child_of opened to any
   parent), the pick (`hire_picked`), the direction (`direction_set`); the vacancy fold applies the
   pick, so the fill, the design and the inherited attempts follow it. The place waits a day.
4. API `app/api/management.py` + MCP tools; the brief in the hire's vacancy, the direction in
   every capital view (only once one is written, so old recordings replay unchanged).
5. Holes: a family's sibling attempts count (law-frozen, old runs keep the old count); a parent
   with no model on record: its child's model is shown as the pool's.
6. Runtime: the onboarding skips a place still in its manager's day; a manager mind's tools.
7. Demo A, B0, real run B, red-team, auditor, merge.
Left out: firing early, opening pods, departments, a manager moving capital (never).

## Risk
Permissions, hiring, the Runtime's hire: red-team + auditor before merge.

## Progress
- cycle 66: started; plan, demo part A, physics.
