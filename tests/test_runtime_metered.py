"""M-001, milestone 1: the fake METERED provider and the gate that opens it only with a key.

Pinned here (ADR-044):

* **the gate** — a spending provider wakes only under a numeric cap, only when the Runtime says it
  holds a key (``metered is True``), only for the one name ``fake-metered`` through the one
  adapter ``native``; HALT and a ``null`` cap still come first;
* **the meter** — every model turn of a metered mind is charged exactly once, all-or-nothing, and
  never past its key's limit; the price is a deterministic function of the request and reply;
* **the registry** — the name builds one class, from a spec with a script, a budget and no model;
* **the under-reporting analyst** — a script that claims a cost the meter does not believe.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.limits import KEY_REF_PATTERN as APP_KEY_REF_PATTERN
from app.limits import MAX_METERED_USD_MICROS as APP_MAX_MICROS
from runtime import gate, metering, scripted
from runtime.gate import METERED_ADAPTERS, METERED_PROVIDERS, decide_wake_under
from runtime.governance import Governance
from runtime.metering import (
    FakeMeteredProvider,
    FakeProvisioner,
    LimitExceeded,
    Meter,
    fake_charge,
    usd_to_micros_floor,
)
from runtime.providers import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ToolCall,
    Usage,
)
from runtime.registry import ProviderRefused, build_provider, check_spec
from runtime.spec import AgentSpec

CAP_50 = Governance(False, 50.0)
CAP_NULL = Governance(False, None)
HALTED = Governance(True, 50.0)


def _spec(**fields) -> AgentSpec:
    base = dict(id="a-analyst", name="desk-1-analyst", role="analyst", pod=1,
                provider="fake-metered", script="ma-signal-analyst-underreports",
                budget_usd=20.0, charter="Analyse.")
    return AgentSpec(**(base | fields))


def _meter(limit: int = 20_000_000) -> Meter:
    prov = FakeProvisioner()
    return Meter(prov, prov.create_key(7, limit))


# --- the gate ---------------------------------------------------------------------------


def test_fake_metered_wakes_under_a_numeric_cap_only_with_a_key() -> None:
    assert decide_wake_under("fake-metered", "native", CAP_50, metered=True) == gate.Decision(True, "metered")
    assert decide_wake_under("fake-metered", "native", CAP_50, metered=False).reason == "no_metered_key"
    assert decide_wake_under("fake-metered", "native", CAP_50).reason == "no_metered_key"


def test_a_key_does_not_open_the_gate_under_cap_null() -> None:
    d = decide_wake_under("fake-metered", "native", CAP_NULL, metered=True)
    assert (d.allowed, d.reason) == (False, "cap_null")


def test_halt_refuses_a_metered_mind_with_a_key() -> None:
    d = decide_wake_under("fake-metered", "native", HALTED, metered=True)
    assert (d.allowed, d.reason) == (False, "halted")


class _Truthy:
    def __bool__(self) -> bool:
        return True


@pytest.mark.parametrize("flag", [1, "yes", _Truthy(), [1], object()])
def test_metered_must_be_exactly_true(flag) -> None:
    assert decide_wake_under("fake-metered", "native", CAP_50, metered=flag).reason == "no_metered_key"


class _Str(str):
    def __eq__(self, other) -> bool:  # a subclass answering the membership test by itself
        return True

    __hash__ = str.__hash__


@pytest.mark.parametrize("name", ["metered", "openrouter", "Fake-Metered", "fake-metered ", "",
                                  _Str("fake-metered"), None, 3])
def test_only_fake_metered_is_metered(name) -> None:
    assert not decide_wake_under(name, "native", CAP_50, metered=True).allowed


def test_fake_metered_through_openclaw_is_refused() -> None:
    d = decide_wake_under("fake-metered", "openclaw", CAP_50, metered=True)
    assert (d.allowed, d.reason) == (False, "no_metered_key")


def test_the_metered_list_is_exactly_one_name() -> None:
    assert METERED_PROVIDERS == frozenset({"fake-metered"})
    assert METERED_ADAPTERS == frozenset({"native"})
    assert not METERED_PROVIDERS & gate.ZERO_COST_PROVIDERS


def test_a_zero_cost_mind_still_wakes_without_a_key_under_any_cap() -> None:
    for law in (CAP_NULL, CAP_50):
        assert decide_wake_under("scripted", "native", law).reason == "zero_cost"


# --- the meter --------------------------------------------------------------------------


def _req(text: str = "hello") -> CompletionRequest:
    return CompletionRequest(messages=[Message(role="user", content=text)])


def test_fake_charge_is_deterministic_and_positive() -> None:
    req, resp = _req(), CompletionResponse(content="ok")
    first = fake_charge(req, resp)
    assert first == fake_charge(req, resp)
    tokens_in, tokens_out, micros = first
    assert tokens_in > 0 and tokens_out > 0 and micros == 3 * tokens_in + 15 * tokens_out
    assert fake_charge(_req("hello " * 50), resp)[2] > micros   # more context costs more


def test_fake_metered_provider_charges_every_turn_once() -> None:
    meter = _meter()
    calls = []

    def script(request):
        calls.append(request)
        return CompletionResponse(content=f"turn {len(calls)}")

    provider = FakeMeteredProvider(script, meter)
    expected = 0
    for i in range(5):
        req = _req(f"q{i}")
        resp = provider.complete(req)
        assert resp.usage.cost_usd > 0
        expected += fake_charge(req, CompletionResponse(content=f"turn {i + 1}"))[2]
    prov = meter.provisioner
    assert prov.charges(meter.key_ref) == 5
    assert prov.usage()[0].usd_micros_total == expected


def test_a_charge_past_the_limit_raises_and_spends_nothing() -> None:
    req, resp = _req(), CompletionResponse(content="ok")
    price = fake_charge(req, resp)[2]
    meter = _meter(limit=price + price // 2)           # room for one turn, not two
    provider = FakeMeteredProvider(lambda r: resp, meter)
    provider.complete(req)
    with pytest.raises(LimitExceeded):
        provider.complete(req)
    prov = meter.provisioner
    assert prov.usage()[0].usd_micros_total == price and prov.charges(meter.key_ref) == 1
    prov.charge(meter.key_ref, price // 2)             # a charge that fits is still accepted
    assert prov.usage()[0].usd_micros_total == price + price // 2


def test_create_key_refuses_a_limit_above_max_and_a_bad_label() -> None:
    prov = FakeProvisioner()
    prov.create_key(1, metering.MAX_METERED_USD_MICROS)
    for bad in (metering.MAX_METERED_USD_MICROS + 1, -1, 1.5, True):
        with pytest.raises(ValueError):
            prov.create_key(1, bad)
    assert len(prov.usage()) == 1
    assert re.fullmatch(metering.KEY_REF_PATTERN, prov.usage()[0].key_ref)


def test_the_runtime_copies_of_max_micros_and_key_ref_pattern_match_physics() -> None:
    assert metering.MAX_METERED_USD_MICROS == APP_MAX_MICROS
    assert metering.KEY_REF_PATTERN == APP_KEY_REF_PATTERN


@pytest.mark.parametrize("usd, micros", [(20.0, 20_000_000), (0.1, 100_000), (1e-7, 0),
                                         (0.0000019, 1), (0, 0)])
def test_usd_to_micros_floors_exactly(usd, micros) -> None:
    assert usd_to_micros_floor(usd) == micros


_NETWORK = {"httpx", "requests", "urllib", "socket", "aiohttp", "http", "openai", "anthropic"}


def _reaches_network(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names} & _NETWORK
        elif isinstance(node, ast.ImportFrom) and node.module:
            found |= {node.module.split(".")[0]} & _NETWORK
    return found


def test_the_fake_metering_classes_name_no_network_client() -> None:
    src = Path(metering.__file__).read_text()
    assert _reaches_network(src) == set()
    assert _reaches_network(src + "\nimport httpx\n") == {"httpx"}   # the check can fail


# --- the registry -----------------------------------------------------------------------


def test_fake_metered_builds_exactly_the_fake_metered_class() -> None:
    provider = build_provider(_spec(), meter=_meter())
    assert type(provider) is FakeMeteredProvider and provider.spends_money is True


@pytest.mark.parametrize("fields, reason", [
    ({"script": "no-such-script"}, "unknown_script"),
    ({"script": None}, "unknown_script"),
    ({"budget_usd": 0.0}, "no_budget"),
    ({"budget_usd": 1e-7}, "no_budget"),                       # floors to 0 micro-dollars
    ({"model": "anthropic/claude-opus"}, "contradiction"),
])
def test_fake_metered_needs_a_script_a_budget_and_no_model(fields, reason) -> None:
    with pytest.raises(ProviderRefused) as exc:
        check_spec(_spec(**fields))
    assert exc.value.reason == reason


def test_fake_metered_without_a_meter_is_unavailable() -> None:
    with pytest.raises(ProviderRefused) as exc:
        build_provider(_spec())
    assert exc.value.reason == "unavailable"


def test_a_meter_handed_to_scripted_is_a_contradiction() -> None:
    zero = _spec(provider="scripted", script="moving-average-pm", budget_usd=0.0)
    with pytest.raises(ProviderRefused) as exc:
        build_provider(zero, meter=_meter())
    assert exc.value.reason == "contradiction"


def test_a_fake_metered_mind_takes_a_real_meter_only() -> None:
    class Imposter:
        provisioner, key_ref = FakeProvisioner(), "fake-0001"

    with pytest.raises(ProviderRefused) as exc:
        build_provider(_spec(), meter=Imposter())
    assert exc.value.reason == "unavailable"


# --- the under-reporting analyst ---------------------------------------------------------


def test_underreporting_analyst_reports_once_after_its_signal_then_is_done() -> None:
    script = scripted.SCRIPTS["ma-signal-analyst-underreports"]
    inner = scripted.SCRIPTS["ma-signal-analyst"]
    import json as _json
    ctx = _json.dumps({"me": {"pod_id": 1}, "input": {"universe": ["SYNA"]}})
    msgs = [Message(role="system", content="c"), Message(role="user", content=ctx)]
    # Turns 0 and 1 are the inner script's own.
    assert script(CompletionRequest(messages=msgs)) == inner(CompletionRequest(messages=msgs))
    msgs += [Message(role="assistant", content="", tool_calls=[
                 ToolCall(id="clock", name="get_clock"),
                 ToolCall(id="bars:SYNA", name="get_ohlcv")]),
             Message(role="tool", content=_json.dumps({"now": "2024-01-02T14:30:00Z"}), tool_call_id="clock"),
             Message(role="tool", content=_json.dumps({"bars": []}), tool_call_id="bars:SYNA")]
    # The wrapper never alters a call of the inner script: the signal goes out as it would.
    reply = script(CompletionRequest(messages=msgs))
    assert reply == inner(CompletionRequest(messages=msgs)) and reply.tool_calls[0].id == "signal"
    # When the inner script is done, the wrapper reports its (false) cost, once.
    done = msgs + [Message(role="assistant", content="", tool_calls=[ToolCall(id="signal", name="send_message")]),
                   Message(role="tool", content="{}", tool_call_id="signal")]
    report = script(CompletionRequest(messages=done))
    [call] = report.tool_calls
    assert (call.id, call.name) == ("self-report", "report_cost")
    assert call.arguments["usd_cost"] == 0.01
    after = done + [Message(role="assistant", content="", tool_calls=[call]),
                    Message(role="tool", content="{}", tool_call_id="self-report")]
    assert script(CompletionRequest(messages=after)).tool_calls == []


# --- what physics is told about these minds ------------------------------------------------


def test_fake_metered_native_is_declared_scripted() -> None:
    from runtime.lockstep import mind_kinds
    assert mind_kinds([_spec()]) == ["scripted"]


def test_fake_metered_through_openclaw_is_declared_model() -> None:
    from runtime.lockstep import mind_kinds
    assert mind_kinds([_spec(adapter="openclaw")]) == ["model"]
