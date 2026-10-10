"""Cost and task self-reporting (TRD §7).

These numbers are the only ones the app cannot verify — it never sees an agent's
token bill. What it *can* guarantee is that a report is about its sender and
nobody else, and that it lands on the ledger. Both are tested here, because a
cost figure that can be attributed to a rival pod is worse than no figure at all.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Cost, Event, Task
from app.ledger.events import (
    EVENT_COST_REPORTED,
    EVENT_PERMISSION_DENIED,
    EVENT_TASK_ENDED,
    EVENT_TASK_STARTED,
)


def post(client, key, path, **body):
    return client.post(path, headers={"X-API-Key": key}, json=body)


# --- Costs ------------------------------------------------------------------

def test_cost_is_attributed_to_the_caller_and_its_pod(client, desk, db):
    pod_id, pm_id, pm_key = desk

    resp = post(
        client, pm_key, "/costs",
        tokens_in=1200, tokens_out=340, usd_cost=0.0182, task_label="morning review",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_id"] == pm_id
    assert body["pod_id"] == pod_id
    assert body["usd_cost"] == 0.0182

    event = db.scalar(select(Event).where(Event.type == EVENT_COST_REPORTED))
    assert event.actor_agent_id == pm_id
    assert event.payload_json["pod_id"] == pod_id


def test_a_report_cannot_be_charged_to_another_agent_or_pod(client, desk):
    """There is no field for it — the schema rejects the attempt outright."""
    _, _, pm_key = desk
    resp = post(
        client, pm_key, "/costs",
        tokens_in=1, tokens_out=1, usd_cost=1.0, agent_id=999, pod_id=2,
    )
    assert resp.status_code == 422


def test_every_role_may_report_its_own_cost(client, desk, agent_factory, admin_key):
    pod_id, _, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    for key in (pm_key, analyst_key, admin_key):
        assert post(
            client, key, "/costs", tokens_in=10, tokens_out=5, usd_cost=0.001
        ).status_code == 201


def test_management_cost_has_no_pod(client, admin_key, db):
    """Firm overhead is not charged to a desk that did not incur it."""
    assert post(
        client, admin_key, "/costs", tokens_in=10, tokens_out=5, usd_cost=0.5
    ).status_code == 201
    assert db.scalar(select(Cost)).pod_id is None


def test_negative_cost_is_refused(client, desk):
    _, _, pm_key = desk
    assert post(
        client, pm_key, "/costs", tokens_in=1, tokens_out=1, usd_cost=-5.0
    ).status_code == 422


def test_token_counts_are_capped_per_report(client, desk):
    """One report may claim at most MAX_TOKENS_PER_REPORT of each kind: no
    single unit of work is that big, and an unbounded count let any agent
    overflow the pod's token sums (red-team 0001)."""
    from app.metrics.reporting import MAX_TOKENS_PER_REPORT

    _, _, pm_key = desk
    for field in ("tokens_in", "tokens_out"):
        ok = {"tokens_in": 1, "tokens_out": 1, field: MAX_TOKENS_PER_REPORT}
        assert post(client, pm_key, "/costs", usd_cost=0.0, **ok).status_code == 201
        too_big = {**ok, field: MAX_TOKENS_PER_REPORT + 1}
        assert post(client, pm_key, "/costs", usd_cost=0.0, **too_big).status_code == 422


def test_token_cap_also_binds_in_process_callers(desk, db):
    """A future system cost-sync calls report_cost directly, not over HTTP."""
    from app.db.models import Agent
    from app.metrics.reporting import MAX_TOKENS_PER_REPORT, report_cost

    _, pm_id, _ = desk
    pm = db.get(Agent, pm_id)
    with pytest.raises(ValueError):
        report_cost(db, reporter=pm, tokens_in=MAX_TOKENS_PER_REPORT + 1,
                    tokens_out=0, usd_cost=0.0)


# --- Tasks ------------------------------------------------------------------

def test_task_start_and_end_records_duration_and_outcome(
    client, desk, db, frozen_clock
):
    pod_id, pm_id, pm_key = desk

    started = post(client, pm_key, "/tasks/start", subject="earnings review")
    assert started.status_code == 201, started.text
    task_id = started.json()["id"]
    assert started.json()["ended_at"] is None
    assert started.json()["seconds"] is None

    frozen_clock.advance(minutes=25)

    ended = post(
        client, pm_key, "/tasks/end",
        task_id=task_id,
        outcome={"summary": "JPM cheapest of the group", "recommendation": "buy"},
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["seconds"] == 1500.0
    assert ended.json()["outcome"]["recommendation"] == "buy"

    task = db.get(Task, task_id)
    assert task.agent_id == pm_id and task.pod_id == pod_id

    types = [e.type for e in db.execute(select(Event)).scalars()]
    assert EVENT_TASK_STARTED in types and EVENT_TASK_ENDED in types


def test_you_cannot_close_someone_elses_task(client, desk, agent_factory, db):
    pod_id, _, pm_key = desk
    analyst_id, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    task_id = post(client, analyst_key, "/tasks/start", subject="screen").json()["id"]
    resp = post(client, pm_key, "/tasks/end", task_id=task_id, outcome={"summary": "mine now"})
    assert resp.status_code == 403

    denial = db.scalar(
        select(Event).where(Event.type == EVENT_PERMISSION_DENIED).order_by(Event.id.desc())
    )
    assert denial.payload_json["owner_agent_id"] == analyst_id
    assert db.get(Task, task_id).ended_at is None


def test_a_task_cannot_be_closed_twice(client, desk):
    _, _, pm_key = desk
    task_id = post(client, pm_key, "/tasks/start", subject="screen").json()["id"]
    assert post(
        client, pm_key, "/tasks/end", task_id=task_id, outcome={"summary": "done"}
    ).status_code == 200
    # The first outcome is the honest one; a retry must not rewrite it.
    second = post(
        client, pm_key, "/tasks/end", task_id=task_id, outcome={"summary": "actually great"}
    )
    assert second.status_code == 409


def test_ending_an_unknown_task_is_a_404(client, desk):
    _, _, pm_key = desk
    assert post(
        client, pm_key, "/tasks/end", task_id=4242, outcome={"summary": "?"}
    ).status_code == 404


def test_outcome_must_be_structured_not_prose(client, desk):
    """TRD §10: every LLM-facing artifact is stored as JSON, never free text only."""
    _, _, pm_key = desk
    task_id = post(client, pm_key, "/tasks/start", subject="screen").json()["id"]
    resp = post(client, pm_key, "/tasks/end", task_id=task_id, outcome="it went fine")
    assert resp.status_code == 422


def test_reporting_requires_authentication(client):
    assert client.post("/costs", json={"tokens_in": 1, "tokens_out": 1, "usd_cost": 1}).status_code == 401
    assert client.post("/tasks/start", json={"subject": "x"}).status_code == 401
