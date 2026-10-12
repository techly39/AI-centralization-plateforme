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
