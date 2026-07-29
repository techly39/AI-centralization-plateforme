"""Structured logging via loguru (TRD §10).

One place configures the sink so both the CLI and the API server log the same
way. ``json=true`` in config emits machine-parseable lines (serialize=True).
"""

from __future__ import annotations

import sys

from loguru import logger

from app.config import get_settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    cfg = get_settings().logging
    logger.remove()
    logger.add(
        sys.stderr,
        level=cfg.level.upper(),
        serialize=cfg.json_logs,
        backtrace=False,
        diagnose=False,
    )
    _configured = True
