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
