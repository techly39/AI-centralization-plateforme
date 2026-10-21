Cycle 0059 · merged: a generation turns over · branch: idea/generation-turnover (merged to main)
Done this session:
- A key's limit is hard: no turn is sent whose worst case (prompt bounded by its bytes, or by the
  provider's count for the turn before plus what was added; 4096 written tokens; the dearest host
  and price tier) could cross what the key has left. Red-team 0031: 6 holes, 5 fixed (Unicode-
  normalized text, dearer hosts, 408s, unreadable answers, price fields), 1 low filed.
- Auditor on the whole idea: PASS, no BLOCK; its notes on the demo's tenure rule and model ids fixed.
- Real PMs re-recorded with 24 tool calls a wake ($0.506): the noise PM let go at September's end,
  the crash's PM at its close, both hires seeded and kept; hire-1 stopped by the guard at $0.195 of
  $0.20 (four turns refused unsent). The demo now checks the run's settings; report shows cents.
Next: plan session: take the next idea from the book's "Next up" (the next slice of "every month
is a generation" is reproduction: a winner's design copied with variation).
Watch out: real runs need --max-tool-calls 24 (default 64); the demo checks it. The suite prints
no summary line: read the exit code.
Demo: passes.
