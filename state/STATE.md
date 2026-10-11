# STATE — rewritten every cycle

**Era:** I — The Desk (Era ½ closed cycle 9, ADR-021; Launch Pad: Survey ✅ → I → II)
**Last cycle:** 16 (B-005 look-ahead guard — merged cb6f4f6, 2026-10-11)

## What is true now
- **A backtest is honest about time** (ADR-028 + amendment, `tests/test_look_ahead.py`,
  `tests/test_redteam_0008.py`): every feed goes through the `MarketDataProvider` base, whose
  `get_price`/`get_ohlcv` cannot be replaced (MRO check, class and instance setattr refused).
  A bar is served only once it has *ended*; a quote stamped after `as_of` or not a positive finite
  price → `FeedDataError` (502, `price_unavailable`, order stays pending); the window handed to a
  feed is clipped to `as_of`'s day; no ended bar → one uniform 404. yfinance: the live quote only
  within 60 s of the real now; otherwise the close of the latest ended 1d **or 1h** bar (a fill is
  never older than what `/ohlcv` already shows), stamped at its end; past quotes cached per exact
  `as_of`. Backtests stay strictly > 60 s behind the real now. New runs record
  `look_ahead_guard: true`.
- **A run is a database** (ADR-027): `fund-env start-backtest --start <ISO>` → empty DB +
  `run_started`; clock moves only by `POST /clock/advance` (`CONTROL_CLOCK`, management/system);
  live → 409; `append_event` refuses a process clock not its ledger's run.
- **Every agent reads the clock** (ADR-026); **replay order is live order** (ADR-025); **the
  ledger is portable JSON** (ADR-024); **halt is physics** (ADR-023); **dependency law** (ADR-022).
- Physics (`app/`): TRD Phases 0–2 + halt + portable JSON + monotonic time + clock read + backtest
  clock + look-ahead guard (Phase 3b). **675 passed + 6 xfailed**. No model has traded through the
  App yet. Era I deliverables 2 of 8 done (+ B-004a, B-005); exit criteria 0 of 7.
- **Physics-hole gate (ADR-021):** 6 strict xfails open (0001: payload size ×2 = B-000g, message
  content = B-000e, system squat = B-000f, MCP path = B-000h; 0004: fee = B-026). Plus untested-
  by-xfail items B-019, B-000n, B-000b, B-025 (rest), B-028–B-030, B-033, B-035 (low).
- Still-open time debts: B-004b one "now" for metrics/market data, B-017 Sharpe ×0.845, B-029
  live forward step. B-032: clock control moves off management before an LLM manager wakes.
- **Constraint for Era III (ADR-028 amendment):** agent strategy code must never run inside the
  App's process — Python has no true `final`, the seal is the process boundary.
- **Interrupted cycles happen** (cycles 13, 16). Rule X-007 by judgement: at step 0, a
  `cycle/NNNN-*` branch not merged with NNNN > `loop_status.cycle` is resumed at step 5. P-0003
  waits for the Human.
- **The Human (2026-10-11):** accepted P-0001/P-0002; Q-0003/Q-0004 closed. Open: Q-0001 (budget),
  Q-0002 (provisioning key) — neither blocks work. P-0003 open.
- **OpenClaw** 2026.5.12, mapped; firm in its own profile (ADR-019). Nothing in OpenClaw changed.
- No Runtime, Truman, Quant Lab or Observatory yet. `bible/09_BUILDER_VISION.md` not yet written
  (due with the Launch Pad's end — at the cycle-20 retrospective at the latest).
- **Headless limits:** the guard blocks Bash heredocs, `>>` redirection after `cd`, `python -c`
  with `#`, `sed -i` in compound commands, and some quoted `$(...)`/`"$PWD"` → write scripts to
  `/tmp/*.py` with Write and run `uv run --project "<repo>" python -I /tmp/x.py "<repo>"`; edit
  with Edit. `git push origin main <branch>` only as a bare command. pytest:
  `uv run pytest -p no:warnings -o addopts="" -q` (plain `-q` prints no summary line).

## Next 3 moves
1. B-004b one "now" (`ledger_now`) for metrics/market data/leaderboard + grep test.
2. The Phase 3 milestone probe: one scripted pod (no LLM), 1-month backtest, < 10 min, replayed
   twice to the same equity curve (first determinism test; measures B-035b request volume).
3. S-004b (quick): `git rm test_api.py`, untrack `.vscode/`.
