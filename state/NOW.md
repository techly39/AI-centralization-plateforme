# A generation turns over: at each month's end the firm measures every pod net of its thinking, lets go the PMs who failed, keeps their lessons in a library every PM reads, and hires into the freed places

## How I understand it
The quarter showed the firm cannot live on its own past a few months: a PM who never earns a seed
thinks (and spends) forever, a closed pod's PM keeps waking, and a dead pod's lesson reaches only
its successor. A real multi-manager runs on turnover: every month the book is marked, and the
managers who did not earn their place go. Here:
- **The month's end is a law of physics** (the "generation" law, named in a world's recipe, off by
  default so every older run replays as it was). At the first advance into a new month, physics
  measures every pod: its P&L that month and its thinking cost that month (from the meter), the
  difference being its **fitness**. One ledger event holds the whole generation's table.
- **Who goes.** A PM whose pod the risk ladder closed goes at the close. A PM whose pod never
  earned a seed goes at the month's end, once it has had a fair time (the law's grace days: a PM
  hired on the 25th is judged next month). A PM who earned a seed and kept it stays.
- **Letting go** is physics: the agent is deactivated (its key answers 401, the Runtime retires its
  mind and it spends nothing more), an unseeded pod is closed (empty, it holds no live-pod place),
  and a vacancy opens in its place. The next morning the Runtime hires into it, as it does today.
- **Lessons are kept.** Each departure writes its lesson (a pure function of the ledger: what the
  pod tried, the gates' verdicts, what it earned, what its thinking cost, why it went) into a
  **library** every PM reads (`read_library`). The firm learns across generations.
- The Human gets a **generation report** (operator command): per month, each pod's fitness, who
  stayed, who went and why, who was hired, and the lessons.

## What done looks like
`uv run python acceptance/generation_turnover.py` ($0, offline):
- A (scripted minds, in process, three months of one made-up market): at each month's end a
  generation event with every pod's fitness (P&L net of thinking charged each morning); the
  PM of a never-seeded pod is let go (deactivated, a refusal if it tries, its pod closed, its
  lesson in the library, its place hired the next morning); a ladder-closed pod's PM is let go at
  the close; a seeded PM stays; a hire reads the library; a hire made late in a month is not
  judged that month; the live-pod limit does not count a let-go PM's empty pod; with the law off,
  nothing of this happens; rebuild from the ledger gives the same books.
- B0 (scripted, hosted, through the Runtime): the same turnover, the let-go minds retired,
  `replay --verify` IDENTICAL.
- B (recorded, real Haiku PMs, three generations): IDENTICAL for $0, the generation report prints.

## Plan
1. Physics: the generation law (`generation:` section, recipe-nameable), the month's-end
   measurement, the let-go law, the lesson, the library (`GET /library` + MCP tool), a vacancy for
   an unseeded pod, the PM of a ladder-closed pod let go at the close. Rebuild handles closes.
2. A tool added must not change the tools older recordings were shown: a spec naming no tools
   gets the list as it was before this idea (new tools are named).
3. The generation report (pure function of the ledger, `fund-env generation-report`).
4. Demo part A + tests. (Session 1.)
5. Runtime: a let-go mind is retired in a replay too; thinking cost charged each step in a real run
   (from the turns' stated cost, so a replay posts the same rows), switched on per run; the hire
   check and the agent cap move into physics. B0 hosted rehearsal. (Session 2.)
6. Before spending: every consequence visible through the PM's own tools. Record the real run
   (≤ about $3), FINDINGS, red-team, auditor, merge. (Session 3.)
Left out: reproduction (2b), capital reset (2c), "the worst fitness dies" (this slice lets go only
the closed and the never-seeded), a manager mind.

## Risk
Money (the closes, the fitness the capital machine may later read), agents deactivated by physics,
hiring under the cap, metering per step: red-team + auditor before merge.

## Progress
- cycle 56: planned.
- cycle 57: steps 1-5 mostly built. Demo A passes (three scripted months: three generations,
  two PMs let go for no seed, one at its ladder close, a late hire spared, a hire reads the
  library, the limit ignores empty pods, the report prints). B0 passes (hosted, billed stand-in
  minds charged each step, let-go minds retired, IDENTICAL). Left: the hire check and the agent
  cap into physics; the visibility check; the real run (B); red-team, auditor, merge.
- cycle 57 (cut by the usage limit, its work committed): the agent cap and the hire check moved
  into physics; each PM sees its own judgement through its own key; a failed month's end retries.
- cycle 58: the real run's part of the demo: a fuller charter, checks of the month's-end law that
  judge any recording (four forged records fail them), the report from a recording; the real
  run recorded ($0.575: pod-2 let go at September's end after 8 noise pitches, the crash's PM at
  the close, both places hired and seeded; every law check passes, replay IDENTICAL). Red-team:
  the high (agent cap at every registration) and two mediums (grace judged by the longest-serving
  PM; a let-go PM's orders cancelled, a pod with money not closed) fixed, four lows filed.
  The demo still fails one check, rightly: hire-1's key spent $0.200068 of $0.20 (the provider
  finishes the turn that crosses a key's limit).
- Next (cycle 59): make a key's limit hard: refuse or shorten a turn whose worst case (its
  prompt so far + MAX_TURN_TOKENS at the model's price) would cross what the key has left, and
  count that one-turn reserve in the monthly cap; re-record B (about $0.60); auditor; merge.
