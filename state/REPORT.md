# REPORT for the Human — rewritten when something matters

**2026-10-11 — Cycle 4: I've read all of the fund's engine. It's solid, but its sense of time
needs fixing before backtests.** All ~7 000 lines are mapped against the TRD (`state/SURVEY.md`
§2a). The good news: the core rules really are written once each (money, permissions, who sees
which message), and the database schema matches the code exactly. I found 9 problems and
measured each one. Three of them only show up once the clock can move, which is exactly what
backtesting needs:
- Rebuilding history after the clock goes backwards invents 10 phantom shares.
- Daily price bars would let an agent see the day's closing price at midday.
- The live price ignores the date it was asked for.

The reported yearly Sharpe ratio is also about 15% too low. These are all in the backlog, in the
order they need fixing. One needs your attention eventually: the TRD says only management may read
the clock, but every agent is told to use it. I'll settle that with a logged decision when I get
there. Nothing was changed in the fund this cycle. Next: survey the rest of the repo.

---

**2026-10-11 — Cycle 3: the fund starts for real, not just in tests.** A new check
(`uv run python scripts/smoke_run.py`) builds a fresh database, starts the API, and connects
an agent through MCP the way OpenClaw will. Every step passed. It runs in a throwaway folder,
so your `fund.db` (your August history) is never touched. Tool versions are in
`state/SURVEY.md`. Next: reading every file in the repo.

---

**2026-10-11 — Cycle 2: the leaderboard can no longer be broken.** The worst red-team hole is
fixed. One cost report can now claim at most 100M tokens, and the totals can't overflow even if
bad rows get in some other way (ADR-018). The red-team attacked the fix 12 ways and none worked.
It found one new minor bug (a huge pod number in a URL → server error; management-only). 9 minor
holes are still open and tracked. Next: back to the Survey (toolchain, repo, OpenClaw).

---

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
