# REPORT for the Human — rewritten when something matters

**2026-10-11 — Cycle 6: the key is out of the files, but it still works.** I couldn't delete
`test_api.py`: in headless mode, `git rm` needs an approval nobody is there to give. So I removed
the key line instead. Your script now reads the key from the environment: `export
FUND_API_KEY=fk_...`, then run it as before. Without that variable it gets a 401. The key is
still in git history and still valid in `fund.db`. Revoking it is still your call (**Q-0003**).
To let me finish the cleanup (delete that file, untrack `.vscode/`), accept **P-0002** (allow
`git rm`) in `state/PROPOSALS.md`. P-0001 is also still open: the guard blocked two of my commit
messages this cycle because of words in the prose. The README and a design note now match the
code. Next: surveying OpenClaw (back it up, change nothing).

---

**2026-10-11 — Cycle 5: one thing needs you: a real API key is in the repo.** `test_api.py`
(your manual try-out script) contains the **management** key of your local `fund.db`, and it is
pushed to GitHub. The money is fake and the server only listens on your machine, so the risk is
small. But deleting the file won't revoke the key: git history keeps it, and I don't rewrite
history. I will remove the file next cycle (S-004). Rotating or revoking the key means writing to
your database, which I never do on my own, so that's your call (**Q-0003**). Also check whether
the GitHub repo is public. The rest of the repo survey is done: the 276 tests are hermetic and
cover every test the TRD asks for. Two honest caveats: the "Phase 2 milestone" was re-run by a
hand-written script, not by an agent, and the test price feed has the same look-ahead leak as the
real one.

---

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
