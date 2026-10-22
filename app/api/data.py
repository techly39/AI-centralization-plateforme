"""The world's news, handed by role (idea: data packages). Headlines and companies' quarterly
reports are read at the ledger's now, like prices: an item published after it does not exist.
Each needs its role's action and the agent's own data right (:mod:`app.registry.permissions`); a
mind without it is refused by name, 403 and logged. No answer says whether an item moves a price.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.marketdata import _http_error
from app.db.base import get_session
from app.db.models import Agent
from app.ledger.events import ledger_now
from app.marketdata import MarketDataError, get_provider
from app.registry.auth import deny, require
from app.registry.permissions import DATA_RIGHTS, Action, data_right_problem, data_rights

router = APIRouter(tags=["data"])

#: The longest window one read covers, in days.
MAX_HEADLINE_DAYS = 31
MAX_REPORT_DAYS = 400


def _read(session: Session, agent: Agent, *, right: str, kind: Literal["headline", "report"],
          days: int, ticker: str | None) -> dict[str, Any]:
    if (problem := data_right_problem(session, agent, right)) is not None:
        raise deny(session, agent, DATA_RIGHTS[right], detail=problem, context={"right": right})
    now = ledger_now(session)
    since = now.date() - timedelta(days=days - 1)
    try:
        found = get_provider().get_news(kind=kind, as_of=now, since=since, ticker=ticker)
    except MarketDataError as exc:
        raise _http_error(exc)
    return {"day": now.date().isoformat(), "since": since.isoformat(),
            f"{kind}s": [{"id": x.id, "day": x.published.isoformat(), "ticker": x.ticker,
                          "title": x.title, "body": x.body,
                          **({"figures": x.figures} if x.figures is not None else {})}
                         for x in found]}


@router.get("/headlines")
def read_headlines(
    days: int = Query(default=3, ge=1, le=MAX_HEADLINE_DAYS,
                      description="Today and the days before it: 1 = today's only."),
    ticker: str | None = Query(default=None, description="Only the headlines about one ticker."),
    agent: Agent = Depends(require(Action.READ_HEADLINES)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """The world's headlines published up to now, oldest first. Needs the headlines right."""
    return _read(session, agent, right="headlines", kind="headline", days=days, ticker=ticker)


@router.get("/reports")
def read_reports(
    days: int = Query(default=91, ge=1, le=MAX_REPORT_DAYS,
                      description="Today and the days before it (a quarter is 91 days)."),
    ticker: str | None = Query(default=None, description="Only one company's reports."),
    agent: Agent = Depends(require(Action.READ_COMPANY_DATA)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Companies' quarterly reports published up to now, oldest first. Needs the company right."""
    return _read(session, agent, right="company", kind="report", days=days, ticker=ticker)


@router.get("/data/rights")
def my_data_rights(
    agent: Agent = Depends(require(Action.READ_MARKET_DATA)),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """What the caller may read: prices always; headlines and company reports if granted. A
    reader of market data only (physics' Runtime identity reads none)."""
    held = data_rights(session, agent.id)
    return {"prices": True, **{right: right in held for right in DATA_RIGHTS}}
