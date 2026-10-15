"""Red-team pass 0021 (M-001, cycle 38+): the metered month (ADR-044).

Holes are ``xfail(strict=True)`` with their severity in the reason: each passes once the
Builder fixes it, and the strict mark then fails the suite so the mark is removed.
Held guards are plain passing tests: they pin what the attack could not break.

Attacked (the mission's new laws first):

(a) the wake gate's ``metered`` flag and its order;
(b) ``FakeProvisioner`` / ``Meter`` / ``FakeMeteredProvider`` / ``usd_to_micros_floor``;
(c) ``vet`` / ``provision``: Σ limits at the micro-dollar, budgets, keys, adapters;
(d) the conductor's ``meter_mismatch`` / ``metered_over_cap`` checks, the cap changed mid-run;
(e) the CLI sync and its exit code;
(f) ``GET /metering/agents`` and what physics ranks on while a metered run is live;
(g) the ``self_reporting`` wrapper;
(h) ``mind_kinds`` for metered specs.
"""

from __future__ import annotations

import json
from types import MappingProxyType

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Event
from app.ledger.events import EVENT_COST_METERED, EVENT_RUN_MINDS_DECLARED
from runtime import cli, metering, scripted
from runtime.gate import decide_wake_under
from runtime.governance import Governance
from runtime.lockstep import mind_kinds
from runtime.metering import FakeProvisioner, Meter, usd_to_micros_floor
from runtime.provision import vet
from runtime.providers import CompletionResponse, ToolCall
from runtime.spec import AgentSpec
from tests.test_runtime_cli_backtest import _write_specs, keys  # noqa: F401 - fixtures
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    _app,
    gov,
    live_afterwards,
    woke,
    world,
)
from tests.test_runtime_metered_run import _agent_id, _cap, _conduct, _m_spec, _pm_spec

CAP_50 = Governance(False, 50.0)


def _add_scripts(monkeypatch: pytest.MonkeyPatch, **more) -> None:
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | more))


def _turns(request) -> int:
    return sum(m.role == "assistant" for m in request.messages)


def _metered_rows(SessionFactory) -> list[dict]:
    with SessionFactory() as s:
        return [e.payload_json for e in s.execute(
            select(Event).where(Event.type == EVENT_COST_METERED).order_by(Event.id)).scalars()]


def _main(app, argv, capsys, transport: httpx.AsyncBaseTransport | None = None):
    """``fund-runtime backtest`` against ``app`` over ASGI: ``(exit, stdout JSON, stderr)``."""
    with TestClient(app):
        code = cli.main(["backtest", *argv],
                        transport=transport or httpx.ASGITransport(app=app))
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


class FailsNthMeteringPost(httpx.AsyncBaseTransport):
    """The App over ASGI; the ``n``-th ``POST /metering/usage`` answers 500 (a lost server)."""

    def __init__(self, app, n: int) -> None:
        self.inner, self.n, self.seen = httpx.ASGITransport(app=app), n, 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/metering/usage":
            self.seen += 1
            if self.seen == self.n:
                return httpx.Response(500, json={"detail": "lost"})
        return await self.inner.handle_async_request(request)


# =========================================================================================
# HOLES
# =========================================================================================

# --- (d) a cap lowered mid-step: the rest of the step still spends ------------------------

# FIXED in M-001 (ADR-044): `run_backtest` checks Σ limits ≤ cap before every wake (high).
def test_hole_a_cap_lowered_to_zero_mid_step_still_lets_the_next_mind_spend(
        SessionFactory, world, woke, gov, monkeypatch) -> None:
    def lowers(request):
        if _turns(request) == 0:
            _cap(gov, 0)                    # the Human lowers the cap to $0 during a's wake
            return CompletionResponse(content="time?", tool_calls=[
                ToolCall(id="c", name="get_clock")])
        return CompletionResponse(content="done")
    _add_scripts(monkeypatch, lowers=lowers)
    _cap(gov, 50)
    prov = FakeProvisioner()
    a = Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-1"), 20_000_000))
    b = Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-2"), 20_000_000))
    run = _conduct(SessionFactory, [(_pm_spec("a-pm", 1, "lowers"), world["pm"][1], a),
                                    (_pm_spec("b-pm", 2, "read-b"), world["pm"][2], b)],
                   world["clock"], steps=1)
    spent = {u.key_ref: u.usd_micros_total for u in prov.usage()}
    # Today: b-pm woke after the cap fell to $0 and was charged for two turns.
    assert spent[b.key_ref] == 0, (run.ended, run.reason, spent)


# --- (f) while the run is live, a metered agent's self-report is what physics ranks on ----

@pytest.mark.xfail(strict=True, reason=(
    "HOLE medium (ADR-044's 'a self-report can no longer move a metered agent's cost or "
    "rank'): the keys are synced once, after the last step, so for the whole run physics "
    "knows no agent is metered. Every leaderboard / pod-metrics read during the month — the "
    "one a management mind allocates on — ranks the metered minds on their own self-reports "
    "(the under-reporting analyst's $0.01/wake) and the silent PM at $0. Fix: in `_conduct`, "
    "right after `provision` returns, `await sync_costs(provisioner, clock)` once (every key "
    "posted at total 0, binding each key to its agent before any wake), or sync before every "
    "advance in `run_backtest`."))
def test_hole_mid_run_leaderboard_ranks_a_metered_mind_on_its_self_report(
        SessionFactory, keys, woke, gov, tmp_path, capsys, monkeypatch) -> None:
    _add_scripts(monkeypatch, **{"reads-reports": scripted.self_reporting(
        scripted.SCRIPTS["read-a"], 0.01)})
    specs = _write_specs(tmp_path / "s", _m_spec("a-pm", "desk-1-pm", 1, "reads-reports"))
    _cap(gov, 50)
    app = _app(SessionFactory)
    seen: dict = {}
    real = metering.sync_costs

    async def peek_then_sync(provisioner, client):
        # The last moment of the run: every wake happened, the final sync has not. What a
        # management mind's `get_leaderboard` would have read during the last step.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://fund.test") as c:
            r = await c.get("/metrics/leaderboard", headers={"X-API-Key": keys["admin"]})
        seen["row"] = next(row for row in r.json()["rows"] if row["pod_id"] == 1)
        return await real(provisioner, client)
    monkeypatch.setattr(cli, "sync_costs", peek_then_sync)
    code, out, err = _main(app, ["--specs", str(specs), "--steps", "3"], capsys)
    assert code == 0, err
    row = seen["row"]
    # Today: metered_usd_cost None, and total_usd_cost == the analyst's own $0.03.
    assert row["metered_usd_cost"] is not None, row
    assert row["total_usd_cost"] != 0.03, row


# --- (b)/(f) a rival bills a metered mind by filling its inbox -----------------------------

@pytest.mark.xfail(strict=True, reason=(
    "HOLE medium (budget: cost charged to another agent): the fake price bills a mind for "
    "every character of its request, tool results included, and any agent may message any "
    "agent (20 000-char bodies, no per-sender quota). A rival — even a zero-cost scripted "
    "mind in another pod, which pays nothing to send — fills a metered PM's inbox; each turn "
    "after the PM reads it costs ~$0.75, and its $1 key is exhausted on the 2nd day: every "
    "later wake ends `error/provider_error:LimitExceeded` and the pod stops trading. Fix "
    "(physics, one law): a per-sender daily character quota on `POST /messages` "
    "(`app/bus/messages.py`), or bill the bytes a message adds to readers to its sender's key."))
def test_hole_a_rival_drains_a_metered_minds_key_by_stuffing_its_inbox(
        SessionFactory, world, woke, gov, monkeypatch) -> None:
    def reads_inbox(request):
        if _turns(request) == 0:
            return CompletionResponse(content="inbox?", tool_calls=[ToolCall(
                id="inbox", name="get_messages", arguments={"latest": True, "limit": 50})])
        return CompletionResponse(content="done")
    _add_scripts(monkeypatch, **{"reads-inbox": reads_inbox})
    _cap(gov, 50)
    victim = _agent_id(SessionFactory, "pm-1")
    with TestClient(_app(SessionFactory)) as c:     # the rival: pod 2's PM, before the month
        for i in range(50):
            r = c.post("/messages", headers={"X-API-Key": world["pm"][2]},
                       json={"to": f"agent:{victim}", "body": f"{i:02d}" + "x" * 19_998})
            assert r.status_code == 201, r.status_code
    prov = FakeProvisioner()
    meter = Meter(prov, prov.create_key(victim, 1_000_000))   # a $1 key
    run = _conduct(SessionFactory, [(_pm_spec("a-pm", 1, "reads-inbox", budget=1.0),
                                     world["pm"][1], meter)], world["clock"], steps=3)
    ends = [(w.ended, w.reason) for st in run.steps for w in st.wakes]
    # Today: [('done', 'done'), ('error', 'provider_error:LimitExceeded'), (same)].
    assert ends == [("done", "done")] * 3, (ends, prov.usage())


# --- (e) the sync is not in a ``finally``: a mind that ends the process loses the dollars ---

# FIXED in M-001 (ADR-044): `_conduct` syncs in a `finally` around `run_backtest`.
def test_hole_a_systemexit_in_a_metered_wake_skips_the_sync(
        SessionFactory, keys, woke, gov, tmp_path, capsys, monkeypatch) -> None:
    def leaves(request):
        if _turns(request) == 0:
            return CompletionResponse(content="time?", tool_calls=[
                ToolCall(id="c", name="get_clock")])
        raise SystemExit(0)                 # after one charged turn
    _add_scripts(monkeypatch, leaves=leaves)
    specs = _write_specs(tmp_path / "s", _m_spec("a-pm", "desk-1-pm", 1, "leaves"))
    _cap(gov, 50)
    app = _app(SessionFactory)
    with TestClient(app):
        try:
            code = cli.main(["backtest", "--specs", str(specs), "--steps", "1"],
                            transport=httpx.ASGITransport(app=app))
        except SystemExit as exc:
            code = exc.code
    capsys.readouterr()
    # Today: code 0 and no cost_metered row, though the first turn was charged.
    assert code != 0 or _metered_rows(SessionFactory) != [], code
    assert _metered_rows(SessionFactory) != []


# --- (e) a sync that fails part-way reports nothing posted, though rows landed -------------

@pytest.mark.xfail(strict=True, reason=(
    "HOLE low (the outcome mislabels the ledger): `sync_costs` raises on a 5xx after earlier "
    "keys were posted; `_sync_metering` then writes `posted: 0` and `_unattributed` names "
    "*every* key's micro-dollars as not attributed, though the first key's row is in the "
    "ledger. Exit 1 is right; the record is wrong, and an operator reconciling by hand would "
    "double-post. Fix: `sync_costs` returns the partial `SyncReport` with an `error` field "
    "instead of raising, and `_unattributed` counts only the keys after the failure."))
def test_hole_a_sync_failing_part_way_reports_zero_posted(
        SessionFactory, keys, woke, gov, tmp_path, capsys) -> None:
    specs = _write_specs(tmp_path / "s", _m_spec("a-pm", "desk-1-pm", 1, "read-a"),
                         _m_spec("b-pm", "desk-2-pm", 2, "read-b"))
    _cap(gov, 50)
    app = _app(SessionFactory)
    code, out, err = _main(app, ["--specs", str(specs), "--steps", "1"], capsys,
                           transport=FailsNthMeteringPost(app, 2))
    landed = _metered_rows(SessionFactory)
    assert code == 1 and len(landed) == 1                       # fake-0001 is in the ledger
    first = out["metering"]["keys"][0]["spent_usd_micros"]
    assert out["metering"]["sync"]["posted"] == 1, out["metering"]["sync"]
    assert f"{out['metering']['total_usd_micros'] - first} metered micro-dollars" in err


# =========================================================================================
# HELD
# =========================================================================================

# --- (a) the gate -----------------------------------------------------------------------

class _Str(str):
    def __eq__(self, other):  # a name that claims to be every name
        return True

    __hash__ = str.__hash__


@pytest.mark.parametrize("provider, adapter, metered, law, verdict", [
    ("fake-metered", "native", True, Governance(True, 50.0), (False, "halted")),
    ("fake-metered", "native", True, Governance(False, None), (False, "cap_null")),
    ("scripted", "native", True, Governance(False, None), (True, "zero_cost")),
    ("fake-metered", "openclaw", True, CAP_50, (False, "no_metered_key")),
    ("fake-metered", "native", 1, CAP_50, (False, "no_metered_key")),
    ("fake-metered", "native", Meter(FakeProvisioner(), "fake-0001"), CAP_50,
     (False, "no_metered_key")),
    (_Str("fake-metered"), "native", True, CAP_50, (False, "no_metered_key")),
    ("fake-metered", _Str("native"), True, CAP_50, (False, "no_metered_key")),
    ("cassette", "openclaw", True, CAP_50, (False, "no_metered_key")),
    ("fake-metered", "native", True, Governance(False, 0.0), (True, "metered")),  # vet's job
])
def test_held_gate_order_and_exact_metered_flag(provider, adapter, metered, law, verdict) -> None:
    d = decide_wake_under(provider, adapter, law, metered=metered)
    assert (d.allowed, d.reason) == verdict


# --- (b) the provisioner and the floor ----------------------------------------------------

@pytest.mark.parametrize("limit", [-1, True, 1.0, 10**12 + 1, float("nan"), "5"])
def test_held_create_key_refuses_bad_limits(limit) -> None:
    with pytest.raises(ValueError):
        FakeProvisioner().create_key(1, limit)


@pytest.mark.parametrize("amount", [-1, True, 0.5, float("inf")])
def test_held_charge_refuses_bad_amounts_and_spends_nothing(amount) -> None:
    p = FakeProvisioner()
    k = p.create_key(1, 10)
    with pytest.raises(ValueError):
        p.charge(k, amount)
    assert (p.usage()[0].usd_micros_total, p.charges(k)) == (0, 0)


def test_held_a_charge_landing_exactly_on_the_limit_then_one_more() -> None:
    p = FakeProvisioner()
    k = p.create_key(1, 10)
    p.charge(k, 10)
    with pytest.raises(metering.LimitExceeded):
        p.charge(k, 1)
    p.charge(k, 0)
    assert p.usage()[0].usd_micros_total == 10


@pytest.mark.parametrize("usd, micros", [
    (0.1 + 0.2, 300_000), (1e-7, 0), (-0.0, 0), (19.9999999, 19_999_999), (1e300, 10**306),
])
def test_held_floor_is_decimal_exact(usd, micros) -> None:
    assert usd_to_micros_floor(usd) == micros


def test_held_floor_refuses_nan() -> None:
    with pytest.raises(ValueError):
        usd_to_micros_floor(float("nan"))


# --- (c) vet --------------------------------------------------------------------------------

def _ms(id: str, pod: int, budget: float, **more) -> AgentSpec:
    return AgentSpec(**(_m_spec(id, f"desk-{pod}-pm", pod, "signal-pm", budget) | more))


@pytest.mark.parametrize("budgets, cap, verdict", [
    ((0.1, 0.2), 0.3, None),                       # binary float would say 0.30000000000000004
    ((0.0000015, 0.0000015), 0.000002, None),      # each key's limit is its floor: 1 + 1 <= 2
    ((1e300,), 1e308, "budget_too_large:m0"),
    ((1e-7,), 50.0, "provider_refused:m0:no_budget"),
    ((-0.0,), 50.0, "provider_refused:m0:no_budget"),
    ((1.0,), 1e-7, "budget_over_cap"),
    ((500_000.0, 500_000.0, 1.0), 1_000_000.0, "budget_over_cap"),
])
def test_held_vet_budget_law_at_the_micro_dollar(budgets, cap, verdict) -> None:
    specs = [_ms(f"m{i}", i + 1, b) for i, b in enumerate(budgets)]
    assert vet(specs, Governance(False, cap)) == verdict


def test_held_vet_refuses_metered_through_openclaw_and_duplicate_ids() -> None:
    assert vet([_ms("m0", 1, 5.0, adapter="openclaw")], CAP_50) == \
        "wake_refused:m0:no_metered_key"
    assert vet([_ms("m0", 1, 5.0), _ms("m0", 2, 5.0)], CAP_50) == "duplicate_spec_id"


def test_held_a_metered_spec_cannot_be_nan_or_inf() -> None:
    from pydantic import ValidationError
    for bad in (float("nan"), float("inf"), -1.0):
        with pytest.raises(ValidationError):
            _ms("m0", 1, bad)


# --- (c) provision: a key failure after the agent exists ------------------------------------

def test_held_a_key_that_cannot_be_minted_names_the_agent_maybe_registered(
        SessionFactory, world, woke, gov) -> None:
    from runtime.provision import ProvisionError
    from tests.test_runtime_metered_run import _provision

    class Broken(FakeProvisioner):
        def create_key(self, agent_id, limit_usd_micros):
            if self._keys:
                raise RuntimeError("provisioner down")
            return super().create_key(agent_id, limit_usd_micros)
    _cap(gov, 50)
    with pytest.raises(ProvisionError) as exc:
        _provision(SessionFactory, [AgentSpec(**_m_spec("a-pm", "desk-1-pm", 1)),
                                    AgentSpec(**_m_spec("b-pm", "desk-2-pm", 2))],
                   world["admin"], provisioner=Broken())
    assert exc.value.reason == "key_failed:b-pm" and exc.value.registered == ("a-pm", "b-pm")


# --- (d) the conductor ----------------------------------------------------------------------

def test_held_two_minds_sharing_one_meter_are_refused(SessionFactory, world, woke, gov) -> None:
    _cap(gov, 50)
    prov = FakeProvisioner()
    shared = Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-1"), 1_000_000))
    run = _conduct(SessionFactory, [(_pm_spec("a-pm", 1), world["pm"][1], shared),
                                    (_pm_spec("b-pm", 2, "read-b"), world["pm"][2], shared)],
                   world["clock"], steps=1)
    assert (run.ended, run.reason) == ("refused", "meter_mismatch:b-pm") and woke == []


def test_held_a_fake_metered_mind_handed_in_without_a_meter_never_spends(
        SessionFactory, world, woke, gov) -> None:
    _cap(gov, 50)
    run = _conduct(SessionFactory, [(_pm_spec("a-pm", 1), world["pm"][1], None)],
                   world["clock"], steps=1)
    assert (run.ended, run.reason) == ("refused", "wake_refused:a-pm:no_metered_key")


def test_held_a_cap_made_null_mid_run_stops_the_next_wake(
        SessionFactory, world, woke, gov, monkeypatch) -> None:
    def nulls(request):
        _cap(gov, "null")
        return CompletionResponse(content="done")
    _add_scripts(monkeypatch, nulls=nulls)
    _cap(gov, 50)
    prov = FakeProvisioner()
    a = Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-1"), 20_000_000))
    b = Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-2"), 20_000_000))
    run = _conduct(SessionFactory, [(_pm_spec("a-pm", 1, "nulls"), world["pm"][1], a),
                                    (_pm_spec("b-pm", 2, "read-b"), world["pm"][2], b)],
                   world["clock"], steps=2)
    assert (run.ended, run.reason) == ("refused", "wake_refused:b-pm:cap_null")
    assert prov.usage()[1].usd_micros_total == 0


def test_held_a_cap_made_unreadable_mid_run_reads_null(
        SessionFactory, world, woke, gov, monkeypatch) -> None:
    def garbles(request):
        (gov / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: .inf\n")
        return CompletionResponse(content="done")
    _add_scripts(monkeypatch, garbles=garbles)
    _cap(gov, 50)
    prov = FakeProvisioner()
    a = Meter(prov, prov.create_key(_agent_id(SessionFactory, "pm-1"), 20_000_000))
    run = _conduct(SessionFactory, [(_pm_spec("a-pm", 1, "garbles"), world["pm"][1], a)],
                   world["clock"], steps=2)
    assert (run.ended, run.reason) == ("refused", "wake_refused:a-pm:cap_null")


# --- (d)/(e) a retired mind's key still reaches the ledger ---------------------------------

def test_held_a_fired_metered_minds_spend_is_still_synced(
        SessionFactory, keys, woke, gov, tmp_path, capsys, monkeypatch) -> None:
    def fires_b(request):
        results = scripted._results(request)
        if _turns(request) == 0:
            return CompletionResponse(content="who?", tool_calls=[
                ToolCall(id="dir", name="list_agents")])
        if _turns(request) == 1:
            target = next((a["id"] for a in results["dir"] or []
                           if a["name"] == "desk-2-pm" and a.get("status") == "active"), None)
            if target is not None:
                return CompletionResponse(content="fire", tool_calls=[
                    ToolCall(id="fire", name="deactivate_agent", arguments={"agent_id": target})])
        return CompletionResponse(content="done")
    _add_scripts(monkeypatch, **{"fires-b": fires_b})
    specs = _write_specs(tmp_path / "s", _m_spec("a-pm", "desk-1-pm", 1, "read-a"),
                         _m_spec("b-pm", "desk-2-pm", 2, "read-b"),
                         {"id": "m-boss", "name": "desk-boss", "role": "management",
                          "provider": "scripted", "script": "fires-b", "charter": "Fire b."})
    _cap(gov, 50)
    code, out, err = _main(_app(SessionFactory), ["--specs", str(specs), "--steps", "3"], capsys)
    assert code == 0 and out["run"]["retired"] == ["b-pm"], (out["run"]["retired"], err)
    b = next(k for k in out["metering"]["keys"] if k["spec_id"] == "b-pm")
    assert b["spent_usd_micros"] > 0
    assert {r["key_ref"]: r["usd_micros_total"] for r in _metered_rows(SessionFactory)}[
        b["key_ref"]] == b["spent_usd_micros"]


# --- (e) nothing reaches the law but the file ---------------------------------------------

def test_held_no_environment_variable_reaches_the_cap(gov, monkeypatch) -> None:
    from runtime.governance import read_governance
    for name in ("FUND_FIRM__MONTHLY_LLM_USD_CAP", "FUND_RUNTIME__CAP", "MONTHLY_LLM_USD_CAP",
                 "FUND_RUNTIME__HUMAN_YAML", "FUND_LAW__HUMAN_YAML"):
        monkeypatch.setenv(name, "1000")
    assert read_governance().monthly_llm_usd_cap is None


def test_held_a_metered_openclaw_spec_is_refused_before_physics_is_told(
        SessionFactory, keys, woke, gov, tmp_path, capsys) -> None:
    specs = _write_specs(tmp_path / "s", _m_spec("a-pm", "desk-1-pm", 1) | {"adapter": "openclaw"})
    _cap(gov, 50)
    code, out, _ = _main(_app(SessionFactory), ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 1 and out["reason"] == "provision:wake_refused:a-pm:no_metered_key"
    assert "metering" not in out
    with SessionFactory() as s:
        assert list(s.execute(select(Event).where(
            Event.type == EVENT_RUN_MINDS_DECLARED)).scalars()) == []


# --- (f) the physics read ---------------------------------------------------------------------

def test_held_metering_agents_refuses_every_firm_role_but_management(
        SessionFactory, world) -> None:
    from app.ledger.events import EVENT_PERMISSION_DENIED
    with TestClient(_app(SessionFactory)) as c:
        assert c.get("/metering/agents", headers={"X-API-Key": world["admin"]}).status_code == 200
        for key in (world["pm"][1], world["clock"]):
            assert c.get("/metering/agents", headers={"X-API-Key": key}).status_code == 403
    with SessionFactory() as s:
        denied = list(s.execute(select(Event).where(
            Event.type == EVENT_PERMISSION_DENIED)).scalars())
    assert len(denied) == 2


def test_held_a_metered_agents_self_report_spam_moves_neither_its_meter_nor_the_total(
        SessionFactory, world) -> None:
    with TestClient(_app(SessionFactory)) as c:
        pm1 = _agent_id(SessionFactory, "pm-1")
        r = c.post("/metering/usage", headers={"X-API-Key": world["clock"]},
                   json={"agent_id": pm1, "key_ref": "fake-0001", "usd_micros_total": 5})
        assert r.status_code == 200, r.status_code
        for _ in range(20):                    # the agent claims $1M a time
            c.post("/costs", headers={"X-API-Key": world["pm"][1]},
                   json={"tokens_in": 0, "tokens_out": 0, "usd_cost": 1_000_000.0,
                         "task_label": "x"})
        body = c.get("/metering/agents", headers={"X-API-Key": world["admin"]}).json()
    [row] = body["agents"]
    assert (row["metered_usd_micros"], body["total_usd_micros"]) == (5, 5)
    assert "key_ref" not in json.dumps(body)


# --- (g) the self-reporting wrapper ---------------------------------------------------------

def test_held_self_reporting_passes_every_inner_call_through_untouched() -> None:
    from runtime.providers import CompletionRequest, Message
    calls = [ToolCall(id=f"c{i}", name="get_clock") for i in range(3)]

    def inner(request):
        n = _turns(request)
        return (CompletionResponse(content=f"turn {n}", tool_calls=[calls[n]]) if n < 3
                else CompletionResponse(content="inner done"))
    wrapped = scripted.self_reporting(inner, 0.01)
    msgs = [Message(role="system", content="x"), Message(role="user", content="{}")]
    seen = []
    for _ in range(6):
        req = CompletionRequest(messages=msgs, tools=[])
        reply = wrapped(req)
        if reply.tool_calls and reply.tool_calls[0].id != "self-report":
            assert reply == inner(req)
        seen.append([c.id for c in reply.tool_calls])
        if not reply.tool_calls:
            break
        msgs = [*msgs, Message(role="assistant", content=reply.content,
                               tool_calls=reply.tool_calls),
                *[Message(role="tool", content="{}", tool_call_id=c.id) for c in reply.tool_calls]]
    assert seen == [["c0"], ["c1"], ["c2"], ["self-report"], []]


# --- (h) what physics is told -------------------------------------------------------------

def test_held_mind_kinds_never_call_a_spending_adapter_scripted() -> None:
    base = _m_spec("a-pm", "desk-1-pm", 1)
    assert mind_kinds([AgentSpec(**base)]) == ["scripted"]
    assert mind_kinds([AgentSpec(**(base | {"adapter": "openclaw"}))]) == ["model"]
    assert mind_kinds([AgentSpec(**(base | {"provider": "Fake-Metered"}))]) == ["model"]
