"""The capital machine (idea: capital follows results): the allocation algorithm and the ladder
(pure), the made-up market, the order system's limits, the sweep, the rebuild and ``GET /capital``.
The end-to-end proof is ``acceptance/capital_machine.py``."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.capital import service as capital_service
from app.capital.allocation import PodTrack, climb, drawdown, reallocate, score, stage_for
from app.capital.service import book, sweep
from app.config import CapitalConfig
from app.db.models import Event, Pod
from app.ledger.events import EVENT_PITCH_JUDGED, EVENT_PITCH_SUBMITTED, append_event
from app.ledger.rebuild import rebuild_state
from app.marketdata import Bar, BarsProvider, LookAheadError, UnknownTickerError
from app.metrics.performance import EquityPoint, daily_returns
from app.oms import force_sell
from app.oms.errors import RoleNotPermittedError
from app.registry.service import get_or_create_system_agent
from app.strategy.rule import StrategyRule, holding

LAW = CapitalConfig()
DAYS = tuple((date(2025, 1, 1) + timedelta(d)).isoformat() for d in range(60))


def track(pod_id: int, returns, *, seeded: int | None = None, equity: float = 200_000.0,
          stage: str = "active", cost: float = 0.0, dd: float = 0.0) -> PodTrack:
    return PodTrack(pod_id=pod_id, seeded=seeded or pod_id, stage=stage, equity=equity,
                    days=DAYS[: len(returns)], returns=tuple(returns), cost_usd=cost, drawdown=dd)


def edge(n=60, mean=0.004):
    return [mean + 0.004 * math.sin(1.7 * k) for k in range(n)]


def noise(n=60, phase=0.0):
    return [0.005 * math.sin(2.3 * k + phase) for k in range(n)]


# --- the algorithm ---------------------------------------------------------------------------------

def test_a_score_needs_enough_forward_days_and_some_variation():
    short = score(track(1, edge(LAW.min_track_days - 1)), [], LAW)
    assert short["viability"] is None and "fewer than" in short["note"]
    flat = score(track(1, [0.0] * 30), [], LAW)
    assert flat["viability"] is None and "no variation" in flat["note"]
    assert score(track(1, edge()), [], LAW)["viability"] > LAW.raise_at


def test_a_copy_is_penalised_never_the_older_pod_it_copies():
    original, copy = track(1, edge(), seeded=1), track(2, edge(), seeded=2)
    rows = {r["pod_id"]: r for r in reallocate([copy, original], centre_cash=9e6, law=LAW)["pods"]}
    assert rows[1]["corr"] is None and rows[1]["viability"] > LAW.raise_at
    assert rows[2]["corr_with"] == 1 and rows[2]["corr"] == pytest.approx(1.0)
    assert rows[2]["viability"] == pytest.approx(0.0, abs=1e-6)
    assert rows[1]["move"] > 0 and rows[2]["move"] <= 0.0   # a perfect copy is worth nothing more
    unrelated = track(2, [r + 0.004 for r in noise(phase=1.0)], seeded=2)
    rows = {r["pod_id"]: r for r in reallocate([original, unrelated], centre_cash=9e6,
                                               law=LAW)["pods"]}
    assert rows[2]["corr"] < 0.5


def test_cost_and_drawdown_lower_the_score():
    base = score(track(1, edge()), [], LAW)
    assert score(track(1, edge(), cost=0.0), [], LAW)["viability"] == base["viability"]
    assert score(track(1, edge(), cost=20_000.0), [], LAW)["viability"] < base["viability"]
    assert score(track(1, edge(), dd=0.05), [], LAW)["viability"] == pytest.approx(
        base["viability"] * 0.5)


def test_moves_are_bounded_and_follow_the_law():
    pods = [track(1, edge(), seeded=1), track(2, noise(), seeded=2),
            track(3, [-r for r in edge()], seeded=3),
            track(4, edge(), seeded=4, stage="reduce_only", equity=150_000.0)]
    result = reallocate(pods, centre_cash=9e6, law=LAW)
    rows = {r["pod_id"]: r for r in result["pods"]}
    assert rows[1]["move"] == pytest.approx(LAW.max_raise * 200_000)        # one step at most
    assert 0 < rows[2]["viability"] < LAW.raise_at and rows[2]["move"] == 0  # not sure yet: holds
    assert rows[3]["move"] == pytest.approx(-100_000.0)                     # toward the floor
    assert rows[4]["move"] <= 0                                             # reduce-only: no raise
    assert result == reallocate(list(reversed(pods)), centre_cash=9e6, law=LAW)  # order-free
    # The floor lifts both targets above what the centre holds: the most viable is paid first.
    floored = CapitalConfig(min_pod_usd=250_000.0, max_pod_share=1.0)
    two = [track(1, edge(mean=0.003), seeded=1),
           track(2, [0.0045 + r for r in noise(phase=1.0)], seeded=2)]
    poor = {r["pod_id"]: r for r in reallocate(two, centre_cash=30_000.0, law=floored)["pods"]}
    assert poor[2]["target"] == poor[1]["target"] == 250_000.0
    assert poor[2]["viability"] > poor[1]["viability"] > LAW.raise_at
    assert (poor[2]["move"], poor[1]["move"]) == (30_000.0, 0.0)
    capped = reallocate([track(1, edge(), equity=2_500_000.0)], centre_cash=7.5e6, law=LAW)
    assert capped["pods"][0]["move"] == pytest.approx(LAW.max_pod_share * 10e6 - 2.5e6)
    floor = reallocate([track(1, [-r for r in edge()], equity=104_000.0)], centre_cash=9e6,
                       law=LAW)
    assert floor["pods"][0]["move"] == 0.0             # within min_move of the floor: no churn


def test_the_ladder_climbs_and_never_comes_down():
    assert drawdown([0.1, -0.05]) == pytest.approx((1.045, 1.1, 0.05))
    assert [stage_for(x, LAW) for x in (0.0, 0.05, 0.075, 0.1)] == [
        "active", "halved", "reduce_only", "closed"]
    assert climb("reduce_only", 0.0, LAW) == "reduce_only"
    assert climb("active", 0.2, LAW) == "closed"
    with pytest.raises(ValueError, match="climb"):
        CapitalConfig(halve_at=0.1, close_at=0.05)


def test_returns_with_flows_at_the_start_of_the_day():
    curve = [EquityPoint(date(2025, 1, 1), 0.0), EquityPoint(date(2025, 1, 2), 202.0, 200.0),
             EquityPoint(date(2025, 1, 3), 99.0, -101.0)]
    assert daily_returns(curve, flows_at="start") == pytest.approx([0.01, 99.0 / 101.0 - 1])
    assert daily_returns(curve) == pytest.approx([(99.0 + 101.0) / 202.0 - 1])
    with pytest.raises(ValueError):
        daily_returns(curve, flows_at="noon")


# --- the made-up market and the rule's holding ---------------------------------------------------

def bars(closes: list[float], first: date = date(2025, 1, 1)) -> list[Bar]:
    return [Bar(ts=datetime.combine(first + timedelta(k), datetime.min.time(), UTC), open=c,
                high=c, low=c, close=c, volume=1e6) for k, c in enumerate(closes)]


def test_a_bars_market_serves_nothing_before_it_ended():
    market = BarsProvider({"XA": bars([10.0, 11.0, 12.0, 13.0])})
    noon = datetime(2025, 1, 3, 12, tzinfo=UTC)
    assert market.get_price("XA", as_of=noon).price == 11.0          # Jan 2's close
    served = market.get_ohlcv("XA", start=date(2025, 1, 1), end=date(2025, 1, 10), interval="1d",
                              as_of=noon)
    assert [b.close for b in served] == [10.0, 11.0]
    with pytest.raises(LookAheadError):
        market.get_ohlcv("XA", start=date(2025, 1, 1), end=date(2025, 1, 10), interval="1d",
                         as_of=datetime(2024, 12, 1, tzinfo=UTC))
    with pytest.raises(UnknownTickerError):
        market.get_price("XB", as_of=noon)
    other = BarsProvider({"XA": bars([10.0, 11.0, 12.0, 13.5])})
    assert market.world()["bars_fingerprint"] != other.world()["bars_fingerprint"]
    assert "13.0" not in str(market.world())
    with pytest.raises(ValueError):
        BarsProvider({"XA": bars([10.0, -1.0])})


def test_a_rules_holding_is_its_latest_rebalance_counted_from_the_start():
    rule = StrategyRule(universe=["XA", "XB", "XC"], signal="momentum", lookback=2,
                        rebalance_every=3, top_n=1)
    up, down = [10.0 + k for k in range(12)], [30.0 - k for k in range(12)]
    flat_then_up = [10.0] * 9 + [11.0, 13.0, 16.0]
    held = holding(rule, {"XA": bars(up), "XB": bars(down), "XC": bars(flat_then_up)},
                   start=date(2025, 1, 3))
    assert held.day == date(2025, 1, 12) and held.rebalanced_on == date(2025, 1, 12)
    assert held.weights == {"XA": 0.0, "XB": 0.0, "XC": 1.0}
    earlier = holding(rule, {t: bars(c[:11]) for t, c in
                             (("XA", up), ("XB", down), ("XC", flat_then_up))},
                      start=date(2025, 1, 3))
    assert earlier.rebalanced_on == date(2025, 1, 9) and earlier.weights["XA"] == 1.0
    warm = holding(rule, {t: bars(c[:2]) for t, c in (("XA", up), ("XB", down),
                                                      ("XC", flat_then_up))},
                   start=date(2025, 1, 1))
    assert set(warm.weights.values()) == {0.0}     # not lookback days yet: flat


# --- the order system's limits -------------------------------------------------------------------

def test_a_reduce_only_pod_may_sell_but_not_buy_and_a_closed_pod_trades_nothing(client, desk, db):
    pod_id, _, key = desk
    order = {"ticker": "AAPL", "qty": 10, "price_type": "market", "justification": "test"}
    assert client.post("/orders", headers={"X-API-Key": key},
                       json={**order, "side": "buy"}).status_code == 201
    db.get(Pod, pod_id).status = "reduce_only"
    db.commit()
    refused = client.post("/orders", headers={"X-API-Key": key}, json={**order, "side": "buy"})
    assert refused.status_code == 403 and "reduce-only" in refused.json()["detail"]
    assert client.post("/orders", headers={"X-API-Key": key},
                       json={**order, "side": "sell", "qty": 5}).status_code == 201
    db.get(Pod, pod_id).status = "closed"
    db.commit()
    assert client.post("/orders", headers={"X-API-Key": key},
                       json={**order, "side": "sell", "qty": 5}).status_code == 403
    denied = db.scalars(select(Event).where(Event.type == "permission_denied")).all()
    assert len(denied) == 2


def test_only_physics_sells_by_force(db, desk, prices):
    pod_id, pm_id, _ = desk
    from app.db.models import Agent
    with pytest.raises(RoleNotPermittedError):
        force_sell(db, pod_id=pod_id, ticker="AAPL", qty=1, actor=db.get(Agent, pm_id),
                   reason="x", provider=prices)


# --- the sweep, the rebuild, the table -----------------------------------------------------------

def _pitch(db, pod_id: int, *, eligible: bool, side: str = "long_only") -> int:
    rule = {"language": "strategy-v1", "universe": ["AAPL", "MSFT"], "signal": "momentum",
            "lookback": 2, "rebalance_every": 1, "top_n": 1, "side": side, "gross": 1.0}
    submitted = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=None,
                             payload={"pod_id": pod_id, "rule": rule})
    append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=None,
                 payload={"pitch_id": submitted.id, "pod_id": pod_id, "eligible": eligible})
    db.commit()
    return submitted.id


def test_the_machine_does_nothing_until_a_pitch_is_eligible(db, frozen_clock, make_pod, prices):
    make_pod(1)
    _pitch(db, 1, eligible=False)
    assert sweep(db, provider=prices) is None
    assert book(db)["law"] is None
    assert not db.scalars(select(Event).where(Event.type.like("capital%"))).all()


def test_an_eligible_pitch_is_seeded_once_and_a_long_short_one_is_refused_once(
        db, frozen_clock, make_pod, prices):
    make_pod(1)
    make_pod(2)
    pitch = _pitch(db, 1, eligible=True)
    _pitch(db, 2, eligible=True, side="long_short")
    done = sweep(db, provider=prices)
    assert done["seeded"] == [1] and len(done["refused"]) == 1
    _pitch(db, 1, eligible=True)                       # a later pitch of a seeded pod: no seed
    again = sweep(db, provider=prices)
    assert again["seeded"] == [] and again["refused"] == []
    state = book(db)
    assert state["pods"][1]["pitch_id"] == pitch and state["pods"][1]["allocated"] == LAW.seed_usd
    assert state["centre_cash"] == LAW.firm_capital_usd - LAW.seed_usd
    assert 2 not in state["pods"]


def test_rebuild_restores_the_pods_capital_and_stage(db, frozen_clock, make_pod, prices):
    make_pod(1)
    _pitch(db, 1, eligible=True)
    sweep(db, provider=prices)
    append_event(db, type="pod_stage_changed", actor_agent_id=None,
                 payload={"pod_id": 1, "from": "active", "to": "reduce_only"})
    pod = db.get(Pod, 1)
    pod.status, pod.current_allocation = "active", 0.0      # a row out of step with the ledger
    rebuild_state(db)
    assert (pod.status, pod.current_allocation) == ("reduce_only", LAW.seed_usd)


def test_a_pod_reads_its_own_row_and_management_the_whole_table(
        client, db, frozen_clock, make_pod, pm_factory, admin_key, prices, monkeypatch):
    # Both pods pitch the same rule for brevity; the copy check at the seed is not under test here
    # (tests/test_redteam_capital.py tests it).
    monkeypatch.setattr(capital_service, "_copy_check", lambda *a, **kw: None)
    make_pod(1)
    make_pod(2)
    _, pm1 = pm_factory("pm-1", 1)
    _pitch(db, 1, eligible=True)
    _pitch(db, 2, eligible=True)
    sweep(db, provider=prices)
    mine = client.get("/capital", headers={"X-API-Key": pm1})
    assert mine.status_code == 200
    assert [r["pod_id"] for r in mine.json()["pods"]] == [1]
    assert mine.json()["centre_cash_usd"] is None and mine.json()["law"]["halve_at"] == 0.05
    assert client.get("/capital?pod_id=2", headers={"X-API-Key": pm1}).status_code == 403
    table = client.get("/capital", headers={"X-API-Key": admin_key}).json()
    assert [r["pod_id"] for r in table["pods"]] == [1, 2]
    assert table["centre_cash_usd"] == LAW.firm_capital_usd - 2 * LAW.seed_usd
