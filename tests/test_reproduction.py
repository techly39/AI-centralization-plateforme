"""Designs reproduce: the founding model on the record, the one change, the parent, the frozen law.
The end-to-end proof is ``acceptance/designs_reproduce.py`` (scripted months on a made-up market:
children, the plain hire, the family's attempts, diversity and its collapse, the law off)."""

from __future__ import annotations

from sqlalchemy import select

from app.capital.reproduction import changes, choose_parent, reproduction_law
from app.config import ReproductionConfig, get_settings
from app.db.models import Agent, AgentStatus, Event, Pod
from app.ledger.events import EVENT_VACANCY_OPENED, append_event

HAIKU, SONNET = "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"
RULE = {"language": "strategy-v1", "signal": "momentum", "lookback": 20, "rebalance_every": 5,
        "side": "long_only", "gross": 1.0, "top_n": 5,
        "universe": [f"K{k:02d}" for k in range(20)]}


def h(key: str) -> dict:
    return {"X-API-Key": key}


def _registered(db, name: str) -> dict:
    return next(e.payload_json for e in db.scalars(select(Event).where(
        Event.type == "agent_registered")) if e.payload_json["name"] == name)


def test_a_registrar_declares_a_founding_pms_model_and_only_when_it_does(
        client, db, admin_key, make_pod):
    make_pod(1)
    r = client.post("/agents/register", headers=h(admin_key),
                    json={"name": "pm-a", "role": "pm", "pod_id": 1, "model": HAIKU})
    assert r.status_code == 201, r.text
    assert client.post("/agents/register", headers=h(admin_key),
                       json={"name": "pm-b", "role": "pm", "pod_id": 1}).status_code == 201
    assert _registered(db, "pm-a")["model"] == HAIKU
    assert "model" not in _registered(db, "pm-b")      # an older run's record, unchanged
    bad = client.post("/agents/register", headers=h(admin_key),
                      json={"name": "pm-c", "role": "pm", "pod_id": 1, "model": "a model; rm"})
    assert bad.status_code == 422


def test_every_change_is_one_step_and_valid():
    found = {(c["what"], c["to"]) for c in changes({"model": HAIKU, "rule": RULE},
                                                   (HAIKU, SONNET, HAIKU))}
    assert found == {("model", SONNET), ("lookback", 10), ("lookback", 40),
                     ("rebalance_every", 2), ("rebalance_every", 10), ("top_n", 4), ("top_n", 6)}
    # every name already held: no "one more"; an undeclared model: no model change
    full = {**RULE, "top_n": 20, "lookback": 250}
    found = {(c["what"], c["to"]) for c in changes({"model": None, "rule": full}, (HAIKU, SONNET))}
    assert found == {("lookback", 120), ("rebalance_every", 2), ("rebalance_every", 10),
                     ("top_n", 19)}
    # a lookback off the ladder moves to the nearest rung on each side
    found = {c["to"] for c in changes({"model": None, "rule": {**RULE, "lookback": 30}}, ())
             if c["what"] == "lookback"}
    assert found == {20, 40}
    assert changes({"model": None, "rule": None}, (HAIKU, SONNET)) == []


def test_the_parent_is_the_fittest_living_pod_above_zero(db, make_pod, pm_factory, admin_key):
    for pod, name in ((1, "a"), (2, "b"), (3, "c"), (4, "d")):
        make_pod(pod, name)
        pm_factory(f"pm-{name}", pod)

    def row(pod: int, name: str, fitness, verdict: str = "stays") -> dict:
        return {"pod_id": pod, "pod_name": name, "fitness_usd": fitness, "verdict": verdict}

    rows = [row(1, "a", 50.0), row(2, "b", 50.0), row(3, "c", 900.0, "let_go"),
            row(4, "d", None, "too_new")]
    # the let-go pod is not alive; a tie goes to the older pod
    assert choose_parent(db, generation=1, rows=rows)["pod_name"] == "a"
    # a closed pod, or one whose PM is gone, is not alive
    db.get(Pod, 1).status = "closed"
    db.flush()
    assert choose_parent(db, generation=1, rows=rows)["pod_name"] == "b"
    db.scalar(select(Agent).where(Agent.name == "pm-b")).status = AgentStatus.inactive
    db.flush()
    assert choose_parent(db, generation=1, rows=rows) is None
    # nobody earned more than it thought: no parent
    assert choose_parent(db, generation=1, rows=[row(2, "b", 0.0), row(1, "a", -5.0)]) is None


def test_the_law_is_frozen_into_the_first_vacancy(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "reproduction", ReproductionConfig(on=True, seed=3))
    assert reproduction_law(db) == ReproductionConfig(on=True, seed=3)
    append_event(db, type=EVENT_VACANCY_OPENED, actor_agent_id=None, payload={
        "vacancy_no": 1, "pod_id": 1, "pod_name": "x", "post_mortem": {}, "hire": {}, "law": {}})
    db.flush()
    # a run whose first vacancy was opened with the law off stays off
    assert reproduction_law(db).on is False


def test_the_family_tree_is_drawn_from_the_ledger_alone(db):
    """A recording holds events, not pod rows: the tree's pods, names, stages and models are the
    events' (pods 41-43 have no row here)."""
    from app.capital.report import family_tree

    def add(type_: str, payload: dict) -> Event:
        return append_event(db, type=type_, actor_agent_id=None, payload=payload)

    add("agent_registered", {"agent_id": 901, "name": "pm-41", "role": "pm", "pod_id": 41,
                             "model": HAIKU})
    add("agent_registered", {"agent_id": 902, "name": "pm-42", "role": "pm", "pod_id": 42})
    add("capital_seeded", {"pod_id": 41, "pitch_id": 1, "seed_usd": 1.0, "rule": RULE})
    add("generation_ended", {"generation": 1, "pods": [
        {"pod_id": 41, "pod_name": "edge"}, {"pod_id": 42, "pod_name": "noise"}]})
    add("pm_let_go", {"pod_id": 42, "pod_name": "noise", "pod_closed": True})
    child = {**RULE, "lookback": 40}
    opened = add(EVENT_VACANCY_OPENED, {"hire": {
        "design": "child", "model": HAIKU, "inherited_rule": child,
        "parent": {"pod_id": 41, "pod_name": "edge"}, "family": {"pod_id": 41, "pod_name": "edge"},
        "change": {"what": "lookback", "from": 20, "to": 40}}})
    add("vacancy_filled", {"vacancy_id": opened.id, "pod_id": 43, "pod_name": "hire-1"})
    db.flush()
    assert db.scalar(select(Pod).where(Pod.id.in_([41, 42, 43]))) is None
    tree = {n["pod_name"]: n for n in family_tree(db)}
    assert set(tree) == {"edge"}       # noise ran nothing (no model, no rule): a spare, left out
    edge = tree["edge"]
    assert (edge["model"], edge["stage"], edge["rule"]) == (HAIKU, "active", RULE)
    assert [(c["pod_name"], c["model"], c["change"]["to"]) for c in edge["children"]] == [
        ("hire-1", HAIKU, 40)]
