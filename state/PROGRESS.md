Cycle 0048 · building: capital follows results (the multi-manager machine, first slice) · branch: idea/capital-machine
Done this session:
- The centre opens with the firm's capital the first time a pitch is eligible; an eligible pitch
  earns a seed at the next day; long-short rules are refused a seed (the order system cannot short).
- On every backtest clock advance the machine runs: the drawdown ladder (5% halves, 7.5% only
  sells, 10% closes and sells everything), seeds, and every 5 days an algorithm re-weighs capital
  by each pod's forward record (net of thinking cost, per unit of risk, cut for copying an older
  pod and for drawdown). Every move is an event with its inputs; rebuild restores capital and stages.
- The order system refuses a reduce-only pod's buy and any order of a closed pod (403, logged).
- A made-up market a run can live in; a pod's mandate (its rule's orders today); GET /capital.
- Demo passes in 2 s; full suite green.
Next: red-team (foreground) on main...idea/capital-machine, fix highs; then the auditor; merge.
Watch out: the algorithm targets are share-of-pool, so a small firm can cut a pod (law, not bug);
the demo's numbers were tuned once (stronger planted edge) — the checks were not loosened.
Demo: passes.
