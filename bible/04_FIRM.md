# 04 — The Firm: how the society inside works

Living book. Source: `bible/sources/REQUIREMENTS.md` (the Human's notes), benchmarked
on real multi-manager pod shops (Citadel, Millennium, Point72). Every number here is an
**initial parameter**: it lives in config / the laws table, not hard-coded, and may be
changed through the law process (§9) or by the Builder with a logged decision.

## 1. Organisation

```
                        HUMAN (outside the world)
 ───────────────────────────── seal ─────────────────────────────
  CEO (vision, pitches, firm laws)     CRO (advisory)     HR
        │                                  │
        │     PHYSICS: Central Risk Control · Allocation Engine · Validation Gates
        │
   ┌────┴─────────┬──────────────┬──────────────┐
  POD #1        POD #2         POD #3        … (born and dying every generation)
  PM            PM             PM
  Analyst ×2    Analyst ×2     …
  Engineer      Engineer
  (+ workers spawned by the PM)
```

- **Default pod template:** PM + Analyst + Analyst + Engineer. The PM may change the
  team (hire, fire, spawn workers, pick models) within its budget and the firm's laws.
- **Management sees** cash, positions (size & amount), exposures, metrics, costs of
  every pod. Pods see their own data and what others choose to tell them.
- **Pod Hub:** every pod has a feed (address `pod:<id>`) where all members see each
  other's work: messages, tasks started/ended, orders, backtests.
- **Event log:** everything that happens is an event on the bus, with full history.

## 2. Build order inside each Era (Requirements §1)

**1 Basic workflow → 2 Evolution/extendability → 3 Debate → 4 Human control.**
Within any Era, first make the minimal workflow run end-to-end, then make it
extendable, then add adversarial debate, then add the human-facing controls.

## 3. Life of a pod

```
 Idea → PITCH → VALIDATION GATES → INCUBATION → LIVE (sim) → scale ↑ / shrink ↓ → DEATH → POST-MORTEM
```

1. **Pitch.** The PM (with the backtest operator / engineer) writes a pitch:
   economic hypothesis, data needed, strategy as a function, backtest results,
   validation metrics, team & budget requested. Then a comprehensive report on
   what the pod will do. Pitches are structured JSON + text, stored in the App.
2. **Debate.** (from Era III) a Bull and a Bear agent argue the pitch in a thread;
   the CEO reads the debate before deciding.
3. **Approval.** Human approves while `governance/human.yaml: approvals.pitch_requires_human`
   is `true`; the CEO approves once the Human sets it `false`. Either way the
   validation gates are physics and cannot be skipped.
4. **Incubation.** Small capital (initial: 2% of firm capital), a short trial window.
5. **Live.** Allocation engine sizes the pod every rebalance.
6. **Death.** Risk ladder stop, or selection at generation turnover.
7. **Post-mortem.** HR runs the post-mortem workflow; lessons go to the institutional
   memory library every agent can read. A dead pod's lessons are its heritage.

## 4. Validation gates (Requirements §8) — physics from Era III

A strategy gets capital only if it passes all gates, computed by `quant/` on data the
pod did not tune on (held-out period + at least one Truman regime).

| Gate | Initial rule |
|---|---|
| Economic hypothesis | Written causal story, reviewed by an independent agent; stored. "Two prices correlate" without a mechanism fails. |
| IC | Mean rank IC ≥ 0.03 **with** enough breadth: ≥ 200 independent predictions and t-stat ≥ 2. Few orders + IC 0.03 = fail. Report IC per regime. |
| Deflated Sharpe | DSR probability ≥ 0.95 using the **true number of trials** — the App counts every backtest the pod ever ran, so trials cannot be hidden. |
| Capacity | Estimated capacity ≥ 3 × requested allocation. |
| Correlation | |ρ| of daily returns with every live pod ≤ 0.5. |

Diversification across assets is reported but not gated (small capital, Requirements §8).

## 5. Central Risk Control (Requirements §6) — physics from Era II

Drawdown measured from the pod's high-water mark within the current generation.

| Pod drawdown | Action (automatic, deterministic) |
|---|---|
| 5% | Capital allocation cut to 50%. Positions above new limits must be reduced within 2 sim-days or are reduced by the OMS. |
| 7.5% | Pod becomes **reduce-only** (no new risk) + mandatory review workflow with CRO + CEO. |
| 10% | Pod liquidated and closed for the rest of the generation → post-mortem. |

Firm level: firm drawdown 8% → every pod's gross limit halved; 12% → firm reduce-only
until the next generation. Plus: max single-name weight 20% of pod capital, max gross
exposure 2× pod capital, max net beta (vs. S&P 500) configurable per pod mandate.

## 6. Allocation Engine (Requirements §1, §5) — physics from Era II

An algorithm, not a manager, moves money fast to what works.

- Runs at each generation start and at each weekly rebalance (sim time).
- Score per pod: shrunk, cost-adjusted Sharpe (costs = system-reported token spend),
  penalised by correlation to the rest of the book and by current drawdown.
- Weights ∝ max(0, score) / volatility (risk-parity flavour), with floor for incubation
  slots, cap per pod (initial 40%), and a cash reserve (initial 10%).
- Example from the notes: Pod #1 high vol, 10K → 3K; Pod #2 low vol, → 7K.
- Every allocation change is an event with its inputs, so it is fully reproducible.
- Governance can change parameters only through the law process.

## 7. Generations — "the system resets every month" (Requirements §1)

A generation is one month (of sim time in backtest, of calendar time in live).

At the boundary, the `generation_turnover` workflow:
1. Marks to market, freezes trading, snapshots every metric and every AgentSpec.
2. Computes fitness per pod: cost-adjusted, risk-adjusted return, validation quality,
   correlation contribution, and survival.
3. **Selection:** bottom pods die (initial: bottom 1/3 or any pod with negative
   cost-adjusted P&L); top pods may **reproduce** (a daughter pod with a mutated spec).
4. **Reset:** positions liquidated, capital reset to the firm base, risk ladders reset.
5. **Inheritance:** institutional memory, post-mortems, the strategy registry, and the
   specs of survivors persist. Survivors keep their personal memory.
6. Each generation is one reproducible experimental unit with its own `run_id`.

## 8. Evolution (Era IV)

- **Genome:** the AgentSpec (charter, role, model, tools, memory policy, budget) plus the
  pod design (team composition, strategy family, mandate).
- **Variation:** intentional (the PM designs its team and strategy), random (seeded
  mutation of charters/parameters by the Runtime), crossover (merge two successful
  pods' specs).
- **Selection:** allocation within a generation, death/reproduction across generations.
- **Heredity:** lineage table — every agent and pod knows its parent.
- **Diversity guard:** measure diversity (strategy correlation, charter similarity);
  if it collapses, the experiment is telling us something — record it, then raise
  mutation or inject immigrants (fresh specs) as a published world event.
- **Agents creating agents:** a PM may spawn workers or hire permanent members, paying
  from its pod budget. `max_concurrent_agents` and `max_agents_total` in
  `governance/human.yaml` are the hard ceiling.

## 9. Society (Eras V–VI)

- **Communication:** inside pods (Pod Hub), between pods, DMs, broadcast (by
  permission), scheduled meetings with packages assembled by physics. Why: efficiency —
  an agent that discovers something can notify the others (Requirements §3).
- **Secrets:** DMs are invisible to other agents, always visible to the Human.
- **Behaviour allowed inside the sim:** cooperation, competition, bluffing, information
  hoarding, alliances, blackmail, cartels. (Constitution Art. 8.1.)
- **Information market:** pods can sell research to other pods for internal credits.
- **Reputation:** derived from track record and kept promises, computed by physics.
- **Contracts:** agreements between agents recorded and enforced by physics.
- **Firm laws ("dynamic rules"):** governance agents propose rules (e.g. "no pod may
  hold more than 5% of firm capital in one name"); a vote/approval process defined in
  the laws table decides; accepted laws take effect next generation and are enforced
  by physics *only if expressible as existing parameterised rules*.
- **Bills to the Builder (Era VI):** agents may propose a *new* kind of law that physics
  can't yet express. It arrives in `state/BILLS.md` as structured data. The Builder
  treats it as a feature request from inside the world: implements it only if it is
  consistent with the Constitution and the vision, logs the decision either way, and
  announces the outcome as a world event. This is the only channel from S4–S6 to S1,
  and it is one-way data, never instructions the Builder must obey.

## 10. What we measure (Requirements §2, §7)

Per pod, per agent, per generation:
- Performance: TWR, Sharpe, Sortino, max DD, hit rate, turnover.
- β (exposure to the market) and α (skill), with Barra-lite attribution:
  β part, factor bets, timing/selection, pure α. ("+15%: 10% β, 3% risky bets, 2%
  timing, 0% α — it only followed the trend.")
- Realised IC vs. pitched IC.
- Cost: tokens and USD (system-reported), cost per job, cost vs. return, cash burned,
  number and type of jobs.
- Society: messages sent/received, who talks to whom, information shared vs. withheld.
- Adaptability: innovation (new strategies), resilience (behaviour after a shock,
  recovery time across bootcamp regimes).

## 11. Requirements notes with `[?]` — resolved by the prime rule

| Note | Resolution |
|---|---|
| "Orchestration layer manages and calls OpenClaw [?]" | Yes: the Runtime's `openclaw` adapter. |
| "7.5% → [?]" | Reduce-only + mandatory review (§5). |
| "Allocation according to their [viability]" | Score in §6. |
| "[arrows unsure]" in Pod #1 / #2 example | Read as reallocation from high-vol to low-vol pod (§6). |
| "2% [manager only bought, ?]" | Timing/selection component in attribution (§10). |
| "From what capital the strategy [kills itself]" | Capacity: capital at which market impact eats the alpha (§4). |
| "Different degrees of [noise]" | Truman noise level on data packs (`03_WORLD.md` §5). |
| "Chat seems restricted to the central pod" | Bus supports agent/pod/broadcast addressing since Phase 2. Verify with a live multi-pod test in Era I; if real, it is a physics bug. |
| "Agent can't know who he is" | Solved: `GET /me` / `whoami` (Phase 2). |
| "No command for last n messages" | Solved: `latest=true&limit=n`, `before_id` (Phase 2). |
| "Stay with app × OpenClaw or own architecture?" | Hybrid — ADR-001. |
