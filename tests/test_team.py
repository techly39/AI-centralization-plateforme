"""A PM builds its team (app/capital/team.py): the paths the acceptance demo does not walk. The
team follows its pod out (the ladder's close, the generation's let-go), a place whose PM is gone
is closed at the fill, the Runtime's refusal keeps a place open, and the law is frozen."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.config import GenerationConfig, TeamConfig, get_settings
from app.db.models import Event
from app.run_clock import start_backtest

HAIKU = "anthropic/claude-haiku-5.5"


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def team_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "team", TeamConfig(on=True, max_analysts=2,
                                                           budget_usd=0.40, models=(HAIKU,)))


@pytest.fixture
def september(SessionFactory):
    s = SessionFactory()
    try:
        start_backtest(s, start=datetime(2024, 9, 1, tzinfo=UTC))
        s.commit()
    finally:
        s.close()
    yield
    set_clock(LiveClock())


def _ask(client, key: str, budget: float = 0.10):
    return client.post("/team/analysts", headers=h(key), json={
        "charter": "research the sector", "model": HAIKU, "budget_usd": budget})


def _types(db, type_: str) -> list[dict]:
    db.expire_all()
    return [e.payload_json for e in db.scalars(select(Event).where(Event.type == type_)
                                               .order_by(Event.id))]


def _hire(client, admin_key, pm_key) -> tuple[int, dict]:
    asked = _ask(client, pm_key)
    assert asked.status_code == 201, asked.text
    made = client.post(f"/team/places/{asked.json()['id']}/fill", headers=h(admin_key))
    assert made.status_code == 201, made.text
    return asked.json()["id"], made.json()["agent"]


def test_the_ladders_close_lets_the_team_go_under_any_generation_law(
        client, db, SessionFactory, team_on, make_pod, pm_factory, admin_key):
    from app.capital.generation import let_go_closed
    from app.registry.service import get_or_create_system_agent

    make_pod(1, "alpha")
    _, pm = pm_factory("pm-1", 1)
    _, analyst = _hire(client, admin_key, pm)
    waiting = _ask(client, pm).json()["id"]
    s = SessionFactory()
    try:
        let_go_closed(s, pod_id=1, post_mortem={}, actor=get_or_create_system_agent(s))
        s.commit()
    finally:
        s.close()
    assert client.get("/me", headers=h(analyst["api_key"])).status_code == 401
    assert client.get("/me", headers=h(pm)).status_code == 200    # the generation law is off
    ends = {p["place_id"]: p["reason"] for t in ("team_member_let_go", "team_place_closed")
            for p in _types(db, t)}
    assert len(ends) == 2 and waiting in ends
    assert set(ends.values()) == {"its pod was closed by the risk ladder"}


def test_the_generations_let_go_takes_the_team_with_its_pm(
        client, db, september, team_on, monkeypatch, make_pod, pm_factory, admin_key,
        runtime_key):
    monkeypatch.setattr(get_settings(), "generation", GenerationConfig(on=True, grace_days=0))
    make_pod(1, "alpha")
    _, pm = pm_factory("pm-1", 1)
    _, analyst = _hire(client, admin_key, pm)
    r = client.post("/clock/advance", headers=h(runtime_key), json={"days": 30})   # 1 October
    assert r.status_code == 200, r.text
    let_go = _types(db, "pm_let_go")
    assert [p["agent_name"] for p in let_go] == ["pm-1"]       # an analyst is not a PM let go
    [member] = _types(db, "team_member_let_go")
    assert (member["agent_id"], member["reason"]) == (analyst["id"], "its PM was let go")
    assert client.get("/me", headers=h(analyst["api_key"])).status_code == 401


def test_a_place_whose_pm_is_gone_is_closed_at_the_fill_never_filled(
        client, db, team_on, make_pod, pm_factory, admin_key, SessionFactory):
    from app.registry.service import deactivate_agent

    make_pod(1, "alpha")
    pm_id, pm = pm_factory("pm-1", 1)
    place = _ask(client, pm).json()["id"]
    s = SessionFactory()
    try:   # gone by a path that is not the team's (the cascade is not what closes it here)
        deactivate_agent(s, agent_id=pm_id)
        s.commit()
    finally:
        s.close()
    r = client.post(f"/team/places/{place}/fill", headers=h(admin_key))
    assert r.status_code == 409 and "gone" in r.json()["detail"]
    assert [p["place_id"] for p in _types(db, "team_place_closed")] == [place]
    assert not _types(db, "team_place_filled")


def test_the_runtimes_refusal_keeps_the_place_open_and_the_law_is_frozen(
        client, db, team_on, monkeypatch, make_pod, pm_factory, admin_key):
    make_pod(1, "alpha")
    _, pm = pm_factory("pm-1", 1)
    place = _ask(client, pm).json()["id"]
    r = client.post(f"/team/places/{place}/refuse", headers=h(admin_key),
                    json={"reason": "its key does not fit the monthly cap"})
    assert r.status_code == 200 and r.json()["status"] == "open"
    assert r.json()["refusals"][0]["reason"] == "its key does not fit the monthly cap"
    # Today's settings change; the run's law was frozen into its first granted request.
    monkeypatch.setattr(get_settings(), "team", TeamConfig(on=False))
    assert _ask(client, pm).status_code == 201


def test_only_a_pm_asks_and_management_reads_every_team(
        client, team_on, make_pod, pm_factory, admin_key, agent_factory):
    make_pod(1, "alpha")
    make_pod(2, "beta")
    _, pm = pm_factory("pm-1", 1)
    _, other = agent_factory("an-1", "analyst", 2)
    assert _ask(client, admin_key).status_code == 403
    assert _ask(client, other).status_code == 403
    assert client.get("/team", headers=h(other), params={"pod_id": 1}).status_code == 403
    assert client.get("/team", headers=h(admin_key), params={"pod_id": 1}).status_code == 200
    assert client.get("/team", headers=h(pm)).json()["law_on"] is True


def test_the_runtime_refuses_an_analyst_whose_key_does_not_fit_the_monthly_cap():
    """The Runtime's own check before the fill: the analyst's budget must fit the Human's monthly
    cap with every key the firm already holds ('yes' and 'no' cases)."""
    from runtime.governance import Governance
    from runtime.metering import FakeProvisioner, Meter
    from runtime.onboarding import HireTemplate, Onboarding

    prov = FakeProvisioner()
    held = [Meter(prov, prov.create_key(1, 900_000))]          # $0.90 of a $1.00 cap held
    hiring = Onboarding(HireTemplate(provider="fake-metered", analyst_script="research-analyst"),
                        registrar=None, connect=None, provisioner=prov)
    place = {"pod_name": "alpha", "asked_by_name": "pm-1", "asked_by": 1, "charter": "c",
             "model": HAIKU}
    law = Governance(False, 1.0, max_agents_total=10)
    over = hiring._decide_analyst(7, {**place, "budget_usd": 0.20}, held, law)
    fits = hiring._decide_analyst(7, {**place, "budget_usd": 0.05}, held, law)
    assert over[0] == "refused:budget_over_cap" and "$0.20" in over[1]
    assert fits == ("hired", None)
