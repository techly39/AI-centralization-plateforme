"""R-6a: the Runtime's fake provisioner and the cost sync (ADR-041).

Claims under test:

* the fake provisioner refuses a charge past a key's limit and an unknown key,
  is deterministic, and holds no secret;
* ``sync_costs`` posts each key's cumulative total to the agent the key was
  made for, so physics' metered dollars equal the provisioner's charges to the
  micro-dollar (EC4's assertion, on the physics half: no mind spends yet);
* syncing twice writes nothing new; only changed keys are posted again;
* a HALT stops the sync (``halted``), and the next sync catches up exactly;
* a wrong key (a PM's) raises; a refused key is reported and the rest go on.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import select

from app.db.base import get_session
from app.db.models import AgentRole, Event
from app.ledger.events import EVENT_COST_METERED
from app.main import create_app
from app.metrics.metering import metered_by_agent
from app.registry.pods import create_pod
from app.registry.service import register_agent, seed_runtime_agent
from mcp_server import FundClient
from mcp_server.client import FundAPIError
from runtime.metering import FakeProvisioner, LimitExceeded, sync_costs


@pytest.fixture
def world(SessionFactory):
    s = SessionFactory()
    try:
        pod = create_pod(s, name="desk-1")
        pm, pm_key = register_agent(s, name="pm-1", role=AgentRole.pm, pod_id=pod.id)
        an, _ = register_agent(s, name="an-1", role=AgentRole.analyst, pod_id=pod.id)
        _, runtime_key = seed_runtime_agent(s)
        s.commit()
        ids = {"pm": pm.id, "an": an.id, "pm_key": pm_key, "runtime": runtime_key}
    finally:
        s.close()
    return ids


def run_sync(SessionFactory, key, provisioner):
    app = create_app()

    def _session():
        s = SessionFactory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session

    async def go():
        client = FundClient(base_url="http://fund.test", api_key=key,
                            transport=httpx.ASGITransport(app=app))
        try:
            return await sync_costs(provisioner, client)
        finally:
            await client.aclose()

    return asyncio.run(go())


def metered_events(SessionFactory):
    s = SessionFactory()
    try:
        return list(s.execute(select(Event).where(Event.type == EVENT_COST_METERED)).scalars())
    finally:
        s.close()


def seeded(world) -> FakeProvisioner:
    p = FakeProvisioner()
    k1 = p.create_key(world["pm"], limit_usd_micros=10_000_000)
    k2 = p.create_key(world["pm"], limit_usd_micros=10_000_000)
    k3 = p.create_key(world["an"], limit_usd_micros=10_000_000)
    p.charge(k1, 1_250_000)
    p.charge(k2, 2_000_001)
    p.charge(k3, 3_000_000)
    return p


# --- the fake provisioner -----------------------------------------------------

def test_fake_provisioner_refuses_charges_past_the_limit_and_unknown_keys():
    p = FakeProvisioner()
    k = p.create_key(1, limit_usd_micros=100)
    p.charge(k, 60)
    with pytest.raises(LimitExceeded):
        p.charge(k, 41)
    p.charge(k, 40)                      # exactly the limit is allowed
    with pytest.raises(KeyError):
        p.charge("fake-9999", 1)
    with pytest.raises(ValueError):
        p.charge(k, -1)
    assert p.usage()[0].usd_micros_total == 100


def test_fake_provisioner_is_deterministic():
    def build():
        p = FakeProvisioner()
        a = p.create_key(7, limit_usd_micros=50)
        b = p.create_key(8, limit_usd_micros=50)
        p.charge(b, 5)
        p.charge(a, 9)
        return p.usage()
    assert build() == build()
    assert [u.key_ref for u in build()] == ["fake-0001", "fake-0002"]


def test_fake_provisioner_keys_are_valid_key_refs():
    import re
    from app.limits import KEY_REF_PATTERN
    assert re.fullmatch(KEY_REF_PATTERN, FakeProvisioner().create_key(1, limit_usd_micros=1))


# --- the sync -----------------------------------------------------------------

def test_sync_attributes_every_fake_dollar_to_its_agent(SessionFactory, world):
    p = seeded(world)
    report = run_sync(SessionFactory, world["runtime"], p)
    assert (report.posted, report.unchanged, report.refused, report.halted) == (3, 0, [], False)

    s = SessionFactory()
    try:
        got = metered_by_agent(s)
    finally:
        s.close()
    assert got[world["pm"]].usd_micros == 1_250_000 + 2_000_001
    assert got[world["an"]].usd_micros == 3_000_000
    assert sum(m.usd_micros for m in got.values()) == sum(u.usd_micros_total for u in p.usage())


def test_sync_twice_writes_no_new_events(SessionFactory, world):
    p = seeded(world)
    run_sync(SessionFactory, world["runtime"], p)
    before = len(metered_events(SessionFactory))
    again = run_sync(SessionFactory, world["runtime"], p)
    assert (again.posted, again.unchanged) == (0, 3)
    assert len(metered_events(SessionFactory)) == before == 3


def test_sync_after_more_charges_posts_only_changed_keys(SessionFactory, world):
    p = seeded(world)
    run_sync(SessionFactory, world["runtime"], p)
    p.charge("fake-0003", 1)
    again = run_sync(SessionFactory, world["runtime"], p)
    assert (again.posted, again.unchanged) == (1, 2)
    assert len(metered_events(SessionFactory)) == 4


def test_sync_stops_on_halt_and_catches_up_after(SessionFactory, world, halt_file):
    p = seeded(world)
    halt_file.write_text("stop")
    report = run_sync(SessionFactory, world["runtime"], p)
    assert report.halted is True and report.posted == 0
    assert metered_events(SessionFactory) == []
    halt_file.unlink()
    caught = run_sync(SessionFactory, world["runtime"], p)
    assert caught.posted == 3 and caught.halted is False


def test_sync_with_a_pm_key_raises(SessionFactory, world):
    with pytest.raises(FundAPIError) as caught:
        run_sync(SessionFactory, world["pm_key"], seeded(world))
    assert caught.value.status_code == 403
    assert metered_events(SessionFactory) == []


def test_sync_records_a_bound_key_refusal_and_continues(SessionFactory, world):
    first = FakeProvisioner()
    first.charge(first.create_key(world["an"], limit_usd_micros=10), 5)   # fake-0001 -> analyst
    run_sync(SessionFactory, world["runtime"], first)
    clash = FakeProvisioner()                                             # fake-0001 -> pm: clash
    clash.charge(clash.create_key(world["pm"], limit_usd_micros=10), 5)
    clash.charge(clash.create_key(world["pm"], limit_usd_micros=10), 6)   # fake-0002 is free
    report = run_sync(SessionFactory, world["runtime"], clash)
    assert report.posted == 1
    assert [(r[0], r[1]) for r in report.refused] == [("fake-0001", 409)]


def test_sync_reports_an_unknown_agent_and_continues(SessionFactory, world):
    p = FakeProvisioner()
    p.charge(p.create_key(9999, limit_usd_micros=10), 5)
    p.charge(p.create_key(world["pm"], limit_usd_micros=10), 5)
    report = run_sync(SessionFactory, world["runtime"], p)
    assert report.posted == 1
    assert [(r[0], r[1]) for r in report.refused] == [("fake-0001", 404)]
