Cycle 0059 · building: a generation turns over · branch: idea/generation-turnover
Done this session:
- A key's limit is hard: no turn is sent whose worst case (prompt bounded by its bytes, or by the
  provider's count for the turn before plus what was added; 4096 written tokens; the dearest host
  and price tier) could cross what the key has left. Over cycle 58's 394 real turns the bound held
  every time (at least 2.4x the real cost); it would have stopped hire-1 at $0.193 of $0.20.
- Red-team 0031 on the guard: 6 holes (2 medium: Unicode-normalized text, dearer hosts), 5 fixed,
  1 low filed (the provider's own prompt count is trusted). Auditor on the whole idea: PASS, no
  BLOCK; notes fixed (demo judges by the longest-serving PM, model ids with '..' refused).
- Re-recorded the real run ($0.545, every key under its limit, IDENTICAL), then found it ran with
  64 tool calls a wake, not the design's 24: the demo now checks this, and the run is being
  re-recorded with --max-tool-calls 24 (in $TMPDIR/gen59b when this was written).
Next: when the 24-call recording completes, copy it to evidence/generation-turnover/, update its
README's numbers, run the demo (must pass), full suite, merge to main, suite on main, push.
Watch out: pass --max-tool-calls 24 (the default is 64). The suite prints no summary line: read
the exit code.
Demo: fails one check until the 24-call recording lands.
