# Designs reproduce: the recorded real run

- `reproduce.cassette.json`: the evidence (cycle 62, 2026-10-21). The generation-turnover world
  (a hosted made-up market; pod-1 an edge sector, pod-2 noise, pod-3 a crash, two unheld sectors
  with an edge; no mind is told any fate) with the reproduction law on (seed 11). Three founding
  PMs, each anthropic/claude-haiku-5.5 on its own $0.20 key, their model declared at registration;
  31 steps of 3 days (Sep 1 to Dec 3, 2024), 24 tool calls a wake, thinking charged every step.
  Made with the command `python acceptance/designs_reproduce.py --write-world DIR` prints.
- What happened: pod-3 was closed by the risk ladder on Sep 19; no month had been measured, so its
  place got the plain hire (hire-1, who found the unheld T sector and kept a seed). pod-2 made 8
  mean-reversion pitches on noise, none eligible, and was let go at September's end. The fittest
  living pod of September was pod-1 ($15,186 net of thinking), so pod-2's place went to its child,
  hire-2: Haiku, pod-1's rule with one change (rebalance every 10 days -> 5), told its parent and
  the 10 attempts its family had made. hire-2 did not keep the inherited sector: it pitched on the
  unheld W names with its parent's lookback and won a seed. In November the three pods made $770k.
  Diversity: 3 live pods, 3 designs, pod-1's family 67%; no collapse. Thinking: $0.547 in all,
  every key under its limit.
- `uv run python acceptance/designs_reproduce.py` judges it against the law (part B) and replays
  it (IDENTICAL, $0).
