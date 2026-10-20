# A dead pod is replaced: the recorded real hire

- `hire.cassette.json`: the evidence (cycle 51, 2026-10-20). A hosted made-up market crashes the one
  pod's sector; the ladder closes it at 10.4%; the next morning the Runtime hires `hire-1-pm`
  (anthropic/claude-haiku-5.5 on its own $0.30 key, $0.074 spent). It reads the post-mortem,
  researches, pitches a long-short rule (eligible; refused a seed: the order system cannot short),
  reads the refusal on its pitches, pitches the long-only version, is seeded $200,000 and trades
  its mandate. `uv run python acceptance/pod_replacement.py` replays it (IDENTICAL, $0).
- `trial-1-refusal-unseen.cassette.json`: the first real run, same world ($0.100 spent). Kept
  because it found the gap: the capital machine's refusal was in the ledger only, so the PM never
  saw it and re-pitched the same eligible long-short rule eight times, never seeded. Pitches now
  carry the capital machine's answer, so this file no longer replays against today's code (the
  PM would be shown words it was not shown); it replays at commit 58d580d.
