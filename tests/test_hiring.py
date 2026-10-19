"""Hiring (idea: a dead pod is replaced): the vacancy a close opens, the fill, the refusals, who reads
what, and the frozen law. The end-to-end proof is ``acceptance/pod_replacement.py`` (a made-up
market where the ladder really closes pods); here a close is staged in the ledger directly."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.capital.allocation import PodTrack
from app.capital.hiring import open_vacancy, post_mortem
from app.config import HiringConfig, get_settings
from app.db.models import Agent, Event, Pod
from app.ledger.events import (
    EVENT_CAPITAL_SEEDED,
    EVENT_PITCH_SUBMITTED,
    EVENT_POD_STAGE_CHANGED,
    append_event,
)
from app.registry.service import get_or_create_system_agent

RULE = {"language": "strategy-v1", "signal": "momentum", "universe": ["AAA", "BBB"],
        "lookback": 20, "rebalance_every": 5, "top_n": 1, "side": "long_only", "gross": 1.0}


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def close(SessionFactory):
    """Stage a machine pod's death in the ledger (pitch, seed, ladder to closed) and open its
    vacancy as the capital machine does. Returns the vacancy's id."""

    def _close(pod_id: int) -> int:
        s = SessionFactory()
        try:
            system = get_or_create_system_agent(s)
            pitch = append_event(s, type=EVENT_PITCH_SUBMITTED, actor_agent_id=system.id, payload={
                "pod_id": pod_id, "hypothesis": "winners keep winning", "rule": RULE})
            append_event(s, type=EVENT_CAPITAL_SEEDED, actor_agent_id=system.id, payload={
                "pod_id": pod_id, "pitch_id": pitch.id, "seed_usd": 200_000.0, "rule": RULE,
                "cost_at_seed_usd": 0.0})
            append_event(s, type=EVENT_POD_STAGE_CHANGED, actor_agent_id=system.id, payload={
                "pod_id": pod_id, "from": "active", "to": "closed", "drawdown": 0.12,
                "worst_drawdown": 0.12})
            s.get(Pod, pod_id).status = "closed"
            record = PodTrack(pod_id=pod_id, seeded=pitch.id, stage="closed", equity=0.0,
                              days=("2025-01-02", "2025-01-03"), returns=(0.01, -0.12),
                              cost_usd=0.25, drawdown=0.12)
            event = open_vacancy(s, pod_id=pod_id, record=record, actor=system)
            s.commit()
            return event.id
        finally:
            s.close()

    return _close


def test_the_post_mortem_is_the_dead_pods_own_record(db, make_pod, close):
    make_pod(1, "sinker")
    vacancy_id = close(1)
    payload = db.get(Event, vacancy_id).payload_json
    pm = payload["post_mortem"]
    assert pm["pod_name"] == "sinker" and pm["pitch"]["rule"] == RULE
    assert pm["pitch"]["hypothesis"] == "winners keep winning"
    assert [s["to"] for s in pm["ladder"]] == ["closed"] and pm["forward_days"] == 2
    assert pm["forward_return"] == pytest.approx(1.01 * 0.88 - 1)
    assert pm["thinking_cost_usd"] == 0.25
    hire = payload["hire"]
    assert (hire["pod_name"], hire["pm_name"], hire["role"]) == ("hire-1", "hire-1-pm", "pm")
    assert hire["model"] == get_settings().hiring.models[0]
    # no forward day: statistics are null, not 0
    empty = PodTrack(pod_id=1, seeded=1, stage="closed", equity=0.0, days=(), returns=(),
                     cost_usd=0.0, drawdown=0.0)
    blank = post_mortem(db, pod_id=1, record=empty)
    assert blank["forward_return"] is None and blank["worst_drawdown"] is None


def test_fill_makes_the_pod_and_pm_the_law_names_once(client, db, admin_key, make_pod, close):
    make_pod(1, "sinker")
    vacancy_id = close(1)
    r = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    assert r.status_code == 201, r.text
    agent = r.json()["agent"]
    assert agent["name"] == "hire-1-pm" and agent["role"] == "pm" and agent["api_key"]
    row = db.get(Agent, agent["id"])
    pod = db.get(Pod, agent["pod_id"])
    assert pod.name == "hire-1" and pod.status == "active" and pod.current_allocation == 0.0
    assert row.charter_ref == f"vacancy:{vacancy_id}"
    me = client.get("/me", headers=h(agent["api_key"])).json()
    assert (me["name"], me["pod_id"]) == ("hire-1-pm", pod.id)
    assert r.json()["vacancy"]["status"] == "filled"
    again = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    assert again.status_code == 409
    assert db.scalar(select(Agent).where(Agent.name == "hire-1-pm")) is not None
    assert client.post("/vacancies/999/fill", headers=h(admin_key)).status_code == 404


def test_the_pod_limit_refuses_the_hire_in_the_ledger(client, db, admin_key, make_pod, close,
                                                      monkeypatch):
    monkeypatch.setattr(get_settings(), "hiring",
                        HiringConfig(max_live_pods=2))
    for pod_id in (1, 2, 3):
        make_pod(pod_id)
    vacancy_id = close(1)          # the law is frozen here: 2 live pods at most
    r = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    assert r.status_code == 409 and "limit of 2 live pods" in r.json()["detail"]
    refused = [e.payload_json for e in db.scalars(select(Event).where(Event.type == "hire_refused"))]
    assert refused == [{"vacancy_id": vacancy_id, "reason": r.json()["detail"], "by": "management"}]
    assert db.scalar(select(Pod).where(Pod.name == "hire-1")) is None
    assert db.scalar(select(Agent).where(Agent.name == "hire-1-pm")) is None
    v = client.get(f"/vacancies/{vacancy_id}", headers=h(admin_key)).json()
    assert v["status"] == "open" and len(v["refusals"]) == 1
    close(2)                       # room: one live pod left
    assert client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key)).status_code == 201


def test_the_law_is_frozen_at_the_first_vacancy_and_models_go_in_turn(db, make_pod, close,
                                                                      monkeypatch):
    monkeypatch.setattr(get_settings(), "hiring",
                        HiringConfig(models=("m/one", "m/two"), budget_usd=0.2))
    for pod_id in (1, 2, 3):
        make_pod(pod_id)
    close(1)
    monkeypatch.setattr(get_settings(), "hiring",
                        HiringConfig(models=("m/other",), budget_usd=9.0))
    close(2)
    close(3)
    hires = [e.payload_json["hire"] for e in db.scalars(
        select(Event).where(Event.type == "vacancy_opened").order_by(Event.id))]
    assert [x["model"] for x in hires] == ["m/one", "m/two", "m/one"]
    assert {x["budget_usd"] for x in hires} == {0.2}
    assert [x["pod_name"] for x in hires] == ["hire-1", "hire-2", "hire-3"]


def test_a_name_already_taken_refuses_the_hire(client, db, admin_key, make_pod, close):
    make_pod(1)
    make_pod(2, "hire-1")          # the operator already used the name
    vacancy_id = close(1)
    r = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    assert r.status_code == 409 and "hire-1" in r.json()["detail"]
    assert db.scalar(select(Agent).where(Agent.name == "hire-1-pm")) is None


def test_the_runtimes_refusal_is_written_and_the_vacancy_stays_open(client, db, admin_key,
                                                                    make_pod, close):
    make_pod(1)
    vacancy_id = close(1)
    r = client.post(f"/vacancies/{vacancy_id}/refuse", headers=h(admin_key),
                    json={"reason": "the hire's budget does not fit the cap"})
    assert r.status_code == 200 and r.json()["status"] == "open"
    assert r.json()["refusals"][0]["reason"] == "the hire's budget does not fit the cap"
    blank = client.post(f"/vacancies/{vacancy_id}/refuse", headers=h(admin_key),
                        json={"reason": "   "})
    assert blank.status_code == 422
    client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    late = client.post(f"/vacancies/{vacancy_id}/refuse", headers=h(admin_key),
                       json={"reason": "too late"})
    assert late.status_code == 409


def test_who_may_read_and_who_may_hire(client, admin_key, make_pod, close, pm_factory,
                                       runtime_key):
    make_pod(1)
    make_pod(2)
    _, outsider = pm_factory("pm-2", 2)
    first, second = close(1), None
    assert client.get("/vacancies", headers=h(outsider)).status_code == 403
    assert client.post(f"/vacancies/{first}/fill", headers=h(outsider)).status_code == 403
    assert client.post(f"/vacancies/{first}/fill", headers=h(runtime_key)).status_code == 403
    assert client.get(f"/vacancies/{first}", headers=h(outsider)).status_code == 403
    hired = client.post(f"/vacancies/{first}/fill", headers=h(admin_key)).json()["agent"]["api_key"]
    mine = client.get(f"/vacancies/{first}", headers=h(hired))
    assert mine.status_code == 200 and mine.json()["post_mortem"]["pod_id"] == 1
    second = close(2)
    # another vacancy, and one that does not exist, answer alike to a pod member
    assert client.get(f"/vacancies/{second}", headers=h(hired)).status_code == 403
    assert client.get("/vacancies/99999", headers=h(hired)).status_code == 403
    assert client.get("/vacancies/99999", headers=h(admin_key)).status_code == 404
    assert len(client.get("/vacancies", headers=h(admin_key)).json()) == 2
