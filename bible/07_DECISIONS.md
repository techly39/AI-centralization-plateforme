# 07 — Decisions (ADR log)

Append-only. Every non-trivial choice the Builder makes — and every choice the Human
made — lives here. Format:

```
## ADR-NNN — <title>            (cycle N | human) — status: accepted | superseded by ADR-MMM
Question: …
Answer from the future: <which option keeps the door open to Era ∞, and why>
Consequences: …
```

---

## ADR-001 — Hybrid agent runtime   (human, 2026-10-11) — accepted
Question: stay App × OpenClaw, or build our own agent architecture? (Requirements §13)
Answer from the future: PMs will spawn and fire agents programmatically, populations
will reach hundreds, every agent needs its own key and budget. OpenClaw alone makes
bulk programmatic spawning awkward; dropping it throws away the working OCT POC.
→ The App stays physics. The Builder writes its own Runtime (`runtime/`) with two
adapters: `openclaw` (existing agents, long-lived personalities) and `native`
(code-spawned agents). Same tools, same keys, same budgets.

## ADR-002 — Builder autonomy: full loop   (human, 2026-10-11) — accepted
The Builder runs cycles headless and indefinitely on the Mac mini. Human gates only:
protected files, caps/limits, anything touching the real world. Era gates are off
by default (`approvals.era_gates: false`).

## ADR-003 — Firm LLM budget: unset until the Human sets it   (human, 2026-10-11) — accepted
`firm.monthly_llm_usd_cap: null`. While null, the Runtime refuses to provision keys or
wake firm agents. The Builder builds and tests everything against a fake provider and
cassettes. Asking the Human to set it goes in `state/QUESTIONS.md` when Era I needs a
live run.

## ADR-004 — Monorepo with enforced boundaries   (bible) — accepted
Supersedes TRD §12 "no agent code inside this repo".
Answer from the future: Runtime, Truman, Quant Lab and the App will evolve together for
years; one repo, one test suite, one history makes the Builder's loop simpler and
makes replays reproducible. The TRD's real concern — AI logic leaking into physics —
is enforced by `tests/test_boundaries.py` instead of by repo separation.

## ADR-005 — "Reset every month" = Generation   (bible) — accepted
A generation is a month of sim/calendar time: capital and positions reset, selection
runs, memory and lessons persist. Without heredity there is no evolution; without
reset there are no comparable experimental units. See `04_FIRM.md` §7.

## ADR-006 — Risk ladder 7.5% step   (bible) — accepted
Requirements left "7.5% → [?]". Chosen: reduce-only + mandatory review; 10% →
liquidate and close. Mirrors real pod-shop practice (cut, freeze, stop).

## ADR-007 — Per-agent cost via provisioned keys   (bible) — accepted
Requirements §11: one shared key makes cost biased. Each agent gets its own provisioned
OpenRouter key with a credit limit; a cost-sync job posts usage as the `system` agent,
which is authoritative over self-reports. A local meter proxy is deferred to Era III+.

## ADR-008 — LLM cassettes for replay   (bible) — accepted
LLM calls are nondeterministic; science needs replay. Every agent LLM exchange is
recorded and linked to events. Replaying a run from cassettes must reproduce the ledger.

## ADR-009 — TRD remains authoritative for physics details   (bible) — accepted
For anything inside `app/`, follow `TRD_ai_fund_environment.md` unless the Bible or a
later ADR says otherwise. TRD Phase 3 = Era I; TRD Phase 4 = Era II (Observatory).
TRD §12 "no evolution logic in the app" is refined: evolution *decisions* live in the
Runtime workflows; the *enforcement* (budgets, lineage, population caps, allocation)
is physics.

## ADR-010 — Validation gates and allocation are physics   (bible) — accepted
Agents would otherwise argue their way past them. Judgment (hypothesis quality,
debate) is LLM; thresholds and money movement are code.

## ADR-011 — Requirements `[?]` items   (bible) — accepted
Resolved in `04_FIRM.md` §11.

## ADR-012 — Launch Pad, then authorship   (human, 2026-10-11) — accepted
The Eras are the launching pad, not the destination. Survey + Era I + Era II are followed
in order so the Builder gets its hands on the system. After that the Builder has full
control of the roadmap, architecture and stack (inside the Constitution) and is expected
to come up with its own ideas — the most efficient, complex, impressive, never-seen
system it can build. Eras III–VI become suggestions. Refines ADR-009: the TRD's "fixed
stack" binds only during the Launch Pad.

## ADR-013 — The first run is a Survey   (human, 2026-10-11) — accepted
Before any feature: clean and understand what exists (repo, toolchain, OpenClaw, OCT POC),
commit Phase 2, correct the Bible where it is wrong, write `state/SURVEY.md`. Era ½.

## ADR-014 — OpenClaw agents must be set up perfectly   (human, 2026-10-11) — accepted
A misconfigured agent invalidates experiments (web access = look-ahead leak; shared auth =
false costs; shell = seal breach). Standard + conformance suite in `08_OPENCLAW.md`; no
agent wakes without passing. Verify against the installed version's docs, never memory.
Never touch the Human's non-`firm-` agents.
