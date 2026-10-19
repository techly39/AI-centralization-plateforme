Cycle 0047 · plan · next: capital follows results (the multi-manager machine, first slice) · branch: main
Done this session:
- Looked back: since the last plan, one idea finished (the pitch and the gates) in two sessions,
  one of them cut by the usage limit; every finished idea's demo still passes on main; no comments.
- Book made true: "a strategy is an isolated function" and "validation gates" are working (first slice).
- Next up re-ordered: the multi-manager machine comes before the debate. A pitch that passes the
  gates leads nowhere today, and a forward trial with a small seed on days that have not happened
  yet is how a real multi-manager works and cures the "held-out prices are readable" hole.
- Queued `capital-machine` (ready, 3 sessions, risk tier): seed for eligible pitches, pods trade
  their rule forward through the order system, an algorithm re-weighs capital, the drawdown ladder
  halves / freezes / closes.
- Factory: a plan now fixes inside the next idea any known hole that idea stands on.
Next: build session: branch idea/capital-machine, write state/NOW.md and acceptance/capital_machine.py
(made-up pods: planted edge grows, noise stays small, a copy is penalised, a bleeder is halved,
frozen and closed, the good pod is never cut; rebuild from the ledger gives the same allocations).
Watch out: the order system has no reduce-only or closed-pod notion yet; `fund_pod` in
app/registry/pods.py already writes the allocation event. Launch red-team/auditor in the foreground.
Demo: none yet (planned).
