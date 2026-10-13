# CYCLE PROTOCOL — one Builder session (Builder-owned)

`.claude/commands/cycle.md` (human-owned) holds the gates; this file is how you meet them. If they
conflict, the gates win — record the conflict in `state/PROPOSALS.md`. Architecture: ADR-042.

A **session** (still numbered as a cycle) has one mode, given by the runner in `$ARGUMENTS`:
- `build` — move the active mission forward; finish it if you can. This file.
- `plan` — groom the future: `protocol/PLAN.md`.
- `diagnosis` — the last sessions failed: find the root cause, write `state/BLOCKED.md`, fix it only
  if the fix is small and safe. No mission work.
No mode given (interactive `/cycle`) → `build` if a mission is `active` or `ready`, else `plan`.

**The team** (models in `governance/human.yaml` → `builder.team`; launch with no `model` override):
`architect` plans a mission once · `validator` runs the checks and reports evidence · `red-team`
attacks physics once per mission that touches it · `auditor` reviews the mission once before merge ·
`worker` takes a well-specified side task (only if `builder.parallel_workers` > 0, each in its own
worktree) · any other subagent is a helper. Give each a precise brief; never re-pay for discovery.

**Context hygiene.** Everything you read is paid again on every later turn. Never read whole:
`state/JOURNAL.md`, `bible/07_DECISIONS.md`, `state/IDEAS.md`, `state/BACKLOG.md`, `state/SURVEY.md`
— `grep`/`tail`. Tests: `uv run pytest -p no:warnings -o addopts="" -q 2>&1 | tail -15`. Wide
searches → a helper subagent; take back only its conclusion.

## 0. Gate 0 — stop checks and resume
- `governance/HALT` exists → write `state/loop_status.json` `{"cycle": N, "result": "blocked",
  "reason": "HALT"}` and stop.
- Cycle number N = `state/loop_status.json` `cycle` + 1.
- Dirty tree: on the active mission's branch it is the previous session's unfinished work (cut by a
  limit or the hang guard) — read it, commit it as `M-NNN: recovered work in progress`, continue.
  Anywhere else: investigate; commit legitimate leftover state, otherwise end `blocked`.

## 1. Orient (cheap)
Read `state/PROGRESS.md` (the last session's handoff), the active or first `ready` mission in
`state/missions.json`, its plan `state/missions/M-NNN.md` if it exists, and `git log --oneline -15`.
`state/STATE.md` only if PROGRESS points you there. That is all: the mission plan holds the rest.

## 2. Start a mission (only when none is `active`)
1. Take the first `ready` mission whose `depends_on` are `done`. Set it `active`, create
   `mission/M-NNN-<slug>` from `main`.
2. **Gate 2 — plan.** Launch the `architect` with the mission entry, the standard
   (`protocol/MISSIONS.md`) and anything PROGRESS says. Save its plan verbatim to
   `state/missions/M-NNN.md`. Commit `M-NNN: plan`.
3. **Acceptance first.** Write `acceptance/M-NNN.py` from the plan, run it, see it **fail** for the
   right reason, commit `M-NNN: acceptance (fails before the work)`. Push the branch.
If the architect says the mission is not ready (too big, wrong, blocked), fix `missions.json` as it
advises (split by capability, reorder, drop with reason), commit on `main`, and end `planned`.

## 3. Build
- Work through the plan's milestones in order. Each milestone ends with the suite green and a commit
  `M-NNN: <what> — <why>`; push the branch after each one. Tests first where the plan names them.
- Follow the TRD inside `app/`; never edit a test just to make it pass (if a test is wrong, say why
  in the commit). A new law that breaks old tests: each break is a finding for the ADR, not a test
  to "fix".
- Decide open questions with the prime rule; real decisions get an ADR in `bible/07_DECISIONS.md`.
- Deviating from the plan is allowed; write the deviation and its reason in `state/missions/M-NNN.md`.
- Keep `state/PROGRESS.md` true at every milestone (§5): a session can be cut at any moment.

## 4. Finish a mission (Gate 5, then Gate 7)
When the acceptance check passes and the plan's milestones are done:
1. `uv run python scripts/smoke_run.py` exits 0 (if the mission touched anything beyond docs/state).
2. Launch the `validator` (brief: mission id, acceptance path, branch). It runs the acceptance check,
   the full suite and the demo line, and returns PASS/FAIL with evidence. FAIL → fix, re-validate.
3. If the mission touched physics (`app/registry`, `app/oms`, `app/marketdata`, metering, Runtime
   halt/budget code) or the plan says `RED-TEAM: yes`: launch the `red-team` with the diff range and
   the new laws. Commit its test file **as written, before any fix**. Triage by
   `protocol/MISSIONS.md` §6. The validator and red-team may run in parallel.
4. Launch the `auditor` on `git diff main...HEAD` with: the plan, the validator's evidence, the
   red-team result, every deviation, and the claim list (every "never / all / only / covers"
   sentence the diff adds, with the counter-example that tests it). Fix every BLOCK. A re-audit is
   scoped to the fix commits.
5. Merge: `git switch main && git merge --no-ff mission/M-NNN-<slug>`, run the suite on `main`,
   set the mission `done`, then record (§6) and push: `git push origin main mission/M-NNN-<slug>`.
6. If time and budget remain, end the session anyway: the runner verifies the merge out of band and
   chooses the next session's mode. Result `merged`.

## 5. End a session without finishing (`progress`)
Commit everything on the mission branch and push it. Rewrite `state/PROGRESS.md`:

```
Cycle: NNNN · Mission: M-NNN (<title>) · Branch: mission/M-NNN-<slug>
Done so far: <milestones done, one line each>
Next: <the exact next step>
Watch out: <anything that cost you time; dead ends>
Acceptance: <passes | fails: why>
```
≤ 40 lines. Result `progress`.

## 6. Record (every session, small)
- `state/JOURNAL.md`: `## Cycle NNNN — <mode> — <mission or plan> (<ISO date>)` then 3–8 lines:
  what you did, the result, what you learned, next. (Constitution Art. 7.2.)
- `state/PROGRESS.md` as in §5 (also after a merge: say what is next).
- On a merged mission only: `state/SHOWCASE.md` (one entry: what's new + the demo line), `state/STATE.md`
  (≤ 120 lines, a map not a history), `state/REPORT.md` if the Human must know or decide something.
- An idea → one line in `state/IDEAS.md`. Never hand-write metrics: the runner measures
  (`$FIRM_HOME/metrics.jsonl`).
- Last: `state/loop_status.json` = `{"cycle": N, "mode": "build", "mission": "M-NNN",
  "result": "merged|progress|planned|failed|blocked", "branch": "...", "ts": "<ISO>"}`. Commit state on
  the branch you are on (`main` after a merge).

End with three lines: what you did, the result, what's next.

## Headless notes
Bash runs in the OS sandbox (repo + temp writable, network: GitHub and PyPI only, localhost
allowed); protected paths are write-denied by the OS. `git push origin …` runs outside the sandbox
and works only as a bare command (no `cd … &&`). Prefer `uv run --project "<repo>" …` over `cd`.
