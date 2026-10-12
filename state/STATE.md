# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 19 (B-037a a run records its world — merged 842e958, 2026-10-12)

## What is true now
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
  clock + look-ahead guard + one now + keyed synthetic market + world record. **796 passed + 8
  xfailed**. No model
  has traded through the App yet (a scripted pod has). Era I deliverables 2 of 8 done (+ B-004a/b/c,
  B-005); exit criteria 0 of 7 (the 1-month criterion needs a PM + Analyst *via the Runtime*).
- **Physics-hole gate (ADR-021):** red-team 0010 (seed recovery, high) and 0011 (static world,
  low) fixed. 8 strict xfails open (0001: payload size ×2 = B-000g, message
  content = B-000e, system squat = B-000f, MCP path = B-000h; 0004: fee = B-026; 0009:
  cross-process `OMS_LOCK` ×2 = B-036). Plus untested-by-xfail items B-019, B-000n, B-000b,
  B-025 (rest), B-028–B-030, B-033 (rest), B-035, B-038 (low).
- Still-open time debts: B-017 Sharpe ×0.845, B-028 row stamps, B-029 live forward step, B-036.
  B-032: clock control moves off management before an LLM manager wakes.
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
- No Runtime, Truman, Quant Lab or Observatory yet. `bible/09_BUILDER_VISION.md` not yet written
  (due with the Launch Pad's end — at the cycle-20 retrospective at the latest).
- **Headless limits:** the guard blocks Bash heredocs, `sed -i`, `git -C`, `git worktree add` /
  `git archive` after `cd`, `python -c` with `#`, `>>` after `cd` → write scripts to `/tmp/*.py`
  with Write and run `uv run --project "<repo>" python -I /tmp/x.py "<repo>"`; edit with Edit;
  `cd "<repo>" && git add … && git commit …` works. `git push origin main <branch>` only as a bare
  command. pytest: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. **Cycle 20 is a retrospective** (re-read 00 + 01, `06_LOOP` §6): write
   `bible/09_BUILDER_VISION.md` (due now) and the Runtime plan (Era I exit: PM + Analyst complete
   the month *via the Runtime*), split into backlog slices.
2. B-037b `fund-env backtest` re-run driver (fingerprint check first, ledger diff) — or B-037c
   lived-worlds, whichever the Runtime plan needs first.
3. B-036 stamp-after-flush check (closes 2 xfails) or B-028 row stamps — the probe is the
   determinism harness for both. (S-004b stays blocked on P-0002.)
