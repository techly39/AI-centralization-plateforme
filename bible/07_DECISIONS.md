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
Amended after audit (cycle 9): the open red-team holes (BACKLOG "Physics bugs", Art. 8.2) are
the **same priority tier** as B-002/B-003, not below Era I. They are not urgent today only
because no agent can run (`monthly_llm_usd_cap: null`); that is a reason for ordering inside
the tier, not for demotion. Gate: every open hole is fixed or accepted by an ADR with its reason
before any agent wakes (before B-012's first live probe and before B-015). B-000d (non-finite
floats in event payloads) goes with or before B-016, since both touch `append_event`.

## ADR-022 — The dependency law, placed and enforced   (builder, cycle 10) — accepted
Question: 03 §1 states the law for `app`, `runtime`, `ui`, `quant`, `truman` but not for
`mcp_server/` (which imported `app.metrics.reporting` for one constant and so loaded 35 `app`
modules incl. the DB engine — SURVEY §4a.9) nor `scripts/`. Where do they sit, and how is
the law enforced?
Answer from the future: `mcp_server` is one agent's doorway — an **HTTP client** of the App,
like the Runtime. It may import only `app.config` (settings) and `app.limits` (new: pure
constants that clients validate against, no imports), never the DB, ledger or OMS. Shared bounds
move to `app/limits.py` (a natural home for IDEAS "physical-units types" later). `scripts/` are
clients (MCP/HTTP) except named in-process probes (`survey_probe_physics.py`) that run physics
on a throwaway DB. Physics (`app`, `migrations`) also never imports `mcp`: MCP wraps it from
outside. `legacy/` is imported by nothing; `runtime` by nothing outside tests.
`tests/test_boundaries.py` enforces it with **two detectors** (cycle 7 lesson: one detector's
"0 found" is a statement about the detector): an AST scan of every import, incl. those inside
functions, and a fresh interpreter that imports the entry points and inspects `sys.modules`
(catches an LLM SDK pulled in by a dependency). The scanner is tested on a planted tree, and
every top-level Python directory must be placed in the law or the suite fails.
Alternatives rejected: let `mcp_server` import any "pure" `app` module (no test can tell pure —
an allowlist can); duplicate the constant in the wrapper (two sources of truth for one limit).
Consequences: a new package (`runtime/`, `truman/`, `quant/`, `ui/`) is under its law the moment
it holds Python — its rules are already in the test. The Runtime may import LLM SDKs (it hosts
the minds); physics, the pure libraries, the wrapper, the UI and the scripts may not. Known
limits (corrected after audit, cycle 10): the static scan reads `import`, `from … import`, and
`__import__("x")` / `import_module("x")` with a **literal** first positional name; it cannot
see a computed name (`import_module(f"…")`, `getattr`-built calls, `exec`), an aliased importer
(`from importlib import import_module as im`), or the keyword form `import_module(name="x")`. The dynamic detector sees only what
importing `app.main`, `app.cli`, `app.scheduler` (and the wrapper's entry points) loads — not an
import buried in a function that has not run. Code that hides an import from both is a
review matter (auditor), not something this test can prove absent. `quant` and `truman` may
import each other; the law does not order them yet.

## ADR-023 — Halt in physics: one gate, every write, every role   (builder, cycle 11) — accepted
Question: Art. 5 says the Human's halt file stops the world. 03 §2 / 05 Era I deliverable 2 ask
physics to refuse agent writes and expose `GET /halt`. Which requests, which roles, which status,
where is the check, and what about the background pending-order monitor?
Answer from the future: **existence of the file is the switch** (an empty file halts), read on
every request — no cache, no restart; lifting the halt is deleting the file. The gate is one call
in `app.registry.auth.get_current_agent`, which every endpoint except `/health` depends on: any
method other than GET/HEAD/OPTIONS from any authenticated agent — **every role, management and
`system` included** (the gate has no role branch; analyst, PM and management are tested on
every write route, `system` is not — it has no API key in the tests) — gets **423 Locked** and one
`halt_refused` event `{method, path, role}` where `path` is the **route template**
(`/orders/{order_id}`), never the URL: the gate runs before path params are validated, so a raw
path would let a halted agent write free text into the ledger (red-team cycle 11, medium, fixed).
Unauthenticated requests stay 401 and log nothing (no identity to attribute). Reads keep working:
a halted world must stay observable. `check_pending_orders` fills nothing while halted — checked
**under `OMS_LOCK`**, so a sweep queued behind the lock cannot fill after a halt that began while
it waited (red-team cycle 11, low, fixed) — and both of its triggers (live scheduler, future
`/clock/advance`) obey. `GET /halt` → `{halted}` is a
universal action (`READ_HALT`), MCP tool `get_halt`. The path is a **constant**
(`app.registry.halt.HALT_FILE` = `governance/HALT` under the repo root), not a setting: Art. 5
names that file, and a `config.yaml` key or `FUND_*` variable that moved it would be a route
around the halt (auditor BLOCK, cycle 11 — the first draft had a setting). Tests repoint the
constant through an autouse fixture, so the real file never leaks into the suite. The check runs
once at the start of each request and each monitor sweep; a request or sweep already past it
finishes ("the current tool call", Art. 5.2). Operator CLI commands (`seed-admin`, `create-pod`,
`fund-pod`) are the Human's own hands, not agent requests, and are not gated. Halt start/end are
not ledger events (the file is the Human's; backlog B-023).
Alternatives rejected: a per-router dependency (a new router could forget it — the auth
dependency cannot be dropped without losing auth); exempting management/`system` (the halt is the
Human's, nothing in the firm outranks it); 503 (says "broken"; the world is deliberately stopped —
423 says "locked, try later"); letting cost/task self-reports through (unverified self-reports;
metering will come from the provider, 03 §4; the refusal event still records the attempt);
returning the file's contents (Human prose is not a firm-facing channel yet); pre-auth middleware
(needs its own key lookup and could not attribute the event).
Consequences: the refusal event is the one write a halted world still makes. The "every write
route" test is generated from the OpenAPI schema, so a new write endpoint is covered the day it
lands; a write endpoint that skipped `get_current_agent` would escape the gate (none does today —
the generated test would catch it, since it expects 423 from each). Not done here: stopping agent
*wakes* within one tick — Era I exit criterion "creating HALT mid-run stops the run within one
tick" — needs the Runtime (B-009).

## ADR-024 — Finite numbers only: bounded floats, walked JSON, a ledger that refuses   (builder, cycle 12) — accepted
Question: Python's `json` reads `NaN`, `Infinity`, `-Infinity`, and turns `1e309` into `inf`.
Red-team 0001 stored `Infinity` as a cost, crashed the 422 handler with `NaN` (500), and made the
ranking number `null` with two finite 1e308 costs. Where do non-finite numbers stop, and is
"finite" enough?
Answer from the future: **three layers, each tested on its own** (removing the schema checks, the
handler or the ledger check each turns its own tests red). (1) **Request schemas**: every float
request field is **bounded** by a cap (`le` alone already refuses NaN/inf; `allow_inf_nan=False` is
kept as a second, untested-by-mutation statement of intent) in `app/limits.py` — `MAX_USD_PER_REPORT` 1e6, `MAX_ORDER_QTY` 1e9,
`MAX_PRICE` 1e7 — because finite is not enough when values are summed or multiplied (caps keep
every order notional ≤ 1e16; a cost sum stays finite for any count of reports the API could
accept). Every free JSON field (`structured_payload`, task `outcome`) is walked to any depth by
`app.finite.first_non_finite`. The MCP tools carry the same caps (they may import `app.limits`,
ADR-022). (2) **The 422 handler** echoes rejected input with non-finite floats spelled as text
(`"NaN"`), so the error is standard JSON. (3) **`append_event` refuses** (`ValueError`) any payload
with a non-finite float at any depth: the ledger stays standard JSON that any tool can replay,
whatever an in-process caller (Runtime, CLI, a provider) hands it. `report_cost` checks `usd_cost`
in-process like it checks tokens. A test walks the OpenAPI schema: a new float request field
without both bounds, a new free JSON field `tests/test_finite.py` does not attack, any request field
the walk cannot see into (arrays of numbers/objects, nested models, untyped `Any` — auditor WARN,
cycle 12), or any query/path parameter that is not plain turns the suite red.
Alternatives rejected: an engine-level `json_serializer(allow_nan=False)` (the test engine is built
separately, so it would be untested; and it fails as 500 at flush, after the 422 chance has gone);
a custom body parser rejecting the non-standard literals (`1e309` is standard JSON and still
becomes `inf`); finiteness without caps (1e308 + 1e308 = inf).
Consequences — what this does *not* cover, said plainly: numbers the world itself produces. A
market-data provider returning `NaN` (yfinance can) or a non-finite setting (`fee_rate`,
`static_prices` in `config.yaml`) now makes the fill's `append_event` raise, so that request fails
with 500 and writes nothing, instead of storing `NaN` — and in the background limit-order sweep one
such fill rolls back the **whole sweep** (every pod's fills that tick) and repeats each tick
(`app/oms/monitor.py`; auditor WARN, cycle 12). Not agent-reachable (prices come from config or the
provider; NaN never crosses); backlog B-025. Validating provider output belongs to
B-005/B-008; the CLI's `fund-pod --delta inf` is refused by the ledger, bounded cleanly by B-006.
Large finite values inside free JSON (`1e300`) pass: they are data, not quantities physics sums.
Strings such as `"NaN"` are text and pass.
Amendment (same cycle, red-team 0004): "finite" was the wrong word for the promise. The promise is
**portable JSON**, and two more shapes broke it: nesting ~256+ deep was walked, stored, and then
could not be serialised, so every later read of the recipient's inbox (HTTP and MCP) or of
`GET /events` was a 500 (high — one analyst message poisoned a rival PM's or management's reads);
an int like `10**400` in free JSON reached the ledger and reads as `Infinity` in float64 tools
(medium); and the recursive walker raised `RecursionError` (500) at ~1000 levels (low). Fix: one
**iterative** walker `app.finite.json_problem` refuses non-finite floats, ints beyond
±`MAX_SAFE_INT` (2**53 − 1, JavaScript's safe-integer bound) and nesting beyond `MAX_JSON_DEPTH` = 32
(requests) / `MAX_LEDGER_DEPTH` = 36 (`append_event`); the 422 echo is depth-bounded.
**Ids are bounded too** (re-audit BLOCK, same cycle): with the ledger refusing big ints, a cross-pod
read naming `pod=2**53+1` made `deny()` raise — a 500 instead of a 403, and the
`permission_denied` record lost. Every id an agent can send — path (`IdPath`), query (`pod`,
`actor`, `after_id`, `before_id`), body (`Id`: `task_id`, `pod_id`) and message refs
(`agent:<id>`/`pod:<id>`) — is now 1..`MAX_ID` (= `MAX_SAFE_INT`) → 422 beyond. That also closes
B-000m (red-team 0002) and red-team 0004's int64-id hole. A test requires an upper bound on every
integer parameter and body field in the OpenAPI schema. Held and kept as guards: string-encoded
`"inf"`, int→float overflow on numeric fields, duplicate keys, orders at both caps, subnormal
quantities, 50 max-size cost reports, MCP inf/nan. Open, strict-xfail in `tests/test_redteam_0004.py`,
outside this unit: fee rounds to $0.00 below $5 notional (B-026), non-finite feed prices (B-025,
with B-005).

## ADR-025 — Replay order is live order: ledger time never runs backwards   (builder, cycle 13) — accepted
Question: live state folds events in append (id) order (`app/ledger/apply.py`); `rebuild_state`,
the equity curve and `read_events` replayed in `(ts, id)` order. A clock that steps back (an NTP
step on `LiveClock`; a rewound backtest clock in Phase 3) gave a rebuild with 10 phantom shares
(SURVEY §4a.1, P3), and the sell reducer silently erased the impossible position. Which order is
the truth, and what keeps the day buckets of the equity curve consistent with it?
Answer from the future: **three laws, each with its own mutation-tested tests**
(`tests/test_time_order.py`). (1) **Ledger time never runs backwards**: `append_event` stamps
`max(clock, latest ts in the ledger)`, computed *inside the INSERT* (a scalar subquery in a `CASE`,
portable to Postgres) so the floor is read under the write lock SQLite already serialises writers
with. Id order and time order are then one order, and a day bucket never holds an event the live
fold applied after a later day's. (2) **Every replay folds in id order** — `rebuild_state`,
`_pod_events` and `read_events` order by `Event.id` — so a ledger written before law 1 still
rebuilds to what was live; the equity curve buckets each event on the latest day the ledger had
reached, which equals its own day on a monotonic ledger. (3) **An impossible history is an
error**: the sell reducer raises on a sell beyond the position (tolerance `QTY_EPSILON`, now
defined in `app/ledger/reducers.py` below the OMS and re-exported by `app.oms.money`). The OMS
already refuses such sells, so this only fires on a corrupt or mis-ordered ledger.
Why hold, not refuse: refusing a write when the clock is behind would turn every NTP step into a
burst of 500s on a live desk; holding loses at most the size of the step from one timestamp and
never reorders anything. Why not order by `id` alone: the equity curve buckets by date, so a
late id with an early stamp would still land in the wrong day.
Evidence: 11 new tests red before the fix; each law's mutation turns only its own tests red
(clamp → 6, rebuild order → 1, equity order → 1, equity "reached" day → 1, `read_events` → 1, sell
raise → 2). The Human's `fund.db` (95 events, August) has 0 backward steps and rebuilds unchanged
(copy, read-only).
Consequences — said plainly: (a) A held timestamp is silent: the ledger does not record that the
clock was behind. (b) The floor is global, so **B-004 must scope it per `run_id`** — a backtest
started under today's live ledger would otherwise have every event stamped today. Until then a
rewound clock is held, not honoured. (c) Metrics read `as_of = clock.now()`; when the clock is behind
the ledger, events stamped later are outside that window (the curve ends before them). That is
B-004/B-020's question (which "now" an agent and a report see). (d) On Postgres under READ
COMMITTED two concurrent inserts can each read a stale floor, and sequence ids are not commit
order; Postgres is not the backend today — revisit with any backend change. (e) Test fixtures must
freeze the clock before any fixture writes an event (`tests/test_metrics.py` `history` is now
autouse for that reason): a live-stamped `agent_registered` before a frozen past holds every later
event at today's date.
