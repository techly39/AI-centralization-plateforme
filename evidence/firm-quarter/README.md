# The firm lives a quarter: the recorded real quarter

- `quarter.cassette.json`: the evidence (cycle 54, 2026-10-20). A hosted made-up market with four
  sectors whose fates no mind is told (pod-1 an edge, pod-2 noise, pod-3 a slow sink, pod-4 a crash
  on day 40; two unheld sectors with an edge). Four founding PMs and every hire are
  anthropic/claude-haiku-5.5, each on its own key ($0.20). 30 steps of 3 days, `tell_pms` on, at
  most 4 live pods. What the minds did: pod-1 was refused a long-short rule, re-pitched long-only,
  was seeded and raised by the algorithm to $2.9M put in (+11%); pod-2 never had an eligible
  pitch; pod-3 and pod-4 were seeded, then closed by the ladder (10.2% and 10.7% down) and
  replaced the same morning by hires who read the post-mortem; hire-2 was seeded and raised,
  hire-1 seeded in the last week. Thinking: $0.672 in all, charged by the system per key.
  `uv run python acceptance/firm_quarter.py` replays it (IDENTICAL, $0) and prints the report.
  Its verify re-reads the Human's agent cap (`firm.max_agents_total`): a cap below 4 makes it
  refuse to verify (fails closed).
- `trial-1-meter-timeout.cassette.json`: the first real run, same world ($0.52 spent). Kept
  because it found the gap: one 408 from OpenRouter while counting the month stopped the run at
  step 26 (fail closed, as designed) and the cost sync hit the same timeout, so no cost reached the
  ledger. Account reads now retry a passing failure, three times at most. It does not replay
  (only a completed run does); it was recorded at commit e56e479's parent, before the red-team's
  correlation-gate fix.
