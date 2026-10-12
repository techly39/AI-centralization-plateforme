# CYCLE PROTOCOL — Builder-owned

This is **your** protocol. Improve it whenever a better process would raise your success rate
(an Era ∞ cycle: hypothesis + metric). `.claude/commands/cycle.md` only points here and holds
the three human-owned gates (0 stop checks, 5 verify, 7 merge) plus the `loop_status.json` rule.
If this file ever conflicts with those gates, the gates win — record the conflict in
`state/PROPOSALS.md`.


**0. Gate — stop checks.** If `governance/HALT` exists: write `state/loop_status.json`
`{"result":"blocked","reason":"HALT"}` and stop. If `git status --porcelain` is not empty,
investigate: commit legitimate leftover state, otherwise record and stop as `blocked`.
**Resume, don't restart (X-007, P-0003):** run `git branch --no-merged main`. A `cycle/NNNN-*`
branch whose number is greater than `loop_status.cycle` is an interrupted cycle: take that number,
check its journal entry (write the hypothesis if missing, saying it was written late), and resume
it at step 5 — no new unit until it is merged, failed, or recorded as abandoned with its reason.

**1. Orient.** Read `state/STATE.md`, last 3 entries of `state/JOURNAL.md`, top of
`state/BACKLOG.md`, `state/QUESTIONS.md` (look for human answers), and the current Era in
`bible/05_ERAS.md`. Cycle number = last cycle in `state/loop_status.json` + 1.
If the cycle number is a multiple of 10: re-read `bible/00_CONSTITUTION.md` and
`bible/01_GENESIS.md` and do the retrospective (`bible/06_LOOP.md` §6) as part of this cycle.

**2. Choose ONE unit of work** using the priority list in `bible/06_LOOP.md` §2.
While Era ½ (Survey) is open, the unit is survey/cleanup work only — no features.
After the Launch Pad, choose from your own roadmap (`bible/09_BUILDER_VISION.md`).
Before touching OpenClaw, read `bible/08_OPENCLAW.md`.
If it is too big for one session, split it in `BACKLOG.md` and take the first slice.
Size check (X-008): a slice that changes physics will meet a red-team pass and its fixes in the
same cycle — leave room for them, or split before building.

**3. Hypothesis.** Append to `state/JOURNAL.md`:
`## Cycle NNNN — <title> (<ISO date>)` / `Era:` / `Exit criterion served:` / `Hypothesis:`.

**4. Build** on `git switch -c cycle/NNNN-<slug>`. Tests first where possible.
Small commits: `cycle NNNN: <what> — <why>`. Follow the TRD inside `app/`.
Commit the build before step 5 begins (X-009, cycle 22): an interrupted cycle then resumes from a
commit, not from an uncommitted tree.
Answer any open question with the prime rule; log it in `bible/07_DECISIONS.md`
(and `state/QUESTIONS.md` if the Human should see it).

**5. Gate — verify.**
- `uv run pytest` → all green. Never edit a test just to make it pass; if a test is
  wrong, say why in the commit message.
- Boundary + determinism tests pass (once they exist).
- Run check (X-004): if the diff touches anything but docs/state, `uv run python
  scripts/smoke_run.py` exits 0 — tests green is not "the fund starts".
- Claim check (X-006), before the auditor: list every "covers / finds / never / all / only /
  0 found" sentence the diff adds (code, ADR, journal) and plant a counter-example for each, or
  narrow the sentence. Ask: what in this diff can an unprotected file or env var change? Is
  every check inside the lock that protects the write it guards? Which old tests did a new law
  break — and is each one a finding (log it in the ADR), not a test to "fix"?
- Launch the `auditor` subagent on `git diff main...HEAD`. Fix every `BLOCK` finding.
  If the change touches `app/registry`, `app/oms`, `app/marketdata`, metering or the
  Runtime's halt/budget code, also launch `red-team`.
- Commit the red-team's test file as it wrote it, before any fix (X-010, re-audit c28 NOTE 5).
  Then every changed hole or guard is a diff in history, not just a sentence in a commit
  message.

**6. Experiment** (only if this unit is an experiment): spec in
`experiments/<id>/spec.yaml`, results in `experiments/<id>/`, conclusion appended to
`state/FINDINGS.md` with evidence (run_id, event ids, numbers). Respect every cap.

**7. Gate — merge.** Only if step 5 passed: `git switch main && git merge --no-ff
cycle/NNNN-<slug>`, run `uv run pytest` again on `main`, then `git push origin main
cycle/NNNN-<slug>`. Never force. If step 5 failed: stay off `main`, keep the branch,
result = `failed`.

**8. Record** (on `main`, one commit `cycle NNNN: state`):
- finish the journal entry: `Work:` / `Result:` / `Learned:` / `Next:`;
- rewrite `state/STATE.md` (current Era, cycle, what's true now, next 3 moves);
- reorder `state/BACKLOG.md`, add discoveries;
- append any idea this cycle gave you to `state/IDEAS.md` (retrospective cycles: write up the top 3);
- update `state/REPORT.md` if the Human should know something;
- append a row to `state/METRICS.md`;
- write `state/loop_status.json`:
  `{"cycle": N, "result": "merged|failed|blocked", "branch": "...", "ts": "<ISO>"}`.

End with a 3-line summary: what you did, the result, what's next.
