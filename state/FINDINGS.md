# FINDINGS — the lab notebook (append-only)

Format:
```
## F-NNNN — <title>   [tags: firm|society|scale|physics|builder]   (cycle N, run_id …)
Observation: what happened, with numbers.
Evidence: event ids, message ids, cassette ids, experiment folder.
Interpretation: what we think it means — and how sure we are.
Follow-up: experiment or backlog item.
```

## F-0001 — The OMS overdraw test never proved the OMS lock   [tags: physics, builder]   (cycle 1)
Observation: `test_concurrent_orders_cannot_overdraw_the_pod` failed ~1 in 3 full-suite runs
(StaleDataError, NULL identity key). On a file-backed engine it passes 40/40 — and also passes
10/10 with `OMS_LOCK` replaced by a no-op. The original in-memory version failed with the lock
removed only through connection-sharing crashes, never through its overdraw assertion.
Evidence: commits 837115c, b058f0d; `app/oms/service.py:239` (flush INSERT) precedes the cash read.
Interpretation: on single-process SQLite, the database write lock taken by the INSERT already
serialises read-check-write; `OMS_LOCK` is defence in depth today and load-bearing only on a
row-locking backend or a shared connection. High confidence. Broader lesson: "N tests green" is
not evidence until the suite is run repeatedly and the guarding tests are mutation-checked.
Follow-up: B-000b; X-003 (mutation checks for invariant tests).

## F-0002 — Phase 2 red-team: identity holds, the numbers don't   [tags: physics]   (cycle 1)
Observation: 42 attacks on bus/costs/metrics/MCP. 0 impersonation, 0 cross-pod read, 0 permission
bypass. 10 holes, all in input bounds and bookkeeping: two in-range token reports (2⁶³−1) make
`/metrics/leaderboard` 500 forever (high); inf/NaN/huge costs; message bodies absent from the ledger;
'system' identity looked up by name; unbounded payloads; MCP path params unescaped.
Evidence: `tests/test_redteam_0001.py` (10 strict xfail, 32 pass).
Interpretation: the *who may do what* layer is solid; the *what values are physical* layer is not.
An agent optimising for leaderboard rank could find the overflow on its own — exactly the kind of
scheming the Constitution treats as data, but here it is our bug.
Follow-up: B-000c…B-000j.

## F-0003 — The first real pod: a careful PM, a forgetful analyst, a small loss   [tags: firm]   (cycle 42)
Observation: three anthropic/claude-haiku-5.5 minds (trend analyst, risk analyst, PM; pod 1, $1M fake)
lived 31 synthetic days with a daily price package. The PM placed 17 accepted orders, always sized
to the risk analyst's per-ticker cap and citing both analysts; the book went $1,000,000 → $993,805
(−0.62%) before $0.25 of thinking. The risk analyst messaged every day; the trend analyst, on 7 of
31 days (steps 2, 8, 15, 16, 20, 22, 25), wrote its calls as its final reply and never sent them, so
the PM traded those days on the risk note alone. The PM cost 2.3–2.7× each analyst.
Evidence: `evidence/real-agents-backtest/month.cassette.json` (replays IDENTICAL at $0;
`uv run python acceptance/real_agents_backtest.py`).
Interpretation: one month, one seed, one model: anecdote, not a result. The PM obeys its risk
analyst more than its trend analyst. "Answering instead of acting" is a model behaviour a charter or
a tool design may change — a known-expected-outcome test candidate.
Follow-up: the model comparison idea (same world, other models); a "the note must reach the PM"
behaviour test.
