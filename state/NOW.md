# A real PM researches a strategy, pitches it, and the app's validation gates give a verdict the Human can read

## How I understand it
Before a pod gets capital, its PM must pitch a strategy, and the strategy must pass checks on data
it was not tuned on. In this first slice the strategy is a **rule** (data, not code): "rank the
universe by 20-day momentum, every 5 days hold the top 2, long only". Deterministic code in the app
runs the rule over any stretch of bars, so anyone can rerun it on any period or world.

The PM (and its analysts) may run **research backtests** of rules, as many as they like, but only
on history older than a held-out window, and every one is counted for the pod, forever. Then the PM
**pitches**: the economic idea, the data needed, the rule, the team and budget asked. The app runs
the rule on the held-out window (still in the past: no look-ahead) and the gates judge it:
- **IC**: mean rank correlation between the rule's scores and what happened next, with the number
  of predictions (IC 0.03 on many predictions is good, on few it is not);
- **Deflated Sharpe**: the Sharpe ratio penalised by the pod's true number of attempts (every
  research backtest and every pitch), so trying 200 things and pitching the best one is seen;
- **Capacity**: the capital at which trading costs (square-root impact against the bars' volume)
  eat half the edge;
- **Correlation** with the other pods' pitched strategies on the same window (none yet: null);
- the **hypothesis** is recorded but not judged by the app (no LLM in physics; a later debate does).
The verdict is "eligible" or not. No capital is granted yet (that is the allocation idea).
The Human reads every pitch and its gate table.

## What done looks like
`uv run python acceptance/pitch_gates.py` ($0, offline):
1. Controls: the gates are fed histories made in the script. A planted-signal market passes every
   gate; pure noise fails; the same planted strategy counted as 1 attempt passes the deflated
   Sharpe and as 200 attempts fails it; a thin market fails capacity; a copy of another pod's
   strategy fails correlation. Each gate says yes once and no once.
2. The recorded real PM session replays IDENTICAL at $0 and prints the pitch: hypothesis, rule,
   every research backtest (attempts counted) and the gate table with each number and PASS/FAIL/null.

## Plan
1. `app/strategy/rule.py`: the strategy-v1 language (signals: momentum, mean reversion, low
   volatility; lookback, rebalance every k days, top n, long only / long-short, gross) and its
   pure evaluation: bars → daily returns, scores, forward returns, trades.
2. `app/strategy/gates.py`: pure gate engine; thresholds in `config.yaml` (`gates:`), never in code.
3. `fund-env gates`: run the engine on a bars file (the demo's controls go through it).
4. Permissions (research: pm + analyst, own pod; pitch: pm, own pod; read: own pod, management all).
5. `POST /research/backtests`, `POST /pitches`, `GET /pitches`, `GET /pitches/{id}` + MCP tools;
   events `research_backtest_run`, `pitch_submitted`, `pitch_judged` (no table: read from the ledger).
6. ADR: the strategy language and the gate law.
7. `specs/pitch-desk/`: one real PM, a small key; one recorded session; the demo replays it.
Left out: agent code in a sandbox, backtest operator, bull/bear debate, capital, IC per regime.

## Risk
Physics: new permissions, new endpoints reading market data, a real spend run → red-team + auditor
before merge.

## Progress
- cycle 45: plan, acceptance demo, the rule language and the gate engine.
