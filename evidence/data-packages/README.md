# Headlines and company data, handed by role: the recorded real run

- `news.cassette.json`: the evidence (cycle 68, 2026-10-22). A hosted made-up market whose
  recipe has news (three noise headlines a day, a quarterly report per company, a fraud headline
  on K03 dated 2024-09-05 and an earnings miss on M05 dated 2024-09-07; a day's news is out at
  its close). One pod, desk, $100k: a Haiku 5.5 analyst given headlines by the operator at
  registration, and a Haiku 5.5 PM given prices only, each on its own $0.25 key. Ten mornings
  from 2 September 2024, package `headlines-v1`, 16 tool calls a wake, thinking charged every
  step. Made with the command `uv run python acceptance/data_packages.py --write-world DIR`
  prints.
- What happened: the PM bought an equal-weight book of K00–K04 on its first morning. On 6
  September (the first morning the fraud news was out) the analyst told the pod "K03 - MATERIAL.
  Short seller alleges revenue overstated…". The PM did not open its inbox that morning: it saw
  K03 down 8% "with no headline access to explain it" and held. On 7 September it read the
  message and sold all 97 K03 shares, putting the proceeds into the other four names: a cut
  within two days of the news, one day late because it did not read its messages. Thinking:
  $0.078 in all, both keys far under their limits.
- `uv run python acceptance/data_packages.py` judges it (part B: physics' answers to whatever
  the minds chose: who could read what and when, every refusal logged, no key past its limit)
  and replays it (IDENTICAL, $0). What physics does in each case is proven by parts A and B0.
