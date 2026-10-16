# 06 — The Loop: how the Builder works forever

Living book. Builder v2 since cycle 37 (ADR-042). The loop is: `loop/builder.sh start` (human-owned)
→ `loop/run.sh` → per session: `loop/preflight.py` (checks + chooses the mode) → `claude -p
"/cycle <mode>"` → `loop/preflight.py --post` (the out-of-band referee) → next session. The
gates are in `.claude/commands/cycle.md`; the procedure in `protocol/CYCLE.md` (build) and
`protocol/PLAN.md` (plan); how work is written in `protocol/MISSIONS.md`. This book explains why.

## 1. Missions, sessions, and why

**The unit of work is a mission**: a capability of the world someone can run and inspect, defined
by an executable acceptance check committed before the code (`protocol/MISSIONS.md`). A mission takes
1–4 **sessions** (still numbered as cycles). Planning happens once per mission, review once per
mission, and "done" is decided by the acceptance check run by the runner — not by the Builder's
own account of its work.

Why (ADR-042): cycles 1–36 made the unit "one slice that fits one session" and paid the whole
review ceremony on every slice — about one demonstrable capability per six cycles. The field reached
the same conclusion independently: a unit is a feature someone can test end to end; one planner,
one final evaluator; verification grounded in the running system, because agents judging their own
progress mistake activity for progress (Anthropic 2025, 2026; arXiv 2607.25152).

A session ends in exactly one result, written to `state/loop_status.json`:
- `merged` — a mission is done: acceptance passes, suite green, validator + auditor passed, on `main`;
- `progress` — the mission moved; its work is committed and pushed on its branch; `state/PROGRESS.md`
  hands off to the next session;
- `planned` — a planning session left a groomed queue of ready missions;
- `failed` — the attempt did not succeed; the branch is kept, the reason is journaled;
- `blocked` — nothing can proceed without the Human; `state/BLOCKED.md` explains why.

The runner re-checks `main` and the acceptance check itself after every session. A claimed merge it
cannot reproduce counts as `failed` and is flagged (`false_done`). Half-done work never reaches `main`.

## 2. The session

0. **Preflight** (runner, before Claude starts): no `governance/HALT`; protected files match their
   sealed hashes; the team config is valid; no open high-severity incident; sessions today < limit;
   consecutive failures < limit. Then the **mode**: `build` if a mission is active (or a mission
   branch is open), `plan` if no mission is ready, after every `builder.plan_every_missions` accepted
   missions, or when the active mission has run twice its estimate; `diagnosis` after
   `max_consecutive_failures`. Before a plan session the runner re-runs every done mission's acceptance
   check on `main` (`$FIRM_HOME/regression.json`).
1. **Build session** (`protocol/CYCLE.md`): resume the active mission from `state/PROGRESS.md`, or start
   the next ready one — architect plan (Gate 2), acceptance check written and failing, then
   milestones, each green and pushed. When the acceptance check passes: validator, red-team (physics),
   auditor (Gate 5), merge (Gate 7), SHOWCASE.
2. **Plan session** (`protocol/PLAN.md`): measure (runner metrics, regressions, showcase), look at the
   world, look outward, ideate, keep `09_BUILDER_VISION.md` one step ahead, write 3–6 ready missions,
   one Era ∞ hypothesis for the factory itself, report to the Human.
3. **Diagnosis session**: no mission work; root cause → `state/BLOCKED.md`; fix only if small and safe.
4. **Record** (every session, small): journal entry (3–8 lines), `state/PROGRESS.md`,
   `state/loop_status.json`. On a merge: `state/SHOWCASE.md`, `state/STATE.md`. Metrics are the
   runner's (`$FIRM_HOME/metrics.jsonl`), never hand-written.

Work priority (the planner orders the queue by it): 1. failing tests on `main`, a failing done-mission
acceptance check, open incidents; 2. Constitution compliance gaps; 3. human answers / overrides in
`state/QUESTIONS.md`; 4. **Launch Pad:** open exit criteria of the current Era; **after it:** the
Builder's own roadmap (`09_BUILDER_VISION.md`); 5. experiments that answer the current Era's question;
6. Era ∞ self-improvement; 7. hardening (≤ 1 mission in 5 unless a hole is high).

## 3. The state files (the Builder's memory)

| File | What | Rule |
|---|---|---|
| `state/missions.json` | The mission queue (standard: `protocol/MISSIONS.md`) | Planner writes; build sessions move status |
| `state/missions/M-NNN.md` | The architect's plan for one mission, plus deviations | Append as you go |
| `acceptance/M-NNN.py` | A mission's executable definition of done | Before the code; kept forever |
| `state/PROGRESS.md` | The last session's handoff (≤ 40 lines) | Rewrite every session |
| `state/SHOWCASE.md` | What's new: one entry per accepted mission + its demo | Append |
| `state/STATE.md` | Current Era, what exists (a map, ≤ 120 lines) | Rewrite on merges |
| `state/JOURNAL.md` | One short entry per session | Append-only |
| `state/FINDINGS.md` | Lab notebook: evidenced observations of the world and the scales | Append-only |
| `state/QUESTIONS.md` | Questions for the Human, **each with the answer chosen** | Builder appends; Human answers |
| `state/PROPOSALS.md` | Proposed changes to protected files or caps | Builder appends; Human decides |
| `state/REPORT.md` | One page for the Human: what changed, what's next, what to decide | Rewrite at plan sessions |
| `state/IDEAS.md` | The idea bank — raw material of future missions and Eras | Append; mark adopted/rejected |
| `state/INCIDENTS.md` | Seal breaches / outside-world attempts | Append-only |
| `state/BILLS.md` | Era VI: bills from agents inside the world | Append-only |
| `state/BACKLOG.md` | Legacy slice backlog (cycles 1–36): raw material for planners | Mark items that became missions |
| `state/METRICS.md` | Hand-written metrics, cycles 0–36 (frozen) | Read-only history |
| `state/SURVEY.md` | Era ½ output | Rewrite when re-surveyed |
| `state/loop_status.json` | `{cycle, mode, mission, result, branch, ts}` for the runner | Overwrite |

Outside the repo, written only by the runner: `$FIRM_HOME/metrics.jsonl` (per session: mode, mission,
cost, minutes, lines written by kind, main green, accepted, red-first, acceptance edits, flags),
`cycles.log`, `acceptance.json`, `regression.json`.

## 4. Asking the Human

The Builder never blocks on a question it can answer with the prime rule
(`01_GENESIS.md` §4). Format in `state/QUESTIONS.md`:

```
## Q-0007 (cycle 42) — <short title>
Context: …
Options: A … / B … / C …
Chosen: B, because <how it serves the future system>.
Reversible: yes — <how>
Human answer: (empty)
```

Must wait (end the session `blocked`) only for: changes to protected files, cap or limit
changes, anything that could touch the real world, a missing credential with no fake
alternative, or a Constitution conflict it cannot resolve. A mission that needs one of these waits
in the queue behind missions that do not.

## 5. Stopping conditions

The loop stops (runner exits or skips) when:
- `governance/HALT` exists (also checked every minute while waiting for a usage-limit reset);
- a protected file's hash doesn't match the seal (someone or something changed it);
- `builder.max_consecutive_failures` failed sessions in a row → one **diagnosis session**; if that
  one fails too, the loop stops until the Human reads `BLOCKED.md` and deletes `~/.firm/failures`;
- `builder.max_cycles_per_day` sessions reached (resumes next day), or an optional USD cap is reached;
- a usage limit whose reset is further than `builder.max_wait_hours` away (closer: the runner waits);
- a session runs longer than `builder.max_session_hours` (hang guard: that session is stopped);
- an open incident in `state/INCIDENTS.md` marked `severity: high`.

## 6. Planning sessions replace the 10-cycle retrospective

Every planning session is a retrospective with numbers: missions accepted since the last plan,
sessions and cost per mission versus estimate, false "done" claims, regressions, the docs share of
what was written. Re-read Genesis and the Constitution at least every third planning session.
Answer in the journal: Is the work still pointed at the current Era's question? What became
predictable (boring)? Move the frontier there. What did we learn about the scales?

## 7. Git rules

- `main` is always green. A mission lives on `mission/M-NNN-<slug>` (cycles 1–36: `cycle/NNNN-slug`),
  pushed at every milestone. Plan sessions commit state/Bible/protocol changes on `main` directly,
  suite green.
- No force-push, no `reset --hard` on shared history, no rebase of `main`, no deleting
  branches that hold failed attempts (they are evidence).
- Commit messages: `M-NNN: <what> — <why>` on missions, `cycle NNNN: <what>` otherwise. End with the
  attribution lines the session provides, if any.
- Never commit secrets, `*.db`, `*.local.json`, `.env`, cassettes containing keys.

## 8. Builder self-improvement rules

- Claude Code protects `.claude/`, so the Builder's editable process lives in **`protocol/`**
  (P-0003): `CYCLE.md`, `PLAN.md`, `MISSIONS.md`, `agents/*-extra.md` (additions only for the
  sealed roles), `agents/<role>.md` (new helper roles, launched via a general-purpose subagent),
  `skills/` (reusable procedures).
- `.claude/commands/cycle.md` and `.claude/agents/*` are thin, human-owned and sealed: they hold
  the gates and the core role instructions. The Builder never weakens them; it proposes changes.
- Every change to its own tooling is an Era ∞ change with a hypothesis and a metric, made in a plan
  session and reviewed by the auditor.
- If a change to its own process made the runner's metrics worse over the next planning period,
  revert it and record the finding. The metrics are the runner's, so the judge is not the judged.

## 9. Subagents

`architect` (plans a mission), `validator` (runs the checks, reports evidence), `red-team` (attacks
physics, writes failing tests with a severity), `auditor` (reviews a mission before merge, judges the
acceptance check), `worker` (side tasks in a worktree when `parallel_workers` > 0). Models:
`governance/human.yaml` → `builder.team`. Red-team at least once per Era and on every mission that
touches `app/registry`, `app/oms`, `app/marketdata`, metering, or the Runtime's halt/budget code.

## 10. Ideation — coming up with the next big idea

The Human didn't get this project from a ticket list; he imagined it. After the Launch
Pad, so must you. Planning sessions are where it happens (`protocol/PLAN.md`):

- **Every session:** if the work made you think of something — a mechanism, an institution, an
  experiment, a shortcut, a new kind of agent — append it to `state/IDEAS.md` (one line).
- **Every planning session:** pick the 3 most promising ideas: scientific question, what it needs,
  how to measure it, what it would make possible. Adopt (→ a mission), park, or reject — with a
  reason. Keep `bible/09_BUILDER_VISION.md` one step ahead of the work.
- **Look outward:** papers, repos, and docs on multi-agent systems, agent economies, market
  simulation, evolution, institutions, agent harnesses. Steal the best mechanisms, combine them in
  ways nobody has. Record sources.
- **Ambition check:** *is the world more capable than at the last plan? What would make the Human
  say "I've never seen that"?* If the honest answer is "nothing changed", the next missions change it.
