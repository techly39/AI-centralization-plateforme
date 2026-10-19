# A dead pod is replaced: when the risk ladder closes a pod, the firm hires a new PM, a real mind, who researches, pitches and can earn a seed

## How I understand it
High turnover is the heart of a multi-manager fund: a pod that bleeds is shut fast and a new PM is
hired to pitch in its place. Today the ladder closes a pod and that is the end of it. Now:
- When a pod is closed, physics opens a **vacancy** (an event naming the dead pod, why it died, and
  its record). A halved or frozen pod opens none.
- The firm's **hiring law** (`config.yaml`, frozen for the run like the capital law) says how many
  pods may live at once, the model pool a new PM is drawn from (in turn), its thinking budget and
  its charter. The law decides, not the Builder; a management mind choosing who to hire comes later.
- At the next morning, the onboarding program (the Runtime, "Onboarding.exe") fills the vacancy:
  a new pod, a new PM made from the hiring template, its own capped key minted inside the $50 cap.
  If the budget does not fit the cap, there is no hire, and the refusal is an event.
- The new PM's first morning hands it the **post-mortem** of the pod it replaces: the dead rule,
  its forward days, the drawdown that closed it. Then it lives like the pitch desk: researches
  (every backtest counted), pitches; an eligible pitch earns a seed at the next capital sweep and
  the new pod trades forward. An ineligible one earns nothing.
- The hire is in the recording, so the whole run, hire included, replays IDENTICAL for $0.

## What done looks like
`uv run python acceptance/pod_replacement.py` ($0, offline):
- A (scripted, a made-up market): a pod's market collapses; it is closed at 10% and one vacancy
  opens; a halved pod opens none. The vacancy is filled at the next morning by a new pod and PM;
  with a budget that does not fit the cap the hire is refused (event, no agent, no key). A scripted
  new PM that pitches the planted rule is seeded and trades; one that pitches noise is not. The
  live-pod limit holds. Rebuilding state from the ledger gives the same pods, agents and capital.
- B (recorded, a real Haiku 5.5 PM hired mid-run): `replay --verify` says IDENTICAL from the file;
  the ledger shows close → vacancy → hire → the post-mortem in its first wake → research → pitch →
  the gates' verdict → seed or no seed, consistent with the verdict. Its cost, charged by the
  system, is shown against its key.

## Plan
1. Law: `hiring:` in config (max live pods, model pool, budget per hire, charter template path).
2. Physics: on close the capital machine writes `vacancy_opened`; `GET /vacancies` + MCP tool;
   filling one (`POST /vacancies/{id}/fill`, management/registrar only) creates the pod and the
   agent in one event chain; rebuild re-derives it.
3. The post-mortem: a pure function of the ledger (rule, record, ladder steps), a data package.
4. Runtime: the conductor reads the vacancies each morning, provisions a mind from the hiring
   template (same checks as `provision`: cap, HALT, names), mints its key, adds it to the roster
   from that step on. The cassette records the hire; replay rebuilds the same roster.
5. Record one real run (a few cents of the cap), commit it under `evidence/pod-replacement/`.
Left out: a manager mind who chooses the hire; firing a PM who never earns a seed (deadline);
lessons library across generations; per-position and firm-level limits.

## Risk
Money, agent creation, key minting under the cap, the Runtime's gate: red-team + auditor before
merge. Holes it stands on (fix inside): a mid-run mint must hold the mint lock and fit the cap
with every live key; a pod can read its correlation from its own score row (the new PM reads
/capital: judge whether that matters once a real mind reads it).

## Progress
- cycle 49: planned.
