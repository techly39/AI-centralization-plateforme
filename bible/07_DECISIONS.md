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

## ADR-015 — Red-team holes are recorded as strict xfail   (builder, cycle 1) — accepted
A hole found by `red-team` becomes a test marked `xfail(strict=True, reason="red-team NNNN: …")`
plus a backlog item. Keeps `main` green without hiding anything: the hole is visible in every run
(`-rx`), and the fix must remove the marker (strict → an unexpected pass fails the suite).
Alternative rejected: leaving red failing tests on the branch → the cycle could never merge.

## ADR-016 — Concurrency tests run on a file-backed DB   (builder, cycle 1) — accepted
The suite's StaticPool in-memory engine shares one connection across threads, which production
never does; concurrency tests override `engine` with a tmp_path SQLite file (one connection
per thread). Evidence: StaleDataError flake ~1/3 runs → 0/40. See F-0001.

## ADR-017 — Messaging and self-reporting are universal permissions   (builder, cycle 1, ratifying Phase 2) — accepted
Phase 2 grants READ_MESSAGES, REPORT_COST, REPORT_TASK to every role via `_UNIVERSAL`
(`app/registry/permissions.py`), extending TRD §6. Every agent must read its inbox and report
what it spent; denying either to a role would only create unmetered agents. Flagged by the auditor.

## ADR-018 — Token counts are capped per report and summed with TOTAL   (builder, cycle 2) — accepted
`POST /costs` (and the MCP tool, and `report_cost` in-process) refuses `tokens_in`/`tokens_out`
above `MAX_TOKENS_PER_REPORT` = 100,000,000 (`app/metrics/reporting.py`). One report is one unit
of work; 1e8 is ~100 full re-reads of a 1M-token context, so no honest report hits it. Pod token
totals are summed with SQLite `TOTAL` (float, never raises) instead of `SUM` (raises on int64
overflow). Two walls because the red-team showed one agent could 500 the leaderboard for the whole
run with two reports (F-0002, B-000c). Cost: totals above 2⁵³ tokens round. Alternatives rejected:
summing in Python (loads every row); a cap alone (a future in-process writer could still bypass it).

## ADR-019 — Firm agents live in their own OpenClaw profile   (builder, cycle 7) — accepted, verify in B-012
The firm's OpenClaw agents go in a separate profile (`openclaw --profile firm …` → state and
config under `~/.openclaw-firm`), not in the Human's `~/.openclaw/openclaw.json`. Why: in the
installed 2026.5.12 several seal keys are **global only** — `tools.web.*` (search + fetch are
on for every agent today), `tools.profile`, `tools.sessions.visibility`, `tools.agentToAgent`,
and `mcp.servers` (no per-agent MCP key) — and the Human's bots need them as they are
(`runtime/openclaw/VERSION_NOTES.md`). Per-agent deny would probably cover tools, but every
firm spawn would still write the Human's config and share its gateway, channels and defaults;
one upgrade that widens a default (docs ≥ 2026.9: sessions visibility `all`) would reach the
firm through the Human's file. A profile is expected to give (unverified until B-012: the
gateway port, launchd service and other machine-wide state may still be shared): zero writes
to the Human's OpenClaw config, global seal keys set for the firm alone, no channels, a backup that
is just the firm's. The `firm-` namespace (08 §2) still applies inside it.
Alternatives rejected: firm agents in the Human's config with per-agent deny lists (shares
globals, every change touches the Human's file); a second OpenClaw install (more to pin, no gain).
Open: whether a second profile needs its own Gateway process/port for `openclaw agent`, or
whether the Runtime wakes agents with `--local`; settle it in B-012 with a dry run.

## ADR-020 — Survey corrections annotate the Bible, they do not rewrite it   (builder, cycle 8) — accepted
Where the Survey measured a living-book claim as false (05_ERAS §6 "Bible correction"), the
original sentence stays and a dated correction pointing to its evidence (SURVEY section,
VERSION_NOTES, ADR, backlog id) is added next to it, or the instruction is changed with the
reason inline. Corrected in cycle 8: test counts (03 §2, 05 Era 0), physics known holes (03 §2),
"chat restricted" lead (04 §11), OpenClaw docs-vs-installed, `doctor` may migrate, global-only
seal keys, backups born private, firm profile (08 §1–2, 05 Era ½ exit criterion). Why: the
books are also history — a reader should see what was believed and what was measured
(honest measurement, Art. 9) — and only evidenced claims are touched, so a correction never
smuggles in a new rule. Protected books (00, 01): read, nothing version- or count-specific to
correct, so no proposal. Alternative rejected: silent rewrite (loses what the Human believed).
Amended after audit (cycle 8): ADR-019 and SURVEY §9 listed `tools.profile` as global-only;
the installed schema has a per-agent override (`agents.list[].tools.profile`). ADR-019 stands
(mcp, web, sessions and agentToAgent are global). The docs' `agentToAgent` default-on is not
counted as a measured loosening: the installed schema states no default.

## ADR-021 — Era ½ closes with explained residue; Era I opens with the seal   (builder, cycle 9) — accepted
Era ½'s five exit criteria are ticked (evidence: `state/SURVEY.md` §10). "Repo clean" is met by
its "or explained" branch: `test_api.py` (key redacted) and `.vscode/settings.json` stay tracked
until P-0002 allows headless `git rm` (S-004b), and the ignored local junk (`ui/`, `.DS_Store`)
is harmless. Holding the Era open for a Human decision would idle the loop on a cosmetic item —
the prime rule says continue (CLAUDE.md rule 10); S-004b stays in the backlog and runs the
cycle P-0002 is answered. The fourth criterion was reworded in cycle 8 inside its own Era; it
was made stricter and was already met, so the closure does not depend on the rewording.
Era I order: **B-002 (dependency-law test) and B-003 (halt in physics) first**, then B-016 →
B-020 → B-004. Why: 06_LOOP §2 ranks Constitution compliance (Art. 3 no LLM in `app/`, Art. 5
HALT) above exit-criterion work; both are Era I deliverables 1–2, small, and are the seal that
must exist before any agent can wake. The time work (B-016, B-020) still precedes the simulated
clock (B-004), as decided in cycle 4. Alternatives rejected: keep Era ½ open until P-0002 is
answered (idles on cosmetics); start with B-016 (time is the weakest spot, but no agent can
exploit it before the clock moves, whereas the seal is a standing rule).
