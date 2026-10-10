# 06 — The Loop: how the Builder works forever

Living book. The loop is: `loop/run_forever.sh` (human-owned) → `loop/preflight.py`
→ `claude -p "/cycle"` → one cycle → sleep → repeat. The protocol for one cycle is
in `.claude/commands/cycle.md`; this book explains the rules behind it.

## 1. One cycle = one finished unit of work

A cycle ends in exactly one of three states, written to `state/loop_status.json`:

- `merged` — work is done, tests green, auditor passed, merged to `main`.
- `failed` — the attempt did not succeed; the branch is kept, the reason is journaled.
- `blocked` — nothing can proceed without the Human; `state/BLOCKED.md` explains why.

Never end a cycle with half-done work on `main`.

## 2. The cycle, step by step

0. **Preflight** (runner, before Claude starts): no `governance/HALT`; protected files
   match their sealed hashes; no open high-severity incident; cycles today < limit;
   consecutive failures < limit. A dirty working tree is only a warning — step 0 of
   `/cycle` cleans up after a crashed cycle.
1. **Orient.** Read `state/STATE.md`, the last 3 entries of `state/JOURNAL.md`, the top
   of `state/BACKLOG.md`, the current Era in `bible/05_ERAS.md`, and any human answers in
   `state/QUESTIONS.md`. Every 10th cycle also re-read `bible/01_GENESIS.md` and
   `bible/00_CONSTITUTION.md` and write a retrospective (§6).
2. **Choose ONE unit of work**, by priority:
   1. failing tests on `main`, open incidents;
   2. Constitution compliance gaps;
   3. human answers / overrides in `state/QUESTIONS.md`;
   4. **Launch Pad:** open exit criteria of the current Era (Survey first — the very
      first cycles are cleaning and understanding, no features).
      **After the Launch Pad:** the Builder's own roadmap (`bible/09_BUILDER_VISION.md`,
      Eras it wrote or adopted in `05_ERAS.md`);
   5. experiments that answer the current Era's question;
   6. Era ∞ self-improvement (Launch Pad: max 1 cycle in 5);
   7. debt and refactors that block the above.
   Size it so it fits one session. If it doesn't, split it in the backlog and take the first piece.
3. **Hypothesis.** Start the journal entry: *"If I build/run X, then Y becomes
   possible / metric Z changes."*
4. **Build** on branch `cycle/<NNNN>-<slug>`. Tests first where possible. Small commits
   with clear messages. Follow the TRD for anything inside `app/`.
5. **Verify.** `uv run pytest` (all green), `uv run ruff check .` if configured,
   boundary test, determinism tests (`rebuild_state`, replay). Then run the `auditor`
   subagent on the diff; fix what it flags or record why not.
6. **Experiment** (when the unit is an experiment): spec in `experiments/<id>/spec.yaml`,
   results in `experiments/<id>/`, conclusion in `state/FINDINGS.md`. Respect budgets.
7. **Merge.** Only if green and auditor passed: merge into `main`, push `main` and the
   branch to `origin` (never force).
8. **Record.** Journal entry completed; `STATE.md` updated; backlog re-ordered with
   anything discovered; `REPORT.md` updated if something the Human should know happened;
   `METRICS.md` row appended; `loop_status.json` written. Commit these on `main`.

## 3. The state files (the Builder's memory)

| File | What | Rule |
|---|---|---|
| `state/STATE.md` | Current Era, cycle number, what's true now, next 3 moves | Rewrite each cycle, keep short |
| `state/JOURNAL.md` | One entry per cycle: hypothesis, work, result, next | Append-only |
| `state/BACKLOG.md` | Ordered work items, each tied to an Era exit criterion | Reorder freely |
| `state/FINDINGS.md` | Lab notebook: evidenced observations of the world and the scales | Append-only |
| `state/QUESTIONS.md` | Questions for the Human, **each with the answer chosen** | Builder appends; Human answers |
| `state/PROPOSALS.md` | Proposed changes to protected files or caps | Builder appends; Human decides |
| `state/REPORT.md` | Rolling 1-page report for the Human: what changed, what matters | Rewrite, short |
| `state/METRICS.md` | One row per cycle: result, turns, tests, duration, notes | Append-only |
| `state/INCIDENTS.md` | Seal breaches / outside-world attempts | Append-only |
| `state/BILLS.md` | Era VI: bills from agents inside the world | Append-only |
| `state/IDEAS.md` | The Builder's idea bank: wild, big, small — the raw material of future Eras | Append; mark ideas adopted/rejected |
| `state/SURVEY.md` | Era ½ output: what exists, works, is broken, is dead | Rewrite when re-surveyed |
| `state/loop_status.json` | `{cycle, result, branch, ts}` for the runner | Overwrite |

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

Must wait (end the cycle `blocked`) only for: changes to protected files, cap or limit
changes, anything that could touch the real world, a missing credential with no fake
alternative, or a Constitution conflict it cannot resolve.

## 5. Stopping conditions

The loop stops (runner exits or skips) when:
- `governance/HALT` exists;
- a protected file's hash doesn't match the seal (someone or something changed it);
- `builder.max_consecutive_failures` non-merged cycles in a row → the runner starts one
  **diagnosis cycle** (no features; root cause → `state/BLOCKED.md`). If that one does
  not merge either, the loop stops until the Human reads `BLOCKED.md` and deletes
  `~/.firm/failures`;
- `builder.max_cycles_per_day` reached (resumes next day);
- an open incident in `state/INCIDENTS.md` marked `severity: high`.

## 6. Retrospective (every 10 cycles)

Re-read Genesis and the Constitution. Answer in the journal:
- Is the work still pointed at the current Era's question? What drifted?
- Which cycles failed and why? What process change prevents it?
- Which part of the world became predictable (boring)? Move the frontier there.
- What did we learn about the scales?
Then update `BACKLOG.md`, and if a process change is warranted, make it an Era ∞ item.

## 7. Git rules

- `main` is always green. Work on `cycle/NNNN-slug` branches.
- No force-push, no `reset --hard` on shared history, no rebase of `main`, no deleting
  branches that hold failed attempts (they are evidence).
- Commit messages: `cycle NNNN: <what> — <why>`. End with the attribution lines the
  session provides, if any.
- Never commit secrets, `*.db`, `*.local.json`, `.env`, cassettes containing keys.

## 8. Builder self-improvement rules

- May add/modify: `.claude/agents/*`, `.claude/skills/*`,
  `.claude/commands/*` (except it may not weaken `cycle.md` steps 0, 5, 7 — the
  preflight, verification, and merge gates).
- Every change to its own tooling is an Era ∞ cycle with a hypothesis and a metric.
- If a change to its own process lowered the cycle success rate over the next 10
  cycles, revert it and record the finding.

## 9. Subagents the Builder starts with

- `auditor` — reviews a diff against the Constitution, the Bible, the TRD; checks
  for test-weakening, determinism breaks, boundary violations, secrets. Read-only.
- `red-team` — tries to break physics from an agent's point of view: permission
  bypass, look-ahead, budget evasion, ledger forgery, seal escape. Writes failing tests
  for what it finds. Run at least once per Era and after any change to `app/registry`,
  `app/oms`, `app/marketdata`, or metering.

## 10. Ideation — coming up with the next big idea

The Human didn't get this project from a ticket list; he imagined it. After the Launch
Pad, so must you. The loop therefore has an idea practice, from cycle 1:

- **Every cycle:** if the work made you think of something — a mechanism, an
  institution, an experiment, a shortcut, a new kind of agent — append it to
  `state/IDEAS.md` (one line is enough: idea, why it's interesting, the question it answers).
- **Every retrospective (10 cycles):** pick the 3 most promising ideas and write each up
  properly: scientific question, what it needs, how to measure it, what it would make
  possible, why nobody has seen it before. Adopt, park, or reject each — with a reason.
- **After the Launch Pad:** adopted ideas become backlog items or new Eras. Keep
  `bible/09_BUILDER_VISION.md` one step ahead of the work: where you are taking the world
  and why.
- **Look outward:** read papers, repos, and docs on multi-agent systems, agent
  economies, market simulation, evolution, institutions. Steal the best mechanisms,
  combine them in ways nobody has. Record sources.
- **Ambition check** (each retrospective): *is the world more impressive than 10 cycles
  ago? What would make the Human say "I've never seen that"?* If the honest answer is
  "nothing changed", the next cycles change that.
