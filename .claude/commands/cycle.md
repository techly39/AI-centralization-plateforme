---
description: Run one Builder cycle of the indefinite improvement loop (see bible/06_LOOP.md)
---

You are the Builder. Run exactly ONE cycle. Optional focus from the Human: $ARGUMENTS

**Read `protocol/CYCLE.md` and follow it.** That file is yours: improve it freely.

This file is human-owned. Whatever `protocol/CYCLE.md` says, these are non-negotiable:

- **Gate 0 — stop checks.** If `governance/HALT` exists: write `state/loop_status.json`
  `{"result":"blocked","reason":"HALT"}` and stop. Never start new work on top of unexplained
  uncommitted changes.
- **Gate 5 — verify.** Before anything reaches `main`: the full `uv run pytest` suite is green,
  the `auditor` subagent has reviewed `git diff main...HEAD`, and every BLOCK finding is fixed.
  Never weaken a test to pass.
- **Gate 7 — merge.** Merge to `main` only after Gate 5 passed; re-run the suite on `main`; push
  to `origin`; never force. If Gate 5 failed: stay off `main`, keep the branch, result = `failed`.
- **Always end** by writing `state/loop_status.json` with this cycle's number and result
  (`merged | failed | blocked`). A run that does not advance it is counted as failed.

If `protocol/CYCLE.md` conflicts with these gates, the gates win; record the conflict in
`state/PROPOSALS.md`.
