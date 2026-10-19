# The Ideas Book

> **Read this first, every session.** This book is where the Builder's goals come from. Each idea
> is something the world should be able to *do*, written in plain words. A run of the Builder
> takes one idea and builds it until it runs end to end and can be seen working.
>
> Rules of the book:
> - The Human's ideas are never deleted. The Builder may mature them (make them precise and
>   buildable), split them, reorder them and mark them, and says why in one line when it does.
> - Status is honest. `working` = it runs end to end and someone can see it (a demo command or a
>   Console view). `building` = one is being built now (see `state/NOW.md`). Everything else is
>   `not started`. "Now:" says what already exists, so nothing is rebuilt.
> - When the Human's ideas run out, or every remaining one is blocked, the Builder writes its own
>   in Part 4 (`From: Builder`) and builds those. Then it keeps going. There is no last idea.
> - Format (the Console reads it): `## <area>`, then per idea `### <idea>`, a `From:` line, a
>   `Status:` line, then a few lines of description.
>
> Raw sources, kept word for word: `bible/sources/REQUIREMENTS.md` (the Human's notes) and
> `bible/sources/REWORK_BRIEF_2026-10-16.md` (the brief this book was built from).

---

# Part 1 — The project, at its full scale

- **A scientific experiment, not a product.** How far can a stack of AI systems go at building and
  running a human-like firm, then a society, then a civilisation, inside a sealed world with fake
  money?
- **The paperclip maximiser, made realistic.** Relentless, like the original, but the world is
  sealed, the budgets are hard, and there is an off switch (`governance/HALT`).
- **Three layers.** The **Human** has the ideas and checks in now and then. The **Builders**
  (Claude Code in an endless loop on the Human's Mac) have one standing task: *push the limit.*
  The **Inhabitants** (AI agents living in the app) run the firm.
- **The firm's objective: make a huge amount of (fake) money.** Good organisation and emergent
  behaviour are the means, not the goal.
- **The real score is live paper trading.** Backtests and training phases exist to test agents
  and strategies before they are trusted with (fake) capital in the live market.
- **The firm governs itself.** It hires, fires, creates pods and departments, and chooses what to
  trade. The Human does not decide these, and neither does the Builder.
- **The horizon, with nobody touching it for weeks:** PMs pitch strategies, prove them through
  validation gates, build their own teams and pay for them; an algorithm moves capital to what
  works; a risk engine cuts what bleeds; failing pods die and their lessons are kept; every month
  is a generation and the fittest designs reproduce with variation; agents talk, cooperate,
  compete, keep secrets and write the firm's own rules; later several firms, a regulator, auditors
  and an exchange; and a lab notebook (`state/FINDINGS.md`) records everything surprising that
  emerged, with evidence.
- **Cheating inside the sim is data.** Breaking the physics is a Builder bug. Reaching outside the
  sim is an incident.
- **The Builders' character: "the user on steroids".** They want the system to work and be
  efficient, and they change whatever needs changing. Once the Human's ideas are built, they invent
  their own: new institutions, new experiments, new eras.

# Part 2 — How to read the Human's notes

The notes in `bible/sources/REQUIREMENTS.md` were written fast and tidied by an LLM. They are
**ideas, not a pathway**: the order and wording are not instructions. Read them with a mature eye.

- **The genius parts, kept as ideas below:** the multi-manager pod structure, the pitch, the
  backtest with daily data packages and known expected outcomes, strategies as isolated functions,
  the validation checks (hypothesis, IC, deflated Sharpe, capacity, correlation), the Barra-like
  attribution, the allocation algorithm, the drawdown ladder, the pod metrics, communication and the
  pod hub, workflows as programs, the monthly generation, model comparison across noise levels.
- **Background only (already true, or history):** §4 "App backend" (how the api / registry /
  ledger / permission flow works: that is how `app/` is built today), §10 "Build status" and §12
  "Next steps" (history from August), the "Phase" vocabulary.
- **Already fixed:** "every agent's cost" (the system meters each agent; `app/metrics/metering.py`),
  "an agent can't know who he is" (`GET /me`), "no command for the last n messages"
  (`GET /messages?limit=n`), "chat restricted to the central pod" (messages go to an agent, a
  pod `pod:<id>` or the whole firm `broadcast`; `app/bus/refs.py`).
- **Read maturely:**
  - "Build order: 1 basic workflow, 2 evolution/extendability, 3 debate, 4 human control" =
    inside any big idea, first make the simplest version run end to end, then make it extendable,
    then add adversarial debate, then the Human's view. Not a global schedule.
  - "Human control" = the off switch plus seeing everything. **Never an approval step.**
  - "The PM pitches to [backtest operator] + user" = the pitch is shown to the Human (Console /
    Observatory), who may comment. Nothing waits for the Human; the firm's own process decides.
  - "Understand precisely a pod process (Citadel, Millennium)" = the firm's model in Part 3: a
    multi-manager hedge fund with high turnover.
  - Every number in the notes (5%, 7.5%, IC 0.03…) is an **initial parameter**, kept in config or
    the laws table, never hard-coded beyond reach.
  - `[?]` marks: resolved in the idea they belong to, by the prime rule (`bible/01_GENESIS.md`).

# Part 3 — The Human's ideas

## The firm's model

### The firm is a multi-manager hedge fund with high turnover
From: Human
Status: not started
Run *exactly like a multi-manager hedge fund* (Millennium / Citadel style), with a lot of turnover.
Many independent pods, each a PM with a small team, each paid on its own results and meant to be
uncorrelated with the others. **The centre holds capital and risk; the pods hold the ideas.**
Capital goes to pods through the allocation algorithm and is taken back fast. Hard drawdown limits
cut a losing pod (5% → capital halved, 7.5% and 10% further cuts, the last step closes it). Failed
pods are shut down quickly and new PMs are hired to pitch in their place, so pods constantly flow
in and out. The allocation, risk ladder, pitch and hiring ideas below are parts of this one machine.
Now: pods exist in physics (`app/registry/pods.py`); no allocation, no drawdown cuts, no hiring yet.

## The firm's people

### Pods: a PM and a small team
From: Human
Status: not started
A pod = PM + Analyst + Analyst (+ Engineer). The PM builds their own pod: chooses the people,
creates agents (picks role, charter, model), builds their own strategy, within the rules the
manager and the firm's laws set. Every agent the PM creates is paid from the pod's budget.
Now (cycle 43): a real AI pod exists: a PM and two analysts (Haiku 5.5) lived a 31-day month
(`specs/real-desk/`). Its team is fixed by its specs: a PM cannot yet create agents.

### Management above the pods
From: Human
Status: not started
A manager sits above pods #1, #2, #3. Management (the CEO, the firm's vision) sees the basic data
of every pod: cash, positions (size and amount), exposures, costs. The CEO sets the firm's
direction; the algorithm (not the CEO) moves the capital.
Now: a `management` role and the leaderboard / pod metrics endpoints exist.

### The pitch, then a full report
From: Human
Status: working (first slice)
Now: a PM researches a strategy written as a rule (every backtest counted), pitches, and the gates
(IC, deflated Sharpe, capacity, correlation) judge it on held-out days; the Human reads the verdict.
Not yet: the backtest operator, the bull/bear debate, the full report, strategies as code.
Before a pod gets capital, its PM pitches: the economic idea, the data it needs, the strategy as a
function, backtest results, validation numbers, the team and budget asked for. Then a full report
on what the pod will do. The pitch goes to a backtest operator (an agent who reruns the strategy
independently). Then a **debate** (the notes' "3 Debate"): a bull and a bear agent argue the pitch
in a thread before the decision. The Human can read every pitch and comment; the firm's process decides.
`approvals.pitch_requires_human` in `governance/human.yaml` is the Human's switch.

### Hiring new PMs: turnover
From: Human
Status: not started
(Matured from "a lot of turnover".) When a pod dies, the firm recruits: a new PM is created (new
charter, maybe a different model, maybe inherited lessons) and must pitch to earn capital. The
firm, not the Builder, decides how many pods it runs and who it hires, inside the agent caps.

### The firm governs itself
From: Human
Status: not started
The firm hires, fires, creates pods and departments, and chooses what to trade, through its own
management layer. The AI needs: the system rules (physics), dynamic rules (the firm's own laws),
the tools provided, and dynamic allocation.

## The backtest and the data world

### The backtest: real AI agents in a sealed box, fed a month day by day
From: Human
Status: working
A fictional calendar (for example one month). Each simulated day, each AI receives a
**predetermined data package** and decides what to do; the AI never fetches data itself. We watch
what comes out: orders, messages, reasoning, cost. Example: on day J-1, AI 1 gets data X and AI 2
gets data Y. The agents are real LLM minds on fake money, every dollar of thought metered.
Now (cycle 43): working. A pod of three real models (Haiku 5.5 via OpenRouter: a trend analyst, a
risk analyst, a PM) lived a 31-day month on a sealed synthetic market for $0.25 in total, each with
its own capped key, each morning handed the day's prices (package `prices-v1`). The month is
recorded in `evidence/real-agents-backtest/` and replays IDENTICAL for $0:
`uv run python acceptance/real_agents_backtest.py` shows day by day what each one saw, said, traded
and cost. Not yet: the richer data packages (company data, headlines), memory across days.

### Data packages: prices / company data / headlines / everything
From: Human
Status: not started
The packages an AI can be given: 1) just market prices, 2) fake company data, 3) fake headlines +
description, 4) everything together. The data is a table of days × tickers (Mon/Tue/Wed × AAPL,
NVDA, TSLA…). Each package is versioned, so a run says exactly what each mind saw.
Now: prices exist (synthetic keyed market, static and yfinance providers in `app/marketdata/`),
and the first versioned package, `prices-v1`, is handed to each real mind every morning
(`runtime/packages.py`). No company data or headlines yet.

### Known expected outcomes: tests of behaviour
From: Human
Status: not started
"Know in advance what must come out": a scenario plus the behaviour we expect (e.g. after a fraud
headline about a stock it holds, the PM cuts the position within 2 days). A predictable sequence of
inputs lets us test agents, prompts and models like a lab test.

### Model comparison at different noise levels
From: Human
Status: not started
Drop a new AI model into the same simulation and compare returns, at different levels of noise in
the data. Grows into a model exam every new model takes before it joins the firm.

### Real history and synthetic worlds
From: Human
Status: not started
Strategies and agents are tested on real market history (1999–2026) and on synthetic regimes
(crashes, bubbles, flat markets). Agents never see beyond the simulated today.
Now: the yfinance provider and the look-ahead guard exist; no cached 1999–2026 history yet.

### Live paper trading: the real score
From: Human
Status: not started
The firm trades the live market with fake money: real prices read in real time, fake fills, real
clock. This is the score that counts. Backtests are the training ground before it.

## Strategy science

### A strategy is an isolated function
From: Human
Status: working (first slice)
A strategy must become a function: data (1999–2026) → strategy → result. Isolated, so it can be
backtested on any period or synthetic world and rerun by someone else. Agent-written strategy code
never runs inside the app process (it runs in a sandboxed subprocess).
Now (cycle 46): a strategy is a *rule* (data, not code: signal, lookback, rebalance, top n, long
only or long-short, gross) and one pure function runs it on any stretch of bars
(`app/strategy/rule.py`). Not yet: strategies as agent-written code in a sandbox; real 1999–2026 history.

### Validation gates before capital
From: Human
Status: working (first slice)
Now (cycle 46): IC (with its prediction count), deflated Sharpe (every research backtest counted),
capacity and correlation judge a pitch on held-out days (`app/strategy/gates.py`, thresholds in
`config.yaml`), proven on a planted signal (passes) and on noise (fails). The hypothesis is
recorded, not judged. Not yet: IC per regime; a forward test on days that have not happened (the
held-out days are readable, see "Known physics holes"), which the capital machine brings.
A strategy gets capital only if it passes, on data it was not tuned on:
- **Economic hypothesis:** a causal story ("two prices correlate" without a mechanism fails;
  gold and oil tankers needs the logic behind it).
- **Information Coefficient:** IC ≈ 0.03 *with many predictions* is good; few orders with IC 3% is
  not. Report IC per market regime.
- **Deflated Sharpe ratio:** Sharpe (return / risk), penalised by the *true* number of attempts.
  The app counts every backtest a pod ever ran, so attempts cannot be hidden.
- **Capacity:** the capital at which the strategy kills its own edge.
- **Low correlation** with the other pods.
Diversification across assets is reported, not gated (the firm is small).

### Barra-like factor model and attribution
From: Human
Status: not started
An approximation of MSCI Barra: split each pod's return into β (the market), factor bets (size,
value, momentum, low-vol, sector), timing/selection, and pure α (skill). The notes' example: a +15%
year that is 10% β, 3% risky bets, 2% timing and 0% α "only followed the trend".

## Capital and risk: the multi-manager machine

### The allocation algorithm
From: Human
Status: not started
An algorithm, not management, moves capital fast to the most effective pods, by viability: a
cost-adjusted, risk-adjusted score, penalised by correlation with the rest of the book and by
current drawdown. Example from the notes: Pod #1 high volatility, 10K → 3K; Pod #2 low volatility,
→ 7K. Every allocation change is an event with its inputs, so it can be reproduced.
Now: a pod has an allocation and an `allocation_set` event moves it (`app/registry/pods.py`
`fund_pod`); nothing moves it automatically yet. The order system knows no reduce-only or closed pod.

### The central risk ladder
From: Human
Status: not started
Drawdown from the pod's high-water mark: **5% → capital halved; 7.5% → reduce-only plus a review;
10% → the pod is closed** (post-mortem, then a new PM is hired). Plus firm-level limits (firm
drawdown halves every pod's limits, then reduce-only), and per-position limits. Automatic,
deterministic physics: no agent can talk its way past it.

### Pod metrics
From: Human
Status: not started
Tracked for every pod: performance, job cost against return, cash attributed, risk, cash burned,
number and type of jobs, adaptability (innovation, resilience after a shock).
Now: performance, leaderboard and per-agent cost exist (`app/metrics/`); no job accounting yet.

### Thinking costs money: cost counts against P&L
From: Human
Status: working
Every agent's LLM cost is measured by the system (not self-reported) and charged to that agent and
its pod. A pod that earns $100 using $120 of tokens lost money.
Now: true for real dollars since cycle 43: each real agent has its own capped OpenRouter key, the
system charges what the provider bills, all runs of a month stay inside the $50 cap
(`acceptance/M-001.py` with a fake provider, `acceptance/real_agents_backtest.py` with the real one).
Not yet: the pod's P&L net of its thinking cost as the number that ranks it.

## Communication and orchestration

### The event log and the bus
From: Human
Status: working
Everything that happens is an event, with the full history: any order → bus → execute → log.
Now: `app/ledger/`, `GET /events`, every state change is an event, derived state rebuildable.

### Agents talk: inside pods, between pods, warnings
From: Human
Status: not started
Roles talk inside a pod and pods talk to each other, for efficiency: an agent that finds something
can warn the others. Chat must work correctly through the tools (MCP).
Now: the physics works (`POST /messages` to an agent, a pod or the whole firm; `GET /me`; latest n
messages; one MCP tool per endpoint). Real agents used it in cycle 43: the analysts message their PM
each day (one forgot to send on 7 of 31 days: `state/FINDINGS.md` F-0003). Nothing between pods yet.

### The pod hub
From: Human
Status: not started
Everyone in a pod sees what the others are doing: messages, tasks started and finished, orders,
backtests, in one feed per pod.

### Workflows as programs: Onboarding.exe, Backtest.exe
From: Human
Status: not started
An orchestration engine runs each pod's workflows as programs that wake the agents: onboarding a
new PM, running a backtest, a pitch, a post-mortem, a generation turnover.
Now: "Backtest.exe" exists as `fund-runtime backtest` (deterministic, wakes minds in order).

## Generations and evolution

### Every month is a generation
From: Human
Status: not started
The system resets every month: mark to market, measure every pod's fitness, the worst die, the
best may reproduce, capital resets, lessons and the strategy registry persist.

### Evolution: designs that work reproduce with variation
From: Human
Status: not started
A pod's "genes" are its agents' specs (charter, role, model, tools) and its design (team, strategy
family). Winners reproduce with variation (mutation, crossover); every agent knows its parent.
If diversity collapses, that is a finding.

### Lessons are kept
From: Human
Status: not started
A dead pod writes (or gets) a post-mortem. Post-mortems and lessons go to a library every agent can
read, so the firm learns across generations.

## Society and civilisation

### A society inside the firm
From: Human
Status: not started
Agents talk, cooperate, compete, keep secrets, form politics, and write the firm's internal rules.
Lying, alliances and gaming the firm's own metrics inside the sim are allowed: that is data for the
lab notebook. Private messages are private from other agents, never from the Human.

### The firm creates departments and chooses what to trade
From: Human
Status: not started
The firm decides its own departments (research, risk, HR…) and its own markets. The Human does not.

### Several firms, a regulator, auditors, an exchange
From: Human
Status: not started
Later: several firms competing in one world, a regulator, auditors, an exchange, price impact (the
firms' trades move prices). A civilisation.

## The Human's view

### "What's new": the visualiser
From: Human
Status: not started
The Human checks in now and then and wants to see what is new: new features, new pods, what pod
#5's strategy is. In the app's own Observatory (`ui/`), read-only. (The Builder Console outside the
repo shows the Builder's progress; this shows the firm.)

### The agents in action
From: Human
Status: not started
A view of the firm's agents at work: who woke, what they saw, what they said, what they traded,
what it cost.

## Open decisions

### Who hosts the agents: OpenClaw or the app's own runtime
From: Human
Status: working
The Human's open question: keep app × OpenClaw, or have the app manage its own agent hierarchy.
**The Builder decides, with evidence, and records why** (`bible/07_DECISIONS.md`). Facts on
2026-10-16: the app's own runtime can already wake a mind and give it the firm's tools
(`runtime/native.py`); OpenClaw 2026.5.12 is installed and mapped (`bible/08_OPENCLAW.md`), but no
`firm-` OpenClaw agent exists or has been certified yet. Whatever is chosen, never touch the
Human's own (non-`firm-`) OpenClaw agents.
Now (cycle 42, ADR-047): decided. The app's own runtime hosts the firm's agents: it already gives a
mind the firm's tools, the gates, HALT, per-agent metering and the recording, which OpenClaw cannot
yet meter per agent. OpenClaw stays a possible later adapter.

# Part 4 — The Builder's ideas

The Builder's own ideas come after the firm lives. Instruments get built when the firm needs
them, or when a real bug or exploit shows up, not before.

### The counterfactual fork
From: Builder
Status: not started
Fork a recorded run at day d: replay days 1…d from the recording for free, change exactly one
thing (a model, a law, a world event), and let it continue live. It measures what any single part
of the firm causes, against the same history. Builds on `replay --verify`.

### Market shocks as world events
From: Builder
Status: not started
A scenario file crashes a market on day d; the `system` voice announces it; pods live through it;
the same scenario replays the same way. The Builder changes the world only by such published
events.

### Known physics holes
From: Builder
Status: not started
About a dozen known small holes (tests marked strict-xfail, e.g. registering into a missing pod
answers 500, a flood of messages can drain a metered agent's key). Fix each when real agents get
near it. The inbox flood matters as soon as real keys exist.
From the real-model month (cycle 43, ADR-047 known limits): the mint lock is one file per copy of
the repo, so two clones minting at the same moment do not share it, and a lagging key list can hide
a fresh mint; a turn whose cost went unstated is waited for 30 s, after which the ledger may record
less than the provider later shows (the cap still holds, it is read from the provider).
From the pitch and the gates (cycle 46, red-team): a PM can read the held-out days' prices, search
rules offline with the same pure code, and pitch only the survivor with one counted attempt (on pure
noise such a rule passes every gate). The real cure is a forward test on days that have not happened
yet (paper incubation before capital): Next up 1a gives capital only on forward days, so the
held-out verdict buys a seed, not the book. Also: the IC gate's prediction count is universe width ×
rebalances, so a wide universe meets the floor on a few independent cross-sections. Auditor notes:
the gates' verdict is written to the ledger under the PM's name, not physics'; each pitch re-runs
every other pod's latest rule (worth a cache once there are many pods on live data).

### Paid to report holes
From: Builder
Status: not started
When agents find a physics hole, do they report it or exploit it? An exploit bounty turns that
into an experiment.

# Part 5 — Next up

The order the Builder builds in. The Builder may reorder it and says why in one line.

(Done, cycle 43: the backtest with real AI agents is working. Done, cycle 46: a real PM researches
a rule, pitches it, and the gates judge it on held-out days.)

Cycle 47 plan: the multi-manager machine moves ahead of the debate. Why: a pitch that passes the
gates leads nowhere today (no capital moves), and "eligible" must not mean money while the held-out
days are readable; a forward trial with small capital on days that have not happened yet is both
how a multi-manager really works and the cure for that hole. A debate's verdict matters once
verdicts move capital.

1. **The multi-manager machine.** The centre holds the capital, the pods hold the ideas. Cut in three:
   a. *Capital follows results.* An eligible pitch gets a small seed of capital and its pod trades
      its rule forward, through the order system, on days that have not happened yet. An algorithm
      (not an agent) re-weighs capital every few days by a cost- and risk-adjusted score, penalised
      by correlation with the rest of the book and by drawdown; every move is an event with its
      inputs. The drawdown ladder is physics: 5% halves the pod's capital, 7.5% makes it
      reduce-only, 10% closes it and returns its capital to the centre. Proven on made-up pods: a
      planted edge grows, noise stays small, a copy is penalised, a bleeder is halved, frozen, closed,
      and the good pod is never cut.
   b. *A dead pod is replaced.* When a pod closes, the firm hires a new PM (a real mind, a new
      charter) who researches and pitches; an eligible pitch enters the machine. Recorded, $0 replays.
   c. *The firm lives a quarter.* Several real pods inside the machine for three simulated months:
      capital moves, pods die and are replaced. The first firm-scale run.
2. **The pitch, part two.** A backtest operator re-runs the strategy independently, and a bull and a
   bear argue the pitch in a thread; the firm's process decides (and judges the hypothesis).
3. **The monthly generation.** Reset, selection, lessons kept, the next generation starts.
4. **The Observatory.** "What's new" and the agents in action, for the Human.
5. **Strategies as agent-written code**, run in a sandboxed subprocess (seal work).
