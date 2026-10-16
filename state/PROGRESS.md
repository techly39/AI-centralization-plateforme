Cycle 0042 · building: real AI agents (a PM and two analysts) live a backtest month on fake money · branch: idea/real-agents-backtest
Done this session:
- Decided: the app's own runtime hosts the agents; OpenRouter is the first real metered provider (ADR-047).
- Built: one OpenRouter key per agent with a hard limit, the month counted across runs from the
  provider itself (the Human's own keys never touched), the daily price package, metered runs
  recorded and verified with their cost rows judged apart, provider keys redacted.
- The real month: 3 Haiku 5.5 minds, 31 days, 17 orders, book −0.62%, $0.25 total; replays
  IDENTICAL at $0 (`evidence/real-agents-backtest/`, finding F-0003).
- Red-team launched on the diff (it ran in the background by mistake; foreground from now on).
Next: read the red-team result, fix every high finding, then the auditor (foreground) on
`git diff main...HEAD`, fix every BLOCK, full suite, merge, mark the idea working.
Watch out: OpenRouter credit was ~$1.86 before the month (≈$1.60 now): enough for ~6 more months
of this pod. Never `cd "<repo>" && …`. The red-team must stay offline (no provisioning key).
Demo: passes (`uv run python acceptance/real_agents_backtest.py`, $0, ~10 s).
