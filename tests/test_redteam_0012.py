"""RED-TEAM 0012 — attacks on cycle 0021's Runtime gates (R-1, ADR-032 + cycle-21 amendment).

Claims under attack:

* ``runtime.governance`` reads HALT and ``firm.monthly_llm_usd_cap`` fresh from
  fixed paths and **fails closed**: every cap it cannot read is ``null`` with a
  ``cap_problem``; only a definite "no such file" means the world runs.
* ``runtime.gate`` lets only ``{scripted, cassette}`` wake under cap ``null``;
  ``metered`` and the ``openclaw`` adapter are always treated as spending
  (ADR-032 (4)).
* ``runtime.spec.AgentSpec`` forbids extra fields; ``load_specs`` refuses a bad
  file with a ``SpecError`` naming it, refuses duplicate ids, orders by id.
* The dependency law: the runtime layer imports no ``app`` module, and what it
  loads is probed dynamically.

Attackers: a firm agent (has only its key; cannot reach any of this — every hole
below is operator- or human-reachable), a careless or hostile spec author, a
careless Human editing ``human.yaml``.

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.

Never touches the real HALT file: every test points the reader at ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime import cli, gate, governance
from runtime.gate import decide_batch, decide_wake_under
from runtime.governance import Governance
from runtime.spec import AgentSpec, SpecError, load_specs
from tests.test_boundaries import LAYERS, _plant, violations

REPO_ROOT = Path(__file__).resolve().parent.parent
CAP_NULL = "firm:\n  monthly_llm_usd_cap: null\n"
LAW_NULL = Governance(halted=False, monthly_llm_usd_cap=None)

SPEC_BASE = "id: {id}\nname: {id}\nrole: management\ncharter: run the firm\n"


@pytest.fixture
def gov(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "gov"
    d.mkdir()
    monkeypatch.setattr(governance, "HALT_FILE", d / "HALT")
    monkeypatch.setattr(governance, "HUMAN_YAML", d / "human.yaml")
    (d / "human.yaml").write_text(CAP_NULL)
    return d


def _status(specs: Path) -> dict:
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["status", "--specs", str(specs)]) == 0
    return json.loads(out.getvalue())


# --- HOLE 1 (high): the openclaw adapter wakes under cap null -------------------------


# Was a strict xfail (H1); fixed in cycle 21 (the gate decides on provider + adapter). Guard.
def test_openclaw_adapter_never_wakes_under_cap_null(gov: Path, tmp_path: Path) -> None:
    """ADR-032 (4): "`metered` and the `openclaw` adapter are always treated as
    spending". An OpenClaw agent runs its own model on its own key, so a spec
    that names ``provider: scripted`` but ``adapter: openclaw`` is a spending
    mind with a $0 label. The gate never sees the adapter."""
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "boss.yaml").write_text(
        SPEC_BASE.format(id="boss")
        + "provider: scripted\nadapter: openclaw\nmodel: anthropic/claude-opus\n"
    )
    wake = _status(specs)["wakes"][0]
    assert wake["allowed"] is False, wake


# --- HOLE 2 (medium): the cap reader crashes instead of failing closed ----------------


# Found by 0012; fixed in the cycle-21 working tree (catch-all in _read_cap). Guard.
@pytest.mark.parametrize("data", [
    # A careless Human: a Latin-1 euro sign in a comment.
    b"firm:\n  monthly_llm_usd_cap: null  # about 50\x80 later\n",
    # An unhashable (sequence) key: the duplicate-key check does `key in set`.
    b"? [a, b]\n: 1\nfirm:\n  monthly_llm_usd_cap: null\n",
    # Deep nesting: RecursionError from the composer/constructor.
    b"x: " + b"[" * 50000 + b"]" * 50000 + b"\nfirm:\n  monthly_llm_usd_cap: null\n",
], ids=["non-utf8", "unhashable-key", "deep-nesting"])
def test_unreadable_human_yaml_reads_as_null_not_a_crash(gov: Path, data: bytes) -> None:
    (gov / "human.yaml").write_bytes(data)
    law = governance.read_governance()
    assert law.monthly_llm_usd_cap is None
    assert law.cap_problem


# Found by 0012; fixed in the cycle-21 working tree (HALT read first). Guard.
def test_halt_still_answers_when_human_yaml_is_broken(gov: Path) -> None:
    """decide_batch needs only HALT, but read_governance reads the cap first. A
    caller that treats an exception as 'gate unavailable, carry on' runs a
    halted batch."""
    (gov / "human.yaml").write_bytes(b"firm:\n  monthly_llm_usd_cap: null # \xff\n")
    (gov / "HALT").write_text("")
    assert decide_batch() == gate.Decision(False, "halted")


# --- HOLE 3 (medium): a missing governance directory reads as "running" ---------------


# Was a strict xfail (H3); fixed in cycle 21. Guard.
def test_missing_governance_directory_is_halted(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """REPO_ROOT is ``Path(__file__).parent.parent``. Installed non-editable
    (``uv sync --no-editable`` / ``UV_NO_EDITABLE=1``, ``uv tool install .``,
    the wheel now ships ``runtime``) or run from a copied tree or a PYTHONPATH
    shadow, it is not the repo: ``<root>/governance/`` does not exist, lstat
    raises FileNotFoundError, and HALT reads as absent even while the Human's
    real HALT file exists. Only "the directory is there and the file is not"
    should mean running."""
    nowhere = tmp_path / "not-a-repo" / "governance"
    monkeypatch.setattr(governance, "HALT_FILE", nowhere / "HALT")
    monkeypatch.setattr(governance, "HUMAN_YAML", nowhere / "human.yaml")
    assert governance.read_governance().halted is True


# --- HOLE 4 (low): the gate trusts a str subclass's __eq__/__hash__ --------------------


class _Liar(str):
    def __hash__(self) -> int:
        return hash("scripted")

    def __eq__(self, other: object) -> bool:
        return True

    __ne__ = lambda self, other: False  # noqa: E731


# Was a strict xfail (H4); fixed in cycle 21. Guard.
def test_gate_refuses_a_str_subclass_provider() -> None:
    """Code-author only: AgentSpec coerces to plain ``str`` (held, below), but the
    public ``decide_wake``/``decide_wake_under`` take the name directly. Fix:
    ``type(provider) is str``."""
    assert decide_wake_under(_Liar("openrouter"), "native", LAW_NULL).allowed is False


# --- HOLE 5 (low): load_specs crashes instead of refusing with SpecError --------------


@pytest.mark.parametrize("extra", [
    pytest.param(b"1: 2\n", id="int-key"),  # was a strict xfail (H5); fixed in cycle 21
    pytest.param(b"# \xff\n", id="non-utf8"),  # fixed in the cycle-21 working tree
])
def test_bad_spec_file_is_a_spec_error(tmp_path: Path, extra: bytes) -> None:
    (tmp_path / "a.yaml").write_bytes(SPEC_BASE.format(id="a").encode()
                                      + b"provider: scripted\n" + extra)
    with pytest.raises(SpecError, match="a.yaml"):
        load_specs(tmp_path)


# --- HOLE 6 (low): a duplicate key in a spec silently keeps the last -----------------


# Found by 0012; fixed in the cycle-21 working tree (load_unique_yaml). Guard.
def test_duplicate_key_in_a_spec_is_refused(tmp_path: Path) -> None:
    """A reviewer reading top-down sees ``provider: metered``; the gate sees the
    last one. The governance reader already refuses duplicates; the spec loader
    should too."""
    (tmp_path / "a.yaml").write_text(
        SPEC_BASE.format(id="a") + "provider: metered\nprovider: scripted\n")
    with pytest.raises(SpecError):
        load_specs(tmp_path)


# --- HOLE 7 (low): YAML 1.1 sexagesimal turns a time-like value into a cap ----------


# Was a strict xfail (H7); fixed in cycle 21. Guard.
def test_sexagesimal_is_not_a_cap(gov: Path) -> None:
    (gov / "human.yaml").write_text("firm:\n  monthly_llm_usd_cap: 1:30\n")
    assert governance.read_governance().monthly_llm_usd_cap is None


# --- HOLE 8 (low): a computed dynamic import in runtime/ escapes both probes ----------


# Was a strict xfail (H8); fixed in cycle 21. Guard.
def test_scanner_flags_a_computed_import_in_runtime(tmp_path: Path) -> None:
    """The dynamic probe only sees what loads at *import* time; the static scanner
    only sees literal names. ``import_module("app." + x)`` inside a wake function
    loads the ledger at run time and neither half sees it. Fix: in the runtime
    layer, a dynamic import with a non-literal name is itself a violation (and
    likewise ``importlib.util.spec_from_file_location``)."""
    _plant(tmp_path, {
        "runtime/sneaky.py": (
            "import importlib\n"
            "def wake(part='ledger.events'):\n"
            "    return importlib.import_module('app.' + part)\n"
        ),
    })
    layer = {layer.name: layer for layer in LAYERS}["runtime"]
    assert violations(tmp_path, layer) != []


# --- HELD: attacks that failed (regression guards) ------------------------------------


@pytest.mark.parametrize("text", [
    # merge keys cannot slip a number past the duplicate-key loader
    "firm:\n  <<: [{monthly_llm_usd_cap: 5}, {monthly_llm_usd_cap: null}]\n",
    "d: &d {monthly_llm_usd_cap: 5}\nfirm:\n  <<: *d\n",
    # a second document cannot override the first
    CAP_NULL + "---\nfirm:\n  monthly_llm_usd_cap: 5\n",
    # duplicate top-level `firm`
    CAP_NULL + "firm:\n  monthly_llm_usd_cap: 5\n",
    # numeric-looking strings and tagged strings
    "firm:\n  monthly_llm_usd_cap: !!str 5\n",
    "firm:\n  monthly_llm_usd_cap: 1e400\n",
    "firm:\n  monthly_llm_usd_cap: !!float 1e400\n",
    "firm:\n  monthly_llm_usd_cap: -0.0001\n",
    "firm:\n  monthly_llm_usd_cap: {amount: 5}\n",
])
def test_held_hostile_human_yaml_reads_as_null(gov: Path, text: str) -> None:
    (gov / "human.yaml").write_text(text)
    assert governance.read_governance().monthly_llm_usd_cap is None


@pytest.mark.parametrize("make", ["dir", "dangling", "loop", "fifo"])
def test_held_anything_at_halt_path_halts(gov: Path, make: str) -> None:
    halt = gov / "HALT"
    if make == "dir":
        halt.mkdir()
    elif make == "dangling":
        halt.symlink_to(gov / "nowhere")
    elif make == "loop":
        halt.symlink_to(halt)
    else:
        os.mkfifo(halt)
    assert decide_batch() == gate.Decision(False, "halted")


def test_held_halt_under_a_non_directory_parent_halts(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "gov"
    f.write_text("i am a file")
    monkeypatch.setattr(governance, "HALT_FILE", f / "HALT")
    assert governance.read_governance().halted is True


@pytest.mark.parametrize("name", [
    "Scripted", "scripted ", " scripted", "scripted\n", "scriptеd", "scripted\x00",
    "cassette/metered", "metered", "openclaw", "",
])
def test_held_near_miss_provider_names_refused(name: str) -> None:
    assert decide_wake_under(name, "native", LAW_NULL).allowed is False


def test_held_agentspec_coerces_a_str_subclass_to_plain_str() -> None:
    spec = AgentSpec(id="a", name="a", role="management", provider=_Liar("openrouter"),
                     charter="c")
    assert type(spec.provider) is str
    assert decide_wake_under(spec.provider, "native", LAW_NULL).allowed is False


@pytest.mark.parametrize("field", [
    {"cost_usd": 0}, {"spends_money": False}, {"zero_cost": True}, {"Provider": "scripted"},
])
def test_held_agentspec_refuses_smuggled_fields(field: dict) -> None:
    with pytest.raises(Exception):
        AgentSpec(id="a", name="a", role="management", provider="metered", charter="c", **field)


@pytest.mark.parametrize("bad_id", ["a\n", "aа", "A", "a_b", "-a", "a" * 64])
def test_held_spec_ids_are_plain(bad_id: str) -> None:
    with pytest.raises(Exception):
        AgentSpec(id=bad_id, name="x", role="management", provider="scripted", charter="c")


def test_held_symlinked_spec_is_a_duplicate(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(SPEC_BASE.format(id="a") + "provider: scripted\n")
    (tmp_path / "b.yaml").symlink_to(tmp_path / "a.yaml")
    with pytest.raises(SpecError, match="duplicate"):
        load_specs(tmp_path)


def test_held_order_is_by_id_not_file_name(tmp_path: Path) -> None:
    (tmp_path / "z.yaml").write_text(SPEC_BASE.format(id="aa") + "provider: scripted\n")
    (tmp_path / "a.yaml").write_text(SPEC_BASE.format(id="zz") + "provider: scripted\n")
    assert [s.id for s in load_specs(tmp_path)] == ["aa", "zz"]


@pytest.mark.parametrize("name", ["m.YAML", "m.yml", "m.Yaml"])
def test_held_near_miss_extension_is_refused_not_skipped(tmp_path: Path, name: str) -> None:
    """A spec that would be silently skipped is refused (cycle-21 working tree)."""
    (tmp_path / "a.yaml").write_text(SPEC_BASE.format(id="a") + "provider: scripted\n")
    (tmp_path / name).write_text(SPEC_BASE.format(id="mm") + "provider: metered\n")
    with pytest.raises(SpecError, match=name):
        load_specs(tmp_path)


def test_held_no_env_var_moves_the_governance_paths(tmp_path: Path) -> None:
    """FUND_* settings and the cwd do not move the fixed paths."""
    env = dict(os.environ)
    env.update({"FUND_GOVERNANCE_DIR": str(tmp_path), "FUND_HALT_FILE": str(tmp_path / "H"),
                "FUND_REPO_ROOT": str(tmp_path), "HOME": str(tmp_path)})
    code = ("import json, runtime.governance as g; "
            "print(json.dumps([str(g.HALT_FILE), str(g.HUMAN_YAML)]))")
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                         capture_output=True, text=True, check=True, timeout=60)
    halt, human = json.loads(out.stdout)
    assert halt == str(REPO_ROOT / "governance" / "HALT")
    assert human == str(REPO_ROOT / "governance" / "human.yaml")
