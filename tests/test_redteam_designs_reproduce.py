"""RED-TEAM (idea: designs reproduce) -- holes in the reproduction law: who may put a founding
model on the record, what ``design_of`` reads as a pod's design, the child's "exactly one change",
and the family's attempts in the deflated Sharpe's N.

Each test states the law as it should hold and FAILS on the branch as found (strict xfail, the
severity in the reason). The Builder fixes the physics; these tests are not to be weakened.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import GenerationConfig, HiringConfig, ReproductionConfig, get_settings
from app.db.models import Event, Pod
from app.ledger.events import (
    EVENT_CAPITAL_SEEDED,
    EVENT_PITCH_SUBMITTED,
    EVENT_RESEARCH_BACKTEST_RUN,
    append_event,
)
from app.registry.service import get_or_create_system_agent

HAIKU, SONNET, OPUS = ("anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5",
                       "anthropic/claude-opus-5")
RULE = {"language": "strategy-v1", "signal": "momentum", "lookback": 20, "rebalance_every": 5,
        "side": "long_only", "gross": 1.0, "top_n": 5,
        "universe": [f"K{k:02d}" for k in range(20)]}


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def reproduction_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "generation", GenerationConfig(on=True, grace_days=20))
    monkeypatch.setattr(s, "reproduction", ReproductionConfig(on=True, seed=11))
    monkeypatch.setattr(s, "hiring", HiringConfig(models=(HAIKU, SONNET), max_live_pods=8))


def _registered(db, name: str) -> dict:
    return next(e.payload_json for e in db.scalars(select(Event).where(
        Event.type == "agent_registered").order_by(Event.id)) if e.payload_json["name"] == name)


def _seed(SessionFactory, pod_id: int, *, research: int = 0) -> None:
    """The capital machine's seed of ``pod_id`` with RULE, after ``research`` backtests."""
    s = SessionFactory()
    try:
        system = get_or_create_system_agent(s)
        for k in range(research):
            append_event(s, type=EVENT_RESEARCH_BACKTEST_RUN, actor_agent_id=system.id, payload={
                "pod_id": pod_id, "agent_id": system.id, "attempt": k + 1, "rule": RULE})
        pitch = append_event(s, type=EVENT_PITCH_SUBMITTED, actor_agent_id=system.id, payload={
            "pod_id": pod_id, "hypothesis": "winners keep winning", "rule": RULE})
        append_event(s, type=EVENT_CAPITAL_SEEDED, actor_agent_id=system.id, payload={
            "pod_id": pod_id, "pitch_id": pitch.id, "seed_usd": 1_000.0, "rule": RULE,
            "cost_at_seed_usd": 0.0})
        s.commit()
    finally:
        s.close()


def _free_a_place(SessionFactory, pod_id: int, rows: list[dict]) -> dict:
    """A month's end let ``pod_id``'s PM go: its pod closes and the vacancy names its hire, a child
    of the fittest of ``rows`` (generation 1). Returns the vacancy's hire."""
    from app.capital.hiring import open_vacancy

    s = SessionFactory()
    try:
        system = get_or_create_system_agent(s)
        s.get(Pod, pod_id).status = "closed"
        s.flush()
        event = open_vacancy(s, pod_id=pod_id, actor=system, lesson={"pod_id": pod_id},
                             measured=(1, rows))
        s.commit()
        return {"id": event.id, **event.payload_json["hire"]}
    finally:
        s.close()


def _row(pod_id: int, name: str, fitness: float) -> dict:
    return {"pod_id": pod_id, "pod_name": name, "fitness_usd": fitness, "verdict": "stays"}


# --- who puts a founding model on the record ----------------------------------------------------

def test_redteam_reproduction_a_firm_management_mind_declares_a_model_on_the_record(
        client, db, make_pod, agent_factory):
    """SEVERITY: medium (a firm mind writes the record a future hire's model is read from).

    The law: "A registrar may declare a founding PM's model at registration; the Runtime declares
    it only under the reproduction law". The route (app/api/agents.py register) checks only
    ``REGISTER_AGENTS`` -- which a firm management mind holds -- and app/registry/permissions.py
    says nothing about ``model``. Hiring was gated to the operator's registrar
    (permissions.may_hire) for exactly this reason: a firm mind does not decide a hire. Yet a
    management mind registers an agent into a founding pod whose PM declared no model (any
    scripted/fake-metered spec: provision declares only ``spec.model``) with ``model`` of its
    choosing; ``design_of`` reads it as the pod's design, and when the pod is the month's fittest
    its child is hired on that model (onboarding.spec_for takes ``hire["model"]``), a model the
    hiring law's pool never named. Expected: a declared model only from the operator's registrar
    (``registered_by_operator``), only for a PM, refused (403) otherwise.
    """
    make_pod(1, "edge")
    _, cio = agent_factory("cio", "management")          # a firm mind, not the operator's
    r = client.post("/agents/register", headers=h(cio), json={
        "name": "edge-helper", "role": "pm", "pod_id": 1, "model": OPUS})
    db.expire_all()
    declared = r.status_code == 201 and _registered(db, "edge-helper").get("model") == OPUS
    assert not declared, (
        f"a management mind made over HTTP declared {OPUS!r} on the record "
        f"({r.status_code}); only the operator's registrar declares a founding model")


def test_redteam_reproduction_an_analysts_declared_model_becomes_its_pods_design(
        client, db, SessionFactory, make_pod, admin_key, reproduction_on):
    """SEVERITY: medium (a wrong record that picks the model a child is hired on).

    ``design_of`` (app/capital/reproduction.py) takes the FIRST ``agent_registered`` naming the pod
    with a model -- any role. The Runtime's provision registers specs sorted by spec id and, under
    the law, declares every spec's model, analysts' too: ``analyst-edge`` sorts before ``pm-edge``,
    so the pod "edge" is recorded as running the analyst's model, not its PM's. The analyst runs
    no pod. When edge is the fittest, its child is hired on the analyst's model and the family
    tree draws edge with it. (The same with a management mind registering an analyst into a
    founding pod first.) Expected: a pod's founding design is its PM's model.
    """
    from app.capital.reproduction import design_of
    from app.ledger.events import append_event

    make_pod(1, "edge")
    # Fixed at two layers: the route refuses an analyst's model (only a PM's is declared) ...
    r = client.post("/agents/register", headers=h(admin_key), json={
        "name": "analyst-edge", "role": "analyst", "pod_id": 1, "model": OPUS})
    assert r.status_code == 403, r.text
    # ... and a design reads only a PM's registration, even if an analyst's model were on record.
    with SessionFactory() as s:
        append_event(s, type="agent_registered", actor_agent_id=None, payload={
            "agent_id": 9999, "name": "analyst-edge", "role": "analyst", "pod_id": 1,
            "model": OPUS})
        s.commit()
    r = client.post("/agents/register", headers=h(admin_key), json={
        "name": "pm-edge", "role": "pm", "pod_id": 1, "model": HAIKU})
    assert r.status_code == 201, r.text
    _seed(SessionFactory, 1)
    db.expire_all()
    assert design_of(db, 1)["model"] == HAIKU, (
        f"pod edge's PM runs {HAIKU}; its design on the record is {design_of(db, 1)['model']!r} "
        f"(its analyst's)")


# --- the child's one change ---------------------------------------------------------------------

# Fixed in cycle 66 (the reproduction law's second edition).
def test_redteam_reproduction_a_child_of_an_undeclared_model_differs_in_two_things(
        client, db, SessionFactory, make_pod, pm_factory, reproduction_on):
    """SEVERITY: low (a mislabelled record: "exactly one change" is not what was hired).

    A founding PM registered without ``model`` (every scripted world, the B0 rehearsal's own) has
    ``design.model = None``. ``changes`` then offers no model change, so the draw changes a rule
    setting -- and ``open_vacancy`` fills the missing model from the hiring pool
    (``child["model"] or hire["model"]``). The child differs from its parent in the model AND in
    the drawn setting, while the vacancy, the family tree and the child's own view name one
    change. Expected: no parent without a declared model (the plain hire), or the model recorded
    as part of the change.
    """
    make_pod(1, "edge")
    pm_factory("pm-edge", 1)                              # no model declared
    make_pod(2, "noise")
    _seed(SessionFactory, 1)
    hire = _free_a_place(SessionFactory, 2, [_row(1, "edge", 500.0)])
    assert hire["design"] == "child", hire
    parent_model = hire["parent"]["model"]
    assert hire["model"] == parent_model or hire["change"]["what"] == "model", (
        f"the child runs {hire['model']!r}, its parent {parent_model!r}, and its one recorded "
        f"change is {hire['change']['what']} {hire['change']['from']} -> {hire['change']['to']}")


# --- the family's attempts ----------------------------------------------------------------------

# Fixed in cycle 66 (the reproduction law's second edition).
def test_redteam_reproduction_a_siblings_attempts_vanish_from_the_familys_count(
        client, db, SessionFactory, make_pod, admin_key, pm_factory, reproduction_on):
    """SEVERITY: medium (trials split across correlated clones: a lower deflated-Sharpe N).

    The law: "a rule chosen as the best of a family has been tried by the family ... every pitch
    of the child counts them". ``child_of`` freezes ``pod_attempts(parent)`` only: the parent's own
    and its ancestors'. A first child of edge spends 40 research backtests (and pitches) tuning
    the family's rule and is let go (or its hire fails and the vacancy reopens); the next child of
    edge is born with N = edge's attempts alone. It reads its sibling's pitches -- rules and the
    gates they failed -- in the library, and re-pitches the best one with the small N: the
    family's 40 tries are hidden by being made under another name. Expected: a child's N counts
    every attempt of its family made before it was born (siblings and failed hires included).
    """
    make_pod(1, "edge")
    pm_factory("pm-edge", 1)
    _seed(SessionFactory, 1, research=3)                  # edge: 3 backtests + 1 pitch
    rows = [_row(1, "edge", 500.0)]
    make_pod(2, "noise-a")
    first = _free_a_place(SessionFactory, 2, rows)
    assert first["design"] == "child" and first["lineage_attempts"] == 4, first
    made = client.post(f"/vacancies/{first['id']}/fill", headers=h(admin_key))
    assert made.status_code == 201, made.text
    sibling = made.json()["agent"]["pod_id"]
    s = SessionFactory()
    try:
        system = get_or_create_system_agent(s)
        for k in range(40):                               # the first child tunes the family's rule
            append_event(s, type=EVENT_RESEARCH_BACKTEST_RUN, actor_agent_id=system.id, payload={
                "pod_id": sibling, "agent_id": made.json()["agent"]["id"], "attempt": 5 + k,
                "rule": {**RULE, "lookback": 40}})
        s.commit()
    finally:
        s.close()
    make_pod(20, "noise-b")
    second = _free_a_place(SessionFactory, 20, rows)
    assert second["design"] == "child" and second["family"]["pod_name"] == "edge", second
    assert second["lineage_attempts"] >= 4 + 40, (
        f"edge's family made 4 attempts in edge and 40 in its first child before the second child "
        f"was born; the second child's pitches count {second['lineage_attempts']}")


# --- the parent ---------------------------------------------------------------------------------

def test_redteam_reproduction_a_pod_whose_pm_is_gone_still_fathers_the_hire(
        client, db, SessionFactory, make_pod, admin_key, agent_factory, reproduction_on):
    """SEVERITY: low (a wrong parent: the law's "a PM still working there" is not what is checked).

    The law (reproduction.py docstring, 2.): the parent is the fittest pod "still alive (not
    closed, a PM still working there, not let go)". ``_alive`` checks for ANY active agent. A
    vacancy opened mid-month (the ladder closes a pod) reads last month's table: the fittest pod's
    PM has since been deactivated (by management, or its key retired) and only its analyst is
    left, yet the pod is chosen and its design reproduced. Expected: no PM working there, no
    parent (the next fittest, or the plain hire).
    """
    from app.capital.reproduction import choose_parent

    make_pod(1, "edge")
    pm_id, _ = agent_factory("pm-edge", "pm", 1)
    agent_factory("analyst-edge", "analyst", 1)
    _seed(SessionFactory, 1)
    assert client.post(f"/agents/{pm_id}/deactivate", headers=h(admin_key)).status_code == 200
    db.expire_all()
    parent = choose_parent(db, generation=1, rows=[_row(1, "edge", 500.0)])
    assert parent is None, (
        f"edge's only PM is gone (an analyst is left); {parent['pod_name']!r} was still chosen as "
        f"the parent")
