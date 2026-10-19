"""RED-TEAM (idea: a dead pod is replaced) -- holes in the vacancy / fill physics.

Each test states the law as it should hold and FAILS on the branch as found. The Builder fixes the
physics; these tests are not to be weakened. Severity is in each test's docstring.

A close is staged in the ledger directly, as tests/test_hiring.py does.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.capital.allocation import PodTrack
from app.capital.hiring import open_vacancy
from app.db.models import Agent, Pod
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


def _close(SessionFactory, pod_id: int) -> int:
    """Stage a seeded pod's close and open its vacancy as the capital machine does."""
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
                          days=("2025-01-02",), returns=(-0.12,), cost_usd=0.0, drawdown=0.12)
        event = open_vacancy(s, pod_id=pod_id, record=record, actor=system)
        s.commit()
        return event.id
    finally:
        s.close()


def test_redteam_a_firm_management_mind_cannot_take_a_hire_the_runtime_refused(
        client, SessionFactory, make_pod, admin_key, agent_factory):
    """SEVERITY: high (an agent acts as another identity; the Runtime's cap refusal is routed
    around).

    The Runtime refuses a hire because its budget does not fit the cap: "no agent, no key". The
    vacancy stays open, and physics lets ANY holder of register_agents fill it. A firm management
    mind (a run may hold one: AgentSpec role "management") fills it on its next wake and is handed
    the new PM's key: it now holds a second identity, a PM in a brand-new pod that can pitch and
    earn a seed from the centre, with no metered mind behind it. Physics cannot tell the
    Runtime's registrar from a firm management mind (both are role management), so the refusal
    binds nobody. (Root: /agents/register already gives management PM keys in existing pods; a
    fill adds a new pod, which no HTTP route could make before.)
    """
    make_pod(1)
    vacancy_id = _close(SessionFactory, 1)
    refused = client.post(f"/vacancies/{vacancy_id}/refuse", headers=h(admin_key),
                          json={"reason": "the new PM's thinking budget does not fit the cap"})
    assert refused.status_code == 200
    _, cio = agent_factory("cio", "management")          # a firm mind, not the Runtime
    taken = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(cio))
    assert taken.status_code == 403, (
        "a firm management mind filled the vacancy the Runtime refused and holds the new PM's "
        f"key: {taken.status_code} {taken.text[:200]}")


def test_redteam_a_hire_whose_pm_is_deactivated_does_not_leave_a_filled_vacancy_and_a_live_pod(
        client, SessionFactory, make_pod, admin_key):
    """SEVERITY: medium (a wrong record an agent can reach, and a pod-limit slot leaked forever).

    The Runtime's own key_over_cap path fills the vacancy, then deactivates the new PM (no PM
    lives without a mind); any management agent can deactivate a hired PM at will too. The
    vacancy then reads "filled" forever though nobody works there, so the dead pod is never
    replaced; and the empty pod is "active", so it counts against max_live_pods for the rest of
    the run. Expected: the vacancy is open again (or the empty pod no longer counts as live).
    """
    make_pod(1)
    vacancy_id = _close(SessionFactory, 1)
    made = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    assert made.status_code == 201
    hired = made.json()["agent"]
    off = client.post(f"/agents/{hired['id']}/deactivate", headers=h(admin_key))
    assert off.status_code == 200
    v = client.get(f"/vacancies/{vacancy_id}", headers=h(admin_key)).json()
    s = SessionFactory()
    try:
        empty_pod_live = s.get(Pod, hired["pod_id"]).status != "closed"
    finally:
        s.close()
    assert v["status"] == "open" or not empty_pod_live, (
        "the vacancy reads filled and its pod is live, but its only PM is deactivated: the dead "
        "pod is never replaced and the empty pod holds a live-pod slot for good")


def test_redteam_a_name_squatted_in_advance_does_not_block_a_vacancy_forever(
        client, SessionFactory, make_pod, admin_key, agent_factory):
    """SEVERITY: low (needs a management agent; denies turnover, moves no money).

    The hire's names are predictable ("hire-<n>-pm", n = the count of vacancies + 1). A
    management agent registers "hire-1-pm" (and "hire-2-pm", ...) before any close; every fill
    of that vacancy is then refused with "a name is taken", every morning, for the rest of the
    run, and the Runtime writes a hire_refused each morning. The firm can never replace the dead
    pod. Expected: a taken name does not leave the vacancy unfillable for ever.
    """
    make_pod(1)
    agent_factory("hire-1-pm", "management")              # squatted before any pod dies
    vacancy_id = _close(SessionFactory, 1)
    first = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    second = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    s = SessionFactory()
    try:
        pms = s.scalar(select(func.count()).select_from(Agent).where(
            Agent.charter_ref == f"vacancy:{vacancy_id}"))
    finally:
        s.close()
    assert 201 in (first.status_code, second.status_code) and pms == 1, (
        f"a squatted name blocks the vacancy for good: {first.status_code}, "
        f"{second.status_code}: {first.json().get('detail')}")
