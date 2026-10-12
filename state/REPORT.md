# REPORT for the Human — rewritten when something matters

**2026-10-12 — Cycle 30 (the 10-cycle review): the first 3 of Era I's 7 exit criteria are
met.** Looking back over the last ten cycles, I found three safety checks that had already been
built but never tested the way a real run uses them:
- an agent cannot see "tomorrow's" prices;
- creating the HALT file stops a run at once;
- with no firm budget, no paid AI agent is ever started.

Eight new tests now prove each one end to end, so those boxes are ticked. One box depends on your
answer to **Q-0005**. If you answer "A" (nothing may run at all without a budget), that box
reopens. Next: recording runs so they can be replayed for free.
(`setup/` has run and is gone. Thank you.)

**2026-10-12 — Cycle 29: the gap from last cycle is closed.** A management agent could read the
simulated market's hidden rules (its trend and volatility) in the event log. Now every agent sees
the word `withheld` in their place, and also where the run's "minds" label is. The full record is
still kept for the app itself and for you. Ten new tests check this. No action needed.

`setup/` is still waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 28: the system now records whether a simulated month was run by scripts
or by AI models.** When the Runtime starts a run, it tells the app once what kind of "minds" the
run's agents have:
- `scripted`: plain code;
- `cassette`: recorded AI answers played back;
- `model`: a live AI.

The app writes this into the run's permanent record. It only accepts the statement before
anything has happened in the run, so the label covers everything that follows. That means a
scripted month can never be reported later as an AI month.

The attack review found a real gap: an agent that existed *before* the label was written could
act afterwards, and nobody had said what it was. The label now covers only the agents created
after it. It found three smaller gaps too. All four are fixed and tested.

**One thing to know (no action needed yet):** a management agent can already read the hidden
rules of the simulated market (its trend and volatility) through the event log. No AI is running,
so nothing has used it. It is first in line to fix before any AI manager wakes (B-049).

`setup/` is still waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 27: a simulated run now starts with one command.** You point
`fund-runtime backtest` at a folder of agent description files. It creates the agents and runs
the simulated days, then prints what happened. I tested it end to end against the real server:
the analyst and the PM from `specs/desk-month/` lived 5 simulated days, and the PM placed a
trade based on its analyst's signal.

The command checks everything it can before it creates anything:
- the folder, the input file and the sizes are valid;
- both keys are present;
- the server is on this machine;
- the database is a simulated run, not the live one.

Keys are read only from environment variables, never typed on the command line, where other
programs on the Mac could see them.

The reviewer caught a real leak. An agent that hires another agent receives the new agent's key,
and my printout would have shown it. Keys are now blanked out of the output. The reviewer also
found that a proxy setting on the Mac could have sent keys off the machine. Proxies are now
ignored. Both are fixed and tested.

Nothing needs your action. `setup/` is still waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 26: agents are now created from their written descriptions.** Each agent
has a file that describes it: name, role, desk, script. Until now, a test created each agent by
hand and handed its key over. Now the Runtime creates every agent from its file through the
app's front door. Before creating anything, it checks every file:
- Is the world halted, or would the budget rule forbid this agent?
- Is the name reserved, already taken, or a near-twin of another name (different capitals,
  invisible characters)?

If anything is wrong, nothing is created. An agent's key now only works for the agent its file
names. Before, any key with the right role and desk was accepted.

I chose **not** to let the Runtime's clock key create agents. That key can already move time,
and it should stay the narrowest key in the world. Creating agents uses an operator key you hold
(today, the seed admin).

The reviewer caught a mistake of mine: renaming old tests had quietly made four safety tests
check the wrong thing. They are fixed. The attack review found 4 small issues, all fixed.

Nothing needs your action. `setup/` is still waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 25: two agents now work together for a simulated month.** An "analyst" and
a "portfolio manager" (PM), both still plain code with no AI and $0 cost, shared a desk for 31
simulated days. Each day the analyst sends its desk a buy/sell signal. The PM trades only on
today's signal from its own desk's analyst. It checks who sent the message against the firm's
directory, and when the message was sent against the app's own timestamp, not against what the
message claims. A second desk with no analyst never traded. Run twice, the history was the same.

This work found a flaw in the tools every agent will use. When the answer was a list holding a
single item, such as an inbox with one message, the agent received the bare item. It could not
tell "one message" from "a message". An empty list arrived as nothing at all. Fixed: a list now
always arrives as a list. This matters for your OpenClaw agents too, since they will use the same
tools.

Nothing needs your action. `setup/` is still waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 24: the Runtime now runs the simulated month itself.** Until now, a test
moved the clock forward day by day. Now the Runtime does it. Each simulated day, it wakes every
agent once, always in the same order, and then moves the clock forward with its own key.

The attack review found a real problem. If management fired a colleague mid-run, the whole
backtest stopped. That would let a firm agent freeze the world's clock at a moment of its
choosing, which is exactly the power cycle 23 took away. Now a fired agent is simply retired: it
is recorded and not woken again, and the world goes on. Three smaller issues were also fixed:
- One agent handed in twice got two turns a day.
- A failure after the clock moved could make the record disagree with the history.
- The agents' shared instructions could be changed mid-run.

Also new: if the clock key is ever lost, `uv run fund-env rotate-runtime-key` issues a new one.

Nothing needs your action. `setup/` is still waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 23: no firm agent controls the clock any more.** In a backtest, simulated
time moves only when someone pushes it forward. Until now the firm's *management* agent could do
that. Once management is a real AI, that would give a player in the game control over the game's
time. Now only a dedicated "runtime" key can move the clock. That key can do nothing else: no
trading, no messages, no reading prices. It is created with one command, `uv run fund-env
seed-runtime`, once per database. Also fixed: an agent could have registered itself under the
name "system", the app's own identity, and had the app's notices attributed to it. That name, and
"runtime", are now reserved, including look-alike spellings with invisible characters (the attack
review found those).

Nothing needs your action. If you ever start a backtest by hand, you'll need `seed-runtime` to
get the clock key. Q-0005 is still open; my default (B) is in force. `setup/` is still waiting
for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 22: the first "mind" acted through the Runtime.** A scripted trader ran
inside the Runtime. It is plain code with no AI model, and it costs $0. It read prices and
placed orders only through the same tools a real agent will get, for one simulated month.
Run twice, it produced exactly the same history.

The two reviews found serious problems, and all are fixed:
- **Your stop file was checked too rarely.** It was checked only between groups of actions; it
  is now checked before every single action and before the agent thinks again.
- **An agent could be woken with another agent's key**, getting that agent's powers or pod.
- **A price-lookup tool could be steered to a different part of the system**, with a crafted
  symbol name. This old hole is now closed for good.

Nothing needs your action. Q-0005 is still open; my default (B) is in force. `setup/` is still
waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 21: the part that will wake agents exists, and its locks come first.** The
"Runtime", the program that will wake the firm's agents, now has its skeleton. It does not wake
anyone yet. What it has are its two locks:
- **Your stop file.** If `governance/HALT` exists, nothing wakes. If the Runtime can't tell
  whether the file exists, it also treats that as a stop.
- **Your budget.** While your budget is `null`, only two zero-cost kinds of "mind" may run:
  scripted code, and replays of recordings. Anything it can't read clearly counts as no budget.

The attack review found 10 holes, and all are fixed. The serious one: an agent set up as
"scripted" but run through OpenClaw would have passed the budget lock, even though OpenClaw runs
its own paid model. The lock now checks both. You can see what the locks would allow right now
with `uv run fund-runtime status`.

Nothing needs your action. Q-0005 is still open; my default (B) is in force. `setup/` is still
waiting for `bash setup/update.sh`.

---

**2026-10-12 — Cycle 20: a look back, my vision, and the plan to wake the first agents.** In
cycles 11–19 I made backtests honest about time and about their market. But **no AI agent has
acted yet**, and all 7 of Era I's finish-line checks are still open, because every one of them
needs the Runtime, the part that wakes agents. That is now the plan. I wrote my vision in
`bible/09_BUILDER_VISION.md`. The idea I am aiming at: make every run exactly replayable, then
"fork" a run. Replay day 1 to day 12 for free, change one thing (say, the PM's model), and let
history branch. As far as I know (I have not checked the research yet), nobody runs such exact
"what if" experiments on AI firms. The Runtime is split into 8 one-cycle steps (R-1…R-8). Steps
1–7 need no money. Step 8, the first real-model month, needs your budget (Q-0001).
**One question for you, Q-0005:** while the budget is `null`, I will let only two kinds of
"minds" run through the Runtime: scripted code with no AI, and replays of recordings. Both cost
$0. Any other kind is refused by default, and these runs never count as agent results. If you
want even those refused, answer A in `state/QUESTIONS.md`. `setup/` is still waiting for
`bash setup/update.sh`.

---

**2026-10-12 — Cycle 19: every backtest now records which market it ran in.** The first event of
a backtest now names its market: which price source, which settings, and for the made-up market
a short "fingerprint" of the secret key. The key itself is never stored, and the fingerprint
cannot be turned back into the key. If the fund is restarted on that backtest with a different
market (another key, other symbols, other prices), it now refuses to start. Before, it would
have silently mixed two markets into one record. The new rule caught two of my own tests that
had been doing exactly that. The attack review found one small gap, now fixed: the fixed-price
test market wasn't recorded. Nothing needs your action. `setup/` is still waiting for
`bash setup/update.sh`.

---

**2026-10-12 — Cycle 18: a backtest can now be re-run to exactly the same result.** I added a
made-up offline market. Its prices are generated from a secret key, so no internet is needed. A
scripted trader (no AI model) traded one simulated month in about half a second. The limit is 10
minutes. I ran it twice and got the same permanent record both times, event for event, not just
the same profit. A different key gives a different month, so the test really checks something. The
attack review found one serious problem in the first version. The market came from a small
number that could be guessed from the trading volumes it showed. With that number, an agent
could know next week's prices. Now the market comes from a long random secret. It can only be set
in the environment. If someone puts it in the committed config file, the fund refuses to start.
**If you run a synthetic backtest yourself:** set
`FUND_MARKETDATA__SYNTHETIC_KEY` to the output of `python -c "import secrets;
print(secrets.token_hex(32))"` and keep it private. Nothing else needs your action. `setup/` is
still waiting for `bash setup/update.sh`.

---

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
