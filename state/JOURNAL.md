# JOURNAL — append-only, one entry per cycle

## Cycle 0000 — Bible installed (2026-10-11)
Era: 0 → I
Work: The Human installed the Bible (`bible/`), `CLAUDE.md`, `.claude/` tooling, `governance/`,
`loop/`, and seeded `state/`. Decisions ADR-001…011 recorded.
Result: ready for cycle 1.
Next: B-001.

## Cycle 0001 — Git hygiene: commit Phase 2 + Bible/harness (2026-10-11)
Era: ½ — The Survey
Exit criterion served: "Phase 2 committed; `main` green; pushed."
Hypothesis: If the uncommitted Phase 2 work and the Human's cycle-0 install are committed as two
separate, secret-free commits and pushed, then every later cycle starts from a clean tree, git
history becomes a second seal on the protected files, and the survey can diff against a real base.
Work: Two commits on `cycle/0001-git-hygiene`: Phase 2 (1317af0) and Bible + harness byte-for-byte
(dd0af27), after a secret scan (clean). The full suite turned out to be **flaky**:
`test_oms_concurrency` failed 1/5 of my runs and 3/~8 of the auditor's (StaleDataError) → auditor
BLOCK. Root cause: StaticPool hands all threads one in-memory connection; a session close outside
OMS_LOCK rolls back another thread's order. Fixed by giving that module a file-backed engine
(837115c), assertions unchanged, 0/40 failures. Mutation check: with OMS_LOCK disabled the new test
*still passes* (flush-before-read + SQLite write lock serialise) — and the old one only "caught" it
via the same crashes. Documented in the docstring; B-000b. Red-team (permissions changed) found 10
holes, 0 impersonation/bypass; recorded as strict xfail (b058f0d, `tests/test_redteam_0001.py`).
Merged f45eecf, pushed `main` + branch.
Result: merged. Suite: 250 passed + 10 xfailed, green 3× on branch, 1× on main.
Learned: (1) "218 tests green" in STATE was true only some of the time — measure suites ≥3 runs.
(2) A test can pass for the wrong reason in both directions; mutation-check tests that guard
invariants. (3) The guard hook matches the substring `loop` (so `state/loop_status.json` reads and
`cd` commands are blocked) — work via Read tool + bare relative commands; proposed a fix (P-0001).
Next: S-001 toolchain inventory → S-003 repo survey; B-000c (leaderboard DoS) is the top physics bug.

## Cycle 0002 — Leaderboard token-overflow DoS (2026-10-11)
Era: ½ — The Survey (physics bug, priority 2 — allowed during the Survey)
Exit criterion served: "`main` green" + F-0002 follow-up — the worst open physics hole.
Hypothesis: If one report's token counts are capped and pod totals are summed with a function
that cannot overflow, then no agent can take the leaderboard down with cost reports, and the
two red-team xfails for it flip to held. (Written at record time — I skipped the step-3 entry
before building; noted honestly.)
Work: `MAX_TOKENS_PER_REPORT` = 1e8 enforced in the `POST /costs` schema, the MCP tool schema, and
`report_cost` (in-process); `_cost_metrics` uses SQLite `TOTAL` instead of `SUM` (ADR-018). Two
strict xfails → held tests; the DoS test now asserts the attack is refused (422) and metrics stay
200, and a new test plants overflowing rows directly to prove the `TOTAL` wall alone
(mutation-checked: `SUM` fails it). Auditor: PASS, 7 notes — fixed 2–5 (domain guard, MCP `le=`,
precision comment, ADR). Red-team: 12 attacks held (type coercion, boundaries, volume, MCP path),
1 new low hole: `GET /metrics/pod/{2**63}` → 500 (pre-existing, management-only) →
`tests/test_redteam_0002.py`, B-000m.
Result: merged 685eaf0. Suite 267 passed + 9 xfailed, 3× on branch, 1× on main.
Learned: (1) An xfail test that encodes the attack's *steps* (201 then 500) can't simply flip when
the fix blocks an earlier step — the honest move is to keep its claim (metrics stay up) and add a
test for the inner wall. (2) Editing a module while a subagent runs the suite produces phantom
flakes; don't edit code that's being red-teamed until it reports.
Next: S-001 toolchain inventory (the Survey has been waiting two cycles); then B-000d.

## Cycle 0003 — Toolchain inventory + run check (S-001) (2026-10-11)
Era: ½ — The Survey
Exit criterion served: "`state/SURVEY.md` complete with all sections above" — deliverable 1 (toolchain inventory).
Hypothesis: If I record every tool version and actually start the API and connect the MCP server
as an agent would, then the Survey has evidence (not belief) that the physics runs outside pytest,
and any gap between "tests green" and "the thing starts" surfaces before Era I builds on it.
Work: Recorded versions (macOS 26.5.2 arm64, uv 0.11.14, venv Python 3.12.13, Node 22.22.2,
OpenClaw 2026.5.12, Claude Code 2.1.296, mcp 2.0.0 …) in `state/SURVEY.md` §1. Wrote
`scripts/smoke_run.py`: temp-dir DB via the real CLI → `fund-env serve` on a free port → MCP client
launches `fund-env-mcp` with the seeded key → 5 read tools. Never touches the Human's `fund.db`.
First run crashed in *my* code: mcp 2.0 renamed `isError` → `is_error`. Auditor PASS, 7 notes;
fixed 1–5 (HALT check, SIGINT stop counted, FUND_* env scrubbed, /docs error as FAIL, stderr shown).
Measured: SIGTERM → rc 143, SIGINT → rc 0. README tool count 19 → 20.
Result: merged b77ed42. Smoke 12/12 PASS (3 runs); suite 267 passed + 9 xfailed on branch + main.
Learned: (1) The physics *does* start and serve an MCP agent end to end — first evidence outside
pytest. (2) Loop-mode permissions deny `VAR=x cmd`, `git --version`, `claude --version` and most
multi-op lines; survey work should be one `uv run python <script>` per check. (3) mcp 2.0 is a
breaking major — the OpenClaw adapter must be written against 2.x field names.
Next: S-003 repo survey (read every file, map to TRD + Bible).

## Cycle 0004 — Repo survey, part 1: the physics code (S-003a) (2026-10-11)
Era: ½ — The Survey
Exit criterion served: "`state/SURVEY.md` complete with all sections above" — deliverable 2
(repo survey), first slice: `app/`, `mcp_server/`, `migrations/` (~7 000 lines). S-003 split:
S-003b = tests, scripts, docs, legacy, root files.
Hypothesis: If I read every physics file against the TRD and the Bible and write down, per
module, what exists, what the TRD asked for, and where they differ, then Era I starts from a map
instead of from STATE's summary — and the gaps that matter (TRD items silently missing, dead code,
invariants that the code does not actually enforce) become backlog items with file:line evidence.
Work: Read all ~7 000 lines of physics against the TRD + 03_WORLD. Turned each suspicion into a
number with `scripts/survey_probe_physics.py` (temp DB, P1–P9). Wrote SURVEY §2a (module → TRD
map), §3–8 physics part. Findings: rebuild ≠ live under a backwards clock (10 phantom shares, P3);
daily-bar look-ahead (bar stamped at open, carries the close); yfinance quote ignores `as_of` and
stamps the requested time; annual Sharpe ×0.845 (calendar days, √252 — P8); pod creation + system
agent unledgered (P2); register into a missing pod → 500 (P5); `inf` limit_price stored, read back
as `null` (P4); `/clock` forbidden to agents the MCP tool tells to use it (P7); `import
mcp_server.tools` loads 35 `app.*` modules (P9). Migrations == models (P1, 0 diffs). Dead: 5
exported functions, two of which are a missing "read my tasks/costs" endpoint. Auditor PASS,
11 notes; fixed 1–9, 11 (second cause of P3 in the sell reducer; StaticProvider overclaim
removed; `/clock` reframed as a TRD decision needing an ADR). Backlog B-016…B-021 new; B-000d,
B-002, B-005, B-006 widened.
Result: merged 3207a72. Suite 267 passed + 9 xfailed on branch (2×) and main. No physics changed.
Learned: (1) The physics' conventions are real in the code (one money path, one permission matrix,
one visibility predicate) — its weak spot is *time*: 3 of 9 findings only bite once the clock moves,
which is Era I's first job, so B-016/B-020 must precede B-004. (2) A reviewer reading my evidence
found a second cause I missed (the reducer erasing an impossible negative position) — a finding
with one cause named is often half a finding. (3) Pydantic serialises `inf` as `null`: the API
can silently disagree with the database; "what came back" is not proof of "what was stored".
Next: S-003b (tests, scripts, docs, legacy, root files) → S-004 cleanup → S-005 OpenClaw survey.

## Cycle 0005 — Repo survey, part 2: tests, scripts, docs, legacy, root (S-003b) (2026-10-11)
Era: ½ — The Survey
Exit criterion served: "`state/SURVEY.md` complete with all sections above" — deliverable 2
(repo survey), second and last slice: everything outside `app/`, `mcp_server/`, `migrations/`,
`bible/`, `state/` (~6 800 lines: 24 test files, 4 scripts, 2 docs, legacy POC, root files).
Hypothesis: If I read the suite against the TRD's test list and the physics map from cycle 4,
and classify every non-physics file as keep / fix / move / delete with a reason, then (a) S-004
becomes a mechanical list of cleanup commits, and (b) I learn which invariants the 267 tests
actually guard and which TRD-demanded tests are missing — so "suite green" stops being a belief.
Work: (resumed: an earlier session wrote SURVEY §2b/§4b/§5b + the probe, then stopped before
committing; this session verified the probe output against the text, committed it, and finished
the cycle.) `scripts/survey_probe_repo.py` (R1–R4, read-only, never prints a key); SURVEY §2b
(tests/scripts/docs/legacy/root), §4b (5 findings), §5b, §6–8; BACKLOG: S-003b done, S-004 now
a concrete list, B-022 secret-scan, B-005/B-018/B-020 widened; QUESTIONS Q-0003. Auditor PASS,
notes 1–3 fixed (probe scope wording, sqlite close, legacy inventory); note 4 → S-004 first.
Result: merged 558b43a. 267 passed + 9 xfailed on branch and main.
Learned: (1) The one real security finding came from a file the Bible called "odd", not from
physics: survey the boring files with the same care. (2) A test double inherits the physics'
assumptions (the look-ahead lives in `HistoricalProvider` too); fixing a provider means fixing
its double in the same commit. (3) "Milestone done" needs a "by whom": script ≠ agent.
(4) An interrupted cycle leaves a dirty tree on its branch; gate 0's "commit legitimate
leftover state" worked, provided I re-verify the measurements before trusting the text.
Next: S-004 cleanup (remove `test_api.py` first) → S-005 OpenClaw survey → S-006/S-007.

## Cycle 0006 — Cleanup commits (S-004) (2026-10-11)
Era: ½ — The Survey
Exit criterion served: "commit the uncommitted Phase 2 work, clean junk" — the cleanup half of
the Survey: every SURVEY §2b/§4b.5 "remove / fix" verdict executed, one reasoned commit each.
Hypothesis: If I execute the S-004 list as deletions/moves/doc fixes only, the tree stops
carrying the committed key and stale docs, the suite stays at 267 passed + 9 xfailed (nothing
collected depended on any of it), and the survey probe keeps working — because I will make R1
read `test_api.py` from git history once it is gone, so the evidence for Q-0003 stays measurable.
Work: `git rm` and `git rm --cached` were refused ("requires approval" — not on the headless
allow list). Did not route around it (no `mv`/`update-index`). Instead: redacted the key in place
(`test_api.py` reads `FUND_API_KEY`); probe R1 finds the key in history via `git log -G` and
still matches it to agent id=1 in `fund.db`; README Layout matches the tree; phase2 note on MCP
imports corrected (b110303); P-0002 proposes allowing `git rm`. Auditor PASS, 5 notes: 2–3 fixed
on branch (probe warns on inconclusive lookup; P-0002 caveat on prefix patterns), 1/4/5 at record
(Q-0003 update, behaviour change told to the Human, partial scope recorded here).
Result: merged 0678d62. 267 passed + 9 xfailed on branch and main. Hypothesis **partly met**: the
key left the tree and the probe survived, but the file is not gone and `.vscode/` is still
tracked — S-004b, blocked on P-0002.
Learned: (1) The headless allow list is part of the world's physics for me: plan units against
it (deletions are not available) or they half-fail. (2) When the intended action is denied,
the goal behind it (no secret in the tree) often has a smaller allowed path — take that, and
log the denied action as a proposal instead of finding a back door. (3) The guard still trips
on prose in commit messages (P-0001); twice this cycle.
Next: S-005 OpenClaw survey (backup first, change nothing) → S-006 Bible corrections → S-007.

## Cycle 0007 — OpenClaw survey (S-005) (2026-10-11)
Era: ½ — The Survey
Exit criterion served: "inventory the toolchain and OpenClaw (back it up, change nothing)" —
the OpenClaw half; `08_OPENCLAW.md` §1 steps 1–3 and §6 (OCT POC inventory).
Hypothesis: If I back up `~/.openclaw` first, then measure the installed version's own schema
(not the online docs) and the Human's agents with a read-only, secret-redacting probe, I get
`runtime/openclaw/VERSION_NOTES.md` with every key the adapter will need, and I find where the
installed version differs from what the Bible "knows" — before B-012 writes code against it.
Work: Backup `~/firm-openclaw-backups/20261011T0129Z-cycle0007.tar.gz` (4 107 = 4 107 entries;
renamed once to its true UTC time). `scripts/survey_probe_openclaw.py` O1–O6 (version, installed
schema, redacted config, workspaces, auth profiles, credential scan). Read the docs for the
precedence + sessions pages and the OCT POC charters/memory. Wrote `runtime/openclaw/VERSION_NOTES.md`,
SURVEY §9, ADR-019 (firm in its own `--profile`), B-023 (explicit seal keys), Q-0004.
`doctor` deliberately not run (may migrate). Auditor: **BLOCK** ×2 first — my scan reported
"0 secrets" but missed `workspace/OPENCLAW_XAI_KEY.txt` (no `xai-` pattern) and double-counted
nested workspaces; fixed (more patterns + filename check, outermost roots), docs corrected,
re-audit **PASS** with 5 notes (→ B-012/B-022 at record). `chmod 600` on the backup denied
headless → asked the Human (Q-0004).
Result: merged ccc1864. 267 passed + 9 xfailed on branch and main. Hypothesis **met**:
the installed 2026.5.12 differs from the online docs (`agents.list` vs `agents.entries`;
sessions visibility default `tree` vs `all`), and MCP + web + sessions keys are global-only.
Learned: (1) The docs for "the" tool are the docs for its *latest* version; the installed
CLI's own schema is the only version-true source, and the newer defaults are looser — so
render every seal key, never inherit one. (2) "0 found" from a pattern list is a statement
about the list, not the disk: a negative needs a second, independent detector (name + content).
(3) My own artifacts carry risk too: a backup of a credentials dir must be born private
(`umask 077`), because fixing permissions later may not be allowed.
Next: S-006 Bible corrections → S-007 close Era ½ → Era I: B-016 + B-020, then B-004.

## Cycle 0008 — Bible corrections (S-006) (2026-10-11)
Era: ½ — The Survey
Exit criterion served: "correct the Bible where it is wrong" — every Bible claim the Survey
(SURVEY §2a/§2b/§9, VERSION_NOTES) measured as false is corrected in the living books, or
proposed in `state/PROPOSALS.md` if it sits in a protected book.
Hypothesis: If I correct only claims that have Survey evidence behind them (test counts,
OpenClaw version/doctor/backup facts, the "chat restricted" lead, the physics' known time
weaknesses) and point each correction to its evidence, the books stop contradicting the
measured world without me inventing new rules — and no protected book needs a proposal,
because 00/01 make no version- or count-specific claims.
Work: Corrected 03 §2 (counts; "works with known holes" paragraph incl. script-met Phase 2
milestone), 04 §11 (chat-restriction lead → OpenClaw, B-014), 05 Era 0 + Era ½ exit criterion,
08 §1 (docs ≠ installed; `config schema` first, `doctor` only after backup on the firm
profile; global-only keys), 08 §2 (born-private backups; firm profile), 08 §5 check 5. ADR-020:
corrections annotate, never rewrite. Read 00 + 01 in full: nothing to propose. Auditor
**BLOCK** ×2 first: I had copied cycle 7's "`tools.profile` is global only" — false, the
installed schema has `agents.list[].tools.profile`; and I counted the docs' `agentToAgent`
default-on as a measured loosening though 2026.5.12 states no default. Fixed in 08,
VERSION_NOTES, SURVEY §9 (ADR-019 corrected by amendment in ADR-020, not rewritten). Re-audit
**PASS**, 3 notes (wording fixed on branch; STATE line fixed at record; note 8 → S-007).
Result: merged 60811d1. 267 passed + 9 xfailed on branch and main. Hypothesis **partly met**:
the books now match the measurements and no protected proposal was needed — but my first pass
carried a cycle-7 error into the Bible, so "only evidenced claims" was not enough by itself.
Learned: (1) A correction copied from my own earlier notes inherits their errors: re-check a
claim against the primary source (the installed schema), not against the summary I wrote.
(2) Upgrading "the docs say" to "measured" is the easiest way to overstate (Art. 9.3); keep
the provenance word with every claim. (3) Annotating instead of rewriting made the auditor's
fix cheap: the amendment sits next to the error, history intact.
Next: S-007 close Era ½ (SURVEY completeness, IDEAS, backlog, note the criterion reworded in
its own Era, S-004b as residue) → Era I: B-016 + B-020, then B-004.

## Cycle 0009 — Close Era ½ (S-007) (2026-10-11)
Era: ½ — The Survey
Exit criterion served: all five Era ½ exit criteria — each ticked with its evidence, or left
open with the reason; the Era closes only if every box can be ticked honestly.
Hypothesis: If I check each exit criterion against its primary evidence (commits, the suite,
`git status`, the backup file, VERSION_NOTES, SURVEY sections) instead of against my STATE
summaries, every box can be ticked — "repo clean" only because its criterion allows "explained"
and S-004b's residue is explained — and Era I can open with a backlog ordered by the 06_LOOP §2
priorities (Constitution gaps, B-002 + B-003, before the clock work).
Work: Checked each criterion against primary evidence (`git rev-parse`, the suite on `main`,
`git status --ignored`, the backup file, VERSION_NOTES' source line, SURVEY headings vs
deliverable 7). Wrote SURVEY §10 (verdict + evidence per criterion, the reworded-criterion
note, the known residue), ticked 05 Era ½ with annotations (ADR-020 style), ADR-021 (close with
explained residue; Era I seal-first), reordered BACKLOG (Era I in ADR-021 order; residue section;
X-005 capability probe). Auditor **BLOCK** ×1: I had moved the physics-bug section below Era I,
silently demoting priority-2 holes that ADR-021's own reasoning ranks first. Fixed: section back
on top with a gate (every hole fixed or ADR-accepted before any agent wakes), ADR-021 amended;
notes 2/3/6/7 fixed on branch. Re-audit **PASS** (note 1: B-000k given a deadline at record).
Result: merged 28e435d, pushed. 267 passed + 9 xfailed on branch and main. Hypothesis **met**:
all five boxes ticked honestly, "repo clean" via its "explained" branch. Era ½ closed; Era I open.
Learned: (1) A reorder is a decision: moving a section changes what its items mean, so it needs
the same written reason as an ADR. (2) My justification for B-002/B-003 ("Constitution gaps
first") applied equally to the holes I demoted — check a rule against everything it covers,
not only what it was written to promote. (3) Push works headless only as a bare `git push` in
the repo cwd; `git -C` and `cd &&` both need approval.
Next: B-002 dependency-law test → B-003 halt in physics → B-000d + B-016 → B-020 → B-004.

## Cycle 0010 — Dependency-law test (B-002) + retrospective (2026-10-11)
Era: I — The Desk
Exit criterion served: Era I deliverable 1 (`tests/test_boundaries.py`, no LLM SDK in `app/`) —
the seal half of "every action through the App" (Art. 3.1), required before any agent wakes.
Hypothesis: If I enforce 03 §1 with two independent detectors (AST scan of every import + a fresh
interpreter's `sys.modules` after importing the entry points) and test the scanner on a planted
tree, the suite fails on the one known violation (`mcp_server` → `app.metrics.reporting`, SURVEY
§4a.9) and on nothing else; moving the shared constant to a pure `app/limits.py` turns it green
with no existing test changed.
Work: `tests/test_boundaries.py` (16 tests: per-layer law for app, migrations, quant, truman,
mcp_server, runtime, ui, scripts; every top-level Python dir must be placed; planted-tree scanner
test; dynamic no-LLM-SDK and wrapper-loads-no-physics probes). Red first: exactly the 2 mcp_server
tests failed. `app/limits.py` (MAX_TOKENS_PER_REPORT; reporting, schemas, mcp tools import it).
ADR-022 (mcp_server = HTTP client, may import `app.config` + `app.limits` only; scripts = clients
except named in-process probes; app never imports `mcp`), 03 §1 diagram, 05 deliverable 1 noted.
Auditor **BLOCK** ×1: the scanner missed `__import__("openai")` / `importlib.import_module("openai")`
and the ADR claimed only computed names were invisible. Fixed (literal dynamic imports read, planted),
ADR limits rewritten; notes fixed (hermetic probe env, path-based exemption, docstring, dropped an
unrecorded quant/truman rule). One suggested planted case was wrong: `from .. import runtime` in
`app/sub/` is `app.runtime` — asserted as such. Re-audit **PASS**; note 1 (aliased/keyword
`import_module`) added to ADR-022 limits. Smoke run 12/12. No red-team: no change to registry,
OMS, market data, metering or halt (`reporting.py` only moved a constant).
Result: merged 86e2486, pushed. 283 passed + 9 xfailed on branch and main (267 + 16 new).
Hypothesis **met**: red on exactly the known violation, green after the move, no test edited.
Learned: (1) Fifth auditor BLOCK in ten cycles, and the same shape every time: my claim about
what a detector *covers* was wider than what it does. Plant the counter-example before writing the
coverage sentence. (2) A test that knows every top-level package turns "new package" into
"new law" — the boundary can't be forgotten by omission. (3) The wrapper loaded the DB engine for one
integer: shared physical limits want their own import-free home (`app/limits.py`), which is also where
IDEAS "physical-units types" can live.

### Retrospective — cycles 1–10 (06_LOOP §6; re-read 00 + 01 this cycle)
- **Pointed at the Era's question?** Cycles 1–9 were the mandated Survey; cycle 10 is the first Era I
  unit. Nothing drifted from the Constitution, but **nothing yet moves toward "one pod runs
  end-to-end"**: 0 of 7 Era I exit criteria ticked. Seal-first (ADR-021) is right; it must not
  become seal-only.
- **Failures:** 10/10 merged, 0 failed, 0 blocked. But 5/10 cycles (1, 7, 8, 9, 10) needed an
  auditor BLOCK, all of one family: overstated claims (flaky "green", "0 secrets", docs→"measured",
  silent demotion, scanner coverage). Process change → **X-006**: before the auditor, list every
  "covers / finds / never / all" sentence in the diff and plant a counter-example for each.
- **What became boring:** the Survey (done) and the auditor's catch (predictable — so automate it,
  X-006). Frontier moves to **time** (B-016, B-004, B-005) and the **Runtime** (B-009).
- **Scales:** the Human answered 0 of 4 questions and 0 of 2 proposals in 10 cycles — the loop must
  run as if answers never come (it has). The Builder scale's own physics (headless allow list)
  blocked 2 units (git rm, chmod): X-005 stays relevant.
- **Ambition check:** is the world more impressive than 10 cycles ago? Honestly: more *truthful*
  (mapped, 10 holes known, a law enforced), **not more capable** — no agent has acted. The next 10
  cycles must end with a pod acting in simulated time against a fake provider (B-003 → B-000d/B-016
  → B-020 → B-004 → B-005 → B-008 → B-009). Ideas written up: IDEAS cycle-10 section.
Next: B-003 halt in physics (+ red-team) → B-000d + B-016 → B-020 → B-004.

## Human intervention — 2026-10-11 (between cycles 10 and 11)
- P-0001 and P-0002 accepted and applied (see `state/PROPOSALS.md`). S-004b (remove `test_api.py`,
  untrack `.vscode/`) is now unblocked.
- Runner fix in `loop/`: ~14 runs between 02:00 and 03:10 ended in seconds (usage limit) and were
  logged as `merged` because `--post` re-read the previous cycle's `loop_status.json`. Now a run only
  counts if `loop_status.json` advanced; a usage-limit stop is not counted and the runner waits 30 min.
  Lesson for you: always write `state/loop_status.json` with the new cycle number at the end of a cycle,
  or the run is counted as failed.
- Q-0003 / Q-0004: the Human handles the keys and the backup permissions.
- This entry and the PROPOSALS edit are uncommitted: commit them in step 0 of the next cycle.
  *(Builder, cycle 11 step 0: committed as 66af48b.)*

## Cycle 0011 — Halt in physics (2026-10-11)
Era: I — The Desk
Exit criterion served: Era I deliverable 2 (`governance/HALT` → agent writes refused; `GET /halt`)
and the physics half of the exit criterion "creating HALT mid-run stops the run within one tick".
Hypothesis: If the halt check lives in the one dependency every authenticated endpoint already
uses (`get_current_agent`), then a test generated from the OpenAPI schema shows every write route
(8 today) refused with 423 + exactly one `halt_refused` event for every role, reads keep working,
the pending monitor fills nothing, and deleting the file resumes the world — with no existing
test changed. A mutation that disables the gate must turn every one of those tests red.
*(Audit correction: as first written the test ran every route for management only, and the
monitor test catches a mutation of the monitor's own check, not of the API gate. Fixed below.)*
Work: Step 0 committed the Human's intervention (P-0001/P-0002 applied, runner fix) as 66af48b.
`app/registry/halt.py` (constant `HALT_FILE`, `is_halted`, `refuse_if_halted`), one call in
`get_current_agent`; `GET /halt` (`app/api/halt.py`, universal `READ_HALT`), MCP `get_halt`;
`check_pending_orders` checks the halt under `OMS_LOCK`; event `halt_refused` {method, route
template, role}. `tests/test_halt.py` (8 OpenAPI write routes × analyst/PM/management, reads,
resume-without-restart, 401, monitor) + MCP test; autouse `halt_file` fixture in conftest.
ADR-023; 03 §2 / 05 deliverable 2 marked. Mutation of the gate: 11/11 behaviour tests red.
Auditor **BLOCK ×2**: (1) the halt path was a setting — `config.yaml` / `FUND_*` could move it
away from the file Art. 5 names → now a constant, no setting; (2) the hypothesis claimed every
role on every route while the test ran management only → role × route. Red-team 0003: **2 holes**,
both fixed this cycle and kept as guards — `halt_refused` stored the raw URL (agent free text
into the ledger while the bus was halted, medium) → route template; the monitor checked before
taking the lock (a queued sweep filled after the halt, low) → check under the lock. 13 attacks
held (method overrides, odd methods, path tricks, malformed body, rebuild). Re-audit **PASS**.
Smoke 12/12 (on the branch and again on main after merge).
Result: merged ffc418a, pushed. 334 passed + 9 xfailed on branch and main (283 → 334, no existing
test weakened). Hypothesis: **met after correction** — as first written it overstated coverage
(the sixth auditor BLOCK of that shape) and missed two holes; the final code and tests meet it.
Learned: (1) X-006 caught one overstatement before audit (per-role) but not the other: I checked
my *coverage* sentences, not my *configuration* surface. Add to X-006: "what in this diff can an
unprotected file or env var change?" (2) An audit record that copies request input is an output
channel — refusal ≠ silence. (3) Any check outside the lock it protects is a TOCTOU; physics
checks belong inside the critical section. (4) The `test_the_write_surface_is_not_empty` guard
paid off immediately: the first route walk found 0 routes and the parametrised test was silently
skipped.
Next: B-000d + B-016 (finite floats; replay order = live order) → B-020 → B-004. S-004b (git rm
`test_api.py`, untrack `.vscode/`) is unblocked by P-0002 — take it as a quick unit soon.

## Cycle 0012 — Finite numbers only (2026-10-11)
Era: I — The Desk
Exit criterion served: the ADR-021 physics-hole gate before any agent wakes (B-000d, 3 strict
xfails), which the Era I exit criteria "one pod runs end-to-end" and "the ledger replays" stand on.
B-016 split off to its own cycle (both touch `append_event`; this one goes first, as planned).
Hypothesis: If every float request field is finite and capped, every free JSON field is walked,
the 422 handler spells NaN as text, and `append_event` refuses non-finite payloads, then every
`NaN`/`±Infinity`/`1e309` sent to every float or free-JSON request field gets a clean, standard-JSON
422 that names the field and writes no row and no event; the 3 B-000d xfails pass with their
markers removed; and removing any one of the three layers turns its own tests red.
Work: `app/finite.py` (`json_problem`, iterative; `json_safe` for the 422 echo); caps in
`app/limits.py` (`MAX_USD_PER_REPORT` 1e6, `MAX_ORDER_QTY` 1e9, `MAX_PRICE` 1e7, `MAX_JSON_DEPTH` 32,
`MAX_LEDGER_DEPTH` 36, `MAX_SAFE_INT` = `MAX_ID` = 2**53 − 1); bounded float fields + `FiniteJSON`
for `structured_payload`/`outcome` + `Id`/`IdPath` and bounded id queries/refs; NaN-safe,
depth-bounded 422 handler in `app/main.py`; `append_event` refuses non-portable payloads;
`report_cost` checks `usd_cost`; MCP float caps. `tests/test_finite.py` (68 tests incl. an OpenAPI
guard that fails on any unbounded float/int, untested free-JSON field, or shape it cannot walk, with
planted counter-examples). ADR-024 (+ amendment). Mutations: no fix → 49/50 red; handler only →
35 red; ledger only → 9 red; id bound on orders → 3 red.
Auditor **PASS** with 2 WARNs (guard blind to arrays/nested models/`Any`; sweep-wide rollback
undisclosed) → both fixed. Red-team 0004: **6 holes** — deep free JSON (~256+) stored then every
inbox/`/events` read of it a 500 (**high**, HTTP+MCP, cross-pod), ints like 10**400 in the ledger
(medium), walker recursion 500, int64 ids from analysts/PMs (low), fee $0.00 below $5 notional
(low), non-finite feed price → 500 (low, not agent-reachable). First four fixed this cycle; 15
attacks held. Re-audit **BLOCK**: my new int cap made `deny()` raise on `pod=2**53+1` → 500 and
the `permission_denied` record lost → every agent-supplied id bounded 1..2**53−1 → re-audit PASS.
Result: merged a70d2bb, pushed. 334 + 9xf → **461 passed + 8 xfailed** on branch and main; 3
B-000d xfails + B-000m (red-team 0002) + red-team 0004's int64 hole closed; 2 new open (B-026 fee,
B-025 feed). Hypothesis **met, then outgrown**: the three layers worked as stated, but "finite" was
the wrong promise — red-team showed depth and big ints break the same portability.
Learned: (1) Name the invariant, not the symptom: "finite floats" was a symptom of "the ledger is
portable JSON a reader can render"; framing it right first would have caught depth and big ints.
(2) Tightening a sink (ledger) turns every producer that copies agent input into a new 500 path —
when a sink gets stricter, grep its producers (`deny()` context) the same cycle. (3) A coverage
guard must classify *every* shape and fail on the unknown, or it certifies only what I thought of.
(4) Third cycle running where red-team found something the auditor did not, and vice versa — both
stay mandatory on physics.
Next: B-016 replay order (with the time-travel invariant suite) → S-004b quick cleanup → B-020 →
B-004.

## Cycle 0013 — Replay order = live order (2026-10-11)
Era: I — The Desk
Exit criterion served: "the ledger replays" (Era I) and the ADR-021 physics-hole gate: B-016 had to
close before B-004 (simulated clock) can rewind time.
Hypothesis (written at verify time: the build session ended after its first commit, before the
journal; the content is what ADR-025 states): If ledger time never runs backwards (stamped in the
INSERT), every replay folds by id, and an impossible sell raises instead of being dropped, then under
a clock that steps back and forth live state == `rebuild_state` == the equity curve's last point,
the SURVEY P3 phantom-shares case is gone, and each law's mutation turns only its own tests red.
Work: e689a72 (prior session) — `_not_before_latest` CASE subquery in `append_event`; id order in
`rebuild_state`, `read_events`, `_pod_events`; "latest day reached" buckets in `_replay_by_day`;
sell reducer raises; `QTY_EPSILON` moved below the OMS; `tests/test_time_order.py`; ADR-025. This
session: found the branch unmerged with `loop_status` still at 12 → resumed at step 5 instead of
starting a new unit. Read-only fold of the Human's `fund.db` (95 events, 0 backward stamps) under the
new reducer: clean. Auditor **PASS** (WARN: a forward clock step is now permanent → ADR-025 (f),
B-029). Red-team 0005: **2 low holes**, 9 attacks held (agent-supplied stamps, clock control,
reducer-event forgery, 8 racing on-disk writers with ±3-day clocks, a writer waiting on an
uncommitted later stamp, 6 racing full sells, 60-order churn with clock steps): (1) a 1e-9 sell of
a never-held ticker filled within `QTY_EPSILON` → OMS and reducer refuse any sell without a
position; (2) `Order.created_at`/`filled_at` took the raw clock while their events were held →
copied from the events, `execute_fill` loses `at`. Re-audit **PASS**; its 2 coverage notes closed
(reducer dust-sell test — mutation red alone; `created_at` checked against `order_placed`).
Result: merged 0c522eb, pushed. 461+8xf → **489 passed + 8 xfailed**. Hypothesis **met**; red-team
showed the law covered the ledger but not the rows agents read beside it.
Learned: (1) A truth source is only as good as its mirrors: holding the ledger's time without
holding `Order.created_at` gave agents a fill history that contradicted the ledger — when a sink
gets a new law, every row that *copies* the sink must inherit it (the converse of cycle 12's
lesson 2). (2) A tolerance is a law too: `QTY_EPSILON` meant "forgive dust" but was written as
"allow 1e-9 of anything". Say what a tolerance forgives. (3) Interrupted cycles are now real:
step 0 should compare `loop_status` with branches ahead of `main` and resume, not restart — done
here by judgement; worth writing into the protocol (X-007 in IDEAS).
Next: B-020 clock-vs-agents ADR → B-004 simulated clock (per-`run_id` floor, B-029 guard) →
S-004b if P-0002's answer covers headless `git rm`.

## Cycle 0014 — Every agent may read the clock (2026-10-11)
Era: I — The Desk
Exit criterion served: "one pod runs end-to-end" in backtest (Era I, TRD Phase 3): a PM must be
able to learn the simulated date; B-020 had to be decided before B-004 builds clock control.
Hypothesis: If reading the clock becomes a universal action (like `READ_HALT`) while clock
control stays absent (B-004 will gate it to system/management), then every role reads the same
`now` the OMS and market data use, the read writes no event and works during halt, no clock
write appears on the surface for any role, the MCP `get_clock` promise becomes true, and
reverting the one matrix line turns only the new read tests red.
Work: `Action.READ_CLOCK` in `_UNIVERSAL` (`app/registry/permissions.py`); `/clock` gated on it;
ADR-026 (+ amendment) amends TRD §7 for the read only. `tests/test_clock_and_health.py` rewritten
(every role, exact `now`, a PM's order stamped with the now it read, no event, works under halt,
deactivated → 401); red-team 0005's management-only read guard → read-only guard. Mutation: drop
`READ_CLOCK` → 13 clock tests red, nothing else. Auditor **PASS** (notes: TRD §7 and the matrix
comment → fixed). Red-team 0006: **1 low hole**, ~36 attacks held — after a clock step back,
`/clock` gave the raw clock while the ledger held stamps (ADR-025), so an agent's next order was
stamped later than the now it was told, revealing another pod's activity in its "future". Fixed:
`ledger_now(session)` = `max(clock, latest ts)` through the INSERT's own expression; mutation →
only that test red. Re-audit **PASS** (note: per-`run_id` floor must land with B-004 → backlog).
X-007 (resume rule in `cycle.md` step 0): **refused** — `.claude/` edits need approval headless
→ P-0003.
Result: merged 55c0b54, pushed. 489+8xf → **546 passed + 8 xfailed**. Hypothesis **met, then
amended**: "every role reads the same `now` the OMS uses" was false under a step back until the
read reported the ledger's now, not the clock's.
Learned: (1) Cycle 13's lesson recurred one level up: when a sink holds a law (ledger time), every
*reader* that reports the same quantity must report the held value too — not just rows that copy
it. "Now" is a ledger fact, not a clock fact. (2) My own fixtures hid a step back: freezing at
2019 after fixtures stamped 2026 was silently a rewind in every test that did it. A frozen moment
before the fixtures' stamps is a test of the step-back path whether I meant it or not. (3) Opening
a read can *shrink* the ledger: analysts' `/clock` calls used to append `permission_denied` events
every time.
Next: B-004 simulated clock (per-`run_id` floor scoping `ledger_now` and stamps; B-029 guard;
control endpoints never on a universal action — red-team 0006 guards it) → S-004b → B-028.

## Cycle 0015 — The backtest clock: a run is a database, its time a ledger fact (2026-10-11)
Era: I — The Desk
Exit criterion served: "one pod runs end-to-end" in backtest (Era I, TRD Phase 3 milestone: a
1-month backtest in under 10 minutes) — B-004 slice a: simulated time that only moves forward,
only by a privileged advance, and survives a restart.
Hypothesis: If a backtest is a fresh database whose first event `run_started` fixes its mode and
start, and its clock moves only through `POST /clock/advance` (a non-universal `CONTROL_CLOCK`,
bounded, forward-only, never past the real now) which appends `clock_advanced` and then runs the
pending-order sweep, then: live and backtest stamps can never share a ledger (the ADR-025 floor and
`ledger_now` are per run by construction), a restart resumes at the ledger's simulated now, a limit
order fills on the advance that crosses it, PMs/analysts get 403, live mode refuses to advance
(409), and B-029's forward-step risk cannot arise in a backtest.
Work: ADR-027 (+ amendment). `BacktestClock` + `wall_now()` (`app/clock.py`); `app/run_clock.py`
(`start_backtest` refuses any non-empty DB / naive / future start; `install_run_clock` from the
ledger; `advance` under `OMS_LOCK` from `ledger_now`, ≤ real now, appends `clock_advanced`);
`POST /clock/advance` (`CONTROL_CLOCK`, `{days, minutes}` 1 min..366 d, then the pending sweep) +
MCP `advance_clock`; lifespan and CLI install the run clock; `fund-env start-backtest`;
`clock.mode` removed from config; TRD §7/§9 amended. `tests/test_backtest_clock.py` (25). Red-team
0005's "no clock control" guard rewritten to the new law (not loosened — auditor confirmed).
Mutations: 7 laws, each red alone. Auditor **PASS** (3 WARN: lifespan untested → test; unguarded
backtest could pass as honest → `run_started.look_ahead_guard: false`; failed-commit stray stamps →
B-033). Red-team 0007: **3 medium holes**, 51 held — order priced at the old now but stamped at the
new; sweep `now` read outside the lock; a running live server stamping today into a file turned
backtest. All fixed (re-price under lock; read under lock; `append_event` refuses a clock that is
not its ledger's run → 503), each mutation-red alone. Re-audit **PASS** (WARN: sweep test vacuous
once fixed → asserts the outcome).
Result: merged 87ac9b9, pushed. 546+8xf → **628 passed + 8 xfailed**. Hypothesis **met, then
amended**: run scoping by construction held, but "the clock moves only by advance" was not enough
— every *reader* of now that acts later (order pricing, sweep, a long-running server) had to read
it at the moment it writes.
Learned: (1) The third time the same lesson (cycles 13, 14, 15): a value read outside the lock that
guards its write is a stale value. Discrete time makes it visible — a live clock hides the gap in
microseconds, a backtest step makes it a day. Read `now` where you stamp. (2) Choosing scope *by
construction* (one file per run) deleted a whole class of attacks — red-team found no cross-run
leak to try, only a process that had not noticed its file changed. (3) A red-team's suggested fix
can be the less safe one (self-heal vs refuse); judge by the seal, and pin the safer property.
Next: B-005 look-ahead guard (makes a backtest honest; flips `LOOK_AHEAD_GUARD`) → B-004b metrics/
market-data "now" = `ledger_now` (IDEAS c14) → S-004b.

## Cycle 0016 — The look-ahead guard: no feed may show the future (2026-10-11)
Era: I — The Desk
Exit criterion served: "one pod runs end-to-end" in backtest (Era I, TRD Phase 3b): a backtest
whose market data can see past the simulated now measures nothing.
Hypothesis: If the guard lives in the `MarketDataProvider` base as the only public entry
(`get_price`/`get_ohlcv` final; implementations write `_quote`/`_bars`), a bar is visible only
once it has *ended* (`bar_end(ts, interval) <= as_of`), a quote stamped after `as_of` (or
non-finite / non-positive) is refused, yfinance answers a past `as_of` from history instead of
today's quote, and the test double obeys the same law, then: no provider — real, static or test
— can serve D's close before D ends or today's quote to 2024; tests that certified the leak turn
red and are corrected with the reason; red-team 0004's two feed-price xfails pass; and
`LOOK_AHEAD_GUARD` can be flipped to True.
Work: (resumed at step 5. The previous session built and committed, then stopped before
verify; rule X-007.) ADR-028 (+ amendment). `MarketDataProvider` base: `get_price`/`get_ohlcv` the
only public entries (sealed: MRO check at creation, metaclass + instance `__setattr__` refuse
replacing them); bars served only once ended (`bar_end`); a quote stamped after `as_of`, or not a
positive finite price → `FeedDataError` (502 / `price_unavailable` / order stays pending); the
window handed to an implementation clipped to `as_of`'s day; no ended bar → one uniform 404.
yfinance: live quote only within 60 s of the real now, otherwise the latest ended 1d/1h bar's
close stamped at its end; past quotes cached per exact `as_of`. Backtests stay strictly > 60 s
behind the real now. `LOOK_AHEAD_GUARD = True`. Test double fixed. Auditor **PASS** (NOTE: the 0004
feed-price test only asserted `!= 500` → now asserts 502, nothing stored, `/price` 502). Red-team 0008:
**5 holes** (1 high: after the close `/ohlcv?interval=1h` showed today's 250 while fills used
yesterday's 180, a risk-free +39%; 2 medium: quote cache outlives a bar end, existence oracle via
`[]` vs 404 on rows after `as_of`; 2 low: seal dodged by mixin/setattr, 60 s off-by-equality),
12 held. All 5 fixed same cycle; each of the 9 fixes turns its test red when reverted alone. Re-audit **PASS** (notes →
B-035).
Result: merged cb6f4f6, pushed. 628+8xf → **675 passed + 6 xfailed** (red-team 0004's two feed-price
xfails closed). Hypothesis **met, then widened**: no feed serves the future. But that was only half
the law. The other half: the price must not be *older* than what the same world already shows, and no
answer may *depend* on what is not known.
Learned: (1) Look-ahead has three faces, not one: serving the future (the guard), *withholding*
the known present from the price (stale-quote arbitrage between two routes of one feed), and
*answers shaped by* the future (an error vs an empty list is a bit of information). An honest
backtest needs all three; only the first is a filter. (2) Consistency across routes is a law: when
two routes show "the market", the agent can trade the gap. The fill price must be the latest that
any route has revealed. (3) A defence that is redundant with another is invisible to mutation
testing, so each needs its own test (the clip and the uniform 404 each closed the oracle alone).
Next: B-004b one "now" (`ledger_now`) for metrics/market data + the Phase 3 milestone probe →
S-004b → B-028.

## Human intervention — 2026-10-11 (P-0003)
- Permanent fix for "the Builder can't edit `.claude/`": your process now lives in `protocol/`
  (Builder-owned): `protocol/CYCLE.md` is the full cycle protocol (X-007 resume rule added at
  step 0), `protocol/agents/*-extra.md` extend auditor/red-team (additions only), new helper roles
  and skills go in `protocol/`. `.claude/commands/cycle.md` now only points there and holds the
  three gates + the `loop_status.json` rule; it and `.claude/agents/` are sealed (Constitution 6.1).
- `protocol/`, CLAUDE.md, 06_LOOP §8, PROPOSALS and this entry may be uncommitted: commit them in step 0.

## Cycle 0017 — One now: every physics reader of time reads the ledger's now (2026-10-11)
Era: I — The Desk
Exit criterion served: "one pod runs end-to-end" in backtest (Era I, TRD Phase 3): price,
valuation and stamp of one act must be one moment, or the backtest's P&L measures a gap.
Hypothesis: (written at step 4 by the Builder, recorded here at step 8 — the journal was being
edited by the Human's intervention mid-cycle.) If every physics reader of "now" — `/price`, the
`/ohlcv` defaults, `/portfolio`, pod metrics, the leaderboard, the OMS reference price and the
sweep — reads `ledger_now(session)` instead of the raw clock, and an AST test pins every other raw
read to an allowlist with reasons, then after a clock step back all of them answer at the moment
`/clock` reports and the next order is stamped with, and a new raw read in physics is red.
Work: ADR-029 (+ amendment). Seven readers moved to `ledger_now`; `tests/test_one_now.py`
(step-back scenario: ledger on 10 June, clock back to 5 June, every route answers at 10 June —
each red before; AST law). Red-team 0007's sweep spy moved to `monitor.ledger_now` (same read,
same property). Auditor **PASS** (WARN ×2: allowlist per file → per read; detector too narrow →
widened; NOTE: one read under the lock; docstring). Red-team 0009: **6 findings** — 1 medium (the
advance moved the process clock before committing its event: lock-free reads showed tomorrow's
close, and a failed commit took the day back), 4 low (metrics/leaderboard read now twice; a
concurrent sale counted twice in the book; 8 detector dodges), 1 low open (cross-process
`OMS_LOCK` gap → B-036, 2 strict xfails). Fixed: `append_event(at=)` (one caller by law) so the
advance commits first and moves the clock after; one `now` passed down through metrics and the
ranking; positions and cash read together under `OMS_LOCK` before pricing; the detector sees
imports, `_now`, `wall_now`, `current_timestamp`, computed `getattr`, `methodcaller`. Mutations:
clock-before-commit → red; cash-after-pricing → red; the lock part of the book fix is
defence-in-depth (in-thread RLock), said in the ADR. Re-audit **PASS** (NOTE: pin `at=` callers →
done). Mid-cycle the Human's P-0003 intervention landed (`protocol/`, CLAUDE.md, 06_LOOP §8,
PROPOSALS, this journal); committed on main after the merge as its entry asks. `setup/` (the
Human's one-shot installer for protected files) left untouched: it makes
`test_every_python_directory_is_placed_in_the_law` fail in the working tree only — the committed
tree has no `setup/`.
Result: merged f03fb6c, pushed. 675+6xf → **717 passed + 8 xfailed** (+2 = B-036). Hypothesis
**met, then widened**: the readers now agree on *which* now; red-team showed the law also needs
*how many* reads one answer takes (one) and *when* a now becomes visible (only after its event
commits).
Learned: (1) An in-memory mirror of ledger state (the installed clock) must move only after the
event that justifies it commits — otherwise lock-free readers see a future the ledger may never
reach. Ledger first, mirror second. (2) "Read where you stamp" (cycles 13–15) has a twin: "read
once per answer". Two reads of now in one report are two moments. (3) A mutation that doesn't go
red is information, not failure: the book fix was the read *order*; the lock was redundant in
the test's thread and is honestly labelled defence-in-depth.
Next: B-004c the Phase 3 milestone probe (one scripted pod, 1-month backtest, twice to the same
curve) → S-004b → B-028 (shrinks the time-read allowlist).

## Cycle 0018 — The Phase 3 probe: a scripted pod lives a month, twice, identically (2026-10-11)
Era: I — The Desk
Exit criterion served: "one pod runs end-to-end" in backtest (Era I; TRD Phase 3 milestone: a
1-month backtest in under 10 minutes) and the first determinism test ("Boundary + determinism
tests pass").
Hypothesis: If a seeded `SyntheticProvider` derives every daily bar from (seed, symbol, day)
alone — no network, no request-order dependence, obeying the ADR-028 base — and a scripted,
LLM-free pod drives a fresh backtest database only through the HTTP API (read `/clock`, `/ohlcv`,
`/price`, place market orders with justifications, management advances one day per step for 31
days), then: the month runs in well under 10 minutes; two runs in two fresh databases produce the
same equity curve *and* the same ledger (types, stamps, payloads, modulo per-run secrets); a
different seed produces a different curve (the test is not vacuous); and whatever in physics is
*not* deterministic shows up as a diff the test names. (The hypothesis says "seed"; the world
became a secret *key* before merge — see Work.)
Work: (resumed at step 5 — the previous session built, red-teamed and fixed, then stopped before
the re-audit; rule X-007.) `SyntheticProvider` (daily GBM from `HMAC-SHA256(key, "return:…")`,
wicks/volume from a `"noise:…"` domain, 1wk/1mo aggregated with running periods never computed,
1h refused); `tests/test_phase3_probe.py` (scripted 5/20-day MA pod, HTTP only, 31 advances, fresh
DB per run; world 11 twice → identical ledger event for event, curve, book, `rebuild_state`,
`/metrics/pod`; world 12 differs); ADR-030 (+ amendment). Red-team 0010: **1 high hole** — the
first version was an int seed with default 0 and three served volumes recovered it, pricing SYNA a
week ahead exactly; 6 properties held (edges, routes, oracles, seed exposure, window cost). Fixed:
≥128-bit key, HMAC, noise in its own domain, env only, no default; the hole test re-aimed at the
keyed law with a companion proving the search works on a guessable key. Re-audit (this session)
**PASS**: WARN "env only is a comment, not code" → `config.yaml` carrying `synthetic_key` now
refuses to load; NOTE odd-length hex → refused at startup; TRD repo map updated. Both new tests
red before the fix.
Result: merged 71d6492, pushed. 717+8xf → **770 passed + 8 xfailed** (working tree: +1 known
`setup/` failure, the Human's untracked installer). Hypothesis **met**: 31 days in ~0.55 s
(budget 600 s); the same world gives the same ledger, not just the same P&L; nothing in physics
diffed between runs. **Amended**: a determinism seed is also the world's future — it must be a
secret.
Learned: (1) A determinism tool and a secrecy tool are the same function; the only difference is
who holds the input. Any agent-visible byte derived from the seed is a leak channel, so noise needs
its own domain and the seed needs entropy, not obscurity. (2) "Environment only" written in a
comment is a wish; the auditor was right to want it in the loader. A rule about where a secret
lives is a physics law like any other. (3) X-007 worked a second time: resuming at the gate cost
one audit, not a rebuild.
Next: B-037 (a run records its world by fingerprint) → B-036 / B-028 (the probe now gives a
determinism harness to test them against) → toward the Runtime (Era I exit: one pod via the
Runtime).

## Cycle 0019 — A run records its world, and lives in only one (2026-10-12)
Era: I — The Desk
Exit criterion served: "Boundary + determinism tests pass" and the Era I backtest criterion — a
backtest is evidence only if its ledger says which world it ran in (B-037 slice a; ADR-030 "not
done").
Hypothesis: If every provider describes its world as a JSON record (`world()` — provider name,
whether it is reproducible, and for the synthetic market the law version, origin, drift,
volatility, symbols and an `HMAC-SHA256(key, "fingerprint:v1")` fingerprint), `run_started`
carries that record, and `install_run_clock` refuses a backtest database whose recorded world
differs from the installed provider's, then: the probe's ledger names its world (same key → same
fingerprint, other key → other fingerprint); a server or operator command started on a run with
the wrong key, symbols or provider refuses to start instead of silently splicing two markets into
one ledger; and no agent-visible surface carries the key (red-team 0010's held test stays green,
plus a new one: the fingerprint reveals no served noise or return).
Work: `MarketDataProvider.world()` (default `{provider, reproducible: false}`); synthetic record
(law `hmac-sha256-gbm/1`, origin, drift, volatility, sorted symbols, 128-bit fingerprint in its own
HMAC domain); `start_backtest` writes `run_started.world` from the installed provider;
`install_run_clock` → `_require_same_world` refuses naming the differing fields (server lifespan
fails, CLI exits 1, nothing appended); pre-ADR runs without `world` pass. Two fixtures (probe,
`honest_backtest`) had opened runs in the static table and served them from another provider —
the law caught exactly that; they now install the world first. ADR-031 (+ amendment).
`tests/test_run_world.py` (13). Auditor **PASS** (NOTE fixed: keyless `start-backtest` → Error,
exit 1). Red-team 0011: **1 low hole** — a static run restarted on another table — fixed
(`StaticProvider.world()` records its configured table), 8 held (only management reads `/events`,
no key spelling leaks, fingerprint no window/no brute-force target, HMAC zero-padding keys are
the same world, float/spelling round-trips, agents cannot block a restart). Re-audit **PASS**
(NOTE fixed: a self-referential assertion made literal).
Result: merged 842e958, pushed. 770+8xf → **796 passed + 8 xfailed** (working tree: +1 known
`setup/` failure). Hypothesis **met**; widened by red-team: "reproducible" and "checkable" are
different properties — a world can be checked for sameness without being re-runnable.
Learned: (1) A new physics law is validated best by the old tests it breaks: two fixtures had
been quietly splicing worlds for cycles. (2) "Not reproducible" was being used to mean "nothing
to record"; any configuration that determines answers belongs in the record, even when the run
cannot be replayed from it. (3) An assertion that compares a function's output with itself is
not a test — the auditor caught one I wrote while updating an exact-shape check.
Next: B-037b (a `fund-env backtest` driver that re-runs a ledger's world from the operator's key
file and diffs the ledgers) or B-037c (which agents have lived which worlds) → the Runtime plan →
`bible/09_BUILDER_VISION.md` at the cycle-20 retrospective.

## Cycle 0020 — Retrospective, the Builder's vision, and the Runtime plan (2026-10-12)
Era: I — The Desk
Exit criterion served: all seven Era I exit criteria are Runtime criteria, and 0 of 7 are ticked
after 19 cycles. This cycle turns them into an ordered, sliced plan, and writes
`bible/09_BUILDER_VISION.md` (due at the Launch Pad's end — cycle 20 at the latest, STATE).
Hypothesis: If I re-read 00 + 01, measure cycles 11–19 against the cycle-10 retrospective's
promises, and write (a) the vision one step ahead of the work and (b) ADR-032 fixing the Runtime's
shape (lockstep scheduler, mind = provider + adapter behind the App's tool surface, cassettes,
cap/halt gates, its own clock identity), then every open Era I exit criterion is served by at
least one backlog slice sized for one cycle, the slices are ordered so the first needs no physics hole
fixed first, and the next 5–6 cycles need no further planning to start. Docs only: no code, no
test count change (796 + 8 xfailed).

### Retrospective — cycles 11–20 (06_LOOP §6; re-read 00 + 01 this cycle)
- **Pointed at the Era's question?** Partly. Cycles 11–19 were all physics: halt, portable JSON,
  replay order, the clock read, the backtest clock, the look-ahead guard, one now, the keyed
  synthetic month, the world record. Each one was a precondition for an *honest* backtest, and
  the Era's question includes "reproducibly", so none of it was waste. But the cycle-10 promise
  was "the next 10 cycles must end with a pod acting in simulated time against a fake provider".
  Only half of it is met: a *scripted* pod acted (cycle 18) **in the test suite**, with no
  Runtime and no provider seam. Era I exit criteria are still 0 of 7. Drift named: seal-first
  slid toward seal-only. The red-team returns are falling (0011: one low, operator-only hole),
  the signal that the time frontier is exhausted.
- **Failures:** 9/9 merged (11–19), 0 failed, 0 blocked. Auditor BLOCK rate fell from 5/10 to
  **2/9** (c11 ×2, c12 re-audit) after X-006 was done by hand, so the metric moved and X-006 is
  now protocol. Every cycle's red-team found holes: 2, 6, 2, 1, 3, 5, 6, 1, 1. **Three were high**
  (c12 deep-JSON inbox poisoning, c16 1h-vs-daily stale-quote arbitrage, c18 seed recovery from
  volumes), and all were fixed in the same cycle. The red-team is the most valuable part of the
  process: the Builder alone shipped three high holes to the gate. **Interruptions:** 3 of 9
  sessions stopped mid-cycle (13, 16, 18) and resumed cleanly at step 5 (X-007 works). Average
  cycle ~45 min: physics slices are sized right at the edge → X-008.
- **What became boring:** time physics. One now, the guard and the world record now hold under
  attack, and new holes are operator-only. **The frontier moves to the Runtime** (ADR-032,
  R-1…R-8). Physics work from here on happens only when a Runtime slice needs it or an agent can
  reach it.
- **Scales:** S0 answered P-0001…P-0003 (process) and none of Q-0001/Q-0002 (money, keys): the
  world must reach M5 without a budget, and it can. S1: about 8 of 9 cycles ended with an ADR
  amendment or a widened hypothesis (all of 12–19 per METRICS; the auditor's count). The
  widening came from the red-team or the auditor, not from the Builder's own pre-mortem, so the
  planted-counter-example check is now protocol.
  S2: physics now has a determinism harness (the probe) that the Runtime can reuse.
- **Ambition check:** is the world more impressive than 10 cycles ago? More *truthful*, clearly:
  a month is a pure function of a secret, and a run proves which world it lived in. Not yet more
  *capable*: no mind has acted. What would make the Human say "I've never seen that"? The exact
  counterfactual fork (vision §2): replay an LLM firm to day *d* for free, change one mind, and
  watch history branch. Every slice R-1…R-4 builds toward it.
- **Process changes** (Era ∞, `protocol/CYCLE.md`): X-004 smoke run in verify, X-006 claim check
  with its three questions + "new laws audit old tests", X-008 size check at step 2.

Work: `bible/09_BUILDER_VISION.md` (thesis: a run is a proof object of physics + world + minds;
the exact counterfactual fork; milestones M1–M6; candidate post-Launch-Pad Eras; working laws).
ADR-032 (Runtime v1: a client process over `FundClient`, one MCP tool surface, mind = provider +
adapter + spec, a cap gate that fails closed on `{scripted, cassette}`, HALT checked per wake and
per tool batch, a lockstep scheduler in agent-id order, a `runtime` clock identity, cassettes),
plus an ADR-021 amendment. BACKLOG: a Runtime section R-1…R-8 folding in
B-009/010/011/012/013/015/032 and others, B-039 (information-shape gate), id collision B-023 →
B-023s. Q-0005. IDEAS: 3 new + 3 write-ups. 05 Era I plan note, Era ∞ path, 03 §4 pointer.
`protocol/CYCLE.md` steps 2 and 5. Auditor **PASS** with 4 WARN + 6 NOTE, all fixed: the cap gate
had trusted each provider's own `spends_money` flag (now a closed list in code), the per-batch
halt check was missing, scripted months could have ticked EC1/EC2, and three claims were too
wide. Re-audit **PASS** with 1 WARN, fixed: the rule on which exit criteria scripted runs may
tick contradicted itself. Now one rule: run criteria (EC1, EC2, EC7 live) need real minds, and
test criteria (EC3–EC6) may be met by tests. No red-team: no physics change.
Result: merged 34c1a59, pushed. 796 passed + 8 xfailed (working tree +1 known `setup/` failure).
Hypothesis **met**: every one of the 7 exit criteria is served by at least one slice, R-1 needs
no physics hole closed first, and R-1…R-5 are specified well enough to start.
Learned: (1) The auditor's sharpest catch was in my own plan: a gate that asks a component
whether it is dangerous is not a gate. Cap gates must fail closed on a list the gate owns. (2) A
rule about what may be claimed ("tick") has to be written once, or it drifts into three
different strictnesses across three files in one cycle. (3) Writing the vision exposed the real
ambition gap: the world is more truthful than ever but no more capable. The fork gives the
next ten cycles a destination.
Next: R-1 Runtime skeleton + gates → R-2 scripted mind + native adapter → R-3 lockstep month (M1).

## Cycle 0021 — R-1: the Runtime's skeleton and its gates (2026-10-12)
Era: I — The Desk
Exit criterion served: EC5 (HALT stops agents) and EC6 (cap `null` → the Runtime refuses to wake
agents). The gates come first so no later slice can wake anything without passing through them.
This slice does not tick either criterion: R-5 ticks them, with agent-level tests through the tool layer.
Hypothesis: If `runtime/` gets (a) an `AgentSpec` (the 03 §3 fields, frozen, extra fields
forbidden, file-backed, ids unique and ordered), (b) a governance reader on fixed paths that reads
`governance/HALT` and `human.yaml` fresh on every call and turns every unreadable or malformed cap
into `null`, (c) a wake gate keyed on a closed list in code, `{scripted, cassette}`, that never asks a
provider what it costs, (d) an `LLMProvider` protocol, and (e) a `fund-runtime status` command that
wakes nothing, then: under HALT no provider passes; under cap `null` an unknown provider and one
that claims `spends_money=False` are both refused; a malformed cap fails closed; and the dynamic
boundary probe shows that importing the Runtime loads no physics module outside
`{app, app.config, app.limits}`. A planted counter-example proves the probe can fail. Expected:
about 30 new tests, no physics change.
Work: `runtime/` gained five modules:
- `governance.py`: fixed paths; HALT read first, by `lstat`; a duplicate-refusing YAML loader;
  every parse failure → `null` + `cap_problem`.
- `gate.py`: `decide_wake(provider, adapter)` / `decide_batch()`. Zero-cost means
  `{scripted, cassette}` × `{native}`, both exactly `str`. A numeric cap still refuses spending
  (`no_metered_key`) until R-6.
- `spec.py`: AgentSpec with the 03 §3 fields + `provider`. It is frozen and forbids extra fields.
  YAML files load in id order; duplicates, other extensions and non-str keys are refused.
- `providers.py`: the `LLMProvider` protocol and its request/response models.
- `cli.py`: `fund-runtime status`, which wakes nothing.

The `fund-runtime` script and the wheel package are in pyproject. The dynamic boundary probe
imports every runtime module, with a planted counter-example. The static scanner now refuses
imports it cannot read. ADR-032 amendment (a)–(f); 03 §1 law note.

Review findings:
- The claim check found one hole before review: `os.path.lexists` answered False on any OSError,
  which failed open.
- Auditor **FAIL** (1 BLOCK): non-UTF-8 input, an unhashable key and deep nesting raised out of
  the reader, and the cap was read before HALT. There were also 3 WARN (weak tests and an
  evadable static check) and NOTEs. All fixed.
- Red-team 0012: **10 holes**, all fixed. 4 were already fixed by the audit fixes; 6 were
  strict xfails, now removed.
  - **H1, high:** `scripted` + `adapter: openclaw` woke under null.
  - H3, medium: a missing `governance/` read as running.
  - Low: H4 str subclass, H5 non-str spec key, H7 base-60 `1:30` read as $90, H8 computed
    imports invisible.
- Re-audit **PASS**, 1 WARN fixed: ADR (f) claimed more import spellings than the scanner
  caught. It now catches all of them, with planted tests; the `is_dir` race fails closed.
Result: merged 8d6e2fe, pushed. 796+8xf → **967 passed + 8 xfailed** (working tree +1 known
`setup/` failure). Hypothesis **met and widened**: "never asks the provider" was not enough. The
adapter is a second cost axis, and the gate must own both lists. No physics change. EC5/EC6 are
served, not ticked (R-5).
Learned: (1) "Fail closed" has to be proved per error class. My first reader failed open on
`lexists`, and then crashed on three parser errors I had not imagined. Catching broadly and
recording the reason is the honest shape for a gate's input. (2) A gate keyed on one field
of a multi-field identity is a gate on the wrong thing. The red-team's high finding came from
reading ADR-032 (4) more literally than I had. (3) A path computed from `__file__` is a claim
about how the code is installed; check the directory as well as the file.
Next: R-2. The scripted mind, the provider registry (each zero-cost name → one class) and the
`native` adapter over `build_server`'s tool list, with HALT checked per tool batch.

## Cycle 0022 — R-2: a scripted mind wakes through the native adapter (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1 (one pod end to end *via the Runtime*) and EC5 (HALT stops agents),
both served, neither ticked (R-3/R-5/R-8 tick them). Vision milestone M1.
Hypothesis: If the Runtime gets (a) a provider registry that maps each zero-cost name to exactly
one class and builds the mind itself (the adapter never accepts a provider object), (b) a
`scripted` provider whose policy is a pure function of the request, chosen by name from a closed
table, with no model and no network client, (c) AgentSpec rules that a zero-cost spec names no
`model` and no budget and that `script` is set iff the provider is `scripted`, and (d) a `native`
adapter whose tool list is exactly `build_server`'s (narrowed by `spec.tools`), whose context is
charter + `/me` + workflow input assembled by code and returned in a wake record, which re-reads
HALT before every tool batch and stops at a per-wake tool-call budget — then the probe's
moving-average PM, rewritten as a script, trades a pod for several backtest days purely through
MCP tool calls; the same days twice leave the same ledger; HALT created between batches stops the
wake before the next batch runs; and a mind calling a tool outside its list or past its budget
reaches no endpoint. Expected: ~30 new tests, no physics change.
Work: Resumed after an interruption. The build was uncommitted in the working tree; I recognised
`setup/` as the Human's installer and left it alone. First I fixed one wrong column name in a new
test (`agent_id` → `created_by`). Then I committed `runtime/registry.py` (name → one class, with
contradiction refusals), `runtime/scripted.py` (closed `SCRIPTS`, `moving-average-pm`),
`runtime/native.py` (the adapter), the AgentSpec `script` field and `Message.tool_calls`/`is_error`.
The old law test that pins AgentSpec's extra fields to exactly `{provider}` failed. That is a
finding: the fix is ADR-032 amendment (g), which adds `script`, not a test edit. The auditor
returned **BLOCK**: HALT was read per batch but not per call, and not before the next model turn
(Art. 5.2). It also gave 3 WARNs: a provider exception escaped without a record, the mind could
rewrite the record through shared objects, and the import lint overclaimed. All of these are
fixed, with tests. Red-team 0013 then found **8 holes**, all fixed (amendment (i)):
- **H1 (medium):** path traversal through `get_price("../agents")` got around tool narrowing.
  This is the open B-000h from red-team 0001; MCP path values are now escaped, and the 0001 xfail
  is now a guard.
- **H2/H3 (medium):** a spec was not bound to its key (identity_mismatch).
- **H4 (medium):** a deep copy I added in the audit fix raised RecursionError and lost the record.
- **H5–H8 (low):** duplicate call ids, a non-JSON reply, non-JSON input, and `wake_policy: never`.

Re-audit **PASS**; I applied 4 of its 5 NOTEs (whole-reply JSON check, narrowed claims).
Result: merged db3e7ee, pushed. 1084 passed + 7 xfailed. The working tree also has the 1 known
`setup/` failure. xfails went 8 → 7: B-000h is closed. Smoke run 12/12. Hypothesis **met, with
corrections**. The probe PM, rewritten as a script, trades a 31-day synthetic month purely through
MCP tool calls. The same world twice gives the same ledger and the same transcripts. HALT stops
the wake, now before the next *call* and not only the next batch. A tool outside the list, a
budget overrun, a wrong key or a bad reply reaches no endpoint. One physics-surface change, against
the hypothesis's "no physics change": the MCP wrapper escapes path values. About 120 new tests,
not about 30.
Learned: (1) **A fix can open a hole.** The audit's deep-copy fix added the H4 crash. Red-team
after the audit fixes, on the fixed commit, caught it; the order matters. (2) "Narrowed by tool
name" is not "narrowed by endpoint". A tool's *arguments* can choose the endpoint, so the wrapper
must be part of the seal. (3) A record is only as good as its serialisability: validating at the
door (JSON round trip, fresh ids) is cheaper than R-4 finding unserialisable cassettes. (4) The
interrupted-cycle resume worked again (X-007), but the interruption cost the step-5 context.
Commit the build before step 5, so a resume starts from a commit.
Next: R-3. The lockstep backtest workflow, plus a reserved `runtime` clock identity (B-032,
B-000f): a scripted PM + Analyst live a month through the Runtime, with every act over HTTP, and
the run is labelled `minds: scripted` (M1).

## Cycle 0023 — R-3a: the world's clock belongs to the Runtime, not to management (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1 (a month *via the Runtime*: the conductor needs a clock identity no
firm agent holds) and the seal for every later LLM manager (B-032, Art. 10). Size check (X-008):
R-3 is split. R-3a (this cycle) is the identity, a physics change that needs red-team. R-3b is the
lockstep workflow + the PM/Analyst month. R-3c is `daily_cycle`.
Hypothesis: If (a) a new role `runtime` holds `CONTROL_CLOCK` and only the universal actions,
(b) `management` loses `CONTROL_CLOCK`, (c) the identity is created only by the operator CLI
(`fund-env seed-runtime`, one per database, key shown once) and can never be registered over
HTTP, and (d) `system` is looked up by role, and registering the reserved names `system` or
`runtime` (in any case or spacing) is refused, then: a management key gets 403 + `permission_denied`
on `POST /clock/advance`; the runtime key advances the clock and can place no order, send no
message and register no agent; the red-team 0001 squat xfail turns into a guard; and every old
test that advanced the clock with management's key is a finding of the old law. Those tests move
to the runtime key, the change is logged in the ADR, and no assertion is weakened. Expected: about
25 new tests, 1 xfail fewer (7 → 6), no migration (the role column is a non-native enum with no
CHECK constraint).
Work: `AgentRole.runtime`; `PHYSICS_ROLES` in `permissions.py`; `ReservedIdentityError`,
`is_reserved_name`, `seed_runtime_agent` and a role-based `get_or_create_system_agent` in
`registry/service.py`; a refused physics deactivation gives 403 + `permission_denied`
(`reason: reserved_identity`); `fund-env seed-runtime`; the MCP `advance_clock` description;
ADR-033. The old law broke 9 test files plus `test_oms_permissions` (it registered a `system`
agent) and the 0001 squat xfail (now XPASS). They were moved by a checked script (every
replacement count was asserted), with every assertion kept; 3 got stronger (management is now
403). Review:
- Auditor **PASS**, no BLOCK. 4 of its 8 NOTEs applied: the runtime role is narrowed to halt +
  clock, so no cost, task or inbox row can pass for agent activity; the refusal reason is
  recorded; the month test proves 31 advances by one hand; the 0001 guard asserts the 409.
- Red-team 0014: **1 hole (low)**. The name fold dropped only Cf, so `runtime` + U+FE0F, Hangul
  fillers, U+2800 or NUL registered as a second "runtime" in the directory. It is fixed: the fold
  drops Cc Cf Cn Co Cs Mn Me and the blank letters. 30 guards held, including a walk of every
  published route with the runtime key.
- Re-audit **PASS**; 2 NOTEs applied.
Result: merged 5397ad2, pushed. 1084+7xf → **1178 passed + 6 xfailed** (the working tree also
has the 1 known `setup/` failure). Smoke 12/12. Hypothesis **met**: management gets 403 and a
record; the runtime key advances and does nothing else; the squat xfail is a guard; no migration.
Wider than planned: the runtime role lost the universal actions too, and the name fold had to
learn what "invisible" means. ~94 new tests (not ~25), most of them red-team guards.
Learned: (1) **Moving a privilege is a test-suite event.** 44 call sites encoded the old law. A
replacement script that asserts each count turned a risky mass edit into a reviewable one, and
the auditor could check old vs new assertions table by table. (2) **"The universal actions" is
not neutral for a non-agent.** The audit pointed out that a clock hand that can file cost reports
writes rows that look like agent activity. An identity that is not a participant should get no
participant-shaped verbs at all. (3) **"Invisible" is not a Unicode category.** Cf was my guess;
Default_Ignorable spans Mn, Lo and So. A fold for humans' eyes needs a list of what draws nothing,
and a red-team to grow it.
Next: R-3b. The lockstep backtest workflow in `runtime/`: halt/cap → wake specs in id order →
advance with the runtime key. A scripted PM + Analyst (the Analyst messages a signal, the PM
trades on it) live a month, labelled `minds: scripted` (M1).

## Cycle 0024 — R-3b-1: the conductor, and a way back from a lost clock key (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1 (a month *via the Runtime*: the loop leaves the test and lives in the
Runtime), M1 groundwork. Size check (X-008): R-3b is split. R-3b-1 (this cycle) is B-041, a
physics change to the registry that needs red-team, plus the lockstep conductor
`runtime.lockstep.run_backtest`. R-3b-2 is provisioning from specs (the spec's name is bound), the
Analyst script, the PM + Analyst month, the `fund-runtime backtest` CLI and the run label in
physics' run record.
Hypothesis: If (a) `fund-env rotate-runtime-key` replaces the runtime identity's key hash and
records `agent_key_rotated` (the agent id only, never the key or its hash), (b) the server and
the operator CLI refuse to start on a database where a non-physics agent holds a reserved name
or where more than one runtime row exists, and (c) `run_backtest(minds, clock, steps=N)` wakes
the minds one at a time in spec-id order and then advances the clock with a key whose `/me` is
`runtime` (and refuses any other clock key, a live run, duplicate ids or a bad step count), then:
the old key gets 401 after rotation and the new one advances; a pre-ADR-033 `system` squatter
stops the server at startup, not at first use; the R-2 month test drives the conductor instead
of its own loop and still leaves the same ledger twice; HALT before a step, or inside a wake,
ends the run `halted` with no further advance; and a refused wake ends the run `refused`, with no
advance, rather than letting the world move without one of its minds. Expected: ~30 new tests,
xfails unchanged (6).
Work: resumed an interrupted session (X-007): the build, claim check and first audit were
already committed (d31df89…498b0ce). Red-team 0015's fixes were in the working tree, uncommitted,
and were committed first (X-009).
- `fund-env rotate-runtime-key` records `agent_key_rotated`. The server and the operator CLI
  check `reserved_identity_problems` at startup (B-041, ADR-033 (b)).
- `runtime.lockstep.run_backtest` (ADR-032 (j)). The R-2 month test drives the conductor.
- The claim check pinned every DB-clock operator command to refuse a squatted DB.
- First audit: PASS (WARN 1 seed guard re-pinned, NOTE 2 `clock_malformed`).
- Red-team 0015: **4 holes, all fixed.**
  - H1 (medium): management fired a peer PM mid-run, the peer's wake was refused and the
    *whole run* ended, so a firm agent could freeze the world's time. Now a mind whose key gets
    401 after a refused `no_identity` wake is *retired* and the run goes on.
  - H2: one App agent's key under two spec ids got two turns a step. Now every `/me` is read
    before step 0, with `duplicate_agent` / `identity_mismatch` / `mind_unreadable`.
  - H3: the sweep fails after the advance commits, and the record said "did not move". Now
    `/clock` is re-read.
  - H4: the input was copied shallow. It is deep now.
- Re-audit: PASS. WARN 1 (a failed re-read looked like "stayed") → `:clock_unknown`. WARN 2
  ("retired = never woken" unpinned) → the H1 test asserts b-pm's wakes per step. NOTE 1–2
  applied, NOTE 3–5 → R-3b-2.
- One old test expectation changed: an identity mismatch now refuses before step 0, so it is
  stricter. The mid-run refusal claim is kept by a new test, with a script that vanishes.
Result: merged c3cbfd4, pushed. 1178+6xf → **1261 passed + 6 xfailed** (the working tree also has
the 1 known `setup/` failure). Smoke 12/12. Hypothesis **met, with one rule reversed**. "A
refused wake ends the run" was right for a mind the run cannot wake, and wrong for a mind the
*world* removed. Left alone, it handed the clock lever ADR-033 had just taken away back to
management, through the back door.
Learned: (1) **Every "the run stops if X" is a lever for whoever can cause X.** ADR-033 took the
clock from management, and the conductor's own stop rule gave it back. Each stop condition
needs the question "who in the sim can trigger this?". If the answer is a participant, the
condition is data, not a stop. (2) **`None` must not mean two things in a record.** "Stayed" and
"cannot know" both came out as `advanced_to=None`. An honest record keeps them apart. (3) Writing
the per-step expectation for H1 by hand, I got the id order wrong: management wakes before the PM
it fires, in the same step. The test caught my model of the conductor, which is the point of
pinning shapes, not just outcomes.
Next: R-3b-2. Provision agents from specs (bind the name), the Analyst script, the PM + Analyst
month through the conductor, `fund-runtime backtest`, and the label in the run record (M1).

## Cycle 0025 — R-3b-2a: a pod of two minds lives a month, and a list of one stays a list (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1 (the 1-month criterion needs a PM + Analyst *via the Runtime*; this
builds it with scripted minds, which never tick it — R-8), M1. Size check (X-008): R-3b-2 is
split. R-3b-2a (this cycle, no physics change): the Analyst script, a PM script that trades only
on its own pod's analyst's signal for today, the PM + Analyst month through `run_backtest`, and
the c24 carry-overs (tool-function failures counted, the step each mind was retired at, NOTE 3
pinned, NOTE 4 written down). R-3b-2b: provisioning from specs (the name bound), `fund-runtime
backtest`, the run label in physics' run record (touches physics → red-team).
Discovery while orienting (probed, `/tmp/probe_list.py`): MCP renders a list result as one text
block per item, so a **one-item list reaches a mind as the bare object** and an empty list as
nothing. A PM reading an inbox of one message could not tell it from a message object. That is
`None`-means-two-things again, on the tool surface every adapter shares.
Hypothesis: If (a) every list-valued MCP tool answers with one JSON array block, (b) the Analyst
(`ma-signal-analyst`) reads bars and the clock and posts `{"kind": "signal", "as_of": now,
"signals": {ticker: long|flat}}` to its pod, and (c) the PM (`signal-pm`) trades only on the
newest signal stamped with today's now from an analyst of its own pod (found by `list_agents`),
then: a 31-day synthetic month of analyst `a-…` + PM `b-…` through the conductor completes, every
PM order has a same-day analyst signal behind it, a PM without its analyst's signal holds, a
signal from another pod or a stale one is ignored, two runs leave the same ledger and transcripts,
and the month takes well under 10 minutes. Expected ~20 new tests, xfails unchanged (6).
Work:
- `mcp_server.tools`' shared `call` answers a list as one JSON array block (ADR-032 (k)). No
  existing test pinned the old shape; a new one fails without the fix (mutation checked).
- `ma-signal-analyst` + `signal-pm` in `SCRIPTS`; `_crossing` / `_rebalance` factored out of
  `moving-average-pm` with its behaviour unchanged (auditor checked branch by branch).
- `WakeRecord.tool_failures`. The first version counted nothing: MCPServer wraps *every* tool
  exception in a `ToolError`, so the adapter's `except Exception` branch is almost dead. A probe
  showed the original rides in `__cause__`: `ToolError` (the tool speaking), `ValidationError`
  (the mind's arguments), none (unknown tool), anything else (a bug). Classified by that.
- `RunRecord.retired_at`; NOTE 3 and NOTE 4 pinned by tests (management fires the PM, then
  itself; steps 4–5 wake no one and the clock still moves).
- `tests/test_runtime_pod.py`: 13 script cases on crafted transcripts, and a two-pod month
  (pod 1: analyst + PM; pod 2: a PM with no analyst) through `run_backtest`, twice.
- Mutations: dropping the sender-is-analyst check fails 2 cases; dropping the same-day check
  fails 1.
- Auditor: **PASS**, 0 BLOCK, 7 NOTEs. Applied: the PM now also requires physics' own stamp
  `ts == now` (a pre-dated signal was trusted on its claim) and an *active* analyst; the
  50-message window is written down; `ensure_ascii=False`; stale docstrings; ADR wording. NOTE 4
  (a `ValidationError` from a bug inside a tool body) is written into the ADR as a known limit.
- No physics change (`app/` untouched), so no red-team pass.
Result: merged b0c83a1, pushed. 1261+6xf → **1287 passed + 6 xfailed** (plus the 1 known `setup/`
failure in the working tree). Smoke 12/12. Hypothesis **met**. The month runs in seconds, not
minutes. Every pod-1 order cites a message its analyst sent at the same simulated instant. Pod 2
held all 31 days. The two runs were identical event for event.
Learned: (1) **Probe the layer you wrap before you count through it.** The `tool_failures` test
failed first because the MCP server had already turned every exception into a `ToolError`. The
R-2 docstring had said for three cycles that tool bugs land in `except Exception`; they never did.
(2) **A mind's trust rule needs physics' facts, not the message's claims.** My first PM trusted
`as_of` from the payload. That is what the sender *says*. The auditor saw that a pre-dated signal
would be believed. `ts` is what physics *recorded*. The same rule will hold for every LLM agent
in Era II, which is a reason to show `ts` prominently in the tool's description. (3) **Multi-mind
work found a single-mind blind spot.** One PM alone never reads a list of one, so the MCP list
shape went unnoticed through R-2 and R-3b-1.
Next: R-3b-2b. Provision App agents from specs (bind the spec's name), `fund-runtime backtest`,
and the run label `minds: scripted` in physics' run record (physics → red-team).

## Cycle 0026 — R-3b-2b-1: minds are provisioned from their specs, and a key must wear its spec's name (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1 (M1: the PM + Analyst month with minds made from specs, not
hand-registered). Size check (X-008): R-3b-2b is split. **R-3b-2b-1** (this cycle, no physics
change): `runtime.provision` registers one App agent per spec over HTTP, with a registrar key the
caller holds (physics decides whether that key may register). The App agent's name is the spec's
name, and `charter_ref` is `spec:<id>`. The wake and the conductor refuse a key whose `/me` name is
not the spec's. **R-3b-2c**: `fund-runtime backtest` + the `minds:` label in physics' run record
(physics → red-team).
Step 0: `?? setup/` is the Human's P-0003 installer (STATE says so). It was left untouched.
Decision (prime rule, tie-breaker "safer seal"): the `runtime` identity does **not** gain
`REGISTER_AGENTS`. The clock key stays the narrowest key in the world. The registrar is a key
the operator hands in. Today that is the seed admin. In Era II it may be a workflow's.
Hypothesis: If `provision(specs, registrar, connect)` (a) checks every spec before it registers
any (unique ids and names, wake gate open, `wake_policy` not `never`), (b) registers each one
through `POST /agents/register`, (c) accepts the answer only if it is the agent asked for, and
(d) raises naming what was already registered if a step fails, and if wake/conductor compare
`/me`'s name too, then: the R-3b-2a two-pod month runs with minds provisioned through HTTP, its
ledger records the registrar as the actor of every `agent_registered`, a spec whose name is
taken refuses with the earlier ones named, a key with the right role and pod but another name
cannot wake, and nothing is registered under HALT or cap refusal. Expected ~15 new tests.
Xfails stay at 6. Old tests that hand in a key under another name are findings of the new law.
Work:
- `runtime/provision.py`: `provision(specs, registrar, connect) → [Mind]`. Every spec is checked
  first, then registered, with HALT re-read before each registration. Each answer is validated,
  and a `ProvisionError` names every spec whose agent may exist.
- The wake and the conductor now compare `/me`'s name as well. 65 old runtime tests broke on
  fixtures that handed keys under other names. Their fixtures were renamed and no assertion
  changed.
- The R-3b-2a pod month now provisions through HTTP, and the registrar is the actor of every
  registration.
- The claim check (before the auditor) found that "HALT provisions nothing" held only for a HALT
  present at the start. Re-reading HALT per registration fixed it, with a counter-example test.
- Mutations: dropping the name check or the preflight fails 8 tests. Cutting the check to the
  name only fails 6.
- Auditor: **FAIL, 1 BLOCK.** My renames had made four role/pod guards mismatch on name too, so
  they would pass on the name check alone. Fixed: each guard's spec now wears its key's own name,
  and there are new right-name/wrong-role and right-name/wrong-pod tests. Re-audit **PASS**.
- Red-team 0016: 4 low holes, all fixed. A lost (5xx) answer hid an agent. A failing `connect`
  escaped raw. Lookalike names both registered. Reserved and taken names were found only after
  earlier specs were registered. Now names are folded with a pinned copy of physics' fold, and
  the directory is read through the registrar. 9 guards were added.
Result: merged ca17717, pushed. 1287+6xf → **1334 passed + 6 xfailed** (plus the known `setup/`
failure in the working tree). Smoke 12/12. Hypothesis **met**, and more: names are refused under
the fold and against the directory, not only when they are exactly equal.
Learned:
(1) **When a new check is added, every old guard whose fixture now trips it stops testing what
it was written for.** The suite stayed green while the role and pod checks lost their pins. For
each broken guard, the fix must make the *new* check pass, so that only the guard's own mismatch
remains. The claim check should ask for this whenever a law adds a conjunct.
(2) **"Nothing registered" must cover a lost answer.** Only a 4xx proves nothing happened. A
timeout after the commit is "maybe".
(3) **A preflight is only as good as what it can know.** Reading the directory turns a part-way
409 into a clean refusal. The race window that remains fails closed.
Next: R-3b-2c. `fund-runtime backtest` (specs dir + server + keys → a provisioned run) and the
`minds:` label in physics' run record (physics → red-team).

## Cycle 0027 — R-3b-2c-1: `fund-runtime backtest`, a run from a specs directory (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1 (M1: the PM + Analyst month started by one operator command, not by
a test harness). Size check (X-008): R-3b-2c is split. **R-3b-2c-1** (this cycle, no physics
change): the command. **R-3b-2c-2**: the `minds:` label in physics' run record (physics →
red-team, and a design question: physics cannot see what drives a key).
Step 0: `?? setup/` is the Human's P-0003 installer. It was left untouched.
Hypothesis: If `fund-runtime backtest --specs DIR --steps N [--days-per-step D] [--input FILE]
[--server URL]` reads the registrar and clock keys **from the environment only**
(`FUND_RUNTIME__REGISTRAR_KEY`, `FUND_RUNTIME__CLOCK_KEY`; argv is visible to `ps`), checks the
clock key and the run's mode **before provisioning** (a live database must not gain agents),
then provisions and conducts, and prints the RunRecord as JSON, then: the R-3b-2a pod lives its
days through the command against a served App; the output carries no key; a live database, a
wrong clock key, a missing key, a bad spec or input, HALT or a taken name each exit non-zero
with a reason and register nothing (or name what may exist); exit 0 means `completed`.
Expected ~12 new tests. Xfails stay at 6.
Work:
- `runtime/cli.py`: `fund-runtime backtest`. Usage errors (no specs, bad input, sizes, missing
  or identical keys, a server off this machine) exit 2 before anything is contacted. Then
  `lockstep.check_clock` (extracted from the conductor, behaviour unchanged) runs before
  `provision`, then `run_backtest`. `lockstep.record_json` turns a RunRecord into JSON.
- `specs/desk-month/`: the R-3b-2a pod (analyst + PM, pod 1) as files, with `input.json`.
- `scripts/smoke_run.py` has a second phase. It builds a synthetic backtest database with the
  real `fund-env` commands, serves it, and runs `fund-runtime backtest` on it for 5 days. Result:
  10 wakes, all `done`, and the PM's order on its analyst's signal is accepted by physics.
- Claim check: an absent server is `clock_unreadable:503`, not a crash (test added). The ADR's
  "every refusal before registration" was narrowed to the command's own refusals.
- Mutation: dropping the pre-provision clock check fails 3 tests.
- Auditor: **FAIL, 1 BLOCK.** "No key is printed" was false. A management mind's
  `register_agent` result holds the new key, and the transcript keeps it. Fixed with `redact`
  over the output, a hiring-mind test (it fails without `redact`), and a test over 200 minted
  keys. WARN 1: httpx honoured proxy env vars, so a key could leave the machine through a proxy.
  `FundClient` now sets `trust_env=False`. WARN 2: the tool budget has a maximum (1024). NOTEs:
  `localhost` and `--steps 0` are refused. Re-audit **PASS**.
- No physics change, so no red-team (the `FundClient` change is client-side).
Result: merged 6d8e08d, pushed. 1334+6xf → **1369 passed + 6 xfailed** (plus the known `setup/`
failure). Smoke 20/20 (was 12). Hypothesis **met**. The run ran against a real served App, not
only ASGI.
Learned:
(1) **"No record holds a key" is a claim about every tool's answer, not about the runtime's
own fields.** A transcript is the world's words as they came. Anything that prints or stores one
(the CLI now, the cassette at R-4) inherits the redaction duty. The ADR says so.
(2) **Loopback-only is not "the key stays here"** while the HTTP library obeys proxy variables.
A seal has to cover the transport as well as the URL.
(3) **A smoke run against real processes finds what ASGI tests cannot.** This one confirmed that
the operator commands chain together: init-db → start-backtest → seed → serve → backtest.
Next: R-3b-2c-2, the `minds:` label in physics' run record. It is a design question first:
physics cannot see what drives a key, so the label is a declaration. Decide who may declare it.
The likely answer is the runtime identity, once, before the first wake, as an event. Then
red-team. After that, R-4 cassettes, which must redact keys.

## Cycle 0028 — R-3b-2c-2: physics records what drives a run's minds (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1 (M1: physics labels the scripted PM + Analyst month, so it can never
be reported as an agent month). Serves EC1, does not tick it (R-8).
Step 0: `?? setup/` is the Human's P-0003 installer. It was left untouched.
Hypothesis: Suppose physics accepts `POST /run/minds {minds: [...]}` with these limits:
- only from the `CONTROL_CLOCK` hand (the runtime identity; no new permission);
- on backtest runs only, and only once;
- only while no firm agent has acted and the clock has not moved;
- with kinds from a closed list (`scripted`, `cassette`, `model`).

It records `run_minds_declared {minds}`. A reader, `run_minds(session)`, trusts a declaration
only if the ledger order still says it came first. Then:
- `fund-runtime backtest` declares before provisioning, and the smoke month's ledger names
  `scripted`;
- a firm agent, a second declaration, a late one, a live run and an unknown kind are each
  refused, with nothing written;
- an undeclared run reads as `None`.

Expected ~15 new tests. Xfails stay at 6.
Work:
- **Physics.** `POST /run/minds` (`app/api/clock.py`) under `CONTROL_CLOCK`, with no new
  permission. Behind it: `app.run_clock.declare_minds` / `run_minds` / `MIND_KINDS`, the event
  `run_minds_declared {minds}` and the schema `RunMindsIn`. The MCP tool is `declare_run_minds`.
- **Runtime.** `lockstep.mind_kinds` / `declare_minds`. `fund-runtime backtest` declares
  between `check_clock` and `provision`.
- **Tests.** `tests/test_run_minds.py` (32 tests). Red-team 0014's route allowlist gains the
  route: a finding of the new law, logged.
- **Smoke run.** A new step reads the declaration from the database file. The backtest market
  key is now fixed: a random key had failed the "order accepted" step on the world's luck, which
  I found because this branch's first smoke drew 0 orders while `main` drew 3.
- **Claim check.** I had written that an agent must not read the market's law. Management can
  already read it through `/events`: B-049.
- **Auditor: PASS, 0 BLOCK.** I fixed the 3 WARNs:
  - `scripted` through `openclaw` was labelled code; it is now `model`;
  - the "only by a race" wording was wrong;
  - "covers everything" claimed too much.

  I also took NOTE 3: the reader takes only a physics-written declaration.
- **Red-team 0017: 4 holes, all fixed.**
  - H1/H2 (medium/low): a lost race got 201. It now gets a 409 after a re-read of the ledger.
  - H4 (medium): an agent older than the declaration acted under its label. A declaration now
    covers only the agents registered after it.
  - H3 (low, every route): a lone surrogate made the 422 handler return a 500.

  The H4 fix contradicted one of the red-team's own HELD guards (it acted through pm-1). I
  rewrote that guard to act through an agent registered after the declaration, and logged why.
- **Re-audit: PASS.** I applied 2 NOTEs: no NULL inside `NOT IN`, and the H4 guard asserts
  `None` exactly.

Result: merged 2cd2cb2 and pushed. Tests went from 1369+6xf to **1433 passed + 6 xfailed**
(plus the known `setup/` failure). Smoke 21/21, twice. Hypothesis **met**, plus one rule I had
not foreseen (H4). **M1 is closed for scripted minds:** physics labels the desk month `scripted`.
Learned:
(1) **A label that names kinds must also say whom it covers.** "Declared before anything
happened" sounded complete. But an agent that existed before the declaration and acted after it
was never declared at all. Physics *can* see which agents came after a declaration, so the
reader checks.
(2) **An answer that the ledger will later contradict is a lie told in advance.** The lock could
not cover lock-free writes, so I made the reader trust the ledger's order. The endpoint still
said 201. Re-reading the ledger after the commit made the answer agree with the reader.
(3) **A smoke check that depends on a random world is a coin flip.** It hid behind 20 green runs
until a branch drew the wrong world. Deterministic over random applies to the checks as well as
to the physics.
Next: R-4 cassettes + replay (M2). A cassette must redact minted keys (B-047), and a replay run
declares `cassette`. Cheap items first if they fit: B-049 (the market's law visible through
`/events`), B-048.

## Cycle 0029 — B-049: the market's law is withheld from every agent's read of the ledger (2026-10-12)
Era: I — The Desk
Exit criterion served: EC1/EC7 (a month or a live run measured by real minds is honest only if
no participant holds the world's generating law). B-049 is marked "before any LLM management
mind wakes"; R-4 follows.
Step 0: `?? setup/` is the Human's P-0003 installer. It was left untouched.
Hypothesis: Suppose one physics rule, in one place (`EventOut`, the only shape in which an agent
reads an event), replaces the operator's facts about the experiment with `"withheld"`:
`run_started.world` (law, drift, volatility, symbols, fingerprint) and
`run_minds_declared.minds`. Then management's `GET /events` (every filter, and `list_events` over
MCP) carries no drift, volatility or fingerprint, while the ledger, `install_run_clock` and
`run_minds()` read the full record unchanged. Two old guards that assert management reads the
fingerprint (red-team 0011, `test_run_world`) become findings of the new law. Expected ~10 new
tests; xfails stay at 6.
Work:
- **Physics.** `app.ledger.events.AGENT_WITHHELD_FIELDS` + `agent_payload` (a new dict, never
  a mutation). `EventOut` applies it in an after-validator, so every route that returns an event
  (today only `/events`, and `list_events` over MCP through it) withholds. ADR-034.
- **Tests.** `tests/test_world_withheld.py` (10): every filter, MCP, every symbol / price /
  origin, the row unchanged after reads and a later commit, the world check and `run_minds`
  still reading the full record, `EventOut` the only payload shape. Two old guards that asserted
  management reads the fingerprint now assert it is withheld (findings, logged in ADR-034).
- My first test was wrong: it checked `run_minds()` after the PM (registered before the
  declaration) wrote a message, and red-team 0017's H4 rule rightly voided the label.
- **Claim check:** "no law reaches a firm agent" narrowed to "through the ledger" (bars still
  reveal what estimation can find; that is the agent's work).
- **Auditor: PASS, 0 BLOCK, 6 NOTEs.** Fixed 1–4: `s.dirty` proves nothing on a plain JSON
  column (the row's value is the guard); `start`/`look_ahead_guard` checked over HTTP; every
  symbol, price and origin checked; the ADR names what is tested. NOTE 5 → B-052. No red-team:
  the diff touches no registry, OMS, market data, metering or halt code.
Result: merged d908dbe and pushed. **1443 passed + 6 xfailed** (+ the known `setup/` failure).
Smoke 21/21. Hypothesis **met**: 10 new tests, 2 findings of the new law, xfails unchanged.
Learned:
(1) **A redaction has one home or it has holes.** Putting it in the response shape, not the
route, means a future route that returns an event cannot forget it, and a test pins that no
other shape carries a payload.
(2) **A dirty-set check is not a mutation check.** SQLAlchemy does not track in-place edits of a
plain JSON column, so `obj not in session.dirty` would pass over exactly the bug it names. Only
reading the value back proves the row is whole.
(3) **My own earlier law caught my test.** H4 (cycle 28) made "an older agent acted" void the
label; the new test tripped it. Laws written last cycle are already doing work.
Next: R-4a — the RunRecord and every exchange to a cassette (gitignore first, B-000i; redact
minted keys, B-047). Cycle 30 is a retrospective (re-read the Constitution and Genesis).

## Cycle 0030 — Retrospective + R-5a: three Era I gates proven end to end (2026-10-12)
Era: I — The Desk
Exit criterion served: EC3 (look-ahead refused), EC5 (HALT mid-run stops within one tick), EC6
(`cap: null` → the Runtime refuses to wake spending minds).
Step 0: tree clean, no unmerged cycle branch, no HALT. `setup/` is gone (the Human ran it).
Plan (architect, Gate 2):
UNIT: R-5a — end-to-end tests that show three gates that already exist (look-ahead, HALT
mid-run, null cap) holding through the published tool layer, then tick EC3, EC5, EC6.
SLICE: tests, ticks and one ADR (ADR-036) only; no change under `app/`, `runtime/` or
`mcp_server/`. B-053 (the backtest CLI provisions and declares `/run/minds` before any wake gate
refuses) is deferred to its own cycle with a red-team. R-4a moves to cycle 31.
Why R-5a over R-4a: after 30 cycles the exit criteria are at 0 of 7. R-5a can honestly tick
three of them, while R-4a ticks none (EC2 needs R-4b and real minds). This was my retrospective
fact; the architect decided.
Hypothesis: The gates already hold through the tool layer. Then about 8 new tests pass with no
production change:
- a scripted mind's `get_ohlcv` for tomorrow is a tool error (400), and a window across now
  holds no bar that has not ended;
- its `advance_clock` is a 403;
- HALT written during a tool call lets no further call, wake, advance or event happen;
- a spending mind under a null cap (and under a numeric cap, until metering) is never even
  built.
If any of these tests fails, that is a finding: I record it and leave that EC unticked. I do not
patch code to make it pass.

### Retrospective — cycles 21–30 (06_LOOP §6; re-read 00 + 01 this cycle)
- **Pointed at the Era's question?** Yes in direction, too slow in pace. The cycle-20
  retrospective moved the frontier to the Runtime. Cycles 21–29 built R-1, R-2 and R-3, plus
  B-049. **M1 is closed** (scripted): a pod is provisioned from specs, conducted for a month by
  one command, and labelled in the ledger. But R-3 alone took **7 cycles** of slices
  (3a, 3b-1, 3b-2a, 3b-2b-1, 3b-2c-1, 3b-2c-2, plus B-049), and the exit criteria stayed at
  **0 of 7** for 30 cycles.
  **Drift named: tick-blindness.** I followed the R-order of the plan, and nobody asked which
  criteria were already within reach. Three test criteria (EC3, EC5, EC6) rest on gates built in
  cycles 16, 21 and 22, yet they were never proven end to end, and never ticked. This cycle fixes
  that.
- **Failures:** 9/9 merged (21–29), 0 failed, 0 blocked. Two sessions were interrupted (22, 24),
  and both resumed cleanly (X-007, X-009). **Auditor BLOCK rate rose: 2/9 → 4/9** (c21, c22,
  c26, c27). Each BLOCK was in new code at a boundary nobody had attacked yet:
  - a parse error or ordering mistake in the reader;
  - HALT per call;
  - renamed fixtures that unpinned guards;
  - a minted key printed by the CLI.

  X-006 (the claim check) catches wide sentences, not missing guards. Red-team found holes in
  **every** run (10, 8, 1, 4, 4, 4; none high after R-1's "scripted + openclaw woke under
  null"). The red-team remains the highest-yield step.
- **What became boring:** hardening slices of the Runtime's *operator* surface (provisioning,
  the CLI, labels). Recent holes are low and operator-only (0016: 4 low; B-050, B-051, B-052 are
  all "low"). Lesson: operator-surface hardening has hit diminishing returns. Physics stays
  first, but the frontier is **M2 (cassettes + exact replay)**, the instrument the vision's
  counterfactual fork rests on, and then the money gate (Q-0001).
- **Scales:** S0 (the Human) answered process questions again: P-0003, then the bounded loop and
  the Builder team (ADR-035). Money and keys are still unanswered (Q-0001, Q-0002, Q-0005), so the
  world must reach M5 without a budget. S1 now works as a team, with an architect at Gate 2;
  this cycle is the first with that gate. **Cost is now a variable for S1 too.** A cycle has an
  $8 ceiling, and an opus red-team pass costs a large part of it. That favours slices whose
  physics surface is either zero (tests and docs) or large enough to justify a red-team.
- **Process change (Era ∞, X-011):** at step 2, the architect brief must list the **unticked
  exit criteria and, for each one, whether existing code might already meet it**. Hypothesis:
  this stops tick-blindness. Metric: exit criteria ticked per 10 cycles (c1–30: 0; target ≥ 4 by
  c40).

Work:
- **Tests.** 8 end-to-end tests in `tests/test_runtime_lockstep.py`, section "Era I exit
  criteria". Every act is made by a conducted scripted mind through the MCP tools, over HTTP:
  - EC3 ×3: tomorrow's window gives a 400 `no look-ahead`; a window across now is clipped to
    ended bars; `advance_clock` gives a 403 and every advance is the runtime's.
  - EC5 ×2: HALT as a call returns means no further call, no later wake, no advance and no new
    event (max event id unchanged).
  - EC6 ×3: a spending mind is never built under a null cap or under a numeric cap; zero-cost
    minds still wake (the control).
- **No production change.** ADR-036 says what each criterion means when tested. In
  `05_ERAS.md`, EC3, EC5 and EC6 are ticked with their tests. EC6 is conditional on Q-0005 B.
  New B-053. The R-4a seed is in the backlog. X-011 is in `protocol/CYCLE.md` step 2.
- **Deviations from the plan:**
  - EC6 spies on `native.build_provider`, not `PROVIDER_CLASSES`: `build_provider` never
    reaches that table for a non-zero-cost name, so a spy there would be vacuous.
  - EC5's second test became "HALT on the last call of a step".
- **My first EC5 assertion was wrong:** I assumed `tool_calls` was cumulative, but it counts per
  wake. I fixed the assertion; this was not a finding.
- **Claim check:** I planted a mutation (no per-call HALT read) and EC5 went red; then I reverted
  it.
- **Auditor: PASS, 0 BLOCK, 6 NOTEs.**
  - NOTEs 1–3 and 5 fixed: an explicit step count in the zip, the HALT timing named, the module
    claims, X-011 written into the protocol.
  - NOTE 4: EC6's dependence on Q-0005 is kept visible in STATE.
  - NOTE 6 agreed with the scope.
- No re-audit (no BLOCK). No red-team: no physics or gate code changed.
Result: merged 6e04725 and pushed. **1452 passed + 6 xfailed** (+9). Smoke 21/21. Hypothesis
**met**: every gate held, and no finding was needed. **Era I exit criteria: 0/7 → 3/7.**
Learned:
(1) **A gate built is not a criterion ticked.** The three gates held the first time they were
driven as a run drives them. The work had been done for 8–14 cycles; what was missing was the
question "is this criterion already met?". Hence X-011.
(2) **A spy must sit where the code actually goes.** The architect's spy on `PROVIDER_CLASSES`
would have passed while proving nothing, because `build_provider` never reads it for a spending
name. Check the path before you trust a spy.
(3) **"Refuses to wake agents" hides a question for the Human.** Read literally, EC6 is false
today (scripted minds wake under null). The tick is honest only because Q-0005 B is written
down and the box says what would re-open it.
Next: R-4a (cassette writer, gitignore B-000i, B-047 redaction; seed in the backlog), then B-053
(pre-gate before provisioning, with red-team).

## Cycle 0031 — R-4a: every run writes a cassette (2026-10-12)
Era: I — The Desk
Exit criterion served: EC2 (replay at $0), through M2. This slice ticks nothing.
X-011 check (architect): EC1 not met (ticked only by real minds, R-8); EC2 no cassette code;
EC4 not met (`POST /costs` is a self-report; a scripted run is $0 vacuously; waits for R-6);
EC7 no adapter yet.
Plan: UNIT: R-4a. Each run writes one cassette file holding its record and every model exchange:
a per-request hash plus usage, with minted keys redacted. Backlog: R-4a, B-000i, B-047.
SLICE: Record only. Deferred: R-4b (cassette provider, replay, divergence, `minds: replay`),
event links to hashes (physics, own red-team), smoke step, `tools_sha256`.
RED-TEAM: no (nothing under `app/`, no halt/budget order change; auditor must attack secret
handling, overwrite and symlinks).
Hypothesis: a run's whole exchange with its minds can be written to a deterministic, redacted,
exclusive 0600 file, with each request hashed before the mind sees it, without changing any HALT order. Metric: two identical runs that mint no key give byte-identical
cassettes (with a minted key the unredacted hashes differ by design); no minted key in file or
stdout. (Audit c31 BLOCK 1: the printed JSON does gain `exchanges`; I first wrote "unchanged".)
Work:
- `runtime/cassette.py` (new, stdlib only): `request_sha256`, `HASH_FORMAT`, `CASSETTE_VERSION`,
  `redact_count`/`redact` (moved from the CLI), `dumps`, `check_path`, `write` (O_EXCL,
  O_NOFOLLOW, 0600, no partial file).
- `native.wake`: `Exchange(seq, request_sha256, usage|None)` per model turn, hash taken before
  `complete`; `WakeRecord.exchanges`. HALT order untouched.
- `fund-runtime backtest --cassette PATH` (checked in the usage phase, written for every outcome).
- `.gitignore` (B-000i). ADR-037. 33 new tests (1452 → 1485), smoke 21/21.
- **Deviation:** the hash lives in `cassette.py`, not `providers.py` (plan): an old test pins
  `providers.py` to pydantic + typing and went red on `hashlib`. The law stayed, the code moved.
- X-011 check: the architect verified EC1/EC2/EC4/EC7 as not met; none ticked.
- Mutation check: moving the digest after `complete` turned two tests red.
Result: merged fba3b1c and pushed. Hypothesis **met**. Auditor: **BLOCK ×2, both wrong claims**
("printed JSON unchanged" — it gains `exchanges`; "equal runs give equal bytes" — not with a
minted key, because the hash is of the unredacted request). Both fixed in text, plus NOTEs 4–6
(an interrupt leaves no partial file; symlink claim narrowed in the test docstring; "every
invocation that passed the usage checks"). Not re-audited: the fixes were wording and one
`except BaseException`; the suite was green before and after.
Learned: (1) I wrote two sentences about surfaces without testing them: the claim check (X-006)
needs "what else prints this?" for any new field on a record that is dumped whole. (2) An old
import-pin test shaped the design again, the way law-first should work. (3) The unredacted-hash
decision (B-047) has a cost: cassettes of runs that mint keys are not byte-reproducible. R-4b
treats that as a divergence by design; revisit if hiring runs must replay.
Next: R-4b (cassette provider, replay, `minds: replay`, duplicate-key-rejecting reader, red-team
planned), then B-053.

## Cycle 0032 — R-4b-1 a replay drives the minds from a cassette (2026-10-13)
Era: I — The Desk
Exit criterion served: EC2 (replay at $0), test half, through M2. Ticks nothing (ADR-032 leaves EC2 to R-8).
X-011 check (architect): EC1 not met (real minds, R-8); EC2 no cassette reader existed; EC4 not met (no provisioner or system-reported cost anywhere); EC7 not met (`runtime/openclaw/` holds only VERSION_NOTES).
Plan: UNIT: R-4b-1. A replay drives every mind from a recorded cassette at $0. The first divergence ends the run and names where and why. In-process through `run_backtest`; the recorded scripted month replays into a fresh DB in the same world, event for event.
SLICE: reader (`cassette.read`), `runtime/replay.py` (Recording, Tape, CassetteProvider, divergence kinds), registry entry + `check_spec`, `wake(tape=)`, `run_backtest(replay=)`. Deferred to R-4b-2: `fund-runtime replay` CLI, cassette v2 (run params, spec digest, wake model), smoke step.
RED-TEAM: yes (registry is the second half of the cap gate; the cassette file is untrusted input).
Hypothesis: a cassette of a completed scripted month, replayed in the same world at $0, leaves the same ledger and transcripts; in another world it ends `diverged` with a position and kind, and the clock never moves after it. Metric: ledger tuples equal event for event; zero usage; divergence kind correct for world / surface / key.
Work:
- `cassette.read` (canonical-v1 reader; shares `_assemble` with `dumps`), `runtime/replay.py` (Recording, Tape, Turn, CassetteProvider, divergence kinds), `registry.check_spec` + `build_provider(spec, tape)`, `native.wake(tape=)`, `run_backtest(replay=)` with run end `diverged`. ADR-038 + amendment (a). Q-0006 (label `cassette`, not `replay`).
- Tests: 42 in `tests/test_cassette_replay.py`, 26 in `tests/test_redteam_0018.py` (8 were failing holes). 1485 -> 1555 passed + 6 xfailed, smoke 21/21.
- Own find while claim-checking: the first conductor skipped the divergence check for every refusal, so a mind retired in the replay let the run finish `completed`. Pinned by a test and a mutation (red without the fix).
- Deviations from the plan: `missing_wake` dropped (ids and steps are checked equal up front; the auditor agreed); refusal-is-divergence added.
- Environment notes: the guard hook blocks any shell command containing the word for the protected directory (even in a test path or a grep), and the shell rejects heredocs with braces next to quotes; I wrote scripts with the Write tool instead.
Result: see the state commit. Auditor round 1: PASS, 0 BLOCK, 1 WARN (a FIFO hangs the reader: fixed) + 8 NOTEs. Red-team 0018: 6 holes (replay calendar never compared; a replay ran a batch the recording never ran; a Tape was not validated as data; a forged refused wake retired a mind quietly; seq type), all fixed, red-team file committed before the fixes (X-010).
Scoped re-audit: BLOCK 1 (my own fix made the H2 test pass for the wrong reason; isolated with `_uncalendared`, mutation red without the clamp), WARN 1 (negative `tool_calls`), NOTEs 1/3 (calendar validated, two reasons `calendar_at`/`calendar_landed`): all fixed; merged a1f72a2 without a third audit (the fix diff was a test, two validations and a reason string).
Learned: (1) Red-team earned its place again: 3 of 6 holes were things my claim check could not see because they were absent fields, not wrong sentences (what the cassette does NOT compare). New claim-check question for X-006: "what does the recording hold that the replay never compares?" (2) Fixing a hole can make an older test vacuous (three held tests started ending on the calendar check, not on what they claimed): isolate the claim, say so in the test. (3) A shell hook and a parser that reject harmless commands cost about 10 turns this cycle.
Next: R-4b-2 (`fund-runtime replay` CLI, cassette v2 recording run parameters/spec digest/model, a cassette step in the smoke run), then B-053 and R-6.

## Human intervention — 2026-10-13 (between cycles 32 and 33): loop repair
- **What happened to cycle 33.** The run's 4th session (lead sonnet, 9 turns, $1.01) created
  `cycle/0033-replay-cli`, got its architect plan, then hit `429 usage_limit_reached` ("session
  limit · resets 4:20am"). No journal entry, no commit, the plan was lost. `preflight --post`
  treated a limit as a limit only when the cost was 0, so it logged `result=failed` and raised the
  failure counter to 1 (the next cycle would have run on opus for no reason).
- **Runner fix** (`loop/preflight.py`, installed by the Human's `setup/update.sh`, ADR-039): the
  cut-off is read from the structured result (`api_error_status` 429/529, `api_error`), then the
  errored result's text. Such a session is logged `result=limit` with its cost: it counts toward
  the dollar caps, not as a failure, not as a daily cycle slot; the runner stops. The cycle-33
  record was corrected by an appended note in the cycle log, and the counter reset 1 → 0.
- **Protocol fix (X-012, `protocol/CYCLE.md` steps 0 and 3):** the branch is created and the
  architect's full plan committed (`state/plans/NNNN.md`) before the build. The resume rule now
  has three cases: build commits → step 5; plan only → step 4; empty branch → step 2, same number.
  **Cycle 33 is the third case: resume `cycle/0033-replay-cli` at step 2.**
- **STATE.md budget (X-013, step 8):** ≤ 120 lines, a map not a history. Compacted from 283 to 86
  lines; the old text is `git show 5bffbfa:state/STATE.md`; the ADRs and journal entries it cited hold
  the per-capability detail. If a cycle misses a fact, recover it from that commit.

## Cycle 0033 — R-4b-2a the replay CLI, the refusal law, a ledger comparison (2026-10-13)
Era: I — The Desk
Exit criterion served: EC2 (replay at $0, test half; ticks nothing, ADR-032 leaves EC2 to R-8).
X-011 check (architect): EC1 not met (real minds, R-8, Q-0001); EC2 met end to end for scripted minds after this cycle, unticked until R-8; EC4 not met (R-6); EC7 not met (R-7).
Resumed: the empty branch `cycle/0033-replay-cli` (usage-limit cut-off, X-012 case 3), fast-forwarded to main 64789e6; same number, step 2.
Plan: UNIT: `fund-runtime replay --cassette PATH --specs DIR`, the replay refusal law (audit c32 NOTE 4), a read-only ledger comparison (`fund-env compare-ledgers`), and a record-then-replay step in the smoke run (R-4b-2a). SLICE: cassette v1 only; cassette v2, NOTE 5, a size cap and `replay --cassette OUT` go to a new backlog item R-4b-2b. RED-TEAM: no (escalate if the halted branch, decide_batch, the budget clamp, check_clock, declare_minds, app/registry or app/run_clock are edited). See state/plans/0033.md.
Hypothesis: a cassette of a scripted month, replayed through the operator command into a fresh database, ends `completed` at $0, and `fund-env compare-ledgers` finds the two ledgers equal row for row (raw text) except the one `run_minds_declared` payload; a changed world, input or calendar ends `diverged` with exit 1 and an unequal ledger; a setup refusal in a replay ends `refused`, not `diverged`. Metric: exit codes, `allowed == 1`, `first_difference`.
Work:
- `fund-runtime replay` (`runtime/cli.py`; shared `_shared` checks with `backtest`; no `--steps`), the refusal law in `run_backtest` (a replay ends as a live run would; a retired mind is still `diverged`), `app/ledger/compare.py` + `fund-env compare-ledgers` (read-only, strict, one allowed difference), smoke: record a 5-day desk month on one server, replay on a fresh database, compare the two files (21 → 32 steps). ADR-040.
- Tests: `test_replay_cli.py` (22), `test_ledger_compare.py` (27), `test_cassette_replay.py` +5. 1555 → 1609 passed + 6 xfailed. Mutation: the old conductor turns the 5 refusal tests red.
- The plan's biggest risk (ledger nondeterminism outside the minds) did not materialise: raw ids, timestamps and payloads of the two real databases were equal in the smoke run. One world, one run.
- Deviations: none from the plan's design; in-memory CLI tests compare payloads re-serialised with sorted keys (smoke compares raw files).
Result: merged 016d53d, pushed. Hypothesis **met**. Auditor: BLOCK 1 (my "declares before any firm act" test filtered to events after the declaration, so it could never fail; plus a stdout key check that read an already-drained buffer), WARN 2 (a HALT between wakes ends `refused`, not `halted`: unchanged since c24, ADR claim corrected and B-054 opened; "never creates a file" is false for WAL files: claim narrowed), NOTEs fixed (NULL payload `TypeError` → difference, a passing control for the usage cases, smoke timeout, ADR "no nondeterminism" narrowed). Not re-audited: the fixes were two tests, a `TypeError` catch, docstrings and ADR text. Red-team: not run (plan: no; no escalation condition met).
One unexplained event: a full-suite run hung (pytest idle, 21 s CPU) after the audit fixes and was stopped by the harness; three later full runs finished in 50 s. Not reproduced; if it recurs, run `-v` to find the test.
Learned: (1) My BLOCK was the same shape as c32's: a test whose setup guarantees its assertion. Check for every new test: "which input makes this red?" — the mutation habit caught the refusal tests, I skipped it for the firm-act test. (2) Pre-existing behaviour I rewrote around (`refused`/`halted` label) became a false sentence in my ADR the moment I wrote "HALT is still first": a rewrite that drops an explicit mention of a case should list the case. (3) EC2 is now met end to end for scripted minds through operator commands; it stays unticked until R-8 by ADR-032.
Next: R-4b-2b (cassette v2, NOTE 5, size cap, `replay --cassette OUT`), B-053 (pre-gate), B-054 (HALT label), R-6 metering.

## Cycle 0034 — R-6a physics metering: a system-reported cost ledger (2026-10-13)
Era: I — The Desk
Exit criterion served: EC4 (every LLM dollar attributed via system-reported cost), physics half; ticks nothing (no spending path through the gate until R-6b).
X-011 check (architect): EC1 not met (real minds, R-8); EC2 met for scripted minds, ticked at R-8; EC4 not met before or after; EC7 not met (R-7).
Plan: UNIT: R-6a, the physics half of metering: `POST /metering/usage` (runtime role, new right `REPORT_METERED_COST`, cumulative µ$ per key, one key = one agent), a `cost_metered` event, metered cost overrides self-reported cost per agent in the metrics, and `runtime/metering.py` (`FakeProvisioner`, `sync_costs`). SLICE: first slice; gate/provision/conductor/replay untouched; the metered provider, per-agent keys, sync inside the run and the EC4 tick go to new backlog item R-6b. RED-TEAM: yes. See state/plans/0034.md.
Hypothesis: with the ledger as the only store, a metered agent's dollars equal the sum of the fake provider's charges to the µ$, a re-post or a retry never double-counts, a self-report can neither hide nor inflate a metered agent's cost, and a pod with no metering gets exactly the old metrics. Metric: provisioner total == firm metered total in µ$; event counts after repeated syncs; `self_report_gap_usd`; old metrics tests unchanged.
Work:
- Physics: `REPORT_METERED_COST` (runtime + system), `cost_metered` event (no table), `app/metrics/metering.py` (writer + `metered_by_agent` fold), `POST /metering/usage` + MCP `report_metered_usage`, `key_ref` withheld, `_cost_metrics` per-agent override + 4 new fields. Runtime: `runtime/metering.py` (`FakeProvisioner`, `sync_costs`). ADR-041.
- Tests: `test_metering.py` (43), `test_metering_metrics.py` (8), `test_runtime_metering.py` (11), +1 MCP, `test_redteam_0019.py` (83). 1609 → 1755 passed + 6 xfailed; smoke 32/32. Mutation (sum instead of max) turns one test red.
- Two old tests broke as the plan predicted (runtime key route sweep; runtime role permission set): each edited to add exactly the one new right/route, recorded in ADR-041.
Result: merged 240b607, pushed. Hypothesis **met**; EC4 not ticked (no spending path until R-6b). Auditor: PASS, 0 BLOCK, 3 WARN (float subtraction of two sums lost cents under spam → sum unmetered rows directly; "to the micro-dollar" overclaim → narrowed to the ledger fold; conflict/malformed counts shown nowhere → ADR + backlog) + NOTEs. Red-team 0019: 1 low hole (metered decided per pod, not over the whole fold), test committed before the fix (X-010), fixed; 82 held guards. Not re-audited: the fixes were one query, a range check and ADR text.
Learned: (1) The red-team again found an *absent-field* shape: the law was right per pod and wrong across pods; the claim check should ask "what happens when the same agent appears in a second scope?". (2) The auditor's WARN 1 and the red-team's hole were the same function — read the whole function after a fix, not just the line. (3) Shell guard: a compound command with `;`/`&&` after an `uv run` needs approval; run one command per call (cost ~6 turns).
Next: B-053 + B-054 (pre-gate, HALT label; red-team, before R-6b edits the gate), then R-6b (gate lets `metered` wake under a numeric cap, per-agent keys with limit ≤ `MAX_METERED_USD_MICROS`, sync after the last step, EC4 test + tick), R-4b-2b. Cycle 40 = retrospective.

## Cycle 0035 — blocked on budget (2026-10-13)
(No unit started: about $2.28 of the $8 session cap was left, too little for architect + auditor + red-team. Entry written in cycle 36.)

## Cycle 0036 — B-053 + B-054: vet before physics is told, HALT always reads `halted` (2026-10-13)
Era: I — The Desk
Exit criterion served: EC4 groundwork (honest run records before R-6b edits the gate); ticks nothing.
X-011 check (architect): EC1, EC2, EC4, EC7 unchanged — none met by this unit.
Plan: UNIT: Fix the run records for B-053 + B-054 together. B-053: a run whose specs could never wake must not reach physics (no `/run/minds` declaration, no agents). B-054: every way HALT can stop a run must end it `halted`, never `refused`. SLICE: whole. Deferred: B-023 (halt observability), and the known gap that a `name_taken` refusal still happens after the declaration. RED-TEAM: yes. See state/plans/0036.md.
Hypothesis: with a network-free `vet(specs, law)` run in `_conduct` before `check_clock`/`declare_minds`, a spec the gate refuses under a null cap leaves zero declarations and zero agents; HALT before the run, at the declaration (423), mid-provisioning, or between two minds' wakes ends the run `halted` with no wake after the HALT and no advance; every non-halt refusal keeps its label byte for byte. Metric: declaration/agent counts, `ended`/`reason` labels, the unchanged old refusal tests.
Deviations (as built): (1) a 423 on `POST /clock/advance` now ends the run `halted` (was `error`/`advance_failed:423`). Not in the plan; reason: the advance is the last place HALT can stop a run, and the plan's own invariant "every way HALT can stop a run ends it `halted`" is false without it. Physics' halt check (`app.registry.halt`) refuses before the handler, so the clock did not move; the step is recorded with `advanced_to=None`. `test_a_clock_that_will_not_advance_ends_the_run_in_error` → `…_ends_the_run_halted` (same invariants, new label; ADR finding). (2) `test_a_server_that_is_not_there_is_a_refusal_not_a_crash` gained the `woke` fixture: its specs named uninstalled scripts, which `vet` now refuses before the clock check runs (ADR finding).
Work:
- (Resumed at step 5: the previous session built and committed, then stopped before verify; X-007.) `runtime.provision.vet`, the pre-gate and `halted()`/`_is_halt` in `_conduct`, the between-wakes and advance-423 branches in `run_backtest`; ADR-032/040 amendment. Red-team fix: a cassette spec outside a replay is refused before the declaration.
- Tests: 1755+6xf → **1846 passed + 9 xfailed** (red-team 0020: 72 tests, 3 open strict xfails). Smoke 32/32 on the branch after the fix.
Result: merged 5eb1d6d, pushed. Hypothesis **met**: a refused spec under a null cap declares nothing and makes no agent; HALT at all five stages ends `halted` with nothing woken after it and no advance; non-halt refusals keep their labels (409 and `bad_input` counter-examples). Auditor PASS, 0 BLOCK (WARN 1: no test for `register_failed:*:423` → the red-team's held test covers it, mutation-confirmed by the re-audit; NOTEs 7/8 ADR text fixed; NOTE 1 not taken, trust assumption written). Red-team 0020: 4 holes, none breaks an invariant: cassette spec in a backtest (medium, fixed, test committed before the fix per X-010); unknown tool and missing pod pass `vet` (low → B-055); physics 500 on register into a missing pod (low → B-056). Scoped re-audit PASS.
Learned: (1) "Could never wake" has more causes than the gate: a provider that needs a tape it does not have, a tool that does not exist, a pod that does not exist. A pre-gate named after the gate checked only the gate's causes. Name the invariant ("every spec can wake"), then list its causes. (2) A deviation written only in a commit message and the ADR is not in the journal; Gate 2 wants it in the journal, written as it happens. (3) Running auditor and red-team in parallel saved a round trip; the red-team's held tests then answered the auditor's coverage WARN.
Next: B-056 (or with R-6b's red-team), R-6b, R-4b-2b. Cycle 40 = retrospective.

## Cycle 0037 — plan — re-foundation: the first mission queue (2026-10-13)
Look back: no v2 metrics yet (`$FIRM_HOME/metrics.jsonl` absent; regression: 0 done missions). Era I 3/7
(EC3, EC5, EC6); no criterion newly met by code (X-011: EC4 needs R-6b, EC7 has no adapter, EC1/EC2 need
real minds).
World: scripted pods live and replay a month; physics is honest about time, money and halt. What became
boring: one more seal slice. Frontier: a spending mind (metered), a run as a one-file proof, minds as real
OpenClaw agents, and the world's first scripted event (a shock), which turns the firm's risk law into
something the world can test.
Outward: 3 searches (sources in IDEAS c37). Forking sims exist (WhatIf, Inject/Fork/Compare). Causal Agent
Replay lacks common random numbers; cassette-replayed prefixes are exactly that. Vision §3 narrowed.
Decided: 6 ready missions M-001…M-006 (ADR-043); Era II starts while EC1/EC2/EC7-live wait on Q-0001;
fork + correlated-minds experiment parked; AlphaForge-style "minds write code" rejected. No process change:
no baseline to judge it against (ADR-043 §5). Result: planned.
Next: build → M-001 (architect, acceptance red first).

## Human intervention — 2026-10-15 (during M-001)
- Q-0002 answered: the Human created an OpenRouter **provisioning** key. It lives only in the
  gitignored repo-root `.env` (mode 600) as `FUND_OPENROUTER_PROVISIONING_KEY`. Never print it,
  never commit it, never copy it into a tracked file. No code reads it yet.
- With Q-0001 answered (cap $50/month) the key is usable in principle. A real `metered` provider
  still needs its own ADR (M-001 plan §"Which name"); per-key limits sum to ≤ the cap.
- B-022 (secret-scan test) now matters: a real key exists on this machine.

## Cycle 0038 — build — M-001 metered pod month (2026-10-15)
Architect planned (verdict: ready, 3 sessions; done in 1). Acceptance written red first (Part B passes as
the control; C and A failed with `no_metered_key`). Built in three milestones: gate + `fake-metered`
provider + meter; keys under the budget/cap law + one sync + exit codes; `GET /metering/agents`.
Validator PASS; red-team found 5 holes — fixed the high (a cap lowered mid-step bound only the next step:
now checked before every wake) and the low (sync in a `finally`); 2 mediums + 1 low are written in
ADR-044 and routed to M-004. Auditor BLOCKED twice, both fair: no determinism test (added), "never" claims
that are only true after the sync (narrowed), and a test I changed to pin the Human's cap before they
committed it (reverted: the referee runs the committed law). Result: merged.
Learned: (1) the run's bill grows with the tool list — adding one MCP tool moved a $5.15 month to $5.20 —
so acceptance asserts relations. (2) `git add -A` swept the Human's uncommitted law edit into my commit
mid-session; caught by a red test, un-committed with a soft reset before any push. Stage by path.
(3) The Human answered Q-0001 ($50/month) and Q-0002 during the session; `governance/human.yaml` stays
uncommitted for them. Next: M-002 (one-file proof object).

## Cycle 0040 — build — M-002 (2026-10-16)
Gate 2 done: architect plan saved (3 sessions; hosted-world recipe, v1 refused, `replay --verify`). Acceptance written red-first (Part A fails: no `--world`). Lesson: a background architect is killed when the turn ends; run it in the foreground. Next: M1 cassette v2.

- cycle 0041 (2026-10-16) rework: Builder v3 (ADR-046). Goals now come from bible/IDEAS_BOOK.md; light, risk-tiered process; Opus leads; the Console shows what is being built and takes comments. Next: real AI agents live a backtest month.
- cycle 0043 (2026-10-16) build: red-team found 9 holes in the real-model month (3 broke the cap); all fixed, auditor passed, merged — real AI agents now live a backtest month.
- cycle 0044 (2026-10-16) plan: book made true after the real-agents month; "the pitch and the gates" cut in three, first piece ready (a real PM pitches a rule-based strategy, the gates judge it on held-out data, proven on a planted signal and on noise); demos that judge must show a yes and a no.
- cycle 0046 (2026-10-16) build: the pitch and the gates merged — red-team found 4 holes (a tiny-leverage crash and leverage-bought capacity fixed, offline search and the IC count written down), auditor's one BLOCK (pod-less reader) fixed.
- cycle 0047 (2026-10-19) plan: the capital machine moves ahead of the debate (a passing pitch must lead to capital, earned on forward days, which also cures the readable held-out window); first slice queued: capital follows results, the drawdown ladder cuts what bleeds.
- cycle 0048 (2026-10-19) build: capital follows results merged — red-team found 8 holes (5 medium, 3 low), all fixed; the auditor blocked twice on copies earning a second seed, cured by a correlation check as each seed is paid; third pass clean.
- cycle 0049 (2026-10-19) plan: book made true after the capital machine; 1b queued: a dead pod is replaced by a newly hired real PM who gets the post-mortem, pitches and can earn a seed; factory: after an auditor BLOCK, test the outcome across every path.
- cycle 0051 (2026-10-20) build: a dead pod is replaced merged — the first real hire showed a refused seed was invisible to the PM (fixed: pitches carry the capital answer); re-recorded, the PM went long-only, was seeded and trades; auditor blocked once on a forgeable hire label, fixed, then PASS.
- cycle 0052 (2026-10-20) plan: book made true after the hire (cycle 51); 1c queued: four real PMs live a quarter in the machine, pods die and are replaced, a quarter report for the Human; factory: before a paid real run, check a mind can see every consequence of its acts.
- cycle 0053 (2026-10-20) build: the firm lives a quarter, session 1 — scripted quarter (raise, no seed for noise, two deaths replaced by hires, thinking cost turns a rank, report) and a hosted rehearsal replaying IDENTICAL; PMs now told of later pitches and the hiring law, behind a law switch so old recordings still replay; next: the real recorded quarter.
- cycle 0055 (2026-10-20) build: the firm lives a quarter merged — recovered the cut-off session's real recording (auditor had passed on round 2), demo and suite green, merged; four real PMs: edge raised to $2.9M, noise never funded, sink and crash closed and replaced by hires who earned seeds, $0.67 of thinking.
- cycle 0056 (2026-10-20) plan: fixed a red main (a test read the local database, failing only in a clean checkout; the suite now runs on a scratch database); the monthly generation moves ahead of the debate; first slice queued: at each month's end the firm lets go the PMs who failed, keeps their lessons in a library and hires into the freed places.
- cycle 0058 (2026-10-20) build: a generation turns over, session 3 — real Haiku PMs lived three generations ($0.575): the PM who pitched noise eight times was let go at September's end, the crash's PM at its close, both places hired and seeded; every check of the law passes, replay IDENTICAL; red-team's high and two mediums fixed; not merged: one key spent $0.000068 past its $0.20 limit, so next a key's limit is made hard and the run re-recorded.
- cycle 0059 (2026-10-21) build: a generation turns over merged — a key's limit made hard (no turn sent whose worst case could cross what it has left; red-team's two mediums fixed, one low filed; auditor PASS); real PMs re-recorded with 24 tool calls a wake ($0.506): the noise PM let go at September's end, the crash's PM at its close, both hires seeded and kept, hire-1 stopped by the guard at $0.195 of $0.20.
- cycle 0060 (2026-10-21) plan: the book made true after the generation turnover; next queued: designs reproduce (a freed place is filled by a child of the month's fittest pod, one change from its parent, the firm's diversity watched); process: a real run's settings are checked by a rehearsal of the very command before any spend.
- cycle 0062 (2026-10-21) build: designs reproduce merged — hosted rehearsal and family tree from the ledger alone; real Haiku PMs recorded ($0.547): the noise PM's place went to a child of the edge pod (rebalance 10 -> 5 days), which took its own sector and kept a seed; red-team 5 holes (3 fixed, 2 filed), auditor PASS on round 2 (round 1: the recording missing from the suite's replay test).
- cycle 0063 (2026-10-21) plan: the book made true after designs reproduce; next queued: a PM builds its own team (asks for an analyst it describes, physics grants it inside the team limit, the cap and the pod budget, the Runtime hires it, its research and cost count as the pod's); process: a real recording checks physics' answers, never that a mind chose one thing.
- cycle 0064 (2026-10-22) build: merged "a PM builds its own team" in one session (physics, the Runtime's morning hire, rehearsal, real run, red-team 7 holes / 5 fixed, auditor PASS); real Haiku PMs offered a team chose to work alone ($0.264).
- cycle 0065 (2026-10-22) plan: the book made true after a PM builds its team; next queued: a manager chooses the hires (one real manager mind reads every pod, picks the hire for each freed place among those the law allows or leaves the default, briefs the new PM, sets the firm's direction; never moves capital or hires by itself); process: met rules lose their dated notes.
