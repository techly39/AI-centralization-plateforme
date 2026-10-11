"""Market data endpoints (TRD §7).

Thin by design: parse, delegate to the provider, translate errors. All three
roles may read market data (TRD §6), so the gate is just "are you a known
agent with READ_MARKET_DATA".

Prices are always requested at the ledger's now (``ledger_now``: the time on
``GET /clock`` and on the caller's next order, ADR-026/029), never at wall-clock
now. In live mode those are the same thing; in backtest mode they are
emphatically not, and this is the line that keeps the simulation honest.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.schemas import BarOut, OHLCVOut, PriceOut
from app.db.base import get_session
from app.db.models import Agent
from app.ledger.events import ledger_now
from app.marketdata import (
    InvalidRequestError,
    LookAheadError,
    MarketDataError,
    UnknownTickerError,
    get_provider,
    normalise_ticker,
)
from app.registry.auth import require
from app.registry.permissions import Action

router = APIRouter(tags=["market data"])

#: Default OHLCV window when the caller gives no dates: the last quarter.
_DEFAULT_LOOKBACK = timedelta(days=90)


def _http_error(exc: MarketDataError) -> HTTPException:
    """Map a market-data failure onto the right HTTP status."""
    if isinstance(exc, UnknownTickerError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (LookAheadError, InvalidRequestError)):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    # Anything else is the upstream feed failing us, not the caller's fault.
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/price/{ticker}", response_model=PriceOut)
def read_price(
    ticker: str,
    _: Agent = Depends(require(Action.READ_MARKET_DATA)),
    session: Session = Depends(get_session),
) -> PriceOut:
    try:
        quote = get_provider().get_price(ticker, as_of=ledger_now(session))
    except MarketDataError as exc:
        raise _http_error(exc)
    return PriceOut(
        ticker=quote.ticker,
        price=quote.price,
        as_of=quote.as_of,
        currency=quote.currency,
        source=quote.source,
    )


@router.get("/ohlcv/{ticker}", response_model=OHLCVOut)
def read_ohlcv(
    ticker: str,
    start: date | None = Query(default=None, description="Inclusive. Defaults to 90 days back."),
    end: date | None = Query(default=None, description="Exclusive. Defaults to the clock's today."),
    interval: str = Query(default="1d", description="1d | 1wk | 1mo | 1h"),
    _: Agent = Depends(require(Action.READ_MARKET_DATA)),
    session: Session = Depends(get_session),
) -> OHLCVOut:
    now = ledger_now(session)
    # Defaults come off the ledger's now, so a backtest asking for "recent
    # history" gets history recent to the *simulation*, not to today.
    resolved_end = end or (now.date() + timedelta(days=1))
    resolved_start = start or (resolved_end - _DEFAULT_LOOKBACK)

    try:
        symbol = normalise_ticker(ticker)
        bars = get_provider().get_ohlcv(
            symbol,
            start=resolved_start,
            end=resolved_end,
            interval=interval,
            as_of=now,
        )
    except MarketDataError as exc:
        raise _http_error(exc)

    return OHLCVOut(
        ticker=symbol,
        interval=interval,
        start=resolved_start,
        end=resolved_end,
        bars=[BarOut(**asdict(bar)) for bar in bars],
    )
