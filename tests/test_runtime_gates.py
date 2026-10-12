"""R-1: the Runtime's skeleton and its gates (ADR-032 (4), Q-0005, 03_WORLD §3).

Nothing wakes here. These tests pin the three doors every later slice must pass:

* the **governance reader** reads ``governance/HALT`` and ``human.yaml`` fresh on
  every call, from fixed paths, and turns every cap it cannot read as a finite
  non-negative number into ``null`` (fail closed);
* the **wake gate** lets nothing through under HALT and, under cap ``null``, only
  the providers on a closed list in code. It never asks a provider what it costs;
* the **AgentSpec** is data the operator writes: frozen, no extra fields, ids
  unique and in a fixed order (the lockstep order, ADR-032 (5)).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime import cli, gate, governance
from runtime.gate import ZERO_COST_PROVIDERS, decide_batch, decide_wake
from runtime.providers import CompletionRequest, CompletionResponse, LLMProvider, Usage
from runtime.spec import AgentSpec, SpecError, load_specs

CAP_NULL = "firm:\n  monthly_llm_usd_cap: null\n"
CAP_50 = "firm:\n  monthly_llm_usd_cap: 50\n"


@pytest.fixture
def gov(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the reader's fixed paths at a temporary governance directory."""
    d = tmp_path / "governance"
    d.mkdir()
    monkeypatch.setattr(governance, "HALT_FILE", d / "HALT")
    monkeypatch.setattr(governance, "HUMAN_YAML", d / "human.yaml")
    (d / "human.yaml").write_text(CAP_NULL)
    return d


def _cap(gov: Path, text: str) -> governance.Governance:
    (gov / "human.yaml").write_text(text)
    return governance.read_governance()


# --- the governance reader -------------------------------------------------------------


def test_reader_paths_are_the_constitutions() -> None:
    root = Path(__file__).resolve().parent.parent
    assert governance.HALT_FILE == root / "governance" / "HALT"
    assert governance.HUMAN_YAML == root / "governance" / "human.yaml"


def test_the_real_human_yaml_reads_as_cap_null() -> None:
    """Today's law, read through the real file (not a fixture)."""
    g = governance.read_governance()
    assert g.monthly_llm_usd_cap is None
    assert g.cap_problem is None  # null is a valid answer, not a parse failure


def test_a_numeric_cap_is_read(gov: Path) -> None:
    assert _cap(gov, CAP_50).monthly_llm_usd_cap == 50.0
    assert _cap(gov, "firm:\n  monthly_llm_usd_cap: 12.5\n").monthly_llm_usd_cap == 12.5
    assert _cap(gov, "firm:\n  monthly_llm_usd_cap: 0\n").monthly_llm_usd_cap == 0.0


@pytest.mark.parametrize("text", [
    "firm:\n  monthly_llm_usd_cap: -1\n",
    "firm:\n  monthly_llm_usd_cap: .inf\n",
    "firm:\n  monthly_llm_usd_cap: .nan\n",
    "firm:\n  monthly_llm_usd_cap: true\n",
    "firm:\n  monthly_llm_usd_cap: '50'\n",
    "firm:\n  monthly_llm_usd_cap: [50]\n",
    "firm:\n  max_concurrent_agents: 12\n",          # key missing
    "firm: 50\n",                                     # firm not a mapping
    "- 1\n- 2\n",                                     # document not a mapping
    "",                                               # empty file
    "firm: {monthly_llm_usd_cap: 50\n",               # not YAML
    "firm:\n  monthly_llm_usd_cap: 50\n  monthly_llm_usd_cap: 60\n",  # duplicate key
])
def test_every_unreadable_cap_fails_closed_to_null(gov: Path, text: str) -> None:
    g = _cap(gov, text)
    assert g.monthly_llm_usd_cap is None
    assert g.cap_problem  # the reason is recorded, never silent


def test_a_missing_human_yaml_fails_closed(gov: Path) -> None:
    (gov / "human.yaml").unlink()
    g = governance.read_governance()
    assert g.monthly_llm_usd_cap is None and g.cap_problem


def test_a_huge_integer_cap_is_finite_or_refused(gov: Path) -> None:
    g = _cap(gov, "firm:\n  monthly_llm_usd_cap: " + "9" * 400 + "\n")
    cap = g.monthly_llm_usd_cap
    assert cap is None or math.isfinite(cap)


def test_halt_is_read_fresh_on_every_call(gov: Path) -> None:
    assert governance.read_governance().halted is False
    (gov / "HALT").write_text("")
    assert governance.read_governance().halted is True
    (gov / "HALT").unlink()
    assert governance.read_governance().halted is False


def test_halt_as_a_directory_or_dangling_link_still_halts(gov: Path) -> None:
    (gov / "HALT").mkdir()
    assert governance.read_governance().halted is True
    (gov / "HALT").rmdir()
    (gov / "HALT").symlink_to(gov / "nowhere")
    assert governance.read_governance().halted is True


def test_halt_that_cannot_be_checked_counts_as_halt(gov: Path) -> None:
    """Only a definite "no such file" means not halted; a permission error does not."""
    gov.chmod(0o000)
    try:
        assert governance.read_governance().halted is True
    finally:
        gov.chmod(0o700)


def test_halt_under_a_governance_path_that_is_a_file_counts_as_halt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "governance").write_text("not a directory")
    monkeypatch.setattr(governance, "HALT_FILE", tmp_path / "governance" / "HALT")
    assert governance.read_governance().halted is True


def test_cap_is_read_fresh_on_every_call(gov: Path) -> None:
    assert governance.read_governance().monthly_llm_usd_cap is None
    (gov / "human.yaml").write_text(CAP_50)
    assert governance.read_governance().monthly_llm_usd_cap == 50.0


# --- the wake gate ---------------------------------------------------------------------


def test_the_zero_cost_list_is_exactly_two_names() -> None:
    assert ZERO_COST_PROVIDERS == frozenset({"scripted", "cassette"})


@pytest.mark.parametrize("provider", sorted(ZERO_COST_PROVIDERS))
def test_zero_cost_providers_wake_under_cap_null(gov: Path, provider: str) -> None:
    d = decide_wake(provider)
    assert d.allowed and d.reason == "zero_cost"


@pytest.mark.parametrize("provider", [
    "metered", "openclaw", "anthropic", "openrouter", "freebie", "",
    "Scripted", "SCRIPTED", " scripted", "scripted ", "scripted\n", "cassette/claude",
])
def test_every_other_provider_is_refused_under_cap_null(gov: Path, provider: str) -> None:
    d = decide_wake(provider)
    assert not d.allowed and d.reason == "cap_null"


def test_a_provider_that_claims_to_be_free_is_still_refused(gov: Path) -> None:
    """The gate owns the list; it never asks the component whether it is dangerous."""

    class Liar:
        name = "freebie"

        @property
        def spends_money(self) -> bool:  # pragma: no cover - must never be read
            raise AssertionError("the gate asked the provider what it costs")

    d = decide_wake(Liar().name)
    assert not d.allowed and d.reason == "cap_null"


@pytest.mark.parametrize("provider", [None, 0, b"scripted", ["scripted"], object()])
def test_a_provider_name_that_is_not_a_string_is_refused(gov: Path, provider: object) -> None:
    d = decide_wake(provider)  # type: ignore[arg-type]
    assert not d.allowed


def test_a_spending_provider_is_refused_even_with_a_cap_until_metering_exists(gov: Path) -> None:
    """A cap without per-agent metered keys (R-6) cannot be enforced, so nothing spends."""
    (gov / "human.yaml").write_text(CAP_50)
    d = decide_wake("metered")
    assert not d.allowed and d.reason == "no_metered_key"
    assert decide_wake("scripted").allowed


@pytest.mark.parametrize("provider", ["scripted", "cassette", "metered", "freebie"])
def test_halt_refuses_every_provider(gov: Path, provider: str) -> None:
    (gov / "HALT").write_text("")
    for cap in (CAP_NULL, CAP_50):
        (gov / "human.yaml").write_text(cap)
        d = decide_wake(provider)
        assert not d.allowed and d.reason == "halted"


def test_halt_refuses_the_next_tool_batch_and_lifting_it_allows_it(gov: Path) -> None:
    assert decide_batch().allowed
    (gov / "HALT").write_text("")
    d = decide_batch()
    assert not d.allowed and d.reason == "halted"
    (gov / "HALT").unlink()
    assert decide_batch().allowed


def test_an_unreadable_cap_refuses_spending_but_names_the_problem(gov: Path) -> None:
    (gov / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: -5\n")
    d = decide_wake("metered")
    assert not d.allowed and d.reason == "cap_null"
    assert decide_wake("scripted").allowed


def test_the_gate_reads_no_provider_attribute() -> None:
    """Static check: the gate module never names ``spends_money`` in code."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(gate))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "spends_money" not in names


# --- the provider protocol -------------------------------------------------------------


def test_a_provider_satisfies_the_protocol() -> None:
    class Echo:
        name = "scripted"
        spends_money = False

        def complete(self, request: CompletionRequest) -> CompletionResponse:
            return CompletionResponse(content=request.messages[-1].content, usage=Usage())

    assert isinstance(Echo(), LLMProvider)
    reply = Echo().complete(CompletionRequest(messages=[{"role": "user", "content": "hi"}]))
    assert reply.content == "hi" and reply.tool_calls == [] and reply.usage.cost_usd == 0.0


@pytest.mark.parametrize("cost", [-0.01, math.inf, math.nan])
def test_usage_cost_must_be_finite_and_non_negative(cost: float) -> None:
    with pytest.raises(ValidationError):
        Usage(cost_usd=cost)


# --- the AgentSpec ---------------------------------------------------------------------


def _spec(**over: object) -> dict:
    base = {
        "id": "pm-alpha", "name": "Alpha PM", "role": "pm", "pod": 1,
        "provider": "scripted", "charter": "Trade the pod's book.",
    }
    base.update(over)
    return base


def test_spec_defaults_are_the_quiet_ones() -> None:
    s = AgentSpec(**_spec())
    assert s.adapter == "native" and s.model is None and s.tools is None
    assert s.budget_usd == 0.0 and s.generation_born == 0 and s.parent_id is None
    assert s.memory_policy == "none" and s.wake_policy == "every_step" and s.mutations == ()


def test_spec_carries_every_03_world_field() -> None:
    fields = set(AgentSpec.model_fields)
    assert {
        "id", "name", "role", "pod", "parent_id", "generation_born", "adapter", "model",
        "charter", "tools", "memory_policy", "budget_usd", "wake_policy", "mutations",
    } <= fields
    assert fields - {
        "id", "name", "role", "pod", "parent_id", "generation_born", "adapter", "model",
        "charter", "tools", "memory_policy", "budget_usd", "wake_policy", "mutations",
    } == {"provider"}  # ADR-032 (3): a mind = provider + adapter + spec


@pytest.mark.parametrize("over", [
    {"role": "system"},                 # physics' own identity, never a mind
    {"role": "runtime"},
    {"role": "pm", "pod": None},        # a PM or Analyst belongs to a pod
    {"role": "analyst", "pod": None},
    {"pod": 0},
    {"id": "PM Alpha"},
    {"id": ""},
    {"id": "a" * 64},
    {"charter": ""},
    {"budget_usd": -1},
    {"budget_usd": math.inf},
    {"budget_usd": math.nan},
    {"generation_born": -1},
    {"adapter": "langchain"},
    {"wake_policy": "always"},
    {"spends_money": False},            # no field lets a spec vouch for its cost
    {"unknown": 1},
])
def test_invalid_specs_are_refused(over: dict) -> None:
    with pytest.raises(ValidationError):
        AgentSpec(**_spec(**over))


def test_spec_is_frozen() -> None:
    s = AgentSpec(**_spec())
    with pytest.raises(ValidationError):
        s.provider = "metered"  # type: ignore[misc]


def _write(d: Path, name: str, spec: dict) -> None:
    import yaml

    (d / name).write_text(yaml.safe_dump(spec))


def test_specs_load_in_id_order(tmp_path: Path) -> None:
    _write(tmp_path, "z.yaml", _spec(id="pm-zeta"))
    _write(tmp_path, "a.yaml", _spec(id="pm-beta"))
    _write(tmp_path, "m.yaml", _spec(id="analyst-a", role="analyst"))
    assert [s.id for s in load_specs(tmp_path)] == ["analyst-a", "pm-beta", "pm-zeta"]


def test_duplicate_spec_ids_are_refused(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", _spec())
    _write(tmp_path, "b.yaml", _spec(name="Other"))
    with pytest.raises(SpecError, match="pm-alpha"):
        load_specs(tmp_path)


@pytest.mark.parametrize("text", ["- 1\n", "id: [\n", ""])
def test_a_malformed_spec_file_is_refused_by_name(tmp_path: Path, text: str) -> None:
    (tmp_path / "bad.yaml").write_text(text)
    with pytest.raises(SpecError, match="bad.yaml"):
        load_specs(tmp_path)


def test_an_invalid_spec_file_is_refused_by_name(tmp_path: Path) -> None:
    _write(tmp_path, "bad.yaml", _spec(role="system"))
    with pytest.raises(SpecError, match="bad.yaml"):
        load_specs(tmp_path)


def test_a_missing_spec_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SpecError):
        load_specs(tmp_path / "nope")


# --- fund-runtime status ---------------------------------------------------------------


def test_status_reports_the_law_and_wakes_nothing(
    gov: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    _write(specs, "pm.yaml", _spec())
    _write(specs, "spender.yaml", _spec(id="pm-spender", provider="metered"))
    assert cli.main(["status", "--specs", str(specs)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["halted"] is False and out["monthly_llm_usd_cap"] is None
    assert out["wakes"] == [
        {"id": "pm-alpha", "provider": "scripted", "allowed": True, "reason": "zero_cost"},
        {"id": "pm-spender", "provider": "metered", "allowed": False, "reason": "cap_null"},
    ]
    assert out["woke"] == 0


def test_status_without_specs_still_reports_the_law(
    gov: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (gov / "HALT").write_text("")
    assert cli.main(["status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["halted"] is True and out["wakes"] == []


def test_status_on_bad_specs_exits_1(
    gov: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "bad.yaml").write_text("- 1\n")
    assert cli.main(["status", "--specs", str(tmp_path)]) == 1
    assert "bad.yaml" in capsys.readouterr().err
