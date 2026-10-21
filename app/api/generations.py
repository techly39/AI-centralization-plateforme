"""Generations (idea: every month is a generation): the library of lessons the firm keeps. Physics
ends each month's generation on the clock advance (:mod:`app.capital.generation`), never on an
agent's request; every firm agent reads what the PMs who went have left.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.capital.generation import library
from app.db.base import get_session
from app.db.models import Agent
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(tags=["generations"])


@router.get("/library", response_model=list[dict[str, Any]])
def get_library(
    actor: Agent = Depends(require(Action.READ_PITCHES)),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Every lesson the firm has kept, oldest first: each PM who was let go, from which pod, when
    and why, what the pod tried (its pitches and the gates they failed, its research, what the
    centre did with it) and what its thinking cost."""
    return library(session)
