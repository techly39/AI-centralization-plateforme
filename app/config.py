"""Runtime configuration.

Single source of truth is ``config.yaml`` at the repo root. Values can be
overridden by environment variables prefixed with ``FUND_`` (nested keys use a
double underscore, e.g. ``FUND_OMS__FEE_RATE=0.002``). Load the settings once via
:func:`get_settings`; it is cached so every component sees the same object.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Repo root = parent of the ``app`` package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


class OMSConfig(BaseModel):
    # Flat simulated fee as a fraction of notional (0.1% default), TRD §8.2.
    fee_rate: float = Field(default=0.001, ge=0.0)
    # How often the background job re-checks pending limit orders (TRD §8.4).
    # In backtest mode this is ignored: the check runs on every clock advance.
    pending_check_minutes: float = Field(default=1.0, gt=0.0)
    # Master switch for that background job. Turned off in tests and whenever
    # you want a server that only ever acts on explicit API calls.
    pending_monitor_enabled: bool = True


class MarketDataConfig(BaseModel):
    # "yfinance" for real delayed quotes, "static" for an offline fixed table.
    provider: Literal["yfinance", "static"] = "yfinance"
    # Reuse a quote while the clock has advanced less than this. 0 disables.
    cache_ttl_seconds: float = Field(default=60.0, ge=0.0)
    # Prices used when provider == "static" (ticker -> price).
    static_prices: dict[str, float] = Field(default_factory=dict)


class MetricsConfig(BaseModel):
    # Daily risk-free rate subtracted from returns before the Sharpe ratio.
    # 0.0 means "Sharpe measured against cash at 0%", which is the honest
    # default for a simulated fund with no financing model.
    risk_free_daily: float = Field(default=0.0)
    # Used only to annualise the daily Sharpe. 252 is the market convention.
    trading_days_per_year: int = Field(default=252, gt=0)


class MCPConfig(BaseModel):
    """Settings for the MCP server (``mcp_server/``), not for the API itself.

    The MCP server is a *client* of the REST API: it holds one agent's key and
    forwards it. Put the key in the environment (``FUND_MCP__API_KEY``) rather
    than in ``config.yaml`` — the file is committed, the environment is not.
    """

    api_base_url: str = "http://127.0.0.1:8000"
    api_key: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0.0)


class LoggingConfig(BaseModel):
    # Accept the natural YAML key "json" while avoiding the shadowed
    # BaseModel.json attribute name internally.
    model_config = ConfigDict(populate_by_name=True)

    level: str = "INFO"
    json_logs: bool = Field(default=True, alias="json")


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class YamlSettingsSource(PydanticBaseSettingsSource):
    """Reads ``config.yaml`` as a settings source.

    It exists so the file can be ranked *below* environment variables. Passing
    the YAML in as constructor kwargs (the obvious approach) makes it rank
    *above* env vars, which silently breaks every ``FUND_*`` override for keys
    the file happens to mention — the exact opposite of what the file's own
    comments promise.
    """

    def get_field_value(  # pragma: no cover - required by the ABC, unused
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return _load_yaml(CONFIG_PATH)


class Settings(BaseSettings):
    """Top-level settings object.

    Precedence, highest first: explicit constructor arguments, ``FUND_*``
    environment variables, ``config.yaml``, then the defaults declared here.
    Nested sections merge across sources, so setting ``FUND_OMS__FEE_RATE``
    overrides only that one key and leaves the rest of the ``oms`` block alone.
    """

    model_config = SettingsConfigDict(
        env_prefix="FUND_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlSettingsSource(settings_cls),
            file_secret_settings,
        )

    database_url: str = "sqlite:///fund.db"
    oms: OMSConfig = Field(default_factory=OMSConfig)
    marketdata: MarketDataConfig = Field(default_factory=MarketDataConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, fully-resolved settings (YAML file + env overrides)."""
    return Settings()
