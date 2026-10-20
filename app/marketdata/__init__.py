"""Market data: the provider interface, its implementations, and the singleton.

Callers ask for :func:`get_provider` and receive whatever ``config.yaml``
selected. Tests (and Phase 3's backtest wiring) swap it with
:func:`set_provider`, exactly like the clock — same pattern, so there is only
one idea to learn.
"""

from __future__ import annotations

from app.config import get_settings
from app.marketdata.base import (
    LIVE_QUOTE_WINDOW,
    VALID_INTERVALS,
    Bar,
    FeedDataError,
    Interval,
    InvalidRequestError,
    LookAheadError,
    MarketDataError,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
    bar_end,
    normalise_ticker,
    validate_window,
)
from app.marketdata.bars_provider import BarsProvider
from app.marketdata.static_provider import StaticProvider
from app.marketdata.synthetic_provider import SyntheticProvider
from app.marketdata.yfinance_provider import YFinanceProvider

_provider: MarketDataProvider | None = None


def _build_default_provider() -> MarketDataProvider:
    cfg = get_settings().marketdata
    if cfg.provider == "static":
        return StaticProvider(cfg.static_prices)
    if cfg.provider == "synthetic":
        if cfg.synthetic_key is None:
            raise ValueError(
                "marketdata.provider is 'synthetic' but no world key is set: put "
                "secrets.token_hex(32) in FUND_MARKETDATA__SYNTHETIC_KEY"
            )
        key = bytes.fromhex(cfg.synthetic_key.get_secret_value())
        return SyntheticProvider(key, cfg.synthetic_symbols)
    if cfg.provider == "made_up":
        from app.marketdata.made_up import MadeUpMarket, bars

        if cfg.made_up is None:
            raise ValueError("marketdata.provider is 'made_up' but no recipe is set: put its JSON "
                             "in FUND_MARKETDATA__MADE_UP")
        return BarsProvider(bars(MadeUpMarket.model_validate(cfg.made_up)))
    return YFinanceProvider(cache_ttl_seconds=cfg.cache_ttl_seconds)


def get_provider() -> MarketDataProvider:
    """The process-wide market data provider (built lazily on first use)."""
    global _provider
    if _provider is None:
        _provider = _build_default_provider()
    return _provider


def set_provider(provider: MarketDataProvider | None) -> None:
    """Install a provider (or ``None`` to fall back to the configured default)."""
    global _provider
    _provider = provider


__all__ = [
    "LIVE_QUOTE_WINDOW",
    "VALID_INTERVALS",
    "Bar",
    "BarsProvider",
    "FeedDataError",
    "Interval",
    "InvalidRequestError",
    "LookAheadError",
    "MarketDataError",
    "MarketDataProvider",
    "Quote",
    "StaticProvider",
    "SyntheticProvider",
    "UnknownTickerError",
    "YFinanceProvider",
    "bar_end",
    "get_provider",
    "normalise_ticker",
    "set_provider",
    "validate_window",
]
