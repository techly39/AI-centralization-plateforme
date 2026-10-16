"""strategy-v1 rules and the validation gates (app/strategy/): pure functions, no database."""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from app.cli import main as cli_main
from app.config import GatesConfig
from app.marketdata import Bar
from app.strategy.gates import (
    deflated_sharpe,
    expected_max_normal,
    judge,
    performance,
    spearman,
)
from app.strategy.rule import EvaluationError, StrategyRule, evaluate

D0 = date(2024, 1, 1)
LAW = GatesConfig(min_periods=10, min_predictions=10)


def bars_from(closes: dict[str, list[float]], volume: float = 1e6) -> dict[str, list[Bar]]:
    return {t: [Bar(ts=datetime.combine(D0 + timedelta(i), time(), UTC), open=c, high=c, low=c,
                    close=c, volume=volume) for i, c in enumerate(cs)] for t, cs in closes.items()}


def walk(seed: int, n: int = 300, tickers: int = 6) -> dict[str, list[float]]:
    rng = random.Random(seed)
    out = {}
    for k in range(tickers):
        p, cs = 100.0, []
        for _ in range(n):
            p *= math.exp(0.01 * rng.gauss(0, 1))
            cs.append(p)
        out[f"T{k}"] = cs
    return out


def rule(**kw) -> StrategyRule:
    base = {"universe": ["A", "B"], "signal": "momentum", "lookback": 2, "rebalance_every": 1,
            "top_n": 1}
    return StrategyRule(**{**base, **kw})


# --- the language ----------------------------------------------------------------------------

def test_rule_normalises_and_refuses_what_it_does_not_mean():
    assert rule(universe=["b", " a "]).universe == ["A", "B"]
    with pytest.raises(ValidationError):
        rule(code="import os")                     # unknown field: a rule says only what it says
    with pytest.raises(ValidationError):
        rule(universe=["A", "a"])                  # the same ticker twice
    with pytest.raises(ValidationError):
        rule(top_n=2, side="long_short")           # 2 long + 2 short do not fit in 2 names
    with pytest.raises(ValidationError):
        rule(gross=float("nan"))
    with pytest.raises(ValidationError):
        rule(universe=["A", ".."])


def test_long_short_with_one_each_side_is_allowed():
    assert rule(side="long_short").side == "long_short"


# --- the evaluation --------------------------------------------------------------------------

def test_hand_computed_momentum_long_only():
    # A rises then falls; B is flat. lookback 2: day 2 scores A +21 %, B 0 → hold A from day 2.
    b = bars_from({"A": [100, 110, 121, 100, 100], "B": [50, 50, 50, 50, 50]})
    e = evaluate(rule(), b, start=D0, end=D0 + timedelta(5), fee_rate=0.0)
    # days 0,1 have no 2-day history: flat. Day 2 → A (121→100), day 3: A -17.4 % vs B 0 → B.
    assert e.days == tuple(D0 + timedelta(i) for i in range(1, 5))
    assert e.returns[:2] == (0.0, 0.0)
    assert e.returns[2] == pytest.approx(100 / 121 - 1)
    assert e.returns[3] == 0.0
    assert e.turnover == pytest.approx(3.0)          # into A (1), then A → B (1 out + 1 in)
    assert e.rebalances == 4


def test_fees_are_charged_on_turnover():
    b = bars_from({"A": [100, 110, 121, 100, 100], "B": [50, 50, 50, 50, 50]})
    free = evaluate(rule(), b, start=D0, end=D0 + timedelta(5), fee_rate=0.0)
    paid = evaluate(rule(), b, start=D0, end=D0 + timedelta(5), fee_rate=0.01)
    assert sum(free.returns) - sum(paid.returns) == pytest.approx(0.01 * paid.turnover)


def test_no_look_ahead_a_later_bar_never_changes_an_earlier_result():
    closes = walk(1)
    r = StrategyRule(universe=list(closes), signal="momentum", lookback=10, rebalance_every=3,
                     top_n=2, side="long_short")
    end = D0 + timedelta(300)
    base = evaluate(r, bars_from(closes), start=D0 + timedelta(20), end=end, fee_rate=0.001)
    cut = 200
    future = {t: cs[:cut] + [c * 3 for c in cs[cut:]] for t, cs in closes.items()}
    moved = evaluate(r, bars_from(future), start=D0 + timedelta(20), end=end, fee_rate=0.001)
    upto = [i for i, d in enumerate(base.days) if d < D0 + timedelta(cut)]
    assert [base.returns[i] for i in upto] == [moved.returns[i] for i in upto]
    assert [p for p in base.predictions if p.day < D0 + timedelta(cut - 3)] == \
           [p for p in moved.predictions if p.day < D0 + timedelta(cut - 3)]


def test_bars_after_the_window_are_ignored():
    closes = walk(2)
    r = StrategyRule(universe=list(closes), signal="mean_reversion", lookback=5, rebalance_every=2,
                     top_n=2)
    end = D0 + timedelta(150)
    full = evaluate(r, bars_from(closes), start=D0 + timedelta(10), end=end, fee_rate=0.001)
    short = evaluate(r, bars_from({t: cs[:150] for t, cs in closes.items()}),
                     start=D0 + timedelta(10), end=end, fee_rate=0.001)
    assert full == short
    assert max(full.days) < end


def test_only_shared_days_count_and_missing_tickers_refuse():
    b = bars_from({"A": [1, 2, 3, 4], "B": [1, 2, 3, 4]})
    b["B"] = b["B"][::2]                            # B has days 0 and 2 only
    with pytest.raises(EvaluationError):
        evaluate(rule(), b, start=D0 + timedelta(1), end=D0 + timedelta(4), fee_rate=0)
    with pytest.raises(EvaluationError):
        evaluate(rule(universe=["A", "C"]), b, start=D0, end=D0 + timedelta(4), fee_rate=0)


def test_low_volatility_prefers_the_calm_name():
    rng = random.Random(3)
    calm = [100 * (1 + 0.001 * rng.gauss(0, 1)) for _ in range(40)]
    wild = [100 * (1 + 0.05 * rng.gauss(0, 1)) for _ in range(40)]
    e = evaluate(rule(signal="low_volatility", lookback=10, universe=["CALM", "WILD"]),
                 bars_from({"CALM": calm, "WILD": wild}), start=D0 + timedelta(15),
                 end=D0 + timedelta(40), fee_rate=0)
    assert all(p.scores[0] > p.scores[1] for p in e.predictions)


# --- the statistics --------------------------------------------------------------------------

def test_spearman_handles_ties_and_constants():
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(math.sqrt(3) / 2)
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_expected_max_grows_with_attempts():
    assert expected_max_normal(1) == 0.0
    values = [expected_max_normal(n) for n in (2, 10, 100, 1000)]
    assert values == sorted(values)
    assert expected_max_normal(1000) == pytest.approx(3.25, abs=0.1)


def test_deflated_sharpe_falls_with_attempts():
    rng = random.Random(4)
    r = [0.001 + 0.01 * rng.gauss(0, 1) for _ in range(500)]
    one, many = deflated_sharpe(r, 1), deflated_sharpe(r, 500)
    assert one["benchmark_daily"] == 0.0
    assert many["probability"] < one["probability"]
    assert deflated_sharpe([0.01] * 50, 1) is None     # no variance: no ratio


# --- the gates -------------------------------------------------------------------------------

def test_gates_are_null_on_too_little_history_and_the_verdict_is_portable_json():
    closes = walk(5, n=40)
    r = StrategyRule(universe=list(closes), signal="momentum", lookback=30, rebalance_every=5,
                     top_n=2)
    e = evaluate(r, bars_from(closes), start=D0 + timedelta(35), end=D0 + timedelta(40),
                 fee_rate=0.001)
    v = judge(e, attempts=3, others={}, law=GatesConfig())
    by = {g["gate"]: g for g in v["gates"]}
    assert by["deflated_sharpe"]["result"] == "null" and by["deflated_sharpe"]["value"] is None
    assert by["correlation"]["result"] == "null"
    assert v["eligible"] is False
    json.dumps(v, allow_nan=False)


def test_no_edge_means_no_capacity_and_flat_books_have_none_at_all():
    falling = {"A": [100 * 0.99**i for i in range(60)], "B": [100 * 0.98**i for i in range(60)]}
    e = evaluate(rule(lookback=2), bars_from(falling), start=D0 + timedelta(25),
                 end=D0 + timedelta(60), fee_rate=0.001)
    cap = {g["gate"]: g for g in judge(e, attempts=1, others={}, law=LAW)["gates"]}["capacity"]
    assert cap["result"] == "fail" and cap["value"] == 0.0
    flat = evaluate(rule(lookback=200), bars_from(falling), start=D0 + timedelta(25),
                    end=D0 + timedelta(60), fee_rate=0.001)
    cap = {g["gate"]: g for g in judge(flat, attempts=1, others={}, law=LAW)["gates"]}["capacity"]
    assert cap["result"] == "null" and flat.warnings


def test_correlation_compares_shared_days_only():
    closes = walk(6)
    r = StrategyRule(universe=list(closes), signal="momentum", lookback=10, rebalance_every=3,
                     top_n=2, side="long_short")
    e = evaluate(r, bars_from(closes), start=D0 + timedelta(20), end=D0 + timedelta(300),
                 fee_rate=0.001)
    same = judge(e, attempts=1, others={"pod-2": (e.days, e.returns)}, law=LAW)
    corr = {g["gate"]: g for g in same["gates"]}["correlation"]
    assert corr["result"] == "fail" and corr["value"] == pytest.approx(1.0)
    few = judge(e, attempts=1, others={"pod-2": (e.days[:5], e.returns[:5])}, law=LAW)
    corr = {g["gate"]: g for g in few["gates"]}["correlation"]
    assert corr["result"] == "null" and corr["against"] == {"pod-2": None}


def test_attempts_must_count_the_pitch_itself():
    closes = walk(7, n=50)
    e = evaluate(rule(universe=list(closes)), bars_from(closes), start=D0 + timedelta(5),
                 end=D0 + timedelta(50), fee_rate=0)
    with pytest.raises(ValueError):
        judge(e, attempts=0, others={}, law=LAW)
    assert performance(e)["days"] == len(e.returns)


# --- the command -----------------------------------------------------------------------------

def test_cli_gates_judges_a_bars_file(tmp_path, capsys):
    closes = walk(8)
    rows = {t: [[(D0 + timedelta(i)).isoformat(), c, c, c, c, 1e6] for i, c in enumerate(cs)]
            for t, cs in closes.items()}
    (tmp_path / "bars.json").write_text(json.dumps(rows))
    (tmp_path / "rule.json").write_text(json.dumps(
        {"universe": list(closes), "signal": "momentum", "lookback": 10, "rebalance_every": 5,
         "top_n": 2}))
    args = [str(tmp_path / "bars.json"), str(tmp_path / "rule.json"), "--start", "2024-02-01",
            "--end", "2024-10-01"]
    assert cli_main(["gates", *args, "--attempts", "4"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rule"]["language"] == "strategy-v1"
    assert {g["gate"] for g in out["gates"]} == {"ic", "deflated_sharpe", "capacity", "correlation"}
    assert next(g for g in out["gates"] if g["gate"] == "deflated_sharpe")["attempts"] == 4
    assert cli_main(["gates", *args, "--attempts", "0"]) == 2
    (tmp_path / "rule.json").write_text('{"universe": ["X", "Y"], "signal": "astrology"}')
    assert cli_main(["gates", *args]) == 2
