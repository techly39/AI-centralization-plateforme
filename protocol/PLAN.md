# PLAN — a planning session (Builder-owned; ADR-046)

The runner starts one when no idea is ready or active, or after every few accepted ideas
(`builder.plan_every_missions`). It decides what gets built next. It writes the book and the queue,
not code. Orient as in `protocol/CYCLE.md` §1 (HALT, cycle number, comments). Work on `main`.

## 1. Look back (measure, don't remember)
- `tail -20 "$FIRM_HOME/metrics.jsonl"`: per session mode, idea, cost, minutes, lines written,
  accepted. Since the last plan: ideas finished, sessions and cost per idea, false "done" claims.
- `$FIRM_HOME/regression.json`: every finished idea's demo re-run on `main`. A failure is fixed first.
- `state/SHOWCASE.md`, the last journal lines, `state/FINDINGS.md` (tail).

## 2. Look at the firm
What can the firm do now that it could not at the last plan? Is it more alive: more agents, more
trading, more decisions made by agents rather than scripts? If not, the next idea changes that.

## 3. Update the book
- Every idea's `Status:` and `Now:` line true to the code.
- The Human's comments since the last plan acted on (answered in `state/comments.json`).
- **Next up** re-ordered, with one line of reason for any change. Keep 3–6 ideas there.
- Read "Known physics holes" before choosing: a hole the next idea will stand on (its money, its
  data, its permissions) is fixed *inside* that idea and named in its queue `notes`, not left for
  later. (Cycle 47; judged by: the next physics idea's red-team and auditor find nothing rooted in a
  hole already written in the book.)
- When the Human's ideas are exhausted or all blocked: write your own ideas in Part 4
  (`From: Builder`), the best into Next up. Look outward first if useful (≤ 10 searches: agent
  economies, market simulation, institutions, evolution, harnesses); cite sources in the idea.

## 4. Queue
`state/missions.json`: one `ready` entry for the first idea of Next up (format in `CYCLE.md` §2;
estimate 1–4 sessions; bigger → split by what someone can see working). Drop stale entries with a
reason in `notes`.

## 5. Improve the factory (one change)
From §1's numbers, one change to your own process with the number that will judge it. Builder-owned
(`protocol/`, `CLAUDE.md`) → make it now. Human-owned → a draft in `setup/files/` + a line in
`state/PROPOSALS.md`. If an earlier change made the numbers worse, revert it. A rule whose
"judged by" was met keeps its words and loses its dated note (every session re-reads `protocol/`).

## 6. Record
`state/PROGRESS.md` (next: the ready idea), one journal line, `state/loop_status.json`
`{"cycle": N, "mode": "plan", "result": "planned", "ts": "<ISO>"}`. Commit on `main` with the suite
green, push.
