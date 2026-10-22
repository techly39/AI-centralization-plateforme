"""A manager chooses the hires (app/capital/management.py): who may be the manager and what it may
not do, the pick's refusals, the place's day of waiting, the direction and the brief. The end to
end proof is ``acceptance/manager_chooses_hires.py`` (scripted months: the pick hired, the silent
manager's default, the law off)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.db.models import Event
from app.ledger.events import EVENT_VACANCY_OPENED, append_event
from app.run_clock import start_backtest

HAIKU, SONNET = "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"


def h(key: str) -> dict:
    return {"X-API-Key": key}


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


@pytest.fixture
def manager(agent_factory) -> tuple[int, str]:
    return agent_factory("the-manager", "manager")


def _types(db, type_: str) -> list[dict]:
    db.expire_all()
    return [e.payload_json for e in db.scalars(select(Event).where(Event.type == type_)
                                               .order_by(Event.id))]


def _listed_vacancy(SessionFactory, *, candidates: bool = True, fill_from: str = "2024-09-02"
                    ) -> int:
    """A vacancy as the management law opens one (the default c1, a plain Sonnet hire c2)."""
    s = SessionFactory()
    try:
        hire = {"pod_name": "hire-1", "pm_name": "hire-1-pm", "role": "pm", "model": HAIKU,
                "budget_usd": 0.5, "charter": "trade"}
        listed = {"candidates": [
            {"id": "c1", "default": True, "what": "a plain hire on haiku", "hire": {"model": HAIKU}},
            {"id": "c2", "default": False, "what": "a plain hire on sonnet",
             "hire": {"model": SONNET}}],
            "fill_from": fill_from, "management": {"on": True}} if candidates else {}
        event = append_event(s, type=EVENT_VACANCY_OPENED, actor_agent_id=None, payload={
            "vacancy_no": 1, "pod_id": 1, "pod_name": "pod-1", "post_mortem": {}, "hire": hire,
            "law": {}, **listed})
        s.commit()
        return event.id
    finally:
        s.close()


def test_only_the_operators_registrar_makes_the_manager_and_it_has_no_pod(
        client, db, admin_key, agent_factory, make_pod):
    make_pod(1)
    assert client.post("/agents/register", headers=h(admin_key), json={
        "name": "m", "role": "manager", "pod_id": 1}).status_code == 422
    # a management agent another agent made is not the firm's management
    _, other = agent_factory("mgmt-2", "management")
    r = client.post("/agents/register", headers=h(other), json={"name": "m", "role": "manager"})
    assert r.status_code == 403
    assert any(e["detail"].startswith("only the operator's registrar makes the firm's manager")
               for e in _types(db, "permission_denied"))
    assert client.post("/agents/register", headers=h(admin_key),
                       json={"name": "m", "role": "manager"}).status_code == 201


def test_the_manager_reads_every_pod_but_registers_deactivates_trades_and_fills_nothing(
        client, db, september, make_pod, pm_factory, manager, SessionFactory):
    make_pod(1)
    pm_id, pm_key = pm_factory("pm-1", 1)
    _, key = manager
    board = client.get("/board", headers=h(key))
    assert board.status_code == 200, board.text
    assert [p["pod_name"] for p in board.json()["pods"]] == ["pod-1"]
    assert board.json()["pods"][0]["pms"] == ["pm-1"]
    assert board.json()["direction"] is None
    vid = _listed_vacancy(SessionFactory)
    for method, path, body in (
            ("post", "/agents/register", {"name": "x", "role": "pm", "pod_id": 1}),
            ("post", f"/agents/{pm_id}/deactivate", None),
            ("post", "/orders", {"ticker": "AAA", "side": "buy", "qty": 1,
                                 "price_type": "market", "justification": "x"}),
            ("post", f"/vacancies/{vid}/fill", None),
            ("post", f"/vacancies/{vid}/refuse", {"reason": "x"}),
            ("post", "/pitches", {"hypothesis": "x", "data_needed": "x", "team": "x",
                                  "budget_usd": 0.0, "rule": {}}),
            ("post", "/research/backtests", {"rule": {}}),
            ("post", "/team/analysts", {"charter": "x", "model": HAIKU, "budget_usd": 0.1})):
        r = getattr(client, method)(path, headers=h(key), json=body)
        assert r.status_code == 403, (path, r.status_code, r.text)
    # a PM neither reads the board nor picks nor sets the direction
    assert client.get("/board", headers=h(pm_key)).status_code == 403
    assert client.post(f"/vacancies/{vid}/pick", headers=h(pm_key),
                       json={"candidate": "c2"}).status_code == 403
    assert client.post("/direction", headers=h(pm_key), json={"text": "x"}).status_code == 403
    assert _types(db, "hire_picked") == [] and _types(db, "direction_set") == []


def test_the_registrar_cannot_pick_or_set_the_direction(september, client, SessionFactory,
                                                         admin_key):
    vid = _listed_vacancy(SessionFactory)
    assert client.post(f"/vacancies/{vid}/pick", headers=h(admin_key),
                       json={"candidate": "c2"}).status_code == 403
    assert client.post("/direction", headers=h(admin_key), json={"text": "x"}).status_code == 403


def test_a_pick_is_one_of_the_list_once_while_the_place_waits(
        client, db, september, manager, SessionFactory, admin_key):
    _, key = manager
    vid = _listed_vacancy(SessionFactory)
    # the place waits for its manager's day: the registrar's fill is not yet taken (no refusal)
    early = client.post(f"/vacancies/{vid}/fill", headers=h(admin_key))
    assert early.status_code == 409 and "waits for the manager's pick" in early.json()["detail"]
    assert _types(db, "hire_refused") == []
    bad = client.post(f"/vacancies/{vid}/pick", headers=h(key), json={"candidate": "c9"})
    assert bad.status_code == 409 and "not a candidate" in bad.json()["detail"]
    ok = client.post(f"/vacancies/{vid}/pick", headers=h(key),
                     json={"candidate": "c2", "brief": "  trade the slow names  "})
    assert ok.status_code == 200, ok.text
    v = ok.json()
    assert v["picked"]["candidate"] == "c2" and v["picked"]["brief"] == "trade the slow names"
    # the hire is the pick's design under the place's own names, budget and charter
    assert v["hire"] == {"pod_name": "hire-1", "pm_name": "hire-1-pm", "role": "pm",
                         "budget_usd": 0.5, "charter": "trade", "model": SONNET}
    again = client.post(f"/vacancies/{vid}/pick", headers=h(key), json={"candidate": "c1"})
    assert again.status_code == 409 and "picked once" in again.json()["detail"]
    assert [r["candidate"] for r in _types(db, "hire_pick_refused")] == ["c9", "c1"]
    assert len(_types(db, "hire_picked")) == 1


def test_a_place_the_law_did_not_list_cannot_be_picked(client, db, september, manager,
                                                        SessionFactory):
    _, key = manager
    vid = _listed_vacancy(SessionFactory, candidates=False)
    r = client.post(f"/vacancies/{vid}/pick", headers=h(key), json={"candidate": "c1"})
    assert r.status_code == 409 and "lists no candidates" in r.json()["detail"]
    assert client.post("/vacancies/999/pick", headers=h(key),
                       json={"candidate": "c1"}).status_code == 404


def test_the_direction_is_in_every_capital_view_once_written(
        client, db, september, make_pod, pm_factory, manager):
    make_pod(1)
    _, pm_key = pm_factory("pm-1", 1)
    _, key = manager
    assert "direction" not in client.get("/capital", headers=h(pm_key)).json()
    assert client.get("/direction", headers=h(pm_key)).json() == {"direction": None}
    assert client.post("/direction", headers=h(key), json={"text": "   "}).status_code == 422
    r = client.post("/direction", headers=h(key), json={"text": "Fewer names, slower turnover."})
    assert r.status_code == 201, r.text
    client.post("/direction", headers=h(key), json={"text": "Cut costs."})
    seen = client.get("/capital", headers=h(pm_key)).json()["direction"]
    assert (seen["direction_no"], seen["text"], seen["by"]) == (2, "Cut costs.", "the-manager")


def test_the_managers_thinking_is_the_centres_not_a_pods(
        client, db, september, make_pod, pm_factory, manager, runtime_key):
    make_pod(1)
    pm_id, _ = pm_factory("pm-1", 1)
    manager_id, key = manager
    runtime = runtime_key
    for agent, usd in ((manager_id, 0.30), (pm_id, 0.05)):
        assert client.post("/metering/usage", headers=h(runtime), json={
            "agent_id": agent, "key_ref": f"k{agent}",
            "usd_micros_total": round(usd * 1e6)}).status_code == 200
    board = client.get("/board", headers=h(key)).json()
    assert board["centre"]["thinking_usd"] == pytest.approx(0.30)
    assert board["pods"][0]["thinking_usd"] == pytest.approx(0.05)


def test_the_scripted_manager_picks_the_other_child_or_stays_silent():
    import json

    from runtime.providers import CompletionRequest, Message
    from runtime.scripted import firm_manager

    board = {"direction": None, "open_vacancies": [{"id": 7, "picked": None, "candidates": [
        {"id": "c1", "default": True, "what": "a child of edge (...)"},
        {"id": "c2", "default": False, "what": "a child of steady (...)"},
        {"id": "c3", "default": False, "what": "a plain hire on x"}]}]}

    def reply(given: dict):
        first = Message(role="user", content=json.dumps({"me": {}, "input": {"manager": given}}))
        asked = firm_manager(CompletionRequest(model=None, messages=[first]))
        done = [first, Message(role="assistant", content=asked.content,
                               tool_calls=asked.tool_calls),
                Message(role="tool", content=json.dumps(board), tool_call_id="board")]
        return firm_manager(CompletionRequest(model=None, messages=done)).tool_calls

    calls = reply({"pick": "other_child", "brief": "b", "direction": "d"})
    assert [(c.name, c.arguments) for c in calls] == [
        ("set_direction", {"text": "d"}),
        ("pick_hire", {"vacancy_id": 7, "candidate": "c2", "brief": "b"})]
    assert reply({}) == []
