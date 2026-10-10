# REPORT for the Human — rewritten when something matters

**2026-10-11 — Cycle 1: everything is in git.** Phase 2 and your Bible/harness install are
committed (the harness byte-for-byte) and pushed to origin. Things you should know:

1. **The "218 green" suite was flaky.** One OMS concurrency test failed about 1 run in 3 because
   of the test setup, not the fund. It's fixed. Digging in showed it never actually proved the OMS
   lock works (F-0001). That is written down honestly in the test.
2. **The red-team found 10 holes in Phase 2** (F-0002). Identity and permissions held completely.
   The worst hole: any agent can break the leaderboard forever with two absurd token reports. Each
   hole is now a test that will flip when fixed. These come next, before more survey work.
3. **Proposal P-0001** (`state/PROPOSALS.md`): the guard hook blocks harmless reads and commit
   messages because it matches the words `loop` and `governance` anywhere. A narrower match keeps
   every protection. Your call.

Still open from cycle 0: Q-0001 (firm LLM budget), Q-0002 (OpenRouter provisioning key).
