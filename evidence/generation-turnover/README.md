# A generation turns over: the recorded real run

- `generations.cassette.json`: the evidence (cycle 59, 2026-10-21; it replaces cycle 58's, whose
  hire-1 key spent $0.200068 of its $0.20 limit). A hosted made-up market, three sectors whose
  fates no mind is told (pod-1 an edge, pod-2 noise, pod-3 a crash), two unheld sectors with an
  edge. Three founding PMs and every hire are anthropic/claude-haiku-5.5, each on its own $0.20
  key; 31 steps of 3 days (Sep 1 to Dec 3, 2024); the generation law on (judged after 20 days), at
  most 3 live pods, thinking charged at every step's end.
  What happened: pod-3 was closed by the risk ladder on Sep 19; its PM was let go at the close and
  hire-1 took the place the same morning. pod-2 made 6 pitches on noise, none eligible: let go at
  September's end; hire-2 took the place on Oct 1. pod-1, hire-1 and hire-2 all held seeds and
  stayed through October and November; in November the three pods made $452k. Thinking: $0.545 in
  all, every key under its limit (the most, hire-2, $0.181 of $0.20).
  `uv run python acceptance/generation_turnover.py` judges it against the law (part B) and
  replays it (IDENTICAL, $0).
- The hard limit (no turn sent whose worst case could cross what its key has left) was on for this
  run but never had to refuse a turn: no key came near its limit. It is proven by
  `tests/test_runtime_openrouter.py` and `tests/test_redteam_0031.py`, and by pricing every one of
  cycle 58's 394 real turns after the fact: the bound held for each (at least 2.4x its real cost),
  and it would have stopped hire-1 at $0.193 of $0.20. This run used the guard's first version
  (priced at the model list's price); the merged one prices at the dearest host (10% more for
  some regions) and reads text as a normalizing tokenizer would.
