"""Halt in physics (Constitution Art. 5, 03_WORLD §2).

The Human halts the world by creating one file, ``governance/HALT`` at the repo
root. The path is a constant, not a setting: Art. 5 names that file, and a path
that ``config.yaml`` or a ``FUND_*`` variable could move would be a way around
the halt. Physics only reads it, at the start of every request and every
monitor sweep, so creating or deleting it takes effect on the next call — no
restart, no cache. A request or sweep already past the check finishes ("the
current tool call", Art. 5.2).

Operator CLI commands (``fund-env seed-admin`` / ``create-pod`` / ``fund-pod``)
are the Human's own hands, not agent requests, and are not gated.

While halted:

* every state-changing request (any method other than GET/HEAD/OPTIONS) from
  every authenticated agent, whatever its role, is refused with **423 Locked**
  and a ``halt_refused`` event (:func:`refuse_if_halted`, called from
  :func:`app.registry.auth.get_current_agent`, which every endpoint but
  ``/health`` goes through);
* reads keep working, so agents and the Human can still see the world;
* the pending-order monitor fills nothing (:mod:`app.oms.monitor`).

The refusal event is the one write a halted world still makes: it is the record
that someone tried.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.db.models import Agent
from app.ledger.events import EVENT_HALT_REFUSED, append_event

#: Tests point this at a temporary path (tests/conftest.py); nothing else may.
HALT_FILE = REPO_ROOT / "governance" / "HALT"

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

HALTED_DETAIL = (
    "The fund is halted by the Human (Constitution Art. 5): state-changing "
    "requests are refused until the halt is lifted. Reads still work; "
    "GET /halt tells you when it is over."
)


def is_halted() -> bool:
    return HALT_FILE.exists()


def refuse_if_halted(request: Request, session: Session, agent: Agent) -> None:
    """Raise 423 (after logging the attempt) for a write while halted."""
    if request.method in READ_METHODS or not is_halted():
        return
    append_event(
        session,
        type=EVENT_HALT_REFUSED,
        actor_agent_id=agent.id,
        payload={
            "method": request.method,
            "path": request.url.path,
            "role": agent.role.value,
        },
    )
    session.commit()
    raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=HALTED_DETAIL)
