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
1. Law: `hiring:` in config (max live pods, model pool taken in turn, budget per hire, charter
   text), frozen into the first vacancy of the run.
2. Physics: on close the capital machine writes `vacancy_opened` with the post-mortem and the hire
   the law names (pod and PM names, model, budget, charter). `GET /vacancies`, `GET /vacancies/{id}`
   (management, or the PM hired into it), `POST /vacancies/{id}/fill` (a registrar: makes the pod
   and the PM, returns its key once; refused, in the ledger, at the pod limit or if already
   filled), `POST /vacancies/{id}/refuse` (the Runtime: "the budget does not fit the cap"). Each
   with its MCP tool.
3. The post-mortem: a pure function of the ledger at the close (the rule and its hypothesis, the
   forward days, the ladder's steps with their drawdowns, the capital in and out), frozen in the
   vacancy.
4. Runtime ("Onboarding.exe"): before each step's wakes the conductor reads the open vacancies,
   checks the hire's budget against the cap with every live key, fills, mints the key, adds the
   mind from that step on, its first wake handed the post-mortem. The cassette records the hire;
   replay rebuilds the same roster.
5. Record one real run (a few cents of the cap), commit it under `evidence/pod-replacement/`.
Cut: session 1 = steps 1-3 and demo part A through the API; session 2 = step 4 and a hosted world
whose market can kill a pod; session 3 = the real run, red-team, auditor, merge.
Left out: a manager mind who chooses the hire; firing a PM who never earns a seed (deadline);
lessons library across generations; per-position and firm-level limits.

## Risk
Money, agent creation, key minting under the cap, the Runtime's gate: red-team + auditor before
merge. Holes it stands on (fix inside): a mid-run mint must hold the mint lock and fit the cap
with every live key; a pod can read its correlation from its own score row (the new PM reads
/capital: judge whether that matters once a real mind reads it).

## Progress
- cycle 49: planned.
- cycle 50: built all of it but the real run: the vacancy, the hire, the post-mortem and the pod
  limit (physics); `GET /mandate`; the Runtime hiring mid-run (`--hire`), recorded and replayed;
  a made-up market a hosted world can be built from. Demo A and B0 pass ($0); next: red-team,
  then the real recorded hire, then the auditor.
- cycle 51: red-team's 3 holes fixed. First real hire found a gap: a refused seed was invisible
  to the PM (it re-pitched 8 times); pitches now show the capital answer. Re-recorded: the PM read
  the refusal, went long-only, was seeded and trades. Auditor blocked once (a hire known from a
  free-text label), fixed; second pass PASS. Merged.
