"""Runtime configuration.

Single source of truth is ``config.yaml`` at the repo root. Values can be
overridden by environment variables prefixed with ``FUND_`` (nested keys use a
double underscore, e.g. ``FUND_OMS__FEE_RATE=0.002``). Load the settings once via
:func:`get_settings`; it is cached so every component sees the same object.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
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
    # "yfinance" for real delayed quotes, "static" for an offline fixed table,
    # "synthetic" for a keyed offline random walk (backtests, ADR-030).
    provider: Literal["yfinance", "static", "synthetic", "made_up"] = "yfinance"
    # Reuse a quote while the clock has advanced less than this. 0 disables.
    cache_ttl_seconds: float = Field(default=60.0, ge=0.0)
    # Prices used when provider == "static" (ticker -> price).
    static_prices: dict[str, float] = Field(default_factory=dict)
    # provider == "synthetic": the world's secret key — whoever holds it knows
    # every future close (red-team 0010). Hex, ≥ 32 digits (128 bits), from
    # `secrets.token_hex(32)`. Environment only (FUND_MARKETDATA__SYNTHETIC_KEY),
    # never config.yaml: the file is committed. No default — no key, no world.
    synthetic_key: SecretStr | None = None
    # provider == "made_up": a market with a planted law, described by a short recipe
    # (app/marketdata/made_up.py, validated there). Like the key, it is the world: environment only
    # (FUND_MARKETDATA__MADE_UP, JSON), set by whoever hosts the world.
    made_up: dict[str, Any] | None = None
    # Each symbol's price on 2000-01-01.
    synthetic_symbols: dict[str, float] = Field(
        default_factory=lambda: {"SYNA": 100.0, "SYNB": 50.0, "SYNC": 20.0}
    )

    @field_validator("synthetic_key")
    @classmethod
    def _key_is_long_hex(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not re.fullmatch(
            r"(?:[0-9a-fA-F]{2}){16,64}", value.get_secret_value()
        ):
            raise ValueError(
                "synthetic_key must be an even 32..128 hex digits (≥ 128 bits)"
            )
        return value

    @field_validator("synthetic_symbols")
    @classmethod
    def _symbols_are_priced(cls, value: dict[str, float]) -> dict[str, float]:
        if not all(math.isfinite(p) and p > 0 for p in value.values()):
            raise ValueError("synthetic_symbols prices must be positive and finite")
        return value


class MetricsConfig(BaseModel):
    # Daily risk-free rate subtracted from returns before the Sharpe ratio.
    # 0.0 means "Sharpe measured against cash at 0%", which is the honest
    # default for a simulated fund with no financing model.
    risk_free_daily: float = Field(default=0.0)
    # Used only to annualise the daily Sharpe. 252 is the market convention.
    trading_days_per_year: int = Field(default=252, gt=0)


class GatesConfig(BaseModel):
    """The validation gates' law (app/strategy/gates.py): every threshold a pitch is judged by.
    Initial parameters from the Human's notes (IC ≈ 0.03 on many predictions), never in code."""

    # The most recent days before today that research may not see; pitches are judged on them.
    holdout_days: int = Field(default=180, ge=30)
    # The longest window one research backtest may cover.
    research_max_days: int = Field(default=1095, ge=30)
    # IC: mean rank IC at least this, over at least this many predictions.
    min_ic: float = Field(default=0.03, gt=0.0, lt=1.0)
    min_predictions: int = Field(default=300, ge=1)
    # Deflated Sharpe: the probability that the true Sharpe beats the best of N luckless tries.
    min_deflated_sharpe: float = Field(default=0.95, gt=0.0, lt=1.0)
    # Fewer daily returns than this and a ratio or a correlation is null, not a number.
    min_periods: int = Field(default=60, ge=10)
    # Capacity: square-root impact, cost = k σ sqrt(traded / daily dollar volume) per trade;
    # the capacity is the gross exposure (capital × gross) at which that cost eats this share of the edge.
    impact_coefficient: float = Field(default=1.0, gt=0.0)
    capacity_edge_share: float = Field(default=0.5, gt=0.0, le=1.0)
    min_capacity_usd: float = Field(default=1_000_000.0, gt=0.0)
    # Correlation of daily returns with any other pod's latest pitch: at most this.
    max_correlation: float = Field(default=0.5, gt=0.0, le=1.0)
    # Does a closed pod's latest pitch count among the "other pods" above? Not since cycle 54
    # (red-team: a dead pod's PM could block live pods' rules at no cost); its traded rule still
    # does. True is the rule as it was, kept only for hosted worlds whose recipe names no laws
    # (every recording made before it), so they replay as recorded (auditor). Never in the law a
    # verdict carries: those recordings were shown that law without it.
    closed_pod_pitches_bind: bool = Field(default=False, exclude=True)


class CapitalConfig(BaseModel):
    """The capital machine's law (app/capital/): the centre's capital, the seed, how capital moves
    and the drawdown ladder. Frozen into the ledger when a run's centre opens, so a run is judged by
    the law it opened with, not by a later edit of this file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # The centre's capital when it opens; every pod's money comes from it and returns to it.
    firm_capital_usd: float = Field(default=10_000_000.0, gt=0.0, le=1e12)
    # What an eligible pitch earns at the next day.
    seed_usd: float = Field(default=200_000.0, gt=0.0, le=1e12)
    # Days between two re-weighings of capital.
    reallocate_every_days: int = Field(default=5, ge=1, le=365)
    # Fewer forward daily returns than this: no score (null, not 0) and the pod's capital stays.
    min_track_days: int = Field(default=20, ge=5, le=1000)
    # Share of the firm's equity the algorithm may put into pods; a pod's ceiling for raises.
    deploy_share: float = Field(default=0.8, gt=0.0, le=1.0)
    max_pod_share: float = Field(default=0.3, gt=0.0, le=1.0)
    # A raise needs at least this viability (the t-statistic of the pod's net daily mean, after
    # the penalties for copying an older pod and for drawdown): below it, the capital stays.
    raise_at: float = Field(default=2.0, gt=0.0, le=100.0)
    # A pod with no positive score is taken down toward this, never below it, by the algorithm.
    min_pod_usd: float = Field(default=100_000.0, ge=0.0, le=1e12)
    # One re-weighing grows a pod's capital by at most this share, and shrinks it by at most that.
    max_raise: float = Field(default=0.5, gt=0.0, le=10.0)
    max_cut: float = Field(default=0.5, gt=0.0, lt=1.0)
    # A move smaller than this share of the pod's equity is not made (no churn).
    min_move: float = Field(default=0.05, ge=0.0, lt=1.0)
    # The drawdown ladder, from the pod's high-water mark on its forward return index.
    halve_at: float = Field(default=0.05, gt=0.0, lt=1.0)
    reduce_only_at: float = Field(default=0.075, gt=0.0, lt=1.0)
    close_at: float = Field(default=0.10, gt=0.0, lt=1.0)
    # Tell each PM what the machine decided that touches its pod (idea: the firm lives a quarter):
    # every eligible pitch gets a capital answer (a seeded pod's later pitches too: "your pod
    # already runs pitch #N"), and its capital view carries the hiring law (a closed pod is
    # replaced). Off by default, and left out of the frozen law while off, so a run recorded before
    # it existed replays as it was; a world turns it on (its recipe's ``laws``).
    tell_pms: bool = Field(default=False, exclude_if=lambda v: v is False)

    @model_validator(mode="after")
    def _ladder_climbs(self) -> CapitalConfig:
        if not self.halve_at < self.reduce_only_at < self.close_at:
            raise ValueError("the ladder must climb: halve_at < reduce_only_at < close_at")
        return self


class HiringConfig(BaseModel):
    """The hiring law (idea: a dead pod is replaced): when the risk ladder closes a pod, a vacancy
    opens and the firm hires a new PM into a new pod. Frozen into the run's first vacancy, as the
    capital law is into ``capital_opened``. The law decides the hire; no Builder, no agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Pods that are not closed, at most, once a vacancy is filled: a fill beyond it is refused.
    max_live_pods: int = Field(default=8, ge=1, le=1000)
    # The models a new PM is drawn from, in turn: the n-th vacancy hires models[(n - 1) % len].
    models: tuple[str, ...] = Field(default=("anthropic/claude-haiku-5.5",), min_length=1,
                                    max_length=32)
    # The new PM's thinking budget (its key's limit); the Runtime checks it against the cap.
    budget_usd: float = Field(default=0.30, gt=0.0, le=50.0)
    # The new PM's charter: who it is and what it must do. The post-mortem comes with the hire.
    charter: str = Field(default=(
        "You are the newly hired portfolio manager of a pod in a hedge fund that trades a simulated "
        "market with fake money. The pod before you was closed by the risk ladder: its post-mortem "
        "(its rule, its forward days, the drawdown that closed it) is in your input. Your pod gets "
        "capital only after you pitch a strategy and it passes the fund's validation gates; an "
        "eligible pitch earns a small seed and trades forward. Research with run_research_backtest "
        "on past data (the most recent days are held out, and your pitch is judged on them; every "
        "backtest is counted). Pitch once, with submit_pitch, when you believe in a rule. Once your "
        "pod is seeded, each day read your mandate (get_mandate) and place its orders "
        "(place_order): that is how your rule trades. You remember nothing between days: read "
        "your research, pitches and capital first. Be brief: every word you think is paid from "
        "your pod's P&L. When you are done for the day, stop."),
        min_length=1, max_length=8000)

    @field_validator("models")
    @classmethod
    def _models_are_named(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(isinstance(m, str) and re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", m) for m in value):
            raise ValueError("models: plain model ids (letters, digits, . _ : / -)")
        return value


class GenerationConfig(BaseModel):
    """The generation law (idea: every month is a generation): at each month's end physics measures
    every pod's fitness (its P&L that month net of its thinking that month), lets go the PMs who
    failed and keeps each one's lesson in a library every PM reads. Off by default, so a run
    recorded before it existed replays as it was; a world turns it on (its recipe's ``laws``).
    Frozen into the run's first ``generation_ended``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    on: bool = False
    # A PM whose pod has no seed at a month's end is let go only after this many days in its pod:
    # a PM hired late in a month is judged at the next month's end.
    grace_days: int = Field(default=20, ge=0, le=366)


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
        data = _load_yaml(CONFIG_PATH)
        # The file is committed; a world key in it is a published future (ADR-030).
        if "synthetic_key" in (data.get("marketdata") or {}):
            raise ValueError(
                f"{CONFIG_PATH}: marketdata.synthetic_key is environment only "
                "(FUND_MARKETDATA__SYNTHETIC_KEY), never the committed file"
            )
        return data


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
    gates: GatesConfig = Field(default_factory=GatesConfig)
    capital: CapitalConfig = Field(default_factory=CapitalConfig)
    hiring: HiringConfig = Field(default_factory=HiringConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
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
