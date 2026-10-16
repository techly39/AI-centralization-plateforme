"""M-001, milestone 2: keys, the budget law, the conductor's checks and the one sync (ADR-044).

* **vet / provision** — a metered spec is judged as if its key existed; the budgets fit the cap
  together, exactly (whole micro-dollars); one key per metered agent, bound to the agent
  provisioning registered; a zero-cost mind gets none;
* **the conductor** — a key must be its own agent's, and the limits must fit the cap now, at
  every step: a caller who hands in minds cannot go around ``vet``;
* **the command** — the keys' totals reach the ledger once, as the last events, whatever the end;
  a sync that fails fails the run loudly; a metered run has no cassette; nothing on the command
  line or in the environment reaches the law.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Event
from app.ledger.events import EVENT_CLOCK_ADVANCED, EVENT_COST_METERED
from runtime import cli, metering
from runtime.lockstep import Mind, run_backtest
from runtime.metering import FakeProvisioner, Meter, SyncReport
from runtime.provision import ProvisionError, provision, vet
from runtime.governance import Governance
from runtime.spec import AgentSpec
from mcp_server.client import FundClient
from tests.test_runtime_cli_backtest import _run, keys, _write_specs  # noqa: F401 - fixtures
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    _app,
    gov,
    live_afterwards,
    woke,
    world,
)

CAP = "firm:\n  monthly_llm_usd_cap: {}\n"


def _m_spec(id: str, name: str, pod: int, script: str = "signal-pm", budget: float = 20.0) -> dict:
    return {"id": id, "name": name, "role": "pm", "pod": pod, "provider": "fake-metered",
            "script": script, "budget_usd": budget, "charter": "Read the clock."}


@pytest.fixture
def mspecs(tmp_path: Path) -> Path:
    return _write_specs(tmp_path / "specs", _m_spec("a-pm", "desk-1-pm", 1, "read-a"),
                        _m_spec("b-pm", "desk-2-pm", 2, "read-b"))


def _spec_zero(id: str, name: str, pod: int, script: str) -> dict:
    return {"id": id, "name": name, "role": "pm", "pod": pod, "provider": "scripted",
            "script": script, "charter": "Read the clock."}


def _cap(gov: Path, value) -> None:
    (gov / "human.yaml").write_text(CAP.format(value))


def _ledger(SessionFactory) -> list[tuple[int, str, int | None, dict]]:
    with SessionFactory() as s:
        return [(e.id, e.type, e.actor_agent_id,
                 json.loads(e.payload_json) if isinstance(e.payload_json, str) else e.payload_json)
                for e in s.execute(select(Event).order_by(Event.id)).scalars()]


def _specs(*items: dict) -> list[AgentSpec]:
    return [AgentSpec(**i) for i in items]


# --- vet --------------------------------------------------------------------------------


def test_vet_refuses_metered_specs_under_cap_null_with_cap_null() -> None:
    specs = _specs(_m_spec("a-pm", "desk-1-pm", 1))
    assert vet(specs, Governance(False, None)) == "wake_refused:a-pm:cap_null"


@pytest.mark.parametrize("cap, verdict", [
    (40.0, None),                       # budgets 20 + 20 == cap, in micro-dollars: fits
    (39.999999, "budget_over_cap"),     # one micro-dollar short
    (40.000001, None),
    (0.0, "budget_over_cap"),
])
def test_vet_budget_sum_boundary(cap, verdict) -> None:
    specs = _specs(_m_spec("a-pm", "desk-1-pm", 1), _m_spec("b-pm", "desk-2-pm", 2))
    assert vet(specs, Governance(False, cap)) == verdict


def test_vet_refuses_a_budget_above_max_metered_micros() -> None:
    specs = _specs(_m_spec("a-pm", "desk-1-pm", 1, budget=1_000_001.0))
    assert vet(specs, Governance(False, 5e6)) == "budget_too_large:a-pm"


def test_zero_cost_specs_do_not_count_against_the_budget() -> None:
    zero = {"id": "z", "name": "desk-3-pm", "role": "pm", "pod": 3, "provider": "scripted",
            "script": "moving-average-pm", "charter": "x"}
    specs = _specs(_m_spec("a-pm", "desk-1-pm", 1), zero)
    assert vet(specs, Governance(False, 20.0)) is None


# --- provision --------------------------------------------------------------------------


def _provision(SessionFactory, specs, registrar_key, **kwargs):
    app = _app(SessionFactory)

    async def go():
        transport = httpx.ASGITransport(app=app)

        def connect(key: str) -> FundClient:
            return FundClient(base_url="http://fund.test", api_key=key, transport=transport)
        registrar = connect(registrar_key)
        try:
            minds = await provision(specs, registrar, connect, **kwargs)
            for m in minds:
                await m.client.aclose()
            return minds
        finally:
            await registrar.aclose()
    with TestClient(app):
        return asyncio.run(go())


def test_provision_mints_one_key_per_metered_agent_bound_to_its_id(
        SessionFactory, world, woke, gov) -> None:
    _cap(gov, 50)
    prov = FakeProvisioner()
    minds = _provision(SessionFactory, _specs(_m_spec("a-pm", "desk-1-pm", 1),
                                              _m_spec("b-pm", "desk-2-pm", 2, "read-b", budget=5.5)),
                       world["admin"], provisioner=prov)
    assert [m.spec.id for m in minds] == ["a-pm", "b-pm"]
    [ka, kb] = [m.meter.key_ref for m in minds]
    assert ka != kb and [prov.limit(ka), prov.limit(kb)] == [20_000_000, 5_500_000]
    # Each key is the agent provisioning registered for the spec, read back from physics.
    from app.db.models import Agent
    with SessionFactory() as s:
        ids = {a.name: a.id for a in s.execute(select(Agent)).scalars()}
    assert [prov.agent_of(ka), prov.agent_of(kb)] == [ids["desk-1-pm"], ids["desk-2-pm"]]


def test_zero_cost_minds_get_no_key(SessionFactory, world, woke, gov) -> None:
    zero = {"id": "z-pm", "name": "desk-3-pm", "role": "pm", "pod": 3, "provider": "scripted",
            "script": "read-c", "charter": "x"}
    _cap(gov, 50)
    prov = FakeProvisioner()
    minds = _provision(SessionFactory, _specs(_m_spec("a-pm", "desk-1-pm", 1), zero),
                       world["admin"], provisioner=prov)
    assert [m.meter is None for m in minds] == [False, True]
    assert len(prov.usage()) == 1


def test_metered_specs_without_a_provisioner_are_refused(SessionFactory, world, woke, gov) -> None:
    _cap(gov, 50)
    before = _ledger(SessionFactory)
    with pytest.raises(ProvisionError) as exc:
        _provision(SessionFactory, _specs(_m_spec("a-pm", "desk-1-pm", 1)), world["admin"])
    assert exc.value.reason == "no_provisioner" and exc.value.registered == ()
    assert _ledger(SessionFactory) == before                 # no agent was registered


# --- the conductor ----------------------------------------------------------------------


def _conduct(SessionFactory, handed, clock_key: str, **kwargs):
    """handed: ``(spec, api_key, meter | None)``; the conductor against the test App."""
    app = _app(SessionFactory)

    async def go():
        transport = httpx.ASGITransport(app=app)

        def client(key: str) -> FundClient:
            return FundClient(base_url="http://fund.test", api_key=key, transport=transport)
        clients = [client(k) for _, k, _ in handed]
        clock = client(clock_key)
        try:
            minds = [Mind(spec, c, meter) for (spec, _, meter), c in zip(handed, clients)]
            return await run_backtest(minds, clock, **kwargs)
        finally:
            for c in [*clients, clock]:
                await c.aclose()
    with TestClient(app):
        return asyncio.run(go())


def _pm_spec(id: str, pod: int, script: str = "read-a", budget: float = 20.0) -> AgentSpec:
    return AgentSpec(**(_m_spec(id, f"pm-{pod}", pod, script, budget)))


def _agent_id(SessionFactory, name: str) -> int:
    from app.db.models import Agent
    with SessionFactory() as s:
        return s.execute(select(Agent).where(Agent.name == name)).scalar_one().id


def test_a_handed_in_meter_for_another_agent_is_refused_meter_mismatch(
        SessionFactory, world, woke, gov) -> None:
    _cap(gov, 50)
    prov = FakeProvisioner()
    wrong = Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-2"), 1_000_000))
    run = _conduct(SessionFactory, [(_pm_spec("a-pm", 1), world["pm"][1], wrong)],
                   world["clock"], steps=2)
    assert (run.ended, run.reason) == ("refused", "meter_mismatch:a-pm")
    assert woke == [] and prov.usage()[0].usd_micros_total == 0


def test_two_provisioners_in_one_run_are_refused(SessionFactory, world, woke, gov) -> None:
    _cap(gov, 50)
    one, two = FakeProvisioner(), FakeProvisioner()
    handed = [(_pm_spec("a-pm", 1), world["pm"][1],
               Meter(one, one.create_key(_agent_id(SessionFactory, "pm-1"), 1_000_000))),
              (_pm_spec("b-pm", 2, "read-b"), world["pm"][2],
               Meter(two, two.create_key(_agent_id(SessionFactory, "pm-2"), 1_000_000)))]
    run = _conduct(SessionFactory, handed, world["clock"], steps=1)
    assert (run.ended, run.reason) == ("refused", "meter_mismatch:provisioner")


def test_handed_in_minds_whose_limits_exceed_the_cap_are_refused(
        SessionFactory, world, woke, gov) -> None:
    """The bypass of ``vet``: minds handed straight to the conductor."""
    _cap(gov, 10)
    prov = FakeProvisioner()
    handed = [(_pm_spec("a-pm", 1), world["pm"][1],
               Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-1"), 6_000_000))),
              (_pm_spec("b-pm", 2, "read-b"), world["pm"][2],
               Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-2"), 6_000_000)))]
    run = _conduct(SessionFactory, handed, world["clock"], steps=2)
    assert (run.ended, run.reason) == ("refused", "metered_over_cap")
    assert woke == [] and [u.usd_micros_total for u in prov.usage()] == [0, 0]


def test_a_cap_lowered_mid_run_ends_it_metered_over_cap_at_the_next_step(
        SessionFactory, world, woke, gov, monkeypatch) -> None:
    from types import MappingProxyType

    from runtime import scripted
    from runtime.providers import CompletionResponse

    def lowers(request):
        _cap(gov, 5)                                 # the Human lowers the cap during step 0
        return CompletionResponse(content="done")
    monkeypatch.setattr(scripted, "SCRIPTS",
                        MappingProxyType(dict(scripted.SCRIPTS) | {"lowers": lowers}))
    _cap(gov, 50)
    prov = FakeProvisioner()
    handed = [(_pm_spec("a-pm", 1, "lowers"), world["pm"][1],
               Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-1"), 20_000_000)))]
    run = _conduct(SessionFactory, handed, world["clock"], steps=3)
    assert (run.ended, run.reason, len(run.steps)) == ("refused", "metered_over_cap", 1)
    assert prov.usage()[0].usd_micros_total > 0     # step 0 was lived and billed


# --- the command ------------------------------------------------------------------------


def _fold(SessionFactory) -> tuple[dict[str, int], list[tuple[int, str, int | None, dict]]]:
    ledger = _ledger(SessionFactory)
    top: dict[str, int] = {}
    for _, t, _, p in ledger:
        if t == EVENT_COST_METERED:
            top[p["key_ref"]] = max(top.get(p["key_ref"], 0), p["usd_micros_total"])
    return top, ledger


def test_metered_month_syncs_once_after_the_last_step(
        SessionFactory, keys, mspecs, woke, gov, capsys) -> None:
    _cap(gov, 50)
    code, out, err = _run(SessionFactory, ["--specs", str(mspecs), "--steps", "3"], capsys)
    assert code == 0 and out["ended"] == "completed", err
    m = out["metering"]
    assert [k["spec_id"] for k in m["keys"]] == ["a-pm", "b-pm"]
    assert m["cap_usd_micros"] == 50_000_000 and m["sync"]["error"] is None
    # one charge per model turn: two turns a wake (the reader asks for the clock, then stops)
    assert [k["charges"] for k in m["keys"]] == [6, 6]
    top, ledger = _fold(SessionFactory)
    assert sum(top.values()) == m["total_usd_micros"] == sum(k["spent_usd_micros"] for k in m["keys"]) > 0
    rows = [e for e in ledger if e[1] == EVENT_COST_METERED]
    last_advance = max(e[0] for e in ledger if e[1] == EVENT_CLOCK_ADVANCED)
    assert len(rows) == 2 and [e[0] for e in rows] == [e[0] for e in ledger[-2:]]
    assert rows[0][0] > last_advance


def test_an_early_end_still_syncs_what_was_spent(
        SessionFactory, keys, tmp_path, woke, gov, capsys, monkeypatch) -> None:
    """Counter-example to "sync only on completed": a cap lowered after step 0 ends the run."""
    from types import MappingProxyType

    from runtime import scripted
    from runtime.providers import CompletionResponse

    def lowers(request):
        _cap(gov, 5)
        return CompletionResponse(content="done")
    monkeypatch.setattr(scripted, "SCRIPTS",
                        MappingProxyType(dict(scripted.SCRIPTS) | {"lowers": lowers}))
    specs = _write_specs(tmp_path / "s", _m_spec("a-pm", "desk-1-pm", 1, "lowers"))
    _cap(gov, 50)
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "3"], capsys)
    assert (code, out["ended"], out["reason"]) == (1, "refused", "metered_over_cap")
    top, _ = _fold(SessionFactory)
    assert sum(top.values()) == out["metering"]["total_usd_micros"] > 0
    assert out["metering"]["cap_usd_micros"] == 50_000_000   # the cap the run was provisioned under


def test_a_refused_key_post_fails_the_run_loudly(
        SessionFactory, keys, mspecs, woke, gov, capsys, monkeypatch) -> None:
    _cap(gov, 50)
    real = metering.sync_costs

    async def refuses(provisioner, client):
        report = await real(provisioner, client)
        return SyncReport(report.posted, report.unchanged, [("fake-0002", 409, "bound elsewhere")])
    monkeypatch.setattr(cli, "sync_costs", refuses)
    code, out, err = _run(SessionFactory, ["--specs", str(mspecs), "--steps", "2"], capsys)
    assert code == 1 and out["ended"] == "completed"
    spent = [k["spent_usd_micros"] for k in out["metering"]["keys"]][1]
    assert f"{spent} metered micro-dollars not attributed" in err


def test_a_halted_sync_fails_the_run_and_names_the_micros(
        SessionFactory, keys, mspecs, woke, gov, capsys, monkeypatch, tmp_path) -> None:
    from app.registry import halt
    _cap(gov, 50)
    monkeypatch.setattr(halt, "HALT_FILE", tmp_path / "PHYSICS_HALT")
    real = metering.sync_costs

    async def halts_first(provisioner, client):
        (tmp_path / "PHYSICS_HALT").write_text("")   # physics is halted just before the sync
        return await real(provisioner, client)
    monkeypatch.setattr(cli, "sync_costs", halts_first)
    code, out, err = _run(SessionFactory, ["--specs", str(mspecs), "--steps", "2"], capsys)
    assert code == 1 and out["metering"]["sync"]["halted"] is True
    assert f"{out['metering']['total_usd_micros']} metered micro-dollars not attributed" in err
    assert [e for e in _ledger(SessionFactory) if e[1] == EVENT_COST_METERED] == []


def test_a_wrong_clock_key_fails_the_sync_as_data_not_a_crash(
        SessionFactory, keys, mspecs, woke, gov, capsys, monkeypatch) -> None:
    _cap(gov, 50)

    async def denied(provisioner, client):
        from mcp_server.client import FundAPIError
        raise FundAPIError(403, "not yours")
    monkeypatch.setattr(cli, "sync_costs", denied)
    code, out, err = _run(SessionFactory, ["--specs", str(mspecs), "--steps", "1"], capsys)
    assert code == 1 and out["metering"]["sync"]["error"] == "sync_failed:403"
    assert "metered micro-dollars not attributed" in err


def test_a_metered_backtest_records_its_cassette_with_its_metering(
        SessionFactory, keys, mspecs, woke, gov, capsys, tmp_path) -> None:
    """ADR-047 wrote the law ADR-044 §6 left open (the trailing cost block, judged apart by
    ``replay --verify``), so a metered run is recorded like any other."""
    _cap(gov, 50)
    path = tmp_path / "x.cassette.json"
    code, out, err = _run(SessionFactory, ["--specs", str(mspecs), "--steps", "1",
                                           "--cassette", str(path)], capsys)
    assert code == 0, err
    doc = json.loads(path.read_text(encoding="ascii"))
    assert doc["outcome"]["metering"] == out["metering"]
    assert [k["spec_id"] for k in doc["outcome"]["metering"]["keys"]] == ["a-pm", "b-pm"]


def test_replay_refuses_fake_metered_specs_exit_2(
        SessionFactory, keys, mspecs, woke, gov, capsys, tmp_path) -> None:
    """A real recording of the same ids (scripted minds), so the refusal is the specs' own."""
    from runtime.cassette import SUFFIX
    scripted_specs = _write_specs(tmp_path / "scripted", _spec_zero("a-pm", "desk-1-pm", 1, "read-a"),
                                  _spec_zero("b-pm", "desk-2-pm", 2, "read-b"))
    path = tmp_path / f"r{SUFFIX}"
    code, out, err = _run(SessionFactory, ["--specs", str(scripted_specs), "--steps", "2",
                                           "--cassette", str(path)], capsys)
    assert code == 0 and path.is_file(), err
    # The cassette carries its own specs now (M-002): swap in the metered ones, digests right.
    import json
    from runtime import cassette as cas
    doc = json.loads(path.read_text(encoding="ascii"))
    for entry in doc["specs"]:
        entry["spec"].update(provider="fake-metered", script=None, budget_usd=1.0)
        entry["sha256"] = cas.spec_sha256(entry["spec"])
    metered = tmp_path / f"m{SUFFIX}"
    metered.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="ascii")
    code = cli.main(["replay", "--cassette", str(metered)])
    assert code == 2
    assert "cannot replay as cassette minds" in capsys.readouterr().err


def test_the_status_command_judges_a_metered_spec_as_vet_does(
        mspecs, gov, capsys) -> None:
    _cap(gov, 50)
    assert cli.main(["status", "--specs", str(mspecs)]) == 0
    wakes = json.loads(capsys.readouterr().out)["wakes"]
    assert [(w["id"], w["allowed"], w["reason"]) for w in wakes] == [
        ("a-pm", True, "metered"), ("b-pm", True, "metered")]
    _cap(gov, "null")
    assert cli.main(["status", "--specs", str(mspecs)]) == 0
    assert {w["reason"] for w in json.loads(capsys.readouterr().out)["wakes"]} == {"cap_null"}


def test_no_cli_option_reaches_the_law(capsys) -> None:
    """Art. 4: a numeric cap exists only where a process rebinds the law file, never by flag."""
    import re
    for command in ("status", "backtest", "replay"):
        with pytest.raises(SystemExit):
            cli.main([command, "--help"])
        help_text = capsys.readouterr().out
        options = re.findall(r"--[a-z][a-z-]*", help_text)
        assert options and not [o for o in options if re.search(r"cap|law|govern|yaml|budget", o)]


def test_the_yaml_spec_round_trips_a_budget(tmp_path: Path) -> None:
    from runtime.spec import load_specs
    [spec] = load_specs(_write_specs(tmp_path / "s", _m_spec("a-pm", "desk-1-pm", 1, budget=0.1)))
    assert (spec.provider, spec.budget_usd) == ("fake-metered", 0.1)
    assert yaml.safe_load((tmp_path / "s" / "a-pm.yaml").read_text())["budget_usd"] == 0.1
