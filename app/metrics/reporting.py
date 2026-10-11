"""Self-reported cost and work logs (TRD §7 "Costs & tasks").

The app runs *outside* the agents. It never sees their token usage, their model
prices, or how long they spent thinking — those numbers exist only in whatever
runtime the agent lives in (OpenClaw, the Claude Agent SDK, a shell script). So
the app cannot measure them; it can only offer a place to put them and refuse to
let anyone put them anywhere else. That is what this module is.

Two rules make the numbers trustworthy enough to rank pods by:

**Attribution is never a parameter.** ``agent_id`` is the authenticated caller
and ``pod_id`` is that agent's pod, read from the registry. An agent cannot
report cost against another agent or charge its spending to a rival pod, because
there is no field in which to say so.

**Every report is an event.** Costs and task boundaries append to the ledger
like everything else, so ``GET /events`` shows the same history the ``costs`` and
``tasks`` tables summarise, and a corrupted table can be reconstructed from it.

Agents will only call these if their charters tell them to — the app cannot make
them. What the app *can* do is make the metrics show the gap: a pod with trades
and no cost reports is visibly unmeasured, not silently free.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Agent, Cost, Task
from app.ledger.events import (
    EVENT_COST_REPORTED,
    EVENT_TASK_ENDED,
    EVENT_TASK_STARTED,
    append_event,
)
from app.limits import MAX_TOKENS_PER_REPORT


class ReportingError(Exception):
    """Base class for cost/task reporting failures."""

    code = "reporting_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class TaskNotFoundError(ReportingError):
    """No such task (HTTP 404)."""

    code = "task_not_found"


class TaskOwnershipError(ReportingError):
    """An agent tried to close a task that is not its own (HTTP 403, logged)."""

    code = "task_not_yours"


class TaskAlreadyEndedError(ReportingError):
    """The task was already closed (HTTP 409).

    Refused rather than overwritten: the first outcome is the honest one, and
    silently accepting a second would let a retry loop rewrite history.
    """

    code = "task_already_ended"


# --- Costs ------------------------------------------------------------------

# MAX_TOKENS_PER_REPORT lives in app.limits (shared with the MCP wrapper).

def report_cost(
    session: Session,
    *,
    reporter: Agent,
    tokens_in: int,
    tokens_out: int,
    usd_cost: float,
    task_label: str | None = None,
) -> Cost:
    """Record one unit of work's token and dollar cost. Caller owns the transaction."""
    # The API schema refuses these first (422); this guards in-process callers.
    for name, value in (("tokens_in", tokens_in), ("tokens_out", tokens_out)):
        if not 0 <= value <= MAX_TOKENS_PER_REPORT:
            raise ValueError(f"{name}={value} outside 0..{MAX_TOKENS_PER_REPORT}")
    cost = Cost(
        ts=get_clock().now(),
        agent_id=reporter.id,
        pod_id=reporter.pod_id,
        tokens_in=int(tokens_in),
        tokens_out=int(tokens_out),
        usd_cost=float(usd_cost),
        task_label=task_label,
    )
    session.add(cost)
    session.flush()

    append_event(
        session,
        type=EVENT_COST_REPORTED,
        actor_agent_id=reporter.id,
        payload={
            "cost_id": cost.id,
            "pod_id": reporter.pod_id,
            "tokens_in": cost.tokens_in,
            "tokens_out": cost.tokens_out,
            "usd_cost": cost.usd_cost,
            "task_label": task_label,
        },
    )
    return cost


def list_costs(
    session: Session,
    *,
    pod_id: int | None = None,
    agent_id: int | None = None,
    limit: int = 500,
) -> Sequence[Cost]:
    stmt = select(Cost)
    if pod_id is not None:
        stmt = stmt.where(Cost.pod_id == pod_id)
    if agent_id is not None:
        stmt = stmt.where(Cost.agent_id == agent_id)
    stmt = stmt.order_by(Cost.ts.desc(), Cost.id.desc()).limit(limit)
    return session.execute(stmt).scalars().all()


# --- Tasks ------------------------------------------------------------------

def start_task(session: Session, *, reporter: Agent, subject: str) -> Task:
    """Open a work log entry. Caller owns the transaction.

    ``subject`` is the grouping key for the TRD's "time per subject" metric, so
    agents should reuse a small stable vocabulary ("earnings review",
    "risk check") rather than writing a fresh sentence each time.
    """
    task = Task(
        pod_id=reporter.pod_id,
        agent_id=reporter.id,
        subject=subject,
        started_at=get_clock().now(),
    )
    session.add(task)
    session.flush()

    append_event(
        session,
        type=EVENT_TASK_STARTED,
        actor_agent_id=reporter.id,
        payload={"task_id": task.id, "pod_id": reporter.pod_id, "subject": subject},
    )
    return task


def end_task(
    session: Session,
    *,
    reporter: Agent,
    task_id: int,
    outcome: dict,
) -> Task:
    """Close a work log entry with a structured outcome.

    Raises:
        TaskNotFoundError, TaskOwnershipError, TaskAlreadyEndedError.
    """
    task = session.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"no task with id {task_id}")
    if task.agent_id != reporter.id:
        raise TaskOwnershipError(
            f"task {task_id} belongs to agent {task.agent_id}, not to "
            f"{reporter.name!r}",
            detail={"task_id": task_id, "owner_agent_id": task.agent_id},
        )
    if task.ended_at is not None:
        raise TaskAlreadyEndedError(
            f"task {task_id} was already ended at {task.ended_at.isoformat()}",
            detail={"task_id": task_id, "ended_at": task.ended_at.isoformat()},
        )

    task.ended_at = get_clock().now()
    task.outcome_json = outcome
    session.flush()

    append_event(
        session,
        type=EVENT_TASK_ENDED,
        actor_agent_id=reporter.id,
        payload={
            "task_id": task.id,
            "pod_id": task.pod_id,
            "subject": task.subject,
            "seconds": task_duration_seconds(task),
            "outcome": outcome,
        },
    )
    return task


def task_duration_seconds(task: Task) -> float | None:
    """How long a closed task took, in seconds; ``None`` while it is still open."""
    if task.ended_at is None:
        return None
    return (task.ended_at - task.started_at).total_seconds()


def list_tasks(
    session: Session,
    *,
    pod_id: int | None = None,
    agent_id: int | None = None,
    open_only: bool = False,
    limit: int = 500,
) -> Sequence[Task]:
    stmt = select(Task)
    if pod_id is not None:
        stmt = stmt.where(Task.pod_id == pod_id)
    if agent_id is not None:
        stmt = stmt.where(Task.agent_id == agent_id)
    if open_only:
        stmt = stmt.where(Task.ended_at.is_(None))
    stmt = stmt.order_by(Task.started_at.desc(), Task.id.desc()).limit(limit)
    return session.execute(stmt).scalars().all()
