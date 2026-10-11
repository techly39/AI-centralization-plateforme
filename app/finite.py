"""Portable JSON only: the one check behind every JSON door (B-000d, ADR-024).

``NaN`` and ``±Infinity`` are not quantities and not standard JSON. Python's
``json`` reads them anyway (and turns ``1e309`` into ``inf``), so a request can
carry one into a table or the ledger, where it renders as ``null`` or as
non-standard ``Infinity`` that another tool cannot parse. Two more shapes break
the same promise (red-team 0004): an integer no float64 reader can hold
(``10**400`` reads as ``Infinity`` in JavaScript), and nesting so deep that the
API itself cannot render the row it stored (every later read of it was a 500).
The request schemas and :func:`app.ledger.events.append_event` both ask
:func:`json_problem`.
"""

from __future__ import annotations

import math
from typing import Any

from app.limits import MAX_SAFE_INT


def json_problem(value: Any, *, max_depth: int) -> str | None:
    """Describe the first thing in ``value`` that is not portable JSON, or None.

    Refuses non-finite floats, integers beyond ±(2**53 - 1), and containers
    nested deeper than ``max_depth`` (the top-level container is depth 1). The
    walk itself is iterative, so no depth can exhaust the stack here (JSON
    parsing and pydantic before it still recurse). Strings such as ``"NaN"``
    are text, not numbers, and pass; ``bool`` is not a number here.
    """
    stack: list[tuple[Any, str, int]] = [(value, "$", 0)]
    while stack:
        item, path, depth = stack.pop()
        if isinstance(item, bool):
            continue
        if isinstance(item, float):
            if not math.isfinite(item):
                return f"non-finite number at {path}"
        elif isinstance(item, int):
            if abs(item) > MAX_SAFE_INT:
                return f"integer beyond ±(2**53 - 1) at {path}"
        elif isinstance(item, (dict, list, tuple)):
            if depth + 1 > max_depth:
                return f"nesting deeper than {max_depth} at {path}"
            children = (
                ((v, f"{path}.{k}") for k, v in item.items())
                if isinstance(item, dict)
                else ((v, f"{path}[{i}]") for i, v in enumerate(item))
            )
            # Reversed so the first problem found is the first in document order.
            stack.extend((v, p, depth + 1) for v, p in reversed(list(children)))
    return None


def json_safe(value: Any, *, max_depth: int = 64, _depth: int = 0) -> Any:
    """Copy ``value`` with every non-finite float spelled as text and anything
    nested deeper than ``max_depth`` replaced by ``"…"``.

    For echoing *rejected* input back in an error: the 422 must itself be
    standard JSON a client can render, or the client gets a 500.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, (dict, list, tuple)) and _depth >= max_depth:
        return "…"
    if isinstance(value, dict):
        return {k: json_safe(v, max_depth=max_depth, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v, max_depth=max_depth, _depth=_depth + 1) for v in value]
    return value
