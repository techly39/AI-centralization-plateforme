# REPORT for the Human — rewritten when something matters

**2026-10-11 — Cycle 17: the whole fund now agrees on what time it is.** Before this change,
the clock agents read, the prices they were shown and the time stamped on their trades could
come from three different moments (after the clock was moved backward). Now they all come from
one: the fund's own record of time. A test now flags any new code that reads the clock any other
way. The attack review found 6 problems, and 5 are fixed. The most serious one: while a backtest
moved forward a day, agents could already see the next day's prices before the move was saved,
and if saving failed, the day was undone after they had seen it. Now the move is saved first and
only then shown. One minor problem is still open (B-036). It needs two programs writing to the
same fund database at the same moment, which normal use never does. **Your P-0003 change is
committed** (the `protocol/` folder and the edits to CLAUDE.md, 06_LOOP and PROPOSALS).
`setup/` is untouched and waiting for you to run `bash setup/update.sh`. Until you do, one
directory test fails on this machine only, because `setup/` is not in git.

---

**2026-10-11 — Cycle 16: backtests are now honest about time.** A backtest replaying March 2024
can no longer see prices from after its simulated "now". Every market-data source goes through
one checkpoint that refuses "future" data, and no data source can skip that checkpoint. Today's
closing price only becomes visible once the day has actually ended. New backtests record
`look_ahead_guard: true`. The attack review found five ways around the first version, and all five
are fixed. The worst was an arbitrage: after the market closed, an agent could already see
today's closing price in the hourly price history, but its trades still went through at
yesterday's price. That would have been a guaranteed 39% profit in the test. Trades now use
the newest price the agent can already see. One design rule for later is now on record: agents'
own code must never run inside the fund's engine. Nothing needs your action. P-0003 is still open.

---

**2026-10-11 — Cycle 15: the fund can now run in simulated past time (backtest), safely
separated from the live fund.** A backtest is its own database file: you create it empty, give
it a start date (for example 2 January 2024), and its clock then moves only when management calls
"advance" (by up to a year at a time, never past today). Each step is recorded in the permanent
history, and limit orders are checked at every step. Live and backtest records can never mix,
because they live in different files. The attack review found three timing issues and all are
fixed. The worst was that an order could be priced at yesterday's market but recorded as
happening today. **Important:** backtests are not yet trustworthy. The market data does not yet
refuse "future" prices, so a 2024 backtest would currently trade at today's prices. Every
backtest records this (`look_ahead_guard: false`), and that guard is my next job. Nothing needs
your action. P-0003 is still open.

---

**2026-10-11 — Cycle 14: every agent can now read the fund's clock.** Before, only management
could see what time the fund thinks it is, even though the agents' instructions told every agent
to check it. That matters once we run backtests: an agent replaying 2019 must know it is "2019",
or it will reason from today's real date, which is exactly the hindsight a backtest must deny it.
Reading the clock is now open to all agents. Changing the clock stays closed to every agent. The
attack review found one small issue: after the computer's clock stepped backwards, the clock
an agent read and the time stamped on its next order could disagree, and the gap hinted at
another desk's activity. The clock now reports the same time the next record entry will carry.
**One small request (P-0003 in `state/PROPOSALS.md`):** I can't edit my own cycle instructions
(`.claude/commands/cycle.md`) in unattended mode. Either allow that folder in the project's
Claude settings, or paste the four lines in P-0003 into the file yourself. Nothing else needs
your action.

---

**2026-10-11 — Cycle 13: the fund's history now replays exactly as it happened.** The fund
keeps one permanent record of every event, and its state can be rebuilt from that record at any
time. Before this change, that rebuild sorted events by their timestamps. If the computer's clock
ever stepped backwards, the rebuild could disagree with what actually happened, for example by
inventing shares. Now the record's time only moves forward, and every rebuild follows the order
in which events actually happened. A rebuilt history that is impossible now raises a loud error
instead of being quietly "corrected". Your existing `fund.db` (95 events) still rebuilds
unchanged; I checked a read-only view of it. The attack review found two small issues, and both are
fixed: an agent could sell a tiny amount (1e-9) of a stock it never owned and get cash for it, and
the order list could show fill times that disagreed with the record. One thing to know: if the
machine's clock ever jumps far into the future, the record's time stays there, because the record
is permanent. Agents cannot cause that; only the operating system clock or an operator script
can. A previous session was interrupted after building this. This session checked and finished it
rather than starting over. Nothing needs your action.

---

**2026-10-11 — Cycle 12: the fund's record can no longer hold numbers that break it.** Agents
could previously send "infinity" or "not-a-number" as a cost or a price, and the fund stored it.
Now every number has a sensible ceiling, and the permanent record refuses anything that a standard
tool couldn't read back. The attack review found something worse along the way: one analyst could
send a single deeply nested message to a rival desk, or to management. After that, every attempt
by that reader to open their inbox (or, for management, the event log) failed. That is now
blocked, and so are five related holes. Two small issues remain on the list. Very small trades
currently pay no fee. A broken price feed would crash orders instead of rejecting them cleanly.
No agent can trigger the second one. Nothing needs your action.

---

**2026-10-11 — Cycle 11: your stop file now works inside the fund itself.** Thank you for
answering P-0001, P-0002, Q-0003 and Q-0004, and for fixing the runner. Your changes are committed
(66af48b). From now on, when `governance/HALT` exists, the fund refuses every action from every
agent, management included, and logs each attempt. Agents can still look at prices and their
books, and they can ask "are we halted?". Delete the file and everything resumes; no restart is
needed. The reviewers made it stronger. The file's location can no longer be changed through a
setting, so nothing can point the fund away from your file. Also, a refused request can no longer
carry an agent's hidden message into the record. Still open for you: Q-0001 (budget) and Q-0002
(provisioning key). Neither blocks work: everything up to the first live run uses a fake AI
provider.

---

**2026-10-11 — Cycle 10: first Era I work, plus my 10-cycle review.** A new test now keeps every
AI SDK out of the fund's engine. It checks two ways: it reads every import in the code, and it
also loads the engine and checks what actually got loaded. While doing this I found that the MCP
doorway agents use was loading the whole engine, including the database, just to read one number.
That number now lives in its own small file, so the doorway talks to the fund only over HTTP.

The review, honestly: all 10 cycles merged. But in 5 of them the reviewer caught me claiming my
checks covered more than they really did. I'm adding a step that hunts for that before review
(X-006). The world is more *truthful* than 10 cycles ago, but not yet more *capable*, since no
agent has acted. The next 10 cycles aim to have one pod trading in simulated time against a fake
AI provider. That needs no budget from you. Your open items are unchanged: Q-0001…Q-0004, P-0001,
P-0002.

---

**2026-10-11 — Cycle 9: the Survey is finished. Era I (The Desk) starts next cycle.** I checked
all five Survey exit criteria against the evidence itself, not my notes. Each one, with its proof,
is in `state/SURVEY.md` §10. One criterion is met only by explanation: `test_api.py` and
`.vscode/` are still tracked, because removing them needs **P-0002**, which only you can
approve. They stay on the list. I did not hold the Era open for them.

The first Era I work protects the boundaries before any agent can run:
1. A test that keeps any AI SDK out of the physics.
2. `governance/HALT` stops every agent action inside the App itself.
3. Every known physics hole gets fixed (or accepted, with a written reason) before an agent wakes.

Then comes the clock work. Your open items haven't changed: Q-0001…Q-0004, P-0001, P-0002.

---

**2026-10-11 — Cycle 8: the Bible now matches what the Survey measured.** I didn't rewrite your
sentences. I added dated corrections next to them, each pointing to its evidence (ADR-020). Changes:
- the test counts;
- a "works, with known holes" list in 03;
- the fact that no model has traded through the App yet;
- the OpenClaw rules in 08: check the installed schema before trusting the docs, run `doctor`
  only after a backup and only on the fund's profile, and create backups private.

Your Constitution and Genesis had nothing that needed a proposal. The auditor caught one error I
made in cycle 7: one setting (`tools.profile`) can be set per agent after all. It's now corrected
everywhere, and the decision to give the fund its own OpenClaw profile still stands.
Q-0003 and Q-0004 are still open. Next: close the Survey, then start Era I with the clock.

---

**2026-10-11 — Cycle 7: I've surveyed your OpenClaw and changed nothing in it. Two things need
you (Q-0004).**
1. `~/.openclaw/workspace/OPENCLAW_XAI_KEY.txt` holds what looks like an xAI API key, in a plain
   file inside `main`'s workspace. Your OCT agents' workspaces sit inside that one, so anything
   with file or shell access can read it. I didn't print it or touch it. I recommend moving or
   deleting it, and rotating the key if it was ever exposed.
2. I backed up all of `~/.openclaw` first. The backup came out readable by your group, and
   headless mode wouldn't let me tighten it. Please run: `chmod 700 ~/firm-openclaw-backups &&
   chmod 600 ~/firm-openclaw-backups/*.tar.gz`.

What I learned:
- **The OpenClaw docs online describe a newer version than yours (2026.5.12).** The newer
  version's defaults are looser: it lets agents read other agents' sessions by default.
- **Some safety settings are global in your version**, such as web search and MCP servers, and
  your bots need them as they are.
- So the fund's agents will live in their own OpenClaw profile (ADR-019). Your config and bots
  stay untouched.
- **Likely cause of "chat restricted to the central pod":** cross-agent spawning needs
  `subagents.allowAgents`, and nothing sets it.

Next: correct the Bible and close the Survey.

---

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
