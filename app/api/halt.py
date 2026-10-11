"""Halt status endpoint (Constitution Art. 5, 03_WORLD §2).

Any authenticated agent may ask whether the world is halted — an agent whose
writes come back 423 needs a cheap way to learn when to try again.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas import HaltOut
from app.db.models import Agent
from app.registry.auth import require
from app.registry.halt import is_halted
from app.registry.permissions import Action

router = APIRouter(tags=["system"])


@router.get("/halt", response_model=HaltOut)
def read_halt(_: Agent = Depends(require(Action.READ_HALT))) -> HaltOut:
    return HaltOut(halted=is_halted())
