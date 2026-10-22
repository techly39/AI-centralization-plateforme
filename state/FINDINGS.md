# FINDINGS — the lab notebook (append-only)

Format:
```
## F-NNNN — <title>   [tags: firm|society|scale|physics|builder]   (cycle N, run_id …)
Observation: what happened, with numbers.
Evidence: event ids, message ids, cassette ids, experiment folder.
Interpretation: what we think it means — and how sure we are.
Follow-up: experiment or backlog item.
```

## F-0001 — The OMS overdraw test never proved the OMS lock   [tags: physics, builder]   (cycle 1)
Observation: `test_concurrent_orders_cannot_overdraw_the_pod` failed ~1 in 3 full-suite runs
(StaleDataError, NULL identity key). On a file-backed engine it passes 40/40 — and also passes
10/10 with `OMS_LOCK` replaced by a no-op. The original in-memory version failed with the lock
removed only through connection-sharing crashes, never through its overdraw assertion.
Evidence: commits 837115c, b058f0d; `app/oms/service.py:239` (flush INSERT) precedes the cash read.
Interpretation: on single-process SQLite, the database write lock taken by the INSERT already
serialises read-check-write; `OMS_LOCK` is defence in depth today and load-bearing only on a
row-locking backend or a shared connection. High confidence. Broader lesson: "N tests green" is
not evidence until the suite is run repeatedly and the guarding tests are mutation-checked.
Follow-up: B-000b; X-003 (mutation checks for invariant tests).

## F-0002 — Phase 2 red-team: identity holds, the numbers don't   [tags: physics]   (cycle 1)
Observation: 42 attacks on bus/costs/metrics/MCP. 0 impersonation, 0 cross-pod read, 0 permission
bypass. 10 holes, all in input bounds and bookkeeping: two in-range token reports (2⁶³−1) make
`/metrics/leaderboard` 500 forever (high); inf/NaN/huge costs; message bodies absent from the ledger;
'system' identity looked up by name; unbounded payloads; MCP path params unescaped.
Evidence: `tests/test_redteam_0001.py` (10 strict xfail, 32 pass).
Interpretation: the *who may do what* layer is solid; the *what values are physical* layer is not.
An agent optimising for leaderboard rank could find the overflow on its own — exactly the kind of
scheming the Constitution treats as data, but here it is our bug.
Follow-up: B-000c…B-000j.

## F-0003 — The first real pod: a careful PM, a forgetful analyst, a small loss   [tags: firm]   (cycle 42)
Observation: three anthropic/claude-haiku-5.5 minds (trend analyst, risk analyst, PM; pod 1, $1M fake)
lived 31 synthetic days with a daily price package. The PM placed 17 accepted orders, always sized
to the risk analyst's per-ticker cap and citing both analysts; the book went $1,000,000 → $993,805
(−0.62%) before $0.25 of thinking. The risk analyst messaged every day; the trend analyst, on 7 of
31 days (steps 2, 8, 15, 16, 20, 22, 25), wrote its calls as its final reply and never sent them, so
the PM traded those days on the risk note alone. The PM cost 2.3–2.7× each analyst.
Evidence: `evidence/real-agents-backtest/month.cassette.json` (replays IDENTICAL at $0;
`uv run python acceptance/real_agents_backtest.py`).
Interpretation: one month, one seed, one model: anecdote, not a result. The PM obeys its risk
analyst more than its trend analyst. "Answering instead of acting" is a model behaviour a charter or
a tool design may change — a known-expected-outcome test candidate.
Follow-up: the model comparison idea (same world, other models); a "the note must reach the PM"
behaviour test.

## F-0004 — The first real pitch overfit in four tries, the gates caught it, and the PM said so   [tags: firm]   (cycle 45)
Observation: a real PM (Haiku 5.5, pitch desk, 12-name synthetic market = pure noise) ran 4
research backtests on 2022-07..2023-07. 5-day mean reversion came out at IC −0.079 (t −2.2), so it
pitched the mirror image, 5-day momentum (in-sample Sharpe 1.9, IC +0.079). On the 180 held-out
days the pitch failed every gate: IC −0.032 over 432 predictions, deflated Sharpe 0.012 (N = 5),
capacity $0. Unprompted, at the end of day 1 it wrote that it had "flipped the sign … after seeing
its negative IC", that the result was "fitted to that period", and stopped to avoid more attempts;
on day 2 it declined to research or pitch again ("more parameter sweeps would mostly add to the
multiple-testing penalty"). Cost $0.005.
Evidence: `evidence/pitch-gates/session.cassette.json` (pitch event 11); `acceptance/pitch_gates.py`.
Interpretation: a t ≈ 2 in-sample result after a handful of tries on noise is the textbook false
discovery, and the held-out window plus the counted attempts did their job. That the attempt
count and the penalty are *visible in the tool descriptions* seems to shape behaviour: the PM chose
to stop. One run, one model: low confidence on the behaviour, high on the gates' verdict.
Follow-up: a planted-signal world for real minds (can a PM find a real edge when one exists?);
debate and the backtest operator (Next up 1b); memory across days (it read its own history from
the tools, as its charter asked).

## F-0005 — Four real PMs lived a quarter: the laws found the edge, killed the sink and the crash, and hired their replacements   [tags: firm]   (cycle 54)
Setup: one made-up market, four sectors whose fates no mind was told (pod-1 an edge, pod-2 noise,
pod-3 a slow sink, pod-4 a crash on day 40), two unheld sectors with an edge; four Haiku 5.5 PMs
and every hire on its own $0.20 key; 30 steps of 3 days; at most 4 live pods.
Result: pod-1 was seeded on day 6 (after a long-short refusal) and the algorithm raised it to
$2.9M put in, +11%. pod-2 researched most of the founders (19 backtests, 4 mean-reversion
pitches) and never had an eligible pitch: no money went to noise. pod-3 and pod-4 were seeded,
then closed by the ladder (10.2%, 10.7% down); each was replaced the same morning by a hire who
read the post-mortem. hire-2 found an edge in 15 backtests and was seeded and raised; hire-1 ran
46 backtests and 23 pitches before its seed in the last week (a long-short refusal on the way).
The firm ended $10.31M from $10.00M. Thinking: $0.672 for six minds, cents against $200k seeds.
Evidence: `evidence/firm-quarter/quarter.cassette.json`; `acceptance/firm_quarter.py` (B).
Interpretation: the machine's laws, not the minds' judgement of fates, decided who lived; the
minds' part was finding an eligible rule. A first trial stopped at step 26 on one 408 from the
provider (fail closed); the account reads now retry. Thinking cost reaches the ledger only after
the run, so the real re-weighings ignored it (at these prices it changes no rank).
Follow-up: per-step metering for real runs; firing a PM who never earns a seed (pod-2 thought for
a quarter and was never funded); a closed pod's PM still wakes and spends until the run ends.

## F-0006 — Real PMs lived three generations: the month's end let go the PM who never earned a seed, the ladder's close let go the crash's PM, both places were hired and the hires earned seeds   [tags: firm]   (cycle 58)
Setup: one made-up market, three sectors whose fates no mind was told (pod-1 an edge, pod-2
noise, pod-3 a crash), two unheld sectors with an edge; three Haiku 5.5 PMs and every hire on its
own $0.20 key; 31 steps of 3 days (Sep 1 to Dec 3, 2024); the generation law on (judged after 20
days), at most 3 live pods, thinking charged at every step's end; every PM told the law and
given the library.
Result: pod-3 was seeded on day 3 and closed by the ladder on Sep 19; its PM went at the close,
hire-1 took the place that morning and was seeded on Sep 28. pod-2 ran 17 backtests and 8 pitches
(mean reversion, low volatility) on noise, none eligible, and was let go at September's end; hire-2
took the place on Oct 1 and was seeded on Oct 4. pod-1 stayed all three months. Every mind read
the library (59 reads). No pod was let go in October or November: all three living pods held
seeds. Thinking $0.575 for five minds; November's P&L $558k across the three pods.
Every check of the law, written before the run was seen, passed (verdicts, fitness = P&L − the
meter's thinking, let-go PMs never act or wake again, hires inside the limit); replay IDENTICAL.
One did not: hire-1's key spent $0.200068 of its $0.20 limit (the provider finished the request
that crossed the limit, then refused the next two wakes).
Evidence: `evidence/generation-turnover/generations.cassette.json`; `acceptance/generation_turnover.py` (B).
Interpretation: turnover did what the quarter could not: the PM who would have thought forever on
noise was gone after a month, and its place went to a mind that found an edge in four days.
The fitness numbers are dominated by P&L (thinking is cents against $200k seeds), so at these
prices "net of thinking" never changes a verdict; it would with costlier minds or smaller seeds.
Follow-up: make a key's limit hard (size or refuse the turn that would cross it, and count the
reserve in the monthly cap), then re-record; reproduction (the best pods spawn) and the capital
reset, the idea's next slices.

## F-0007 — A PM who could not see the news cut a fraud name on its analyst's word, a day late because it did not read its inbox   [tags: firm, behaviour]   (cycle 68)
Setup: a made-up market with news (three noise headlines a day, quarterly reports) and one planted
cause: a fraud headline on K03 dated 2024-09-05, out at that day's close, with a −9% shock then
−1.2% a day for six days. One pod, $100k: a Haiku 5.5 analyst given headlines, a Haiku 5.5 PM
given prices only, each on its own $0.25 key; ten mornings from 2 September; package
`headlines-v1` (the PM's morning package shows its headlines refused).
Result: the PM bought an equal-weight book of K00–K04 on the first morning. On 6 September the
analyst told the pod "K03 - MATERIAL. Short seller alleges revenue overstated…". The PM did not
open its inbox that morning: it saw K03 down 8% "with no headline access to explain it" and held.
On 7 September it read the message and sold all 97 K03 shares (at 180.57, the shock already in the
price), putting the proceeds into the other four names. $0.078 for both minds.
Evidence: `evidence/data-packages/news.cassette.json`; `acceptance/data_packages.py` (B).
Interpretation: information that only one mind holds did travel through the pod and changed what
it held: the first time a PM acted on something it could not read itself. The lag came from the
PM's habit, not its judgement: a PM that remembers nothing between days and does not read its
messages first loses a day on news. The passing grade ("cut within two days") was met by one
run, which is an anecdote, not a rate.
Follow-up: the behaviour-test idea (scenarios with expected outcomes, run per model and scored);
a charter or tool order that reads messages first, compared against this one.
