"""Portfolio assembly for ``GET /portfolio/{pod_id}`` (TRD §7).

Positions and cash come from the derived tables (which are a fold of the event
ledger). Unrealised P&L needs a *current* price, so this is the one read path
that touches the market.

Degrading, not failing: if one ticker cannot be priced, its valuation fields
come back ``null`` and the symbol is listed in ``pricing_errors`` rather than the
whole request 502-ing. A PM checking a ten-name book should not be blinded
because one quote timed out — and the totals stay honest by excluding what could
not be valued, with ``fully_priced`` saying whether that happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Position
from app.ledger.events import ledger_now
from app.marketdata import MarketDataError, MarketDataProvider, get_provider
from app.oms.money import round_money
from app.oms.service import get_cash


@dataclass(slots=True)
class PositionView:
    ticker: str
    qty: float
    avg_cost: float
    #: Cost basis of the shares held (qty × avg_cost), excluding fees paid.
    cost_basis: float
    last_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None


@dataclass(slots=True)
class PortfolioView:
    pod_id: int
    as_of: datetime
    cash: float
    positions: list[PositionView]
    positions_value: float
    total_value: float
    unrealized_pnl: float
    #: Tickers whose price could not be read on this call.
    pricing_errors: list[str] = field(default_factory=list)

    @property
    def fully_priced(self) -> bool:
        return not self.pricing_errors


def build_portfolio(
    session: Session,
    *,
    pod_id: int,
    provider: MarketDataProvider | None = None,
) -> PortfolioView:
    """Positions + cash + unrealised P&L for one pod, valued at the ledger's now."""
    provider = provider or get_provider()
    now = ledger_now(session)

    rows = (
        session.execute(
            select(Position)
            .where(Position.pod_id == pod_id)
            .order_by(Position.ticker)
        )
        .scalars()
        .all()
    )

    views: list[PositionView] = []
    pricing_errors: list[str] = []
    positions_value = 0.0
    unrealized = 0.0

    for row in rows:
        view = PositionView(
            ticker=row.ticker,
            qty=row.qty,
            avg_cost=round_money(row.avg_cost),
            cost_basis=round_money(row.qty * row.avg_cost),
        )
        try:
            price = provider.get_price(row.ticker, as_of=now).price
        except MarketDataError:
            pricing_errors.append(row.ticker)
        else:
            view.last_price = price
            view.market_value = round_money(row.qty * price)
            view.unrealized_pnl = round_money(row.qty * (price - row.avg_cost))
            positions_value += view.market_value
            unrealized += view.unrealized_pnl
        views.append(view)

    cash = round_money(get_cash(session, pod_id))
    return PortfolioView(
        pod_id=pod_id,
        as_of=now,
        cash=cash,
        positions=views,
        positions_value=round_money(positions_value),
        total_value=round_money(cash + positions_value),
        unrealized_pnl=round_money(unrealized),
        pricing_errors=pricing_errors,
    )
