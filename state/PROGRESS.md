Cycle 0043 · merged: real AI agents (a PM and two analysts) live a backtest month on fake money · branch: idea/real-agents-backtest
Done this session:
- Red-team (foreground) attacked the real-model month: 9 holes, 3 high. All fixed, each pinned as a
  test: one run mints keys at a time and counts its own keys at once; the check before every wake
  asks the account for the whole month; keys the provider does not bound exactly are disabled at
  once; a key stops at its limit; turns are capped at 4096 tokens; keys are disabled whatever ends
  the run; `replay --verify` refuses rewritten cost rows.
- Auditor: PASS, no blocks; its notes fixed (wording in the decision record, Ctrl-C while minting).
- Merged to main; the idea is "working" in the book.
Next: plan the next idea from "Next up" (the pitch and the gates), or the richer data packages
(company data, headlines) if the plan session judges them first.
Watch out: the demo replays the recorded month, so it proves the record, not the live path (the live
OpenRouter path is tested against a fake account). OpenRouter credit ≈ $1.60. The mint lock is one
file per copy of the repo (`.openrouter-mint.lock`, gitignored). Never `cd "<repo>" && …`.
Demo: passes (`uv run python acceptance/real_agents_backtest.py`, $0, ~7 s).
