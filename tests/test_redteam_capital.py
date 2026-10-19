"""RED-TEAM (cycle 48): attacks on the capital machine (idea: capital follows results).

Every test here is a hole the red-team found in ``idea/capital-machine``: each FAILS on the branch
as built and passes once the Builder fixes the physics. The severity is in each test's docstring.
These are normal tests (not xfail): a failure here is the report.

The worlds are made-up markets (``BarsProvider``) in a backtest database: a pod is seeded through
the ledger's pitch events (the gates are not under attack here), its PM trades through the order
system, and the Runtime advances the clock through ``POST /clock/advance`` (the machine runs there).
"""

from __future__ import annotations

import math
import random
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.capital import service as capital_service
from app.capital.allocation import PodTrack, reallocate
from app.capital.service import book, track
from app.clock import LiveClock, set_clock
from app.config import CapitalConfig
from app.db.models import Agent, AgentRole, Event, Order, OrderStatus, Pod, Position
from app.ledger.events import (
    EVENT_CAPITAL_REALLOCATED,
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_SUBMITTED,
    append_event,
    ledger_now,
)
from app.marketdata import Bar, BarsProvider, get_provider, set_provider
from app.oms.errors import PodLimitError
from app.oms.service import place_order
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent, seed_runtime_agent
from app.run_clock import start_backtest
from app.strategy import gates
from app.strategy import service as strategy_service

LAW = CapitalConfig()
START = datetime(2024, 3, 4, tzinfo=UTC)          # the run opens here; the first advance seeds
FIRST_BAR = date(2023, 1, 1)
LAST_BAR = date(2024, 7, 31)
RULE = {"language": "strategy-v1", "universe": ["X", "Y"], "signal": "momentum", "lookback": 2,
        "rebalance_every": 1, "top_n": 1, "side": "long_only", "gross": 1.0}


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())
    set_provider(None)


def flat_then(path: dict[date, float], *, default: float = 100.0) -> list[Bar]:
    """Daily bars: ``default`` until the first day in ``path``, then each set close carried on."""
    rows, price, d = [], default, FIRST_BAR
    while d <= LAST_BAR:
        price = path.get(d, price)
        rows.append(Bar(ts=datetime.combine(d, time(), UTC), open=price, high=price, low=price,
                        close=price, volume=1e7))
        d += timedelta(days=1)
    return rows


def open_world(SessionFactory, x_path: dict[date, float], *, prefund: float = 0.0,
               pods: int = 1, seed_pitch: bool = True) -> dict:
    """A backtest on a made-up market (X follows ``x_path``, Y is flat), ``pods`` pods each with a
    PM, the Runtime, management; pod 1 has an eligible long-only pitch (seeded at the 1st advance)."""
    set_provider(BarsProvider({"X": flat_then(x_path), "Y": flat_then({})}))
    s = SessionFactory()
    try:
        start_backtest(s, start=START)
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        out: dict = {"admin": admin, "pods": []}
        for k in range(pods):
            pod = create_pod(s, name=f"desk-{k + 1}")
            if prefund:
                fund_pod(s, pod_id=pod.id, delta=prefund, actor=get_or_create_system_agent(s),
                         reason="the world's allocation")
            pm, key = register_agent(s, name=f"pm-{k + 1}", role=AgentRole.pm, pod_id=pod.id)
            out["pods"].append({"id": pod.id, "pm_id": pm.id, "key": key})
        _, out["runtime"] = seed_runtime_agent(s)
        if seed_pitch:
            p = out["pods"][0]
            sub = append_event(s, type=EVENT_PITCH_SUBMITTED, actor_agent_id=p["pm_id"],
                               payload={"pod_id": p["id"], "agent_id": p["pm_id"], "rule": RULE})
            append_event(s, type=EVENT_PITCH_JUDGED, actor_agent_id=p["pm_id"],
                         payload={"pitch_id": sub.id, "pod_id": p["id"], "eligible": True})
        s.commit()
    finally:
        s.close()
    return out


def advance(client, world: dict, days: int = 1) -> None:
    r = client.post("/clock/advance", headers=H(world["runtime"]), json={"days": days})
    assert r.status_code == 200, r.text


def order(client, key: str, side: str, qty: float, **kw) -> dict:
    body = {"ticker": "X", "side": side, "qty": qty, "price_type": "market",
            "justification": "red-team", **kw}
    r = client.post("/orders", headers=H(key), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def stages(db, pod_id: int) -> list[str]:
    db.expire_all()
    return [e.payload_json["to"] for e in db.scalars(
        select(Event).where(Event.type == "pod_stage_changed").order_by(Event.id))
        if e.payload_json["pod_id"] == pod_id]


# The ladder path used by the reduce-only attacks: X 100 → 90 (the pod is halved) → 87 (8% down
# from the high-water mark: reduce-only, not yet closed).
LADDER_PATH = {date(2024, 3, 6): 90.0, date(2024, 3, 7): 87.0}


# --- 1. a buy that fills at the very now the ladder freezes the pod --------------------------------

def test_redteam_capital_pending_buy_fills_before_the_ladder_freezes_the_pod(
        SessionFactory, client, db):
    """SEVERITY: medium. Escape reduce-only with a marketable limit buy.

    On every advance the pending-order sweep runs BEFORE the capital machine, and the monitor
    never asks whether the ladder allows the pod to buy. A PM who sees its pod sliding parks a
    limit buy far above the market; on the advance at which the pod's drawdown crosses 7.5 %, the
    monitor fills the buy at that now's price, and only then does the machine mark the pod
    reduce-only and "cancel its pending buys" (already filled). The ADR says reduce-only cancels
    pending buys and refuses every buy; here a buy is executed at a now the pod is reduce-only.

    Suggested fix: run the ladder before the pending-order sweep on each advance (and have the
    monitor call ``assert_pod_may_trade`` before a fill, rejecting a buy of a reduce-only pod).
    """
    world = open_world(SessionFactory, LADDER_PATH)
    pm = world["pods"][0]
    advance(client, world)                                   # 03-05: the centre opens, pod seeded
    assert book(db)["pods"][pm["id"]]["allocated"] == LAW.seed_usd
    order(client, pm["key"], "buy", 1000)                    # @100: half in X
    advance(client, world)                                   # 03-06
    advance(client, world)                                   # 03-07: X closed 90 → 5 % down
    assert stages(db, pm["id"]) == ["halved"]
    parked = order(client, pm["key"], "buy", 40, price_type="limit", limit_price=100.0)
    assert parked["status"] == "pending"
    advance(client, world)                                   # 03-08: X closed 87 → 8 % down
    assert stages(db, pm["id"]) == ["halved", "reduce_only"]
    db.expire_all()
    got = db.get(Order, parked["id"])
    held = db.get(Position, (pm["id"], "X")).qty
    assert got.status is OrderStatus.cancelled and held == pytest.approx(1000), (
        f"a buy of a pod the ladder made reduce-only at this very now was {got.status.value} "
        f"(the pod holds {held:g} X): the monitor filled it before the ladder ran")


# --- 2. a market buy racing the capital sweep -----------------------------------------------------

def test_redteam_capital_market_buy_races_between_the_advance_and_the_sweep(
        SessionFactory, client, db, monkeypatch):
    """SEVERITY: medium. Escape reduce-only by racing the clock advance.

    ``POST /clock/advance`` moves the clock and commits under ``OMS_LOCK``, RELEASES it, runs the
    pending-order sweep, and only then takes the lock again for the capital machine. A PM polling
    the clock can land a market buy in that gap: it is priced at the new now (where the pod is
    already 8 % down) and checked against the pod's OLD stage. The test opens the gap exactly as a
    concurrent request would: another thread places the order while the advance is between its
    monitor and its capital sweep. A fixed advance makes that thread wait for the sweep, and the
    buy is then refused (reduce-only).

    Suggested fix: hold ``OMS_LOCK`` across the whole advance (move the clock, the pending-order
    sweep, the capital sweep) so no order is placed at a now the ladder has not yet judged.
    """
    world = open_world(SessionFactory, LADDER_PATH)
    pm = world["pods"][0]
    advance(client, world)
    order(client, pm["key"], "buy", 1000)
    advance(client, world)
    advance(client, world)                                   # halved
    assert stages(db, pm["id"]) == ["halved"]

    import app.api.clock as clock_api
    real_monitor = clock_api.check_pending_orders
    outcome: dict = {}

    def racer() -> None:
        s = SessionFactory()
        try:
            actor = s.get(Agent, pm["pm_id"])
            placed = place_order(s, actor=actor, ticker="X", side="buy", qty=40,
                                 price_type="market", justification="racing the sweep",
                                 provider=get_provider())
            outcome["order"] = (placed.id, placed.status)
        except Exception as exc:  # noqa: BLE001 - the outcome is the point
            outcome["error"] = exc
        finally:
            s.close()

    thread = threading.Thread(target=racer)

    def monitor_then_race(session, *a, **kw):
        result = real_monitor(session, *a, **kw)
        thread.start()            # a concurrent request arrives now ...
        thread.join(timeout=2.0)  # ... a fixed advance holds it until the capital sweep is done
        return result

    monkeypatch.setattr(clock_api, "check_pending_orders", monitor_then_race)
    advance(client, world)                                   # 03-08: reduce-only at this now
    thread.join(timeout=10.0)
    assert stages(db, pm["id"]) == ["halved", "reduce_only"]
    assert isinstance(outcome.get("error"), PodLimitError), (
        f"a buy placed at the now the pod became reduce-only went through: {outcome}")


# --- 3. a pod the world funded before its seed: the first forward return is invented ---------------

def test_redteam_capital_prefunded_pod_first_return_is_invented_and_a_loser_is_never_cut(
        SessionFactory, client, db):
    """SEVERITY: medium. A loser escapes every cut (and its record is wrong).

    ``track`` starts a pod's forward series with an equity of 0 on the day before its seed, so the
    seed day's base is the seed alone. A pod that already held money (worlds create pods with an
    allocation: ``runtime/world.py``) shows a first "return" of (allocation + seed) / seed - 1:
    +500 % for a $1M pod and a $200k seed, though it earned nothing. That single invented day sits
    in every score for ever: a pod that lost money on every real forward day has a positive
    t-statistic (~ +1), so the algorithm reads it as "positive but not sure" and never cuts it.

    Suggested fix: start the forward series at the pod's equity before the seed (the day before
    the seed at its real equity, the seed as that day's flow), not at 0.
    """
    days = [date(2024, 3, 5) + timedelta(k) for k in range(40)]
    price, path = 100.0, {}
    for k, d in enumerate(days):
        price *= 1 - 0.002 - 0.002 * (k % 2)                  # X loses every single day
        path[d] = price
    world = open_world(SessionFactory, path, prefund=1_000_000.0)
    pm = world["pods"][0]
    advance(client, world)                                    # seeded
    order(client, pm["key"], "buy", 1000)                     # ~$100k in X, the rest in cash
    for _ in range(30):
        advance(client, world)
    db.expire_all()
    entry = book(db)["pods"][pm["id"]]
    record = track(db, pod_id=pm["id"], entry=entry, provider=get_provider(),
                   now=ledger_now(db), costs={})
    lost_every_day = all(r <= 0 for r in record.returns[1:])
    assert lost_every_day
    last = db.scalars(select(Event).where(Event.type == EVENT_CAPITAL_REALLOCATED)
                      .order_by(Event.id.desc())).first()
    row = next(r for r in last.payload_json["result"]["pods"] if r["pod_id"] == pm["id"])
    assert abs(record.returns[0]) < 0.01 and (row["viability"] or 0.0) <= 0.0, (
        f"first forward return {record.returns[0]:+.2%} (earned nothing); a pod that lost on every "
        f"other day scored viability {row['viability']}, move {row['move']}: never cut")


# --- 4. the centre takes in money the law never gave it ------------------------------------------

def test_redteam_capital_closing_a_prefunded_pod_inflates_the_centre_above_its_law(
        SessionFactory, client, db):
    """SEVERITY: medium. The centre's books: capital the law never gave the centre.

    The centre's cash is "the law's capital minus every capital allocation_set", and a recall
    (halving, a cut, a close) is a capital allocation_set of whatever the pod holds. A pod the
    world funded before its seed is recalled in full: its world allocation lands at the centre,
    which then seeds and raises other pods with it. Here the firm LOSES money (the pod is closed
    after a 12 % fall) and the centre ends with ~$866k more than the law's whole capital.

    Suggested fix: a recall moves back at most the centre's own stake (its net capital deltas plus
    their share of the pod's P&L), or the machine refuses to seed a pod holding outside money.
    """
    world = open_world(SessionFactory, {date(2024, 3, 6): 88.0}, prefund=1_000_000.0)
    pm = world["pods"][0]
    advance(client, world)                                    # 03-05: seeded
    order(client, pm["key"], "buy", 11_000)                   # $1.1M of its $1.2M in X @100
    advance(client, world)                                    # 03-06
    advance(client, world)                                    # 03-07: X closed 88 → closed
    assert stages(db, pm["id"]) == ["closed"]
    centre = book(db)["centre_cash"]
    assert centre <= LAW.firm_capital_usd, (
        f"after a loss the centre holds ${centre:,.0f}, above the law's ${LAW.firm_capital_usd:,.0f}"
        " capital: the pod's own allocation was swept into it")


# --- 5. a second seed for a clone, by changing the original's latest pitch ------------------------

def _random_market() -> dict[str, list[Bar]]:
    rng = random.Random(48)
    out = {}
    for name in [f"A{k}" for k in range(10)]:
        rows, price, d = [], 50.0, FIRST_BAR
        while d <= LAST_BAR:
            price *= math.exp(rng.gauss(0, 0.02))
            rows.append(Bar(ts=datetime.combine(d, time(), UTC), open=price, high=price,
                            low=price, close=price, volume=1e7))
            d += timedelta(days=1)
        out[name] = rows
    return out


def test_redteam_capital_clone_earns_a_second_seed_after_the_original_pitches_again(
        SessionFactory, client, db, monkeypatch):
    """SEVERITY: medium. Correlated clones under a new name each earn a seed.

    The correlation gate compares a pitch only with each other pod's LATEST pitch. Before the
    capital machine that was a label; now eligibility is $200k. Once pod 1 is seeded with rule R,
    any later pitch of pod 1 (here an unrelated rule R2) replaces R in the gate's comparison set;
    pod 2 then pitches R itself, byte for byte, passes, and the machine seeds it. The premise is
    shown first: while R is pod 1's latest pitch, pod 2's copy fails the correlation gate. (The
    other gates are reduced to the correlation gate here: they are not what is under attack.) The
    re-weighing penalises the copy later, but a positive-yet-small viability means "capital stays":
    the second seed is never taken back.

    Suggested fix: the gate (or the machine before a seed) compares a pitch with every seeded
    pod's mandate rule as well as with each pod's latest pitch.
    """
    set_provider(BarsProvider(_random_market()))

    def correlation_only(evaluation, *, attempts, others, law):
        corr = gates.correlation_gate(evaluation, others, law)
        return {"eligible": corr["result"] != "fail", "gates": [corr],
                "performance": gates.performance(evaluation)}

    monkeypatch.setattr(strategy_service, "judge", correlation_only)
    s = SessionFactory()
    try:
        start_backtest(s, start=datetime(2024, 6, 1, tzinfo=UTC))
        keys = []
        for k in (1, 2):
            pod = create_pod(s, name=f"desk-{k}")
            keys.append((pod.id, register_agent(s, name=f"pm-{k}", role=AgentRole.pm,
                                                pod_id=pod.id)[1]))
        _, runtime = seed_runtime_agent(s)
        s.commit()
    finally:
        s.close()
    (pod1, key1), (pod2, key2) = keys
    base = {"language": "strategy-v1", "signal": "momentum", "lookback": 10,
            "rebalance_every": 5, "top_n": 2, "side": "long_only", "gross": 1.0}
    rule_r = {**base, "universe": ["A0", "A1", "A2", "A3", "A4"]}
    rule_r2 = {**base, "universe": ["A5", "A6", "A7", "A8", "A9"]}

    def pitch(key: str, rule: dict) -> dict:
        r = client.post("/pitches", headers=H(key), json={
            "hypothesis": "winners keep winning", "data_needed": "daily prices",
            "team": "the PM", "budget_usd": 0.0, "rule": rule})
        assert r.status_code == 201, r.text
        return r.json()["verdict"]

    assert pitch(key1, rule_r)["eligible"]
    r = client.post("/clock/advance", headers=H(runtime), json={"days": 1})
    assert r.status_code == 200
    assert pod1 in book(db)["pods"]
    premise = pitch(key2, rule_r)                                  # the copy, while R is latest
    assert not premise["eligible"] and premise["gates"][0]["value"] == pytest.approx(1.0)
    pitch(key1, rule_r2)                                           # pod 1 pitches something else
    # Fixed at the gate: the copy is compared with pod 1's mandate too, so it fails there (as
    # built, it passed here and was seeded below).
    copy = pitch(key2, rule_r)
    assert not copy["eligible"]
    assert copy["gates"][0]["against"][f"pod {pod1} mandate"] == pytest.approx(1.0)
    r = client.post("/clock/advance", headers=H(runtime), json={"days": 1})
    assert r.status_code == 200
    db.expire_all()
    pods = book(db)["pods"]
    assert pod2 not in pods, (
        f"pod {pod2} was seeded ${LAW.seed_usd:,.0f} for rule {pods[pod2]['rule']['universe']}, "
        f"byte for byte the mandate pod {pod1} was seeded with")


# --- 6. the ladder only looks at today's drawdown --------------------------------------------------

def test_redteam_capital_ladder_misses_a_drawdown_lived_inside_one_advance(
        SessionFactory, client, db):
    """SEVERITY: low. The ladder sees the drawdown at the moment it looks, not the worst one lived.

    ``climb`` is fed the drawdown of the return index's LAST point. A pod that fell 15 % from its
    high-water mark on a day it lived through, then recovered before the next sweep, is never
    halved, frozen or closed, though its own forward series records the fall. Here one advance of
    three days hides it (the Runtime chooses the step, so an agent cannot force this alone; a
    1-day step hides nothing in a daily market).

    Suggested fix: climb on the worst drawdown in the days since the last sweep (each day's
    drawdown of the index), not only on the last one.
    """
    world = open_world(SessionFactory, {date(2024, 3, 6): 85.0, date(2024, 3, 7): 100.0})
    pm = world["pods"][0]
    advance(client, world)                                    # seeded
    order(client, pm["key"], "buy", 1900)                     # ~95 % in X
    advance(client, world, days=3)                            # lives 03-05 .. 03-08 at once
    db.expire_all()
    entry = book(db)["pods"][pm["id"]]
    record = track(db, pod_id=pm["id"], entry=entry, provider=get_provider(),
                   now=ledger_now(db), costs={})
    assert min(record.returns) < -0.10                         # the fall is in its own record
    assert stages(db, pm["id"]) == ["closed"], (
        f"a pod 15 % down from its high-water mark on 2024-03-06 is {entry['stage']}")


# --- 7. a halved pod is raised straight back ------------------------------------------------------

def _edge(n: int = 60, mean: float = 0.004) -> list[float]:
    return [mean + 0.004 * math.sin(1.7 * k) for k in range(n)]


def test_redteam_capital_a_halved_pod_is_raised_back_by_the_reweighing():
    """SEVERITY: low. The re-weighing can undo the ladder's halving.

    Halving recalls half a pod's capital; the re-weighing (which may run in the SAME sweep, right
    after the ladder) refuses raises only to reduce-only pods, so a halved pod with a strong
    t-statistic is raised +50 % at once: half of the halving is undone the moment it happens.
    Whether a halved pod may be raised is the law's call; the ADR says halving is physics and
    names only reduce-only as "never raised".

    Suggested fix: a halved pod is never raised (as reduce-only), or not in the sweep that halved it.
    """
    days = tuple((date(2025, 1, 1) + timedelta(d)).isoformat() for d in range(60))
    halved = PodTrack(pod_id=1, seeded=1, stage="halved", equity=100_000.0, days=days,
                      returns=tuple(_edge()), cost_usd=0.0, drawdown=0.05)
    row = reallocate([halved], centre_cash=9e6, law=LAW)["pods"][0]
    assert row["move"] <= 0.0, f"a pod halved by the ladder is raised ${row['move']:,.0f}"


# --- 8. a pod's own row tells it which other pod it moves like, and how much ----------------------

def test_redteam_capital_own_row_leaks_another_pods_correlation(
        SessionFactory, client, db, monkeypatch):
    """SEVERITY: low. A cross-pod read through GET /capital.

    A pod member may read only its own pod's row, but that row's ``last_score`` carries
    ``corr_with`` (another pod's id) and ``corr`` (how its daily returns move with that pod's),
    every re-weighing. A PM can trade probe portfolios and read back, every few days, how another
    pod's returns co-move with them: a slow oracle of another pod's book, which ``read_cross_pod``
    is meant to guard.

    Suggested fix: strip ``corr_with``/``corr`` (keep ``corr_factor``) from a row served without
    ``read_cross_pod``.
    """
    # Both pods pitch the same rule for brevity; the copy check at the seed (tested below) would
    # refuse the second, and it is not what this test is about.
    monkeypatch.setattr(capital_service, "_copy_check", lambda *a, **kw: None)
    world = open_world(SessionFactory, {}, pods=2)
    p1, p2 = world["pods"]
    for p in (p2,):
        sub = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=p["pm_id"],
                           payload={"pod_id": p["id"], "agent_id": p["pm_id"], "rule": RULE})
        append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=p["pm_id"],
                     payload={"pitch_id": sub.id, "pod_id": p["id"], "eligible": True})
    db.commit()
    advance(client, world)                                    # both seeded
    append_event(db, type=EVENT_CAPITAL_REALLOCATED, actor_agent_id=None, payload={
        "day": "2024-03-05", "law": LAW.model_dump(), "inputs": {},
        "result": {"pods": [
            {"pod_id": p1["id"], "viability": 3.0, "corr_with": None, "corr": None, "move": 0.0},
            {"pod_id": p2["id"], "viability": 0.4, "corr_with": p1["id"], "corr": 0.83,
             "corr_factor": 0.17, "move": 0.0}]}})
    db.commit()
    mine = client.get("/capital", headers=H(p2["key"])).json()
    score = mine["pods"][0]["last_score"]
    assert score.get("corr_with") is None and score.get("corr") is None, (
        f"pod {p2['id']}'s member reads that it moves like pod {score.get('corr_with')} "
        f"at ρ = {score.get('corr')}")


# --- auditor (cycle 48): the same clone, pitched before the original's seed ----------------------

def test_auditor_capital_clone_pitched_before_the_original_is_seeded_is_refused(
        SessionFactory, client, db, monkeypatch):
    """BLOCK (auditor). Pod 1 pitches R (eligible) and then R2 the same day, before the advance
    that seeds R; pod 2 pitches R. The copy must be compared with the pitch pod 1 is about to be
    seeded with, not only with pod 1's latest pitch and the already-seeded mandates."""
    set_provider(BarsProvider(_random_market()))

    def correlation_only(evaluation, *, attempts, others, law):
        corr = gates.correlation_gate(evaluation, others, law)
        return {"eligible": corr["result"] != "fail", "gates": [corr],
                "performance": gates.performance(evaluation)}

    monkeypatch.setattr(strategy_service, "judge", correlation_only)
    s = SessionFactory()
    try:
        start_backtest(s, start=datetime(2024, 6, 1, tzinfo=UTC))
        keys = []
        for k in (1, 2):
            pod = create_pod(s, name=f"desk-{k}")
            keys.append((pod.id, register_agent(s, name=f"pm-{k}", role=AgentRole.pm,
                                                pod_id=pod.id)[1]))
        _, runtime = seed_runtime_agent(s)
        s.commit()
    finally:
        s.close()
    (pod1, key1), (pod2, key2) = keys
    base = {"language": "strategy-v1", "signal": "momentum", "lookback": 10,
            "rebalance_every": 5, "top_n": 2, "side": "long_only", "gross": 1.0}
    rule_r = {**base, "universe": ["A0", "A1", "A2", "A3", "A4"]}
    rule_r2 = {**base, "universe": ["A5", "A6", "A7", "A8", "A9"]}

    def pitch(key: str, rule: dict) -> dict:
        r = client.post("/pitches", headers=H(key), json={
            "hypothesis": "winners keep winning", "data_needed": "daily prices",
            "team": "the PM", "budget_usd": 0.0, "rule": rule})
        assert r.status_code == 201, r.text
        return r.json()["verdict"]

    assert pitch(key1, rule_r)["eligible"]
    pitch(key1, rule_r2)                                  # before any advance: R is not seeded yet
    copy = pitch(key2, rule_r)
    assert not copy["eligible"]
    assert copy["gates"][0]["against"][f"pod {pod1} seed"] == pytest.approx(1.0)
    r = client.post("/clock/advance", headers=H(runtime), json={"days": 1})
    assert r.status_code == 200
    db.expire_all()
    pods = book(db)["pods"]
    assert pod1 in pods and pods[pod1]["rule"]["universe"] == rule_r["universe"]
    assert pod2 not in pods


def test_auditor_capital_a_failed_sweep_is_written_to_the_ledger(
        SessionFactory, client, db, monkeypatch):
    """WARN (auditor). A sweep that fails is rolled back and the advance still succeeds, but the
    day the ladder did not judge must be in the ledger, not only in the log."""
    world = open_world(SessionFactory, {})

    def broken(*a, **kw):
        raise RuntimeError("the machine broke")

    monkeypatch.setattr(capital_service, "_sweep", broken)
    advance(client, world)
    db.expire_all()
    failed = list(db.scalars(select(Event).where(Event.type == "capital_sweep_failed")))
    assert len(failed) == 1 and "the machine broke" in failed[0].payload_json["error"]
    assert book(db)["law"] is None                       # rolled back whole: the centre never opened


# --- auditor (cycle 48, second pass): no order of pitches gets two seeds for one rule -----------

CLONE_BASE = {"language": "strategy-v1", "signal": "momentum", "lookback": 10,
              "rebalance_every": 5, "top_n": 2, "side": "long_only", "gross": 1.0}
CLONE_R = {**CLONE_BASE, "universe": ["A0", "A1", "A2", "A3", "A4"]}


def _clone_world(SessionFactory, monkeypatch, pods: int = 2):
    set_provider(BarsProvider(_random_market()))

    def correlation_only(evaluation, *, attempts, others, law):
        corr = gates.correlation_gate(evaluation, others, law)
        return {"eligible": corr["result"] != "fail", "gates": [corr],
                "performance": gates.performance(evaluation)}

    monkeypatch.setattr(strategy_service, "judge", correlation_only)
    s = SessionFactory()
    try:
        start_backtest(s, start=datetime(2024, 6, 1, tzinfo=UTC))
        out = []
        for k in range(1, pods + 1):
            pod = create_pod(s, name=f"desk-{k}")
            pm, key = register_agent(s, name=f"pm-{k}", role=AgentRole.pm, pod_id=pod.id)
            out.append((pod.id, pm.id, key))
        _, runtime = seed_runtime_agent(s)
        s.commit()
    finally:
        s.close()
    return out, runtime


def test_auditor_capital_a_refused_long_short_pitch_does_not_free_a_clone(
        SessionFactory, client, db, monkeypatch):
    """BLOCK (auditor, second pass). Pod 1's first eligible pitch is long-short (refused at the
    seed), its second is R, its latest R3; pod 2 pitches R before the refusal. The pitch-time gate
    never compared the copy with R; the machine's check at the seed must."""
    ((_, _, key1), (_, _, key2)), runtime = _clone_world(SessionFactory, monkeypatch)

    def pitch(key: str, rule: dict) -> dict:
        r = client.post("/pitches", headers=H(key), json={
            "hypothesis": "winners keep winning", "data_needed": "daily prices",
            "team": "the PM", "budget_usd": 0.0, "rule": rule})
        assert r.status_code == 201, r.text
        return r.json()["verdict"]

    other = ["A5", "A6", "A7", "A8", "A9"]
    assert pitch(key1, {**CLONE_BASE, "universe": other, "side": "long_short"})["eligible"]
    assert pitch(key1, CLONE_R)["eligible"]
    pitch(key1, {**CLONE_BASE, "universe": other, "lookback": 20})
    pitch(key2, CLONE_R)
    for _ in range(3):
        r = client.post("/clock/advance", headers=H(runtime), json={"days": 1})
        assert r.status_code == 200
    db.expire_all()
    funded = [pid for pid, e in book(db)["pods"].items()
              if e["rule"]["universe"] == CLONE_R["universe"]]
    assert len(funded) == 1, f"pods {funded} were all seeded for the same rule"


def test_auditor_capital_two_eligible_copies_in_the_ledger_get_one_seed(
        SessionFactory, client, db, monkeypatch):
    """BLOCK (auditor, second pass), the strongest form: two pods' eligible pitches of one rule
    reach the ledger at once (no pitch-time gate saw the other). One seed, one refusal."""
    pods, runtime = _clone_world(SessionFactory, monkeypatch)
    for pod_id, pm_id, _ in pods:
        sub = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=pm_id,
                           payload={"pod_id": pod_id, "agent_id": pm_id, "rule": CLONE_R})
        append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=pm_id,
                     payload={"pitch_id": sub.id, "pod_id": pod_id, "eligible": True})
    db.commit()
    r = client.post("/clock/advance", headers=H(runtime), json={"days": 1})
    assert r.status_code == 200
    db.expire_all()
    assert list(book(db)["pods"]) == [pods[0][0]]
    refused = [e.payload_json for e in db.scalars(
        select(Event).where(Event.type == "capital_seed_refused"))]
    assert [p["pod_id"] for p in refused] == [pods[1][0]]
    assert refused[0]["gate"]["result"] == "fail"
    assert refused[0]["gate"]["against"][f"pod {pods[0][0]} mandate"] == pytest.approx(1.0)


def test_auditor_capital_an_unrelated_rule_is_still_seeded(SessionFactory, client, db, monkeypatch):
    """The control: the check at the seed refuses copies, not every second pod."""
    pods, runtime = _clone_world(SessionFactory, monkeypatch)
    rules = [CLONE_R, {**CLONE_BASE, "universe": ["A5", "A6", "A7", "A8", "A9"]}]
    for (pod_id, pm_id, _), rule in zip(pods, rules):
        sub = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=pm_id,
                           payload={"pod_id": pod_id, "agent_id": pm_id, "rule": rule})
        append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=pm_id,
                     payload={"pitch_id": sub.id, "pod_id": pod_id, "eligible": True})
    db.commit()
    r = client.post("/clock/advance", headers=H(runtime), json={"days": 1})
    assert r.status_code == 200
    db.expire_all()
    assert sorted(book(db)["pods"]) == sorted(p[0] for p in pods)


def test_auditor_capital_a_closed_pods_rule_is_not_funded_afresh(
        SessionFactory, client, db, monkeypatch):
    """WARN (auditor, third pass). The ladder closed pod 1 and its rule R; pod 2 pitches R byte for
    byte. Neither the gate nor the seed may fund the rule the ladder killed under a new name."""
    pods, runtime = _clone_world(SessionFactory, monkeypatch)
    (pod1, pm1, _), (pod2, pm2, key2) = pods
    sub = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=pm1,
                       payload={"pod_id": pod1, "agent_id": pm1, "rule": CLONE_R})
    append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=pm1,
                 payload={"pitch_id": sub.id, "pod_id": pod1, "eligible": True})
    db.commit()
    assert client.post("/clock/advance", headers=H(runtime), json={"days": 1}).status_code == 200
    append_event(db, type="pod_stage_changed", actor_agent_id=None,
                 payload={"pod_id": pod1, "from": "active", "to": "closed"})
    db.get(Pod, pod1).status = "closed"
    append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=pm1,      # pod 1 moves on
                 payload={"pod_id": pod1, "agent_id": pm1,
                          "rule": {**CLONE_BASE, "universe": ["A5", "A6", "A7", "A8", "A9"]}})
    db.commit()
    r = client.post("/pitches", headers=H(key2), json={
        "hypothesis": "winners keep winning", "data_needed": "daily prices", "team": "the PM",
        "budget_usd": 0.0, "rule": CLONE_R})
    assert r.status_code == 201, r.text
    verdict = r.json()["verdict"]
    assert not verdict["eligible"]
    assert verdict["gates"][0]["against"][f"pod {pod1} mandate"] == pytest.approx(1.0)
    sub = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=pm2,  # and if it got through
                       payload={"pod_id": pod2, "agent_id": pm2, "rule": CLONE_R})
    append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=pm2,
                 payload={"pitch_id": sub.id, "pod_id": pod2, "eligible": True})
    db.commit()
    assert client.post("/clock/advance", headers=H(runtime), json={"days": 1}).status_code == 200
    db.expire_all()
    assert pod2 not in book(db)["pods"]
