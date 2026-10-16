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
Amended (cycle 20, ADR-032 (8), Q-0005): "any agent" means any **spending** mind. The gated
milestones are unchanged: B-012's live probe is now R-7's and B-015 is now R-8. Scripted and
cassette minds in R-1…R-6 are code, not subjects, and may run while holes are open. If the Human
answers Q-0005 with A, this reverts to "any mind".

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
event at today's date. (f) **A forward step is permanent** (auditor WARN): one clock jump to a far
future date — an NTP glitch, or a script that sets a frozen clock forward against a real DB — pins
every later stamp there, and the append-only ledger cannot take it back. Agents cannot cause it:
nothing outside `app/clock.py` calls `set_clock`, and no route controls the clock (red-team 0005).
A guard (refuse or log a clock far ahead of the floor) belongs with B-004's clock design.
Amendment (same cycle, review): red-team 0005 found 2 low holes, both fixed. (1) Rows agents read
must carry the ledger's time: `Order.created_at` and `filled_at` are now copied from their
`order_placed` / `order_filled` events (`fund_pod` already did this for `Allocation.ts`), and
`execute_fill` lost its `at` argument. `Message.ts`, `Cost.ts` and `Task` times still take the raw
clock → B-028. (2) `QTY_EPSILON` forgives float dust on a position, never a sell of nothing: the OMS
and the reducer both refuse any sell of a ticker the pod does not hold (a 1e-9 naked sell used to
fill and credit cash).

## ADR-026 — Every agent may read the clock; only the world controls it   (builder, cycle 14) — accepted
Question: TRD §7 lists `GET /clock` under "Clock (system/management only)", so analysts and PMs
get 403 — yet the MCP `get_clock` tool tells every agent "use this rather than your own clock"
(SURVEY §4a.8, P7; B-020). In backtest mode (B-004) the fund's now is a simulated date. Widen the
read, or correct the tool?
Answer from the future: **widen the read, keep control closed.** Reading the clock becomes a
universal action, `Action.READ_CLOCK`, beside `READ_HALT` in `app/registry/permissions.py`; the
response stays `{mode, now}`. `POST /clock/mode` / `/clock/advance` do not exist yet and, when
B-004 builds them, are system/management-only as TRD §7 says. This ADR amends TRD §7 for the read
only.
Why: (1) **Honest measurement** — an agent in a 2019 backtest that cannot learn it is 2019 will
reason from its runtime's wall clock (2026), which is exactly the future knowledge the look-ahead
guard exists to deny; the simulated date is the only honest time it can use. (2) **The 403 sealed
nothing**: every order, fill, message and bar an agent already reads carries the fund's time, so
the date leaks by inference anyway — the 403 only made the honest path the hard one. (3) Reading
is not a privilege: like the halt state, it is the world's state, which every participant lives in
(Art. 10.2: world facts are visible). (4) Smaller and reversible: one matrix line.
On `mode`: an agent can tell `live` from `backtest`. Hiding it would be theatre while agents' own
runtimes carry a wall clock; if an experiment needs agents blind to the mode, that belongs to the
Runtime/Truman (which controls what an agent perceives), and this field can then be withheld by
role in one place.
Evidence: `tests/test_clock_and_health.py` — every role reads the frozen clock's `now` exactly;
a PM's order is stamped with the `now` it read; the read writes no event and works under halt; a
deactivated agent gets 401. Mutation: dropping `READ_CLOCK` from the universal set turns 13 tests
red, all clock tests, nothing else. Red-team 0005's `test_held_no_clock_control_on_the_surface`
(no clock write for any role, management included) is unchanged; its management-only read guard
is replaced by a read-only guard (200, only `mode`/`now`).
Amendment (same cycle, review): red-team 0006 — 1 low hole, ~36 attacks held (query strings, path
and verb tricks, forged keys, `READ_CLOCK` admitting any other route, universal-set creep,
cross-pod reads, deny-event spam, per-pod side channels, halt). Hole: after a clock step back the
ledger holds its stamps (ADR-025) but `/clock` returned the raw clock, so an agent's next order
was stamped later than the now it was told — the gap revealed another pod's activity in its
"future". Fix: **`now` is the ledger's now** — `ledger_now(session)` in `app/ledger/events.py`,
`max(clock, latest ts)` through the same `_not_before_latest` expression the INSERT uses: the stamp
the agent's next event will carry. It reveals nothing an order would not (`created_at`). Mutation:
raw clock back in `/clock` → only that test red. Tests whose frozen moment sat *before* the
fixtures' stamps (an unnoticed step back) were moved after them; the attacks are unchanged.
B-004's per-`run_id` floor will scope `ledger_now` with it.

## ADR-027 — A run is a database; a backtest's time is a ledger fact   (builder, cycle 15) — accepted
Question: TRD §9 wants backtest mode (simulated time advanced only by `/clock/advance`), a mode
switch (`POST /clock/mode`), and "live and backtest runs are separate `run_id` scopes on all
tables". ADR-025's floor and ADR-026's `ledger_now` are global: a backtest in a ledger that holds
today's stamps would be stamped today forever. How are runs scoped, where does backtest time live,
and who moves it?
Answer from the future: (1) **A run is a database.** A backtest is a *fresh* database opened by
`fund-env start-backtest --start <ISO>`, whose first event is `run_started {mode, start}`; any
database whose ledger does not open with it is live. `start_backtest` refuses a database with a
row in any table, a naive start, or a start in the future. (2) **Backtest time is a ledger fact.**
`BacktestClock` (`app/clock.py`) is the process's copy of the latest `run_started.start` /
`clock_advanced.to`; `install_run_clock` rebuilds it on every server start (lifespan, through
`get_session`) and before every operator CLI command, so a restart resumes and an operator's
`create-pod` stamps simulated time. (3) **Only `POST /clock/advance` moves it** —
`Action.CONTROL_CLOCK` (management, system; never universal), body `{days, minutes}` with 1
minute..366 days per step (`MAX_ADVANCE_*` in `app/limits.py`, mirrored by the MCP tool), from
`ledger_now` forward, under `OMS_LOCK`, never past the real now (`wall_now()`: the world has no data
from the future), recorded as `clock_advanced {from, to, minutes}` stamped `to`, then the same
pending-order sweep the live scheduler runs. Live → 409; halt → 423. (4) **No `POST /clock/mode`**,
and `clock.mode` leaves `config.yaml`: a mode that a setting or a request could flip mid-ledger is
the mixing this ADR forbids; the database is the only authority.
Why: (1) **Safer seal** — scoping by file means no query anywhere can forget a `run_id` filter
(every table, every reader, every future feature); a `run_id` column would make each of the ~40
queries a potential cross-run leak, i.e. look-ahead from a live ledger into a backtest. The ADR-025
floor and `ledger_now` are per run with zero code. (2) **Honest measurement** — a run's ledger
holds exactly its own history; replay, metrics and equity curves need no filter to be right.
(3) **Deterministic** — the clock is derived from events, so a restart and a replay agree on now;
B-029's permanent forward step cannot arise in a backtest (every step is bounded and recorded).
(4) **More general** — parallel backtests (Quant Lab, Era III+) are parallel files/processes, no
shared lock. (5) Reversible: a `run_id` column can still be added if one database ever has to hold
many runs. Cost: comparing runs means opening several files — the Observatory's job, not physics'.
Not done (next slices): look-ahead guard on market data (B-005 — until then a backtest run is
**not** honest: providers may serve post-`now` data); metrics `as_of` and market data still read the
raw clock (equal to `ledger_now` in a backtest); management as clock controller is the TRD's
choice — if management becomes an LLM agent, control moves to a Runtime identity (B-032). B-029
(live forward step) stays open.
Evidence: `tests/test_backtest_clock.py` (24): opening, refusals, every role reads the simulated
now, advance + record, every event of the run inside [start, now], a limit order fills on the
advance that crosses it (live = replay), only `CONTROL_CLOCK` advances, 9 malformed/unbounded steps
→ 422, the real-now bound, halt, restart resume, operator stamps, CLI refusal. Red-team 0005's
"no clock control" guard now pins `/clock/mode`, `PUT/POST/PATCH /clock` absent and a live clock
unmovable by any role. Mutations (each alone): sweep dropped → 1 red; CLI install dropped → 1;
wall bound dropped → 1; used-DB check dropped → 2; `CONTROL_CLOCK` universal → 5 (incl. 3 red-team
0006 guards); restart reads the oldest event → 1.
Amendment (same cycle, review): auditor **PASS** (3 WARN); red-team 0007 — **3 medium holes**, 51
attacks held. All fixed, each mutation-checked alone (1 red each): (1) `place_order` priced before
`OMS_LOCK`, so an advance in between gave a fill at the old now's price stamped at the new now →
under the lock, a moved non-live clock re-prices at the new now (only that rare path fetches under
the lock). (2) The pending sweep read `now` before the lock → read under it. (3) A server already
running on a file that `start-backtest` then opened kept its live clock and stamped today into the
backtest (and bricked it) → **`append_event` refuses a clock that is not its ledger's run clock**
(`RunClockMismatch`, one indexed read per append; API 503 "restart the server"). The red-team's
test expected the stale server to self-heal; refusing is the safer seal (a live scheduler would
still be sweeping), so the test pins: no live stamp, 503/409, and a restart resumes at the run's
now. Auditor WARN 1 (lifespan install untested) → `test_the_server_starts_on_its_databases_clock`
(mutation → red alone). WARN 2 (an unguarded backtest could later pass as honest) →
`run_started` records `look_ahead_guard: false` (`LOOK_AHEAD_GUARD` in `app/run_clock.py`; B-005
flips it). WARN 3 (a failed advance commit restores the clock after non-OMS writers stamped `end`)
→ accepted, low, backlog B-033.

## ADR-028 — No feed may show what is not known by now; the guard is the base   (builder, cycle 16) — accepted
Question: TRD §9 wants market data to "reject any request for data beyond simulated now". SURVEY
§4a.2/§4a.3/§4b.3 found three leaks: daily bars filtered by their *open* stamp (00:00) while they
carry that day's *close*; yfinance `get_price` serving today's quote for any `as_of` and stamping it
with the time asked; the test double copying the first leak, so the suite certified it. What does
"beyond now" mean, where is it enforced, and what does a live feed answer for a past now?
Answer from the future: (1) **"Beyond now" = not yet known.** A bar is served once it has *ended*
(`bar_end(ts, interval)`: +1 h / next midnight of its stamp / +7 d / next month); a quote is
stamped with the latest moment its price can be from and refused (`FeedDataError`, 502; the OMS
answers `price_unavailable`, the sweep leaves orders pending) if that is after `as_of`. A price
that is not a positive finite number is refused the same way (the feed half of B-025). A window
starting after now stays 400 (`LookAheadError`). (2) **The guard is the base, and cannot be
skipped.** `MarketDataProvider.get_price` / `get_ohlcv` are the only public entries; implementations
write `_quote` / `_bars`; defining either public method on a subclass is a `TypeError` at class
creation. Real providers, `StaticProvider`, the test double and every future Truman provider get
the same law with no code of their own. (3) **A live feed answers the past from history.** yfinance's
current quote answers only an `as_of` within `LIVE_QUOTE_WINDOW` (60 s) of the real now
(`wall_now()`, now with a second sanctioned use: telling which answer the feed can honestly give —
still never a stamp or a price); an older `as_of` gets the close of the last daily bar ended by
then (14-day lookback), stamped at that bar's end. A live current quote is stamped at the moment
asked — an upper bound, since a delayed quote is older. (4) **A backtest stays out of the live
window:** `start_backtest` and `advance` refuse a now within 60 s of the real now, so a backtest is
always answered from history. (5) `LOOK_AHEAD_GUARD = True`: runs opened from now on record
`look_ahead_guard: true` in `run_started`; older runs keep their `false`.
Why: (1) **Honest measurement** (Art. 9) — a backtest that can see the close it is about to trade
on measures nothing; every result of Era I's milestone rests on this line. (2) **Safer seal** — one
enforcement point that a subclass cannot route around beats a filter in each implementation (the
survey's leak was precisely an implementation-level filter written the wrong way, then copied into
the double). (3) Conservative by construction: a daily close is served ~8 h late (midnight, not
16:00 ET), never early; the cost is coarse intraday resolution in backtests (at noon the pod sees
yesterday's close), the gain is no exchange-calendar logic in physics. (4) **Deterministic** — the
rule is arithmetic on stamps. (5) Reversible: finer bar ends (exchange close times) can come with
Truman (B-008) without changing the law.
Not done: intraday prices in backtests (daily bars only; Truman's job, B-008); non-finite *bar*
values and `config.yaml` price bounds (rest of B-025); metrics/market-data "now" = `ledger_now`
(B-004b); market data as of a now that differs between the route and the OMS (B-004b).
Evidence: `tests/test_look_ahead.py` (override refused ×2, future stamp refused, 5 bad prices, naive
`as_of`, a bar served exactly at its end, `bar_end` ×6 incl. Dec→Jan and Jan 31→Feb 29, the double
at noon, yfinance past from history and live only within 60 s, a future-stamped feed → 502 with
nothing stored, an honest backtest end to end through the API: noon → yesterday's close, fill at
it, +12 h → today's). Tests corrected because they certified the leak, each said in the commit:
yfinance live-path tests now run at the real now; the history test drops the 07-30 bar at 15:00;
metrics and POC fixtures fill at the prior close. Red-team 0004's two feed-price xfails pass.
Mutations (each alone, 1 red each): bar by open, stamp unchecked, non-finite allowed, override
allowed, yfinance always live, advance into the window, start into the window, flag off, double
leaks today's close.
**Amendment (cycle 16, red-team 0008 — 5 holes, all fixed same cycle).** The law was "nothing not
known by `as_of` is *served*"; it must also be "nothing known by `as_of` is *withheld from the
price*, and no answer *depends* on what is not known". (a) **High — stale-quote arbitrage:** `/ohlcv
?interval=1h` served today's ended hourly bars while fills used yesterday's daily close; after the
close a PM bought at 180 what the world already showed at 250. A past quote is now the close of the
latest bar of any interval `/ohlcv` serves (`1d`, `1h`) that had ended, stamped at its end. So "not
done: intraday prices" above now reads: intraday *resolution* is whatever the feed's hourly history
gives (Yahoo: ~730 days); older backtests price daily. (b) **Medium — cache across a bar end:** a
past quote is reused for its exact `as_of` only; live quotes keep the TTL. (c) **Medium — existence
oracle:** `[] vs 404` depended on rows after `as_of` (bisect `end` → a future listing day). The base
now clips the window it hands an implementation to `as_of`'s day, and a window with no ended bar is
one `UnknownTickerError` naming only the request (so `/ohlcv` answers 404, not 200 `[]`, before any
bar has ended). Two independent defences; each pinned by its own test. (d) **Low — the seal:**
"final" is checked through the MRO at creation (a mixin is refused), and assigning a guarded entry
on the class (metaclass) or an instance is a `TypeError`. `object.__setattr__` still bypasses the
instance check: Python has no true final, and code inside the App's process is past the seal anyway
— agent strategy code must never run in it (a constraint on Era III's sandbox, recorded here).
(e) **Low — the 60 s edge:** `start_backtest`/`advance` refuse `>= wall − 60 s` (strict), matching
the feed's inclusive window. Tests corrected, each with its reason: the look-ahead yfinance stub
returned its daily frame for every interval (Yahoo never does); the one-lookup-per-sweep test
counted by replacing `get_price` on an instance, now refused — it counts `_quote`. Mutations: each
of the 9 fixes reverted alone turns its test red.

## ADR-029 — One "now" for physics: every reader of time reads the ledger's now   (builder, cycle 17) — accepted
Question: ADR-026 made `GET /clock` answer `ledger_now` (`max(clock, latest stamp)`), and ADR-025
stamps every event with it. But the quote route, the OHLCV defaults, the portfolio valuation, pod
metrics, the leaderboard's `as_of`, the OMS reference price and the pending-order sweep still read
the raw clock. After a clock step back an agent was told 10 June, shown 4 June's close and stamped
10 June — a market order filled at a price from a moment its own stamp says had passed. Which "now"
does physics answer with?
Answer from the future: **one: `ledger_now(session)`.** Every physics reader of time uses it; the
raw clock is read only where an allowlist in `tests/test_one_now.py` names the file, the exact
number of reads and the reason (the clocks; `append_event`/`ledger_now`, whose floor is applied in
SQL; the backtest controller; yfinance's 60 s live window; the CLI's start line; the request log).
A "read" is any spelling the AST shows: `.now`/`.utcnow`/`.today` called or not, `getattr(x,
"now")`, anything off the `time` module, `wall_now`. The row-stamp sites of B-028 are listed as
debt and leave the list when B-028 copies `event.ts`; a count above or below the list is red.
Why: (1) **Honest measurement** — price, valuation and stamp of one act must be one moment, or
P&L is measured across a gap nobody chose. (2) **Safer seal** — a law pinned by an AST test, not
by review: a new `.now()` in physics is red until someone argues for it. (3) Deterministic and
small: in a backtest and in an un-stepped live run `ledger_now == clock.now()`, so nothing changes
there; it differs only after a step back (live, B-029) or a test's frozen clock. (4) Reuse — the
function already existed (ADR-026). Cost: one indexed `max(ts)` read per quote/valuation.
Not done: B-028 row stamps (allowlisted); the OMS still fetches the live price *before* `OMS_LOCK`
in live mode (B-030 note) — unchanged here, only its `now` moved.
Evidence: `tests/test_one_now.py` — ledger on 10 June, clock stepped back to 5 June: `/price`,
`/ohlcv` defaults, `/portfolio`, `/metrics/pod`, `/metrics/leaderboard`, a market fill and the sweep
(a 106 limit the stale 104 would fill stays pending at 109) all answer at 10 June; each was red
before. Red-team 0007's sweep spy moved from `monitor.get_clock` to `monitor.ledger_now` (the same
read; the property — fill price at the stamp's moment — unchanged).
**Amendment (cycle 17, red-team 0009 — 6 findings; 4 fixed + detector widened, 1 open).** "One now"
is not only *which* now but *how many reads* of it one answer takes, and *when the now becomes
visible*. (a) **Medium — a failed advance had shown its prices:** `advance` moved the process clock
before `clock_advanced` committed; lock-free reads (`/clock`, `/price`) answered at the new now, and
a failed commit took the day back after an agent had seen it. Now the event is stamped `at=end`
(`append_event(..., at=)`, still under the floor; only the advance uses it) and committed first;
the clock moves after. (b) **Low ×2 — two reads of now in one report:** pod metrics and the
leaderboard read now once and pass it down (`build_portfolio(now=)`, `compute_pod_metrics(now=)`,
`compute_leaderboard(now=)`). (c) **Low — a book counted twice:** `build_portfolio` read positions,
priced them (network), then read cash; a fill in between was counted as shares and proceeds. Now
positions and cash are read first, together, under `OMS_LOCK`, then priced. The test pins the order
of reads; the lock (cross-thread) is defence-in-depth, untested like B-000b. (d) **Low — detector:**
also sees `import time` under any name, `from time import …`, imported/attribute `wall_now`, `_now`,
`current_timestamp`, computed `getattr`, `methodcaller`. Per-file counts cannot tell a diagnostic
read from a physics one swapped for it — review's job. **Open (B-036, 2 strict xfails):** `OMS_LOCK`
is a per-process lock; an advance committed by a second process between the in-lock read of now and
the fill's INSERT prices a fill at the old now and stamps it at the new. The TRD runs one process;
the operator CLI (`check-orders`) is the second. Fix candidates: compare the event's stamp with the
priced now after the flush and roll back on mismatch, or `BEGIN IMMEDIATE` before the read.
Mutations: advance's clock moved before the commit → (a) red; cash read after pricing → (c) red.

## ADR-030 — A backtest's world is a secret key; the first determinism test is a month, twice   (builder, cycle 18) — accepted
Question: TRD Phase 3's milestone is a 1-month backtest in under 10 minutes; Era I wants "one pod
runs end-to-end" and determinism tests. Against what market? yfinance needs the network, revises
its history, and rate-limits — a test on it measures Yahoo, not physics. And what does
"deterministic" have to cover to mean anything?
Answer from the future: (1) **A keyed synthetic market in physics** (`SyntheticProvider`,
`marketdata.provider: "synthetic"`, `synthetic_key`, `synthetic_symbols`): day D's log-return for a
symbol is Box-Muller on `HMAC-SHA256(key, "return:{symbol}:{D}")` — a pure function, independent of
which days were asked first or by whom; closes compound from 2000-01-01 at the configured start
price (GBM, drift 0.0003, vol 0.015 a day, every calendar day); open = previous close; wicks and
volume from a second domain, `"noise:{symbol}:{D}"`. Only configured symbols exist. **Daily bars
only** (1wk Monday-anchored and 1mo aggregate them, and a period still running is skipped before
any of its days is computed); `1h` is refused, because an invented intraday path is a second route
showing a second market (red-team 0008's arbitrage). A quote is the last ended day's close stamped
at its end. It is a sealed `MarketDataProvider`, so ADR-028's guard is its law with no code of its
own. A golden value pins the formula: changing it changes every synthetic backtest ever run — an
ADR, not a test edit. (2) **The world is a secret.** The formula is published law (Art. 10); the
key is not, because whoever holds it knows every future close. It is ≥ 128 bits (`SyntheticProvider`
refuses fewer than 16 bytes; config takes 32..128 hex digits as a `SecretStr`), read from the
environment only (`FUND_MARKETDATA__SYNTHETIC_KEY`, never the committed `config.yaml`), with no
default: no key, no world. Test worlds use `tests/support.world_key(n)` — public by construction,
never for a real run. (3) **Determinism = same ledger, not just same P&L.** The probe
(`tests/test_phase3_probe.py`) runs a scripted, LLM-free PM (5- vs 20-day average, one third of the
book per name) through HTTP only, management advancing one day per step for 31 days, in a fresh
database per run. World 11 twice must give the same ledger event for event (id, stamp, actor, type,
payload), the same daily `/portfolio` curve, the same derived book (which `rebuild_state` must
reproduce) and the same `/metrics/pod`; world 12 must differ (not vacuous). (4) **The probe lives
in `tests/`**, the pod in the test file: agent strategy code never runs inside the App's process
(ADR-028 amendment); a TestClient is a client.
Why: (1) **Honest measurement** — a backtest is evidence only if it can be re-run to the same
answer; the ledger, not a summary number, is what an auditor replays. (2) **Safer seal** — a world
an agent can reconstruct is look-ahead with extra steps; key entropy, not formula obscurity, is
what keeps tomorrow unknown. (3) **Deterministic over LLM / reuse** — the provider is Truman's first
organ (IDEAS c16): any scenario (crash, regime, correlated names) is a key and a parameter, offline.
(4) **Smaller & reversible** — one file in `app/marketdata`, config-selected; yfinance untouched.
Not done: the run's `run_started` does not yet record *which* world it ran in — B-037: provider,
symbols, parameters and a one-way **fingerprint** of the key (never the key: management reads
`/events`); a run's ledger plus the operator's key file should be enough to re-run it. Re-running a
world for an agent that has lived it is not out-of-sample (red-team 0010 note) — B-037 also records
which worlds which agents have seen. No cross-machine determinism claim (libm `exp`/`log` may differ
in the last ulp). No CLI backtest driver yet; no correlated names, regimes or jumps.
Evidence: world 11, 31 days: 49 events (31 `clock_advanced`, 7 orders placed and filled, 3 round
trips), $100,000 → $99,278.49, fees $227.93 — identical twice; world 12 → $102,739.09. ~0.55 s a
month in-process (budget 600 s). `tests/test_synthetic_provider.py`, `tests/test_redteam_0010.py`.
**Amendment (cycle 18, before merge — red-team 0010, 1 high hole, 6 held).** The first version was
*seeded*: `sha256("{seed}:{symbol}:{D}")` with `synthetic_seed: int = 0`. Every served bar's volume
is ~20 raw bits of that hash and its wick ~50 more, so three served volumes pinned a small seed in
a fraction of a second, and the attacker priced SYNA a week ahead exactly. Fixed as (2) above:
HMAC with a ≥ 128-bit key, noise in its own domain, no default, environment only. The hole test now
runs the same search (small ints in three encodings, their hashes, the public test keys) against a
fresh `secrets.token_bytes(32)` world and finds nothing; a companion test shows the same search
*does* recover a public test key, so the hole test is not vacuous. Auditor WARN (a running week's
future days were computed then dropped) fixed: skipped before computing, spy-tested, mutation red.
Lesson: a determinism tool and a secrecy tool are the same function; its input is the secret.

## ADR-031 — A run records its world and lives in only one   (builder, cycle 19) — accepted
Question: ADR-030 made a synthetic market a pure function of a secret key, but a backtest's
ledger did not say which market it ran in — and nothing stopped a server restarted with another
key (or `provider: yfinance`) from carrying on in the same database, splicing two markets into one
run with no event saying so. What does a run record, and what does it refuse?
Answer from the future: (1) **Every provider describes its world** (`MarketDataProvider.world()`,
a JSON record): `{provider, reproducible}` by default — honest for a live feed or a table tests can
move, whose answers are not a function of the record. The synthetic market's record is
reproducible and complete except for the secret: `law` (`"hmac-sha256-gbm/1"`, a version — a new
formula is a new law), `origin`, `drift`, `volatility`, `symbols` (normalised, sorted) and
`key_fingerprint` = first 128 bits of `HMAC-SHA256(key, "fingerprint:v1")`. (2) **`run_started`
carries it** (`world`), built from the installed provider at the moment the run opens — the world
must be installed first. (3) **One run, one world:** `install_run_clock` (server lifespan, every
operator command but `init-db`/`start-backtest`/`serve`) compares the recorded world with the
installed provider's and refuses with `RunClockError` naming the differing fields; the server does
not start, the CLI exits 1 with nothing appended. A run opened before this ADR has no `world` and
is let through (its ledger never claimed one). Live databases have no `run_started` and are not
checked.
Why: (1) **Honest measurement** — a backtest is evidence only if its ledger names the market it
was measured in; a run served by two worlds is a corrupted experiment that would look whole.
(2) **Safer seal** — the fingerprint is a separate HMAC domain under a ≥ 128-bit key, so management
reading `/events` learns a name, not a window onto any `return:`/`noise:` value nor a brute-force
target (red-team 0010's lesson). (3) **Deterministic over LLM / smaller** — one method on the base,
one check at the existing clock-install seam; no schema change (the record is an event payload).
Not done (B-037 slices b, c): a `fund-env backtest` driver that re-runs a ledger's world from the
operator's key file; a record of which agents have lived which worlds (re-running a lived world is
not out-of-sample). `world()` is not sealed: it is operator/physics code, not agent-reachable. Two
fixtures (the probe, `honest_backtest`) opened a run in the suite's static table and served it from
another provider — exactly what the law now forbids; they install their world first.
Evidence: `tests/test_run_world.py` (11 tests: record, golden fingerprint replica, restart in the
same world, refusals for another key / symbols / provider, pre-ADR run, server lifespan, operator
CLI, `/events` shows the fingerprint and not the key).
**Amendment (cycle 19, before merge — red-team 0011: 1 low hole, 8 held).** The static table is a
function of its configuration, so recording only `{provider, reproducible: false}` let a static
run restart on another table (other prices, extra symbols) — the splice this ADR forbids
(operator-only, hence low). Fixed: `StaticProvider.world()` records its configured table as
`prices` (still `reproducible: false`, because `set_price` moves it). Held: only management reads
`/events`; no spelling of the key leaks; the fingerprint matches no served HMAC and is no
brute-force target for a random key; equal records ⇔ equal markets (HMAC zero padding included);
floats and spellings round-trip through the JSON payload; agent activity cannot block a restart.
Auditor NOTE fixed: `start-backtest` without a key is `Error:` + exit 1. Left as noted: a
format-valid zero-entropy key (`"00"*16`) is accepted (predates this ADR; config cannot judge
entropy); `volatility=0` is code-only; a malformed configured symbol is a traceback (exits non-zero,
writes nothing).

## ADR-032 — The Runtime v1: a lockstep conductor of minds, recorded on cassette   (builder, cycle 20) — accepted
Question: all seven Era I exit criteria need a Runtime (`03_WORLD.md` §3), and none exists after 19
cycles. What is its shape, in what order is it built, and what may run while
`firm.monthly_llm_usd_cap` is `null`?
Answer from the future (the plan; each point lands in the slice named, with its own tests and,
where it refines this ADR, an amendment):
(1) **A separate client process.** `runtime/` package, `uv run fund-runtime` entry point. It reaches
the App only over HTTP with each agent's own API key, reusing `mcp_server.client.FundClient`. The
dependency law already allows `runtime → mcp_server`, and the transitive physics load must stay
`app.config` + `app.limits`, which the dynamic probe will measure (R-1). No rule that matters lives
in the Runtime. It decides *when* a mind wakes and *what it sees*, never what is allowed
(`02_SCALES.md` §2).
(2) **One tool surface.** A mind acts only through the MCP tool list `mcp_server.build_server`
publishes (the same tools an OpenClaw agent gets). The `native` adapter converts that list into an
LLM tool schema and executes calls through it, so "same tools for every adapter" holds by
construction (R-2).
(3) **A mind = provider + adapter + AgentSpec.** `LLMProvider.complete(request) → response`.
Three providers: `scripted` (a deterministic policy in code, used by tests and the probe pod; no
network client, $0, no model), `cassette` (replays a recorded exchange by request hash and
**refuses on a miss**; a miss is a divergence, recorded, never papered over) and later a
`metered` provider (an OpenRouter key per agent, R-6/M6). Each provider declares
`spends_money: bool`.
(4) **The cap gate reads the law literally and fails closed.** Before every wake **and before
every tool-call batch** (`03_WORLD.md` §3) the Runtime reads `governance/HALT`; before every wake
it reads `governance/human.yaml` (read-only, fixed paths). Under HALT nothing wakes and no further
batch runs. Under cap `null` no key is provisioned and only the providers on a closed list in
code, `{scripted, cassette}`, may wake. Every other provider is refused, including an unknown
one or one that claims `spends_money = False`; `metered` and the `openclaw` adapter are always
treated as spending. A `scripted` provider is not a firm agent (Art. 2.1: "every AI inside the
simulation"). It is a script with an API key, like the cycle-18 probe pod. A `cassette` provider
replays recorded model output at $0 and calls nothing. Runs are labelled `minds: scripted` or
`minds: replay` in the run record, so neither can be reported as a live agent run (Q-0005 covers
both).
(5) **Lockstep scheduler in backtest mode.** For each step: check halt and cap; wake the agents
whose wake policy fires, **one at a time in a fixed order** (agent id); each wake ends when the
mind says done, or hits its tool-call budget or a wall-clock timeout (recorded as such); then the
Runtime advances the clock. Sequential wakes make the ledger a function of (physics, world,
cassettes). Parallel wakes are a later, explicit trade (Era II) with their own ADR.
(6) **The Runtime holds the clock, not a firm agent.** `CONTROL_CLOCK` moves from `management` to a
reserved `runtime` identity (role or reserved name, never a squattable name, B-000f). The world's
time is not a participant's lever (Art. 10, B-032) (R-3).
(7) **Cassettes are the minds' ledger.** Every LLM exchange is stored in the run's directory as
(wake id, sequence, request hash, request, response, usage), with its hash linked from the events
the wake produced. Replay = the same scheduler with every provider swapped for `cassette`, into a
fresh database in the same world → the same ledger event for event (the ADR-030 comparison),
at $0 (R-4). `experiments/*/runs/` and cassettes are gitignored before the first one is written
(B-000i).
(8) **Order of slices** (BACKLOG "Runtime" section): R-1 skeleton + gates → R-2 scripted mind +
native adapter over the tool surface → R-3 lockstep backtest + runtime clock identity (M1: PM +
Analyst, scripted, a month, < 10 min) → R-4 cassettes + replay (M2) → R-5 agent-level halt, cap,
look-ahead tests (M3) → R-6 metering v1 on a fake provisioner + firm-level costs (M4) → R-7
`openclaw` adapter + static conformance (M5) → R-8 the first real-model month (M6, needs Q-0001).
Physics holes stay a gate before any **spending** mind wakes (ADR-021): they must be closed or
accepted before R-8 and before R-7's live probes, not before R-1…R-6.
Why: (1) **Safer seal and budget**: a Runtime that can only act through the App's published tools
cannot grow a second physics or a side door; the cap gate is code at every wake. (2) **Honest
measurement**: lockstep plus cassettes make a run with minds as replayable as the cycle-18 probe,
and the label keeps scripted months from passing as agent months. (3) **Deterministic over LLM**:
the scheduler, context assembly and gates are code; only the mind's reply is a model's. (4)
**More general**: provider, adapter and spec are the three seams the fork instrument
(`09_BUILDER_VISION.md` §2), model swaps and OpenClaw all need. (5) **Smaller and reversible**:
every slice is one cycle. Physics changes are limited to what a slice names: R-3 (the clock
permission move to a `runtime` identity, a TRD role deviation, and the `minds` label in the run
record), R-4 (if cassette hashes are linked from events), R-5 (B-023 halt events, if taken) and R-6
(system-reported costs overriding self-reports, firm-level costs, a cost-report rate law). Each of
these gets its own red-team pass. **Run criteria are ticked only by real minds:** R-3 and R-4
deliver M1/M2 with scripted minds and do not tick EC1/EC2. Those, and EC7's live half, are ticked
at R-8. EC3–EC6 are test criteria, and tests with scripted or fake providers may meet them
(EC4's own text allows "the fake provider in tests"). (6) **Reuse**: `FundClient`, the MCP tool table and the probe's scripted pod.
Dependency law (R-1): if `runtime` imports `mcp_server`, it transitively loads `app.config` +
`app.limits`. Giving the runtime layer an app allowlist is a change to the law, recorded as an
amendment here, with a planted counter-example showing every other `app.*` module is still refused.
Not decided here: parallel wakes, live-mode wake policies (cron/event), the meter proxy (03 §4.3),
memory policy, context packages beyond `/me` + charter + workflow input, and the cassette storage
format (files vs table). Each is decided in its slice.

Amended (cycle 21, R-1 shipped: `runtime/`, `tests/test_runtime_gates.py`):
(a) **The dependency law has two halves.** Statically, the runtime layer still imports **no** `app`
module. Its Layer is unchanged, and a planted `runtime/direct.py: app.config` is caught.
Dynamically, importing every `runtime` module may load no physics module beyond
`RUNTIME_MAY_LOAD_FROM_APP` = `{app, app.config, app.limits}`. That is the MCP wrapper's set, and
the Runtime will reach `FundClient` through the wrapper. The probe imports every file under
`runtime/`, so a new module is probed without a test edit. A planted package that imports
`app.ledger.events` is reported. Today the Runtime loads no `app` module at all.
(b) **The gate decides on names, never on a flag.** `runtime.gate` matches the AgentSpec's
`provider` **and `adapter`** strings exactly (type exactly `str`, no case folding, no trimming)
against `ZERO_COST_PROVIDERS` and `ZERO_COST_ADAPTERS = {native}`. Red-team 0012 H1 (high): with
the provider alone, `provider: scripted` + `adapter: openclaw` woke under null, though an OpenClaw
agent runs its own model on its own key. H4: a `str` subclass could answer the membership test
itself. The gate's code never names `spends_money`; a static test checks attributes, identifiers
and string constants (a `getattr` spelling is caught, with a planted counter-example). The other half of the closed
list lands in R-2. There, the name→class registry must map `scripted` and `cassette` each to
exactly one class with no model and no network client, so a spec cannot name `scripted` and get a
spending mind.
(c) **A cap set is not yet a licence to spend.** Under a numeric cap, a spending provider is
still refused, with `no_metered_key`, until per-agent metered keys exist (R-6). A cap the Runtime
cannot meter is a cap it cannot keep (prime rule: safer budget).
(d) **Both levers fail closed.** The reader turns into `null`, with a recorded `cap_problem`,
every cap it cannot read as a finite, non-negative number: a missing file or key, a YAML error, a
duplicate key, a string, a bool, ±inf, NaN, a negative, an integer too large for a float, a YAML
1.1 base-60 value (`1:30` would read as 90; red-team H7), or **any** parser failure. The
auditor's BLOCK: non-UTF-8 bytes, an unhashable key and deep nesting raised out of the reader
instead. HALT is read first, independently of the cap file. HALT counts if anything is at the
path, if the path cannot be checked, or if `governance/` itself is missing (red-team H3: a
non-editable install or a copied tree moves `REPO_ROOT` away from the Human's real HALT). Only
"the directory is there and the file is not" means the world runs. The claim check found the
first form: `os.path.lexists` answers False on any OSError, which would have failed open.
(Physics' `Path.exists()` has a milder form of the same gap → B-040.) The spec loader uses the
same duplicate-refusing loader, and it refuses `.yml`/`.YAML` files instead of skipping them.
(f) **The boundary scanner refuses what it cannot read** (red-team H8, widened at re-audit).
In every layer, each of these is itself a violation:
- `import_module` or `__import__` called with a non-literal name, whether as a bare name or as an
  attribute (`importlib.__import__`, `builtins.__import__`);
- `getattr(…, "import_module" | "__import__")(…)`;
- the builtins `exec`, `eval` and `compile`;
- a load from a file path (`spec_from_file_location`, `SourceFileLoader`).

No layer had any of these. Planted tests cover each spelling, plus one showing that `re.compile`
is not mistaken for one. This is a lint on code the Builder writes, not a seal: a determined
author can still hide an import (for example, a getattr chain built from computed strings).
(e) **AgentSpec deviations from 03 §3, recorded.**
- One added field, `provider`.
- `role` is one of {pm, analyst, management}. `system` and R-3's `runtime` identity are never a
  mind's role.
- A PM or Analyst needs a pod.
- `memory_policy` is `none`, and `wake_policy` is one of {every_step, never}, until their slices
  widen them.
- Specs are YAML files, one per agent, loaded in id order, which is the lockstep order.

Amended (cycle 22, R-2 shipped: `runtime/registry.py`, `runtime/scripted.py`, `runtime/native.py`,
`tests/test_runtime_native.py`):
(g) **The name builds the mind, and a contradicting spec builds none.** `runtime.registry.build_provider`
builds every mind from its spec through `PROVIDER_CLASSES`, a read-only table in code. Today that
table has one entry: `scripted` → `ScriptedProvider`. `cassette` is on the gate's list, but the
registry refuses it with `unavailable` until R-4, so it is never built from another class.
`wake()` has no parameter that takes a provider object (a test pins its signature). Open question
(b) is decided by the prime rule (safer budget, more honest measurement): a zero-cost spec that
names a `model` or a non-zero `budget_usd` is **refused** (`contradiction`). A `$0` label on a
model must not load as if it were valid. The spec still *loads*. The refusal happens where a mind
would be built, so `fund-runtime status` can still show the spec. AgentSpec gains a **second added
field, `script`**: the name of a policy in `runtime.scripted.SCRIPTS`, a read-only table in code.
It is required when the provider is `scripted` and refused for any other provider. A spec names
a script but can never supply one. `scripted.py` may import only pure stdlib modules and
`runtime.providers`, and may not name a builtin that loads code or reaches other modules
(`__import__`, `eval`, `exec`, `compile`, `globals`, `vars`, `getattr`, `open`, `__builtins__`).
An AST check with planted counter-examples enforces this. It is a lint, not a seal (as in (f)).
"A script is a pure function of the transcript and keeps no state" is a rule for script authors.
Review enforces it, and the month-twice test checks it for `moving-average-pm`. Code does not
enforce it. `Usage.cost_usd` is a provider's self-report and is never the meter (R-6).
(h) **The native adapter.** A mind sees `build_server`'s published tool list, narrowed by
`spec.tools`; an unknown name in that list refuses the wake. A call outside the list returns a
tool error and reaches no endpoint. Every other call runs the MCP tool function over HTTP with the
agent's own key, so physics' 403s reach the mind as tool errors. The context is assembled by code
and is the start of the returned `WakeRecord.transcript`: the charter as the system message, then
`{me: whoami, input: workflow_input}` as sorted JSON. **HALT is read (`decide_batch`) before every
model turn and before every tool call.** 03 §3 asks only for "every batch". The auditor's c22 BLOCK
read Art. 5.2's "nothing beyond the current tool call" as covering calls inside a batch, and the
next model turn too, which under R-6 costs money. A per-wake tool-call budget (default 64) also
stops the wake: a batch that would pass the budget does not run at all. The mind is shown deep
copies of the transcript, and its reply is copied on receipt, so nothing a mind holds can rewrite
the record (c22 WARN). A wake ends `done | halted | tool_budget | refused | error`. `error` means the
provider raised (`provider_error:<Type>`) or returned something other than a
`CompletionResponse` (`bad_reply`). An exception from a tool function becomes a tool error.
There is no wall-clock timeout yet: a script that never returns hangs its wake. Timeouts arrive
with the first network provider (R-6). The context is returned in the record, not yet stored.
Storing it is R-4's cassette.
(i) **Red-team 0013: 8 holes (3 medium, 5 low), all fixed in cycle 22.** `tests/test_redteam_0013.py`.
- **H1 (medium).** Tool-list narrowing went by name only. `get_price("../agents")` reached `GET
  /agents`: the open red-team 0001 hole, B-000h. **This is the cycle's one physics-surface change.**
  `mcp_server.tools._segment` percent-encodes every string path value and refuses `""`, `.` and
  `..`. Today the only string path parameter is `ticker`, in `get_price` and `get_ohlcv`; every
  other path parameter is an int. A guard checks the raw path the server routes on. The 0001
  xfail is now a guard.
- **H2/H3 (medium).** `wake()` did not bind the spec to its key: a PM spec woken with
  management's key, or another pod's key, ran. Now `/me`'s (role, pod_id) must equal the spec's
  (role, pod), or the wake is refused (`identity_mismatch`). The agent's name is not compared:
  spec ids and App names may differ until R-3 provisions agents from specs.
- **H4 (medium).** The audit fix's deep copy raised RecursionError on a 600-deep reply, and the
  wake was lost. Fixed together with H5/H6.
- **H5/H6 (low).** Duplicate call ids ran, and non-JSON arguments (objects, NaN) poisoned the
  record. Now copying and checking a reply happens inside one guarded step: call ids must be new
  in the wake, and arguments must survive a strict JSON round trip unchanged. Otherwise the wake
  ends `error`/`bad_reply` and the reply is not recorded, so a record always serialises. One
  held guard moved: a NaN argument used to become a tool error, and now ends the wake before any
  call.
- **H7 (low).** A non-JSON `workflow_input` crashed the wake. It is now refused with `bad_input`
  before `/me` is read.
- **H8 (low).** `wake_policy: never` still woke. It is now refused with `wake_policy_never`. The
  scheduler's own reading of wake policies is R-3's.

Held: spec tricks (empty model, tiny budget, padded or odd script names, YAML `!!python`), odd
tool names, a 10,000-call batch, refused calls counting toward the budget, widening the tool list
through the request, and a dangling-symlink HALT.
Dynamic boundary, measured: with `runtime → mcp_server` in place, importing every runtime module
loads `{app, app.limits}`, within (a)'s set. The probe's moving-average PM is now the script
`moving-average-pm`. It trades a 31-day synthetic month through the adapter, and two runs of the
same world leave the same ledger and the same transcripts. The test still advances the clock with
management's key. R-3 moves that into the Runtime.

Amended (cycle 24, R-3b-1 shipped: `runtime/lockstep.py`, `tests/test_runtime_lockstep.py`):
(j) **The conductor.** `run_backtest(minds, clock, steps=, days_per_step=1, workflow_input=,
max_tool_calls=)` → `RunRecord(ended ∈ completed|halted|refused|error, reason, minds, steps)`.
Each step: HALT is read; every mind wakes once through `native.wake`, one at a time, sorted by
spec id (the caller's order is ignored); HALT is read again; then `POST /clock/advance`. Decisions
made here by the prime rule:
- **A refused wake ends the run** (`refused`, `wake_refused:<id>:<reason>`), with no advance. A
  world that moves on without a mind the run names is not the run that was asked for (more honest
  measurement). A mind that crashes (`error`) or spends its tool budget is data: it is recorded,
  and the run goes on.
- **The conductor checks what it is handed, before step 0.** The clock key's `/me` must have
  role `runtime`, `/clock` must say `backtest`, and spec ids must be unique. Otherwise the run is
  refused (`clock_identity`, `not_backtest`, `clock_unreadable:<status>`, `duplicate_spec_id`)
  and nothing wakes. Physics would refuse a firm agent's advance anyway (403); refusing first
  means no mind acts in a run that could never advance.
- `steps` ∈ [0, 3660] and `days_per_step` ∈ [1, 366] (physics' own advance limit) must be exact
  `int`s.
- The run label `minds` is the sorted, `+`-joined set of providers (`scripted`). Writing it into
  physics' run record is R-3b-2.
- After an early end the clock never moves again, so the ledger shows exactly how far the run
  got. A clock that will not advance (e.g. physics' own HALT, 423) ends the run with
  `error`/`advance_failed:<status>`.

Red-team 0015 (`tests/test_redteam_0015.py`) amended (j) the same cycle:
- **A mind deactivated inside the world is retired, not a world stop** (H1). If a wake is
  refused `no_identity` and the key now gets 401, the mind is listed in `RunRecord.retired`, is
  never woken again, and the run goes on. Otherwise management could freeze the world's time at
  the step it chooses by firing a colleague. That would be a clock lever by the back door, which
  ADR-033 took away. Every other refused wake still ends the run.
- **One App agent is one mind** (H2). Before step 0 every mind's `/me` is read. Its role and pod
  must be its spec's (`identity_mismatch:<id>`), its agent id must not repeat
  (`duplicate_agent:<id>`), and an unreadable key refuses the run (`mind_unreadable:<id>:<status>`).
- **A failed advance records what physics says** (H3). Physics commits `clock_advanced` before
  the sweep, so the clock may have moved. `/clock` is read again, and the step's `advanced_to` is
  the new now if it moved. If physics cannot be asked, or its answer has no `now`, the reason is
  `advance_failed:<status>:clock_unknown`. Without that suffix, "stayed" and "nobody knows" would
  look the same (audit WARN 1).
- **The input is deep-copied once** (H4).

The R-2 month test now drives `run_backtest` instead of its own loop; its assertions are
unchanged. Not yet (R-3b-2): provisioning agents from specs (binding the spec's name), the
Analyst script and the PM + Analyst month, the `fund-runtime backtest` command, and the label in
the run record. The record is returned, not stored (R-4).

Amended (cycle 25, R-3b-2a shipped: `runtime/scripted.py`, `tests/test_runtime_pod.py`):
(k) **A list stays a list on the tool surface.** MCP renders a list returned by a tool as one
text block per item, so a list of one reached a mind as the bare object and an empty list as no
content at all (probed). A PM reading an inbox of one message could not tell it from a message.
Every MCP tool now answers a list as **one JSON array block** (`mcp_server.tools`' shared `call`).
That is the surface every adapter shares, OpenClaw's included (R-7), so the fix is there, not in
the native adapter. No existing test pinned the old shape.
(l) **A pod of two scripted minds.** `ma-signal-analyst` reads the clock and the bars and sends
its pod `{"kind": "signal", "as_of": <now>, "signals": {ticker: long|flat}}`. `signal-pm` reads
the newest 50 messages it can see and trades only on the newest that is addressed to its pod,
comes from an *active* analyst *of its pod by the directory* (not by anything the message
claims), was stamped by physics (`ts`) with the clock's now, and whose payload's `as_of` says the
same. A malformed signal, a stale or pre-dated one, another pod's, one pushed out of the 50 by
later messages, or none means the PM holds (audit c25 NOTEs 1–3: in-sim data, worded exactly). Spec-id order (`a-…` analyst,
`b-…` PM) is how the signal reaches the PM within the same step. In a 31-day month, a second pod
whose PM has no analyst never trades, and every order of pod 1 cites a message its analyst sent
that same simulated day. The same world twice leaves the same ledger and transcripts.
(m) **Carry-overs from the c24 audit.** `WakeRecord.tool_failures` counts calls whose tool
function raised something other than a `ToolError` (physics refusing, App unreachable) or a
`ValidationError` (the mind's bad arguments): a bug under the tool, which the mind sees as an
ordinary tool error. (A `ValidationError` raised by a bug *inside* a tool body would be taken for
bad arguments; no tool body builds a pydantic model today — audit c25 NOTE 4.)
`RunRecord.retired_at` records the step each retired mind left at (NOTE 5). If every
mind is retired, the world still lives its remaining steps with no one awake: the clock is the
Runtime's, not the minds' (NOTE 4). A `no_identity` refusal while the key still answers ends the
run like any other refusal (NOTE 3, now pinned).
Still R-3b-2b: provisioning agents from specs (the name bound), `fund-runtime backtest`, and the
run label in physics' run record.

Amended (cycle 26, R-3b-2b-1 shipped: `runtime/provision.py`, `tests/test_runtime_provision.py`):
(n) **Minds are made from their specs, and a key wears its spec's name.**
`runtime.provision.provision(specs, registrar, connect)` registers one App agent per spec through
`POST /agents/register`. Name, role and pod come from the spec, and `charter_ref` is
`spec:<id>`.
- *Who registers.* The registrar is a key the caller holds, and physics decides whether it may
  register. The `runtime` identity was **not** given `REGISTER_AGENTS` (prime rule, safer seal):
  the clock key stays the narrowest key in the world. A leaked clock key moves time but cannot
  mint puppets. Today the registrar is the operator's seed admin, so every `agent_registered`
  names it as actor. Whether an Era II workflow registers through its own identity is decided
  then.
- *All checked first.* Before anything is registered, every spec is checked, under one read of
  the law:
  - ids and names are unique;
  - the wake gate is open (HALT or a cap refusal provisions nothing);
  - `wake_policy` is not `never`;
  - a mind can be built from it (registry contradictions).
  A spec that could never wake gets no agent. HALT is read again before every registration
  (claim check: a HALT created part-way was not seen until this was added).
- *Part-way failure.* An answer is accepted only if it is the agent asked for: the name, role
  and pod match, the id is an int not already seen in this call, and the key is not empty.
  Otherwise `ProvisionError(reason, registered)` names the specs already registered, the failing
  one included if its answer was wrong. Their clients are closed. Those agents exist, so the run
  database is spoiled (ADR-027).
- *The name is bound.* `native.wake` and `run_backtest` compare `/me`'s **name** as well as role
  and pod (`identity_mismatch`). A caller may still hand in clients it made, and the name holds
  them to their specs.
- *Finding.* 65 older runtime tests broke because their fixtures handed a key under another
  name: spec name = spec id, agent `pm-1`. That is the gap this law closes. Only the fixtures
  were changed, to name the agent they register. No assertion changed. **But** (audit c26
  BLOCK 1) in four guards whose purpose is a role or pod mismatch (0013 H2/H3, lockstep
  wrong-pod, 0015 clock-key-as-mind), the new names also mismatched. Those guards would have
  passed on the name check alone, so the role and pod checks were left unpinned. Fixed: each
  spec now wears its key's own name, so only the role or pod differs. Two new tests check a
  right name with a wrong role and a right name with a wrong pod, through both the wake and the
  conductor.
- *Red-team 0016 amendment* (4 low holes, all fixed, guards in `tests/test_redteam_0016.py`):
  - H1: a 5xx answer (lost after physics committed) now names the failing spec as possibly
    registered. Only a 4xx proves nothing was made.
  - H1b: a failing `connect`, or any other exception from the POST, is a `ProvisionError`
    naming what may exist.
  - H2: names are unique **under physics' fold** (`provision.name_key`, a copy pinned to
    `app.registry.service._name_key` by a test, since runtime imports no `app`).
  - H3: reserved names (`name_reserved`) and names already in the directory (`name_taken`,
    read through the registrar's `GET /agents`) are refused before anything is registered.
    A registrar that cannot read the directory is refused (`directory_unreadable`). A name
    taken in the window between that read and the POST still fails closed with a 409.
  - Seen, not filed: management keeps `REGISTER_AGENTS`, so in Era II a management mind could
    take a future spec's name first. It fails closed, but it is a way to block a spec (→
    BACKLOG).
- *Proof.* The R-3b-2a two-pod month now runs with minds provisioned over HTTP.
Still **R-3b-2c**: `fund-runtime backtest` and the `minds:` label in physics' run record
(physics → red-team).

Amended (cycle 27, R-3b-2c-1 shipped: `runtime/cli.py`, `specs/desk-month/`,
`tests/test_runtime_cli_backtest.py`, `scripts/smoke_run.py` backtest phase):
(o) **A run starts from one operator command.** `fund-runtime backtest --specs DIR --steps N
[--days-per-step D] [--input FILE] [--max-tool-calls K] [--server URL]` provisions one App agent
per spec and conducts the run, then prints `{ended, reason, registered, run}` as JSON (`run` =
the RunRecord, `record_json`). Exit 0 only for `completed`; 1 for a refusal or an early end; 2
when the command itself is wrong, before anything is contacted.
- *Keys from the environment only* (`FUND_RUNTIME__REGISTRAR_KEY`, `FUND_RUNTIME__CLOCK_KEY`):
  argv is visible to every user through `ps`. One key for both jobs is refused (the clock identity
  registers nobody).
- *No key in the form physics mints is printed* (`cli.redact`, `fk_` + url-safe base64, over the
  serialized text). Audit c27 BLOCK 1: the first version claimed "no key is printed" because no
  record holds one. False: a management mind's `register_agent` result carries the new key, and
  the transcript keeps tool results as they came. Tested with a scripted management mind that
  hires; the test fails without `redact`. A key a mind re-encodes is in-world data (Art. 8), not
  covered. **R-4 inherits this:** a cassette stores the same transcripts, so it must redact too,
  and a replay that meets a redacted key is a recorded divergence.
- *No proxy* (audit c27 WARN 1): `FundClient` sets `trust_env=False`, so neither `HTTP(S)_PROXY`
  / `ALL_PROXY` nor the OS proxy settings can route a key off the machine. This covers every
  `FundClient`, the MCP server's included.
- *The clock is checked before anything is registered* (`lockstep.check_clock`, shared with the
  conductor): the clock key must be the `runtime` role on a `backtest` run. Without this, a live
  database, or a wrong clock key, would gain the run's agents and only then be refused.
- *Sizes are checked before anything is registered*, against the conductor's own bounds, plus
  `--steps ≥ 1` (0 would make the run's agents and live nothing, audit NOTE 3) and
  `--max-tool-calls ≤ 1024` (WARN 2).
- *The server must be on this machine* (`127.0.0.1` or `::1`; http(s); no userinfo): the keys go
  wherever the URL points. `localhost` is refused: it is whatever `/etc/hosts` says (NOTE 1).
  Prime rule, safer seal; widening it is a later, explicit decision.
- *No specs* is refused: a run with no minds would only move a run database's clock.
- `specs/desk-month/` is the R-3b-2a pod (analyst + PM, pod 1) as files. The smoke run now
  builds a synthetic backtest database with the real `fund-env` commands, serves it, and runs
  `fund-runtime backtest` on it for 5 days: 10 wakes, all `done`, at least one PM order
  accepted by physics, no key in the output.
Why: (1) M1 needs the month to be started by the operator, not by a test harness. (2) Safer seal:
every refusal the command itself makes (usage, clock, sizes) comes before the first
registration (ADR-027: a part-way refusal spoils the run's database). Provisioning can still
stop part-way (HALT between registrations, a name taken in the race window, a lost answer);
then `registered` names what may exist. Not done here: physics' own record of `minds:` (R-3b-2c-2:
physics cannot see what drives a key, so the label is a declaration, and who may declare it is a
design question for that slice), writing the RunRecord to a file (R-4's cassette).

(p) **Physics records what drives a run's minds** (R-3b-2c-2, cycle 28, `tests/test_run_minds.py`).
Physics cannot see what is behind a key, so the label is a *declaration*, and physics guarantees
only *who* makes it and *when*:
- *Who:* `POST /run/minds {minds: [...]}` under `CONTROL_CLOCK`, the conductor's hand (the runtime
  identity; `system` in code). There is no new permission: the runtime role still holds
  `READ_HALT`, `READ_CLOCK` and `CONTROL_CLOCK`, nothing else. A firm agent gets 403 and a
  `permission_denied` event.
- *What:* one or more kinds from the closed `app.run_clock.MIND_KINDS`: `scripted` (code),
  `cassette` (recorded model output played back), and `model` (a model answering now). Each kind
  appears once; extra fields get 422. The event is `run_minds_declared {minds}`, sorted. The
  Runtime declares the kinds of its specs (`lockstep.mind_kinds`). **A mind is `scripted` or
  `cassette` only if both its provider and its adapter are in the gate's zero-cost sets.
  Anything else is declared `model`**, so an unknown mind is never labelled as code. Audit c28
  WARN 1: the first version looked at the provider only, which would have labelled `scripted` +
  `openclaw` (OpenClaw's own model) as code. ADR (4)'s
  `minds: replay` is spelled `cassette` here: physics names what plays, not what the run is for.
- *When:* backtest runs only (a live run's agents are not conducted), **once**, and only while the
  clock has not moved and no firm agent (any non-physics actor) has written an event. A refused
  act counts, because its `permission_denied` names the actor. Physics' own setup (seeds, actor
  null) and the runtime's own events do not count. So a declaration precedes every event a firm
  agent wrote. Reads write nothing, so an agent that already existed (the registrar) may have
  read before it (audit c28 WARN 3). The run's own minds are registered after it. `fund-runtime backtest` declares right after `check_clock` and **before it
  registers anyone** (registrations by the registrar are firm acts). A run whose firm agent
  already acted is refused (`minds_refused:409`) before any agent is made. Under HALT, physics
  refuses with 423. A firm agent cannot forge a label, but one that already exists can spoil a
  run before its declaration by writing any event, a refused one included. The run then stops
  as `minds_refused:409`: that is a way to stop a run, not to fake one. If provisioning refuses
  after the declaration, the declaration stays and the database cannot be declared again. That
  is acceptable: a backtest database is single-use (ADR-027; audit c28 NOTE 4).
- *Reading:* `run_minds(session)` returns the first declaration's kinds, or `None`. It also
  returns `None` for a live run, an undeclared run, or a first declaration the ledger shows came
  after a firm act or an advance. It reads only declarations a physics hand wrote (audit c28
  NOTE 3). The check and the append run under `OMS_LOCK`, but writes that take no lock (a
  message) can land between them. The reader trusts the ledger's id order, not the lock. A
  second declaration needs a second process on the same database (`OMS_LOCK` is per process,
  B-036) or a direct ledger write. It is never read (audit c28 WARN 2).
- *Not done:* no `GET` of the run record. That would hand every agent `run_started.world`, the
  market's law (drift, volatility). The claim check found that **management can already read
  it** through `GET /events` (`READ_CROSS_POD`): B-049. Readers use the ledger, and a report
  surface is later work. Undeclared runs stay legal: older tests and runs never declared, and they read as
  `None`, never as `scripted`. Q-0005 is unchanged.
- *Old test that changed, a finding of the new law:* red-team 0014's
  `held_every_route_but_me_clock_halt_refuses_the_runtime_key` lists the routes that answer the
  runtime key. `POST /run/minds` joined that list. The sweep still proves that every other
  route refuses the key.
- *Red-team 0017* (`tests/test_redteam_0017.py`: 4 holes, all fixed the same cycle) amended (p):
  - **H1 (medium), H2 (low): the ledger has the last word on the answer too.** After its commit,
    `declare_minds` re-reads the ledger. If its event is not the first physics-written
    declaration, or a firm act precedes it, the endpoint answers 409 ("lost a race"). The event
    stays (append-only) and is never read. Before, a firm message in the check/append gap, or a
    second process's declaration, got 201, and the Runtime lived a month that read as `None`.
  - **H4 (medium): a declaration covers only the agents registered after it.** It names kinds,
    not agents, and an older agent's key could be in any hand (an OpenClaw model). `run_minds`
    returns `None` if any firm agent not registered after the declaration writes any event other
    than a registration after it. The exemption for registrations is the registrar making the
    run's minds: it trusts the holder of the registrar key, and each agent it registers is
    covered. So a pre-existing agent can void a label after the fact by any act, a refused one
    included. That is a true statement about the run (an undeclared hand acted), not a forgery.
    The red-team's own HELD guard `firm_acts_after_the_declaration_never_void_it` first acted
    through pm-1, an older agent. It now acts through an agent registered after the declaration:
    a finding of the H4 fix, which makes pm-1's acts void the label on purpose.
  - **H3 (low, every route): a lone surrogate (`"\ud800"`) in a body made the 422 handler 500.**
    `json_safe` now re-encodes strings (keys included) with replacement.
  - Held: firm agents cannot declare (HTTP or MCP); lookalike, padded, huge, deep or mistyped
    kinds get 422 and write nothing; deactivated agents still count; actor-null setup and key
    rotation do not spoil; HALT fails closed; forged rows by null or firm actors are never read;
    a live run never reads one.
- *Smoke run:* the backtest phase reads the database file and checks that there is exactly one
  declaration, `["scripted"]`, before the first firm event. Its market key is now fixed (a
  hash of `fund-smoke-world/1`). With a random key, some draws gave five days with no `long`
  signal, so the "an order was accepted" step failed on the world's luck, both on this branch
  and potentially on `main`.

## ADR-033 — The world's clock belongs to the Runtime: a reserved `runtime` identity   (builder, cycle 23) — accepted
Question: ADR-027 gave `CONTROL_CLOCK` to `management` (TRD §6). A management agent is a firm
agent, a participant. Once an LLM manager wakes, it could stop, speed up or time its own world's
clock: a participant would hold a world lever (Art. 10, B-032). The lockstep conductor (R-3b)
needs a hand on the clock that no mind holds. Separately, `system` was found by *name*, and
management could register an analyst called `system` first (red-team 0001, B-000f).
Answer from the future: (1) **A new role, `runtime`**, holds `READ_HALT`, `READ_CLOCK` and
`CONTROL_CLOCK`, and nothing else (`/me` needs no permission). It has none of a participant's
actions: no orders, messages, registrations, market data, directory or events. It also lacks the
inbox, cost and task actions every firm agent has (audit c23 NOTE 5), so nothing it writes can
pass for agent activity.
**`management` loses `CONTROL_CLOCK`. This deviates from the TRD:** TRD §6 implies
management/system, and ADR-027 says management. `system` keeps every action (it never
authenticates). (2) **Physics' roles** (`PHYSICS_ROLES = {system, runtime}`, in
`permissions.py`) are never registered: `RegisterableRole` excludes them (422), and
`register_agent` raises `ReservedIdentityError`. Firm agents cannot deactivate them: a 403 plus a
`permission_denied` event with `target_agent_id`. (3) **The runtime identity is created only by
`fund-env seed-runtime`** (`seed_runtime_agent`). There is one per database: a second is refused,
and the unique name `runtime` backs that up at the database level. It is recorded as an
`agent_registered` event (actor null), and its key is shown once. (4) **`system` is found by
role** (`role == system`, lowest id). The names `system` and `runtime` are reserved, compared
after NFKC, casefold, dropping Unicode Cf characters and stripping whitespace. Cross-script
lookalikes (Cyrillic `с`) are *not* folded. The identity is the role; the reserved name only keeps
the directory honest. A database written before this ADR that has a non-system agent named
`system` makes `get_or_create_system_agent` raise. It never borrows that identity; the operator
must rename the agent. (5) **No migration**: the role column is a non-native enum (VARCHAR 16)
with no CHECK constraint, so `runtime` fits as it is.
Old tests that broke and are findings of the old law (not fixed to pass): 9 test files advanced
the clock over HTTP with management's key. They now use a runtime key, with every assertion kept. Three
assertions got *stronger*. Management is now in the 403 list (`test_only_clock_control_advances`).
A live run gives management 403 *and* the runtime identity 409 (`test_redteam_0005`,
`test_redteam_0007`). `test_oms_permissions` covers every `AgentRole`, `runtime` included. Rows for
physics' roles are built through the private `_create_agent`. The red-team 0001 squat xfail is now
a guard (xfails 7 → 6). `tests/test_runtime_identity.py` holds the new law.
Not done: key rotation for a lost runtime key (re-seed needs a fresh database or a new operator
command, when R-3b needs it); B-034 (operator CLI ignores HALT) is unchanged; the Runtime does not
use the key yet (R-3b). Tie-breaker: safer seal first. The conductor is built on the right
identity, not moved onto it later.
(a) **Red-team 0014: 1 hole (low), fixed in cycle 23.** `tests/test_redteam_0014.py` has 30
held guards; the 20 hole tests are now guards too. **H1:** the fold dropped only Cf, so names
like `runtime` + U+FE0F, U+034F, U+17B4, the Hangul fillers, U+2800 or NUL were accepted (201),
and the directory showed a second "runtime". Physics was not fooled, because the role gates
`CONTROL_CLOCK`. The fold now drops every category that draws nothing (Cc Cf Cn Co Cs Mn Me)
plus the blank letters `U+115F U+1160 U+3164 U+FFA0 U+2800`. Dropping a visible combining mark
only widens what counts as reserved. Held: every published route walked with the runtime key
(a coverage assert proves the walk is complete); firm keys × every advance body; HALT × method
tricks; deactivation; physics roles in HTTP, service and spec; a racing second seeder (the unique
name stops it); attribution of `clock_advanced` and sweep fills; `seed-runtime` on a backtest DB
(run-time stamp), on a live DB (409 on advance) and under HALT (it seeds; the key gets 423); an
alembic-built DB; rebuild-state. Left open, not holes: a lost runtime key freezes that backtest
(B-041); a firm agent's own name can carry invisible characters to pass for a colleague's,
which predates this ADR and is in-sim scheming (B-042).
(b) **A way back from a lost clock key, and the reserved names checked at startup (B-041,
cycle 24).** `tests/test_runtime_key.py`. `fund-env rotate-runtime-key` (`rotate_runtime_key`)
replaces the one runtime identity's key hash. The old key gets 401 in the same commit. It
records `agent_key_rotated` with payload `{agent_id}` and actor null: never the key or its hash.
It refuses a database with no runtime identity, or with two. It is operator-only; no endpoint
rotates a key, because a firm agent rotating the clock hand's key would be pulling a world lever.
`reserved_identity_problems` / `check_reserved_identities` find (i) a non-physics agent whose
name folds to a reserved one, and (ii) more than one runtime row. The server's lifespan runs
the check *before* it installs the run's clock, so a refused start leaves the process clock
alone. Every operator command that runs on the database's clock runs it too (all but
`init-db`, `start-backtest` and `serve`, which gets it from the lifespan). A pre-ADR squatter
now stops the world at startup, not at the first act that needs `system`. The operator repairs
the database by hand. There is no rename command (prime rule: smaller; physics never renames
an agent). Old test that changed, a finding of the new law: red-team 0014's
`held_a_pre_adr_runtime_squatter_blocks_seeding_loudly` still gets exit 1 and no runtime row,
but the reason is now the startup check naming the squatter, not `seed-runtime`'s "already
exists". The assertion now checks the new, more precise message.

## ADR-034 — The operator's facts about the experiment are withheld from every agent   (builder, cycle 29) — accepted
Question: ADR-031 put the market's record in `run_started.world` (synthetic: law, origin, drift,
volatility, symbols, fingerprint; static: the price table). ADR-032 (p) put the minds' kinds in
`run_minds_declared.minds`. Management reads both through `GET /events` (`READ_CROSS_POD`).
The drift and volatility of a GBM world are the edge itself: a participant holding them is not
measured, it is told the answer (Art. 9, Art. 10). Found by the cycle-28 claim check (B-049).
Answer from the future: **The ledger keeps the full record; an agent never reads it.**
`app.ledger.events.AGENT_WITHHELD_FIELDS` names, per event type, the fields an agent reads as
`"withheld"`: `run_started.world` and `run_minds_declared.minds`. The rule has one home:
`EventOut`, the only response shape in `app.api.schemas` that carries a payload (a test pins
that), applies `agent_payload` after validation. It builds a new dict, so the ORM row is never
touched and no commit can write the redaction back. Physics (`install_run_clock`, `run_minds`,
both tested after agent reads) reads the database, whole, as does the operator, who reads the
file. The minds' kinds are withheld too (prime
rule: safer seal): whether the colleagues are code or a model is the scientists' label, not a
fact of the world, and a mind that knew its peers were scripted could exploit them. The field
stays, with a marker, so a transcript shows that something was withheld rather than nothing
recorded. `mode`, `start` and `look_ahead_guard` still pass through (`/clock` already says the
mode).
Old tests that broke, findings of the new law: red-team 0011's
`held_only_management_reads_the_world` and `test_run_world`'s
`management_sees_the_fingerprint_never_the_key` asserted that management reads the fingerprint.
Both now assert it is withheld; every other assertion is kept. `tests/test_world_withheld.py`
holds the new law.
Not done: the operator has no API read of the world (it reads the file; none is needed). The
symbol universe is not otherwise published to agents (charters name it today). Truman will
decide what a mind is told about its world.

## ADR-035 — The Builder is a team: judgment on opus, execution on sonnet   (Human direction, 2026-10-12) — accepted
Question: every Builder cycle ran on opus end to end, in an unbounded loop. Measured over 35 cycles:
$1.2–4.8 a cycle, $6–7.6 with a red-team pass; most of that was the review subagents (runs that
crashed after one lead turn still cost $3–4.7). The Human asked for cheaper cycles without
weaker work, and a team robust enough that later adjustments stay safe.
Answer from the future: **Models follow the kind of thinking, and the Human owns the
assignment.** `governance/human.yaml` → `builder.team` is the single place models are chosen:
lead (the main session) on sonnet; the lead on opus for diagnosis, every 10th cycle
(retrospective) and the cycle after a failure; a new sealed `architect` subagent (opus) that
plans every unit before code is written (Gate 2 in `.claude/commands/cycle.md`); `auditor` and
`red-team` on opus; every other subagent on sonnet. `loop/seal.sh` writes the subagent models
into their frontmatter, `loop/preflight.py` refuses to start a cycle if the two disagree or a
value is invalid, and `--post` logs cost per model per cycle and flags a merge that used no
auditor-model tokens. Frontmatter beats the `CLAUDE_CODE_SUBAGENT_MODEL` default (verified live).
The loop is bounded (`loop/builder.sh start` runs `cycles_per_run`, then stops) with per-cycle,
per-run and per-day USD caps that a cycle may never overshoot.
Why this split: planning, review and attack are where a wrong call costs a cycle or lets a hole
into physics; implementing a precise plan is where most tokens go. The plan makes the lead's
job execution; the gates catch what execution misses; failure escalates the lead to opus.
Process changes in `protocol/CYCLE.md`: plan step, scoped re-audits, precise briefs, context
hygiene (big state files are tailed or grepped, never read whole).
Not done: no automatic per-unit model choice (the architect cannot switch the lead's model
mid-session); no haiku anywhere (review quality first). Measure with `cycles.log` (cost and
models per cycle) and `state/METRICS.md` (results) before tuning further.

## ADR-036 — What Era I's test criteria EC3, EC5 and EC6 mean when a test ticks them   (builder, cycle 30) — accepted
Question: three Era I exit criteria are "test" criteria (ADR-032): look-ahead refused (EC3),
HALT mid-run stops within one tick (EC5), and `cap: null` → the Runtime refuses to wake agents
(EC6). The gates behind them were built in cycles 16, 21 and 22, but no test drove them as a
run does, so none was ticked. What counts as meeting each one?
Answer from the future: **a criterion is met only end to end.** A mind run by the conductor
(`lockstep.run_backtest`) acts through the published MCP tools, over HTTP, into physics. The
tests are in `tests/test_runtime_lockstep.py`, section "Era I exit criteria (R-5a)":
- **EC3 — "refused".**
  - A window that starts after the clock's now is a tool error carrying physics' 400 (`no
    look-ahead`): `test_ec3_a_mind_asking_for_tomorrows_bars_is_refused`.
  - A window that runs past now is served clipped. No bar in it ends after the step's now:
    `test_ec3_a_window_past_now_holds_no_bar_that_has_not_ended`.
  - The clock is in no firm agent's hand: a mind's `advance_clock` is a 403, and every advance
    is the runtime identity's (`test_ec3_a_mind_cannot_reach_tomorrow_by_moving_the_clock`,
    ADR-033).
  - `get_price` takes no instant, so a mind cannot name a future one.
  - Tested over a `StaticProvider` (flat bars). The test proves the structure (what is
    withheld), not values. ADR-028's tests carry the guard's base.
- **EC5 — "within one tick".** The tool call in flight when HALT appears finishes. After it
  there is no further call, no wake of a later mind, no advance and no new event (Art. 5.2):
  `test_ec5_halt_created_during_a_tool_call_stops_the_run_within_that_call` and
  `..._halt_on_the_last_call_of_a_step_wakes_no_one_and_moves_nothing`.
  Planted counter-example: removing the per-call HALT read in `native.wake` turns the first one
  red.
- **EC6 — "refuses to wake agents"** means *spending* minds: Q-0005 answer B, pending the
  Human.
  - A spending spec is refused before a provider is even built, so no provider exists to call:
    `test_ec6_cap_null_never_builds_a_spending_mind`.
  - A numeric cap refuses too until R-6 (`no_metered_key`).
  - Zero-cost minds still wake (the control).
  - If the Human answers Q-0005 with A, a scripted case joins EC6 and the tick is re-checked.
Not done: B-053. `fund-runtime backtest` provisions agents and declares `/run/minds` *before*
any wake gate refuses. Under a null cap, a spending spec therefore leaves registered agents and
a `model` label on a run in which nothing woke. Nothing spends, so EC6 holds. But the ledger
tells a misleading story, and the fix changes Runtime gate code (its own cycle, with a
red-team). EC1, EC2, EC4 and EC7 are untouched.

## ADR-037 — R-4a: a run writes a cassette file   (builder, cycle 31) — accepted
Amends ADR-032 (7). Question: what does a run leave behind so that R-4b can replay it at $0,
without storing a minted key and without a hash that matches by luck?
- **One file per run**, `*.cassette.json`, written by `fund-runtime backtest --cassette PATH`,
  not a table. A run is a proof object that can be carried around (`09_BUILDER_VISION.md` §2).
  Gitignored (`*.cassette.json`, `experiments/*/runs/`: B-000i), created `O_EXCL | O_NOFOLLOW`
  with mode 0600, never overwritten. The path is checked in the usage phase (exit 2, nothing
  contacted) and again by the open itself.
- **What an exchange stores:** `(seq, request_sha256, usage | None)`
  (`runtime.native.Exchange`, `WakeRecord.exchanges`). Deviation from (7)'s "request, response":
  neither is stored again. The request is the transcript before the `seq`-th assistant message
  plus the wake's tools plus `spec.model`; the response is that assistant message. `usage` is
  `None` exactly when no assistant message answers the exchange (the provider raised, or
  `bad_reply`), so a failed turn is a recorded exchange, and a turn never asked (HALT first) is
  not.
- **The hash** (`cassette.request_sha256`, `HASH_FORMAT = sha256/json-sorted-compact-ascii/1`)
  is taken in `native.wake` after the request is built and **before** `provider.complete`,
  because a mind holds the object it is given. It is of the *unredacted* request, so a request
  holding a minted key diverges on replay (B-047, decided). Pinned by a golden vector whose
  canonical JSON is written out by hand in the test. Tool descriptions and schemas are inside
  every request: editing one invalidates old cassettes, which R-4b must call "surface changed",
  not a bug.
- **Redaction** is at the way out, not the source (B-047 decided): `native` keeps what the mind
  saw, and both stdout and the file redact (`cassette.redact_count`, on the serialised text,
  so object keys, values and JSON nested in strings are all covered; the count is stored). A
  key a mind re-encodes is not caught (Art. 8). Two keys that redact to one object key leave a
  duplicate key in the text: R-4b's reader must reject duplicate keys.
- **A cassette is written for every invocation that passed the usage checks**, refused ones
  included (`run: null`; Art. 9: no trial is hidden). A write that fails after the run exits 1
  and the outcome was already printed. The printed JSON **gains** `exchanges` in every wake
  record (`record_json` dumps every field); `--cassette` adds two exits: 2 for a path that
  cannot be written (before anything is contacted), 1 for a run that completed but whose
  cassette could not be written.
- **Byte-for-byte determinism has one exception:** the exchange hash is of the unredacted
  request, so once a mind is handed a minted key (`register_agent`) every later hash in that
  wake differs run to run, while the redacted text does not (B-047, decided above). Two equal
  scripted runs that mint no key write equal bytes (`test_runtime_pod`). R-4b treats a minted
  key as a divergence by design.
- **Known, accepted:** the cleanup after a failed write unlinks by path, not inode; `redactions`
  also counts `fk_…` text in a mind's prose.
- **Finding (an old law broke a design, the law stayed):** `request_sha256` first went into
  `runtime.providers`. `tests/test_redteam_0013.py::test_held_scripted_module_has_no_reach_via_its_shapes`
  pins that module to `{__future__, typing, pydantic}` (a script's only non-stdlib import) and
  went red on `hashlib`/`json`. The hash moved to `runtime.cassette` (stdlib only, imports no
  physics and not the conductor); the test was not touched.
- **Not done:** replay, the `cassette` provider, `minds: replay` (R-4b); hashes linked from
  events (a physics change, its own red-team); a cassette step in the smoke run; a size cap
  (bounded by `max_tool_calls` and context growth). EC1, EC2, EC4, EC7 are not ticked.


## ADR-038 — R-4b-1: a replay drives the minds from a cassette   (builder, cycle 32) — accepted
Amends ADR-032 (4)(g)(j) and ADR-037. Serves EC2's test half; **ticks nothing** (ADR-032 leaves EC2
to real minds, R-8). Plan by the architect; red-team: see the cycle-32 entry in the journal.
- **What shipped.** `cassette.read` (the canonical-v1 reader), `runtime/replay.py` (`Recording`,
  `Tape`, `CassetteProvider`, `as_cassette`), `registry.check_spec` + `build_provider(spec, tape)`,
  `native.wake(tape=)`, `run_backtest(replay=)`, run end `diverged`. In process only: no CLI yet.
- **The label is `cassette`, not `replay`.** Physics' kind (`app.run_clock.MIND_KINDS`) and the
  sorted provider name are both `cassette`; Q-0005 wrote `minds: replay`. Reuse over a physics
  change. Noted for the Human in `state/QUESTIONS.md`.
- **Where the tape enters.** As data: `wake(tape=)`, and the registry builds the mind from it only
  if `type(tape) is Tape` and the name is `cassette`. A tape on `scripted` is a `contradiction`;
  no tape (or a subclass, a dict, a provider) on `cassette` is `unavailable`. The no-provider-object
  law holds, and the gate is unchanged (`cassette` was already on `ZERO_COST_PROVIDERS`).
- **Provisioning** now calls `check_spec` (every contradiction, no tape needed) instead of
  building a provider; a test pins that `cassette` with a model, a budget or a script is refused.
- **The reader refuses anything but the canonical v1 document**: it re-serialises the parsed
  outcome with the writer's own assembly and demands equal text. That rejects pretty-printing,
  reordered keys, a second version or hash format, extra keys, NaN, non-ASCII, repeated keys (two
  minted keys that redact to one object key included: the writer cannot see it, the reader
  does), a symlink, a non-regular file. **No size cap yet** (a hostile file can be large).
- **A miss ends the run.** `diverged:<id>:<step>:<seq>:<kind>`, kinds decided from the two
  records, never from reason strings: `unrecorded`, `world` (the transcript before the turn
  differs), `key` (equal, except the recording holds a redacted minted key), `surface` (equal
  transcript, different request: tools or model changed), `ended` (all hashes matched but the
  wake ended differently or earlier). The step is recorded with `advanced_to=None`, nothing wakes
  after it and the clock does not move. Only HALT is not a divergence: any other refusal (a mind
  retired in the replay included) is, because a completed recording woke every mind every step.
  (Found by me while claim-checking: the first version skipped the check for every refusal, so a
  retired mind let a replay finish `completed`. Pinned by a test and a mutation.)
- **Replay costs nothing and says so**: replies carry `Usage()`; the recorded cost belongs to the
  recording. A recorded failed turn replays as a failure (`provider_error:ReplayedFailure`), not
  a divergence.
- **What replays.** A canonical v1 cassette of a `completed` run, no retired mind, whose specs have
  no `model` (v1 does not record the model; a model-bearing recording needs cassette v2).
- **Known, accepted:** responses are not hashed. A cassette edited in its replies while the request
  hashes are kept replays the edited replies, within the agent key's own permissions and under
  the `cassette` label. Only a ledger comparison against the original catches it (R-4b-2).
  Cassette bytes are trusted as far as a file you chose to read is.
- **Finding (an old pin moved, with its reason):** `test_the_adapter_takes_no_provider_object` pinned
  `wake`'s parameters to four names; `tape` is a fifth. The pin now names it and says why; the
  stronger tests are the tape-type ones in `tests/test_cassette_replay.py`. One spy in
  `test_runtime_lockstep` (`_built`) took `build_provider(spec)` and now passes the tape through;
  its assertion is unchanged.
- **Evidence.** The recorded 31-day scripted month (3 minds), replayed into a fresh database in the
  same world, leaves the same ledger event for event, the same transcripts and request hashes, at
  zero usage. World 12 diverges (`world`); narrowing the tool list diverges at turn 0 (`surface`).
  1485 → 1527 passed, smoke 21/21.
- **Not done (R-4b-2 and later):** `fund-runtime replay`; cassette v2 (run parameters, spec
  digests, each wake's model); a cassette step in the smoke run; hash links from events (physics,
  own red-team); `tools_sha256`; a size cap; replaying a run that did not complete; mixed
  live/replay minds (Era II fork instrument). EC1, EC2, EC4, EC7 stay unticked.

**Amendment (a) to ADR-038 — red-team 0018 (6 holes, 8 tests, all fixed) and audit c32 (PASS, 0 BLOCK).**
- **The recording's calendar is replayed** (H1). `Recording` keeps each step's `at` and
  `advanced_to`; a replay whose step starts, or lands, on another time ends
  `diverged:clock:<step>:0:calendar`. A changed start date or `days_per_step` can no longer finish
  `completed` just because no mind read a dated value. (`max_tool_calls` and `days_per_step` are
  still not recorded as parameters: v2.)
- **A recorded `tool_budget` stop is reproduced** (H2): that wake gets `min(recorded calls, the
  caller's budget)`, so a replay never runs a batch the recording never ran. A smaller caller
  budget still diverges (`ended`), before any further act.
- **A tape is data all the way down** (H3): `Turn`, `Tape` and `Recording` check exact types on
  construction (a `str` subclass equal to every hash, or a "reply" with its own `model_copy`, is
  refused with `RecordingError`).
- **A completed run holds no refused or turn-less wake** (H4), and `seq` must be an exact int (H5):
  a forged "completed, nobody retired" file can no longer retire a mind quietly.
- Audit c32: a FIFO is refused (`O_NONBLOCK`; the Mac never blocked, Linux would); the cassette
  builder is bound to the name `cassette`, so a later provider cannot fall through to it.
- **Not done, on the backlog:** a setup error (contradiction, `unknown_tool`, `identity_mismatch`)
  during a replay reads as `diverged:...:ended` with the real reason only in the wake record
  (audit NOTE 4); `key` can mislabel a surface change when the recorded prefix holds a redacted
  key (NOTE 5); `workflow_input`, `max_tool_calls` and `days_per_step` become recorded parameters
  in cassette v2. The forged-reply limit stands: replies are not hashed, so a cassette with
  consistent forged hashes encodes any policy, within the agent key's permissions.
- Suite 1485 → 1554 passed + 6 xfailed; smoke 21/21.

## ADR-039 — A usage-limit cut-off is not a failed cycle   (Human-directed loop repair, 2026-10-13) — accepted
Question: cycle 33 spent $1.01, got its plan, then hit `429 usage_limit_reached`. The runner
called it `failed` (a limit counted only at cost 0), raised the failure counter, and the plan was
lost. How should the loop treat a session the API cut off?
- **Classification (`loop/preflight.py`, Human-installed):** read the final result object:
  `api_error_status ∈ {429, 529}` or an `api_error` naming a limit/overload/quota → a limit; an
  errored result whose text names a limit → a limit; no result object at all → the old text
  markers. Anything else that did not advance `loop_status.json` is still a failure (a max-turns
  or max-budget stop is a real signal that the unit was too big).
- **Accounting:** a limit is logged `result=limit cost=…`. Its dollars count toward the day's cap
  (honest measurement of spend), it does not use a daily cycle slot, it does not touch the failure
  counter, and the runner stops (it never retries on its own).
- **Recovery is resuming:** `protocol/CYCLE.md` X-012 saves the architect's plan in a commit
  before the build, and the resume rule distinguishes an empty branch (re-plan, same number),
  a plan-only branch (build) and a built branch (verify).
- Rejected: auto-retry after the reset time (a cap must end the run, `builder` rules); counting
  limits as failures with a higher threshold (it would still promote the next lead to opus).
- Tests: a scratch check of the staged file against the real cycle-32 (merged) and cycle-33
  (limit) logs plus synthetic max-turns, 529, plain-text cases: 14 checks. Not in `tests/`: the
  file is the Human's and has no pytest suite.

## ADR-040 — `fund-runtime replay`, the refusal law, `fund-env compare-ledgers` (R-4b-2a; amends ADR-038) — accepted
Question: R-4b-1 replayed only in process, a replay's setup refusal read as `diverged:…:ended`, and
nothing compared a replay's ledger with the recording's. What is the operator path, and who checks
the ledger?
1. **Who compares the ledgers?** Physics' operator command `fund-env compare-ledgers RECORDED REPLAYED`
   (`app/ledger/compare.py`), read-only (`mode=ro`; a missing path is exit 2, never a new database).
   The Runtime stays ledger-blind (ADR-022, ADR-033): it imports no ledger code and the `runtime`
   role gained no permission. Prime rule: keeps the seal.
2. **A setup refusal in a replay is a refusal.** A replay ends the way a live run would at every wake
   a live run would stop: `wake_refused:<id>:<reason>` for every refusal except a retirement
   (`no_identity` + a 401 key), which a live run absorbs and a replay cannot (the recording woke
   every mind): that is `diverged:…:ended`. A HALT seen at the top of a step or after a wake is
   still `halted`. **Known, unchanged since cycle 24 (audit c33 WARN):** a HALT that lands between
   one mind's wake and the next makes that wake return `refused`/`halted`, which ends the run
   `refused` (`wake_refused:<id>:halted`) in live and replay alike; nothing wakes after it and the
   clock does not move, so Art. 5 holds, but the label is `refused`. Under HALT, `declare_minds`
   likewise ends `refused:minds_refused:<code>`. Mapping both to `halted` touches the halted branch
   (a red-team slice): backlog B-054. Closes audit c32 NOTE 4.
   Accepted: an in-world act that makes the recorded identity differ (a mind moved or renamed)
   ends `refused:identity_mismatch`, not `diverged`; the run still exits 1, never `completed`.
3. **Parameters of a v1 replay.** Steps come from the recording (`replay` has no `--steps`); input,
   days-per-step and max-tool-calls from flags. A wrong input ends `diverged:…:0:world` at turn 0, wrong
   days `diverged:clock:…:calendar_landed`, a budget through H2 (ADR-038 (a)). Recording them is
   cassette v2 (R-4b-2b). A spec with a `model` is a usage error (v1 replays scripted runs only).
4. **Strict comparison.** Equal length and every row equal as raw text (id, ts, actor, type,
   `payload_json`), with exactly one allowed difference: the single `run_minds_declared` row, whose
   replayed payload must be exactly `{"minds":["cassette"]}` and whose recorded payload must be a valid kind
   list; its id, ts, actor and type stay equal. Stricter than EC2's "except ids/wall-clock": a
   difference there is a finding, never a reason to widen the law. Derived tables rebuild from the
   ledger and are not compared. "Raw text" is Python `==` on the values SQLite returns; the one
   allowed row is judged on parsed JSON (a hand-made database may spell it differently); the file
   is opened `mode=ro`, which creates no file for the App's rollback-journal databases (a WAL file
   would get `-shm`/`-wal`).
- **Over-claim guard.** `fund-runtime replay` exit 0 means every wake matched its tape and the
  calendar matched; it is **not** proof of an identical ledger. Only `compare-ledgers` against the
  *original* database says that, and the cassette carries no ledger digest: keep the recorded database.
- **X-006 answer: what the recording holds that the replay never compares.** Never compared: the
  recorded replies (taken from the tape, not hashed), usage and cost (zero by design), `redactions`,
  each wake's `reason` and `tool_failures`, trailing tool results after the last turn of a
  `tool_budget` wake, the outcome's `registered` and `reason`, spec fields in no request (budget, wake
  policy; in v1 the model), and the ledger itself (only `compare-ledgers`). Compared: request hashes
  (prefix transcript, tools, model: identity and input too), each wake's `ended` and `tool_calls`,
  the calendar, the step count, the spec ids, and that no mind was retired.
- **Found while building:** the smoke run records a 5-day desk month on one real server and replays it
  on a second fresh database; `compare-ledgers` finds the two files equal but for the declaration,
  raw text, ids and timestamps included. In that one world and one run, no ledger nondeterminism
  outside the minds showed (the plan's risk; it is one sample, not a proof); the in-memory tests compare payloads re-serialised with sorted keys, the smoke run
  compares the databases' own text.
- Not done (R-4b-2b): cassette v2 (run parameters, spec digests, each wake's model, `tools_sha256`),
  NOTE 5 (`key` can mislabel a surface change), a size cap on the reader, `replay --cassette OUT`.
- Tests: `tests/test_replay_cli.py` (21), `tests/test_ledger_compare.py` (25),
  `tests/test_cassette_replay.py` +5 (refusal law; mutation: the old conductor turns all five red).
  Suite 1555 → 1606 passed + 6 xfailed; smoke 21 → 32 steps, all PASS.

## ADR-041 — Metering v1, the physics half: a system-reported cost ledger (R-6a; amends ADR-033 and 03_WORLD §4) — accepted
Context: until now the only cost physics held was what an agent *said* it spent (`POST /costs`). EC4
asks for every LLM dollar attributed to an agent by a system-reported cost. R-6a builds the law and the
fake provider; R-6b (gate lets a metered provider wake, per-agent keys, sync inside a run, the EC4
tick) is not built. **This cycle ticks nothing**: no mind spends and the gate is unchanged.
1. **Who posts.** The `runtime` role, through a new narrow right `REPORT_METERED_COST` (held by
   `runtime` and, through `frozenset(Action)`, `system`; by no firm role, management included). Not
   `system`: the Runtime process holds both keys anyway, so a separate identity buys no seal, and
   `system` would hand the sync job every right (prime rule: safer seal). A stolen runtime key could
   forge costs — the same operator-level trust as the clock (ADR-033). The metered agent is named in
   the body (the caller is never the subject); the endpoint refuses a physics identity as subject
   (422) and an unknown id (404).
2. **Cumulative, in integer micro-dollars** (`MAX_METERED_USD_MICROS` = 10^12, strict ints: `true` and
   `1.0` are 422). A re-post of a key's total writes nothing (`recorded:false`); a lower total is 409;
   a sync cut by HALT catches up exactly. The reader counts each key once at its maximum total, so
   a duplicate or out-of-order event cannot double-count.
3. **One key, one agent.** The key's first well-formed `cost_metered` event binds it. A later post
   naming another agent is 409. An event forged straight into the ledger naming another agent is
   ignored by the reader and counted (`MeteredLedger.conflicts`); one that is not a well-formed row is
   ignored and counted (`malformed`). An agent may hold several keys; they sum.
4. **What "overrides" means.** Per agent, not per pod: an agent with any metered row is metered; its
   self-reported `Cost` rows leave the authoritative `total_usd_cost` and stay as the cross-check
   (`self_reported_usd_cost`, `self_report_gap_usd`). An unmetered agent keeps its self-report. A pod
   with no metering gets exactly the old numbers, with the new fields `null` / 0. `cost_adjusted_pnl`
   and the leaderboard rank on the authoritative total. An agent's metered dollars (all its keys) go to
   one pod: the pod in the latest event of the last key in first-seen order, i.e. the agent's pod when
   it was posted (agents do not change pods today; a move would need a split by delta). The
   unmetered part is summed from the rows directly, not as a difference of float sums (audit c34 WARN 1).
   The published figures are dollars rounded to cents; exactness to the micro-dollar holds in the
   ledger fold (`metered_by_agent`) only (audit c34 WARN 2). The reader's `conflicts` and `malformed`
   counts are computed but exposed nowhere yet: a forged row is dropped silently (audit c34 WARN 3,
   backlog); `SyncReport.refused` is not persisted either, and a 422 for a label that fails the
   pattern would leave dollars unattributed — R-6b must fail loudly on it. A metered agent with no pod (management) appears in no pod's cost:
   B-000k.
5. **Ledger only.** `cost_metered {agent_id, pod_id, key_ref, usd_micros_total}`; no table, no
   migration, no reducer: nothing to rebuild, so `rebuild_state` cannot disagree. `key_ref` is an
   opaque label (`^[a-z0-9][a-z0-9_-]{0,63}$`), never a key or a hash of one, and agents read it as
   `withheld` (`AGENT_WITHHELD_FIELDS`). HALT refuses the post (423, the existing middleware).
6. **Concurrency.** The endpoint holds `METER_LOCK` across the check, the append and the commit: one
   process. Two servers on one file are the B-036 class; the reader's first-binding and maximum rules
   keep that race from rebinding a key or double-counting.
7. **Runtime half** (`runtime/metering.py`, imports only `mcp_server.client`): `FakeProvisioner`
   (deterministic `fake-0001…`, per-key limit, no secret, no network) and `sync_costs`, which posts
   every key's total in `key_ref` order. 423 stops it (`halted`), 401/403 raises, 404/409/422 are
   recorded per key and the rest go on.
8. **Decided now for R-6b: metering rows in a replayed ledger.** A metered run's ledger will hold
   `cost_metered` rows a $0 replay cannot produce, and a sync between steps would shift ids, which
   `compare-ledgers` (ids strict, ADR-040) would reject. Answer: sync only after the last step, so the
   rows form a trailing block that R-6b's comparison handles by type, by its own ADR. The comparison
   is never widened to make a difference pass.
- **Red-team 0019** (`tests/test_redteam_0019.py`, 83 tests): 1 hole (low, reachable only by a row forged
  into the ledger or a future pod-move law): "metered" was decided per pod, so an agent whose metered
  row named another pod kept its self-reports in its own. Fixed: "metered" is decided over the whole
  fold; its self-reports leave every pod's total, its dollars land on the event's pod. Defence in
  depth: the reader also requires `agent_id`/`pod_id` in 1..`MAX_ID`. Held: every firm-role post,
  rebind and lowering; the runtime key on 11 participant routes; `key_ref` anchor/unicode/coercion
  tricks; 12-thread races on one key (file-backed SQLite); HALT; self-report masking; forged rows;
  10 000 keys at the cap; `key_ref` in every agent read; MCP bounds. Noted, not filed: a post already
  past the halt check can still write once (every endpoint has this gap); R-6b must cap a key's
  limit at `MAX_METERED_USD_MICROS`.
- **Old tests this law broke (findings, not tests to loosen):** `test_redteam_0014` (the runtime key
  answers only /me, /clock, /halt, /clock/advance, /run/minds, /health — now also
  `POST /metering/usage`) and `test_runtime_identity` (the runtime role was exactly
  READ_HALT/READ_CLOCK/CONTROL_CLOCK — now plus REPORT_METERED_COST). Both edits add the one new right
  and name it; every other route still refuses the runtime key.
- **Not done:** the gate letting a metered provider wake, per-agent key creation in `provision`, a limit
  from `budget_usd` with the total under the cap, sync inside a run, a sync CLI, EC4's end-to-end test
  and tick (R-6b); B-000k firm-level costs; B-000n self-report rate law (self-report spam is still
  unbounded, but cannot move a metered agent's ranking); B-022 secret scan (before any real key).
- Tests: `tests/test_metering.py` (physics), `tests/test_metering_metrics.py`, `tests/test_runtime_metering.py`.

## ADR-032/ADR-040 amendment (cycle 36, B-053 + B-054) — accepted
- **Vetted before physics is told (B-053).** `fund-runtime backtest`/`replay` read the law once in
  `_conduct`, before any client is used, and run `runtime.provision.vet(specs, law)`: the network-free
  checks `provision` makes (duplicate id/name, reserved name, `wake_policy: never`, the wake gate,
  `check_spec`), with the same reason strings. A refusal there ends the run `refused`/`provision:<reason>`
  with no `/run/minds` declaration and no agent. `provision` delegates to `vet` and keeps its own read.
  Outside a replay, `_conduct` also refuses a `provider: cassette` spec
  (`provision:cassette_without_recording:<id>`): it has no tape and could never wake (red-team 0020, medium).
  **Known gaps (B-055):** `name_taken`, `directory_unreadable` and `directory_malformed` need the directory,
  a spec in a pod that does not exist fails only at registration, and a `tools` list naming an unpublished
  tool is refused only at the first wake (`unknown_tool`; the published list is read over the network).
  Each still comes after the declaration, and each can only leave a zero-cost label, because every spec
  that reaches it passed the gate (red-team 0020: no spec that passes `vet` is ever declared `model`).
- **HALT reads `halted` (B-054).** Corrects the cycle-33 claim. A run HALT stops ends
  `{"ended": "halted", "reason": "halted"}` when HALT is: present at the law read; met by the
  declaration (`minds_refused:423`); met in `provision` (`halted`, `wake_refused:<id>:halted`,
  `register_failed:<id>:423` — exactly these, `cli._is_halt`; `registered` still names what exists);
  met at the gate between two wakes (the refused wake stays in the step's record); or met by the advance
  (`423`, was `error`/`advance_failed:423`: physics' halt check runs before the handler, so the clock did
  not move; the record trusts the loopback server to be this App, as every other answer does). Only
  `app.registry.halt` answers 423 (grep, cycle 36; red-team 0020 confirmed). Every non-halt refusal keeps
  its label. A spec that is both refused by `vet` and run against a bad clock now ends `provision:<reason>`
  instead of `not_backtest`/`clock_identity`: each label is unchanged, only which check runs first.
- Old tests changed (findings): `test_halt_provisions_nothing` (the B-054 label; now stronger: no
  declaration, no advance); `test_a_clock_that_will_not_advance_ends_the_run_in_error` → `test_a_clock_physics_halted_will_not_advance_ends_the_run_halted`
  (same invariants, new label); `test_a_server_that_is_not_there_is_a_refusal_not_a_crash` gained the `woke`
  fixture (its specs named uninstalled scripts, hidden while the clock check ran first).
- Tests: `test_run_minds.py`, `test_runtime_cli_backtest.py`, `test_runtime_lockstep.py`, `test_runtime_provision.py`,
  `test_redteam_0020.py` (1 hole fixed, 3 open as strict xfail: B-055 ×2, B-056 physics 500 on a missing pod).

---

## ADR-042 — Builder v2: missions, acceptance checks run by the runner, planning sessions — accepted (Human-directed, 2026-10-13)
**Context.** Cycles 1–36: unit = one slice that fits one session, with architect + auditor (+ red-team)
on every slice and ~8 state files updated per cycle. Measured (cycles 31–36, list price): ~$28.6 for
~1,580 product lines, 0 Era exit criteria ticked, ~1 demonstrable capability; per cycle the lead made
~200 model calls at ~130k context, three opus reviewers started cold, ~1/3 of lines written were
state/docs, and red-team lows became the next units of work. The Human (a scientist, not shipping a
product) asked for a builder that delivers concrete features per run.

**Sources weighed** (the Human's research + the Builder's): Anthropic, "Effective harnesses for
long-running agents" (Nov 2025: feature list with pass/fail test steps, progress file, git, one
end-to-end feature at a time); Anthropic, "Harness design for long-running application development"
(Mar 2026: planner kept, sprints and per-sprint evaluation removed for newer models, one final
evaluator, evaluators earn their cost only at the edge of model ability); Anthropic, "Building a C
compiler with parallel Claudes" (Feb 2026: tests steer agents; parallelism pays only on independent
tasks); arXiv 2607.25152 (self-evaluated loops report progress in 100% of cycles while 56% change
nothing; an in-transcript judge accepts 44% of regressions; out-of-band, world-grounded checks close
the gap); Claude Code docs (subagents before agent teams — ~7× tokens; Stop hooks; OS sandbox; CLAUDE.md
< 200 lines); Cursor (flat coordination makes agents risk-averse — small, safe changes).
Rejected from the research: splitting one feature into per-layer subagents (no evidence; the layers
share `permissions.py`, the ledger and the MCP server); agent teams and named swarms (cost, experimental);
cloud projects (the seal, fund.db and OpenClaw are local); `/goal` as the done-judge (it is an
in-transcript judge). Parallel workers: deferred to a measured phase (`builder.parallel_workers: 0`).

**Decision.**
1. The unit of work is a **mission** (`protocol/MISSIONS.md`): a capability someone can run, 1–4
   sessions, with an executable acceptance check committed before the code and failing at that commit.
2. Sessions are `plan` (`protocol/PLAN.md`: measure, look outward, ideate, write 3–6 ready missions, one
   Era ∞ hypothesis) or `build` (`protocol/CYCLE.md`); the runner chooses (no ready mission, every
   `plan_every_missions` accepted missions, or a mission at twice its estimate → plan).
3. Architect once per mission; validator (runs checks, reports evidence); red-team once per mission
   touching physics, with severities (high fixed now, medium in the mission or next, low → one hardening
   mission, ≤ 1 in 5); auditor once per mission, judging the acceptance check too.
4. **The referee is outside the Builder:** after every session `loop/preflight.py --post` re-runs the
   suite on `main` and the mission's acceptance check in its own worktree, checks red-first, records
   acceptance edits, logs `$FIRM_HOME/metrics.jsonl`; a claimed merge it cannot reproduce is `failed`
   (`false_done`). A Stop hook refuses a `merged`/`progress` claim the repo does not support.
5. Paperwork per session: journal (3–8 lines), `PROGRESS.md`, `loop_status.json`; per mission: SHOWCASE,
   STATE, ADR only for real decisions. `METRICS.md` frozen.
6. Human decisions (2026-10-13): no USD caps (the subscription's usage limit is the stop), the runner
   waits for usage resets ≤ 6 h, an 8 h hang guard; Bash in the OS sandbox (writes: repo + temp; network:
   GitHub, PyPI); lead sonnet for build, opus for plan.

**Rollout (one variable at a time, Anthropic's method):** phase 1 = this ADR. Phase 2 = A/B the build
lead's model (sonnet vs opus) on accepted missions per dollar. Phase 3 = `parallel_workers` 1–2 on
independent tasks. **Metric:** accepted missions per $100 (runner-verified); secondary: false-done rate,
main-red events, review share of tokens, docs/product ratio. **Rollback:** if after two runs it does not
beat the cycle 31–36 baseline, or main goes red, `setup/rollback.sh` restores v1 and the result is
recorded (a negative result is a result, Art. 9.2).

**Protected files** changed by the Human through `setup/install.sh` (staged in `setup/files/`):
`.claude/commands/cycle.md`, `.claude/agents/{architect,auditor,red-team}.md` + new `validator.md`,
`worker.md`, `.claude/settings.json` (Stop hook), `.claude/hooks/guard.py` (quoted text is data, not shell
syntax; `>/dev/null` is not a write; `$(…)` is never read-only) + new `stop_gate.py`, `loop/run.sh`,
`loop/builder.sh`, `loop/preflight.py`, `governance/human.yaml`. Recorded as P-0004.

## ADR-043 — The first mission queue; Era II work starts while Era I's real-mind criteria wait on the cap — accepted (cycle 37, plan)
**Context.** The re-foundation planning session (cycle 37, `protocol/PLAN.md`) turned the vision
milestones M1–M6, the open Era I criteria and the open backlog into missions. Era I has 3 of 7 exit
criteria ticked. Of the other four, EC4 and EC7's static half can be met with fake providers and no
money. EC1, EC2 and EC7's live half are ticked only by real minds, which need `monthly_llm_usd_cap`
(Q-0001, unanswered since cycle 0). Once EC4 and EC7-static are met, Era I has nothing left that the
Builder can do alone.

**Decision.**
1. The queue is M-001 metered month (EC4) → M-002 self-contained proof object (EC2 path) → M-003
   OpenClaw certified (EC7 static) → M-004 hardening (9 strict xfails) → M-005 Truman shock (Era I
   deliverables 4–5) → M-006 risk ladder (Era II EC2). Raw material is mapped in `state/BACKLOG.md`.
2. **Era II work may begin before Era I closes**, while Era I's open criteria wait only on the Human.
   Era II is N+1, so the prime rule's "never build Era N+2 to finish Era N" is not breached. CLAUDE.md
   rule 10 ("never wait for the Human") rules out idling. Missions that unblock Era I always go ahead
   of Era II missions in the queue.
3. The fork instrument (`09_BUILDER_VISION.md` §2) is **parked, not adopted**. It belongs to an Era
   after the Launch Pad (N+2). M-002 (one-file proof object) is the prerequisite it shares with Era I.
   The fork will be considered when Era II's generations need it ("generation N+1 is a fork of N").
4. Truman v1 is built on the keyed synthetic market, not a real-history pack. Fetching history needs
   network that the Builder's sandbox does not have.
5. No process change at this plan (`protocol/PLAN.md` §6). The runner has logged zero v2 sessions
   (`$FIRM_HOME/metrics.jsonl` does not exist yet). Changing the process before its baseline is
   measured would confound ADR-042's own evaluation. The first process hypothesis is due at the next
   plan, against measured v2 sessions.

**Alternatives rejected.** Waiting for Q-0001 before Era II (idles the loop). Adopting the fork now
(N+2, and without real minds it measures scripted code). A hardening-first queue (MISSIONS §5: at
most 1 in 5; none of the 9 holes is high).

**Reversible.** Yes: the queue is re-cut at every plan.


## ADR-044 — Metering v1, the Runtime half: a fake metered provider, keys under the cap, one sync (M-001; amends ADR-032 (4)(p) and ADR-041 §7–8) — accepted (cycle 38)

**Context.** ADR-041 built the physics half of metering: a cumulative `cost_metered` ledger the
metrics read instead of an agent's self-report. Nothing in the Runtime produced it. The gate still
answered `no_metered_key` to every spending provider under a numeric cap, so no run could show that
each dollar is charged by the system to the mind that spent it (Era I EC4, vision M4).

**Decision.**
1. **Which name is metered.** `fake-metered` only (`runtime.gate.METERED_PROVIDERS`): a script from
   the closed table, billed per model turn to its own key at a fake provisioner. No model, no
   network. A real provider is a new name by its own ADR, with the Human's cap (Q-0001).
2. **The gate** opens it only when the cap is a number, the adapter is `native`, and the Runtime says
   it holds the mind's key (`metered is True`, exact). Order: halted → zero_cost → cap_null →
   metered → `no_metered_key`. The gate is told; it never asks the provider.
3. **A numeric cap exists only inside a process that rebinds `runtime.governance.HUMAN_YAML`** (the
   existing test seam). No flag, env variable or config reaches it; the Builder never sets the cap (it was `null` when
   this was written; the Human answered Q-0001, $50/month, on 2026-10-15 while M-001 was built); HALT
   stays the real HALT. The acceptance check proves the real law refuses the same specs.
4. **Limits.** key limit = floor(`budget_usd` × 10⁶) micro-dollars, in 1..10¹². `vet` refuses
   `budget_over_cap` when Σ limits > floor(cap × 10⁶); the conductor re-checks every step
   before every wake (`metered_over_cap`), so minds handed in around `vet`, or a cap lowered mid-run, are met. Enforced
   per run: **monthly accounting across runs must exist before any real key** (a gate for R-8, with B-022).
5. **One key per metered agent**, minted right after registration and bound to that agent's id; the
   conductor refuses a key that is not its agent's (`meter_mismatch`). A charge past the limit raises
   before anything is returned: nothing is ever spent past a limit, the wake ends `error`.
6. **One sync**, after the run ends, whatever the end (`sync_costs`). A refused, halted or failed
   post exits 1 and names the unattributed micro-dollars on stderr. **Compare-ledgers is unchanged
   (one allowed difference)**; a metered run's `--cassette` is refused (exit 2). The mission that
   replays a metered run owns a second, named verdict: recorded ledger = replay + a trailing block of
   k ≥ 1 well-formed `cost_metered` rows by the runtime, reported apart, never folded into `equal`.
7. **Physics hears `scripted`** for these minds (`run_minds_declared`): code from a closed table.
8. **A read** `GET /metering/agents` (READ_CROSS_POD, no new Action; the Runtime identity does not
   read): per metered agent the meter, the agent's own self-report and the gap; `total_usd_micros` is
   `null` when nothing is metered; forged rows are counted, never believed; no `key_ref`. Tool
   `get_metered_costs`. Closes audit c34 WARN 3.
9. **The fake price** is $3 / $15 per million tokens on ceil(chars/4) of the request's and reply's
   canonical JSON. Deterministic: same world + specs → same charges to the micro-dollar (guarded by
   `tests/test_runtime_metered_determinism.py`: two fresh databases, identical usage and ledger). A month of the 2-mind pod measured ≈ $5.2 of a $40 budget; it
   grows with the published tool list (adding one MCP tool moved it by ~$0.05), so the acceptance
   asserts relations, not dollar constants.

**Old tests this law broke (findings, restated not loosened).**
`test_every_registered_name_is_on_the_gates_list_and_says_so` (registered names = ZERO_COST ∪
METERED, `spends_money` ⇔ metered); `test_the_adapter_takes_no_provider_object` (+`meter`, a key
handle checked as exactly a `Meter`); a spy's `build()` signature in test_runtime_lockstep; the
red-team 0014 route sweep (+ the new read, refused to the Runtime key).

**Alternatives rejected.** A `law=` parameter on the CLI (an injectable cap is what Art. 4 forbids);
metering through OpenClaw (it has its own key and model); posting after every step (many rows, no
gain: totals are cumulative); fixing the O(n²) scan in `record_metered_usage` (one sync per run —
stays in BACKLOG).

**Red-team 0021 (5 holes).** Fixed in this mission: *high* — a cap lowered during a step bound only
the next step (now Σ limits ≤ cap is checked before every wake); *low* — the sync is in a `finally`,
so a crash or `SystemExit` out of a wake still posts the dollars. **Accepted, written, and routed to
the hardening mission M-004 (Art. 9: a hole accepted is written, never hidden):** *medium* — until
the single sync, physics knows no agent is metered, so a leaderboard read **during** the run ranks
metered minds on their self-reports; "a self-report can no longer move a metered agent's cost or
rank" is true of the finished run only (the fix, posting every key at 0 after provisioning, makes
the cost rows no longer a trailing block — the compare-ledgers law of §6 must be written with it);
*medium* — a rival can drain a metered mind's key by stuffing its inbox with long messages, since
the fake bills every character (needs a per-sender message quota, a law change); *low* — a sync
that fails part-way reports `posted: 0` and counts every key as unattributed (exit 1 is right).
Tests: `tests/test_redteam_0021.py` (3 strict xfails).

**Not done.** A real provisioner; persistence of the fake's state (a HALT before the sync leaves the
dollars unposted — reported, exit 1, no catch-up); B-000k, B-000n, B-022.

**Reversible.** Yes: one name in the gate's list, one class in the registry's table.

## ADR-045 — A run is a self-contained proof object: cassette v2 + `replay --verify` (M-002) — accepted (cycle 41)

**Decision.** A recording (cassette v2) carries everything needed to re-live it: the run's parameters,
the specs with their digests, a per-wake model/tools digest, the world's recipe and the recorded
ledger rows. `fund-runtime backtest --world FILE` hosts a world of its own (`runtime/world.py`, the
only spawner); `fund-runtime replay --cassette F --verify` rebuilds that world from the recipe and the
world key (a secret, never in the file), replays every mind at $0 and prints IDENTICAL (exit 0),
DIVERGED at <step, wake | physics, event> (1), usage (2), SETUP ERROR (3) or HALTED (4). Version 1
cassettes are refused by name. `acceptance/M-002.py` passes.

**What IDENTICAL proves.** Reproducibility under this checkout's physics, not authorship; the final
reply text of a wake is not hashed (pinned limit, `tests/test_runtime_verify.py`).

**Not done (by the Human's call, 2026-10-16: finish quickly, process to be slimmed).** The scoped
red-team, the validator and the auditor did not run on this mission; the smoke hosted step and the
design note were dropped. Recorded here so the gap is visible (Art. 9).

## ADR-046 — Builder v3: the ideas book is the goal source; a light, risk-tiered process (Human-directed rework) — accepted (cycle 41, 2026-10-16)

**Why.** After 40 cycles no AI agent had traded. The Human's brief
(`bible/sources/REWORK_BRIEF_2026-10-16.md`) traced it to the setup, not the idea: goals came from
AI-written measurement criteria (`05_ERAS.md`) while the Human's ideas sat in "original notes"; firm
agents could not run until the cap was set (2026-10-15); the rulebook read as a safety manual; every
mission paid the full ceremony (architect, red-first, validator, red-team, auditor, re-audit, six state
files); tool friction (session 40: 16 refused commands, all `cd "<repo>" && …`; its architect, run in
the background, was killed at session end); the cheaper model built while the stronger one reviewed.

**Decision.**
1. `bible/IDEAS_BOOK.md` is the only goal source: the project at full scale, the Human's ideas
   (matured from `bible/sources/REQUIREMENTS.md` and the brief, read as ideas, not a pathway), each with
   an honest status, the Builder's own ideas (Part 4), and "Next up". The firm's model, per the Human
   (2026-10-16): a multi-manager hedge fund with high turnover (allocation + drawdown ladder + hiring).
2. A unit of work = one idea, built until its demo works (`acceptance/<slug>.py`, $0 of real LLM spend).
   A short plan with "how I understand it" in `state/NOW.md`, shown in the Console. No architect, no
   validator (the runner already checks out of band). Red-team + auditor only for money, physics or the
   seal. Tests proportionate. Paperwork: handoff, one journal line, loop status, a SHOWCASE entry per
   finished idea; an ADR only when a rule of the world changes.
3. No human in the loop. The Human comments in the Console (`$FIRM_HOME/comments.jsonl`); the Builder
   answers in `state/comments.json` at the next session. `approvals.pitch_requires_human` → false (draft).
4. Rulebook: short Constitution and Genesis (drafts in `setup/files/bible_dir/`), same hard limits;
   tie-breakers reordered: inside the seal → makes the firm more real or capable now → deterministic
   physics → reuse → measurement where it matters.
5. Setup (drafts in `setup/files/`, installed by the Human with `bash setup/install.sh`): lead = opus;
   architect and validator removed; Bash allowed broadly (deny list kept); the guard blocks only writes
   aimed at protected paths; subagents in the foreground; the runner accepts `idea/*` branches and
   flags a merge without the auditor only for risk-tier ideas.
6. Archived: `bible/04_FIRM.md`, `05_ERAS.md`, `06_LOOP.md`, `09_BUILDER_VISION.md` → `bible/archive/`;
   `state/BACKLOG, IDEAS, SURVEY, BILLS, METRICS, REPORT, plans/` → `state/archive/`;
   `protocol/MISSIONS.md` folded into `protocol/CYCLE.md`. Old missions M-003…M-006 dropped, re-cut into
   book ideas. The first idea: real AI agents live a backtest month.

**Coverage check (brief → where it lives).** Brief §1 (full scale) → book Part 1. §6 seeds → book Part 3:
pods/PM builds pod → "Pods"; manager/CEO → "Management above the pods"; pitch → "The pitch"; strategy as
a function → "A strategy is an isolated function"; backtest + packages + days×tickers + known outcomes +
model comparison → the five backtest ideas; validation (hypothesis, IC, DSR, capacity, correlation) →
"Validation gates"; Barra → "Barra-like…"; allocation → "The allocation algorithm"; 5/7.5/10% →
"The central risk ladder"; pod metrics → "Pod metrics"; communication + hub + bus → three ideas;
orchestration → "Workflows as programs"; monthly reset + evolution → "Generations and evolution";
cost → "Thinking costs money"; society/civilisation → three ideas; the Human's view → two ideas; the
open host decision → "Who hosts the agents" (the Builder decides). Brief §5 hard limits → draft
Constitution §1 (seal, fake money, origin only), §2 (no LLM in `app/`), §3 (HALT), §4 (caps), §5
(not a participant; non-`firm-` OpenClaw agents), §6 (honest measurement), §7 (main green,
append-only, no force-push).

**Reversible.** Yes: `bash setup/rollback.sh <backup>` restores the protected files and reverts the
merge; the archived files are one `git mv` away.
