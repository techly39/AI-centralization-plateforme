# A generation turns over: the recorded real run

- `generations.cassette.json`: the evidence (cycle 58, 2026-10-20). A hosted made-up market, three
  sectors whose fates no mind is told (pod-1 an edge, pod-2 noise, pod-3 a crash), two unheld
  sectors with an edge. Three founding PMs and every hire are anthropic/claude-haiku-5.5, each on
  its own $0.20 key; 31 steps of 3 days (Sep 1 to Dec 3, 2024); the generation law on (judged
  after 20 days), at most 3 live pods, thinking charged at every step's end.
  What happened: pod-3 was seeded on day 3 and closed by the ladder on Sep 19; its PM was let go at
  the close and hire-1 took the place the same morning (seeded Sep 28). pod-2 ran 17 backtests and
  8 pitches on noise, none eligible: let go at September's end; hire-2 took the place on Oct 1
  (seeded Oct 4). pod-1 was seeded on day 6 and stayed. Every mind read the library. The firm's
  three pods ended November with $558k of P&L that month. Thinking: $0.575 in all.
  `uv run python acceptance/generation_turnover.py` judges it against the law (part B) and
  replays it (IDENTICAL, $0).
- Known: hire-1's key spent $0.200068 of its $0.20 limit. The provider lets the request that
  crosses a key's limit finish, then refuses (hire-1's last two wakes were refused). The demo's
  check "none past its key's limit" fails on this, and stays as written until a key's limit is
  hard (next step of the idea).
