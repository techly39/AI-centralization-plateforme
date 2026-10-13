# REPORT for the Human — rewritten each planning session (≤ 1 page)

*Earlier reports (cycles 1–36) are in git: `git show 1826a1b:state/REPORT.md`.*

## 2026-10-13 — Cycle 37: the first mission queue (Builder v2)

**What the world can do now.** A pod of two scripted minds (an analyst and a PM) can live a simulated
month through the Runtime. Every act goes through the app. The run can be recorded to a cassette and
replayed into a fresh database with the same ledger. Three of the seven Era I exit criteria are
ticked: no look-ahead, HALT stops a run within one tick, and no paid AI wakes without a budget.
**No AI model has acted yet.** That is by design: the firm budget (`monthly_llm_usd_cap`) is still
`null`.

**The next six missions.** Each one is something you can run and see.
1. **M-001 Metered month.** Every (fake) dollar a mind spends is charged by the system, not
   self-reported. Ticks exit criterion 4.
2. **M-002 One-file proof.** One recording file is enough to re-live a month and get the verdict
   "identical ledger" or "differs at step X".
3. **M-003 OpenClaw, certified.** The firm's agents are generated into their own isolated OpenClaw
   profile and checked by a conformance suite. An agent that fails is never woken. Ticks the static
   half of criterion 7. Your own OpenClaw agents are never touched.
4. **M-004 Holes closed.** Nine known small physics bugs fixed before real minds arrive.
5. **M-005 Market shock.** A scenario file crashes a market on a given day. The firm is told by an
   announcement, and the same scenario always replays the same way.
6. **M-006 Risk ladder.** A pod that loses 5% has its capital cut, at 7.5% it may only reduce
   risk, and at 10% it is closed. This is enforced by code, exactly. It is the first Era II criterion.

**Why Era II work starts before Era I is closed.** After missions 1–4, Era I's last three criteria
all need one month run by real AI models, and that needs a budget only you can set. I will not wait
idle (ADR-043), so missions 5–6 start Era II.

**What you could decide.**
- **Q-0001 (the one that matters):** set a small `firm.monthly_llm_usd_cap` when you are ready for
  the first real-model month. Until then, nothing in the firm spends money.
- Q-0005 / Q-0006 are still open. I chose answers so that work can continue, and each is reversible.

**The research I looked at, briefly.** Others have built "fork a simulation at round N" tools
(WhatIf, Inject/Fork/Compare). None of them replays the agents' own past answers exactly, so their
branches cannot isolate the one change. Our recorded replays can. I am keeping that "exact
counterfactual" experiment for after Era II (`bible/09_BUILDER_VISION.md` §3).
