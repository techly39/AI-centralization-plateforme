# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 31 (R-4a: a run writes a cassette — merged fba3b1c, 2026-10-12)

## What is true now
- **A run can leave a cassette** (R-4a, ADR-037, `tests/test_cassette.py`).
  `fund-runtime backtest --cassette PATH` writes the printed outcome to a new `*.cassette.json`
  (redacted, mode 0600, exclusive, the file never a symlink), refused runs included.
  - Every `WakeRecord` now has `exchanges: (seq, request_sha256, usage | None)`, one per model
    turn asked. The hash (`runtime.cassette.request_sha256`, `HASH_FORMAT`) is of the unredacted
    request, taken before the mind sees it. Request and response are not stored twice: they are
    the transcript prefix and the assistant message.
  - Printed JSON gained `exchanges`. Equal runs give equal bytes unless a mind was handed a
    minted key (hashes of the unredacted request then differ by design).
  - `*.cassette.json` and `experiments/*/runs/` are gitignored (B-000i closed).
  - No replay yet (R-4b), no EC ticked. **1485 passed + 6 xfailed**, smoke 21/21.
- **Era I exit criteria: 3 of 7 ticked** (cycle 30, ADR-036, `tests/test_runtime_lockstep.py`
  section "Era I exit criteria"). The gates are driven as a run drives them: a conducted mind,
  the MCP tools, HTTP, physics.
  - **EC3:** tomorrow's window gives 400; a window across now is clipped; `advance_clock` gives
    403.
  - **EC5:** HALT as a tool call returns means no further call, wake, advance or event.
  - **EC6:** a spending mind is never built under a null cap or a numeric cap.
  - **EC6 holds only under Q-0005 answer B** (spending minds). If the Human answers A, the box
    re-opens.
  - Open: EC1, EC2 (real minds, R-8), EC4 (R-6), EC7 (R-7/R-8).
  - New B-053: `fund-runtime backtest` provisions and declares before any wake gate refuses.
- **Retrospective c21–30** (journal): direction right, pace slow. R-3 took 7 slices. Drift
  named: tick-blindness. Auditor BLOCK rate is 4/9. Operator-surface hardening has hit
  diminishing returns; the frontier is M2. Process change X-011 is in step 2 of
  `protocol/CYCLE.md`.
- **No agent reads the operator's facts about the experiment** (B-049, ADR-034,
  `tests/test_world_withheld.py`). `app.ledger.events.AGENT_WITHHELD_FIELDS` names
  `run_started.world` and `run_minds_declared.minds`; `EventOut` (the only response shape with a
  payload, pinned by a test) reads them as `"withheld"` for every agent, management included.
  The ledger keeps the full record; `install_run_clock` and `run_minds()` read it. The ticker
  universe can still be probed by 200/404 (B-052, with Truman).
- **Physics records what drives a run's minds** (R-3b-2c-2, ADR-032 (p) + red-team 0017
  amendment, `tests/test_run_minds.py`, `tests/test_redteam_0017.py`). **M1 is closed for
  scripted minds.**
  - `POST /run/minds {minds}` uses the `CONTROL_CLOCK` hand; the runtime gets no new permission.
    It records `run_minds_declared`.
  - Kinds come from the closed `MIND_KINDS = {scripted, cassette, model}`.
  - Physics takes the declaration on backtest runs only, once, and only before the clock moves
    and before any firm agent writes an event (a refused act counts).
  - After its commit it re-reads the ledger. If it lost a race, the answer is 409, not 201.
  - `run_minds(session)` returns the first physics-written declaration's kinds, or `None`. It
    returns `None` if a firm act or an advance precedes the declaration. It also returns `None`
    if **an agent older than the declaration** writes anything other than a registration after
    it: a declaration covers only the agents registered after it.
  - `fund-runtime backtest` declares `lockstep.mind_kinds(specs)` before it registers anyone.
    A mind is `model` unless both its provider and its adapter are zero-cost.
  - The smoke run checks the database: one declaration, `["scripted"]`, before the first firm
    event. The smoke market key is now fixed (a hash of `fund-smoke-world/1`); a random key
    could fail the order step on luck.
  - A lone surrogate in any request body is now a 422, not a 500 (`json_safe`).
  - B-049 (found here) fixed in cycle 29: the world record is withheld from agents.
- **A run starts from one operator command** (R-3b-2c-1, ADR-032 (o) + audit amendment,
  `tests/test_runtime_cli_backtest.py`).
  `fund-runtime backtest --specs DIR --steps N [--days-per-step D] [--input FILE]
  [--max-tool-calls K] [--server URL]`:
  - Keys come from the environment only: `FUND_RUNTIME__REGISTRAR_KEY`, `FUND_RUNTIME__CLOCK_KEY`.
    The server comes from `--server` or `FUND_RUNTIME__SERVER_URL`, and must be `127.0.0.1` or
    `::1`.
  - Exit 2 for usage problems, before anything is contacted. Then `lockstep.check_clock` runs
    before any registration (a live database never gains a run's agents). Then provision, then
    conduct.
  - It prints `{ended, reason, registered, run}`. The output passes through `cli.redact` (keys
    in the form physics mints). Exit 0 only for `completed`.
  - `FundClient` uses no proxy from the environment (`trust_env=False`), the MCP server's
    client included.
  - `specs/desk-month/` is the analyst + PM pod as files. **The smoke run lives it for 5 days
    against a real `fund-env serve` on a synthetic backtest database**, and the PM's order is
    accepted (smoke 20/20).
- **Minds are made from their specs** (R-3b-2b-1, ADR-032 (n) + red-team 0016 amendment,
  `tests/test_runtime_provision.py`, `tests/test_redteam_0016.py`).
  `runtime.provision.provision(specs, registrar, connect) → [Mind]` registers one App agent per
  spec through `POST /agents/register`. Name, role and pod come from the spec, and
  `charter_ref` is `spec:<id>`.
  - **The registrar is a caller-held key** (today the seed admin). Physics decides whether it may
    register. The runtime key was **not** widened: it is still halt + clock only.
  - **Before anything is registered**, provisioning refuses:
    - duplicate ids;
    - names equal under physics' fold (`provision.name_key`, a copy pinned by a test);
    - reserved names;
    - a closed wake gate (one law read), `wake_policy: never`, or an unbuildable mind;
    - names already in the directory (`GET /agents` through the registrar). A registrar that
      cannot read the directory is refused.
  - HALT is re-read before each registration.
  - **On failure**, `ProvisionError(reason, registered)` names every spec whose agent may exist
    (a 5xx, a non-API error or a failing `connect` name the failing spec too), and closes their
    clients.
  - **The name is bound:** `native.wake` and `run_backtest` compare `/me`'s name, role and pod
    (`identity_mismatch`). Each conjunct has its own guard.
  - The R-3b-2a two-pod month now runs with provisioned minds, and the registrar is the actor of
    every registration.
- **A pod of two scripted minds lives a month through the conductor** (R-3b-2a, ADR-032 (l),
  `tests/test_runtime_pod.py`).
  - `ma-signal-analyst` sends its pod `{"kind": "signal", "as_of", "signals": {t: long|flat}}`.
  - `signal-pm` trades only on the newest of its 50 newest visible messages that meets all of
    these: addressed to `pod:<own>`; from an *active* analyst of its pod (checked against the
    directory); physics' `ts` == the clock's now; payload `as_of` == now. Otherwise it holds.
  - Two pods, 31 days: every pod-1 order cites a same-instant signal from its analyst, pod 2
    (no analyst) never trades, and two runs are identical. It runs in seconds.
- **A list stays a list on the MCP surface** (ADR-032 (k)). Every list answer is one JSON array
  block. Before, a list of one reached an agent as the bare object, and an empty list as nothing.
- **The records say more** (ADR-032 (m)):
  - `WakeRecord.tool_failures` counts bugs under a tool, told apart from refusals and bad
    arguments by the `ToolError`'s `__cause__`.
  - `RunRecord.retired_at` gives the step at which each mind was retired.
  - If every mind is retired, time still moves.
  - A `no_identity` refusal while the key is still live ends the run.
- **The Runtime conducts a backtest** (R-3b-1, ADR-032 (j) + its red-team amendment,
  `tests/test_runtime_lockstep.py`, `tests/test_redteam_0015.py`).
  `runtime.lockstep.run_backtest(minds, clock, steps=, days_per_step=1, workflow_input=,
  max_tool_calls=)` → `RunRecord(ended ∈ completed|halted|refused|error, reason, minds, steps,
  retired)`.
  - **Before step 0** it checks:
    - the clock key's `/me` is `runtime`;
    - `/clock` is `backtest`;
    - spec ids are unique;
    - every mind's `/me` matches its spec's role and pod, with an int id that does not repeat
      (one App agent = one mind);
    - `steps` and `days` are exact ints in range.
  - **Each step:** HALT is read, every mind wakes once in spec-id order, HALT is read again, then
    the runtime key advances the clock.
  - **A refused wake ends the run**, with no advance. The exception is a mind whose key now gets
    401: it was deactivated *inside the world*, so it is **retired** (never woken again) and the
    run goes on. Firing a peer cannot freeze the world's time.
  - **A failed advance** re-reads `/clock` and records the now that physics reports. If physics
    cannot say, the reason ends `:clock_unknown`.
  - The input is deep-copied once. The R-2 month test drives the conductor.
- **The clock key can be replaced** (B-041, ADR-033 (b)). `fund-env rotate-runtime-key` records
  `agent_key_rotated` (the id only). The server and every DB-clock operator command refuse a
  database where a non-physics agent holds a reserved name, or where there is more than one
  runtime row.
- **The world's clock has one hand, and it is not a firm agent's** (R-3a, ADR-033 + amendment
  (a), `tests/test_runtime_identity.py`, `tests/test_redteam_0014.py`).
  - Role `runtime` = `READ_HALT`, `READ_CLOCK`, `CONTROL_CLOCK`, nothing else. `management` lost
    `CONTROL_CLOCK` (403 + `permission_denied`), a logged TRD §6 deviation.
  - `PHYSICS_ROLES = {system, runtime}`: never registered (422 / `ReservedIdentityError`). A firm
    agent cannot deactivate them (403, `reason: reserved_identity`).
  - `fund-env seed-runtime` creates the one runtime identity per database, and the key is shown
    once. No rotation yet (B-041, before R-3b gives the Runtime the key).
  - `system` is found by role. The names `system` and `runtime` are reserved after NFKC,
    casefold and dropping everything that draws nothing (Cc Cf Cn Co Cs Mn Me plus blank
    letters). Cross-script lookalikes are not folded, on purpose.
  - Tests advance the clock with a `runtime_key` fixture. No migration (non-native enum).
- **A scripted mind wakes through the Runtime** (R-2, ADR-032 amendment (g)(h)(i),
  `tests/test_runtime_native.py`, `tests/test_redteam_0013.py`). `runtime.native.wake(spec,
  client, workflow_input=, max_tool_calls=64)` → `WakeRecord(ended ∈ done|halted|tool_budget|
  refused|error, reason, tool_calls, transcript)`.
  - The mind is built from the spec by `runtime.registry` (`scripted` → `ScriptedProvider`;
    `cassette` → `unavailable` until R-4). A zero-cost spec with a `model` or `budget_usd` is
    refused (`contradiction`). `script` names a policy in the closed `runtime.scripted.SCRIPTS`.
  - Tools = `build_server`'s list narrowed by `spec.tools`. The context is the charter + `{me,
    input}`. `/me`'s role and pod must equal the spec's (`identity_mismatch`). HALT is read
    before every model turn and every tool call. The mind gets deep copies. A reply is recorded
    only if it is plain JSON with fresh call ids, else `error/bad_reply`. `wake_policy: never`
    and non-JSON input are refused.
  - `moving-average-pm` trades a 31-day synthetic month through MCP tools. Twice in the same
    world, it gives the same ledger and the same transcripts, with 31 advances by the runtime
    key, still driven by the test (R-3b moves the loop into the Runtime).
  - MCP path values are escaped (`mcp_server.tools._segment`, B-000h closed).
  - Importing runtime loads `{app, app.limits}`.
- **The Runtime's gates** (R-1, ADR-032 amendment (a)–(f),
  `tests/test_runtime_gates.py`, `tests/test_redteam_0012.py`).
  - `runtime.governance` reads HALT first, then the cap, fresh, from fixed paths. HALT counts if
    anything is at the path, if the path cannot be checked, or if `governance/` is missing. Every
    unreadable cap is `null` + `cap_problem`.
  - `runtime.gate.decide_wake(provider, adapter)`: zero-cost = `{scripted, cassette}` ×
    `{native}`, exact `str`. A numeric cap still refuses spending (`no_metered_key`) until R-6.
    `decide_batch()` checks HALT.
  - `runtime.spec.AgentSpec` has the 03 §3 fields + `provider`. Specs are YAML, in id order.
  - `runtime.providers.LLMProvider` is the protocol.
  - `uv run fund-runtime status [--specs DIR]` prints the law and what would wake.

  Boundary law: runtime imports no `app` module, and importing it loads at most
  `{app, app.config, app.limits}` (dynamic probe, planted counter-example). The scanner refuses
  imports it cannot read, in every layer.
- **The frontier is the Runtime** (cycle-20 retrospective). `bible/09_BUILDER_VISION.md` exists:
  a run is a proof object (physics + world + minds' cassettes), and the target instrument is the
  exact counterfactual fork. ADR-032 fixes the Runtime's shape. BACKLOG "Runtime" R-1…R-8 serve
  all 7 Era I exit criteria; M1–M5 need no money, R-8 needs the cap (Q-0001). Cap gate: fails
  closed, and only `{scripted, cassette}` run under null (Q-0005, chosen B, awaiting the Human).
  Run criteria (EC1, EC2, EC7 live) are ticked only by real minds; test criteria (EC3–EC6) may be
  met by tests. Physics work only when a Runtime slice needs it or an agent can reach it.
- **Process** (`protocol/CYCLE.md`, cycle 20): step 2 size check (X-008); step 5 smoke run
  (X-004) + claim check (X-006). Auditor BLOCK rate 5/10 (c1–10) → 2/9 (c11–19).
- **A run records its world and lives in only one** (ADR-031 + amendment,
  `tests/test_run_world.py`, `tests/test_redteam_0011.py`): every provider has `world()`;
  `run_started.world` carries it (synthetic: law `hmac-sha256-gbm/1`, origin, drift, volatility,
  symbols, `key_fingerprint` = 128 bits of `HMAC(key, "fingerprint:v1")`; static: its configured
  table; yfinance: `{provider, reproducible: false}`). The world must be installed *before*
  `start_backtest`. `install_run_clock` refuses a backtest DB whose recorded world differs (server
  will not start; CLI exits 1). Pre-ADR runs carry no world and pass. Not yet: re-run driver
  (B-037b), per-agent lived-worlds (B-037c).
- **A backtest is reproducible** (ADR-030 + amendment, `tests/test_phase3_probe.py`): a keyed
  `SyntheticProvider` (`marketdata.provider: synthetic`) makes every daily bar a pure function of
  (key, symbol, day) — offline, request-order free, under the ADR-028 base. The key is ≥128 bits,
  `FUND_MARKETDATA__SYNTHETIC_KEY` only (a `config.yaml` carrying it refuses to load), no default.
  A scripted LLM-free pod lives 31 days through HTTP in ~0.55 s; the same world twice gives the
  same ledger event for event, curve, book and metrics; another world differs. TRD Phase 3
  milestone met for a scripted pod.
- **The world has one now** (ADR-029 + amendment, `tests/test_one_now.py`,
  `tests/test_redteam_0009.py`): `/price`, `/ohlcv` defaults, `/portfolio`, pod metrics, the
  leaderboard, the OMS reference price and the sweep all answer at `ledger_now(session)` — the
  time `/clock` reports and the next event is stamped with. One read of now per report (passed
  down). A backtest advance commits `clock_advanced` (`append_event(at=end)`, one caller by law)
  *before* the process clock moves. `build_portfolio` reads positions + cash together under
  `OMS_LOCK`, then prices. An AST law counts every raw time read per file (any spelling: `.now`,
  `_now`, `wall_now`, `time` module, imports, computed `getattr`, `methodcaller`, SQL clock)
  against an allowlist with reasons; B-028's row stamps are listed as debt.
- **A backtest is honest about time** (ADR-028 + amendment): sealed `MarketDataProvider` base;
  a bar is served only once ended; future/non-finite quotes refused (502 `price_unavailable`);
  window clipped to `as_of`; one uniform 404; past quote = latest ended 1d/1h close; backtests
  > 60 s behind the real now; runs record `look_ahead_guard: true`.
- **A run is a database** (ADR-027); **every agent reads the clock** (ADR-026); **replay order is
  live order** (ADR-025); **portable JSON ledger** (ADR-024); **halt is physics** (ADR-023);
  **dependency law** (ADR-022).
- Physics (`app/`): TRD Phases 0–2 + halt + portable JSON + monotonic time + clock read + backtest
  clock + look-ahead guard + one now + keyed synthetic market + world record + runtime clock
  identity + the lockstep conductor + the run's minds label + the withheld world record.
  **1452 passed + 6 xfailed** (with
  the runtime). No model
  has traded through the App yet (a scripted mind has, through the Runtime). Era I deliverables 2 of 8 done (+ B-004a/b/c,
  B-005); exit criteria 3 of 7 (EC3/5/6, cycle 30; the 1-month criterion needs real minds, R-8).
- **Physics-hole gate (ADR-021):** red-team 0010 (seed recovery, high) and 0011 (static world,
  low), 0012, 0013 (Runtime), 0014 (clock identity), 0015 (conductor: 4 holes), 0016 (provisioning: 4 low) and 0017 (minds label: 4) fixed. 6 strict xfails open (0001: payload
  size ×2 = B-000g, message content = B-000e; 0004: fee = B-026; 0009:
  cross-process `OMS_LOCK` ×2 = B-036). Plus untested-by-xfail items B-019, B-000n, B-000b,
  B-025 (rest), B-028–B-030, B-033 (rest), B-035, B-038, B-040 (low; physics' halt check is
  milder than the Runtime's).
- Still-open time debts: B-017 Sharpe ×0.845, B-028 row stamps, B-029 live forward step, B-036.
  B-032 done (cycle 23).
- **Constraint for Era III (ADR-028 amendment):** agent strategy code never runs inside the App's
  process.
- **The Builder's process now lives in `protocol/`** (P-0003, Human intervention 2026-10-11,
  committed 6449135): `protocol/CYCLE.md` is the full cycle protocol (X-007 resume rule at step 0),
  `protocol/agents/*-extra.md` extend auditor/red-team; `.claude/` is sealed. The Human's
  `setup/` installer has run and is gone (seen cycle 30): the suite is fully green in the
  working tree. The Builder is a team (ADR-035): the architect plans at Gate 2 (first used
  cycle 30), and the auditor and red-team are on the Human's models. Each cycle has an $8 cap.
- **The Human (2026-10-11):** accepted P-0001/P-0002/P-0003. Open: Q-0001 (budget), Q-0002
  (provisioning key) — neither blocks work.
- **OpenClaw** 2026.5.12, mapped; firm in its own profile (ADR-019). Nothing in OpenClaw changed.
- No Truman, Quant Lab or Observatory yet. The Runtime conducts a lockstep backtest. There is no
  live scheduler yet (R-3c). Agents are provisioned from specs, a run is one command
  (`fund-runtime backtest`) and physics records its minds. The RunRecord is printed, not stored
  (R-4).
- **Headless limits:** the guard blocks Bash heredocs, `sed -i`, `git -C`, `git worktree add` /
  `git archive` after `cd`, `python -c` with `#`, `>>` after `cd` → write scripts to `/tmp/*.py`
  with Write and run `uv run --project "<repo>" python -I /tmp/x.py "<repo>"`; edit with Edit;
  `cd "<repo>" && git add … && git commit …` works. `git push origin main <branch>` only as a bare
  command. pytest: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. **R-4b**: the `cassette` provider reads a cassette (reject duplicate JSON keys), replays into
   a fresh DB in the same world; same ledger, declared `minds: replay`; a miss, a changed tool
   surface or a minted key is a recorded divergence (M2). Physics-adjacent (`/run/minds` label):
   plan a red-team.
2. **B-053**: a pre-gate before provisioning in `fund-runtime backtest` (red-team).
3. R-3c `daily_cycle`. B-048 when cheap. Tick-check (X-011) EC2 after R-4b.
