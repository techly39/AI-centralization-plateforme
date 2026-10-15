"""M-001: a metered month is deterministic — same world, same specs, same charges (ADR-044 §9).

Charges depend on the length of every request, which carries every tool result the App returned:
one varying field (a wall-clock stamp, a random id) would change the meter between two runs of the
same world. Two fresh databases, the same keyed synthetic market, the same fake-metered PM: the
provisioner's usage and the whole ledger (ids, stamps, payloads) must be identical.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.db.base import get_session
from app.db.models import AgentRole, Event
from app.main import create_app
from app.marketdata import SyntheticProvider, set_provider
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent, seed_runtime_agent
from app.run_clock import start_backtest
from mcp_server import FundClient
from runtime import governance
from runtime.lockstep import Mind, run_backtest
from runtime.metering import FakeProvisioner, Meter, sync_costs
from runtime.spec import AgentSpec
from tests.support import world_key
from tests.test_phase3_probe import CAPITAL, START, SYMBOLS, _fresh_database

DAYS = 6


def _metered_month(world: int):
    _, Sessions = _fresh_database()
    set_provider(SyntheticProvider(world_key(world), SYMBOLS))
    with Sessions() as s:
        start_backtest(s, start=START)
        _, clock_key = seed_runtime_agent(s)
        pod = create_pod(s, name="runtime-desk")
        fund_pod(s, pod_id=pod.id, delta=CAPITAL, actor=get_or_create_system_agent(s),
                 reason="probe capital")
        agent, pm_key = register_agent(s, name="pm-runtime", role=AgentRole.pm, pod_id=pod.id)
        s.commit()
        pod_id, pm_id = pod.id, agent.id

    app = create_app()

    def _session():
        s = Sessions()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_session] = _session
    spec = AgentSpec(id="pm-a", name="pm-runtime", role="pm", pod=pod_id, provider="fake-metered",
                     script="moving-average-pm", budget_usd=20.0, charter="Run the desk.")
    prov = FakeProvisioner()
    meter = Meter(prov, prov.create_key(pm_id, 20_000_000))
    runs = []

    async def month() -> None:
        transport = httpx.ASGITransport(app=app)
        async with FundClient(base_url="http://fund.test", api_key=pm_key,
                              transport=transport) as pm, \
                FundClient(base_url="http://fund.test", api_key=clock_key,
                           transport=transport) as clock:
            runs.append(await run_backtest([Mind(spec, pm, meter)], clock, steps=DAYS,
                                           workflow_input={"universe": list(SYMBOLS)}))
            await sync_costs(prov, clock)

    with TestClient(app):
        asyncio.run(month())
    (run,) = runs
    assert (run.ended, len(run.steps)) == ("completed", DAYS), run.reason
    with Sessions() as s:
        ledger = [(e.id, e.ts.isoformat(), e.actor_agent_id, e.type, e.payload_json)
                  for e in s.execute(select(Event).order_by(Event.id)).scalars()]
    return prov.usage(), prov.charges(meter.key_ref), ledger


@pytest.fixture
def cap_50(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.registry import halt
    d = tmp_path / "gov"
    d.mkdir()
    (d / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: 50\n")
    monkeypatch.setattr(governance, "HALT_FILE", d / "HALT")
    monkeypatch.setattr(governance, "HUMAN_YAML", d / "human.yaml")
    monkeypatch.setattr(halt, "HALT_FILE", d / "PHYSICS_HALT")
    monkeypatch.setattr(get_settings().oms, "pending_monitor_enabled", False)
    yield
    set_provider(None)
    set_clock(LiveClock())


def test_metered_runs_are_deterministic(cap_50) -> None:
    first, second = _metered_month(11), _metered_month(11)
    usage, charges, ledger = first
    assert usage[0].usd_micros_total > 0 and charges >= DAYS
    assert first == second                       # charges to the micro-dollar, and the whole ledger
    assert [e[3] for e in ledger].count("cost_metered") == 1


def test_a_different_world_is_a_different_meter(cap_50) -> None:
    """Counter-example to a meter that ignores the world: another market, other prices, other bytes."""
    assert _metered_month(11)[0] != _metered_month(12)[0]
