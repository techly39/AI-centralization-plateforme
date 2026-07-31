"""OMS endpoints: place, cancel, list orders, and read a portfolio (TRD §7).

The router does three things and nothing else: check *pod scope* (the role
matrix already ran in the dependency), call :mod:`app.oms`, and translate the
OMS's vocabulary into HTTP. All the trading logic lives in the service — that
separation is what lets the MCP server in Phase 2 expose the same behaviour
without duplicating a single rule.

Two access rules apply to the read endpoints, straight from TRD §6:

* every role may read **its own pod's** orders and portfolio;
* reading **another pod** needs ``read_cross_pod``, i.e. management.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.schemas import OrderCreateRequest, OrderOut, PortfolioOut, PositionOut
from app.db.base import get_session
from app.db.models import Agent, OrderStatus
from app.marketdata import get_provider
from app.oms import (
    AccessError,
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderRejected,
    OrderValidationError,
    PriceUnavailableError,
    build_portfolio,
    cancel_order,
    list_orders,
    place_order,
)
from app.registry.auth import deny, get_current_agent, require
from app.registry.permissions import Action, has_permission

router = APIRouter(tags=["oms"])


def _assert_may_read_pod(session: Session, actor: Agent, pod_id: int) -> None:
    """Own pod is always readable; anything else needs cross-pod rights."""
    if actor.pod_id == pod_id:
        return
    if has_permission(actor.role, Action.READ_CROSS_POD):
        return
    raise deny(
        session,
        actor,
        Action.READ_CROSS_POD,
        detail=f"pod {pod_id} is not your pod",
        context={"pod_id": pod_id},
    )


# --- Orders -----------------------------------------------------------------

@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: OrderCreateRequest,
    actor: Agent = Depends(require(Action.PLACE_ORDER)),
    session: Session = Depends(get_session),
) -> OrderOut:
    """Place an order for the caller's own pod.

    201 means the order was *recorded*, not that it was filled. Read ``status``:
    ``filled`` (market order done), ``pending`` (limit order waiting for the
    market), or ``rejected`` (not enough cash or shares — ``status_reason``
    explains, and a message has been sent to you).
    """
    try:
        order = place_order(
            session,
            actor=actor,
            ticker=body.ticker,
            side=body.side,
            qty=body.qty,
            price_type=body.price_type,
            limit_price=body.limit_price,
            justification=body.justification,
            provider=get_provider(),
        )
    except AccessError as exc:
        # Covers both "your role never may" and "not your pod". Either way it
        # is a 403 recorded as a permission_denied event, per TRD §6.
        raise deny(
            session, actor, Action.PLACE_ORDER, detail=exc.message, context=exc.detail
        )
    except OrderValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except PriceUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    except OrderRejected as exc:  # pragma: no cover - rejections are stored, not raised
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message)

    return OrderOut.model_validate(order)


@router.delete("/orders/{order_id}", response_model=OrderOut)
def cancel(
    order_id: int,
    actor: Agent = Depends(require(Action.PLACE_ORDER)),
    session: Session = Depends(get_session),
) -> OrderOut:
    """Cancel one of your own pod's pending orders."""
    try:
        order = cancel_order(session, actor=actor, order_id=order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message)
    except AccessError as exc:
        # Covers both "your role never may" and "not your pod". Either way it
        # is a 403 recorded as a permission_denied event, per TRD §6.
        raise deny(
            session, actor, Action.PLACE_ORDER, detail=exc.message, context=exc.detail
        )
    except OrderNotCancellableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message)
    return OrderOut.model_validate(order)


@router.get("/orders", response_model=list[OrderOut])
def read_orders(
    pod: int | None = Query(default=None, description="Defaults to your own pod."),
    order_status: OrderStatus | None = Query(
        default=None, alias="status", description="pending | filled | rejected | cancelled"
    ),
    ticker: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: Agent = Depends(get_current_agent),
    session: Session = Depends(get_session),
) -> list[OrderOut]:
    """Order history, newest first.

    With no ``pod``: your own pod's orders — or, for management (which has no
    pod), every pod's.
    """
    if pod is not None:
        _assert_may_read_pod(session, actor, pod)
        scope = pod
    elif actor.pod_id is not None:
        scope = actor.pod_id
    elif has_permission(actor.role, Action.READ_CROSS_POD):
        scope = None  # management: the whole firm
    else:
        raise deny(
            session,
            actor,
            Action.READ_OWN_PORTFOLIO,
            detail="you belong to no pod, so name one with ?pod=",
        )

    orders = list_orders(
        session, pod_id=scope, status=order_status, ticker=ticker, limit=limit
    )
    return [OrderOut.model_validate(o) for o in orders]


# --- Portfolio --------------------------------------------------------------

@router.get("/portfolio/{pod_id}", response_model=PortfolioOut)
def read_portfolio(
    pod_id: int,
    actor: Agent = Depends(require(Action.READ_OWN_PORTFOLIO)),
    session: Session = Depends(get_session),
) -> PortfolioOut:
    """Positions, cash, and unrealised P&L for a pod, valued at clock-now."""
    _assert_may_read_pod(session, actor, pod_id)
    view = build_portfolio(session, pod_id=pod_id, provider=get_provider())
    return PortfolioOut(
        pod_id=view.pod_id,
        as_of=view.as_of,
        cash=view.cash,
        positions=[PositionOut.model_validate(p) for p in view.positions],
        positions_value=view.positions_value,
        total_value=view.total_value,
        unrealized_pnl=view.unrealized_pnl,
        pricing_errors=view.pricing_errors,
        fully_priced=view.fully_priced,
    )
