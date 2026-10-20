"""The Human's agent cap in physics (``firm.max_agents_total`` in the Human's file): the alive
agents the firm may hold. The Runtime refuses a hire past it before it asks (it reads the same
file); physics refuses the fill itself too, so no registrar, the Runtime's or another, hires past
it (red-team, the firm lives a quarter: the cap was the Runtime's check, not physics').

The path is a constant, as the HALT file's is: a setting that could move it would be a way around
the cap. Read fresh at every fill, fail closed: an unreadable or malformed cap hires no one.
"""

from __future__ import annotations

from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.db.models import Agent, AgentStatus

#: Tests point this at a temporary path; nothing else may.
HUMAN_FILE = REPO_ROOT / "governance" / "human.yaml"


def agents_cap() -> tuple[int | None, str | None]:
    """``(cap, None)``, else ``(None, why)``."""
    try:
        doc: Any = yaml.safe_load(HUMAN_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - fail closed on any read or parse failure
        return None, f"the Human's file is not readable ({exc.__class__.__name__})"
    firm = doc.get("firm") if isinstance(doc, dict) else None
    raw = firm.get("max_agents_total") if isinstance(firm, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return None, "the Human's agent cap (firm.max_agents_total) is missing or malformed"
    return raw, None


def alive_agents(session: Session) -> int:
    """Every agent not deactivated, every role, as the directory lists them."""
    return int(session.scalar(select(func.count()).select_from(Agent)
                              .where(Agent.status != AgentStatus.inactive)) or 0)


def over_cap(session: Session, adding: int = 1) -> str | None:
    """Why ``adding`` more agents would pass the Human's cap, else ``None``."""
    cap, why = agents_cap()
    if cap is None:
        return why
    alive = alive_agents(session)
    if alive + adding > cap:
        return (f"the firm holds {alive} alive agents: one more passes the Human's cap of {cap} "
                f"(firm.max_agents_total)")
    return None
