"""Finite numbers only: the one check behind every JSON door (B-000d, ADR-024).

``NaN`` and ``±Infinity`` are not quantities and not standard JSON. Python's
``json`` reads them anyway (and turns ``1e309`` into ``inf``), so a request can
carry one into a table or the ledger, where it renders as ``null`` or as
non-standard ``Infinity`` that another tool cannot parse. The request schemas
and :func:`app.ledger.events.append_event` both ask :func:`first_non_finite`.
"""

from __future__ import annotations

import math
from typing import Any


def first_non_finite(value: Any, path: str = "$") -> str | None:
    """Return the JSON path of the first non-finite float inside ``value``, or None.

    Walks dicts, lists and tuples to any depth. ``bool`` and ``int`` are always
    finite; strings such as ``"NaN"`` are text, not numbers, and pass.
    """
    if isinstance(value, float):
        return None if math.isfinite(value) else path
    if isinstance(value, dict):
        for key, item in value.items():
            found = first_non_finite(item, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = first_non_finite(item, f"{path}[{index}]")
            if found:
                return found
    return None


def json_safe(value: Any) -> Any:
    """Copy ``value`` with every non-finite float spelled as text.

    For echoing *rejected* input back in an error: the 422 must itself be
    standard JSON, or rendering it fails and the client gets a 500.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
