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
