Cycle: 0037 · Mission: none active (plan session) · Branch: main
Done so far: cycle 37 = the re-foundation plan. `state/missions.json` holds 6 ready missions
(M-001 metered month → M-002 one-file proof object → M-003 OpenClaw certified → M-004 holes closed
→ M-005 Truman shock → M-006 risk ladder). ADR-043 records the queue and why Era II starts while
Era I's real-mind criteria wait on Q-0001. Backlog items mapped to missions (BACKLOG.md header).
Next: build session → start M-001 (`protocol/CYCLE.md` §2): set it active, branch
`mission/M-001-metered-month`, architect plans it (Gate 2), write `acceptance/M-001.py` and see it fail.
Watch out: the real `governance/human.yaml` cap stays null. M-001's numeric cap exists only as an
injected `Governance` (`runtime/gate.py` `decide_wake_under`), never through the CLI. The guard blocks
any Bash command whose text names `governance/`: use Read for HALT checks.
Acceptance: n/a (no mission active)
