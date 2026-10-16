Cycle 0044 · plan · next: a real PM researches a strategy, pitches it, and the app's validation gates give a verdict the Human can read · branch: idea/pitch-gates (to create)
Done this session:
- Looked back: the real-agents month merged in 2 build sessions (estimate 4), ~$16 of building;
  every finished idea's demo still passes on main; no new comments from the Human.
- The book made true: a real pod exists, the analysts message their PM, prices-v1 is handed out
  daily, thinking costs real dollars inside the cap, and "who hosts the agents" is decided (ADR-047).
- "The pitch and the gates" cut in three; the first piece is queued `ready` in state/missions.json
  with its shape: the strategy is a rule (data, not code), every research backtest is counted, the
  gates judge on a held-out window, the Human reads the verdict, no capital granted yet.
- Process: a demo that measures or judges must show both a "yes" case and a "no" case.
Next: build session — branch idea/pitch-gates, write state/NOW.md from the queue entry's notes, the
acceptance demo (gate controls first: planted signal passes, noise fails, 1 vs 200 attempts), then
the rule language and gate engine as pure functions, then the endpoints + MCP tools, then one real
PM session recorded.
Watch out: the synthetic market is pure noise (random walk), so the real PM's pitch is expected to
FAIL the gates; that is the honest result, not a bug. Physics tier (new permissions + real spend):
red-team + auditor before merge. OpenRouter credit ≈ $1.60. Never `cd "<repo>" && …`.
Demo: none yet for this idea (acceptance/pitch_gates.py to write).
