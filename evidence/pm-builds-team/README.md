# A PM builds its own team: the recorded real run

- `team.cassette.json`: the evidence (cycle 64, 2026-10-22). The generation-turnover world (a
  hosted made-up market; pod-1 an edge sector, pod-2 noise, pod-3 a crash, two unheld sectors with
  an edge; no mind is told any fate) with the team law on: two analysts a pod at most, a $0.20 team
  budget a pod, Haiku only. Three founding PMs, each anthropic/claude-haiku-5.5 on its own $0.20
  key, every PM (founder or hire) told it may build a team and given the team tools (get_team,
  request_analyst, let_go_analyst) and the message tools; 12 steps of 3 days (Sep 1 to Oct 7,
  2024), 24 tool calls a wake, thinking charged every step. Made with the command
  `uv run python acceptance/pm_builds_team.py --write-world DIR` prints.
- What happened: **no PM asked for an analyst.** Three of the five PMs read their team (get_team,
  7 times in all) and chose to work alone. pod-2, on the noise sector, ran 26 backtests and 8
  pitches, none eligible, and said why it stopped: "more attempts would only make the next
  deflated-Sharpe test harder" (an analyst's backtests count the same). pod-3 pitched an eligible
  rule early; hire-1 (in a freed place) found the unheld W sector and kept a seed. Thinking: $0.264
  in all, five keys, every one under its limit.
- `uv run python acceptance/pm_builds_team.py` judges it (part B: physics' answers to whatever the
  minds chose) and replays it (IDENTICAL, $0). What physics does when a PM does hire is proven by
  parts A and B0, where the choice is forced.
