"""Configuration precedence.

``config.yaml`` says environment variables override it, and the loader must
actually honour that — the failure mode otherwise is silent and nasty: you point
``FUND_DATABASE_URL`` at a scratch database, the override is ignored, and you
write to the real one.
"""

from __future__ import annotations

import pytest

from app.config import CONFIG_PATH, Settings


@pytest.fixture
def env(monkeypatch):
    """Clear any FUND_* variables the developer's shell might already have."""
    import os

    for key in list(os.environ):
        if key.startswith("FUND_"):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_yaml_supplies_the_baseline(env):
    settings = Settings()
    assert CONFIG_PATH.exists()
    assert settings.database_url == "sqlite:///fund.db"
    assert settings.oms.fee_rate == 0.001


def test_env_beats_yaml(env):
    env.setenv("FUND_DATABASE_URL", "sqlite:///scratch.db")
    assert Settings().database_url == "sqlite:///scratch.db"


def test_env_beats_yaml_for_nested_keys(env):
    env.setenv("FUND_OMS__FEE_RATE", "0.05")
    assert Settings().oms.fee_rate == 0.05


def test_overriding_one_nested_key_keeps_its_siblings(env):
    """A nested override must merge into its section, not replace it."""
    env.setenv("FUND_MARKETDATA__PROVIDER", "static")
    settings = Settings()
    assert settings.marketdata.provider == "static"
    assert settings.marketdata.cache_ttl_seconds == 60.0  # still from config.yaml


def test_explicit_arguments_beat_everything(env):
    env.setenv("FUND_DATABASE_URL", "sqlite:///from-env.db")
    assert Settings(database_url="sqlite:///explicit.db").database_url == (
        "sqlite:///explicit.db"
    )


def test_the_json_logging_alias_still_works(env):
    """config.yaml spells it ``json``; the model calls it ``json_logs``."""
    assert Settings().logging.json_logs is True
