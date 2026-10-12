"""R-3b-2a: a pod of two minds lives a month through the conductor (M1, serves EC1).

The Analyst (``ma-signal-analyst``) posts a dated signal to its pod; the PM
(``signal-pm``) trades only on the newest signal from an analyst of its own pod
stamped with today's now. Claims under test:

* **the scripts** — the PM holds without a signal, and ignores a stale signal, one
  from a non-analyst, one from another pod's analyst, one sent to another
  audience and a malformed one; the newest of today's signals wins; the Analyst
  sends nothing after a failed read;
* **the month** — analyst ``a-…`` and PM ``b-…`` in pod 1, and a PM ``c-…`` with no
  analyst in pod 2, live 31 synthetic days through ``run_backtest``: pod 1 trades
  both ways, every order cites a signal its analyst sent that same simulated day,
  pod 2 never trades; the same world twice leaves the same ledger and the same
  transcripts; the month runs inside TRD Phase 3's 10-minute budget.

Scripted minds are code, not firm agents (Q-0005 B): this run never ticks EC1 (R-8).
"""

from __future__ import annotations

import asyncio
import json
import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.db.base import get_session
from app.db.models import Agent, AgentRole, Event, Message as Msg, Order
from app.ledger.events import EVENT_ORDER_FILLED
from app.main import create_app
from app.marketdata import SyntheticProvider, set_provider
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent, seed_runtime_agent
from app.run_clock import start_backtest
from mcp_server import FundClient
from runtime import governance
from runtime.lockstep import run_backtest
from runtime.providers import CompletionRequest, Message, ToolCall
from runtime.provision import provision
from runtime.scripted import ma_signal_analyst, signal_pm
from runtime.spec import AgentSpec
from tests.support import world_key
from tests.test_phase3_probe import BUDGET_SECONDS, CAPITAL, START, SYMBOLS, _fresh_database

DAYS = 31
NOW = "2024-01-10T14:30:00Z"
UNIVERSE = ["SYNA", "SYNB"]


# --- the scripts, shown crafted transcripts -------------------------------------------

def _request(me: dict, turns: list[tuple[list[ToolCall], dict[str, object]]]) -> CompletionRequest:
    """A transcript: the context, then for each turn its calls and their results
    (``None`` = the call failed)."""
    messages = [Message(role="system", content="charter"),
                Message(role="user", content=json.dumps(
                    {"me": me, "input": {"universe": UNIVERSE}}, sort_keys=True))]
    for calls, results in turns:
        messages.append(Message(role="assistant", content="", tool_calls=calls))
        for c in calls:
            value = results[c.id]
            messages.append(Message(role="tool", tool_call_id=c.id, is_error=value is None,
                                    content="failed" if value is None else json.dumps(value)))
    return CompletionRequest(messages=messages, tools=[])


PM = {"id": 3, "role": "pm", "pod_id": 1}
DIRECTORY = [{"id": 2, "role": "analyst", "pod_id": 1, "name": "an-1", "status": "active"},
             {"id": 3, "role": "pm", "pod_id": 1, "name": "pm-1", "status": "active"},
             {"id": 4, "role": "pm", "pod_id": 1, "name": "pm-1b", "status": "active"},
             {"id": 5, "role": "analyst", "pod_id": 2, "name": "an-2", "status": "active"},
             {"id": 6, "role": "analyst", "pod_id": 1, "name": "an-1-old", "status": "inactive"}]
BOOK = {"positions": [{"ticker": "SYNB", "qty": 10}], "cash": 10_000.0, "total_value": 10_500.0}


def _msg(id: int, *, sender: int = 2, to: str = "pod:1", as_of: str = NOW, ts: str = NOW,
         signals: object = None, kind: str = "signal") -> dict:
    return {"id": id, "from_agent": sender, "to": to, "body": "x", "thread_id": None,
            "ts": ts, "structured_payload": {
                "kind": kind, "as_of": as_of,
                "signals": {"SYNA": "long", "SYNB": "flat"} if signals is None else signals}}


def _pm_turn_1(inbox: list[dict]):
    first = signal_pm(_request(PM, []))
    results = {"clock": {"now": NOW, "mode": "backtest"}, "book": BOOK, "directory": DIRECTORY,
               "inbox": inbox, "price:SYNA": {"price": 100.0}, "price:SYNB": {"price": 50.0}}
    assert {c.id for c in first.tool_calls} == set(results)
    return signal_pm(_request(PM, [(first.tool_calls, results)]))


def test_the_pm_trades_on_todays_signal_from_its_analyst_and_cites_it() -> None:
    reply = _pm_turn_1([_msg(7)])
    orders = {c.arguments["ticker"]: c.arguments for c in reply.tool_calls}
    assert orders["SYNA"]["side"] == "buy" and orders["SYNB"]["side"] == "sell"
    assert orders["SYNB"]["qty"] == 10
    assert all("analyst signal #7" in o["justification"] for o in orders.values())


@pytest.mark.parametrize("inbox", [
    [],
    [_msg(7, as_of="2024-01-09T14:30:00Z")],          # yesterday's
    [_msg(7, ts="2024-01-09T14:30:00Z")],             # sent yesterday, pre-dated to today
    [_msg(7, sender=6)],                               # an analyst no longer active
    [_msg(7, sender=4)],                               # a PM of the pod, not an analyst
    [_msg(7, sender=5, to="pod:2")],                   # another pod's analyst
    [_msg(7, sender=5)],                               # another pod's analyst, to pod 1
    [_msg(7, to="agent:4")],                           # its analyst, to someone else
    [_msg(7, to="broadcast")],
    [_msg(7, kind="note")],
    [_msg(7, signals={"SYNA": "all-in"})],
    [_msg(7, signals=["SYNA"])],
    [{**_msg(7), "structured_payload": None}],
], ids=["none", "stale", "pre-dated", "inactive-analyst", "not-analyst", "other-pod", "other-pod-to-us", "elsewhere",
        "broadcast", "not-signal", "bad-side", "bad-shape", "no-payload"])
def test_the_pm_holds_without_a_valid_signal_for_today(inbox) -> None:
    reply = _pm_turn_1(inbox)
    assert reply.tool_calls == [] and "holding" in reply.content


def test_the_newest_of_todays_signals_wins() -> None:
    reply = _pm_turn_1([_msg(7), _msg(9, signals={"SYNA": "flat", "SYNB": "flat"}), _msg(8)])
    assert [(c.arguments["ticker"], c.arguments["side"]) for c in reply.tool_calls] == [
        ("SYNB", "sell")]
    assert "#9" in reply.tool_calls[0].arguments["justification"]


def test_the_pm_trades_only_names_in_its_universe() -> None:
    reply = _pm_turn_1([_msg(7, signals={"SYNC": "long"})])
    assert reply.tool_calls == []


def test_the_analyst_signals_its_pod_with_todays_now() -> None:
    me = {"id": 2, "role": "analyst", "pod_id": 1}
    first = ma_signal_analyst(_request(me, []))
    rising = {"bars": [{"close": 100.0 + i} for i in range(25)]}
    falling = {"bars": [{"close": 100.0 - i} for i in range(25)]}
    results = {"clock": {"now": NOW}, "bars:SYNA": rising, "bars:SYNB": falling}
    assert {c.id for c in first.tool_calls} == set(results)
    (send,) = ma_signal_analyst(_request(me, [(first.tool_calls, results)])).tool_calls
    assert send.name == "send_message" and send.arguments["to"] == "pod:1"
    assert send.arguments["structured_payload"] == {
        "kind": "signal", "as_of": NOW, "signals": {"SYNA": "long", "SYNB": "flat"}}


def test_the_analyst_sends_nothing_after_a_failed_read() -> None:
    me = {"id": 2, "role": "analyst", "pod_id": 1}
    first = ma_signal_analyst(_request(me, []))
    results = {"clock": {"now": NOW}, "bars:SYNA": None, "bars:SYNB": {"bars": []}}
    reply = ma_signal_analyst(_request(me, [(first.tool_calls, results)]))
    assert reply.tool_calls == [] and "no signal" in reply.content


# --- the month ------------------------------------------------------------------------

def _spec(id: str, name: str, role: str, pod: int, script: str) -> AgentSpec:
    return AgentSpec(id=id, name=name, role=role, pod=pod, provider="scripted", script=script,
                     charter="Work the desk.")


def _pod_month(world: int) -> dict:
    _, Sessions = _fresh_database()
    set_provider(SyntheticProvider(world_key(world), SYMBOLS))
    keys = {}
    with Sessions() as s:
        start_backtest(s, start=START)
        _, clock_key = seed_runtime_agent(s)
        system = get_or_create_system_agent(s)
        pods = []
        for n in (1, 2):
            pod = create_pod(s, name=f"desk-{n}")
            fund_pod(s, pod_id=pod.id, delta=CAPITAL, actor=system, reason="pod capital")
            pods.append(pod.id)
        # The operator's seed admin is the registrar; the minds are made from their
        # specs over HTTP (R-3b-2b-1, ADR-032 (n)).
        _, keys["registrar"] = register_agent(s, name="management", role=AgentRole.management)
        s.commit()
    specs = [_spec("a-analyst-1", "an-1", "analyst", pods[0], "ma-signal-analyst"),
             _spec("b-pm-1", "pm-1", "pm", pods[0], "signal-pm"),
             _spec("c-pm-2", "pm-2", "pm", pods[1], "signal-pm")]

    app = create_app()

    def _session():
        s = Sessions()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_session] = _session
    runs = []

    async def month() -> None:
        transport = httpx.ASGITransport(app=app)

        def connect(key: str) -> FundClient:
            return FundClient(base_url="http://fund.test", api_key=key, transport=transport)

        clients = {k: connect(v) for k, v in [*keys.items(), ("clock", clock_key)]}
        minds = []
        try:
            minds = await provision(specs, clients["registrar"], connect)
            runs.append(await run_backtest(minds, clients["clock"], steps=DAYS,
                                           workflow_input={"universe": UNIVERSE}))
        finally:
            for c in [*clients.values(), *(m.client for m in minds)]:
                await c.aclose()

    began = time.monotonic()
    with TestClient(app):
        asyncio.run(month())
    seconds = time.monotonic() - began
    (run,) = runs
    with Sessions() as s:
        ledger = [(e.id, e.ts.isoformat(), e.actor_agent_id, e.type, e.payload_json)
                  for e in s.execute(select(Event).order_by(Event.id)).scalars()]
        orders = [(o.pod_id, o.created_by, o.justification, o.created_at.isoformat())
                  for o in s.execute(select(Order).order_by(Order.id)).scalars()]
        messages = {m.id: (m.from_agent, m.to_ref, m.ts.isoformat())
                    for m in s.execute(select(Msg)).scalars()}
        analyst_id = next(e[4]["agent_id"] for e in ledger
                          if e[3] == "agent_registered" and e[4].get("name") == "an-1")
        charters = {a.name: a.charter_ref for a in s.execute(select(Agent)).scalars()}
    return {"run": run, "ledger": ledger, "orders": orders, "messages": messages,
            "pods": pods, "analyst": analyst_id, "seconds": seconds, "charters": charters}


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
            yield {"a": _pod_month(11), "b": _pod_month(11)}
        finally:
            set_provider(None)
            set_clock(LiveClock())


def test_the_pod_lives_a_month_through_the_conductor(months) -> None:
    m = months["a"]
    run = m["run"]
    assert (run.ended, run.minds, len(run.steps), run.retired) == (
        "completed", "scripted", DAYS, ()), run.reason
    wakes = [w for st in run.steps for w in st.wakes]
    assert len(wakes) == 3 * DAYS
    assert all((w.ended, w.tool_failures) == ("done", 0) for w in wakes), \
        [(w.spec_id, w.ended, w.reason) for w in wakes if w.ended != "done" or w.tool_failures]
    assert [[w.spec_id for w in st.wakes] for st in run.steps] == [
        ["a-analyst-1", "b-pm-1", "c-pm-2"]] * DAYS
    # The analyst spoke every day, to its pod.
    sent = [v for v in m["messages"].values() if v[0] == m["analyst"]]
    assert len(sent) == DAYS and {v[1] for v in sent} == {f"pod:{m['pods'][0]}"}
    assert m["seconds"] < BUDGET_SECONDS


def test_the_minds_were_made_from_their_specs_by_the_registrar(months) -> None:
    m = months["a"]
    registered = {e[4]["name"]: (e[2], e[4]["role"], e[4]["pod_id"])
                  for e in m["ledger"] if e[3] == "agent_registered"}
    (registrar,) = [e[4]["agent_id"] for e in m["ledger"]
                    if e[3] == "agent_registered" and e[4]["name"] == "management"]
    pod_1, pod_2 = m["pods"]
    assert {k: v for k, v in registered.items() if k not in {"management", "runtime"}} == {
        "an-1": (registrar, "analyst", pod_1), "pm-1": (registrar, "pm", pod_1),
        "pm-2": (registrar, "pm", pod_2)}
    assert {k: m["charters"][k] for k in ("an-1", "pm-1", "pm-2")} == {
        "an-1": "spec:a-analyst-1", "pm-1": "spec:b-pm-1", "pm-2": "spec:c-pm-2"}


def test_every_order_rests_on_its_analysts_signal_of_that_day(months) -> None:
    m = months["a"]
    pod_1, pod_2 = m["pods"]
    fills = [e for e in m["ledger"] if e[3] == EVENT_ORDER_FILLED]
    assert len(fills) >= 3 and {e[4]["side"] for e in fills} == {"buy", "sell"}
    assert {e[4]["pod_id"] for e in fills} == {pod_1}
    assert m["orders"] and all(o[0] == pod_1 for o in m["orders"])  # pod 2 never traded
    for _, _, justification, at in m["orders"]:
        (cited,) = re.findall(r"analyst signal #(\d+)", justification)
        sender, to, sent_at = m["messages"][int(cited)]
        assert (sender, to, sent_at) == (m["analyst"], f"pod:{pod_1}", at)


def test_a_pm_without_an_analyst_holds_all_month(months) -> None:
    lone = [w for st in months["a"]["run"].steps for w in st.wakes if w.spec_id == "c-pm-2"]
    assert len(lone) == DAYS
    assert all(w.transcript[-1].content == "No signal from my analyst for today; holding."
               for w in lone)


def test_the_same_world_twice_writes_the_same_cassette_bytes(months) -> None:
    """R-4a: the cassette is a pure function of the run — nothing in it is a clock or a dice."""
    from runtime import cassette
    from runtime.lockstep import record_json
    a, b = (cassette.dumps({"run": record_json(months[k]["run"])}) for k in "ab")
    assert a == b and a[1] == 0
    wakes = [w for st in months["a"]["run"].steps for w in st.wakes]
    assert wakes and all(len(w.exchanges) == sum(m.role == "assistant" for m in w.transcript)
                         for w in wakes)
    hashes = [e.request_sha256 for w in wakes for e in w.exchanges]
    assert len(set(hashes)) > len(hashes) // 2  # days differ: requests are not all one request


def test_the_same_world_twice_leaves_the_same_pod_ledger(months) -> None:
    a, b = months["a"], months["b"]
    assert len(a["ledger"]) == len(b["ledger"])
    for x, y in zip(a["ledger"], b["ledger"]):
        assert x == y, f"first divergence at event {x[0]}:\n{x}\n{y}"
    assert [w.transcript for st in a["run"].steps for w in st.wakes] == \
        [w.transcript for st in b["run"].steps for w in st.wakes]
