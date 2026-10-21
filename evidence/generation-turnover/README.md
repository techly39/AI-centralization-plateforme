# A generation turns over: the recorded real run

- `generations.cassette.json`: the evidence (cycle 59, 2026-10-21; it replaces cycle 58's, whose
  hire-1 key spent $0.200068 of its $0.20 limit). A hosted made-up market, three sectors whose
  fates no mind is told (pod-1 an edge, pod-2 noise, pod-3 a crash), two unheld sectors with an
  edge. Three founding PMs and every hire are anthropic/claude-haiku-5.5, each on its own $0.20
  key; 31 steps of 3 days (Sep 1 to Dec 3, 2024), 24 tool calls a wake; the generation law on
  (judged after 20 days), at most 3 live pods, thinking charged at every step's end.
  What happened: pod-3 was closed by the risk ladder on Sep 19; its PM was let go at the close and
  hire-1 took the place the same morning. pod-2 made 5 pitches on noise, none eligible: let go at
  September's end; hire-2 took the place on Oct 1. pod-1, hire-1 and hire-2 all held seeds and
  stayed through October and November; in November the three pods made $657k. Thinking: $0.506
  in all, every key under its limit.
  `uv run python acceptance/generation_turnover.py` judges it against the law (part B) and
  replays it (IDENTICAL, $0).
- The hard limit at work: hire-1 reached $0.195 of its $0.20; its last four wakes each ended on a
  turn the Runtime refused unsent (the worst case did not fit what was left). The provider
  answered 377 turns, all 200, the same as the 377 charges on the five keys: nothing was sent past
  the guard. Over cycle 58's 394 real turns, priced after the fact, the bound held for each (at
  least 2.4x its real cost).
