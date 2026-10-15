# Metering v1, the Runtime half (M-001, ADR-044)

What shipped: a two-mind pod can live a month on a fake **metered** provider; the system, not the
mind, says what each mind spent, and — once the run's one sync has posted it — the pod's cost and
rank come from that number. (Until that sync a leaderboard read still uses self-reports: a known
hole, routed to M-004, ADR-044.)

```
uv run python acceptance/M-001.py     # starts its own App; ~5 s; prints the evidence, ends ACCEPTED
```

## The path of a dollar

`specs/metered-month/*.yaml` (provider `fake-metered`, `budget_usd: 20`) →
`vet` (gate asked as if the key existed; Σ budgets ≤ cap) → `provision` (register the agent, then
mint its key at the `FakeProvisioner`, limit = budget) → `run_backtest` (key is its agent's;
Σ limits ≤ cap *now*, every step) → `wake(meter=…)` (the gate is told a key exists) →
`FakeMeteredProvider.complete` (script reply; `fake_charge`; `Meter.charge`, all or nothing) →
after the last step `sync_costs` posts each key's cumulative total as the Runtime identity →
`cost_metered` events (a trailing block) → `GET /metering/agents`, the leaderboard, `/metrics/pod/N`.

## Decisions and why (ADR-044)

- **A numeric cap only by rebinding the law file in-process.** The CLI can never be handed a cap, so
  the Human's `null` cannot be routed around; the acceptance runs the same specs under the real law
  and checks the refusal leaves the ledger untouched.
- **`fake-metered` is one closed name** (a no-network class), told to physics as `scripted`.
- **Limits are checked three times**: `vet` (Σ budgets ≤ cap, and each ≤ the physics maximum),
  `create_key` (each limit ≤ the maximum) and the conductor before every wake (Σ limits ≤ the cap as
  read now), because the conductor accepts minds from callers and the cap can change under a run.
- **Per run, not per month.** Two runs could each spend up to the cap. Harmless with a fake; required
  before any real key.
- **The self-report stays visible** (`self_reported_usd`, `self_report_gap_usd`) as the cross-check
  and, once the keys are synced, does not enter the authoritative cost.

## What was deliberately not done

A real provider/provisioner; replaying a metered run (`--cassette` is refused; the compare-ledgers
law for the trailing block is sketched in ADR-044 §6, owned by the mission that replays one);
persistence of the fake provisioner; metering through OpenClaw; the O(n²) scan; B-000k/n, B-022.
