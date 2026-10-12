"""R-2: a scripted mind wakes through the native adapter (ADR-032 (2)(3), amendment (b)).

Three things are pinned here:

* **the registry** — each zero-cost name builds exactly one class, the adapter
  never accepts a provider object, and a spec whose fields contradict its
  provider builds no mind;
* **the scripted provider** — a pure function of the transcript, chosen by name
  from a closed table, in a module that imports nothing that could reach a model
  or the network;
* **the native adapter** — the mind sees exactly ``build_server``'s tools
  (narrowed by ``spec.tools``), gets a context assembled by code, acts only
  through those tools over HTTP, and is stopped by HALT before any batch and by
  its tool-call budget.

Then the probe's moving-average PM, as a script, trades a backtest month through
the Runtime, twice, and leaves the same ledger both times.
"""

from __future__ import annotations

import ast
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.db.base import get_session
from app.db.models import AgentRole, Event, Order
from app.ledger.events import EVENT_ORDER_FILLED
from app.main import create_app
from app.marketdata import SyntheticProvider, set_provider
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import start_backtest
from mcp_server import FundClient, build_server
from runtime import governance, native, registry, scripted
from runtime.gate import ZERO_COST_PROVIDERS
from runtime.native import wake
from runtime.providers import CompletionResponse, ToolCall
from runtime.registry import PROVIDER_CLASSES, ProviderRefused, build_provider
from runtime.spec import AgentSpec
from tests.support import world_key
from tests.test_phase3_probe import CAPITAL, START, SYMBOLS, _fresh_database

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def gov(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The Runtime reads a governance directory the test owns: cap null, no HALT."""
    d = tmp_path / "governance"
    d.mkdir()
    monkeypatch.setattr(governance, "HALT_FILE", d / "HALT")
    monkeypatch.setattr(governance, "HUMAN_YAML", d / "human.yaml")
    (d / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: null\n")
    return d


def _spec(**fields) -> AgentSpec:
    base = dict(id="pm-a", name="pm-a", role="pm", pod=1, provider="scripted",
                script="moving-average-pm", charter="Run the desk.")
    return AgentSpec(**(base | fields))


@pytest.fixture
def scripts(monkeypatch: pytest.MonkeyPatch):
    """Install test scripts beside the real ones (the table stays read-only)."""
    def _install(**more) -> None:
        monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | more))
    return _install


@pytest.fixture
def fund_client(SessionFactory, client):
    """A FundClient for a key, speaking to the test app over ASGI (as in test_mcp_server)."""
    app = create_app()
    app.dependency_overrides[get_session] = client.app.dependency_overrides[get_session]

    def _make(api_key: str) -> FundClient:
        return FundClient(base_url="http://fund.test", api_key=api_key,
                          transport=httpx.ASGITransport(app=app))
    return _make


def _orders(SessionFactory) -> list[Order]:
    with SessionFactory() as s:
        return list(s.execute(select(Order)).scalars())


# --- the registry ----------------------------------------------------------------------


def test_scripted_builds_exactly_the_scripted_class() -> None:
    provider = build_provider(_spec())
    assert type(provider) is PROVIDER_CLASSES["scripted"] is scripted.ScriptedProvider


def test_every_registered_name_is_on_the_gates_list_and_says_so() -> None:
    """Today every buildable mind is zero-cost; a spending class is an ADR (R-6)."""
    assert set(PROVIDER_CLASSES) <= ZERO_COST_PROVIDERS
    for name, cls in PROVIDER_CLASSES.items():
        assert cls.name == name and cls.spends_money is False


def test_the_tables_are_read_only() -> None:
    with pytest.raises(TypeError):
        PROVIDER_CLASSES["metered"] = object  # type: ignore[index]
    with pytest.raises(TypeError):
        scripted.SCRIPTS["mine"] = lambda r: CompletionResponse()  # type: ignore[index]


@pytest.mark.parametrize("fields, reason", [
    ({"model": "anthropic/claude-opus"}, "contradiction"),     # a $0 label on a model
    ({"budget_usd": 5.0}, "contradiction"),
    ({"provider": "cassette", "script": "moving-average-pm"}, "contradiction"),
    ({"provider": "metered", "script": "moving-average-pm"}, "contradiction"),
    ({"script": None}, "unknown_script"),
    ({"script": "free-money"}, "unknown_script"),
    ({"provider": "cassette", "script": None}, "unavailable"),  # R-4
    ({"provider": "metered", "script": None}, "unknown_provider"),
    ({"provider": "Scripted", "script": None}, "unknown_provider"),
])
def test_a_contradicting_or_unknown_spec_builds_no_mind(fields: dict, reason: str) -> None:
    with pytest.raises(ProviderRefused) as exc:
        build_provider(_spec(**fields))
    assert exc.value.reason == reason


def test_the_adapter_takes_no_provider_object() -> None:
    """The mind is built from the spec inside the wake: no caller can hand one in."""
    import inspect
    params = inspect.signature(wake).parameters
    assert set(params) == {"spec", "client", "workflow_input", "max_tool_calls"}


# --- the scripted provider -------------------------------------------------------------

#: What a zero-cost provider's module may import: nothing that can open a socket or
#: load a model. ``runtime.providers`` is the shapes; the rest is pure stdlib.
_SCRIPTED_MAY_IMPORT = frozenset({
    "__future__", "json", "math", "collections.abc", "types", "typing", "runtime.providers",
})


def _imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "__import__":
            names.add("<__import__>")
    return names


def test_the_scripted_module_imports_nothing_that_reaches_out() -> None:
    found = _imports((REPO / "runtime" / "scripted.py").read_text())
    assert "runtime.providers" in found  # the check really read the file
    assert found <= _SCRIPTED_MAY_IMPORT, found - _SCRIPTED_MAY_IMPORT


@pytest.mark.parametrize("planted", [
    "import httpx\n", "from anthropic import Anthropic\n", "import socket\n",
    "from runtime import native\n", "x = __import__('urllib.request')\n",
])
def test_the_import_check_catches_a_planted_reach(planted: str) -> None:
    assert not _imports("import json\n" + planted) <= _SCRIPTED_MAY_IMPORT


def test_a_script_is_a_pure_function_of_the_transcript() -> None:
    """Same request twice → same reply; the provider keeps no state between calls."""
    from runtime.providers import CompletionRequest, Message
    ctx = {"me": {"pod_id": 1}, "input": {"universe": ["SYNA"]}}
    req = CompletionRequest(messages=[Message(role="system", content="c"),
                                      Message(role="user", content=json.dumps(ctx))])
    p = build_provider(_spec())
    assert p.complete(req) == p.complete(req) == build_provider(_spec()).complete(req)


# --- the native adapter ----------------------------------------------------------------


@pytest.mark.anyio
async def test_the_mind_sees_exactly_the_published_tools(fund_client) -> None:
    client = fund_client("unused")
    published = [t.name for t in await build_server(client).list_tools()]
    assert [t.name for t in await native.published_tools(client)] == published
    assert {"place_order", "get_price", "whoami"} <= set(published)


@pytest.mark.anyio
async def test_context_is_charter_then_me_and_input(fund_client, desk, scripts) -> None:
    pod_id, pm_id, pm_key = desk
    seen = []

    def look(request):
        seen.append(request)
        return CompletionResponse(content="nothing to do")
    scripts(look=look)
    rec = await wake(_spec(script="look", charter="You run pod 1."), fund_client(pm_key),
                     workflow_input={"day": 3})
    assert (rec.ended, rec.tool_calls) == ("done", 0)
    system, user = rec.transcript[:2]
    assert (system.role, system.content) == ("system", "You run pod 1.")
    ctx = json.loads(user.content)
    assert ctx["input"] == {"day": 3}
    assert (ctx["me"]["id"], ctx["me"]["pod_id"], ctx["me"]["role"]) == (pm_id, pod_id, "pm")
    assert {t.name for t in seen[0].tools} == {t.name for t in await native.published_tools(
        fund_client(pm_key))}
    assert seen[0].model is None


def _calls(*names: str, turns: int = 1):
    """A script that asks for ``names`` on each of its first ``turns`` turns."""
    def run(request):
        turn = sum(m.role == "assistant" for m in request.messages)
        if turn >= turns:
            return CompletionResponse(content="done")
        return CompletionResponse(tool_calls=[
            ToolCall(id=f"{turn}:{i}", name=n,
                     arguments=_BUY if n == "place_order" else {})
            for i, n in enumerate(names)])
    return run


_BUY = {"ticker": "AAPL", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "test"}


@pytest.mark.anyio
async def test_a_scripted_pm_trades_through_the_tools(fund_client, desk, scripts,
                                                      SessionFactory) -> None:
    pod_id, pm_id, pm_key = desk
    scripts(buy=_calls("place_order"))
    rec = await wake(_spec(script="buy"), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.tool_calls) == ("done", 1)
    result = rec.transcript[3]
    assert result.role == "tool" and not result.is_error, result.content
    assert json.loads(result.content)["status"] == "filled"
    [order] = _orders(SessionFactory)
    assert (order.pod_id, order.created_by) == (pod_id, pm_id)


@pytest.mark.anyio
async def test_physics_refusals_reach_the_mind_as_tool_errors(
    fund_client, desk, agent_factory, scripts, SessionFactory,
) -> None:
    _, analyst_key = agent_factory("analyst-1", "analyst", 1)
    scripts(buy=_calls("place_order"))
    rec = await wake(_spec(id="an-a", role="analyst", script="buy"), fund_client(analyst_key),
                     workflow_input={})
    assert rec.ended == "done"
    assert rec.transcript[3].is_error and "403" in rec.transcript[3].content
    assert _orders(SessionFactory) == []


@pytest.mark.anyio
async def test_a_tool_outside_the_list_reaches_no_endpoint(fund_client, desk, scripts,
                                                           SessionFactory) -> None:
    _, _, pm_key = desk
    scripts(buy=_calls("get_clock", "place_order"))
    rec = await wake(_spec(script="buy", tools=("get_clock",)), fund_client(pm_key),
                     workflow_input={})
    assert rec.ended == "done"
    clock, order = rec.transcript[3:5]
    assert not clock.is_error
    assert order.is_error and "not in your tool list" in order.content
    assert _orders(SessionFactory) == []


@pytest.mark.anyio
async def test_the_narrowed_list_is_what_the_mind_is_shown(fund_client, desk, scripts) -> None:
    _, _, pm_key = desk
    seen = []
    scripts(look=lambda r: seen.append(r) or CompletionResponse())
    await wake(_spec(script="look", tools=("get_price", "get_clock")), fund_client(pm_key),
               workflow_input={})
    assert sorted(t.name for t in seen[0].tools) == ["get_clock", "get_price"]


@pytest.mark.anyio
async def test_an_unknown_tool_in_the_spec_refuses_the_wake(fund_client, desk) -> None:
    _, _, pm_key = desk
    rec = await wake(_spec(tools=("get_price", "teleport")), fund_client(pm_key),
                     workflow_input={})
    assert (rec.ended, rec.reason, rec.transcript) == ("refused", "unknown_tool", ())


@pytest.mark.anyio
async def test_halt_refuses_the_wake_before_any_call(fund_client, desk, gov, scripts) -> None:
    _, _, pm_key = desk
    (gov / "HALT").write_text("")
    scripts(boom=lambda r: pytest.fail("a halted mind was asked to think"))
    rec = await wake(_spec(script="boom"), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.reason, rec.transcript) == ("refused", "halted", ())


@pytest.mark.anyio
async def test_halt_between_batches_stops_the_next_batch(fund_client, desk, gov, scripts,
                                                         SessionFactory) -> None:
    """03 §3: HALT is re-checked before every tool-call batch, not only at wake."""
    _, _, pm_key = desk

    def halt_after_first(request):
        turn = sum(m.role == "assistant" for m in request.messages)
        if turn == 0:
            return CompletionResponse(tool_calls=[ToolCall(id="c", name="get_clock")])
        (gov / "HALT").write_text("")  # the Human halts while the mind is thinking
        return CompletionResponse(tool_calls=[ToolCall(id="o", name="place_order",
                                                       arguments=_BUY)])
    scripts(halter=halt_after_first)
    rec = await wake(_spec(script="halter"), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.tool_calls) == ("halted", 1)
    assert [m.tool_call_id for m in rec.transcript if m.role == "tool"] == ["c"]
    assert _orders(SessionFactory) == []


@pytest.mark.anyio
async def test_the_tool_budget_ends_the_wake_and_no_batch_runs_past_it(
    fund_client, desk, scripts,
) -> None:
    _, _, pm_key = desk
    scripts(chatty=_calls("get_clock", "get_clock", turns=1000))
    rec = await wake(_spec(script="chatty"), fund_client(pm_key), workflow_input={},
                     max_tool_calls=5)
    assert (rec.ended, rec.tool_calls) == ("tool_budget", 4)  # 2 + 2; the third pair would be 6
    assert sum(m.role == "tool" for m in rec.transcript) == 4


@pytest.mark.anyio
async def test_a_zero_budget_runs_no_call(fund_client, desk, scripts) -> None:
    _, _, pm_key = desk
    scripts(one=_calls("get_clock"))
    rec = await wake(_spec(script="one"), fund_client(pm_key), workflow_input={},
                     max_tool_calls=0)
    assert (rec.ended, rec.tool_calls) == ("tool_budget", 0)


@pytest.mark.parametrize("bad", [-1, 1.5, True, "3"])
def test_the_budget_must_be_a_plain_non_negative_int(bad) -> None:
    with pytest.raises(ValueError):
        asyncio.run(wake(_spec(), FundClient(base_url="http://x", api_key="k"),
                         workflow_input={}, max_tool_calls=bad))


@pytest.mark.anyio
@pytest.mark.parametrize("fields, reason", [
    ({"adapter": "openclaw"}, "wrong_adapter"),
    ({"provider": "metered", "script": None}, "cap_null"),
    ({"model": "anthropic/claude-opus"}, "contradiction"),
    ({"provider": "cassette", "script": None}, "unavailable"),
])
async def test_refused_wakes_make_no_call(fund_client, desk, fields, reason) -> None:
    _, _, pm_key = desk
    rec = await wake(_spec(**fields), fund_client(pm_key), workflow_input={})
    assert (rec.ended, rec.reason, rec.tool_calls, rec.transcript) == ("refused", reason, 0, ())


@pytest.mark.anyio
async def test_a_bad_key_refuses_the_wake(fund_client, desk) -> None:
    rec = await wake(_spec(), fund_client("not-a-key"), workflow_input={})
    assert (rec.ended, rec.reason) == ("refused", "no_identity")


@pytest.mark.anyio
async def test_malformed_arguments_are_a_tool_error_not_a_crash(fund_client, desk, scripts,
                                                                SessionFactory) -> None:
    _, _, pm_key = desk
    scripts(bad=lambda r: CompletionResponse() if any(m.role == "assistant" for m in r.messages)
            else CompletionResponse(tool_calls=[ToolCall(id="x", name="place_order",
                                                         arguments={"ticker": 5})]))
    rec = await wake(_spec(script="bad"), fund_client(pm_key), workflow_input={})
    assert rec.ended == "done" and rec.transcript[3].is_error
    assert _orders(SessionFactory) == []


# --- the probe pod as a mind: a backtest month through the Runtime ---------------------

DAYS = 31


def _month_through_the_runtime(world: int) -> tuple[list[tuple], list]:
    _, Sessions = _fresh_database()
    set_provider(SyntheticProvider(world_key(world), SYMBOLS))
    with Sessions() as s:
        start_backtest(s, start=START)
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        pod = create_pod(s, name="runtime-desk")
        fund_pod(s, pod_id=pod.id, delta=CAPITAL, actor=get_or_create_system_agent(s),
                 reason="probe capital")
        _, pm_key = register_agent(s, name="pm-runtime", role=AgentRole.pm, pod_id=pod.id)
        s.commit()
        pod_id = pod.id

    app = create_app()

    def _session():
        s = Sessions()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_session] = _session
    spec = _spec(pod=pod_id)
    records = []

    async def month() -> None:
        transport = httpx.ASGITransport(app=app)
        async with FundClient(base_url="http://fund.test", api_key=pm_key,
                              transport=transport) as pm, \
                FundClient(base_url="http://fund.test", api_key=admin,
                           transport=transport) as boss:
            for _ in range(DAYS):
                records.append(await wake(spec, pm, workflow_input={"universe": list(SYMBOLS)}))
                await boss.post("/clock/advance", {"days": 1})  # R-3 moves this into the Runtime

    with TestClient(app):  # the lifespan puts the server on the run's clock
        asyncio.run(month())
    with Sessions() as s:
        ledger = [(e.id, e.ts.isoformat(), e.actor_agent_id, e.type, e.payload_json)
                  for e in s.execute(select(Event).order_by(Event.id)).scalars()]
    return ledger, records


@pytest.fixture(scope="module")
def months(tmp_path_factory):
    from app.config import get_settings
    from app.registry import halt
    with pytest.MonkeyPatch.context() as mp:
        d = tmp_path_factory.mktemp("gov")
        (d / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: null\n")
        mp.setattr(governance, "HALT_FILE", d / "HALT")
        mp.setattr(governance, "HUMAN_YAML", d / "human.yaml")
        mp.setattr(halt, "HALT_FILE", d / "PHYSICS_HALT")
        mp.setattr(get_settings().oms, "pending_monitor_enabled", False)
        try:
            yield {"a": _month_through_the_runtime(11), "b": _month_through_the_runtime(11)}
        finally:
            set_provider(None)
            set_clock(LiveClock())


def test_the_scripted_pm_lives_a_month_through_the_tools(months) -> None:
    ledger, records = months["a"]
    assert len(records) == DAYS and all(r.ended == "done" for r in records), \
        [(r.ended, r.reason) for r in records]
    fills = [e for e in ledger if e[3] == EVENT_ORDER_FILLED]
    assert len(fills) >= 3 and {e[4]["side"] for e in fills} == {"buy", "sell"}
    placed = sum(1 for r in records for m in r.transcript
                 if m.role == "assistant" for c in m.tool_calls if c.name == "place_order")
    assert placed == len(fills)
    stamps = sorted({e[1] for e in fills})
    assert stamps[0] >= START.isoformat() and stamps[-1] < (START + timedelta(days=DAYS)).isoformat()


def test_the_same_world_twice_through_the_runtime_leaves_the_same_ledger(months) -> None:
    a, b = months["a"][0], months["b"][0]
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x == y, f"first divergence at event {x[0]}:\n{x}\n{y}"
    assert [r.transcript for r in months["a"][1]] == [r.transcript for r in months["b"][1]]
