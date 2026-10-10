# Requirements: AI Hedge Fund System

`[?]` = unclear in the original notes.

## 1. Ecosystem / Structure
- Build order: 1 Basic Workflow, 2 Evolution/Extendability, 3 Debate, 4 Human Control
- Work on the ecosystem first: completing nodes, capital allocation, evolution, cross-pod communication
- The APP is the centralized core of the ecosystem
  - Micro orchestration → AI architecture
  - Macro structure → APP
- POD HUB: everyone in the pod can see what the others are doing
- Event log: see everything happening + the history of every action
  - Uses the "Bus"
  - Any order → Bus → Execute
  - Bus → Log
- Orchestration layer: the engine that runs the workflow of any pod
  - Examples: Onboarding.exe, Backtest.exe, ...
  - It is the one that manages and calls Openclaw [?]
- The system resets every month

## 2. Pods and Roles
- POD = PM + Analyst + Analyst
- Manager sits above POD #1, #2, #3
- Management (CEO, vision of the firm) should be able to see basic data: cash, position (size & amount, ...)
- The AI needs:
  - System rules + dynamic rules
  - Tools provided
  - Dynamic allocation (move the money fast to the most effective strategies)
- Understand precisely a POD process (ex: Citadel, Millennium)
- The PM builds his own pod (with regulation from user/manager)
  - He must be able to build his own strategy
  - He has the people he wants
  - He can create agents
  - Roles in the pod: PM, Analyst, Analyst, Engineer
- The PM must first pitch his idea: [PM + backtest operator] + user
  - Then a comprehensive report on what he wants to do
- POD data tracked:
  - Performance
  - Job cost against return
  - Job cash attributed
  - Basic data: risk, cash burned, amount of jobs and type of job
- Adaptability: innovation, resilience (with adaptability)

## 3. Communication
- Between roles inside the PODs
- Between PODs
- Why communication between AIs: efficiency (if an AI finds out something happens, it can notify the others)
- Chat/MCP must work correctly
- Chat messaging currently seems restricted to the central pod only

## 4. App Backend
### File structure
- `api/`: one file per topic
  - The first knock: receives the HTTP request, treats it, checks it, then calls `registry/service.py` and `ledger/events.py`
- `registry/`: Security + HR, where everything is transferred safely
- `ledger/`: the record keeper
- `db/`: the door between the app outside and the storage

### Roles of the files
- `api/events.py`: the window, the clerk at the counter
  - Handles the HTTP request, checks permission, parses, hands back a response
  - Checks: is this a valid, allowed requester?
- `ledger/events.py`: the worker, the archivist
  - Reads from and writes to the log book
  - Called by `api/events.py`, not directly by the agent
- The window imports the worker when a "Get/events" request comes in

### Responsibilities
- Who's allowed → `permission.py`
- What gets saved → `service.py` / `events.py`
- URL & request management → api files
- Data storage → `fund.db` + `models.py`

### HTTP methods
- Get → Read
- Post → Create
- Delete → Delete

### Flow for [Get/Events]
1. Request arrives → `main.py`
2. Routed to the event window → `api/events.py`
3. Identity check → `registry/auth.py` + `service.py` → looks in `fund.db`
4. Check the rule book → `permission.py` → deny: not allowed
5. Denial written to the log book → `ledger/events.py`, then `fund.db`
6. A 403 is returned to the sender → `main.py` to the AI

### API permission flow (example: John-PM)
- John-PM makes a request
  - Name: John-PM
  - Credit: "Random API key specific to him"
  - Request: "Random request type"
- Checks, in order:
  1. Where do you want to go?
  2. Is the API key real (is it fake)? → `auth.py` (then the table)
  3. Are you allowed to do so? → `permission.py`
  4. If passed everything, then execute → the targeted script

### Database
- `fund.db` is not created yet; the app needs to run for it to be created
- It stores all info (11 tables)
  1. AI agent
  2. POD
  3. Events
  - ...

## 5. Strategy / Quant
- Build an approximation of the MSCI Barra engine (MSCI Barra itself isn't usable)
- An algorithm (not the management layer) handles the allocation of the PODs according to their [viability] [?]
  - Example: POD #1 (Vol: high, Cash 10K → 3K), POD #2 (Vol: low, Cash → 7K) [arrows unsure]
- The strategy must be transformed into a function, isolated for the backtests
  - Data 1999–2026 → [Strategy] → result
- Correlation: the strategy must not correlate with other PODs

## 6. Risk Management (Central Risk Control)
- 5% drawdown = Capital / 2
- 7.5% → [?]

## 7. Metrics
- β (Beta): exposure of the strategy to the actual market movement
- α (Alpha): the skill of the POD
  - The POD uses his skill → research to try to beat the market
- Example portfolio, 10K: 8K → S&P500, 2K → unknown solar energy company
  - β = overall expected return
  - α = skill developed by working on the strategy
- If the market (β) moves up 10%, the portfolio is expected to grow at minimum 10%; α can grow much more
- MSCI Barra determines α with more precision and shows each part of it
  - Example, 15% bonus: 10% β, 3% dangerous investments, 2% [manager only bought, ?], 0% alpha (only followed the trend)

## 8. Strategy Validation Checks
1. Economic hypothesis
   - Example: finding that 2 prices are correlated (gold market and oil tankers); there has to be logic behind it
2. IC measure (Information Coefficient)
   - Score of 1 = perfect market prediction
   - Score of 0.05 = exceptionally robust
   - IC of 0.03 ✓
   - Few orders and an IC of 3% ✗
   - The IC can vary across different types of market
3. Deflated Sharpe Ratio
   - SR = Return / Risk
   - Deflated = adjust the SR score according to the number of previous attempts
4. Capacity
   - From what amount of capital the strategy [kills itself] [?]
   - Diversification: if the IC stays the same across different stocks or currencies, it's good. Less important for us (not enough capital)
   - Frequency: many orders and an IC of 0.03 ✓
- Required metrics / agent allocation / backtest / ...

## 9. Backtesting
- Fictional data calendar (one month, for example)
  - Day J-1 → AI1 receives data X; AI2 receives data Y
  - Observe what comes out
- Goal: know in advance what must come out; create a predictable sequence of actions and test them
- The AI does not fetch data itself; it is given a predetermined data package, for example:
  1. Just the market prices
  2. Fake company data
  3. Fake headline + description
  4. Everything together
- Data table: days (Mon / Tue / Wed ...) × AAPL price, NVDA price, TSLA price, ...
- Idea: AI models could be tested
  - New models placed in simulations to see the return, with different degrees of [noise] [?]

## 10. Build Status
- Phase 0 complete
  - Skeleton of the system
  - Git initialization (also a project in GitHub)
  - API test working
- Phase 1 has been built
  - OMS [written "ONS"] migrated: the old system made to work for the new system
- Known to work
  - API skeleton
  - Database
  - Logging logic
  - OMS migrated: orders can be passed to it and it executes them
- Next: understand the goal of Phase 1 and make the AI work as simply as possible
- To see what is currently doable in Phase 1: check the chat "Assess AI hedge fund system"

## 11. Open Issues
- **Cost**: the whole fund uses one API key, not one per agent → the cost part is biased
  - Need a way to get every agent's cost
  - Find a way to have cost management, for future AI experiments
- **Chat issues**
  1. An agent can't know who he is (agent from system script) → add a "Get me" chat; check "Explain chat... system work..."
  2. No precise command to get "n" messages of history; it gives back the whole history
- Chat messaging seems restricted to the central pod only

## 12. Next Steps
- Test the chat
- Test the MCP; understand precisely how MCP works
- Check the new Phase 1 development
- Test/understand the API with a test (ask an API to work with it, ask a question)
- Install Git

## 13. Open Decisions
- Stay with the app × Openclaw, or transform it to manage a hierarchy / create my own AI architecture inside the app
