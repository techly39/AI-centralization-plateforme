"""Order Management System — the deterministic broker simulation (TRD §8).

Where to look:

* :mod:`app.oms.service` — placing, filling, rejecting, cancelling orders.
* :mod:`app.oms.monitor` — the sweep that fills pending limit orders.
* :mod:`app.oms.portfolio` — positions + cash + unrealised P&L for a pod.
* :mod:`app.oms.money` — the fee and P&L arithmetic, in one place.
* :mod:`app.oms.errors` — what can go wrong, and whether it is stored or raised.

Nothing here reads the system clock, the filesystem, or yfinance directly: time
comes from :mod:`app.clock` and prices from :mod:`app.marketdata`, both
injectable, which is what makes backtests and tests possible.
"""

from app.oms.errors import (
    AccessError,
    InsufficientCashError,
    InsufficientPositionError,
    OMSError,
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderRejected,
    OrderValidationError,
    PodLimitError,
    PodScopeError,
    PriceUnavailableError,
    RoleNotPermittedError,
)
from app.oms.monitor import MonitorResult, check_pending_orders
from app.oms.portfolio import PortfolioView, PositionView, build_portfolio
from app.oms.service import (
    cancel_order,
    force_sell,
    get_cash,
    get_order,
    get_position,
    list_orders,
    place_order,
)

__all__ = [
    "AccessError",
    "InsufficientCashError",
    "InsufficientPositionError",
    "MonitorResult",
    "OMSError",
    "OrderNotCancellableError",
    "OrderNotFoundError",
    "OrderRejected",
    "OrderValidationError",
    "PodLimitError",
    "PodScopeError",
    "PortfolioView",
    "PositionView",
    "PriceUnavailableError",
    "RoleNotPermittedError",
    "build_portfolio",
    "cancel_order",
    "force_sell",
    "check_pending_orders",
    "get_cash",
    "get_order",
    "get_position",
    "list_orders",
    "place_order",
]
