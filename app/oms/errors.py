"""OMS failure modes.

Two categories, and the difference matters:

* **Rejections** (:class:`OrderRejected` and subclasses) are legitimate business
  outcomes. The order is a real, stored order whose status is ``rejected`` — the
  PM gets an auto-message and can look it up later. The API answers 201, because
  a resource really was created. This is what TRD §8.2 describes.
* **Refusals** (everything else here) mean the request never became an order:
  malformed input, wrong pod, no price available. Nothing is stored and the API
  answers 4xx/502.

Each error carries a machine-readable ``code`` so agents can branch on it
without parsing prose (TRD §10).
"""

from __future__ import annotations


class OMSError(Exception):
    """Base class for everything the OMS refuses to do."""

    code = "oms_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class OrderValidationError(OMSError):
    """The request is malformed (bad quantity, missing limit price, ...)."""

    code = "invalid_order"


class AccessError(OMSError):
    """The agent is not allowed to do this. Always becomes a logged HTTP 403.

    Split into two cases below because they fail for different reasons and a PM
    reading the message deserves to know which: "your role never may" versus
    "not on that pod".
    """

    code = "access_denied"


class RoleNotPermittedError(AccessError):
    """The agent's role is not granted this action by the permission matrix.

    The API layer checks the same matrix first, so in normal operation this
    never fires. It exists so the OMS is safe when called from somewhere that
    is not an HTTP route — a maintenance script, a Phase 3 backtest driver, a
    test. Crucially it asks :func:`app.registry.permissions.has_permission`
    rather than keeping its own list of roles, so there is still exactly one
    permission matrix in the codebase (TRD §6).
    """

    code = "role_not_permitted"


class PodScopeError(AccessError):
    """The agent tried to act on a pod that is not its own, or has no pod.

    This is the "(own pod)" qualifier in the TRD §6 table. A ``role → action``
    matrix cannot express it — it needs the agent-to-pod relationship — so it
    is checked here rather than in the matrix.
    """

    code = "pod_scope"


class PodLimitError(AccessError):
    """The risk ladder limits this pod: a reduce-only pod may only sell, a closed pod may not
    trade at all (app/capital/). Physics, not a role: no agent can talk its way past it."""

    code = "pod_limit"


class OrderNotFoundError(OMSError):
    """No such order."""

    code = "order_not_found"


class OrderNotCancellableError(OMSError):
    """Only pending orders can be cancelled."""

    code = "order_not_cancellable"


class PriceUnavailableError(OMSError):
    """No price could be obtained, so the order cannot be evaluated at all."""

    code = "price_unavailable"


# --- Rejections (stored as orders with status=rejected) ---------------------

class OrderRejected(OMSError):
    """Base class for outcomes recorded on the order rather than raised to HTTP."""

    code = "rejected"


class InsufficientCashError(OrderRejected):
    code = "insufficient_cash"


class InsufficientPositionError(OrderRejected):
    code = "insufficient_position"
