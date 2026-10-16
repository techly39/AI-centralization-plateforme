"""Research backtests and pitches over HTTP (app/api/pitches.py, ADR-048): permissions, pod scope,
the held-out window, the attempt count and the verdict in the ledger."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db.models import Event
from app.limits import MAX_USD_PER_REPORT
from app.marketdata import SyntheticProvider, set_provider
from tests.support import world_key

SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0, "SYNC": 20.0, "SYND": 35.0}
RULE = {"universe": ["SYNA", "SYNB", "SYNC", "SYND"], "signal": "momentum", "lookback": 20,
        "rebalance_every": 5, "top_n": 1, "side": "long_short"}
PITCH = {"hypothesis": "Trends persist: slow information diffusion makes winners keep winning.",
         "data_needed": "daily prices", "team": "one analyst", "budget_usd": 5.0, "rule": RULE}
TODAY = date(2026, 6, 1)                      # the frozen clock's day
HELD_FROM = TODAY - timedelta(days=180)       # config.yaml gates.holdout_days


@pytest.fixture
def world(frozen_clock, make_pod, pm_factory, agent_factory):
    set_provider(SyntheticProvider(world_key(48), SYMBOLS))
    make_pod(1)
    make_pod(2)
    _, pm1 = pm_factory("pm-1", 1)
    _, pm2 = pm_factory("pm-2", 2)
    _, analyst1 = agent_factory("analyst-1", "analyst", 1)
    yield {"pm1": pm1, "pm2": pm2, "analyst1": analyst1}
    set_provider(None)


def h(key: str) -> dict:
    return {"X-API-Key": key}


def events(db, type: str) -> list[Event]:
    return list(db.scalars(select(Event).where(Event.type == type).order_by(Event.id)))


def test_research_is_counted_per_pod_and_stays_out_of_the_held_out_days(client, world, db):
    first = client.post("/research/backtests", headers=h(world["analyst1"]), json={"rule": RULE})
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["attempt"] == 1 and body["pod_id"] == 1
    assert body["window"] == {"start": (HELD_FROM - timedelta(days=365)).isoformat(),
                              "end": HELD_FROM.isoformat()}
    assert body["performance"]["days"] > 200 and body["performance"]["predictions"] > 0

    second = client.post("/research/backtests", headers=h(world["pm1"]),
                         json={"rule": {**RULE, "signal": "mean_reversion"},
                               "start": "2024-01-01", "end": "2025-01-01"})
    assert second.status_code == 201 and second.json()["attempt"] == 2

    late = client.post("/research/backtests", headers=h(world["pm1"]),
                       json={"rule": RULE, "end": (HELD_FROM + timedelta(days=1)).isoformat()})
    assert late.status_code == 422 and "held out" in late.json()["detail"]
    unknown = client.post("/research/backtests", headers=h(world["pm1"]),
                          json={"rule": {**RULE, "universe": ["SYNA", "NOPE"]}})
    assert unknown.status_code == 422
    assert len(events(db, "research_backtest_run")) == 2       # refusals are not attempts

    listed = client.get("/research/backtests", headers=h(world["analyst1"])).json()
    assert [r["attempt"] for r in listed] == [1, 2]
    assert client.get("/research/backtests", headers=h(world["pm2"])).json() == []
    assert client.get("/research/backtests?pod_id=1", headers=h(world["pm2"])).status_code == 403


def test_a_pitch_is_judged_on_the_held_out_days_with_every_attempt_counted(client, world, db):
    for lookback in (10, 20, 40):
        assert client.post("/research/backtests", headers=h(world["analyst1"]),
                           json={"rule": {**RULE, "lookback": lookback}}).status_code == 201
    r = client.post("/pitches", headers=h(world["pm1"]), json=PITCH)
    assert r.status_code == 201, r.text
    pitch = r.json()
    verdict = pitch["verdict"]
    assert verdict["window"] == {"start": HELD_FROM.isoformat(), "end": TODAY.isoformat()}
    assert verdict["attempts"] == 4                            # 3 research + this pitch
    gates = {g["gate"]: g for g in verdict["gates"]}
    assert set(gates) == {"ic", "deflated_sharpe", "capacity", "correlation", "hypothesis"}
    assert gates["deflated_sharpe"]["attempts"] == 4
    assert gates["correlation"]["result"] == "null"            # no other pod has pitched
    assert gates["hypothesis"]["result"] == "recorded"
    assert all(g["result"] in {"pass", "fail", "null", "recorded"} for g in gates.values())
    assert verdict["performance"]["days"] > 100
    assert verdict["law"]["holdout_days"] == 180

    [submitted] = events(db, "pitch_submitted")
    [judged] = events(db, "pitch_judged")
    assert pitch["id"] == submitted.id == judged.payload_json["pitch_id"]
    assert submitted.payload_json["hypothesis"] == PITCH["hypothesis"]
    assert client.get(f"/pitches/{pitch['id']}", headers=h(world["analyst1"])).json() == pitch

    again = client.post("/pitches", headers=h(world["pm1"]), json=PITCH).json()
    assert again["verdict"]["attempts"] == 5                   # a pitch is an attempt too


def test_only_the_pm_pitches_and_pods_read_only_their_own(client, world, db, admin_key):
    denied = client.post("/pitches", headers=h(world["analyst1"]), json=PITCH)
    assert denied.status_code == 403
    assert events(db, "permission_denied")
    assert client.post("/research/backtests", headers=h(admin_key), json={"rule": RULE}).status_code == 403

    mine = client.post("/pitches", headers=h(world["pm1"]), json=PITCH).json()
    assert client.get(f"/pitches/{mine['id']}", headers=h(world["pm2"])).status_code == 403
    assert client.get("/pitches?pod_id=1", headers=h(world["pm2"])).status_code == 403
    assert client.get("/pitches", headers=h(world["pm2"])).json() == []
    assert [p["id"] for p in client.get("/pitches", headers=h(admin_key)).json()] == [mine["id"]]
    assert client.get(f"/pitches/{mine['id']}", headers=h(admin_key)).status_code == 200
    not_a_pitch = events(db, "permission_denied")[0].id
    assert client.get(f"/pitches/{not_a_pitch}", headers=h(admin_key)).status_code == 404


def test_a_copy_of_another_pods_strategy_fails_correlation(client, world):
    client.post("/pitches", headers=h(world["pm1"]), json=PITCH)
    copy = client.post("/pitches", headers=h(world["pm2"]), json=PITCH).json()
    corr = next(g for g in copy["verdict"]["gates"] if g["gate"] == "correlation")
    assert corr["result"] == "fail" and corr["value"] == pytest.approx(1.0)
    assert corr["against"] == {"pod 1": pytest.approx(1.0)}
    assert copy["verdict"]["eligible"] is False
    assert copy["verdict"]["attempts"] == 1                    # pod 1's attempts are not pod 2's


def test_a_rule_that_is_not_strategy_v1_is_refused_before_anything_runs(client, world, db):
    for bad in ({**RULE, "code": "import os"}, {**RULE, "lookback": 0},
                {**RULE, "universe": ["SYNA"]}, {**RULE, "gross": 5}):
        assert client.post("/pitches", headers=h(world["pm1"]),
                           json={**PITCH, "rule": bad}).status_code == 422
    raw = json.dumps({**PITCH, "budget_usd": 1}).replace('"budget_usd": 1', '"budget_usd": 1e309')
    assert client.post("/pitches", headers={**h(world["pm1"]), "Content-Type": "application/json"},
                       content=raw).status_code == 422
    assert events(db, "pitch_submitted") == []


#: The floats in these bodies (tests/test_finite.py's guard lists them and points here).
_FLOATS = [
    ("/pitches", lambda v: {**PITCH, "budget_usd": v}, "budget_usd", MAX_USD_PER_REPORT),
    ("/pitches", lambda v: {**PITCH, "rule": {**RULE, "gross": v}}, "gross", 2.0),
    ("/research/backtests", lambda v: {"rule": {**RULE, "gross": v}}, "gross", 2.0),
]


@pytest.mark.parametrize(("path", "make", "field", "cap"), _FLOATS,
                         ids=["pitch-budget", "pitch-gross", "research-gross"])
def test_every_float_is_finite_and_capped(client, world, db, path, make, field, cap):
    """Non-finite and just-over-the-cap are a clean 422 naming the field, nothing written;
    the cap itself is accepted."""
    marker = "0.123456789"
    before = len(list(db.scalars(select(Event))))
    for token in ("NaN", "Infinity", "-Infinity", "1e309", "1e308",
                  repr(math.nextafter(cap, math.inf))):
        raw = json.dumps(make(float(marker))).replace(marker, token)
        r = client.post(path, headers={**h(world["pm1"]), "Content-Type": "application/json"},
                        content=raw)
        assert r.status_code == 422, (token, r.text)
        json.loads(r.text)
        assert any(field in [str(p) for p in e["loc"]] for e in r.json()["detail"]), r.text
    db.expire_all()
    assert len(list(db.scalars(select(Event)))) == before
    assert client.post(path, headers=h(world["pm1"]), json=make(cap)).status_code == 201
