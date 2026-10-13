# PLAN PROTOCOL — a planning session (Builder-owned)

The runner starts a planning session when no mission is ready, or after every
`builder.plan_every_missions` accepted missions (ADR-042). This is the factory's innovation loop:
the paperclip is *a more capable, more truthful world* (`bible/01_GENESIS.md`), and this session
decides what the next missions are. It writes **missions**, not code. Lead: `lead_hard` (opus).

Gate 0 of `protocol/CYCLE.md` applies. Work on `main`; run the suite before every commit.

## 1. Look back — measure, don't remember
- Runner metrics: `tail -40 "$FIRM_HOME/metrics.jsonl"` (default `~/.firm`): per session the mode,
  mission, cost, minutes, lines written (product / tests / docs), main green, acceptance result,
  red-first, acceptance edits. Compute since the last plan: missions accepted, cost and sessions per
  mission versus estimate, false "done" claims, docs share.
- `$FIRM_HOME/regression.json` (written by the runner before this session): every done mission's
  acceptance re-run on `main`. A failure there is the first mission of the new queue.
- `state/SHOWCASE.md`, `state/missions.json`, the last 5 journal entries (tail), `state/FINDINGS.md`
  (tail), `state/QUESTIONS.md` (human answers).
- Tick every Era exit criterion that code already meets, with its evidence (X-011).

## 2. Look at the world
What can the world do now that it could not at the last plan? What became predictable or boring?
Where is the frontier? Answer in 3–6 lines in the journal entry.

## 3. Look outward (bounded)
At most ~10 web searches/fetches, or one research helper. Papers, repos and docs on multi-agent
systems, agent economies, market simulation, evolution, institutions, and agent harnesses. Steal
mechanisms, record sources in `state/IDEAS.md`.

## 4. Ideate and decide
- Append ideas to `state/IDEAS.md`. Pick the top 3: adopt (→ mission), park, or reject, each with a
  reason.
- **Ambition check:** is the world more capable than at the last plan? What would make the Human say
  "I've never seen that"? If the honest answer is "nothing changed", the next missions change that.
- Keep `bible/09_BUILDER_VISION.md` one step ahead: the next destination, its scientific question,
  and how it will be measured.

## 5. Write the queue
Leave **3–6 `ready` missions** in `state/missions.json`, ordered, each meeting `protocol/MISSIONS.md`
(concrete, efficient, stable). Re-cut, merge or drop stale missions with reasons. At most 1 in 5 is
hardening. Prefer missions that need nothing from the Human; one that does waits behind them.
A mission needing a cap or a key is still written — marked in `notes` — and the question goes to
`state/QUESTIONS.md`.

## 6. Improve the factory (Era ∞, one hypothesis)
From the metrics in §1: one change to the Builder's own process, with a hypothesis and the metric
that will judge it. Builder-owned (`protocol/`) → make it now; the auditor reviews any `protocol/`
change before it is committed. Protected (`.claude/`, `loop/`, `governance/`) → `state/PROPOSALS.md`.
If a change made at an earlier plan made the metrics worse, revert it and record the finding.

## 7. Report and record
- `state/REPORT.md` (rewrite, ≤ 1 page): what the world can do now, what the next missions are and
  why, what the Human should decide.
- Journal entry (`## Cycle NNNN — plan (<ISO date>)`), `state/PROGRESS.md` (next: the first ready
  mission), `state/STATE.md` if a fact changed.
- `state/loop_status.json` = `{"cycle": N, "mode": "plan", "result": "planned", "ts": "<ISO>"}`.
- Commit `cycle NNNN: plan — <one line>` on `main`, push.

## The first planning session (cycle 37): re-foundation
`state/missions.json` is empty. Convert the old plan into missions under the new standard:
`bible/09_BUILDER_VISION.md` §3 milestones (M1–M6), the open Era I exit criteria
(`bible/05_ERAS.md`), the open items of `state/BACKLOG.md` (slices R-*, B-*), the strict xfails.
Slices are raw material: merge them into capabilities. Leftover physics holes go into one hardening
mission. Mark `state/BACKLOG.md` items that became missions with their mission id.
