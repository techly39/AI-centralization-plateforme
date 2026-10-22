"""A pitch is argued before its seed (app/capital/debate.py): the law off changes nothing; under it
the sweep opens the debate, waits, pays early on a seed verdict, refuses on a hold, pays at the
close on silence; who may argue and rule, and the refusals. The end to end proof is
``acceptance/pitch_debate.py`` (scripted pods, real gates, the month's end, the law off)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.capital import debate as debate_mod
from app.capital.service import sweep
from app.clock import LiveClock, set_clock
from app.config import CapitalConfig, get_settings
from app.db.models import Event
from app.ledger.events import EVENT_PITCH_JUDGED, EVENT_PITCH_SUBMITTED, append_event
from app.marketdata import get_provider
from app.registry.pods import create_pod
from app.registry.service import get_or_create_system_agent
from app.run_clock import advance, start_backtest

RULE = {"language": "strategy-v1", "signal": "momentum", "lookback": 20, "rebalance_every": 5,
        "side": "long_only", "gross": 1.0, "universe": ["AAPL", "MSFT"], "top_n": 1}


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def september(SessionFactory):
    s = SessionFactory()
    try:
        start_backtest(s, start=datetime(2024, 9, 2, tzinfo=UTC))
        s.commit()
    finally:
        s.close()
    yield
    set_clock(LiveClock())


@pytest.fixture
def law(monkeypatch, september):
    monkeypatch.setattr(get_settings(), "capital", CapitalConfig(debate_days=2))


def _pitch(db, pod_id: int, *, eligible: bool = True) -> int:
    """A pitch the gates judged, as physics writes it."""
    submitted = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=None, payload={
        "pod_id": pod_id, "agent_id": None, "hypothesis": "momentum", "data_needed": "closes",
        "team": "me", "budget_usd": 1.0, "rule": RULE})
    append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=None, payload={
        "pitch_id": submitted.id, "pod_id": pod_id, "eligible": eligible, "gates": [],
        "performance": {}, "window": {}, "attempts": 1})
    db.commit()
    return submitted.id


def _morning(db) -> dict:
    """The clock moves a day and the capital machine runs, as an advance does."""
    advance(db, minutes=24 * 60, actor_agent_id=get_or_create_system_agent(db).id)
    return sweep(db, provider=get_provider())


def _types(db, type_: str) -> list[dict]:
    db.expire_all()
    return [e.payload_json for e in db.scalars(select(Event).where(Event.type == type_)
                                               .order_by(Event.id))]


def test_without_the_law_a_pitch_is_seeded_the_next_morning_and_the_law_reads_as_before(
        db, september):
    assert "debate_days" not in CapitalConfig().model_dump()
    pod = create_pod(db, name="alpha").id
    _pitch(db, pod)
    _morning(db)
    assert [p["pod_id"] for p in _types(db, "capital_seeded")] == [pod]
    assert _types(db, "debate_opened") == []


def test_silence_pays_the_seed_the_morning_the_debate_closes(db, law):
    pod = create_pod(db, name="alpha").id
    pitch = _pitch(db, pod)
    assert _morning(db)["debating"] == [pitch]
    opened = _types(db, "debate_opened")[0]
    assert (opened["opened_on"], opened["closes_on"]) == ("2024-09-03", "2024-09-05")
    assert debate_mod.debating_pods(db) == {pod}
    _morning(db)
    assert _types(db, "capital_seeded") == []
    _morning(db)
    assert [p["pitch_id"] for p in _types(db, "capital_seeded")] == [pitch]
    assert debate_mod.debating_pods(db) == set()


def test_a_seed_verdict_pays_early_and_a_hold_refuses_with_the_reason(
        db, law, client, agent_factory):
    a, b = create_pod(db, name="alpha").id, create_pod(db, name="beta").id
    pa, pb = _pitch(db, a), _pitch(db, b)
    _morning(db)
    _, manager = agent_factory("manager", "manager")
    r = client.post(f"/debates/{pa}/verdict", headers=h(manager),
                    json={"verdict": "hold", "reason": "a fraud headline in the universe"})
    assert r.status_code == 201, r.text
    assert client.post(f"/debates/{pb}/verdict", headers=h(manager),
                       json={"verdict": "seed"}).status_code == 201
    _morning(db)
    assert [p["pitch_id"] for p in _types(db, "capital_seeded")] == [pb]
    refused = _types(db, "capital_seed_refused")
    assert [p["pitch_id"] for p in refused] == [pa]
    assert "a fraud headline in the universe" in refused[0]["reason"]


def test_who_may_argue_and_rule(db, law, client, agent_factory):
    a, b = create_pod(db, name="alpha").id, create_pod(db, name="beta").id
    pa = _pitch(db, a)
    _morning(db)
    _, bull = agent_factory("bull", "reviewer")
    _, pm_a = agent_factory("alpha-pm", "pm", a)
    _, pm_b = agent_factory("beta-pm", "pm", b)
    _, analyst = agent_factory("alpha-analyst", "analyst", a)
    _, manager = agent_factory("manager", "manager")
    say = {"text": "the momentum held out of sample"}
    assert client.post(f"/debates/{pa}/argue", headers=h(bull), json=say).status_code == 201
    assert client.post(f"/debates/{pa}/argue", headers=h(pm_a), json=say).status_code == 201
    assert client.post(f"/debates/{pa}/argue", headers=h(pm_b), json=say).status_code == 403
    assert client.post(f"/debates/{pa}/argue", headers=h(analyst), json=say).status_code == 403
    assert client.post(f"/debates/{pa}/argue", headers=h(manager), json=say).status_code == 403
    for key in (bull, pm_a):
        assert client.post(f"/debates/{pa}/verdict", headers=h(key),
                           json={"verdict": "seed"}).status_code == 403
    assert client.get(f"/debates/{pa}", headers=h(pm_b)).status_code == 403
    assert [d["pitch_id"] for d in client.get("/debates", headers=h(analyst)).json()] == [pa]
    for _ in range(debate_mod.MAX_POSTS - 1):
        client.post(f"/debates/{pa}/argue", headers=h(bull), json=say)
    r = client.post(f"/debates/{pa}/argue", headers=h(bull), json=say)
    assert r.status_code == 409 and "most one author" in r.json()["detail"]
    assert client.post(f"/debates/{pa}/verdict", headers=h(manager),
                       json={"verdict": "hold"}).status_code == 422     # a hold says why
    assert client.post(f"/debates/{pa}/verdict", headers=h(manager),
                       json={"verdict": "seed", "seed_usd": 1e9}).status_code == 422
    assert client.post(f"/debates/{pa}/verdict", headers=h(manager),
                       json={"verdict": "seed"}).status_code == 201
    assert client.post(f"/debates/{pa}/verdict", headers=h(manager),
                       json={"verdict": "hold", "reason": "changed my mind"}).status_code == 409
    refused = _types(db, "debate_refused")
    assert [p["act"] for p in refused] == ["argue", "rule"]


def test_no_verdict_on_an_ineligible_pitch_or_after_the_close(db, law, client, agent_factory):
    a = create_pod(db, name="alpha").id
    bad, good = _pitch(db, a, eligible=False), None
    _, manager = agent_factory("manager", "manager")
    r = client.post(f"/debates/{bad}/verdict", headers=h(manager), json={"verdict": "seed"})
    assert r.status_code == 409 and "not eligible" in r.json()["detail"]
    good = _pitch(db, create_pod(db, name="beta").id)
    _morning(db)
    _morning(db)
    _morning(db)       # the debate closed this morning and the seed is paid
    r = client.post(f"/debates/{good}/verdict", headers=h(manager),
                    json={"verdict": "hold", "reason": "late"})
    assert r.status_code == 409
    assert [p["pitch_id"] for p in _types(db, "capital_seeded")] == [good]


def test_only_the_operator_makes_a_reviewer_and_it_has_no_pod(client, admin_key, agent_factory):
    _, other = agent_factory("another-management", "management")
    r = client.post("/agents/register", headers=h(other), json={"name": "r", "role": "reviewer"})
    assert r.status_code == 403
    r = client.post("/agents/register", headers=h(admin_key),
                    json={"name": "r", "role": "reviewer", "pod_id": 1})
    assert r.status_code == 422
    r = client.post("/agents/register", headers=h(admin_key),
                    json={"name": "bear", "role": "reviewer", "data": ["headlines"]})
    assert r.status_code == 201
