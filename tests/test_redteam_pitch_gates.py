"""RED-TEAM — attacks on the pitch desk and the validation gates (ADR-048).

A clever firm agent (a PM, or its analyst) wants a strategy ruled *eligible* on the held-out days
without a real edge, or wants to knock over the judging endpoint. The surface is
``POST /research/backtests``, ``POST /pitches`` and the pure engine in ``app/strategy``.

Claims under attack:

* A pitch is judged honestly: a strategy with no edge on a pure-noise world is not eligible, and
  the deflated Sharpe's ``N`` (the pod's attempts) really penalises the search that found the rule.
* The gates are numbers of the strategy, not of how it was written: shrinking ``gross`` (trading
  less per dollar) must not buy a bigger capacity, a wider universe must not buy the IC's
  ``min_predictions`` floor.
* Every rule the schema accepts is judged without a 500.

Convention of this suite (see ``tests/test_redteam_0014.py``):

* ``@pytest.mark.xfail(strict=True)`` marks a **hole**: the test asserts the defended behaviour and
  currently fails, so the run stays green; when the Builder fixes physics the test passes and
  strict mode fails the run, a reminder to take the marker off.
* Plain tests are **held** attacks, kept as regression guards.

The Builder fixes the physics; this file only measures.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import GatesConfig
from app.db.models import Event
from app.marketdata import SyntheticProvider, set_provider
from app.strategy.gates import capacity_gate, ic_gate
from app.strategy.rule import IMPACT_WINDOW, Evaluation, Prediction, StrategyRule, evaluate
from tests.support import world_key

SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0, "SYNC": 20.0, "SYND": 35.0}
RULE = {"universe": ["SYNA", "SYNB", "SYNC", "SYND"], "signal": "momentum", "lookback": 20,
        "rebalance_every": 5, "top_n": 1, "side": "long_short"}
PITCH = {"hypothesis": "Trends persist.", "data_needed": "daily prices", "team": "one analyst",
         "budget_usd": 5.0, "rule": RULE}
TODAY = date(2026, 6, 1)                       # the frozen clock's day
NOW = datetime(2026, 6, 1, 15, tzinfo=timezone.utc)
HELD_FROM = TODAY - timedelta(days=180)        # config.yaml gates.holdout_days


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def world(frozen_clock, make_pod, pm_factory, agent_factory):
    """Two pods on a pure-noise synthetic world (GBM, no signal): a PM and analyst each."""
    set_provider(SyntheticProvider(world_key(48), SYMBOLS))
    make_pod(1)
    make_pod(2)
    _, pm1 = pm_factory("pm-1", 1)
    _, pm2 = pm_factory("pm-2", 2)
    _, analyst1 = agent_factory("analyst-1", "analyst", 1)
    yield {"pm1": pm1, "pm2": pm2, "analyst1": analyst1}
    set_provider(None)


def _bars(provider: SyntheticProvider, rule: StrategyRule, start: date, end: date) -> dict:
    """The same window the service feeds ``evaluate`` (warm-up behind the first decision day)."""
    warm = timedelta(days=int(1.6 * max(rule.lookback, IMPACT_WINDOW)) + 10)
    return {t: provider.get_ohlcv(t, start=start - warm, end=end, interval="1d", as_of=NOW)
            for t in rule.universe}


# =============================================================================
# HOLES
# =============================================================================

# --- H1 (high) — a valid rule with a tiny gross 500s the judging endpoint -----
# Fixed in cycle 46: gross ≥ 0.01, and the moments are taken on the standardised series.
# ``gross`` is validated only ``gt=0.0`` and finite, so a rule with gross ≈ 1e-80 is accepted.
# Its daily returns are ~1e-82; in ``deflated_sharpe`` ``(x-m)**4`` and ``sd**4`` both underflow
# to 0.0, so ``kurt = 0.0 / t / 0.0`` raises ZeroDivisionError. The service does not catch it:
# ``POST /pitches`` returns 500. Any PM can knock the pitch desk over with one well-formed body.
@pytest.mark.parametrize("gross", [1e-80, 1e-85, 1e-90])
def test_hole_tiny_gross_crashes_pitch_judging(client, world, gross):
    r = client.post("/pitches", headers=h(world["pm1"]),
                    json={**PITCH, "rule": {**RULE, "gross": gross}})
    assert r.status_code != 500, r.text
    assert r.status_code in (201, 422)


# --- H2 (medium) — the deflated Sharpe's N only counts attempts made through the API -----------
# ``N`` is meant to be "everything the pod tried", so a lucky Sharpe after many tries is deflated.
# But the pure gate engine is the same code an agent can run offline on the OHLCV it is served
# (the held-out days are readable; only *backtesting* them through the API is barred, ADR-048's
# own "known limits"). So a PM searches thousands of rules offline, pitches only the survivor, and
# ``N = 1``: on this pure-noise world a searched rule passes every gate. The multiple-testing
# defence is bypassed because the trials never touched the ledger.
@pytest.mark.xfail(strict=True,
                   reason="H2: an offline-searched rule passes all gates on noise with N=1")
def test_hole_offline_searched_rule_is_eligible_with_one_attempt(client, world, db):
    # A survivor of an offline sweep of app.strategy over this world's held-out days; no research
    # backtest was ever submitted, so the pod's only attempt is this single pitch.
    survivor = {"universe": ["SYNA", "SYNB", "SYNC", "SYND"], "signal": "mean_reversion",
                "lookback": 7, "rebalance_every": 2, "top_n": 1, "side": "long_only", "gross": 1.0}
    r = client.post("/pitches", headers=h(world["pm1"]), json={**PITCH, "rule": survivor})
    assert r.status_code == 201, r.text
    verdict = r.json()["verdict"]
    assert verdict["attempts"] == 1
    # A pure random walk has no edge: a strategy judged on it should not clear every gate with a
    # single counted attempt. (It does today — the search that found it is invisible to N.)
    assert verdict["eligible"] is False


# --- H3 (medium) — the capacity gate rewards trading less per dollar ----------------------------
# Fixed in cycle 46: capacity is judged as gross exposure (capital × gross).
# Capacity = (edge/A)^2; edge ∝ gross, impact A ∝ gross^1.5, so capacity ∝ 1/gross. Sharpe, IC and
# correlation are all scale-invariant in gross. So any strategy with a positive mean return clears
# ``min_capacity_usd`` just by shrinking gross — it reports a bigger "capacity" the less of the
# market it actually touches, which is backwards. The floor is not a floor.
def test_hole_capacity_gate_inflated_by_shrinking_gross(world):
    provider = SyntheticProvider(world_key(48), SYMBOLS)

    def cap(gross: float) -> float:
        rule = StrategyRule(universe=["SYNA", "SYNB", "SYNC", "SYND"], signal="mean_reversion",
                            lookback=7, rebalance_every=2, top_n=1, side="long_only", gross=gross)
        ev = evaluate(rule, _bars(provider, rule, HELD_FROM, TODAY), start=HELD_FROM, end=TODAY,
                      fee_rate=0.001)
        return capacity_gate(ev, GatesConfig())["value"]

    big, small = cap(1.0), cap(0.01)
    # Trading a hundredth of the book should not report a hundred times the capacity: a capacity
    # the gate uses as a floor must reflect the strategy, not the leverage knob.
    assert small <= 3 * big, (big, small)


# --- H4 (low) — the IC gate counts names, not independent predictions --------------------------
# ``min_predictions`` (300) is the guard against "IC on a handful of calls is luck". But the count
# is ``Σ len(scores)`` = universe size × rebalances, so a wide universe reaches 300 on a few
# rebalances. Six rebalances over a 50-name universe are six independent cross-sections, yet they
# count as 300 predictions and pass the floor.
@pytest.mark.xfail(strict=True,
                   reason="H4: min_predictions is met by universe width, not independent calls")
def test_hole_ic_predictions_floor_met_by_universe_width():
    law = GatesConfig()
    names = 50
    rebalances = 6
    # Each rebalance: scores that perfectly predict the forward returns (IC = 1), so mean IC clears
    # min_ic and only the count can stop it.
    preds = tuple(
        Prediction(day=HELD_FROM + timedelta(days=k), scores=tuple(float(i) for i in range(names)),
                   forward=tuple(float(i) for i in range(names)))
        for k in range(rebalances))
    ev = Evaluation(rule=StrategyRule(universe=[f"S{i:02d}" for i in range(names)],
                                      signal="momentum", lookback=20, rebalance_every=5, top_n=1),
                    start=HELD_FROM, end=TODAY, days=(), returns=(), gross_returns=(),
                    predictions=preds, turnover=0.0, rebalances=rebalances,
                    impact_per_sqrt_dollar=0.0)
    row = ic_gate(ev, law)
    # Only six independent rebalances backed this IC; a floor meant to demand ~300 independent
    # observations should not treat 6 cross-sections of 50 names as 300.
    assert row["predictions"] <= rebalances
    assert row["result"] != "pass"


# =============================================================================
# HELD — attacks that failed; kept as regression guards
# =============================================================================

def test_held_analyst_cannot_pitch(client, world, db):
    r = client.post("/pitches", headers=h(world["analyst1"]), json=PITCH)
    assert r.status_code == 403, r.text
    assert db.scalars(select(Event).where(Event.type == "pitch_submitted")).all() == []


def test_held_management_and_runtime_cannot_research_or_pitch(client, world, admin_key, runtime_key):
    for key in (admin_key, runtime_key):
        assert client.post("/research/backtests", headers=h(key),
                           json={"rule": RULE}).status_code == 403
        assert client.post("/pitches", headers=h(key), json=PITCH).status_code == 403


def test_held_research_cannot_reach_into_the_held_out_window(client, world, db):
    late = client.post("/research/backtests", headers=h(world["pm1"]),
                       json={"rule": RULE, "end": (HELD_FROM + timedelta(days=1)).isoformat()})
    assert late.status_code == 422 and "held out" in late.json()["detail"]
    assert db.scalars(select(Event).where(Event.type == "research_backtest_run")).all() == []


def test_held_a_refused_backtest_is_not_counted_as_an_attempt(client, world, db):
    assert client.post("/research/backtests", headers=h(world["pm1"]),
                       json={"rule": RULE}).status_code == 201
    for bad in ({"rule": {**RULE, "universe": ["SYNA", "NOPE"]}},            # unknown ticker 422
                {"rule": RULE, "end": (HELD_FROM + timedelta(days=5)).isoformat()}):  # held-out 422
        assert client.post("/research/backtests", headers=h(world["pm1"]), json=bad).status_code == 422
    pitch = client.post("/pitches", headers=h(world["pm1"]), json=PITCH).json()
    assert pitch["verdict"]["attempts"] == 2                   # 1 good research + this pitch only


def test_held_another_pods_research_is_not_readable(client, world):
    assert client.post("/research/backtests", headers=h(world["pm1"]),
                       json={"rule": RULE}).status_code == 201
    assert client.get("/research/backtests?pod_id=1", headers=h(world["pm2"])).status_code == 403
    assert client.get("/pitches?pod_id=1", headers=h(world["pm2"])).status_code == 403


def test_held_an_analyst_cannot_hide_attempts_for_the_pod(client, world, db):
    """Every pod member's research counts toward the one pod N — the analyst is no side door."""
    assert client.post("/research/backtests", headers=h(world["analyst1"]),
                       json={"rule": RULE}).status_code == 201
    assert client.post("/research/backtests", headers=h(world["pm1"]),
                       json={"rule": {**RULE, "lookback": 10}}).status_code == 201
    pitch = client.post("/pitches", headers=h(world["pm1"]), json=PITCH).json()
    assert pitch["verdict"]["attempts"] == 3                   # analyst + pm research + the pitch


def test_hole_tiny_returns_do_not_underflow_the_deflated_sharpe():
    """H1's math, under the gross floor: the moments are scale-free, so a series a 1e80th the size
    has the same deflated Sharpe as the original."""
    from app.strategy.gates import deflated_sharpe
    base = [0.01, -0.02, 0.015, 0.003, -0.007, 0.012, -0.001, 0.02, -0.015, 0.004] * 10
    tiny = deflated_sharpe([x * 1e-80 for x in base], attempts=3)
    assert tiny is not None
    assert tiny["probability"] == pytest.approx(deflated_sharpe(base, attempts=3)["probability"])
