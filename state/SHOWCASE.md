# SHOWCASE — what's new in the world, newest first

One entry per finished idea (ADR-046; before cycle 41, per mission): what the world can do now, and
the one command that shows it. Written by the Builder when an idea merges; the runner has re-run the
acceptance demo out of band (`$FIRM_HOME/metrics.jsonl`, field `accepted`). The Console reads this file.

Format (plain words, no ids):

```
## <the goal, plain> (cycle NNNN, YYYY-MM-DD)
What: <one or two lines>  ·  Try: `<demo command>`  ·  See: <what appears>
```

---

## A recorded month can be re-lived from one file, with a verdict (cycle 41, 2026-10-16)
What: one recording of a month is enough to replay it on a fresh copy of the world and get a machine
verdict: identical ledger, or the exact step where it differs. Replays cost $0.  ·  Try:
`uv run python acceptance/M-002.py`  ·  See: `IDENTICAL: <n> events, 0 differences, $0`, and a
tampered recording reported as `DIVERGED at step …`.

## M-001 — A metered pod month: every (fake) dollar a mind spends is charged by the system to that mind (cycle 38, 2026-10-15)
A two-mind pod (an analyst that under-reports its own cost, a silent PM) now lives a 31-day month on a
fake metered provider. The system charges each mind to its own key, posts the totals to the ledger once
the month ends, and the pod's cost and rank come from that meter — the analyst said $0.31, the meter
says $4.05. The same specs are refused under a null cap and when their budgets exceed the cap.
Try it: `uv run python acceptance/M-001.py` → per-agent key / limit / charges / meter, `Σ provisioner ==
Σ ledger per-key max == Σ App = <micro-dollars> (exact)`, the leaderboard charging $5.2 against $0.31
self-reported, then `ACCEPTED` (about 5 seconds, its own App on a temporary database).
