# Next: capital follows results (planned, not started)

## How I understand it
The firm is a multi-manager hedge fund: the centre holds the capital, the pods hold the ideas.
Today a PM can pitch a strategy and the gates can call it eligible, but no money moves. Next, an
eligible pitch earns a small seed and its pod trades its rule forward, on days that have not
happened yet. An algorithm (not an agent) moves capital every few days toward the pods that earn
the most per unit of risk and cost, and away from pods that copy each other or are falling. The
drawdown ladder is physics: 5% down from the pod's best → capital halved; 7.5% → it may only
shrink its positions; 10% → the pod is closed and its capital goes back to the centre.

## What done looks like
`uv run python acceptance/capital_machine.py` ($0, offline): made-up pods on a synthetic market.
The planted edge's capital grows, noise stays small, a copy is penalised, a bleeder is halved,
frozen (its buy is refused) and closed, the good pod is never cut, and rebuilding from the
ledger gives the same allocations.

## Plan
Written by the build session that starts it (branch idea/capital-machine). Queue notes:
`state/missions.json` entry `capital-machine`.

## Risk
Money and the order system: red-team + auditor before merge.

## Progress
- cycle 47: planned.
