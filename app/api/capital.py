"""The capital machine's allocation table (idea: capital follows results).

Read only: the machine itself runs on every backtest clock advance (:mod:`app.capital.service`),
never on an agent's request. A pod member reads its own pod's row; the whole table, and the
centre's cash, need ``read_cross_pod``. ``GET /mandate`` is the orders a seeded pod's rule wants
today (a reader: the PM still sends each order through ``POST /orders``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.capital.mandate import NoMandate, mandate_orders
from app.capital.service import capital_view
from app.db.base import get_session
from app.db.models import Agent
from app.limits import MAX_ID
from app.marketdata import MarketDataError, get_provider
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
    pod_id = _pod_to_read(session, actor, pod_id, cross)
    return capital_view(session, pod_id=pod_id, cross=cross)


@router.get("/mandate", response_model=dict[str, Any])
def get_mandate(
    pod_id: int | None = Query(default=None, ge=1, le=MAX_ID,
                               description="Default: your own pod."),
    actor: Agent = Depends(require(Action.READ_OWN_PORTFOLIO)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """The orders that bring your seeded pod's book to what its rule holds today (sells first).
    Nothing is placed: send each one with ``POST /orders``."""
    cross = has_permission(actor.role, Action.READ_CROSS_POD)
    pod_id = _pod_to_read(session, actor, pod_id, cross) or actor.pod_id
    if pod_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name a pod_id")
    try:
        return mandate_orders(session, pod_id=pod_id, provider=get_provider())
    except NoMandate as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MarketDataError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _pod_to_read(session: Session, actor: Agent, pod_id: int | None, cross: bool) -> int | None:
    """The pod a request may read: one's own by default; another only with ``read_cross_pod``."""
    if pod_id is None and not cross:
        pod_id = actor.pod_id
        if pod_id is None:
            raise deny(session, actor, Action.READ_CROSS_POD,
                       detail="you have no pod: name none you may not read", context={})
    elif pod_id is not None and pod_id != actor.pod_id and not cross:
        raise deny(session, actor, Action.READ_CROSS_POD, detail=f"pod {pod_id} is not your pod",
                   context={"pod_id": pod_id})
    return pod_id
