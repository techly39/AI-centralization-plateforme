"""RED-TEAM (idea: a manager chooses the hires) -- holes in the management law: what a freed
place's candidate list shows to the pod it hires, the pick against the Runtime's morning hire, and
the records that still say "the fittest pod's child" after the manager picked another.

Each test states the law as it should hold and FAILS on the branch as found (the severity and the
expected behaviour in its docstring). The Builder fixes the physics; these tests are not to be
weakened.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.clock import LiveClock, get_clock, set_clock
from app.config import (
    GenerationConfig,
    HiringConfig,
    ManagementConfig,
    ReproductionConfig,
    get_settings,
)
from app.db.models import Event, Pod
from app.ledger.events import EVENT_CAPITAL_SEEDED, EVENT_PITCH_SUBMITTED, append_event
from app.registry.service import get_or_create_system_agent
from app.run_clock import start_backtest

HAIKU, SONNET = "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"
BASE = {"language": "strategy-v1", "signal": "momentum", "lookback": 20, "rebalance_every": 5,
        "side": "long_only", "gross": 1.0, "universe": [f"K{k:02d}" for k in range(20)]}
#: Each pod's live rule, told apart by top_n (a pod's rule is its own: others need read_cross_pod).
RULES = {1: {**BASE, "top_n": 5}, 2: {**BASE, "top_n": 9}, 3: {**BASE, "top_n": 13}}
ROWS = [{"pod_id": 1, "pod_name": "edge", "fitness_usd": 50.0, "verdict": "stays"},
        {"pod_id": 2, "pod_name": "steady", "fitness_usd": 30.0, "verdict": "stays"},
        {"pod_id": 3, "pod_name": "weak", "fitness_usd": -10.0, "verdict": "let_go"}]


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def managed(monkeypatch, SessionFactory):
    """September 2024, the generation, reproduction (second edition) and management laws on."""
    s = get_settings()
    monkeypatch.setattr(s, "generation", GenerationConfig(on=True, grace_days=20))
    monkeypatch.setattr(s, "reproduction", ReproductionConfig(on=True, seed=11))
    monkeypatch.setattr(s, "management", ManagementConfig(on=True, other_parents=2, wait_days=1))
    monkeypatch.setattr(s, "hiring", HiringConfig(models=(HAIKU, SONNET), max_live_pods=8))
    session = SessionFactory()
    try:
        start_backtest(session, start=datetime(2024, 9, 1, tzinfo=UTC))
        session.commit()
    finally:
        session.close()
    yield
    set_clock(LiveClock())


def _seed(SessionFactory, pod_id: int) -> None:
    s = SessionFactory()
    try:
        system = get_or_create_system_agent(s)
        pitch = append_event(s, type=EVENT_PITCH_SUBMITTED, actor_agent_id=system.id, payload={
            "pod_id": pod_id, "hypothesis": "winners keep winning", "rule": RULES[pod_id]})
        append_event(s, type=EVENT_CAPITAL_SEEDED, actor_agent_id=system.id, payload={
            "pod_id": pod_id, "pitch_id": pitch.id, "seed_usd": 1_000.0, "rule": RULES[pod_id],
            "cost_at_seed_usd": 0.0})
        s.commit()
    finally:
        s.close()


def _world(SessionFactory, make_pod, pm_factory) -> int:
    """Three seeded pods (edge the fittest, steady fit, weak not); weak's place is freed at the
    month's end and its vacancy lists the candidates. The clock then reaches the place's
    fill_from morning. Returns the vacancy's id."""
    from app.capital.hiring import open_vacancy

    for pod_id, name in ((1, "edge"), (2, "steady"), (3, "weak")):
        make_pod(pod_id, name)
        pm_factory(f"pm-{name}", pod_id)
        _seed(SessionFactory, pod_id)
    s = SessionFactory()
    try:
        system = get_or_create_system_agent(s)
        s.get(Pod, 3).status = "closed"
        s.flush()
        event = open_vacancy(s, pod_id=3, actor=system, lesson={"pod_id": 3},
                             measured=(1, ROWS))
        s.commit()
        vid = event.id
        assert event.payload_json["fill_from"] == "2024-09-02"
    finally:
        s.close()
    get_clock().move_to(datetime(2024, 9, 2, 13, tzinfo=UTC))   # the place's morning
    return vid


def _candidate(client, key: str, vid: int, parent: str) -> str:
    v = client.get(f"/vacancies/{vid}", headers=h(key)).json()
    return next(c["id"] for c in v["candidates"]
                if (c["hire"].get("parent") or {}).get("pod_name") == parent)


# --- what the hired pod reads -------------------------------------------------------------------

def test_redteam_management_a_hired_pm_reads_other_live_pods_rules_in_its_vacancy(
        client, db, managed, SessionFactory, make_pod, pm_factory, admin_key):
    """SEVERITY: medium (a cross-pod read: a PM learns the live strategies of the firm's fittest
    pods, the pods it competes with for the centre's capital).

    A pod's rule is its own: another pod's pitches, research and capital row need
    ``read_cross_pod`` (app/api/pitches.py, capital_view). Under the reproduction law alone a
    child reads its own parent's rule in its vacancy -- by design, it inherits it. Under the
    management law the vacancy also lists every candidate (app/capital/management.candidates), and
    each candidate's ``hire`` carries ``parent.rule`` and ``inherited_rule`` of ANOTHER live fit
    pod. GET /vacancies/{id} (app/api/vacancies.py) hands the whole vacancy to the pod that filled
    it, so the new PM (and its analysts) reads, word for word, the live rule of up to
    ``other_parents + 1`` other pods -- whichever candidate was picked, a plain hire too.
    Expected: a pod member reads its own hire only (the picked candidate's design); the other
    candidates' designs (their parents' live rules) only with ``read_cross_pod``.
    """
    vid = _world(SessionFactory, make_pod, pm_factory)
    made = client.post(f"/vacancies/{vid}/fill", headers=h(admin_key))   # silent manager: c1
    assert made.status_code == 201, made.text
    new_pm = made.json()["agent"]["api_key"]
    seen = client.get(f"/vacancies/{vid}", headers=h(new_pm))
    assert seen.status_code == 200, seen.text
    # The new pod is edge's child: edge's rule is its inheritance. steady's live rule is not.
    leaked = RULES[2] in [c["hire"].get("parent", {}).get("rule")
                          for c in seen.json().get("candidates") or []]
    assert not leaked, ("the hired PM read steady's live rule (top_n 9) in its own vacancy's "
                        "candidate list: another pod's strategy without read_cross_pod")


# --- the pick against the Runtime's morning hire ------------------------------------------------

class _Api:
    """A FundClient over the in-process app; ``before_fill`` runs just before a fill is posted
    (the manager's call landing between the Runtime's read of the vacancies and its fill)."""

    def __init__(self, client, key: str, before_fill=None) -> None:
        self.client, self.key, self.before_fill = client, key, before_fill

    def _answer(self, r, path: str):
        from mcp_server.client import FundAPIError

        if r.status_code >= 400:
            raise FundAPIError(r.status_code, r.text, path=path)
        return r.json()

    async def get(self, path: str):
        return self._answer(self.client.get(path, headers=h(self.key)), path)

    async def post(self, path: str, body=None):
        if path.endswith("/fill") and self.before_fill is not None:
            self.before_fill()
        return self._answer(self.client.post(path, headers=h(self.key), json=body), path)

    async def aclose(self) -> None:
        return None


def test_redteam_management_a_pick_during_the_morning_hire_splits_the_ledger_and_the_mind(
        client, db, managed, SessionFactory, make_pod, pm_factory, admin_key, agent_factory):
    """SEVERITY: medium (a wrong record a firm agent reaches: the ledger's design of a pod is not
    the mind the Runtime runs in it).

    The pick is taken while the place is open (app/capital/management.pick), with no end to the
    manager's day: on and after ``fill_from`` too, i.e. while the Runtime's morning hire is under
    way. The Runtime (runtime/onboarding.Onboarding._one) reads the vacancy's ``hire`` from its
    GET /vacancies listing BEFORE it posts the fill, and builds the new PM from that read: its
    spec's model (spec_for), its first input's parent, change, inherited rule and inherited
    attempts, and the brief. Physics' fill (app/capital/hiring.fill) re-reads the vacancy under
    OMS_LOCK and so hires the pick. A manager (a mind on an MCP key, which physics does not
    schedule) that picks in that window makes the ledger say "a child of steady, steady's family
    attempts in its N, on steady's model" while the mind is told it is edge's child, given edge's
    rule and attempts, runs the default's model, and never gets the brief.
    Expected: the new PM's mind and input are what physics hired (one of: physics refuses a pick
    once the place's fill_from morning has come, so the hire is fixed when the Runtime may read
    it; or the Runtime builds the spec and the input from the fill's answer, not from its earlier
    listing; or the fill takes the hire the Runtime read and answers 409 when it changed).
    """
    from app.capital.reproduction import hire_of
    from runtime.governance import Governance
    from runtime.onboarding import HireTemplate, Onboarding

    vid = _world(SessionFactory, make_pod, pm_factory)
    _, manager = agent_factory("the-manager", "manager")
    steady_child = _candidate(client, admin_key, vid, "steady")

    def manager_picks() -> None:     # whatever physics answers: the test reads the outcome
        client.post(f"/vacancies/{vid}/pick", headers=h(manager),
                    json={"candidate": steady_child, "brief": "Trade like steady, slower."})

    registrar = _Api(client, admin_key, before_fill=manager_picks)
    hiring = Onboarding(HireTemplate(provider="scripted", script="pitch-pm"),
                        registrar=registrar, connect=lambda key: _Api(client, key))

    async def morning():
        listed = await registrar.get("/vacancies")
        vacancy = next(v for v in listed if v["id"] == vid)
        return await hiring._one(0, vacancy, set(), [],
                                 Governance(False, 1.0, max_agents_total=50))

    record, mind = asyncio.run(morning())
    assert record.outcome == "hired" and mind is not None, record
    db.expire_all()
    pod_id = mind.spec.pod
    hired = hire_of(db, pod_id)          # what physics hired, and what the ledger will judge
    told = hiring.inputs[mind.spec.id]   # what the Runtime hands the new PM's every wake
    picked = any(e.payload_json.get("vacancy_id") == vid for e in db.scalars(
        select(Event).where(Event.type == "hire_picked")))
    assert (told.get("parent") or {}).get("pod_name") == hired["parent"]["pod_name"], (
        f"physics hired a child of {hired['parent']['pod_name']} (its N counts that family's "
        f"{hired['lineage_attempts']} attempts) but the Runtime told the new PM it is a child of "
        f"{(told.get('parent') or {}).get('pod_name')} with that pod's rule")
    assert told.get("inherited_rule") == hired["inherited_rule"]
    assert told.get("lineage_attempts") == hired["lineage_attempts"]
    if picked:
        assert (told.get("brief") or {}).get("text") == "Trade like steady, slower.", (
            "physics recorded the manager's brief; the new PM's input never carried it")


# --- the records that still say "the fittest" ---------------------------------------------------

def _picked_and_filled(client, admin_key, agent_factory, vid: int) -> tuple[int, str]:
    _, manager = agent_factory("the-manager", "manager")
    steady_child = _candidate(client, admin_key, vid, "steady")
    r = client.post(f"/vacancies/{vid}/pick", headers=h(manager),
                    json={"candidate": steady_child, "brief": "slower"})
    assert r.status_code == 200, r.text
    made = client.post(f"/vacancies/{vid}/fill", headers=h(admin_key))
    assert made.status_code == 201, made.text
    return made.json()["agent"]["pod_id"], made.json()["agent"]["api_key"]


def test_redteam_management_the_family_tree_draws_a_picked_child_under_the_defaults_parent(
        client, db, managed, SessionFactory, make_pod, pm_factory, admin_key, agent_factory):
    """SEVERITY: low (mislabels a record: the generation report's family tree, the very record
    on which "does a manager pick better than the law" is read).

    app/capital/report.family_tree reads each filled pod's parent and change from the vacancy's
    OPENED hire (``opened[vacancy_id]["hire"]``), never through the pick (reproduction.hire_of /
    with_pick, which design_of and the deflated Sharpe's N use). A child of steady the manager
    picked is drawn as edge's child with edge-child's change; a picked plain hire as edge's child.
    Expected: the tree draws every hired pod under the parent and change it was hired with
    (hire_of), the same as its design.
    """
    from app.capital.report import family_tree

    vid = _world(SessionFactory, make_pod, pm_factory)
    pod_id, _ = _picked_and_filled(client, admin_key, agent_factory, vid)
    db.expire_all()

    def find(nodes, parent=None):
        for node in nodes:
            if node["pod_id"] == pod_id:
                return parent, node
            got = find(node["children"], node["pod_id"])
            if got is not None:
                return got
        return None

    parent, node = find(family_tree(db))
    assert parent == 2 and node["parent"] == 2, (
        f"the manager picked steady's child; the family tree draws it under pod {parent} "
        f"(change {node['change']})")


def test_redteam_management_a_picked_child_is_told_its_parent_is_the_fittest_pod(
        client, db, managed, SessionFactory, make_pod, pm_factory, admin_key, agent_factory):
    """SEVERITY: low (mislabels what a PM is told about its own design).

    app/capital/generation._your_pod writes the child's family note as "Your pod is a child of
    {parent}, the fittest pod of generation {g}", and the generation law's text in every capital
    view still says "the hire into a freed place is a child of the fittest pod of the generation
    last measured". Under the management law the manager picks a child of another fit pod: the
    new PM is told steady (fitness $30) was the fittest when edge ($50) was.
    Expected: the note and the law's words say how the parent was chosen (the law's fittest, or
    the manager's pick among the fit pods).
    """
    vid = _world(SessionFactory, make_pod, pm_factory)
    _, new_pm = _picked_and_filled(client, admin_key, agent_factory, vid)
    view = client.get("/capital", headers=h(new_pm))
    assert view.status_code == 200, view.text
    note = view.json()["generation"]["your_pod"]["family"]["note"]
    assert "child of steady" in note, note
    assert "the fittest pod" not in note, (
        f"steady's child is told: {note!r} -- edge, not steady, was the fittest of generation 1")
