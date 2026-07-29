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
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = parent of the ``app`` package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


class ClockConfig(BaseModel):
    mode: Literal["live", "backtest"] = "live"


class OMSConfig(BaseModel):
    # Flat simulated fee as a fraction of notional (0.1% default). Used from Phase 1.
    fee_rate: float = Field(default=0.001, ge=0.0)


class LoggingConfig(BaseModel):
    # Accept the natural YAML key "json" while avoiding the shadowed
    # BaseModel.json attribute name internally.
    model_config = ConfigDict(populate_by_name=True)

    level: str = "INFO"
    json_logs: bool = Field(default=True, alias="json")


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class Settings(BaseSettings):
    """Top-level settings object."""

    model_config = SettingsConfigDict(
        env_prefix="FUND_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    database_url: str = "sqlite:///fund.db"
    clock: ClockConfig = Field(default_factory=ClockConfig)
    oms: OMSConfig = Field(default_factory=OMSConfig)
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
    return Settings(**_load_yaml(CONFIG_PATH))
