Cycle 0058 · building: a generation turns over · branch: idea/generation-turnover
Done this session:
- Real PMs lived three generations, recorded ($0.575): pod-2's PM, 8 pitches on noise and none
  eligible, was let go at September's end; the crash pod's PM went at the ladder's close; both
  places were hired the same morning and both hires earned seeds; every mind read the library.
- The demo now judges any recording against the month's-end law (verdicts, fitness, let-go PMs
  never act or wake again, hires inside the limit); four forged records fail it. All pass on the
  real run; replay IDENTICAL for $0; the generation report prints from the recording.
- Red-team: 8 holes. Fixed: the Human's agent cap now binds every registration (high); a pod is
  judged by its longest-serving PM (medium); a let-go PM's pending orders are cancelled and a pod
  holding money is not closed by the let-go (medium); the capital view's judgement date (low).
  Four lows filed in the book, strict-xfail tests. Suite green.
Next: make a key's limit hard. In `runtime/openrouter.py`, before each turn, refuse (or cap
max_tokens for) a turn whose worst case (prompt tokens so far + MAX_TURN_TOKENS at the model's
price, from the provider's model list) would cross what the key has left; count a one-turn
reserve per live key in the monthly cap. Old recordings must still replay. Re-record B with
`uv run python acceptance/generation_turnover.py --write-world DIR openrouter` + the backtest
command in this session's journal line; then the auditor on `git diff main...HEAD`; merge.
Watch out: the provider finishes the request that crosses a key's limit (hire-1: $0.200068 of
$0.20), so "none past its key's limit" fails; do not loosen that check. The red-team ran in the
background by mistake (wait for it before acting). The suite prints no summary line: read the
exit code.
Demo: fails one check (a key $0.000068 past its limit); everything else passes.
