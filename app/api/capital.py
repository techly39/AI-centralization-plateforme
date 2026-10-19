"""The capital machine's allocation table (idea: capital follows results).

Read only: the machine itself runs on every backtest clock advance (:mod:`app.capital.service`),
never on an agent's request. A pod member reads its own pod's row; the whole table, and the
centre's cash, need ``read_cross_pod``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.capital.service import capital_view
from app.db.base import get_session
from app.db.models import Agent
from app.limits import MAX_ID
from app.registry.auth import deny, require
from app.registry.permissions import Action, has_permission

router = APIRouter(tags=["capital"])


@router.get("/capital", response_model=dict[str, Any])
def get_capital(
    pod_id: int | None = Query(default=None, ge=1, le=MAX_ID,
                               description="Default: your own pod (management: every pod)."),
    actor: Agent = Depends(require(Action.READ_OWN_PORTFOLIO)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Your pod's capital, its risk-ladder stage and its latest score; the law that moves them."""
    cross = has_permission(actor.role, Action.READ_CROSS_POD)
    if pod_id is None and not cross:
        pod_id = actor.pod_id
        if pod_id is None:
            raise deny(session, actor, Action.READ_CROSS_POD,
                       detail="you have no pod: name none you may not read", context={})
    elif pod_id is not None and pod_id != actor.pod_id and not cross:
        raise deny(session, actor, Action.READ_CROSS_POD, detail=f"pod {pod_id} is not your pod",
                   context={"pod_id": pod_id})
    return capital_view(session, pod_id=pod_id)
