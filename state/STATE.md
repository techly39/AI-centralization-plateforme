# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 23 (R-3a the world's clock belongs to the Runtime — merged 5397ad2, 2026-10-12)

## What is true now
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
  identity. **1178 passed + 6 xfailed** (with the runtime). No model
  has traded through the App yet (a scripted mind has, through the Runtime). Era I deliverables 2 of 8 done (+ B-004a/b/c,
  B-005); exit criteria 0 of 7 (the 1-month criterion needs a PM + Analyst *via the Runtime*).
- **Physics-hole gate (ADR-021):** red-team 0010 (seed recovery, high) and 0011 (static world,
  low), 0012, 0013 (Runtime) and 0014 (clock identity) fixed. 6 strict xfails open (0001: payload
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
  `protocol/agents/*-extra.md` extend auditor/red-team; `.claude/` is sealed. **`setup/`** (the
  Human's one-shot installer: copies protected files, then deletes itself) is untracked and
  untouched — never run or delete it. Until the Human runs it,
  `test_every_python_directory_is_placed_in_the_law` fails in the working tree (only `setup/`);
  step 0 must treat `?? setup/` as the Human's, not as junk.
- **The Human (2026-10-11):** accepted P-0001/P-0002/P-0003. Open: Q-0001 (budget), Q-0002
  (provisioning key) — neither blocks work.
- **OpenClaw** 2026.5.12, mapped; firm in its own profile (ADR-019). Nothing in OpenClaw changed.
- No Truman, Quant Lab or Observatory yet. The Runtime wakes one scripted mind per call; no
  scheduler yet (R-3).
- **Headless limits:** the guard blocks Bash heredocs, `sed -i`, `git -C`, `git worktree add` /
  `git archive` after `cd`, `python -c` with `#`, `>>` after `cd` → write scripts to `/tmp/*.py`
  with Write and run `uv run --project "<repo>" python -I /tmp/x.py "<repo>"`; edit with Edit;
  `cd "<repo>" && git add … && git commit …` works. `git push origin main <branch>` only as a bare
  command. pytest: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. **R-3b** Lockstep backtest workflow in `runtime/`: per step halt/cap → wake specs in id order
   via `native.wake` → advance with the runtime key. A scripted PM + Analyst (new script: the
   Analyst messages a signal, the PM trades on it) live a month, run labelled `minds: scripted`
   (M1). R-2 carry-overs (provision agents from specs, bind name; count tool-function errors).
   B-041 (runtime key rotation + startup squat check) first, or as the first commit. If it is
   too big: provisioning from specs → R-3b, the month → R-3b'.
2. **R-4** Cassettes + replay (M2): `WakeRecord` transcripts already serialise by construction.
3. **R-5** Agent-level gates (EC3/5/6); R-3c `daily_cycle`. B-040 when cheap. Retrospective at 30.
