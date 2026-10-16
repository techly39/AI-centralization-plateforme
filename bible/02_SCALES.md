# 02 — The Scales of Intelligence

This project stacks several kinds of intelligence on top of each other. Most bugs,
most wasted money, and most interesting findings come from **putting a job at the
wrong scale**. The Builder must know at which scale it is working at every moment.

## 1. The stack

```
 S0  HUMAN ............ BYD — the scientist. Constitution, budgets, the switch.
      │  files only (bible/, governance/, state/), Observatory
 S1  BUILDER .......... Claude Code, headless loop on the Mac mini. Builds the world.
      │  code changes (= laws) and Truman scenarios (= world events). Never chat.
 ─────────────────────────────── the seal ───────────────────────────────────────
 S2  PHYSICS .......... app/  — deterministic. Ledger, OMS, clock, risk, allocation, halt.
      │  REST API / MCP — the only door
 S3  RUNTIME .......... runtime/ — deterministic. Scheduler, workflows, adapters, metering.
      │  wakes minds, assembles their context, hosts them
 S4  GOVERNANCE ....... CEO, CRO (advisory), HR — LLM agents with firm-wide read access.
 S5  PODS ............. PM, Analysts, Engineer — LLM agents (OpenClaw or native).
 S6  WORKERS .......... short-lived agents spawned by S5/S4, paid from their budget.
```

S2 and S3 contain **zero AI**. They are the parts of the world that must not have
opinions. S4–S6 are the subjects of the experiment. S1 is the experimenter's hands.
S0 is the experimenter.

## 2. Each scale

### S0 — Human
- **Objective:** learn; keep the experiment safe and pointed at the vision.
- **Can:** everything. Edits Constitution, Genesis, governance, budgets. Halts.
- **Interface in:** `state/NOW.md` + `state/PROGRESS.md` (shown in the Console), `state/QUESTIONS.md`,
  `state/PROPOSALS.md`, `state/FINDINGS.md`, the Observatory UI.
- **Interface out:** editing `governance/human.yaml`, creating `governance/HALT`,
  answering in `state/QUESTIONS.md`, editing the Bible.

### S1 — Builder (Claude Code)
- **Objective:** the Builder's paperclip — a more capable, more truthful world, every cycle.
- **Can:** after the Launch Pad, decide the direction of the whole project
  (`01_GENESIS.md` §6); write any code outside protected paths; run tests, experiments, backtests;
  spawn its own subagents (`.claude/agents/`); create skills and commands for itself;
  read the web; push to `origin`; edit Bible books 02–09 with a logged decision.
- **Cannot:** participate in the firm (Constitution Art. 10); touch protected files;
  raise caps; contact anyone.
- **Memory:** it has none between sessions except files. `CLAUDE.md` (auto-loaded),
  `state/STATE.md`, `state/JOURNAL.md`, git history.
- **Strengths:** writing and refactoring code, tests, reading docs, careful local reasoning.
- **Weaknesses to design around:**
  - finite context → state files and a short handoff (`state/PROGRESS.md`), never rely on
    "remembering";
  - drift over many sessions → planning sessions with the runner's numbers, Genesis re-read;
  - judging its own progress too kindly → "done" is an acceptance check run by the runner, out of
    band; the `validator` runs, the `auditor` reviews; Constitution Art. 9 (ADR-042);
  - over-building and under-building → one mission at a time, each a capability someone can run,
    ideas from `bible/IDEAS_BOOK.md`, each built until its demo works (`protocol/CYCLE.md`).

### S2 — Physics (the App)
- **Objective:** none. Physics has no goal; it enforces laws and records everything.
- **Is:** the existing `app/` — FastAPI + SQLite + SQLAlchemy, event-sourced, injected
  clock, permission matrix, OMS, bus, metrics, MCP wrapper. Governed in detail by
  `TRD_ai_fund_environment.md` where the Bible is silent.
- **Rule:** if something must be true no matter what an agent says, it lives here.
  Risk limits, budget limits, allocation math, validation gates, halt, look-ahead guard.

### S3 — Runtime
- **Objective:** none. It is the nervous system: it decides *when* a mind wakes up and
  *what it sees*, never *what it thinks*.
- **Does:** ticks with the App clock; runs workflows (Onboarding, Pitch, Daily Cycle,
  Backtest, Meeting, Generation Turnover); assembles context packages; hosts minds
  through adapters; provisions per-agent metered keys; records every LLM exchange.
- **Adapters:**
  - `openclaw` — renders the agent's OpenClaw workspace and config from its AgentSpec,
    points it at a `fund-env-mcp` process carrying its own API key, and wakes it through
    the installed version's supported mechanism. Used for long-lived, personality-rich
    agents and for everything the OCT POC already proved. **Must meet the standard and
    pass the conformance suite in `08_OPENCLAW.md`.**
  - `native` — a code-spawned agent loop (Claude Agent SDK or an OpenAI-compatible
    loop) using the agent's metered key and the same MCP tools. Used for anything
    spawned programmatically, in bulk, or in compressed backtests.
  - Both adapters expose the **same tools** (the App's MCP) and obey the same budget.

### S4 — Governance agents
- **Objective:** the firm's paperclip, firm-wide.
- **CEO:** sets firm direction, approves pitches (once the Human delegates it), proposes
  firm laws, hires/fires PMs within rules. Sees cash, positions, metrics of all pods.
- **CRO (advisory):** reads risk, writes warnings, proposes limit changes. The *actual*
  risk limits are physics (S2). The CRO can't override them.
- **HR:** onboarding packages, agent directory hygiene, post-mortems for dead pods.
- **Not** an allocator: capital allocation is an algorithm in S2. Governance may only
  propose changes to the algorithm's parameters through the law process (`IDEAS_BOOK.md`, society).

### S5 — Pod agents
- **Objective:** the pod's share of the firm's paperclip — and survival.
- **PM:** owns the strategy, the team, the budget, the orders. Builds the pod.
- **Analysts:** research, signals, data work, theses.
- **Engineer:** turns the strategy into a function (`quant/` interface), runs backtests.
- Strategic choices that are *theirs*: which model each member uses (cost vs. quality),
  how many workers to spawn, what to research, whom to talk to, what to keep secret.

### S6 — Workers
- Short-lived minds spawned by a PM (or governance) for one job: "read these 40 filings",
  "stress-test this thesis", "write this feature". They report and die.
- Every worker has a parent, a budget drawn from the parent's pod, and a lineage record.

## 3. Rules between scales

1. **No skipping the seal.** S1 never talks to S4–S6 as a participant. It changes their
   world only through physics changes (announced as `system` events) and Truman world
   events. It reads their behaviour only through the ledger, the bus, and recorded LLM I/O.
2. **No impersonation.** No scale acts under another's identity. One API key = one identity.
3. **Judgment up, enforcement down.** LLMs decide; deterministic code enforces. If a
   rule matters, it is code in S2, not a sentence in a prompt.
4. **Cost flows down, attribution flows up.** Every token is charged to the agent that
   spent it, its pod, its generation, and its lineage.
5. **The Human sees everything.** No scale can create a channel S0 cannot read.

## 4. Studying the scales (a standing research program)

Learning how these scales behave is one of the project's goals, not a side effect.
The Builder keeps this program alive and records results in `state/FINDINGS.md` with
the tag `[scale]`.

Standing questions:
- **Model swap:** same pod design, same Truman scenario, different model per role.
  What does a stronger PM buy versus a stronger analyst? Where is intelligence wasted?
- **Cost frontier:** return per dollar of tokens, per role, per model tier.
- **Horizon:** how many sim-days can an agent keep a coherent thesis? Where does memory fail?
- **Coordination:** at what team size does communication cost exceed its benefit?
- **Adapter effect:** same agent spec under `openclaw` vs `native` — does the host matter?
- **Builder scale:** which kinds of missions does the Builder finish within estimate, which
  fail, and why? (Measured by the runner: `$FIRM_HOME/metrics.jsonl`; cycles 0–36 in
  `$FIRM_HOME/metrics.jsonl`.) What should be delegated to its subagents? What process change raised
  accepted missions per dollar?
- **Model exam:** a fixed battery of Truman scenarios with known correct behaviour, run
  against any new model before it is allowed in the firm.
