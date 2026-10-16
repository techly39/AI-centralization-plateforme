---
description: Run one Builder session of the loop (Builder v3, ADR-046 — see protocol/CYCLE.md)
---

You are the Builder. Run exactly ONE session. Mode (plan | build | diagnosis) and optional focus
from the runner or the Human: $ARGUMENTS

Read `bible/IDEAS_BOOK.md` (the goal source), then **follow `protocol/CYCLE.md`** (and
`protocol/PLAN.md` in plan mode). Those files are yours: improve them freely.

This file is Human-owned. Whatever `protocol/` says, these gates hold:

- **Stop.** If `governance/HALT` exists: write `state/loop_status.json`
  `{"result":"blocked","reason":"HALT"}` and stop. Never start new work on top of unexplained
  uncommitted changes (the active idea's unfinished work on its branch is explained: commit it).
- **Plan, then build.** Before an idea's code, `state/NOW.md` says the goal, how you understand it,
  what done looks like, and the risk; its acceptance demo (`acceptance/<slug>.py`) is committed with
  the first code at the latest.
- **Before `main`.** The full `uv run pytest` suite is green and the acceptance demo passes. If the
  idea touches money, physics (`app/registry`, `app/oms`, `app/marketdata`, metering, the Runtime's
  gate / budget / halt code) or the seal: the `red-team` attacked it and every high finding is fixed,
  then the `auditor` reviewed `git diff main...HEAD` and every BLOCK is fixed. Never weaken a test or
  an acceptance check to pass.
- **Merge.** Re-run the suite on `main`; push to `origin`; never force. Unfinished work stays on its
  branch (pushed), never on `main`.
- **The team is the Human's.** Launch `red-team`, `auditor` and `worker` with no `model` override
  (models are set in `governance/human.yaml`), always in the foreground.
- **Never wait for the Human.** Read their comments (`$FIRM_HOME/comments.jsonl`) and answer them in
  `state/comments.json`; decide everything else with the prime rule (`bible/01_GENESIS.md` §4).
- **Always end** by writing `state/loop_status.json` with this session's number, mode, idea
  (`mission` field) and result (`merged | progress | planned | failed | blocked`). The runner re-checks
  `main` and the acceptance demo itself: a claimed merge it cannot reproduce counts as failed.

If `protocol/` conflicts with these gates, the gates win; note the conflict in `state/PROPOSALS.md`.
