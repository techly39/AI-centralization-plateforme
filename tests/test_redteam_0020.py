"""Red-team pass 0020 (cycle 0036): B-053 (pre-gate ``vet``) and B-054 (HALT reads ``halted``).

Holes are ``xfail(strict=True)`` with their severity in the reason: each passes once the
Builder fixes it, and the strict mark then fails the suite so the mark is removed.
Held guards are plain passing tests: they pin what the attack could not break.

Attacks (from the architect's brief):

1. a spec that passes ``vet`` but can never wake, so physics is told (declaration, agents)
   and nothing wakes;
2. HALT at every await point of ``_conduct`` / ``run_backtest``;
3. a non-halt refusal disguised as a halt (``_is_halt`` on crafted reasons);
4. other 423 sources (none in ``app/``: only ``app.registry.halt``; ``FundClient`` maps a
   transport failure to 503);
5. a governance/cap change between ``_conduct``'s read and ``provision``'s;
6. replay: a HALT mid-replay, and a tape that tries to fake one.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Event
from app.ledger.events import EVENT_CLOCK_ADVANCED, EVENT_HALT_REFUSED, EVENT_RUN_MINDS_DECLARED
from runtime import cassette, cli, lockstep
from runtime.governance import Governance
from runtime.lockstep import mind_kinds
from runtime.provision import vet
from runtime.spec import AgentSpec
from tests.test_runtime_cli_backtest import (  # noqa: F401 - fixtures
    HaltsAt,
    _made,
    _run,
    _spec,
    _write_specs,
    keys,
    specs,
)
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    _app,
    gov,
    live_afterwards,
    woke,
    world,
)


def _events(SessionFactory, kind: str) -> int:
    with SessionFactory() as s:
        return len(list(s.execute(select(Event).where(Event.type == kind)).scalars()))


def _halting(SessionFactory, argv, capsys, path, when, files):
    app = _app(SessionFactory)
    with TestClient(app):
        code = cli.main(["backtest", *argv], transport=HaltsAt(app, path, when, files))
    out, _ = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None)


HALTED = {"ended": "halted", "reason": "halted"}


@pytest.fixture
def desk_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """What ``tests/test_replay_cli.py``'s autouse fixture does, for the replay tests here."""
    from app.config import get_settings
    from app.marketdata import set_provider
    from tests.test_replay_cli import DESK
    monkeypatch.setattr(get_settings().oms, "pending_monitor_enabled", False)
    input_file = tmp_path / "input.json"
    input_file.write_text((DESK / "input.json").read_text())
    yield input_file
    set_provider(None)


# =========================================================================================
# HOLES
# =========================================================================================

@pytest.mark.xfail(strict=True, reason=(
    "HOLE medium (B-053): a `provider: cassette` spec passes `vet` under `fund-runtime "
    "backtest` (zero-cost, check_spec needs no tape), so physics records a `cassette` "
    "declaration and registers every agent; then every wake is refused `unavailable` (no "
    "tape outside replay). A spec that could never wake told physics a provenance claim "
    "(`cassette`) that no wake ever backed. Fix: `_conduct` (or `vet` with a `replay` flag) "
    "refuses a cassette spec when no Recording is given, before `check_clock`."))
def test_hole_cassette_spec_in_a_backtest_declares_and_registers_then_never_wakes(
        SessionFactory, keys, woke, tmp_path, capsys):
    specs = _write_specs(tmp_path / "specs", _spec("a-pm", "desk-1-pm", 1),
                         {"id": "x-pm", "name": "x", "role": "pm", "pod": 2,
                          "provider": "cassette", "charter": "Replay."})
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 1 and out["ended"] == "refused"
    # Expected after the fix: nothing told to physics.
    assert _events(SessionFactory, EVENT_RUN_MINDS_DECLARED) == 0
    assert _made(SessionFactory) == {}


@pytest.mark.xfail(strict=True, reason=(
    "HOLE low (B-053): a spec whose `tools` names a tool that is not on the published "
    "surface passes `vet`; physics gets the declaration and the agents, then the wake is "
    "refused `unknown_tool` at step 0, every time. Network-free to check (the tool surface "
    "is `mcp_server`'s, static). Fix: `vet` refuses `tools` not a subset of the published "
    "tool names (`unknown_tool:<id>`)."))
def test_hole_unknown_tool_spec_declares_and_registers_then_never_wakes(
        SessionFactory, keys, woke, tmp_path, capsys):
    specs = _write_specs(tmp_path / "specs",
                         _spec("a-pm", "desk-1-pm", 1) | {"tools": ["no_such_tool"]})
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 1 and out["ended"] == "refused"
    assert _events(SessionFactory, EVENT_RUN_MINDS_DECLARED) == 0
    assert _made(SessionFactory) == {}


@pytest.mark.xfail(strict=True, reason=(
    "HOLE low (B-053, same class as the known name_taken gap): a spec naming a pod that "
    "does not exist passes `vet`; the declaration is recorded, then registration fails "
    "(`register_failed:<id>:error`/`500`, the spec named maybe-registered). Needs a read, so "
    "not `vet`'s job; fix: `_conduct` reads "
    "the directory and the pods (GETs, no write) and checks names and pods before "
    "`declare_minds`."))
def test_hole_spec_in_a_missing_pod_is_declared_before_it_is_refused(
        SessionFactory, keys, woke, tmp_path, capsys):
    specs = _write_specs(tmp_path / "specs", _spec("a-pm", "desk-1-pm", 99))
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    # Today: ``provision:register_failed:a-pm:error`` (500 from a real server, see the
    # physics hole below) and ``registered == ["a-pm"]``: the run cannot know nothing was made.
    assert code == 1 and out["ended"] == "refused", out
    assert _events(SessionFactory, EVENT_RUN_MINDS_DECLARED) == 0, out


@pytest.mark.xfail(strict=True, reason=(
    "HOLE low (physics, found on the way): `POST /agents/register` with a `pod_id` that "
    "names no pod is not refused; the FK fails at flush and the request dies 500 (an "
    "unhandled IntegrityError). Any registrar, a management mind's `register_agent` tool "
    "included, can make physics 500 at will, and the Runtime must then name the spec as "
    "maybe-registered. Fix: `app.registry.service.register_agent` checks the pod exists "
    "and raises a RegistryError (the router's 409) or a 404."))
def test_hole_registering_into_a_missing_pod_is_a_500_not_a_refusal(SessionFactory, world):
    app = _app(SessionFactory)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/agents/register", headers={"X-API-Key": world["admin"]},
                   json={"name": "ghost", "role": "pm", "pod_id": 999})
    assert 400 <= r.status_code < 500, r.status_code


# =========================================================================================
# HELD
# =========================================================================================

# --- 2. HALT at every await point --------------------------------------------------------

def test_held_halt_at_the_law_read_contacts_physics_with_no_write(
        SessionFactory, keys, specs, woke, gov, capsys):
    (gov / "HALT").write_text("")
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and out == HALTED | {"registered": [], "run": None}
    # No write was even attempted: physics logged no halt_refused.
    assert _events(SessionFactory, EVENT_HALT_REFUSED) == 0
    assert _events(SessionFactory, EVENT_RUN_MINDS_DECLARED) == 0 and woke == []


def test_held_halt_after_the_clock_check_before_the_declaration(
        SessionFactory, keys, specs, woke, gov, halt_file, capsys):
    """HALT lands after ``check_clock``'s ``GET /clock``: the declaration gets 423."""
    code, out = _halting(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys,
                         "/clock", "after", (gov / "HALT", halt_file))
    assert code == 1 and out == HALTED | {"registered": [], "run": None}
    assert _events(SessionFactory, EVENT_RUN_MINDS_DECLARED) == 0
    assert _made(SessionFactory) == {} and woke == []


def test_held_halt_after_the_directory_read(
        SessionFactory, keys, specs, woke, gov, halt_file, capsys):
    """HALT lands after ``provision``'s ``GET /agents``: its re-read stops registration."""
    code, out = _halting(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys,
                         "/agents", "after", (gov / "HALT", halt_file))
    assert code == 1 and out == HALTED | {"registered": [], "run": None}
    assert _made(SessionFactory) == {} and woke == []
    assert _events(SessionFactory, EVENT_CLOCK_ADVANCED) == 0


def test_held_physics_halt_at_the_first_registration_post(
        SessionFactory, keys, specs, woke, gov, halt_file, capsys):
    """Only physics' file, written as the POST goes out: 423 → ``register_failed:a-pm:423``
    → ``halted``, and nothing registered."""
    code, out = _halting(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys,
                         "/agents/register", "before", (halt_file,))
    assert code == 1 and out == HALTED | {"registered": [], "run": None}
    assert _made(SessionFactory) == {} and woke == []


def test_held_halt_between_provision_and_step_0(
        SessionFactory, keys, specs, woke, gov, halt_file, capsys, monkeypatch):
    """HALT after the last registration and before the conductor's first gate read."""
    real = lockstep.run_backtest

    async def run_backtest(minds, clock, **kw):
        (gov / "HALT").write_text("")
        halt_file.write_text("")
        return await real(minds, clock, **kw)
    monkeypatch.setattr(cli, "run_backtest", run_backtest)
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and (out["ended"], out["reason"]) == ("halted", "halted")
    assert out["registered"] == ["a-pm", "b-pm"] and out["run"]["steps"] == []
    assert woke == [] and _events(SessionFactory, EVENT_CLOCK_ADVANCED) == 0


def test_held_physics_halt_at_a_later_advance(
        SessionFactory, keys, specs, woke, gov, halt_file, capsys, monkeypatch):
    """Step 0 advances; physics halts as step 1's advance goes out: ``halted``, one advance,
    nothing woken after."""
    real = lockstep.wake
    seen: list[str] = []

    async def wake(spec, client, **kw):
        seen.append(spec.id)
        if len(seen) == 4:  # the last wake of step 1
            halt_file.write_text("")
        return await real(spec, client, **kw)
    monkeypatch.setattr(lockstep, "wake", wake)
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "3"], capsys)
    assert code == 1 and (out["ended"], out["reason"]) == ("halted", "halted")
    assert len(out["run"]["steps"]) == 2 and out["run"]["steps"][1]["advanced_to"] is None
    assert _events(SessionFactory, EVENT_CLOCK_ADVANCED) == 1 and len(seen) == 4


def test_held_halt_between_two_minds_via_the_cli(
        SessionFactory, keys, specs, woke, gov, capsys, monkeypatch):
    real = lockstep.wake

    async def wake(spec, client, **kw):
        record = await real(spec, client, **kw)
        if spec.id == "a-pm":
            (gov / "HALT").write_text("")
        return record
    monkeypatch.setattr(lockstep, "wake", wake)
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "2"], capsys)
    assert code == 1 and (out["ended"], out["reason"]) == ("halted", "halted")
    [step] = out["run"]["steps"]
    assert [(w["ended"], w["reason"]) for w in step["wakes"]][1] == ("refused", "halted")
    assert woke == ["a"] and _events(SessionFactory, EVENT_CLOCK_ADVANCED) == 0


# --- 3. disguises --------------------------------------------------------------------------

@pytest.mark.parametrize("reason", [
    "provider_refused:x-pm:halted", "wake_refused:x-pm:cap_null", "wake_refused:halted",
    "wake_refused:x:y:halted", "register_failed:x-pm:4230", "register_failed:x-pm:423:x",
    "register_failed:423", "directory_unreadable:423", "name_taken:halted", "halted ",
    "HALTED", "wrong_agent:halted", "connect_failed:halted", "register_failed:x-pm:error",
    "minds_refused:423", "wake_refused:x-pm:no_metered_key",
])
def test_held_is_halt_refuses_disguises(reason):
    assert cli._is_halt(reason) is False


@pytest.mark.parametrize("reason", ["halted", "wake_refused:a-pm:halted",
                                    "register_failed:a-pm:423"])
def test_held_is_halt_accepts_exactly_provisions_halt_reasons(reason):
    assert cli._is_halt(reason) is True


def test_held_a_spec_id_cannot_carry_a_colon():
    """``_is_halt``'s split relies on it."""
    with pytest.raises(ValueError):
        AgentSpec(id="x:halted", name="n", role="pm", pod=1, provider="scripted",
                  script="read-a", charter="c")


def test_held_a_non_423_declaration_refusal_keeps_its_label(
        SessionFactory, keys, specs, woke, capsys):
    """The clock key declares twice (the second refused): only ``minds_refused:423`` is
    relabelled; a 409 keeps ``minds_refused:409``."""
    app = _app(SessionFactory)
    with TestClient(app):
        assert cli.main(["backtest", "--specs", str(specs), "--steps", "1"],
                        transport=httpx.ASGITransport(app=app)) == 0
        capsys.readouterr()
        code = cli.main(["backtest", "--specs", str(specs), "--steps", "1"],
                        transport=httpx.ASGITransport(app=app))
    out = json.loads(capsys.readouterr()[0])
    assert code == 1 and out["ended"] == "refused"
    assert out["reason"].startswith("minds_refused:") and out["reason"] != "minds_refused:423"


# --- 1/5. vet under any law; no `model` label from a gated spec ---------------------------

COMBOS = [(p, a) for p in ("scripted", "cassette", "metered", "anthropic", "Scripted")
          for a in ("native", "openclaw")]


@pytest.mark.parametrize("provider, adapter", COMBOS)
@pytest.mark.parametrize("cap", [None, 0.0, 5.0])
def test_held_no_spec_vet_passes_is_declared_model(woke, provider, adapter, cap):
    fields = {"script": "read-a"} if provider == "scripted" else {}
    spec = AgentSpec(id="x-pm", name="x", role="pm", pod=1, provider=provider,
                     adapter=adapter, charter="c", **fields)
    if vet([spec], Governance(False, cap)) is None:
        assert mind_kinds([spec]) != ["model"]


@pytest.mark.parametrize("provider, adapter", COMBOS)
def test_held_a_cap_change_between_the_two_reads_changes_no_verdict(woke, provider, adapter):
    """``_conduct`` vets under one law, ``provision`` under its own: under any cap the same
    specs pass or fail together, so only HALT can differ between the two reads."""
    fields = {"script": "read-a"} if provider == "scripted" else {}
    spec = AgentSpec(id="x-pm", name="x", role="pm", pod=1, provider=provider,
                     adapter=adapter, charter="c", **fields)
    verdicts = {vet([spec], Governance(False, cap)) is None for cap in (None, 0.0, 5.0, 1e9)}
    assert len(verdicts) == 1


# --- 6. replay ----------------------------------------------------------------------------

def test_held_halt_between_two_minds_mid_replay_ends_halted(tmp_path, monkeypatch, capsys,
                                                           desk_env):
    from tests.test_replay_cli import Desk, _record, _replay
    input_file = desk_env
    _, _, path = _record(tmp_path, input_file, monkeypatch, capsys)
    fresh = Desk(11)
    gov_dir = tmp_path / "governance"
    real = lockstep.wake
    seen: list[str] = []

    async def wake(spec, client, **kw):
        record = await real(spec, client, **kw)
        seen.append(spec.id)
        if len(seen) == 3:  # the first mind of step 1 woke; the Human halts
            (gov_dir / "HALT").write_text("")
        return record
    monkeypatch.setattr(lockstep, "wake", wake)
    code, out, _ = _replay(fresh, path, input_file, monkeypatch, capsys)
    assert code == 1 and (out["ended"], out["reason"]) == ("halted", "halted")
    assert len(out["run"]["steps"]) == 2 and out["run"]["steps"][1]["advanced_to"] is None
    with fresh.Sessions() as s:
        assert len(list(s.execute(select(Event).where(Event.type == EVENT_CLOCK_ADVANCED))
                        .scalars())) == 1


def test_held_a_tape_cannot_fake_a_halt(tmp_path, monkeypatch, capsys, desk_env):
    """A recorded wake rewritten to ``halted`` in a canonical cassette: the replay's wake
    ends as the mind really does, so the run diverges; it never reads ``halted``."""
    from tests.test_replay_cli import Desk, _record, _replay
    input_file = desk_env
    _, out, _ = _record(tmp_path, input_file, monkeypatch, capsys)
    out["run"]["steps"][0]["wakes"][0]["ended"] = "halted"
    out["run"]["steps"][0]["wakes"][0]["reason"] = "halted"
    forged = tmp_path / "forged.cassette.json"
    cassette.write(forged, out)
    code, replayed, _ = _replay(Desk(11), forged, input_file, monkeypatch, capsys)
    assert code == 1 and replayed["ended"] == "diverged"
    assert replayed["reason"].startswith("diverged:") and replayed["reason"].endswith(":ended")
