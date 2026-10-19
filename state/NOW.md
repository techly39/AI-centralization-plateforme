# Capital follows results: eligible pods trade forward with a seed, an algorithm moves capital to what works, and the drawdown ladder cuts what bleeds

## How I understand it
The firm is a multi-manager hedge fund: the centre holds the capital, the pods hold the ideas.
Today a PM can pitch a strategy and the gates can call it eligible, but no money moves. Now:
- The centre opens with the firm's capital (the law, in `config.yaml`, frozen for the run).
- An eligible pitch earns a small seed at the next day. Its pod then trades its rule forward, on
  days that had not happened when it was judged, through the ordinary order system.
- Every few days an algorithm (not an agent) re-weighs capital: a cost- and risk-adjusted score of
  each pod's forward days, cut for copying an older pod and for drawdown; capital moves toward the
  best, within limits on each move. Every move is one event holding its inputs, so anyone can redo it.
- The drawdown ladder is physics, checked every day from each pod's own high-water mark:
  5% down → half its capital goes back to the centre; 7.5% → it may only sell; 10% → the pod is
  closed, its positions sold and all its money returned. No agent can argue with it.
- Long-short rules get no seed yet: the order system cannot short (said plainly in the ledger).

## What done looks like
`uv run python acceptance/capital_machine.py` ($0, offline, a made-up market): four pods pitch
rules that the gates find eligible. Then a hundred forward days pass:
- the planted edge's capital grows several times; the good pod is never cut;
- a pod whose edge died at the pitch (noise forward) is not raised and ends small;
- a pod that looked different at the pitch but moves exactly like the edge pod forward is
  penalised for the correlation and does not grow like the original;
- a pod whose market collapses is halved at 5%, refused a buy at 7.5% (403, logged), closed at 10%
  with every share sold and its money back at the centre; a closed pod's order is refused too;
- a control: the same machine with one pod's thinking cost set high scores it lower;
- each reallocation, redone from the inputs in its event, gives the same moves; rebuilding the
  state from the ledger gives the same cash, positions, capital and stages.

## Plan
1. Law: `capital:` in config (firm capital, seed, cadence, limits, ladder thresholds).
2. A made-up market a run can live in: a provider serving given daily bars (under the same
   look-ahead guard as every feed).
3. Pure parts: `app/capital/allocation.py` (scores → moves) and the ladder (drawdown → stage).
4. Physics: `app/capital/service.py` — open the centre, seed, ladder, reallocate; run on every
   clock advance, before the order sweep (one lock across the advance); forced sales by physics through the order system; pod
   stage written to the ledger and the pod row; rebuild re-derives it.
5. Order system: a reduce-only pod's buy and any order of a closed pod are refused (403 + event);
   pending orders are cancelled at the cut.
6. The pod's mandate: what its rule wants held today (the rule engine, unchanged law), turned into
   orders a scripted PM sends through `POST /orders`.
7. `GET /capital` (the allocation table) + its MCP tool. An ADR for the new rules.
Left out (slices b, c): hiring a replacement PM, real minds in the machine, firm-level drawdown
limits, per-position limits, a review that lifts reduce-only, the live (non-backtest) scheduler.

## Risk
Money, the order system and market data: red-team + auditor before merge.

## Progress
- cycle 47: planned.
- cycle 48: built — law, made-up market, algorithm + ladder, the machine on every advance, order
  limits, mandate, GET /capital, ADR-049; the demo passes (2 s); suite green. Next: red-team, auditor.
- cycle 48 (cont.): the red-team's 8 holes fixed; the auditor's two blocks (copies earning a second
  seed) fixed by a copy check as each seed is paid; third pass clean; merged.
