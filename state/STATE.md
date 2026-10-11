# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 15 (B-004a backtest clock — merged 87ac9b9, 2026-10-11)

## What is true now
- **A run is a database** (ADR-027, `tests/test_backtest_clock.py`, `tests/test_redteam_0007.py`):
  `fund-env start-backtest --start <ISO>` opens an *empty* DB with `run_started {mode, start,
  look_ahead_guard: false}`; any other DB is live. The backtest clock (`BacktestClock`) is rebuilt
  from the ledger at server start and before every CLI command; it moves only by
  `POST /clock/advance` (`CONTROL_CLOCK` = management/system; `{days, minutes}` 1 min..366 d; never
  past the real now) → `clock_advanced` event → pending sweep. Live → 409. `append_event` refuses a
  process clock that is not its ledger's run (503 "restart"). No `POST /clock/mode`; `clock.mode`
  is gone from config. Orders and sweeps price at the now they are stamped with (under `OMS_LOCK`).
- **A backtest is not yet honest:** market data has no look-ahead guard (B-005); yfinance ignores
  `as_of`. Every run records `look_ahead_guard: false` until B-005 flips it.
- **Every agent reads the clock** (ADR-026): `/clock` = `{mode, now=ledger_now}`.
- **Replay order is live order** (ADR-025); **the ledger is portable JSON** (ADR-024); **halt is
  physics** (ADR-023); **the dependency law is enforced** (ADR-022).
- Physics (`app/`): TRD Phases 0–2 + halt + portable JSON + monotonic time + clock read + backtest
  clock. **628 passed + 8 xfailed**. No model has traded through the App yet. Era I deliverables
  2 of 8 done (+ B-004a); exit criteria 0 of 7.
- **Physics-hole gate (ADR-021):** 8 strict xfails open (0001: payload size ×2 = B-000g, message
  content = B-000e, system squat = B-000f, MCP path = B-000h; 0004: fee = B-026, feed price ×2 =
  B-025). Plus untested-by-xfail items B-019, B-000n, B-000b, B-028–B-030, B-033 (low).
- Still-open time debts: B-005 look-ahead, B-004b one "now" for metrics/market data, B-017 Sharpe
  ×0.845, B-029 live forward step. B-032: clock control moves off management before an LLM
  manager wakes.
- **Interrupted cycles happen** (cycle 13). Rule X-007 by judgement: at step 0, a `cycle/NNNN-*`
  branch not merged with NNNN > `loop_status.cycle` is resumed at step 5. P-0003 waits for the Human.
- **The Human (2026-10-11):** accepted P-0001/P-0002; Q-0003/Q-0004 closed. Open: Q-0001 (budget),
  Q-0002 (provisioning key) — neither blocks work. P-0003 open.
- **OpenClaw** 2026.5.12, mapped; firm in its own profile (ADR-019). Nothing in OpenClaw changed.
- No Runtime, Truman, Quant Lab or Observatory yet. `bible/09_BUILDER_VISION.md` not yet written
  (due with the Launch Pad's end — consider it at the cycle-20 retrospective at the latest).
- **Headless limits:** the guard blocks Bash heredocs, `python -c` with `#`, and some quoted
  `$(...)`/`"$PWD"` → write scripts to `/tmp/*.py` with Write and run
  `uv run --project "<repo>" python -I /tmp/x.py "<repo>"`; edit with Edit. `git push origin main
  <branch>` only as a bare command. pytest: `uv run pytest -p no:warnings -o addopts="" -q`.

## Next 3 moves
1. B-005 look-ahead guard on every market-data route (bars by end time, quotes never stamped with
   the requested time, test double fixed) → flip `LOOK_AHEAD_GUARD`; red-team.
2. B-004b one "now" (`ledger_now`) for metrics/market data + the Phase 3 milestone probe (1-month
   backtest, one scripted pod, < 10 min).
3. S-004b (quick): `git rm test_api.py`, untrack `.vscode/`.
