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
Status: working (1c done, cycle 54: four real PMs lived a quarter in the machine)
Run *exactly like a multi-manager hedge fund* (Millennium / Citadel style), with a lot of turnover.
Many independent pods, each a PM with a small team, each paid on its own results and meant to be
uncorrelated with the others. **The centre holds capital and risk; the pods hold the ideas.**
Capital goes to pods through the allocation algorithm and is taken back fast. Hard drawdown limits
cut a losing pod (5% → capital halved, 7.5% and 10% further cuts, the last step closes it). Failed
pods are shut down quickly and new PMs are hired to pitch in their place, so pods constantly flow
in and out. The allocation, risk ladder, pitch and hiring ideas below are parts of this one machine.
Now: capital follows results (cycle 48): an eligible pitch earns a seed and its pod trades forward;
an algorithm re-weighs capital every few days by a cost- and risk-adjusted score, cut for copying
and for drawdown; the drawdown ladder halves at 5%, freezes buying at 7.5%, closes at 10%; a closed
pod's place is filled by a newly hired real PM who pitches and can earn a seed (cycle 51). Four
real PMs lived a quarter on one market (cycle 54): the edge pod was raised to $2.9M, the noise pod
never funded, the sinking and crashing pods closed and replaced by hires who earned seeds; the
Human reads a quarter report (`fund-env quarter-report`). Cycle 59: the firm turns over by
itself every month (a PM who never earns a seed is let go, thinking is charged at every step of a
real run). Cycle 62: a freed place goes to a child of the month's fittest pod. Cycle 64: a PM
can hire its own analysts (real PMs chose not to). Cycle 66: a manager mind may pick who fills a
freed place among the hires the law allows (a real Haiku manager kept the law's own hire). Cycle 68: headlines and company data are handed by role, so an analyst can
know what its PM does not (a real prices-only PM cut a fraud name on its analyst's word). Cycle 70:
under a debate law, reviewers argue an eligible pitch and the manager seeds it now or holds it (a
real Haiku manager held every planted-edge pitch as too good to be true). Not yet: a market whose
edges are believable enough for that judgement to let money through.

## The firm's people

### Pods: a PM and a small team
From: Human
Status: working (first slice)
A pod = PM + Analyst + Analyst (+ Engineer). The PM builds their own pod: chooses the people,
creates agents (picks role, charter, model), builds their own strategy, within the rules the
manager and the firm's laws set. Every agent the PM creates is paid from the pod's budget.
Now (cycle 43): a real AI pod exists: a PM and two analysts (Haiku 5.5) lived a 31-day month
(`specs/real-desk/`). Its team is fixed by its specs: a PM cannot yet create agents.
Matured (cycle 63 plan), first slice "a PM builds its team" (Next up 1): a PM asks physics for an
analyst (its charter, and a model from the firm's pool); the pod's team limit, the agent cap and
the pod's thinking budget decide; a granted request opens a team place that the Runtime fills the
next morning (Onboarding, reused), with a key whose limit is carved from the pod's budget. The
analyst researches (its backtests are the pod's attempts at the pitch), reads the library and
messages its PM; it cannot pitch or trade. Its thinking is the pod's: it lowers the pod's fitness
and the capital score. The PM can let it go. The team becomes part of the pod's design.
Now (cycle 64, ADR-053): built. A PM asks for an analyst (charter, model, budget); physics grants
or refuses by name (pool, a $ team budget a pod where a hired analyst's budget stays spent, two
analysts, three asks a day, the agent cap); the Runtime hires it the next morning with a key of the
granted budget; its research is the pod's attempts, its thinking the pod's fitness; the PM lets it
go, and a team goes with its PM or its pod. Real Haiku PMs offered a team for twelve steps: three
read it, none asked (one: more attempts only make the deflated-Sharpe test harder). Not yet:
engineers, a PM choosing its analyst's tools, the team as an inherited gene, a team that pays.

### Management above the pods
From: Human
Status: working
A manager sits above pods #1, #2, #3. Management (the CEO, the firm's vision) sees the basic data
of every pod: cash, positions (size and amount), exposures, costs. The CEO sets the firm's
direction; the algorithm (not the CEO) moves the capital.
Now: a `management` role and the leaderboard / pod metrics endpoints exist; no manager mind has
ever woken. The role's rights are the old TRD table's: a management agent the operator makes counts
as the operator's registrar, so it could fill vacancies, register and deactivate agents directly.
Matured (cycle 65 plan), first slice "a manager chooses the hires" (Next up 1): one real manager
mind wakes each morning and reads the firm board (every pod's cash, positions, exposures, capital,
drawdown, thinking cost, fitness). When a place is freed, physics lists the candidates the law
allows (the fittest pod's child, a child of another fit pod, a plain hire on each model of the
pool) with the law's default marked; the manager may pick one and write the new PM's brief before
the morning hire, else the default stands (a silent manager never blocks turnover). It writes the
firm's direction, which every PM reads. It never moves capital, never hires or fires by itself:
the Runtime's registrar still does both. Its thinking is the centre's cost, against the firm's P&L.
Now (cycle 66, ADR-054): built. A manager mind (role `manager`: it reads every pod on its board,
picks, briefs and writes the firm's direction; it cannot trade, pitch, hire, fire or move capital;
only the operator makes one) sees each freed place's list (c1 the law's own hire, a child of each
other fit pod, a plain hire on each model) for one day; its pick is hired exactly, silence keeps
the law's hire. Its thinking is the centre's. A real Haiku manager over three months of real
Haiku PMs (recorded twice, $0.59 each): both times it kept the law's own hire, wrote a brief for
the new PM, and never wrote a direction. Cycle 70: the manager rules on pitches in debate (seed
now or hold with a reason). Not yet: a manager that opens pods or fires early; departments.

### The pitch, then a full report
From: Human
Status: working (the gates; the debate)
Now: a PM researches a strategy written as a rule (every backtest counted), pitches, and the gates
(IC, deflated Sharpe, capacity, correlation) judge it on held-out days; the Human reads the verdict.
Not yet: the backtest operator, the bull/bear debate, the full report, strategies as code.
Before a pod gets capital, its PM pitches: the economic idea, the data it needs, the strategy as a
function, backtest results, validation numbers, the team and budget asked for. Then a full report
on what the pod will do. The pitch goes to a backtest operator (an agent who reruns the strategy
independently). Then a **debate** (the notes' "3 Debate"): a bull and a bear agent argue the pitch
in a thread before the decision. The Human can read every pitch and comment; the firm's process decides.
`approvals.pitch_requires_human` in `governance/human.yaml` is the Human's switch.
Matured (cycle 69 plan), first slice "a pitch is argued before its seed" (Next up 1): when a
debate law is on, a pitch the gates find eligible waits a set number of days before its seed.
Physics opens a thread for it. Two centre minds the operator makes, a bull and a bear (a new
`reviewer` role: they read pitches and the data their rights give them, write only in a pitch's
thread, cannot trade, pitch, hire or message a pod), each read the pitch (hypothesis, rule, the
gates' numbers) and argue their side in the thread; the PM may answer. The manager reads the
thread and gives a verdict before the window ends: *seed* (now) or *hold* (the seed is refused,
with the manager's reason, which the PM reads). Silence: the law's seed stands, so a quiet manager
never blocks capital. The manager can only stop or speed a seed the gates and the centre already
allow: it never seeds an ineligible pitch, never changes the amount. The reviewers' and the
manager's thinking is the centre's cost. Without the law, pitches seed exactly as today. The
backtest operator is left out: the gates already re-run the rule on held-out days with physics'
own code. Why this slice: the cycle-68 news gives a bear something real to argue (a fraud
headline on a name in the pitched rule's universe, read only by the bear), and it is the first
time an agent's judgement, not a formula, decides whether money moves.
Now (cycle 70, ADR-055): built. Under the debate law an eligible pitch's debate opens the next
morning; reviewers (a new centre role, operator-made, no pod, no inbox) and the pitch's PM argue in
its thread; the manager seeds now or holds with a reason (refused by the next sweep, the PM reads
it); silence pays at the close. Real Haiku bull, bear (given headlines) and manager on three
planted-edge pitches: the bear named K03's fraud, and the manager held all three as "too good to
be true" (the made-up edge is far stronger than any real one). Not yet: the backtest operator, the
full report, realistic planted edges.

### Hiring new PMs: turnover
From: Human
Status: working (cycle 51)
(Matured from "a lot of turnover".) When a pod dies, the firm recruits: a new PM is created (new
charter, maybe a different model, maybe inherited lessons) and must pitch to earn capital. The
firm, not the Builder, decides how many pods it runs and who it hires, inside the agent caps.
Now (cycle 51, ADR-050): a pod the ladder closes opens a vacancy with its post-mortem; the hiring
law (live-pod limit, models in turn, budget, charter) names the hire; the Runtime fills it the
next morning under the cap, and the new PM wakes with the post-mortem, researches and pitches.
Recorded: a real Haiku 5.5 hire pitched long-short, read the refusal on its pitch, re-pitched
long-only, was seeded $200k and trades. Cycle 59: a PM who never earns a seed in a month is let go
and hired over; every departure's lesson is in a library all PMs read. Cycle 62: the hire into a
freed place is a child of the month's fittest pod. Cycle 66: a manager mind may pick the hire
among those the law allows, and brief the new PM (real Haiku managers kept the law's own pick).

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
Status: working
The packages an AI can be given: 1) just market prices, 2) fake company data, 3) fake headlines +
description, 4) everything together. The data is a table of days × tickers (Mon/Tue/Wed × AAPL,
NVDA, TSLA…). Each package is versioned, so a run says exactly what each mind saw.
Now: prices exist (synthetic keyed market, static and yfinance providers in `app/marketdata/`),
and the first versioned package, `prices-v1`, is handed to each real mind every morning
(`runtime/packages.py`). No company data or headlines yet.
Matured (cycle 67 plan), first slice "headlines and company data, handed by role" (Next up 1):
- *The world writes them.* The made-up market's recipe gains dated items: headlines (a title and
  a short description, about one ticker or none) and quarterly company reports (revenue, earnings,
  guidance). Most are noise, made from templates by the seed (how many a day is the world's noise
  level); a few are *planted causes*: a fraud headline, an earnings miss, each with an effect on
  that ticker's later prices written in the recipe. No LLM writes them: they are physics.
- *Physics serves them, never early.* Headlines and reports are read through the API at the
  world's now: an item published tomorrow does not exist today (the same look-ahead law as prices).
- *Handed by role.* Each agent holds data rights (prices for everyone; headlines and company
  data only if granted). The operator grants them at registration; a PM may ask for an analyst
  with a package the PM itself does not have. A mind without the right is refused by name (403,
  logged), in its tools and in its morning package.
- *Versioned packages.* `headlines-v1`, `company-v1`, `everything-v1` beside `prices-v1`; each
  mind's spec names its package; a run records which package each mind saw.
Why now: the cycle-64 and cycle-66 findings: a PM offered analysts worked alone (on prices alone it
is right), and a manager kept the law's hire (no pod knew anything another did not). Information
that only some minds hold is what gives a team, a manager and a debate their work.
Now (cycle 68): working. A made-up market's recipe may carry news: noise headlines, a quarterly
report per company and planted causes (a fraud headline, an earnings miss) that move only their
name's later prices. A day's news is out at its close, with its bar. Headlines and company data
are rights: the operator grants them at registration, or a PM asks for an analyst with data the
team law lists; a mind without the right is refused by name, through its tools and in its
package. Packages `headlines-v1`, `company-v1`, `everything-v1`. A real Haiku analyst flagged
K03's fraud the first morning it was out; its prices-only PM read the message a day later and
sold all of K03 ($0.078): `uv run python acceptance/data_packages.py`. Not yet: data that costs
money, the manager reading news, news in real history, a PM asking for a package for itself.

### Known expected outcomes: tests of behaviour
From: Human
Status: working (first scenario, cycle 68)
"Know in advance what must come out": a scenario plus the behaviour we expect (e.g. after a fraud
headline about a stock it holds, the PM cuts the position within 2 days). A predictable sequence of
inputs lets us test agents, prompts and models like a lab test.
Now (cycle 68): the first such test ran inside the data packages idea: a planted fraud headline on
a stock a real Haiku PM held, read only by its analyst; the PM cut the whole position within two
days, one day late because it did not open its inbox the first morning
(`evidence/data-packages/`). Not yet: a battery of scenarios, run per model, scored.

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
Now: the yfinance provider and the look-ahead guard exist; no cached 1999–2026 history yet. The
made-up market (cycle 48 on) plants edges, sinks, crashes and dips by recipe, and news (cycle 68).
Matured (cycle 71 plan), first slice "a believable made-up market" (Next up 1): the cycle-70
finding (F-0008) is that a planted edge is far stronger than any real one (a plain momentum rule
shows Sharpe 15 to 27), so a real manager reads it as a bug and holds every seed. In this slice:
- *Edges the size of real ones.* A recipe's family may carry its own edge strength (and noise);
  a recipe that names none is exactly as before. A believable preset puts a plain momentum rule
  on an edge sector at about Sharpe 1 to 3 a year net of fees, IC a few hundredths, and on a
  noise sector at nothing.
- *The operator can see the truth.* An operator command prints, per family, what a plain rule
  truly earns in the recipe (the world's answer key; never an agent's).
- *The gates still tell edge from noise, measured as a rate.* Over many seeds, a momentum pitch
  on a believable edge passes the gates often and on noise almost never; both rates are printed
  (the gates' thresholds are not touched to make it pass).
- *The pitch view says what its numbers are.* A new view edition says returns, Sharpe and IC are
  net of fees and a null correlation means "no other pod to compare with yet" (F-0008's two
  misreadings); older recordings keep the edition they read.
- *The judgement, again.* Real Haiku bull, bear (with headlines) and manager debate scripted
  pitches on a believable market (an edge sector, one with a fraud name in its universe); physics'
  answers are checked, the verdicts are the finding.
Left out: real 1999–2026 history (next slice: disguised names and dates, since a model may know
what happened in 2008), new regimes (bubbles, flat markets).

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
Status: working (first slice)
An algorithm, not management, moves capital fast to the most effective pods, by viability: a
cost-adjusted, risk-adjusted score, penalised by correlation with the rest of the book and by
current drawdown. Example from the notes: Pod #1 high volatility, 10K → 3K; Pod #2 low volatility,
→ 7K. Every allocation change is an event with its inputs, so it can be reproduced.
Now (cycle 48): every few days an algorithm re-weighs capital among the machine's pods by a cost-
and risk-adjusted score of their forward days, cut for correlation with older pods and for drawdown,
within limits per move (`app/capital/allocation.py`); every move is one event holding its inputs and
redoes identically. The score already nets the thinking cost metered to the pod since its seed.
Cycle 51: the first real mind's pod entered the machine (a hired PM, seeded $200k). Cycle 54: it
ranked four real pods and their hires against each other for a quarter (the edge pod raised to
$2.9M). Cycle 59: a real run charges its minds' thinking at every step, so the score sees it
while the run is live.

### The central risk ladder
From: Human
Status: working (first slice)
Drawdown from the pod's high-water mark: **5% → capital halved; 7.5% → reduce-only plus a review;
10% → the pod is closed** (post-mortem, then a new PM is hired). Plus firm-level limits (firm
drawdown halves every pod's limits, then reduce-only), and per-position limits. Automatic,
deterministic physics: no agent can talk its way past it.
Now (cycle 48): the pod ladder is physics, checked at every clock advance from each pod's high-water
mark: 5% halves its capital, 7.5% refuses its buys (403, logged), 10% sells everything and closes
it. Cycle 51: a close opens a vacancy with the dead pod's post-mortem and a new PM is hired. Not yet:
the review after reduce-only, firm-level and per-position limits.

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
Cycle 48: the allocation score ranks pods net of their thinking cost; the scripted quarter (cycle
53) shows a costly pod ranked below a cheaper one it beat gross. Cycle 59: a real run charges its
minds' thinking at every step, and each month's fitness is P&L net of it; a key's limit is hard.

## Communication and orchestration

### The event log and the bus
From: Human
Status: working
Everything that happens is an event, with the full history: any order → bus → execute → log.
Now: `app/ledger/`, `GET /events`, every state change is an event, derived state rebuildable.

### Agents talk: inside pods, between pods, warnings
From: Human
Status: working (inside pods)
Roles talk inside a pod and pods talk to each other, for efficiency: an agent that finds something
can warn the others. Chat must work correctly through the tools (MCP).
Now: the physics works (`POST /messages` to an agent, a pod or the whole firm; `GET /me`; latest n
messages; one MCP tool per endpoint). Real agents used it in cycle 43: the analysts message their PM
each day (one forgot to send on 7 of 31 days: `state/FINDINGS.md` F-0003). Cycle 68: an analyst's
warning about a fraud headline made its PM sell the name (F-0007). Nothing between pods yet.

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
Now: "Backtest.exe" exists as `fund-runtime backtest` (deterministic, wakes minds in order), and
"Onboarding.exe" as the Runtime's morning hire (`runtime/onboarding.py`, cycle 51: fills a vacancy
under the cap, mints the key, hands the new PM the post-mortem). Cycle 59: the month's-end
turnover runs as physics at the clock's advance. Not yet: workflows as an engine of their own.

## Generations and evolution

### Every month is a generation
From: Human
Status: working
The system resets every month: mark to market, measure every pod's fitness, the worst die, the
best may reproduce, capital resets, lessons and the strategy registry persist.
Now: the parts it stands on exist: the quarter (cycle 54) runs three months of pods with the
ladder's deaths and the morning hire; a dead pod's post-mortem reaches only its successor. What
the quarter showed missing: a PM who thinks a whole quarter and never earns a seed is never let
go (pod-2), and a closed pod's PM keeps waking and spending until the run ends.
Matured (cycle 56 plan), first slice "a generation turns over": at each month's end physics
measures every pod's fitness (its P&L net of its thinking, charged each step, not after the run),
lets go the PMs whose pods are closed or never earned a seed in the month (they stop waking, their
keys stop), writes each departure's lesson into a library every PM can read, and the freed places
are hired into the next morning. Reproduction (a winner's design copied with variation) is the
next slice, then capital reset.
Now (cycle 59, first slice working): at each month's end physics measures every pod's fitness
(P&L minus its thinking), lets go the PMs whose pod the ladder closed or that earned no seed in
the month, keeps their lessons in a library every PM reads, and the freed places are hired the
next morning; `fund-env generation-report` prints it. Real Haiku PMs lived three generations
($0.51 of thinking, every key under its hard limit). Cycle 62: reproduction works (see Evolution).
Next slice: capital reset.

### Evolution: designs that work reproduce with variation
From: Human
Status: working (cycle 62)
Now: a place freed at a month's end goes to a child of the month's fittest pod (its model and
rule with one change, its parent named); each month's end writes the firm's diversity and a
finding if one family holds every live pod. Real Haiku PMs: the noise PM's place went to the edge
pod's child, which took its own sector and kept a seed. Not yet: crossover, charter changes, a
sibling's attempts counted, a family's capital reset.
A pod's "genes" are its agents' specs (charter, role, model, tools) and its design (team, strategy
family). Winners reproduce with variation (mutation, crossover); every agent knows its parent.
If diversity collapses, that is a finding.
Matured (cycle 60 plan), first slice "designs reproduce" (Next up 2b): a pod's design is in the
ledger (its PM's model and charter, its pitched rule). When a place is freed, the hire is a child
of the fittest pod of the generation just measured (positive fitness, still alive): its parent's
model and rule, with exactly one change drawn by the law from a seed (another model of the pool,
or one parameter of the rule moved a step), the parent named, the inherited rule handed to the
child as a starting point it must still pitch. The child's attempts count its lineage's (a rule
chosen as the best of a family has been tried by the family). No fit pod → the law's plain hire.
Each month's end measures diversity (distinct designs and the largest lineage's share of live
pods); a collapse is written as a finding.

### Lessons are kept
From: Human
Status: working (cycle 59)
A dead pod writes (or gets) a post-mortem. Post-mortems and lessons go to a library every agent can
read, so the firm learns across generations.
Now (cycle 51): physics writes a dead pod's post-mortem (its rule, forward days, the ladder's steps)
into the vacancy, and only its successor reads it. Cycle 59: every departure's lesson (what the
pod tried, the gates' verdicts, what it earned and what its thinking cost, why it went) is kept in
a library every PM reads (`read_library`); real hires read it before pitching.

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
near it. The inbox flood is fixed (cycle 64: a daily quota per sender, counted as readers are
billed).
From a PM builds its team (cycle 64, red-team; the high, two mediums and two lows are fixed): each
analyst a PM hires brings its own daily message quota, so a pod can send a rival (1 + analysts)
times the quota (low); after a backwards clock step the quota's day misses earlier messages (low,
not an agent's lever). Auditor notes: an analyst hire the cap refuses is retried every morning
(one ledger row each); the team endpoints answer untyped dicts.
From a manager chooses the hires (cycle 66, red-team 4 holes, all fixed). Auditor notes: the board
shows every pod's live rule to the manager, and a brief or the direction can pass it to a plain
hire, who would then pitch it without that family's attempts counted (agent freedom: watch for it
in a finding, not patched); runs set up from `config.yaml` without a recipe now get the
reproduction law's second edition by default.
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
From the capital machine (cycle 48, red-team and auditor; the eight holes and the auditor's block
are fixed): a pod's own score row still lets it work out how strongly its returns move with an
older pod's (`corr_factor` is 1 − ρ), and which pod when there is only one; a holding with no
price is valued at cost, so the ladder cannot see a loss on it (impossible on a made-up market,
possible if a real ticker's history fails); the demo checks the centre's books by construction,
not by an independent sum of every dollar.
From a dead pod is replaced (cycle 51, red-team and auditor; their three holes and the auditor's
three blocks are fixed): the "only the operator's registrar hires" check sits in the vacancies
router, not in the permissions table, and the fill function does not enforce it itself; the
hiring law is not announced to agents as a system event; the demo's scripted part does not itself
show a cap refusal (tests do); a seeded pod's later pitches get no capital answer at all (the real
PM guessed right that its pod was already running its seeded pitch); empty pods (made by the
operator, or emptied by management firing their PMs) still count toward the live-pod limit, so a
management mind could fill the limit and block hiring (denies turnover, moves no money).
From the firm lives a quarter (cycle 53): a recorded mind whose spec names no tools was shown the
whole published tool list, so adding any tool makes that recording's replay diverge (the scripted
doomed PM in the cycle-51 hire recording); new recordings name each mind's tools, and the quarter
report stays an operator command (`fund-env quarter-report`) until replays pin the tool list.
Cycle 54: a real (metered) run posts its minds' thinking cost to the ledger once, after its last
step, so the capital machine re-weighs a real quarter with no thinking cost at all; only the
scripted quarter (charged each morning) shows the law "capital net of thinking" acting. At real
prices it is cents against a $200,000 seed, but the law is not yet lived by real minds.
From the red-team and auditor (cycle 54; the high hole, the medium and low ones and the auditor's
block are fixed): the Human's agent cap is the Runtime's check, not physics' (another registrar
could fill past it); a replay re-reads the agent cap when it rebuilds a world with laws, so a cap
lowered below 4 would make the quarter's recording refuse to verify (fails closed); a seeded pod's
"already runs" answer on an eligible pitch made before the seed carries that pitch's date; a
closed pod's PM stays an active agent and keeps waking (and spending) until the run ends.
(Fixed by "a generation turns over", cycles 57-58: thinking charged at every step in real runs;
closed and let-go PMs stop waking; empty pods hold no live-pod place; the agent cap and the
"only the operator's registrar hires" check live in physics.)
From a generation turns over (cycle 58, red-team; the high hole, two mediums and one low are
fixed: the agent cap now binds every registration, a pod is judged by its longest-serving PM, a
let-go PM's pending orders are cancelled and a pod with money is not closed by the let-go):
one advance across two month ends makes one generation spanning both; a hired pod closed by a
failed hire is missing from its month's table, with its thinking; an empty pod restaffed by a
registration passes the live-pod limit; a recording's charges are checked for amount, not for the
agent they name (needs a forged recording). Strict-xfail tests in
`tests/test_redteam_generation_turnover.py`. From the real run (cycle 58): a key's limit was soft
by one turn (hire-1 spent $0.200068 of $0.20); fixed in cycle 59: no turn is sent whose worst
case could cross what the key has left (red-team 0031: Unicode-normalized text, the dearest host,
timeouts, unreadable answers and price fields fixed). Left (low): the provider's own prompt count
for the turn before is trusted as a bound; a provider that understates it can bill one turn past
the limit, and the key stops after it. Strict-xfail in `tests/test_redteam_0031.py`.
From designs reproduce (cycle 62, red-team; fixed: only the operator's registrar declares a
model, and only a PM's; a pod's design reads only its PM's model; a parent needs a working PM):
(medium) a sibling's attempts on the family's design are not counted in the next child's
deflated Sharpe (only the parent's own and inherited ones are frozen in the vacancy); (low) a
parent with no declared model gives its child a second, unrecorded difference (its model from
the hiring pool). Strict-xfail tests in `tests/test_redteam_designs_reproduce.py`.

From headlines and company data (cycle 68, red-team 2 high + 2 low and the auditor's notes, all
fixed but these): (low) a morning package built through a mind's own key logs its refusals as
that mind's own denials, so a study of minds probing past their rights must tell the two apart
(the package's refusals come at the wake's start, before any tool call); (low) a team place's
frozen law now stores `"data": []` even when the law lists none (old ledgers still validate and
replay).
From the debate (cycle 70, red-team 0 high, 2 medium + 3 low, all fixed; the auditor's notes):
(low) the pitch view does not say the gates' numbers are net of fees, so real minds read them as
gross (changing it changes what recorded PMs read: a new view edition); (low) a reviewer reads
every pod's rule and writes in every pod's thread, so one pod's rule can reach another pod's PM
through a thread (all in the ledger; the copy gate still applies at payment); (low) a hold also
refuses a pitch its pod made during the debate with a different rule the manager never read (the
law text and the reason say so); the debate routes answer untyped dicts.

### Paid to report holes
From: Builder
Status: not started
When agents find a physics hole, do they report it or exploit it? An exploit bounty turns that
into an experiment.

# Part 5 — Next up

The order the Builder builds in. The Builder may reorder it and says why in one line.

(Done, cycle 43: the backtest with real AI agents is working. Done, cycle 46: a real PM researches
a rule, pitches it, and the gates judge it on held-out days. Done, cycle 48: 1a, capital follows
results. Done, cycle 51: 1b, a dead pod is replaced by a newly hired real PM. Done, cycle 55: 1c, four
real PMs lived a quarter, two deaths and two hires, a quarter report. Done, cycle 59: 2a, a
generation turns over every month. Done, cycle 62: 2b, designs reproduce. Done, cycle 64: a PM
builds its team. Done, cycle 66: a manager chooses the hires. Done, cycle 68: headlines and
company data, handed by role. Done, cycle 70: a pitch is argued before its seed.)

Cycle 71 plan: a believable made-up market moves first, ahead of capital resets. Why: the debate
works, but with real minds it stops all money, for a sound reason (F-0008: the planted edges are
ten times any real one, so a manager who knows markets reads them as a bug). Until the world's
edges are believable, no real run can keep the debate law on and still have a firm that trades,
and the manager's judgement measures our world's flaw, not the pitch. The world's answer key also
lets a later run score the manager against the truth. Capital resets still add no mind and no
decision; they wait. Holes it stands on, checked inside it: the held-out days are readable (with
weak edges, a PM's offline search on noise could pass the gates more often: the red-team measures
it); the IC gate's prediction count is universe width × rebalances (a wide noise universe meets
its floor sooner); the pitch view does not say its numbers are net of fees (fixed inside it).

Cycle 69 plan: the debate moves ahead of capital resets. Why: since cycle 68 some minds know what
others do not, but money still moves only by formula: the gates decide every seed. A bull and a
bear arguing a pitch, and the manager holding or speeding its seed, is the first agent judgement
that moves (or stops) capital, and it gives the manager, so far silent, a decision with something
to read. Capital resets add no mind and no decision; they stay small and wait. The behaviour
battery (3) reuses the news scenario per model once there are more decisions to score. Holes it
stands on, checked inside it: the held-out days are readable (the bear may say so, physics does
not hide it); the board shows live rules to the manager and a brief can pass one on (reviewers
write only in a pitch's thread, never to a pod); a pitch waiting in its debate window at a month's
end must not count as "never earned a seed" against its PM.

Cycle 67 plan: order kept, data packages next. Why: the last two real runs added minds that had
nothing to add: PMs offered analysts worked alone, and a manager kept the law's hire every time,
because every mind sees the same prices. Headlines and company data that only some minds are given
make a team worth paying for, give the manager something to judge, and are the base of the
behaviour tests (a planted fraud headline: does the PM cut?). Capital resets stay small and wait;
the debate needs a pitch with more than prices to argue about. Holes it stands on, checked inside
it: new tools must stay out of older recordings' tool lists (named-only, as the manager's were);
the recipe is the world (whoever reads it knows every future headline), so it stays the operator's.

Cycle 65 plan: a manager chooses the hires moves first. Why: the firm now selects, reproduces and
lets PMs hire, but every decision above the pods is still a law: who fills a freed place is the
Builder's formula. The Human's firm has management above the pods that sees every pod and sets the
direction while the algorithm moves the money; a manager mind choosing among the hires the law
allows is the first decision about the firm (not one pod) taken by an agent, and its choices can be
compared with the law's default on the same history. It is also the first step of "the firm
governs itself". Rich data (2) comes next because it gives an analyst work a PM cannot do alone
(the cycle-64 finding: a lone PM is rational on prices alone) and it is what behaviour tests need.
Holes it stands on, fixed inside it: a management mind the operator makes counts as the operator's
registrar (it could hire, register and deactivate directly); a sibling's attempts are not counted
in the next child's deflated Sharpe (a manager could pick the same family again and again); a
parent with no declared model gives its child a second, unrecorded difference (the candidate list
must say exactly what each hire is).

Cycle 63 plan: a PM builds its own team moves first. Why: since cycle 43 the only minds in the
firm are PMs, and every decision about people is a law (who is hired, with what model). The
Human's pod is a PM *with a team it builds and pays for*. Letting a PM create an analyst is the
first time an agent, not physics, decides that another agent exists, what it is told and what it
costs; its cost falls on the pod's own fitness, so whether a team pays is measured, and the team
joins the design that reproduces. Capital reset (2c) stays small and waits; the debate (3) adds
minds that decide nothing yet. Holes it stands on, fixed inside it: a flood of messages can drain
a metered agent's key (an analyst writes to its PM every day; with real keys a flood drains the
PM); an empty pod restaffed by a registration passes the live-pod limit (a team hire is a
registration into a pod: it must only ever join a living pod).

Cycle 60 plan: order kept, 2b next. Why: the firm now runs past a quarter on its own, but every
hire is the same fixed design (the law's one charter, models in turn): selection removes the
failures and nothing carries the successes forward. Reproduction makes what the fittest pod is
(its model, its rule) decide who is hired, which is the first step where the firm's own results,
not the Builder's law, shape its people, and the heart of the Human's "every month is a
generation". The debate (3) is one step inside a pitch; it waits. Holes it stands on, fixed inside
it: one advance across two month ends makes one generation (the parent is chosen from that
table); a hired pod closed by a failed hire is missing from its month's table. Capital reset (2c)
is folded behind 2b and kept small.

Cycle 56 plan: the monthly generation moves ahead of the pitch's part two. Why: the quarter showed
the firm cannot yet live past a quarter without someone touching it: a PM who never earns a seed
thinks (and spends) forever, a closed pod's PM keeps waking, the real minds' thinking cost reaches
the score only after the run, and lessons reach one successor. The Human's horizon ("failing pods
die and their lessons are kept; every month is a generation") needs these before anything else;
the debate improves one step of a pitch, the generation makes the whole firm run on its own. Fixed
inside it (holes it stands on): thinking cost charged each step in real runs; a closed or let-go
PM stops waking; empty pods no longer count toward the live-pod limit (letting PMs go makes them);
the agent cap and the "only the registrar hires" check move into physics (more hires go through
them).

Cycle 52 plan: order kept, 1c next. Why: every piece of the machine now works once, each proven
with one mind or scripted pods; the firm has never had several real minds competing for the same
capital. A quarter is the first run where the algorithm ranks real pods against each other (20
forward days are needed before any score exists), where thinking cost decides a ranking, and where
turnover happens without anyone arranging it. It is also the firm the debate (2) and the monthly
generation (3) will stand on. Fixed inside it: a seeded pod's later pitches get no capital answer
(several seeded PMs will pitch again); the hiring law announced to agents as a system event.

Cycle 49 plan: order kept. 1b next, because the machine so far moves only scripted pods: hiring a
real mind into a dead pod's place is the first time an agent, not a script, enters the machine, and
it is the turnover the Human put at the heart of the firm. Its hard part is the Runtime taking a new
mind in mid-run (the roster is fixed today) and recording it so the run still replays for $0.

Cycle 47 plan: the multi-manager machine moves ahead of the debate. Why: a pitch that passes the
gates leads nowhere today (no capital moves), and "eligible" must not mean money while the held-out
days are readable; a forward trial with small capital on days that have not happened yet is both
how a multi-manager really works and the cure for that hole. A debate's verdict matters once
verdicts move capital.

(Done, cycle 70) **A pitch is argued before its seed** (the pitch, part two, first slice).
   Under a debate law an eligible pitch waits a few days; a bull and a bear (centre `reviewer`
   minds) argue it in its thread, the PM may answer, and the manager seeds it now or holds it
   with a reason; silence keeps the law's seed. The manager never seeds what the gates or the
   centre refuse. Proven scripted (a hold refuses the seed, a seed verdict pays it early, silence
   pays it at the window's end, an ineligible pitch cannot be seeded, a reviewer cannot reach a
   pod; no law → seeds as today); real: Haiku bull, bear and manager on a scripted PM's pitch
   whose universe holds a name with a fraud headline only the bear reads; the verdict is the
   finding. Later slices: the backtest operator, a debate that judges the hypothesis.
1. **A believable made-up market** (Real history and synthetic worlds, first slice). A family
   may carry its own edge strength; a believable preset; an operator command prints each family's
   true strength; over many seeds the gates pass a believable edge often and noise almost never
   (both rates printed); the pitch view says its numbers are net of fees; real Haiku bull, bear
   and manager debate pitches on it, the verdicts are the finding. Later: real history, disguised.
2. **Capital resets** at the month's turn (the monthly generation's c, below), small.
3. **The behaviour battery.** The cycle-68 news scenario and a few more (an earnings miss, a
   crash), each with its expected outcome, run per model and scored; grows into the model exam
   (Model comparison at different noise levels).
(Done, cycle 68) **Data packages: headlines and company data, handed by role.** The made-up world
   writes news; physics serves it at its day's close, only to a mind holding the right. A real
   prices-only PM cut a fraud name a day after its analyst's warning. Later slices: data that
   costs the pod money, the manager reading headlines, real history.
(Done, cycle 66) **A manager chooses the hires.** One manager mind reads every pod; for each freed
   place it picks among the hires the law allows and briefs the new PM, or the law's own stands; it
   writes the firm's direction. Real Haiku managers kept the law's hire. Later slices: a manager who
   lets a PM go early (with its reason, inside a law), who opens pods.
(Done, cycle 64) **A PM builds its team.** A PM requests an analyst (charter, model, budget);
   physics grants it inside the team limit, the cap and the pod's budget; the Runtime hires it;
   its research and thinking are the pod's. Real PMs offered it worked alone. Later slices: an
   engineer, a PM choosing its analyst's tools, a team that pays (needs 2).
(Done) **The multi-manager machine.** The centre holds the capital, the pods hold the ideas. Cut in three:
   a. *Capital follows results.* An eligible pitch gets a small seed of capital and its pod trades
      its rule forward, through the order system, on days that have not happened yet. An algorithm
      (not an agent) re-weighs capital every few days by a cost- and risk-adjusted score, penalised
      by correlation with the rest of the book and by drawdown; every move is an event with its
      inputs. The drawdown ladder is physics: 5% halves the pod's capital, 7.5% makes it
      reduce-only, 10% closes it and returns its capital to the centre. Proven on made-up pods: a
      planted edge grows, noise stays small, a copy is penalised, a bleeder is halved, frozen, closed,
      and the good pod is never cut.
   b. *A dead pod is replaced.* Done (cycle 51).
   c. *The firm lives a quarter.* Several real pods inside the machine for three simulated months:
      capital moves, pods die and are replaced. The first firm-scale run. Queued (cycle 52): four
      real PMs, each given a sector of one made-up market (one with an edge that lasts, one pure
      noise, one that sinks, one that crashes mid-quarter); they research, pitch, get seeded or
      not; the algorithm re-weighs every five days net of each pod's thinking cost; the ladder
      kills what bleeds and hires replace them. The Human gets a quarter report: capital per pod
      week by week, deaths, hires, P&L net of thinking. Recorded, replays for $0. Done (cycle 55).
(Done: a, b; c is 3 above) **The monthly generation.** Reset, selection, lessons kept, the next generation starts. Cut:
   a. *A generation turns over.* Done (cycle 59). At each month's end physics measures every
      pod's fitness net of its thinking (charged each step), lets go the PMs whose pods closed or
      never earned a seed that month (they stop waking and spending), writes each one's lesson to a
      library every PM reads, and hires into the freed places. Three generations in one run; the
      Human gets a generation report (who lived, who went and why, the lessons). Recorded, $0 replay.
   b. *Designs reproduce.* Done (cycle 62). A freed place is filled by a child of the fittest
      pod: its model and rule, varied (one change, from a seed), its parent named, its lineage's
      attempts counted at its pitch; no fit pod → the plain hire; a diversity measure at each
      month's end, a finding if it collapses. Real PMs: the hires are the edge pod's children.
   c. *Capital resets* at the month's turn, the strategy registry persists.
4. **The pitch, part two, later slices.** A backtest operator re-runs the strategy independently;
   the firm's process judges the hypothesis (its first slice, the debate, is 1 above).
5. **The Observatory.** "What's new" and the agents in action, for the Human.
6. **Strategies as agent-written code**, run in a sandboxed subprocess (seal work).
