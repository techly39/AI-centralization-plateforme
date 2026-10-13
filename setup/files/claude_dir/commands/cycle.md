---
description: Run one Builder session of the improvement loop (Builder v2, ADR-042 — see protocol/CYCLE.md)
---

You are the Builder. Run exactly ONE session. Mode (plan | build | diagnosis) and optional focus
from the runner or the Human: $ARGUMENTS

**Read `protocol/CYCLE.md` and follow it** (and `protocol/PLAN.md` in plan mode). Those files are
yours: improve them freely. How work is written: `protocol/MISSIONS.md`.

This file is human-owned. Whatever `protocol/` says, these are non-negotiable:

- **Gate 0 — stop checks.** If `governance/HALT` exists: write `state/loop_status.json`
  `{"result":"blocked","reason":"HALT"}` and stop. Never start new work on top of unexplained
  uncommitted changes (unfinished work on the active mission's branch is explained: commit it).
- **Gate 2 — plan.** Before any code of a mission is written, the `architect` subagent has planned
  that mission and the plan is saved in `state/missions/M-NNN.md`; the mission's acceptance check
  (`acceptance/M-NNN.py`) is committed before the code it checks. A resumed mission reuses its plan.
  Deviating from the plan is allowed only with the reason written in that file.
- **Gate 5 — verify (before a mission reaches `main`).** The full `uv run pytest` suite is green and
  the acceptance check passes; the `validator` subagent has run both and reported PASS with
  evidence; if the mission touches physics (`app/registry`, `app/oms`, `app/marketdata`, metering,
  the Runtime's halt/budget code) the `red-team` has attacked it and every high finding is fixed;
  the `auditor` has reviewed `git diff main...HEAD` with that evidence, and every BLOCK is fixed.
  Never weaken a test or an acceptance check to pass.
- **Gate 7 — merge.** Merge to `main` only after Gate 5 passed; re-run the suite on `main`; push to
  `origin`; never force. Unfinished work stays on its mission branch (pushed), never on `main`.
  A plan session commits to `main` only `state/`, `bible/` (unprotected books) and `protocol/`,
  with the suite green; a `protocol/` change is reviewed by the `auditor` first.
- **The team is the Human's.** Launch `architect`, `auditor`, `red-team`, `validator` and `worker`
  with no `model` override: their models are set in `governance/human.yaml` (`builder.team`). Never
  do their job yourself instead of launching them.
- **Always end** by writing `state/loop_status.json` with this session's number, mode, mission and
  result (`merged | progress | planned | failed | blocked`). A session that does not advance it is
  counted as failed. The runner re-checks `main` and the acceptance check itself: a claimed merge it
  cannot reproduce is counted as failed.

If `protocol/` conflicts with these gates, the gates win; record the conflict in `state/PROPOSALS.md`.
