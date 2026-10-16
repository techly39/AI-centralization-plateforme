# Rework brief — the AI firm builder (2026-10-16)

## 1. The project, at its full scale
- A scientific experiment, not a product: how far can a stack of AI systems go at building and running a human-like firm, then a society, then a civilisation, inside a sealed simulated world with fake money?
- Inspiration: the paperclip maximiser, made realistic. It is relentless, but the world is sealed, the budgets are hard, and there is an off switch.
- Three layers:
  - The Human: has the ideas and checks in now and then.
  - The Builders: Claude Code in an endless loop on the Human's Mac and subscription, with one standing task: push the limit.
  - The Inhabitants: AI agents living in the app (OpenClaw first) that run the firm.
- Ultimate objective of the firm: make a huge amount of (fake) money. Good organisation and emergent behaviour are the means.
- The real score is live paper trading. Backtests and training phases exist to test agents and strategies.
- The firm governs itself like a civilisation: it hires, fires, creates pods and departments, and chooses what to trade. The Human does not decide these.
- Horizon, with nobody touching it for weeks:
  - AI agents run a firm on simulated capital, in a world built from real market history and synthetic scenarios.
  - PMs pitch strategies, prove them through validation gates, build their own teams, spawn agents and pay for them from their budget.
  - An allocation algorithm moves capital toward what works. A risk engine cuts what bleeds. Failing pods die and their lessons are kept.
  - Every month is a generation: capital resets, the fittest designs reproduce with variation, the firm evolves.
  - Agents talk, cooperate, compete, keep secrets, form politics, and write the firm's internal rules: a society.
  - Later: several firms, a regulator, auditors, an exchange: a civilisation.
  - A lab notebook records everything surprising that emerged, with evidence.
- Cheating or exploits by agents inside the sim are allowed and are data. Breaking the physics is a builder bug. Reaching outside the sim is an incident.
- The Builders' character: "the user on steroids". They want the system to work and be efficient, and they change whatever needs changing.
- Once the Human's ideas are built, the Builders invent their own (new institutions, new experiments, new Eras) and keep going.

## 2. The core problem to fix
- 40 cycles in, no AI agent has ever traded. The loop builds slowly, tests everything, and builds verification tools instead of the firm.
- Numbers since Oct 1:
  - About 9,900 lines of product code, 22,000 lines of tests, and 10,500 lines of docs and state files.
  - About 2,150 tests. The full suite takes 96 s and is re-run many times per session.
  - 46 ADRs: the decision log is 1,732 lines and the journal is 1,500 lines.
  - Each mission costs about 3 sessions and $13 or more.
- Last mission (M-002): a tool proving that a recording of scripted bots replays identically. Valid, but it is an instrument around a world that has no inhabitants yet.
- Session 39: $2.11, its only output a plan from the architect (a planning subagent), which was killed when the session ended.
- Session 40: 190 turns. 16 commands were refused by the guard or sandbox, and the session ended on the usage limit.
- The Human is a non-coder. They want to see the firm come alive, not manage a process.

## 3. Root causes, all in how the builder environment was set up
- **Wrong source of goals.**
  - The Builder works toward `bible/05_ERAS.md` exit criteria, which an AI wrote and which are mostly measurement checks (identical replay, HALT within one tick, conformance).
  - The Human's actual ideas sit in `bible/sources/REQUIREMENTS.md` as "original notes": background, not the to-do list.
  - Nothing tells the Builder the full ambition up front.
- **The inhabitants were forbidden to run until 2026-10-15.**
  - The monthly LLM cap for firm agents was null, which means no agent wakes.
  - So the Builder polished plumbing around scripted bots for weeks.
  - The cap is now $50/month, so real agents can run.
- **The rulebook reads as a safety manual.**
  - The Constitution and CLAUDE.md say "never" throughout.
  - The decision rule's tie-breakers put "safer" and "more honest measurement" first.
  - A model reading this becomes maximally cautious.
- **Ceremony on every mission, whatever its risk:**
  - an Opus architect writes a 300-line plan;
  - a failing acceptance check is written first;
  - the milestones are built;
  - a smoke run;
  - the validator, which duplicates the runner's own out-of-band check;
  - the red-team, whose holes are committed as strict-xfail tests before any fix;
  - the auditor, with a "claim list" (one counter-example test for every never/all/only sentence);
  - a re-audit;
  - six state files to update.
- **Friction:**
  - The guard blocks heredocs, `python -c`, `cd … &&`, and any command naming a protected path, which costs turns.
  - Runs are often a single session.
  - Background subagents are killed when a session ends.
- **Model choice:** Sonnet leads the build sessions while Opus reviews them. The cheaper model does the building.
- **Jargon:** the work is framed as M-00X / R-* / B-* / EC* ids, and the Human cannot follow it.

## 4. Target design
- **One main vision file: the ideas book.**
  - All the Human's ideas, in plain words, at full scale: section 1 above, every item of REQUIREMENTS.md, and the vision answers.
  - Read first in every session. The whole loop runs from it.
  - Each idea is marked: not started / building / working.
  - When the Human's ideas are exhausted (or blocked), the Builder appends its own ideas in the same book, marked as the Builder's, and builds those.
- **A run = one idea from the book, built until it works and can be seen working.**
  - The goal is one plain sentence (e.g. "the backtest: one AI in a sealed box, fed a month of data, day by day").
  - "Done" means it runs end to end with a demo, not "all reviews passed".
- **No human in the loop.**
  - Never a step that waits for the Human. Silence means go.
  - Visibility instead: the Builder Console shows "what the Builder is building now and how it understands it" in plain words.
  - The Human can leave an optional comment there. The Builder reads comments at the start of the next run and corrects course.
- **Build the firm first.** Instruments, verification and hardening come only when the firm needs them, or when a real bug or exploit shows up.
- **Risk-tiered process:**
  - Every change: `main` stays green, plus one acceptance check (a demo script) per idea.
  - Only changes to money, physics (permissions, OMS, market data, metering) or the seal get an independent review or a red-team.
  - No architect for normal work: the lead writes a short plan (about 30–60 lines at most).
  - Drop the separate validator; the runner already checks out of band.
  - Tests stay proportionate to the code; the acceptance demo is the main proof.
- **Paperwork:**
  - One handoff note per session, plus one journal line.
  - An ADR only when a rule of the world changes.
  - STATE / SHOWCASE / REPORT updated only if the Console needs them.
- **Rulebook tone:** short. A few hard limits, stated once. Everything else reads as "build it, make it real, make it work, push the limit".
- **Decision tie-breakers, reordered:**
  1. Inside the seal.
  2. Makes the firm more real or capable now.
  3. Deterministic physics.
  4. Reuse.
  5. Measurement where it matters.
- **Setup:**
  - Opus as lead, fewer subagents, subagents run in the foreground.
  - The guard allows normal shell commands inside the repo; the OS sandbox already protects what matters.
  - Several sessions per run (`cycles_per_run` 3–4).
- **Plain language everywhere the Human looks.** No internal ids in the Console, the handoff or the commit summaries.

## 5. Hard limits to keep (non-negotiable)
- Fake money only; nothing touches the real world: no brokers, payments, accounts, emails or posts. Read the web; push only to `origin`.
- Physics in `app/` is deterministic: no LLM call inside it.
- `governance/HALT` stops everything.
- Never raise or route around a budget cap. The firm-agent cap is set by the Human (currently $50/month).
- The Builder never trades or speaks as an agent, and never edits an agent's mind to steer it.
- Honest measurement: never fake a result or hide a failed trial.
- `main` always green, append-only history, no force-push.
- Never touch the Human's non-`firm-` OpenClaw agents.

## 6. The Human's ideas to seed the book (from REQUIREMENTS.md + vision answers)
- **Firm structure:**
  - Pods = PM + 2 analysts (+ engineer). A manager sits above the pods. Management (CEO) sees cash and positions.
  - The PM builds their own pod, chooses people, creates agents, and builds their own strategy, within rules set by the manager.
- **Pitch process:**
  - The PM pitches to a backtest operator (and initially the Human), then writes a full report.
  - A strategy must become an isolated function: data 1999–2026 → strategy → result.
- **Backtest:**
  - A fictional data calendar (e.g. one month). Each day, each AI receives a predetermined data package. The AI never fetches data itself.
  - The packages: prices only / fake company data / fake headlines + description / everything together.
  - Data is a table of days × tickers. Expected outcomes are known in advance, so behaviour can be tested.
  - New AI models can be dropped into the simulations to compare returns at different noise levels.
- **Strategy validation:** economic hypothesis; Information Coefficient (IC: 0.03 with many orders is good); deflated Sharpe ratio (penalise the number of attempts); capacity; low correlation with other pods.
- **Quant:** a Barra-like factor model, with attribution splitting returns into β / factors / α.
- **Allocation:** an algorithm (not management) moves capital fast to the most effective pods, based on viability.
- **Central risk:** at 5% drawdown, capital is halved; 7.5% and 10% trigger further steps.
- **Pod metrics:** performance, job cost vs return, cash attributed, risk, cash burned, number and type of jobs.
- **Communication:** inside pods, between pods (agents warn each other), a pod hub where everyone sees what the others do, and an event log / bus showing everything.
- **Orchestration:** workflows as programs ("Onboarding.exe", "Backtest.exe") that wake the agents.
- **Monthly reset:** each month is a generation. Evolution: designs that work reproduce with variation.
- **Cost:** every agent's LLM cost is attributed to it (done: metered). Cost counts against P&L.
- **Society and civilisation:** the firm creates departments and decides what to trade. Later: multiple firms, a regulator, an auditor, an exchange, price impact.
- **The Human's view:** a "what's new" visualiser (new features, new pods, what pod #5's strategy is), and a view of the agents in action.
- **Open decision from the Human:** keep the app × OpenClaw, or have the app manage its own agent hierarchy and architecture.

## 7. What already exists (reuse, don't rebuild)
- `app/`: FastAPI + SQLite physics:
  - event ledger, permissions, OMS, market data with a look-ahead guard, synthetic market;
  - metering (system-reported cost per agent), leaderboard, chat/bus, pods, HALT.
- `runtime/`: wakes agents and runs a month-long backtest:
  - scripted minds and a fake metered provider; budget gate; cassette record and replay;
  - `replay --verify` (IDENTICAL / DIVERGED); hosted world (`backtest --world`).
- `mcp_server/`: one MCP tool per endpoint.
- OpenClaw: static conformance work exists (`bible/08_OPENCLAW.md`). No `firm-` agent has run live yet.
- Mission queue (`state/missions.json`):
  - M-001 and M-002 are done.
  - M-003 (real OpenClaw desk), M-004 (hardening), M-005 (market crash scenario) and M-006 (central risk) are ready. They are raw material, not orders.
- Builder Console (outside the repo): `~/firm-dashboard`, port 8765, plain-English progress for the Human, including "How the last run went".
- The loop runner: `loop/builder.sh`, `loop/preflight.py` (out-of-band suite + acceptance + metrics in `~/.firm/metrics.jsonl`), and a Stop hook.

## 8. Practical notes for whoever does the rework
- **Human-only files:** the Builder may not edit `bible/00_*`, `bible/01_*`, `governance/**`, `loop/**` or `.claude/**`.
  - Write their new versions as drafts; the Human installs them through `setup/`.
  - That covers the Constitution and Genesis, the session gates (`.claude/commands/cycle.md`), the agent definitions, the guard, the runner, and `governance/human.yaml` (team models, sessions per run).
- **Builder-owned files:** `protocol/`, `CLAUDE.md`, `bible/02–09`, `state/`.
- Keep the existing code. The rework is the process, the rulebook, the goal source and the Console, not the app.
- First real target after the rework, unless the ideas book says otherwise: real AI agents (not scripted) living a backtest month with data packages, now that the cap allows it.
- The Human's profile: a non-coder who wants professional, sustainable engineering. Explain in plain words; never ask them to manage the process.

I (the user) have added my notes, those are notes and some part of it are completly irrelevent to it. But some contain genius ideas. This is another job by itself, but rework them to fit what we want, as a guideline for the builders
my notes (be carefull when using them, when reading that, it's not a pathwork to follow, it has been written like that but it's not. It's just an LLM that has work with it. make sure to read it with a necessary mature vision):
"
1. Ecosystem / Structure
Build order: 1 Basic Workflow, 2 Evolution/Extendability, 3 Debate, 4 Human Control
Work on the ecosystem first: completing nodes, capital allocation, evolution, cross-pod communication
The APP is the centralized core of the ecosystem
Micro orchestration → AI architecture
Macro structure → APP
POD HUB: everyone in the pod can see what the others are doing
Event log: see everything happening + the history of every action
Uses the "Bus"
Any order → Bus → Execute
Bus → Log
Orchestration layer: the engine that runs the workflow of any pod
Examples: Onboarding.exe, Backtest.exe, ...
It is the one that manages and calls Openclaw [?]
The system resets every month
2. Pods and Roles
POD = PM + Analyst + Analyst
Manager sits above POD #1, #2, #3
Management (CEO, vision of the firm) should be able to see basic data: cash, position (size & amount, ...)
The AI needs:
System rules + dynamic rules
Tools provided
Dynamic allocation (move the money fast to the most effective strategies)
Understand precisely a POD process (ex: Citadel, Millennium)
The PM builds his own pod (with regulation from user/manager)
He must be able to build his own strategy
He has the people he wants
He can create agents
Roles in the pod: PM, Analyst, Analyst, Engineer
The PM must first pitch his idea: [PM + backtest operator] + user
Then a comprehensive report on what he wants to do
POD data tracked:
Performance
Job cost against return
Job cash attributed
Basic data: risk, cash burned, amount of jobs and type of job
Adaptability: innovation, resilience (with adaptability)
3. Communication
Between roles inside the PODs
Between PODs
Why communication between AIs: efficiency (if an AI finds out something happens, it can notify the others)
Chat/MCP must work correctly
Chat messaging currently seems restricted to the central pod only
4. App Backend
File structure
api/: one file per topic
The first knock: receives the HTTP request, treats it, checks it, then calls registry/service.py and ledger/events.py
registry/: Security + HR, where everything is transferred safely
ledger/: the record keeper
db/: the door between the app outside and the storage
Roles of the files
api/events.py: the window, the clerk at the counter
Handles the HTTP request, checks permission, parses, hands back a response
Checks: is this a valid, allowed requester?
ledger/events.py: the worker, the archivist
Reads from and writes to the log book
Called by api/events.py, not directly by the agent
The window imports the worker when a "Get/events" request comes in
Responsibilities
Who's allowed → permission.py
What gets saved → service.py / events.py
URL & request management → api files
Data storage → fund.db + models.py
HTTP methods
Get → Read
Post → Create
Delete → Delete
Flow for [Get/Events]
Request arrives → main.py
Routed to the event window → api/events.py
Identity check → registry/auth.py + service.py → looks in fund.db
Check the rule book → permission.py → deny: not allowed
Denial written to the log book → ledger/events.py, then fund.db
A 403 is returned to the sender → main.py to the AI
API permission flow (example: John-PM)
John-PM makes a request
Name: John-PM
Credit: "Random API key specific to him"
Request: "Random request type"
Checks, in order:
Where do you want to go?
Is the API key real (is it fake)? → auth.py (then the table)
Are you allowed to do so? → permission.py
If passed everything, then execute → the targeted script
Database
fund.db is not created yet; the app needs to run for it to be created
It stores all info (11 tables)
AI agent
POD
Events
...
5. Strategy / Quant
Build an approximation of the MSCI Barra engine (MSCI Barra itself isn't usable)
An algorithm (not the management layer) handles the allocation of the PODs according to their [viability] [?]
Example: POD #1 (Vol: high, Cash 10K → 3K), POD #2 (Vol: low, Cash → 7K) [arrows unsure]
The strategy must be transformed into a function, isolated for the backtests
Data 1999–2026 → [Strategy] → result
Correlation: the strategy must not correlate with other PODs
6. Risk Management (Central Risk Control)
5% drawdown = Capital / 2
7.5% → [?]
7. Metrics
β (Beta): exposure of the strategy to the actual market movement
α (Alpha): the skill of the POD
The POD uses his skill → research to try to beat the market
Example portfolio, 10K: 8K → S&P500, 2K → unknown solar energy company
β = overall expected return
α = skill developed by working on the strategy
If the market (β) moves up 10%, the portfolio is expected to grow at minimum 10%; α can grow much more
MSCI Barra determines α with more precision and shows each part of it
Example, 15% bonus: 10% β, 3% dangerous investments, 2% [manager only bought, ?], 0% alpha (only followed the trend)
8. Strategy Validation Checks
Economic hypothesis
Example: finding that 2 prices are correlated (gold market and oil tankers); there has to be logic behind it
IC measure (Information Coefficient)
Score of 1 = perfect market prediction
Score of 0.05 = exceptionally robust
IC of 0.03 ✓
Few orders and an IC of 3% ✗
The IC can vary across different types of market
Deflated Sharpe Ratio
SR = Return / Risk
Deflated = adjust the SR score according to the number of previous attempts
Capacity
From what amount of capital the strategy [kills itself] [?]
Diversification: if the IC stays the same across different stocks or currencies, it's good. Less important for us (not enough capital)
Frequency: many orders and an IC of 0.03 ✓
Required metrics / agent allocation / backtest / ...
9. Backtesting
Fictional data calendar (one month, for example)
Day J-1 → AI1 receives data X; AI2 receives data Y
Observe what comes out
Goal: know in advance what must come out; create a predictable sequence of actions and test them
The AI does not fetch data itself; it is given a predetermined data package, for example:
Just the market prices
Fake company data
Fake headline + description
Everything together
Data table: days (Mon / Tue / Wed ...) × AAPL price, NVDA price, TSLA price, ...
Idea: AI models could be tested
New models placed in simulations to see the return, with different degrees of [noise] [?]
10. Build Status
Phase 0 complete
Skeleton of the system
Git initialization (also a project in GitHub)
API test working
Phase 1 has been built
OMS [written "ONS"] migrated: the old system made to work for the new system
Known to work
API skeleton
Database
Logging logic
OMS migrated: orders can be passed to it and it executes them
Next: understand the goal of Phase 1 and make the AI work as simply as possible
To see what is currently doable in Phase 1: check the chat "Assess AI hedge fund system"
11. Open Issues
Cost: the whole fund uses one API key, not one per agent → the cost part is biased
Need a way to get every agent's cost
Find a way to have cost management, for future AI experiments
Chat issues
An agent can't know who he is (agent from system script) → add a "Get me" chat; check "Explain chat... system work..."
No precise command to get "n" messages of history; it gives back the whole history
Chat messaging seems restricted to the central pod only
"