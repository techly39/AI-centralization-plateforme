# SHOWCASE — what's new in the world, newest first

One entry per accepted mission (ADR-042): what the world can do now, and the one command that shows
it. Written by the Builder when a mission merges; the runner has re-run the acceptance check out of
band (`$FIRM_HOME/metrics.jsonl`, field `accepted`).

Format:

```
## M-NNN — <title> (cycle NNNN, <date>)
<2–4 lines: what is possible now that was not before>
Try it: `<demo command>` → <what you will see>
```

---

## M-001 — A metered pod month: every (fake) dollar a mind spends is charged by the system to that mind (cycle 38, 2026-10-15)
A two-mind pod (an analyst that under-reports its own cost, a silent PM) now lives a 31-day month on a
fake metered provider. The system charges each mind to its own key, posts the totals to the ledger once
the month ends, and the pod's cost and rank come from that meter — the analyst said $0.31, the meter
says $4.05. The same specs are refused under a null cap and when their budgets exceed the cap.
Try it: `uv run python acceptance/M-001.py` → per-agent key / limit / charges / meter, `Σ provisioner ==
Σ ledger per-key max == Σ App = <micro-dollars> (exact)`, the leaderboard charging $5.2 against $0.31
self-reported, then `ACCEPTED` (about 5 seconds, its own App on a temporary database).
