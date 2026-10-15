"""The parts of a cassette v2 beside its outcome, for tests that only care about the outcome
(M-002): run parameters and one spec entry. ``cassette.write(path, outcome, **PARTS)``."""

from __future__ import annotations

from typing import Any

PARAMETERS: dict[str, Any] = {"steps": 1, "days_per_step": 1, "max_tool_calls": 64,
                              "workflow_input": {}}
SPECS: list[dict[str, Any]] = [{"id": "a-analyst"}]
PARTS: dict[str, Any] = {"parameters": PARAMETERS, "specs": SPECS}
