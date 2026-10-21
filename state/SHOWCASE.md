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

## Designs that work reproduce: a freed place goes to a child of the month's fittest pod (cycle 62, 2026-10-21)
What: at a month's end the fittest living pod becomes the parent of every hire into a freed place: the child gets its model and rule with one change, knows its parent, and must still pitch; each month the firm counts its distinct designs and flags a collapse  ·  Try: `uv run python acceptance/designs_reproduce.py`  ·  See: a family tree (edge -> its children, each with its one change), each month's diversity line, and real Haiku PMs where the edge pod's child found its own sector and made $169k in November

## Capital follows results: the centre funds what works and the drawdown ladder cuts what bleeds (cycle 48, 2026-10-19)
What: an eligible pitch earns a seed and trades forward; an algorithm moves capital toward the pods that earn it, net of thinking cost and cut for copying; a pod that falls 5% is halved, 7.5% may only sell, 10% is closed and its money goes back  ·  Try: `uv run python acceptance/capital_machine.py`  ·  See: 100 days of an allocation table, the planted edge growing from $200k to about $3.4M, the copy staying small, the bleeder halved, frozen and closed, its refused buys

## A PM pitches a strategy and the validation gates judge it (cycle 46, 2026-10-16)
What: a real AI PM researched four strategy rules (each try counted), pitched the best one, and the
gates judged it on six months it was not tuned on: it failed, and the PM explained why it overfit.
Try: `uv run python acceptance/pitch_gates.py`  ·  See: the gates proven on a planted signal (pass) and
noise (fail), then the PM's pitch, its research, the gate table and the PM's own words.

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

## Real AI agents live a backtest month on fake money (cycle 43, 2026-10-16)
What: a PM and two analysts on a real model (Haiku 5.5) lived 31 days on a sealed market, each fed the
day's prices, each on its own capped key: 17 orders, book −0.62%, $0.25 of thinking in total, recorded
and replayed identical for $0.  ·  Try: `uv run python acceptance/real_agents_backtest.py`  ·  See: day
by day what each agent saw, said, traded and cost, the book's path, and the cost per agent.

## A dead pod is replaced by a newly hired PM (cycle 51, 2026-10-20)
What: when the risk ladder closes a pod, a vacancy opens with its post-mortem and the firm hires a new
pod and PM the next morning, under the cap. Recorded: a real Haiku 5.5 hire read the post-mortem,
researched, pitched long-short (refused: no shorting yet), read why, re-pitched long-only, was seeded
$200k and trades its mandate, for $0.07.  ·  Try: `uv run python acceptance/pod_replacement.py`  ·
See: the close, the vacancy, the hire, each of the new PM's days in its own words, its pitches with
the gates' verdict and the capital answer, all replayed identical for $0.

## The firm lives a quarter (cycle 55, 2026-10-20)
What: four real Haiku 5.5 PMs, each on one sector of a made-up market whose fates nobody inside knew
(an edge, noise, a slow sink, a crash), competed for one pot for three months. The edge pod was
raised to $2.9M (+11%), the noise pod was never funded, the sinking and crashing pods were closed by
the ladder and replaced the same morning by hires who earned seeds; the firm ended $10.31M from
$10.00M, for $0.67 of thinking.  ·  Try: `uv run python acceptance/firm_quarter.py`  ·  See: the
quarter report (equity per pod week by week, each pod's P&L net of thinking, every seed, close and
hire), replayed identical for $0; the Human can print it with `fund-env quarter-report`.

## A generation turns over: each month's end lets go the PMs who failed and hires into their places (cycle 59, 2026-10-21)
What: at every month's end the firm measures each pod's P&L net of its thinking; the PM whose pod never earned a seed is let go, the crash's PM goes at the ladder's close, each lesson goes into a library every PM reads, and the freed places are hired the next morning. Real Haiku PMs lived three generations for $0.51, and no key can spend past its limit any more.  ·  Try: `uv run python acceptance/generation_turnover.py`  ·  See: the generation report (each month's pods, fitness, who stayed, who went and why, who was hired, the library), replayed identical for $0.

## A PM builds its own team (cycle 64, 2026-10-22)
What: a PM can ask for an analyst it describes (a charter in its words, a model, a budget); the firm's law grants or refuses it by name, the analyst is hired the next morning into the PM's pod, its research counts in the PM's pitch and its thinking in the pod's results; it can be let go, and it leaves with its PM. Real Haiku PMs were offered a team: none took it, and one said why (every extra attempt makes its test harder).  ·  Try: `uv run python acceptance/pm_builds_team.py`  ·  See: each grant and refusal with its reason, the analyst at work, the team's cost, and the real PMs' choice, replayed identical for $0.
