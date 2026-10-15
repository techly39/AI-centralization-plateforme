# 05 — The Eras: the path of the factory

Living book. Each Era has a **scientific question**, **deliverables**, and **exit
criteria**. An Era is finished only when every exit criterion is verified by a test or
a recorded experiment.

```
 ┌──────────── LAUNCH PAD (follow in order) ────────────┐   ┌──── AUTHORSHIP (yours) ────┐
  Era ½ Survey  →  Era I The Desk  →  Era II The Firm        Era III … VI = suggestions
                                                             + Eras you invent
 └────────────────────────────────────────────────────────┘   └────────────────────────────┘
                          Era ∞ (the factory improving itself) runs alongside everything
```

**During the Launch Pad:** Eras are followed in order; the Builder never starts Era N+1
work while Era N exit criteria are open — except bug fixes and research tooling that
serves the current Era. The point is to get your hands on the system.

**After the Launch Pad:** the Builder owns the roadmap (`01_GENESIS.md` §6). Eras III–VI
below are the Human's suggestions — follow, reorder, merge, replace, or discard them, and
write new Eras in this book with the same structure (question, deliverables, exit
criteria). Record every roadmap change in `07_DECISIONS.md` and the vision behind it in
`bible/09_BUILDER_VISION.md`.

If `governance/human.yaml: approvals.era_gates` is `true`, the Builder stops at each
Era boundary, writes `state/ERA_REVIEW.md`, and waits. If `false`, it continues.

---

## Era 0 — Foundation ✅ (done before the Bible)

TRD Phases 0–2: skeleton, ledger, registry, auth, permissions, OMS, market data, bus,
costs, metrics, MCP. 218 tests green at Bible writing. ~~Phase 2 is uncommitted in git.~~
*(Survey correction, cycle 8: Phase 2 committed in cycle 1; at the Survey the suite was
276 collected = 267 passed + 9 strict xfails, the xfails being open red-team holes —
`state/SURVEY.md` §2b. The Phase 2 milestone was met by a hand-written script, not an agent
(§4b.2).)*

---

## Era ½ — The Survey (the first run: clean and understand) ✅ (cycles 1–9)

**Question:** what exactly are we working with — what exists, what works, what is
broken, what is dead, and what in the Bible is wrong about it?

The first cycles build **no new features**. They read, run, inventory, clean, and correct.

Deliverables:
1. **Toolchain inventory:** versions of macOS, `uv`, Python, Node, `openclaw`, `claude`,
   git remote state. Whether the API starts (`uv run fund-env serve`) and the MCP server
   connects.
2. **Repo survey:** read every file in `app/`, `mcp_server/`, `tests/`, `scripts/`,
   `migrations/`, `docs/`, `legacy/`. Map what exists to the TRD and the Bible. Run the
   full suite. Note dead code, duplicates, stale docs, odd files (`test_api.py` at root,
   empty `ui/`, `.DS_Store`, `legacy/` POC), and gaps.
3. **Git hygiene:** commit the uncommitted Phase 2 work as its own commit, then the Bible
   + harness as another; push to `origin`. Check `.gitignore` covers secrets and runtime
   artefacts.
4. **Cleanup:** only deletions, moves, renames, doc fixes, `.gitignore`, formatting —
   each with a reason in the commit message. Anything bigger becomes a backlog item.
   `legacy/` stays as an archive unless there is a reason.
5. **OpenClaw survey (read-only + backup):** follow `08_OPENCLAW.md` §1–2: back up
   `~/.openclaw`, record the version and the docs for it in
   `runtime/openclaw/VERSION_NOTES.md`, list existing agents/bindings/models (no secrets),
   inventory the OCT POC agents and workspace files. Change nothing in OpenClaw yet.
6. **Bible correction:** wherever the Bible is wrong about reality (paths, counts,
   versions, OpenClaw details), fix the living books (02–08) with a logged decision; for
   protected books, write `state/PROPOSALS.md`.
7. **`state/SURVEY.md`:** what exists · what works (with evidence) · what's broken ·
   what's dead · risks · surprises · what this changes in the backlog.
8. **First ideas:** seed `state/IDEAS.md` with what the survey made you think.

Exit criteria *(closed cycle 9 — evidence per box in `state/SURVEY.md` §10; ADR-021)*:
- [x] `state/SURVEY.md` complete with all sections above.
- [x] Phase 2 committed; `main` green; pushed.
- [x] Repo clean: no junk files, every odd file resolved or explained. *(Explained, not all
      resolved: `test_api.py` + `.vscode/` untracking waits on P-0002 — S-004b.)*
- [x] `~/.openclaw` backed up; `runtime/openclaw/VERSION_NOTES.md` written from the
      installed version's own schema (`openclaw config schema`) — the online docs only
      describe the latest release (cycle 8 correction, `08_OPENCLAW.md` §1). *(Reworded in
      cycle 8, inside its own Era, to be stricter; cycle 7's notes already met it.)*
- [x] Backlog re-ordered from the survey's findings.

---

## Era I — The Desk

**Question:** can one pod of AI agents run end-to-end through physics alone, in
compressed time, reproducibly, with real per-agent costs?

Deliverables:
1. Commit Phase 2; add `tests/test_boundaries.py` (dependency law, no LLM SDK in `app/`).
   *(Done: Phase 2 committed in the Survey; boundary test cycle 10, ADR-022.)*
2. Halt in physics (`governance/HALT` → agent writes refused; `GET /halt`).
   *(Done cycle 11, ADR-023: 423 + `halt_refused` event for every write, every role; monitor
   idle; `GET /halt` + MCP `get_halt`. The Runtime half — wakes stop within a tick — is B-009.)*
3. TRD Phase 3: simulated clock, `/clock/advance`, look-ahead guard, `run_id` scopes,
   allocation endpoint, meeting packages.
4. Truman v1: prices-only pack from cached real history + one scripted scenario;
   served through `MarketDataProvider`.
5. World events table; `system` announcements of law changes.
6. Runtime v1: AgentSpec, scheduler on the App clock, `daily_cycle` + `backtest`
   workflows, cassette recording, halt checks.
6b. `openclaw` adapter built to the standard in `08_OPENCLAW.md`: generated config,
   per-agent workspace/agentDir/auth/MCP, deny-by-default tools, no bindings, OCT POC
   charters turned into AgentSpec templates, and the conformance suite
   (`fund-runtime openclaw doctor`).
7. Metering v1: per-agent provisioned keys, cost-sync job → system-reported costs.
   Built and tested against a fake provider if no provisioning credential exists.
8. Verify the "chat restricted to central pod" report with two pods.

Exit criteria *(from cycle 37 served by missions in `state/missions.json`, ADR-042; before that the
plan was ADR-032 — every criterion below is served by at least one backlog slice R-1…R-8. The first two
criteria and the live half of the last one are ticked only by real minds, at R-8. The other four are
test criteria and may be met by tests using scripted or fake providers)*:
- [ ] One pod (PM + Analyst) completes a 1-month backtest via the Runtime in < 10 min
      real time, every action through the App.
- [ ] Replaying that run from cassettes reproduces an identical event ledger (except ids/
      wall-clock fields) at zero LLM cost.
- [x] Look-ahead guard has a test that an agent asking for tomorrow's price gets refused.
      *(Cycle 30, ADR-036: `test_ec3_*` in `tests/test_runtime_lockstep.py` — a conducted
      mind through the MCP tools: tomorrow's window 400, a window across now clipped, the
      clock not in its hand.)*
- [x] Every LLM dollar of the run is attributed to an agent via system-reported cost
      (or the fake provider in tests). *(M-001, ADR-044: `acceptance/M-001.py` — a two-mind pod
      lives a month on the fake metered provider under an injected cap; Σ provisioner == Σ ledger
      per-key max == Σ `GET /metering/agents`, exact; the self-report does not count. A real
      provider waits on the cap, Q-0001.)*
- [x] Creating `governance/HALT` mid-run stops the run within one tick (test).
      *(Cycle 30, ADR-036: `test_ec5_*` — the call in flight finishes; no further call, wake,
      advance or event.)*
- [x] `firm.monthly_llm_usd_cap: null` → Runtime refuses to wake agents (test).
      *(Cycle 30, ADR-036: `test_ec6_*` — a spending mind is never built, under null or a
      numeric cap until R-6. "Agents" = spending minds per Q-0005 answer B, pending the Human;
      an answer A re-opens this box. B-053: the CLI provisions before the gate refuses.)*
- [ ] OpenClaw conformance: 100% of static checks pass for every `firm-` agent; live
      probes pass once a firm budget exists. No agent woke without passing.

---

## Era II — The Firm

**Question:** can a firm with several pods, management, central risk, and algorithmic
allocation run for several generations without a human?

Deliverables: 3 pods + CEO + CRO + HR; risk engine (drawdown ladder, exposure limits,
reduce-only); allocation engine; generations + `generation_turnover`; `native` adapter;
Observatory read-only (TRD Phase 4) + halt toggle; `post_mortem` workflow +
institutional memory library.

Exit criteria:
- [ ] 3 consecutive generations run unattended in backtest mode.
- [ ] A forced-drawdown Truman scenario triggers 5% / 7.5% / 10% actions exactly (tests).
- [ ] Allocation changes are reproducible from logged inputs (test).
- [ ] Leaderboard ranks by cost-adjusted P&L with system-reported costs.
- [ ] Observatory shows feed, portfolios, leaderboard, events, generation timeline.

---

## ── End of the Launch Pad. Everything below is a suggestion. ──

The Human's ideas for where the world could go next. You own the roadmap from here
(`01_GENESIS.md` §6). Keep what serves your vision, change the rest.

---

## Era III — The Research Machine (suggested)

**Question:** can agents produce strategies that survive honest validation?

Deliverables: `quant/` strategy interface, backtester, sandbox; IC, DSR (true trial
count), capacity, correlation; Barra-lite factor model + attribution; validation gates
as physics; `pitch` workflow with Bull/Bear debate; Truman packs 2–4 (fake companies,
fake headlines, combined, noise levels).

Exit criteria:
- [ ] No pod receives capital without passing all gates (test that tries to bypass).
- [ ] DSR uses the App's trial count; a pod running 500 backtests is penalised (test).
- [ ] Attribution splits a pod's return into β / factors / timing / α on a known
      synthetic case with the right answer.
- [ ] At least one agent-generated strategy passes all gates on held-out data — or a
      documented finding explaining why none can yet.

---

## Era IV — Evolution (suggested)

**Question:** does the firm get better across generations by itself?

Deliverables: genome (AgentSpec + pod design), mutation/crossover, lineage, PMs build
pods and spawn workers paid from their budget, hiring/firing, diversity metric,
Bootcamp (10–15 regimes), Model Exam.

Exit criteria:
- [ ] 10 generations unattended across Bootcamp regimes.
- [ ] Out-of-sample fitness trend across generations measured against a frozen
      Generation-1 baseline, with confidence interval — improvement *or* a documented
      finding on why not.
- [ ] Lineage tree visible in the Observatory.
- [ ] Agent population limits respected under a test that tries to spawn without end.

---

## Era V — Society (suggested)

**Question:** what social structures emerge when agents can talk, trade information,
make deals, and write rules?

Deliverables: information market with internal credits, reputation, contracts,
richer meetings, laws table + law process, social-graph and behaviour detectors
(collusion, information hoarding, manipulation, deception between agents).

Exit criteria:
- [ ] Laws proposed by agents take effect through the law process (test + live run).
- [ ] Detectors run every generation and write candidate findings automatically.
- [ ] `state/FINDINGS.md` holds ≥ 10 evidenced society findings.

---

## Era VI — Civilisation (suggested)

**Question:** what happens with several firms and institutions in one world?

Deliverables: multiple firms in one simulated market; endogenous price impact (agent
orders move synthetic prices); an exchange, a regulator agent, an auditor agent;
inter-firm competition for a shared resource (talent pool, capital from simulated LPs);
bills to the Builder (`04_FIRM.md` §9).

Exit criteria are written by the Builder at the end of Era V, following this pattern,
and logged in `07_DECISIONS.md`.

---

## Era ∞ — The factory that builds the factory

Runs **in parallel** with every Era (during the Launch Pad, at most 1 cycle in 5; after it, as often as the Builder judges worth it):
- the Builder improves its own process: the cycle protocol, skills, helper roles and extra
  auditor/red-team checks in `protocol/` (P-0003; `.claude/` is sealed), test harnesses, the
  experiment runner;
- meta-metrics in `state/METRICS.md`: cycle success rate, regressions caught by the
  auditor, time and turns per cycle, test count and runtime, cost per experiment;
- the scale research program (`02_SCALES.md` §4);
- every improvement to itself is justified by a metric that moved.

There is no final Era. After the Launch Pad the Builder writes new Eras here itself,
whenever the prime rule says so: *what would make the experiment deeper, more truthful,
more capable — more never-seen-before — next?*
