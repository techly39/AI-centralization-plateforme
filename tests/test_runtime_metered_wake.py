"""M-001, milestone 1: waking a metered mind through the native adapter (ADR-044).

The fixtures are test_runtime_native's: an in-process App, a desk (pod, PM, key), a table of test
scripts, and a governance directory the test owns (cap null unless a test sets one).
"""

from __future__ import annotations

import pytest

from runtime.metering import FakeProvisioner, Meter
from runtime.native import wake
from tests.test_runtime_native import (  # noqa: F401 - fixtures
    _calls,
    _orders,
    _spec,
    anyio_backend,
    fund_client,
    gov,
    scripts,
)

CAP_50 = "firm:\n  monthly_llm_usd_cap: 50\n"


def _metered_spec(**fields):
    return _spec(**({"provider": "fake-metered", "script": "buy", "budget_usd": 20.0} | fields))


def _keyed(pm_id: int, limit: int = 20_000_000) -> tuple[FakeProvisioner, Meter]:
    prov = FakeProvisioner()
    return prov, Meter(prov, prov.create_key(pm_id, limit))


@pytest.mark.anyio
async def test_wake_of_a_fake_metered_mind_without_a_meter_is_refused_no_metered_key(
        fund_client, desk, gov, scripts) -> None:
    (gov / "human.yaml").write_text(CAP_50)
    _, _, pm_key = desk
    scripts(buy=_calls("place_order"))
    rec = await wake(_metered_spec(), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.reason, rec.transcript) == ("refused", "no_metered_key", ())


@pytest.mark.anyio
async def test_a_metered_mind_with_a_key_wakes_and_is_charged_once_per_turn(
        fund_client, desk, gov, scripts, SessionFactory) -> None:
    (gov / "human.yaml").write_text(CAP_50)
    _, pm_id, pm_key = desk
    scripts(buy=_calls("place_order"))
    prov, meter = _keyed(pm_id)
    rec = await wake(_metered_spec(), fund_client(pm_key), workflow_input={}, meter=meter)
    assert (rec.ended, rec.tool_calls) == ("done", 1)
    assert len(rec.exchanges) == 2 == prov.charges(meter.key_ref)   # a turn to trade, a turn to stop
    [usage] = prov.usage()
    assert usage.usd_micros_total > 0 and usage.agent_id == pm_id
    assert round(sum(e.usage.cost_usd for e in rec.exchanges), 6) == usage.usd_micros_total / 1e6
    assert len(_orders(SessionFactory)) == 1


@pytest.mark.anyio
async def test_a_metered_mind_with_a_key_does_not_wake_under_cap_null(
        fund_client, desk, scripts) -> None:
    _, pm_id, pm_key = desk
    scripts(buy=_calls("place_order"))
    prov, meter = _keyed(pm_id)
    rec = await wake(_metered_spec(), fund_client(pm_key), workflow_input={}, meter=meter)
    assert (rec.ended, rec.reason) == ("refused", "cap_null")
    assert prov.usage()[0].usd_micros_total == 0


@pytest.mark.anyio
async def test_a_charge_past_the_key_limit_ends_the_wake_as_an_error(
        fund_client, desk, gov, scripts) -> None:
    (gov / "human.yaml").write_text(CAP_50)
    _, pm_id, pm_key = desk
    scripts(buy=_calls("place_order"))
    prov, meter = _keyed(pm_id, limit=1)                             # one micro-dollar
    rec = await wake(_metered_spec(), fund_client(pm_key), workflow_input={}, meter=meter)
    assert (rec.ended, rec.reason) == ("error", "provider_error:LimitExceeded")
    assert prov.usage()[0].usd_micros_total == 0
