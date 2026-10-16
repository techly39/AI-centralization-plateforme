"""The real metered provider, offline (ADR-047): a fake OpenRouter account behind httpx.MockTransport."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from runtime.metering import FakeProvisioner, Meter
from runtime.openrouter import (
    OpenRouterError,
    OpenRouterProvider,
    OpenRouterProvisioner,
    OverCap,
    holds_secret,
    usd_to_micros_ceil,
)
from runtime.providers import CompletionRequest, Message, ToolCall, ToolSpec
from runtime.registry import ProviderRefused, build_provider, check_spec
from runtime.spec import AgentSpec

CAP = 50_000_000


class Account:
    """An OpenRouter account: keys (the Human's and the firm's), chat answers queued per test."""

    def __init__(self) -> None:
        self.keys: dict[str, dict] = {}
        self.secrets: dict[str, str] = {}
        self.chats: list[dict] = []
        self.answers: list[dict] = []
        self.patched: list[str] = []
        self.add("the-humans-own", limit=None, usage=8.1, disabled=False)

    def add(self, name: str, *, limit, usage=0.0, usage_monthly=None, disabled=False) -> str:
        digest = hashlib.sha256(f"{name}/{len(self.keys)}".encode()).hexdigest()
        self.keys[digest] = {"hash": digest, "name": name, "limit": limit, "usage": usage,
                             "usage_monthly": usage if usage_monthly is None else usage_monthly,
                             "disabled": disabled}
        self.secrets[f"sk-or-v1-{digest[-12:]}secret"] = digest
        return digest

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        path = request.url.path.removeprefix("/api/v1")
        if path == "/chat/completions":
            digest = self.secrets.get(auth.removeprefix("Bearer "))
            assert digest is not None, "a chat call must carry a minted key"
            self.chats.append({"key": digest, "body": json.loads(request.content)})
            answer = self.answers.pop(0)
            self.keys[digest]["usage"] += answer.get("usage", {}).get("cost", 0)
            return httpx.Response(200, json=answer)
        assert auth == "Bearer prov-key", "account calls carry the provisioning key"
        if path == "/keys" and request.method == "GET":
            offset = int(request.url.params.get("offset", 0))
            rows = list(self.keys.values())[offset:offset + 2]   # pages of two
            return httpx.Response(200, json={"data": rows})
        if path == "/keys" and request.method == "POST":
            body = json.loads(request.content)
            digest = self.add(body["name"], limit=body["limit"])
            secret = next(s for s, d in self.secrets.items() if d == digest)
            return httpx.Response(201, json={"data": self.keys[digest], "key": secret})
        digest = path.removeprefix("/keys/")
        if request.method == "GET":
            return httpx.Response(200, json={"data": self.keys[digest]})
        if request.method == "PATCH":
            assert self.keys[digest]["name"].startswith("firm-"), "the Human's keys are never changed"
            self.keys[digest]["disabled"] = json.loads(request.content)["disabled"]
            self.patched.append(digest)
            return httpx.Response(200, json={"data": self.keys[digest]})
        return httpx.Response(404)


@pytest.fixture
def account() -> Account:
    return Account()


def provisioner(account: Account, cap: int = CAP) -> OpenRouterProvisioner:
    return OpenRouterProvisioner("prov-key", cap, transport=httpx.MockTransport(account.handler),
                                 run_tag="t1", settle_s=0, sleep=lambda s: None)


def spec(**more) -> AgentSpec:
    return AgentSpec.model_validate({"id": "b-pm", "name": "desk-1-pm", "role": "pm", "pod": 1,
                                     "provider": "openrouter", "model": "vendor/cheap",
                                     "budget_usd": 1.0, "charter": "Trade."} | more)


def request(*messages: Message) -> CompletionRequest:
    return CompletionRequest(
        messages=list(messages) or [Message(role="system", content="c"), Message(role="user", content="u")],
        tools=[ToolSpec(name="get_price", description="d", input_schema={"type": "object"})],
        model="vendor/cheap")


def chat(content="", calls=(), cost=0.0012) -> dict:
    return {"choices": [{"message": {"content": content, "tool_calls": [
        {"id": "call_0", "type": "function", "function": {"name": n, "arguments": a}}
        for n, a in calls]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": cost}}


# -- the monthly accounting -----------------------------------------------------------------

def test_the_humans_keys_are_never_counted_or_changed(account) -> None:
    p = provisioner(account)
    assert p.month_committed() == 0
    p.create_key(7, 2_000_000, spec_id="b-pm")
    assert p.close() == []
    assert [account.keys[d]["name"] for d in account.patched] == ["firm-t1-b-pm"]


def test_enabled_firm_keys_count_their_limit_and_disabled_ones_their_month(account) -> None:
    account.add("firm-old-a", limit=10.0, usage=9.0, usage_monthly=3.0, disabled=True)
    account.add("firm-old-b", limit=4.0, usage=1.0, disabled=False)
    account.add("not-firm", limit=40.0, usage=40.0, disabled=False)
    assert provisioner(account).month_committed() == 7_000_000   # 3 spent + 4 still spendable


def test_a_key_that_would_pass_the_cap_across_runs_is_not_minted(account) -> None:
    account.add("firm-earlier-run", limit=45.0, disabled=False)
    p = provisioner(account)
    p.create_key(1, 5_000_000, spec_id="a")              # 45 + 5 = 50: fits exactly
    with pytest.raises(OverCap):
        p.create_key(2, 1, spec_id="b")                   # one micro-dollar more does not
    assert sum(1 for k in account.keys.values() if k["name"].startswith("firm-t1-")) == 1


def test_an_unlimited_firm_key_makes_the_month_unbounded(account) -> None:
    account.add("firm-no-limit", limit=None)
    with pytest.raises(OverCap):
        provisioner(account).create_key(1, 1, spec_id="a")


@pytest.mark.parametrize("bad", [0, -1, 1.5, 10**12 + 1])
def test_a_key_limit_is_a_positive_int_of_micros(account, bad) -> None:
    with pytest.raises(ValueError):
        provisioner(account).create_key(1, bad)


def test_spend_is_rounded_up_and_garbage_is_refused() -> None:
    assert usd_to_micros_ceil(0.0000001) == 1 and usd_to_micros_ceil(None) == 0
    assert usd_to_micros_ceil(0.001 + 0.0005 + 0.003) == 4500      # float noise is not spend
    assert usd_to_micros_ceil(8.14448822) == 8144489
    for bad in (float("nan"), -1.0, "1", True):
        with pytest.raises(OpenRouterError):
            usd_to_micros_ceil(bad)


# -- the mind ---------------------------------------------------------------------------------

def test_a_turn_goes_to_the_minds_own_key_and_its_cost_is_the_providers(account) -> None:
    p = provisioner(account)
    meter = Meter(p, p.create_key(7, 1_000_000, spec_id="b-pm"))
    mind = build_provider(spec(), meter=meter)
    assert type(mind) is OpenRouterProvider
    account.answers.append(chat("hold", [("get_price", '{"ticker": "SYNA"}')], cost=0.0012))
    out = mind.complete(request())
    assert [(c.id, c.name, c.arguments) for c in out.tool_calls] == [("t0c0", "get_price", {"ticker": "SYNA"})]
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cost_usd) == (100, 20, 0.0012)
    sent = account.chats[0]
    assert account.keys[sent["key"]]["name"] == "firm-t1-b-pm"
    assert sent["body"]["model"] == "vendor/cheap" and sent["body"]["usage"] == {"include": True}
    assert sent["body"]["tools"][0]["function"]["name"] == "get_price"
    assert p.charges(meter.key_ref) == 1
    assert [u.usd_micros_total for u in p.usage()] == [1200]


def test_the_transcript_goes_out_in_the_providers_shape(account) -> None:
    p = provisioner(account)
    mind = build_provider(spec(), meter=Meter(p, p.create_key(7, 1_000_000)))
    account.answers.append(chat("done"))
    out = mind.complete(request(
        Message(role="system", content="charter"), Message(role="user", content="today"),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="t0c0", name="get_price",
                                                                    arguments={"ticker": "X"})]),
        Message(role="tool", content="no such ticker", tool_call_id="t0c0", is_error=True)))
    wire = account.chats[0]["body"]["messages"]
    assert wire[2] == {"role": "assistant", "content": None, "tool_calls": [
        {"id": "t0c0", "type": "function", "function": {"name": "get_price", "arguments": '{"ticker": "X"}'}}]}
    assert wire[3] == {"role": "tool", "tool_call_id": "t0c0", "content": "ERROR: no such ticker"}
    assert out.content == "done" and out.tool_calls == []


def test_ids_are_the_runtimes_and_bad_arguments_reach_the_tool_as_such(account) -> None:
    p = provisioner(account)
    mind = build_provider(spec(), meter=Meter(p, p.create_key(7, 1_000_000)))
    account.answers.append(chat(calls=[("a", "not json"), ("b", "[1]"), ("c", "")]))
    out = mind.complete(request(Message(role="system", content="c"),
                                Message(role="assistant", content="earlier turn")))
    assert [c.id for c in out.tool_calls] == ["t1c0", "t1c1", "t1c2"]
    assert [c.arguments for c in out.tool_calls] == [
        {"_unparsed_arguments": "not json"}, {"_unparsed_arguments": "[1]"}, {}]


@pytest.mark.parametrize("answer", [{"choices": []}, {"error": {"message": "no credits"}},
                                    {"choices": ["x"]}])
def test_an_answer_without_a_reply_raises_and_its_cost_is_still_booked(account, answer) -> None:
    p = provisioner(account)
    meter = Meter(p, p.create_key(7, 1_000_000))
    mind = build_provider(spec(), meter=meter)
    account.answers.append(answer | {"usage": {"cost": 0.0005}})
    with pytest.raises(OpenRouterError):
        mind.complete(request())
    assert p.usage()[0].usd_micros_total == 500


def test_usage_never_reports_less_than_the_turns_billed(account) -> None:
    p = provisioner(account)
    meter = Meter(p, p.create_key(7, 1_000_000))
    p.billed(meter.key_ref, 900)          # the provider's usage has not caught up yet
    assert p.usage()[0].usd_micros_total == 900


def test_an_http_refusal_is_an_error_not_a_reply(account) -> None:
    p = OpenRouterProvisioner("prov-key", CAP, run_tag="t1", settle_s=0, transport=httpx.MockTransport(
        lambda r: httpx.Response(402, json={"error": "no credits"})))
    with pytest.raises(OpenRouterError) as caught:
        p.month_committed()
    assert caught.value.status == 402


# -- the registry -----------------------------------------------------------------------------

def test_an_openrouter_spec_needs_a_model_and_a_budget_and_no_script() -> None:
    check_spec(spec())
    for more, reason in (({"model": None}, "no_model"), ({"model": " "}, "no_model"),
                         ({"budget_usd": 0}, "no_budget"), ({"script": "signal-pm"}, "contradiction")):
        with pytest.raises(ProviderRefused) as caught:
            check_spec(spec(**more))
        assert caught.value.reason == reason


def test_an_openrouter_mind_needs_an_openrouter_key(account) -> None:
    fake = FakeProvisioner()
    with pytest.raises(ProviderRefused) as caught:
        build_provider(spec(), meter=Meter(fake, fake.create_key(7, 1_000_000)))
    assert caught.value.reason == "unavailable"
    with pytest.raises(ProviderRefused):
        build_provider(spec())


def test_the_secret_scan_finds_a_key() -> None:
    assert holds_secret('{"k": "sk-or-v1-0123456789abcdef"}')
    assert not holds_secret('{"key_ref": "or-0123456789abcdef"}')


# -- a run through the command (the App in-process, OpenRouter faked) --------------------------

from tests.test_runtime_cli_backtest import _run, _write_specs, keys  # noqa: E402,F401 - fixtures
from tests.test_runtime_lockstep import gov, live_afterwards, world  # noqa: E402,F401 - fixtures
from tests.test_runtime_metered_run import _cap, _fold  # noqa: E402


def _or_spec(id: str, name: str, pod: int, budget: float = 1.0) -> dict:
    return {"id": id, "name": name, "role": "pm", "pod": pod, "provider": "openrouter",
            "model": "vendor/cheap", "budget_usd": budget, "charter": "Read the clock."}


@pytest.fixture
def faked(account, monkeypatch):
    """``fund-runtime`` finds this account instead of the real one."""
    from runtime import cli
    monkeypatch.setattr(cli.OpenRouterProvisioner, "from_env",
                        classmethod(lambda cls, cap: provisioner(account, cap)))
    return account


def _answers(account: Account, wakes: int) -> None:
    for _ in range(wakes):   # each wake: ask the clock, then stop
        account.answers += [chat(calls=[("get_clock", "{}")], cost=0.001), chat("done", cost=0.0005)]


def test_a_real_model_month_is_metered_synced_and_its_keys_disabled(
        SessionFactory, keys, tmp_path, gov, faked, capsys) -> None:
    _cap(gov, 50)
    specs = _write_specs(tmp_path / "specs", _or_spec("a-pm", "desk-1-pm", 1),
                         _or_spec("b-pm", "desk-2-pm", 2))
    _answers(faked, 2 * 3)
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "3"], capsys)
    assert code == 0 and out["ended"] == "completed", (out["reason"], err)
    m = out["metering"]
    assert [(k["spec_id"], k["spent_usd_micros"], k["charges"]) for k in m["keys"]] == [
        ("a-pm", 4500, 6), ("b-pm", 4500, 6)]
    assert m["sync"]["posted"] == 2 and m["keys_left_enabled"] == []
    top, _ = _fold(SessionFactory)
    assert sum(top.values()) == m["total_usd_micros"] == 9000
    firm = [k for k in faked.keys.values() if k["name"].startswith("firm-")]
    assert sorted(k["name"] for k in firm) == ["firm-t1-a-pm", "firm-t1-b-pm"]
    assert all(k["disabled"] for k in firm)
    assert faked.answers == []
    assert not holds_secret(json.dumps(out)) and not holds_secret(err)


def test_a_run_that_would_pass_the_month_makes_no_key_beyond_it(
        SessionFactory, keys, tmp_path, gov, faked, capsys) -> None:
    _cap(gov, 50)
    faked.add("firm-earlier", limit=49.5)
    specs = _write_specs(tmp_path / "specs", _or_spec("a-pm", "desk-1-pm", 1, 0.4),
                         _or_spec("b-pm", "desk-2-pm", 2, 0.4))
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 1 and out["ended"] == "refused" and out["reason"] == "provision:key_over_cap:b-pm"
    made = [k for k in faked.keys.values() if k["name"].startswith("firm-t1-")]
    assert [k["name"] for k in made] == ["firm-t1-a-pm"] and made[0]["disabled"] is True
    assert faked.chats == []


def test_no_provisioning_key_refuses_before_any_agent_is_made(
        SessionFactory, keys, tmp_path, gov, capsys, monkeypatch) -> None:
    from runtime.openrouter import PROVISIONING_KEY_ENV
    monkeypatch.delenv(PROVISIONING_KEY_ENV, raising=False)
    _cap(gov, 50)
    specs = _write_specs(tmp_path / "specs", _or_spec("a-pm", "desk-1-pm", 1))
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 1 and out["reason"] == "provision:openrouter_unavailable:0" and out["registered"] == []


def test_a_real_model_run_under_a_null_cap_is_refused_before_anything(
        SessionFactory, keys, tmp_path, gov, faked, capsys) -> None:
    specs = _write_specs(tmp_path / "specs", _or_spec("a-pm", "desk-1-pm", 1))
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 1 and out["reason"] == "provision:wake_refused:a-pm:cap_null"
    assert [k for k in faked.keys.values() if k["name"].startswith("firm-")] == []
