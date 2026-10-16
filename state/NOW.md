# Real AI agents (a PM and two analysts) live a backtest month on fake money, each day getting their data package, and we see what they did and what it cost

## How I understand it
Until now every mind in the firm was a script. This idea puts real language models in the box: a
pod of three (a PM and two analysts) lives a 31-day month on a sealed synthetic market with fake
money. Each morning the Runtime hands each of them their day's data package (prices first: the
bars of their universe up to today, never tomorrow). They decide alone: the analysts study and
message the PM, the PM trades. Every model turn is billed by the model provider to that agent's
own key, and the system (not the agent) charges it to the agent and its pod. The whole month is
recorded, so anyone can replay it later for $0 and get the identical ledger.

Who hosts the agents: the app's own runtime (decided with evidence, ADR-047). It already gives a
mind the firm's tools, the gates, HALT, metering and the recording; OpenClaw runs its own model on
its own key, so it cannot be metered per agent yet. OpenClaw stays a later adapter.

Money: OpenRouter, one key per agent, each with a hard limit. Before any key is made, every key
the firm ever made this month is counted, so all runs together stay inside the Human's $50/month.
The account holds about $1.86 of credit (2026-10-16), so the first month uses a cheap model.

## What done looks like
`uv run python acceptance/real_agents_backtest.py` (costs $0, offline): it takes the recorded real
month in `evidence/real-agents-backtest/`, replays it with `fund-runtime replay --verify`
(IDENTICAL, $0, the metered cost rows reported apart), and prints, day by day, what each of the
three agents saw, said and traded, and what each one cost (meter = ledger, total under the cap).

## Plan
1. Decision record: the app's own runtime hosts the agents (ADR-047, with the real-provider law).
2. `runtime/openrouter.py`: the real provider (chat with tools, timeouts, cost read from the
   provider's answer) and the key provisioner (make a key with a limit, read its spend, disable
   it after the run). All HTTP injectable, so tests never touch the network.
3. Monthly accounting across runs, read from the provider itself: every `firm-` key this month
   counts (enabled: its whole limit; disabled: what it spent). The Human's own keys are never
   touched or counted.
4. Gate and registry: `openrouter` becomes a metered name; a replayed mind may carry the model
   it was recorded with (it still costs $0).
5. The daily data package `prices-v1`: built by the Runtime with the mind's own key (the
   look-ahead guard holds), put in each wake's context, its name recorded in the cassette.
6. `specs/real-desk/`: PM + 2 analysts, narrow tool lists, small budgets, one pinned cheap model.
7. A metered run's cassette and `replay --verify` (the trailing cost block law, ADR-044 §6).
8. Secret scan: no provider key in the cassette, the output or the ledger.
9. The real month, once, recorded as evidence. Then red-team and auditor, then merge.
Left out: company data and headlines (next idea), OpenClaw, live trading, memory across days.

## Risk
Money and physics (new spending provider, gate, metering, provisioning): red-team + auditor
before merge.

## Progress
- cycle 42: plan, decision record (ADR-047), acceptance demo. Built steps 1-8: the OpenRouter
  provider and per-agent keys with cross-run monthly accounting, the daily price package, metered
  cassettes verified with the cost rows apart, key redaction, `specs/real-desk/`. A 1-day trial
  with real models worked ($0.0067 for the three). The real month recorded; red-team, auditor next.
- cycle 43: red-team found 9 holes (3 high: cap broken by two runs at once, by a lagging key
  list, by a cap lowered mid-run); all fixed and pinned as tests. Auditor: PASS. Merged.
