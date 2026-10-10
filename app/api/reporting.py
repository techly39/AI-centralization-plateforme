"""Cost and task self-reporting endpoints (TRD §7).

The app cannot see what an agent spends or how long it thought — only the agent
knows. These three endpoints are where it says so. Attribution is taken from the
API key, never from the body, so a report can only ever be about its sender; see
:mod:`app.metrics.reporting` for why that constraint is load-bearing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import (
    CostOut,
    CostReportRequest,
    TaskEndRequest,
    TaskOut,
    TaskStartRequest,
)
from app.db.base import get_session
from app.db.models import Agent, Task
from app.metrics.reporting import (
    TaskAlreadyEndedError,
    TaskNotFoundError,
    TaskOwnershipError,
    end_task,
    report_cost,
    start_task,
    task_duration_seconds,
)
from app.registry.auth import deny, require
from app.registry.permissions import Action

router = APIRouter(tags=["costs & tasks"])


def _task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        pod_id=task.pod_id,
        agent_id=task.agent_id,
        subject=task.subject,
        started_at=task.started_at,
        ended_at=task.ended_at,
        seconds=task_duration_seconds(task),
        outcome=task.outcome_json,
    )


@router.post("/costs", response_model=CostOut, status_code=status.HTTP_201_CREATED)
def post_cost(
    body: CostReportRequest,
    actor: Agent = Depends(require(Action.REPORT_COST)),
    session: Session = Depends(get_session),
) -> CostOut:
    """Report what one unit of your work cost, in tokens and dollars."""
    cost = report_cost(
        session,
        reporter=actor,
        tokens_in=body.tokens_in,
        tokens_out=body.tokens_out,
        usd_cost=body.usd_cost,
        task_label=body.task_label,
    )
    session.commit()
    return CostOut.model_validate(cost)


@router.post("/tasks/start", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def post_task_start(
    body: TaskStartRequest,
    actor: Agent = Depends(require(Action.REPORT_TASK)),
    session: Session = Depends(get_session),
) -> TaskOut:
    """Open a work log entry. Keep the returned ``id`` — you need it to close it."""
    task = start_task(session, reporter=actor, subject=body.subject)
    session.commit()
    return _task_out(task)


@router.post("/tasks/end", response_model=TaskOut)
def post_task_end(
    body: TaskEndRequest,
    actor: Agent = Depends(require(Action.REPORT_TASK)),
    session: Session = Depends(get_session),
) -> TaskOut:
    """Close your own work log entry with a structured outcome."""
    try:
        task = end_task(
            session, reporter=actor, task_id=body.task_id, outcome=body.outcome
        )
        session.commit()
    except TaskNotFoundError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message)
    except TaskOwnershipError as exc:
        session.rollback()
        raise deny(
            session,
            actor,
            Action.REPORT_TASK,
            detail=exc.message,
            context={"task_id": body.task_id, **exc.detail},
        )
    except TaskAlreadyEndedError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message)

    return _task_out(task)
