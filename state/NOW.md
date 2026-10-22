# A pitch is argued before its seed: a bull and a bear argue an eligible pitch in its thread, and the manager seeds it now or holds it with a reason; silence keeps the law's seed

## How I understand it
Today the gates decide every seed: a pitch they find eligible gets $200k the next morning, no
one asks. This slice puts a judgement between the gates and the money:
- **The debate law** (in the capital law, frozen when the centre opens): an eligible pitch waits
  a set number of days before its seed. Physics opens a debate for it at the next morning's sweep,
  with the day it closes.
- **Reviewers.** Two centre minds the operator makes, a bull and a bear (a new `reviewer` role).
  They read every open debate (the pitch's hypothesis, rule, the gates' numbers) and the data the
  operator gave them (the bear: headlines), and write in the pitch's thread, nowhere else: they
  cannot trade, pitch, hire, message a pod or rule. The pitch's PM reads its own debate and may
  answer in the thread.
- **The verdict.** The manager reads the thread and rules once, before the window closes:
  *seed* (paid at the next morning's sweep) or *hold* (the seed is refused, with the manager's
  reason, which the PM reads in its pitch's capital answer). Silent: the seed is paid when the
  window closes. The manager only stops or speeds a seed the gates and the centre allow: an
  ineligible pitch, a closed pod, a long-short rule, a copy, a short centre are refused as today;
  there is no amount to name.
- Reviewers' and manager's thinking has no pod: the centre's cost. Without the law, nothing
  changes: no debate, the seed the next morning, every older recording replays identical.
- A pod whose pitch is in its window at a month's end is not "a pod that never earned a seed".

## What done looks like
`uv run python acceptance/pitch_debate.py` ($0, offline):
- A (scripted, through the API): three pods under a 2-day debate law; bull, bear, manager.
  Pod 1: argued, the PM answers, the manager holds → refused with the reason, the PM reads it, no
  money. Pod 2: a seed verdict → paid the next morning, before the window closes. Pod 3: silence →
  paid the morning the window closes, not before. Refused by name (logged): an ineligible pitch,
  a second verdict, a late verdict, a verdict or argument by a reviewer/PM where it is not theirs,
  an amount; a reviewer cannot trade, pitch, message or read a pod. Month's end mid-window: the
  PM stays. Without the law: seeds as today. Rebuild: the same seeds and verdicts.
- B0: the same hosted through the Runtime with the real run's very command, replay IDENTICAL.
- B (recorded): real Haiku bull, bear and manager on a scripted PM's pitch whose universe holds
  a name with a fraud headline only the bear reads; the verdict is the finding.

## Plan
1. Law: `capital.debate_days` (0 = off, left out of the frozen law while off).
2. `app/capital/debate.py`: open debates (events `debate_opened`), the thread (`debate_argued`),
   the verdict (`pitch_ruled`, refusals `pitch_ruling_refused`), views for each reader.
3. The sweep: under the law, open the debate, wait, pay early on seed, refuse on hold, pay at the
   window's close on silence; the pod checks first, cash and the copy check at payment, as today.
4. Role `reviewer` (operator-made, no pod, may be given headlines/company data).
5. API `app/api/debates.py` + MCP tools (named-only); the PM's pitch view shows its debate.
6. Generation: a pod whose pitch is in debate stays.
7. Demo A, then B0 (Runtime: reviewer specs, packages), red-team, auditor, real run B, merge.
Left out: the backtest operator, a debate on the hypothesis itself, reviewers paid by outcome.

## Risk
Money (the seed) and permissions: red-team + auditor before the paid run and merge.

## Progress
- cycle 70: plan; physics, API and demo part A.
