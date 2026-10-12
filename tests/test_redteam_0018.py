"""Red-team pass 0018 — R-4b-1 replay: ``cassette.read``, ``runtime.replay``, ``build_provider(spec,
tape)``, ``run_backtest(replay=)`` (ADR-038, cycle 32).

The attacker is whoever hands the conductor a cassette (an untrusted file, or an in-process
caller building a ``Recording``/``Tape``), and the world a replay runs in. The aim: make a replay
finish ``completed`` when it is not the recorded run, make it act in the world in ways the
recording never did, make the name ``cassette`` run something other than a tape, or hang the
reader.

HOLES are plain failing tests (none is left for the Human): each passes once the Builder fixes
it. HELD guards are plain tests that pass: attacks that failed and must keep failing.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import MappingProxyType

import pytest
from sqlalchemy import select

from app.db.models import Agent, AgentStatus, Event
from app.ledger.events import EVENT_CLOCK_ADVANCED
from app.registry.service import deactivate_agent
from runtime import cassette, scripted
from runtime.cassette import CassetteError
from runtime.lockstep import record_json
from runtime.native import Exchange, WakeRecord
from runtime.providers import CompletionRequest, CompletionResponse, Message, ToolCall
from runtime.registry import ProviderRefused, build_provider
from runtime.replay import (
    CassetteProvider,
    Recording,
    RecordingError,
    ReplayMiss,
    Tape,
    Turn,
    as_cassette,
)
from tests.test_runtime_lockstep import (  # noqa: F401 - fixtures
    _spec,
    conduct,
    gov,
    live_afterwards,
    world,
)


# --- rig -------------------------------------------------------------------------------

def _hold(request: CompletionRequest) -> CompletionResponse:
    """A mind that reads nothing from the world: its requests do not depend on the date."""
    return CompletionResponse(content="hold")


def _two_messages(request: CompletionRequest) -> CompletionResponse:
    """Turn 0 asks for two writes in one batch; turn 1 is done."""
    if any(m.role == "assistant" for m in request.messages):
        return CompletionResponse(content="done")
    return CompletionResponse(tool_calls=[
        ToolCall(id=f"0:{i}", name="send_message", arguments={"to": "pod:1", "body": f"m{i}"})
        for i in range(2)])


@pytest.fixture
def rt_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    more = {"rt-hold": _hold, "rt-two-messages": _two_messages}
    monkeypatch.setattr(scripted, "SCRIPTS", MappingProxyType(dict(scripted.SCRIPTS) | more))


def _record_to_recording(run, path: Path) -> Recording:
    cassette.write(path, {"run": record_json(run)})
    return Recording.load(path)


def _events(SessionFactory) -> list[tuple[str, dict]]:
    with SessionFactory() as s:
        return [(e.type, e.payload_json)
                for e in s.execute(select(Event).order_by(Event.id)).scalars()]


def _cassette_spec_of(spec):
    return as_cassette(spec)


# =====================================================================================
# HOLES
# =====================================================================================

# HOLE rt0018-1 (medium): a replay's time frame is never compared with the recording's.
# The v1 cassette already holds every step's ``at`` and ``advanced_to``, but ``Recording``
# drops them, and ``run_backtest(replay=)`` checks only the ids and the step count. A replay
# started at another date, or with another ``days_per_step``, of minds that do not happen to
# read a dated value finishes ``completed`` -- the record says "the recorded run replayed" while
# the clock lived a different run (here 2 x 30 days instead of 2 x 1, starting 2 days late).
def test_hole_a_replay_on_another_calendar_does_not_finish_completed(
        SessionFactory, world, rt_scripts, tmp_path):
    spec = _spec("a-pm", 1, "rt-hold")
    recorded = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=2,
                       days_per_step=1)
    assert recorded.ended == "completed"
    rec = _record_to_recording(recorded, tmp_path / "r.cassette.json")
    # The same database, the clock now 2 days on; the replay steps 30 days at a time.
    replay = conduct(SessionFactory, [(_cassette_spec_of(spec), world["pm"][1])], world["clock"],
                     steps=2, days_per_step=30, replay=rec)
    assert [st.at for st in replay.steps] != [st.at for st in recorded.steps]  # the scenario
    assert [st.advanced_to for st in replay.steps] != [st.advanced_to for st in recorded.steps]
    assert replay.ended != "completed", (
        "a replay whose steps start and land on other dates than the recording's finished "
        f"'completed': recorded {[s.at for s in recorded.steps]}, replayed "
        f"{[s.at for s in replay.steps]}")


# HOLE rt0018-2 (medium): a replay acts in the world where the recording did not. The recorded
# wake ended ``tool_budget`` (its batch of two writes was over the budget of 1, so nothing ran).
# ``max_tool_calls`` is not in the v1 cassette; the replay, under the default budget, *executes*
# the recorded batch (two messages land in the ledger) and only then misses on the next turn and
# ends ``diverged``. The divergence is caught, but after the world was changed by acts the
# recorded run never performed. (The Tape knows the wake ended ``tool_budget`` after this turn.)
def test_hole_a_replay_does_not_execute_a_batch_the_recording_never_ran(
        SessionFactory, world, rt_scripts, tmp_path):
    spec = _spec("a-pm", 1, "rt-two-messages")
    recorded = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=1,
                       max_tool_calls=1)
    (w,) = recorded.steps[0].wakes
    assert (recorded.ended, w.ended, w.tool_calls) == ("completed", "tool_budget", 0)
    rec = _record_to_recording(recorded, tmp_path / "r.cassette.json")
    before = [e for e in _events(SessionFactory) if e[0] != EVENT_CLOCK_ADVANCED]
    replay = conduct(SessionFactory, [(_cassette_spec_of(spec), world["pm"][1])], world["clock"],
                     steps=1, replay=rec)  # max_tool_calls: the default, 64
    after = [e for e in _events(SessionFactory) if e[0] != EVENT_CLOCK_ADVANCED]
    assert replay.ended == "diverged"  # caught -- but look at the ledger
    assert after == before, (
        f"the replay wrote {len(after) - len(before)} events the recorded run never wrote: "
        f"{[t for t, _ in after[len(before):]]}")


# HOLE rt0018-3 (low): a forged cassette that drops ``retired`` replays a retirement as
# ``completed``. ``Recording.from_outcome`` refuses a run with ``retired`` set, but not a
# "completed, nobody retired" run whose wake ended ``refused`` -- something an honest completed
# run can only hold if a mind was retired. ``divergence`` then finds the replayed refusal equal
# to the recorded one (no turns, same end, 0 calls), the conductor retires the mind and the run
# finishes ``completed`` with ``retired`` non-empty: ADR-038 says any refusal but HALT diverges.
def test_hole_a_recording_with_a_refused_wake_in_a_completed_run_is_refused():
    wake = {"spec_id": "a-pm", "ended": "refused", "reason": "no_identity", "tool_calls": 0,
            "tool_failures": 0, "transcript": [], "exchanges": []}
    forged = {"run": {"ended": "completed", "retired": [], "retired_at": [], "steps": [
        {"step": 0, "at": "x", "wakes": [wake], "advanced_to": "y"}]}}
    with pytest.raises(RecordingError):
        Recording.from_outcome(forged)


def test_hole_a_forged_refusal_lets_a_replay_with_a_dead_key_finish_completed(
        SessionFactory, world, rt_scripts):
    wake = {"spec_id": "a-pm", "ended": "refused", "reason": "no_identity", "tool_calls": 0,
            "tool_failures": 0, "transcript": [], "exchanges": []}
    rec = Recording.from_outcome({"run": {"ended": "completed", "retired": [], "steps": [
        {"step": 0, "at": "x", "wakes": [wake], "advanced_to": "y"}, {"step": 1, "wakes": []}]}})
    spec = _cassette_spec_of(_spec("a-pm", 1, "rt-hold"))
    # The key passes the conductor's pre-flight /me, then dies before the first wake: patch
    # nothing in the conductor, just kill the agent between the pre-flight and step 0.
    from runtime import lockstep
    real_wake = lockstep.wake

    async def kill_then_wake(spec_, client, **kw):
        with SessionFactory() as s:
            pm = s.scalar(select(Agent).where(Agent.name == "pm-1"))
            if pm.status == AgentStatus.active:
                deactivate_agent(s, agent_id=pm.id)
                s.commit()
        return await real_wake(spec_, client, **kw)
    lockstep.wake = kill_then_wake
    try:
        run = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=2,
                      replay=rec)
    finally:
        lockstep.wake = real_wake
    assert run.steps[0].wakes[0].reason == "no_identity"  # the scenario
    assert run.ended != "completed", (
        f"replay retired {run.retired} and finished 'completed' from a recording that "
        "retired nobody")


class _AnyHash(str):
    """A "hash" equal to every hash."""
    def __eq__(self, other):  # noqa: D105
        return True

    def __ne__(self, other):  # noqa: D105
        return False

    __hash__ = str.__hash__


class _CodeReply:
    """Not a reply: code that runs when the cassette mind 'copies' it."""
    ran = False

    def model_copy(self, **kw):
        _CodeReply.ran = True  # here: any I/O, any spend, any network
        return CompletionResponse(content="forged")


# HOLE rt0018-4 (medium): ``type(tape) is Tape`` is the registry's whole check that the
# ``cassette`` mind is built from *data*; the tape's contents are never validated. A ``Tape`` is
# a plain frozen dataclass: its ``turns`` may hold any object. A turn whose ``request_sha256``
# is a ``str`` subclass equal to everything makes a world-blind mind (it answers any request,
# and ``Recording.divergence`` sees no divergence either), and a ``response`` that is an object
# with a ``model_copy`` method runs arbitrary code inside ``CassetteProvider.complete`` -- the
# "no provider object" law (ADR-038: "data ..., never a provider") defeated one level down.
def test_hole_a_tape_whose_turns_are_not_data_does_not_build_or_does_not_answer():
    spec = _cassette_spec_of(_spec("a-pm", 1, "rt-hold"))
    tape = Tape((Turn(_AnyHash("0" * 64), _CodeReply(), ()),), "done", 0)  # type: ignore[arg-type]
    _CodeReply.ran = False
    try:
        provider = build_provider(spec, tape)
    except ProviderRefused:
        return  # fixed by refusing the tape
    request = CompletionRequest(messages=[Message(role="user", content="anything at all")])
    with pytest.raises(ReplayMiss):
        provider.complete(request)
    assert not _CodeReply.ran, "code inside a Tape ran inside the cassette mind"


def test_hole_a_recording_built_by_hand_does_not_hide_a_world_divergence():
    turn = Turn(_AnyHash("0" * 64), CompletionResponse(content="hold"), ())
    try:
        rec = Recording(1, {(0, "a-pm"): Tape((turn,), "done", 0)})
    except (RecordingError, TypeError, ValueError):
        return  # fixed by validating what a Recording holds
    replayed = WakeRecord("a-pm", "done", "done", 0,
                          (Message(role="user", content="another world"),
                           Message(role="assistant", content="hold")), 0,
                          (Exchange(0, "f" * 64, None),))
    assert rec.divergence(0, replayed) is not None


# HOLE rt0018-5 (low): ``seq`` is compared with ``==`` to ``range``, so ``true`` / ``1.0`` pass as
# ``1``. The reader's canonical check keeps the file canonical JSON, not well-typed; the
# Recording claims "exchanges are numbered 0..n-1" (ints), the way ``tool_calls`` (bool refused)
# and ``ended`` are checked with ``type(...) is``.
@pytest.mark.parametrize("seq", [True, 1.0])
def test_hole_an_exchange_seq_that_is_not_an_int_is_refused(seq):
    sha = "a" * 64
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    transcript = [{"role": "system", "content": "Work."}, {"role": "user", "content": "{}"},
                  {"role": "assistant", "content": "",
                   "tool_calls": [{"id": "c", "name": "get_clock", "arguments": {}}]},
                  {"role": "tool", "content": "{}", "tool_call_id": "c"},
                  {"role": "assistant", "content": "done"}]
    transcript = [Message.model_validate(m).model_dump(mode="json") for m in transcript]
    wake = {"spec_id": "a-pm", "ended": "done", "reason": "done", "tool_calls": 1,
            "tool_failures": 0, "transcript": transcript,
            "exchanges": [{"seq": 0, "request_sha256": sha, "usage": usage},
                          {"seq": seq, "request_sha256": sha, "usage": usage}]}
    with pytest.raises(RecordingError):
        Recording.from_outcome({"run": {"ended": "completed", "retired": [], "steps": [
            {"step": 0, "wakes": [wake]}]}})


# =====================================================================================
# HELD
# =====================================================================================

def _doc(outcome_text: str) -> str:
    return ('{"cassette_version":1,"hash_format":"%s","outcome":%s,"redactions":0}'
            % (cassette.HASH_FORMAT, outcome_text))


def _raw(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "x.cassette.json"
    p.write_bytes(text.encode("ascii"))
    return p


@pytest.mark.parametrize("label,outcome_text", [
    ("dup key deep", '{"run":{"a":[{"b":1,"b":1}]}}'),
    ("huge int", '{"n":' + "9" * 5000 + "}"),
    ("float not repr", '{"n":1.10}'),
    ("float exponent", '{"n":1e5}'),
    ("escaped ascii", '{"n":"\\u0041"}'),
    ("uppercase escape", '{"n":"\\u00E9"}'),
    ("escaped slash", '{"n":"a\\/b"}'),
    ("whitespace", '{"n": 1}'),
])
def test_held_the_reader_refuses_non_canonical_bodies(tmp_path, label, outcome_text):
    with pytest.raises(CassetteError):
        cassette.read(_raw(tmp_path, _doc(outcome_text)))


def test_held_a_lone_surrogate_is_canonical_but_harmless(tmp_path):
    """``\\ud800`` round-trips through ``ensure_ascii`` unchanged, so the reader accepts it; the
    request hash and the writer both serialise it with ``ensure_ascii=True``."""
    got, _ = cassette.read(_raw(tmp_path, _doc('{"n":"\\ud800"}')))
    assert got == {"n": "\ud800"}
    assert len(cassette.request_sha256(CompletionRequest(
        messages=[Message(role="user", content=got["n"])]))) == 64


def test_held_a_symlink_swapped_in_and_a_device_are_refused(tmp_path):
    real = tmp_path / "real.cassette.json"
    cassette.write(real, {"run": None})
    link = tmp_path / "l.cassette.json"
    link.symlink_to(real)
    with pytest.raises(CassetteError):
        cassette.read(link)
    with pytest.raises(CassetteError):
        cassette.read(Path("/dev/null"))


def test_held_a_tape_reply_with_repeated_call_ids_is_rechecked_by_the_adapter():
    """``CassetteProvider`` returns the reply; ``native.wake`` re-checks it (``bad_reply``) the
    way it checks a live one -- checked here at the provider: the copy is a real
    ``CompletionResponse`` with the repeated ids, which the adapter's id check refuses."""
    reply = CompletionResponse(tool_calls=[ToolCall(id="x", name="get_clock"),
                                           ToolCall(id="x", name="get_clock")])
    req = CompletionRequest(messages=[Message(role="user", content="q")])
    got = CassetteProvider(Tape((Turn(cassette.request_sha256(req), reply, ()),))).complete(req)
    ids = [c.id for c in got.tool_calls]
    assert type(got) is CompletionResponse and len(set(ids)) != len(ids)


def test_held_the_returned_reply_shares_nothing_with_the_tape():
    reply = CompletionResponse(tool_calls=[ToolCall(id="x", name="place_order",
                                                    arguments={"nested": {"qty": 1}})])
    req = CompletionRequest(messages=[Message(role="user", content="q")])
    tape = Tape((Turn(cassette.request_sha256(req), reply, ()),))
    got = CassetteProvider(tape).complete(req)
    got.tool_calls[0].arguments["nested"]["qty"] = 10**9
    got.tool_calls.append(ToolCall(id="y", name="advance_clock"))
    assert tape.turns[0].response.tool_calls == reply.tool_calls
    assert tape.turns[0].response.tool_calls[0].arguments == {"nested": {"qty": 1}}


def test_held_a_scripted_spec_with_a_tape_and_a_cassette_with_a_lookalike_are_refused():
    with pytest.raises(ProviderRefused):
        build_provider(_spec("a-pm", 1, "rt-hold"), Tape())
    for fake in (Tape, (), [], {"turns": ()}, CassetteProvider(Tape())):
        with pytest.raises(ProviderRefused):
            build_provider(_cassette_spec_of(_spec("a-pm", 1, "read-a")), fake)


def test_held_a_changed_workflow_input_diverges(SessionFactory, world, rt_scripts, tmp_path):
    spec = _spec("a-pm", 1, "rt-hold")
    recorded = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=1,
                       workflow_input={"universe": ["AAPL"]})
    rec = _record_to_recording(recorded, tmp_path / "r.cassette.json")
    replay = conduct(SessionFactory, [(_cassette_spec_of(spec), world["pm"][1])], world["clock"],
                     steps=1, workflow_input={"universe": ["MSFT"]}, replay=rec)
    assert replay.ended == "diverged" and replay.reason.endswith(":0:world"), replay.reason
    assert replay.steps[-1].advanced_to is None


def test_held_a_changed_charter_diverges(SessionFactory, world, rt_scripts, tmp_path):
    spec = _spec("a-pm", 1, "rt-hold")
    recorded = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=1)
    rec = _record_to_recording(recorded, tmp_path / "r.cassette.json")
    other = _cassette_spec_of(spec).model_copy(update={"charter": "Do something else."})
    replay = conduct(SessionFactory, [(other, world["pm"][1])], world["clock"], steps=1,
                     replay=rec)
    assert replay.ended == "diverged", replay.reason


def test_held_a_replay_reports_zero_usage_and_a_smaller_budget_diverges(
        SessionFactory, world, rt_scripts, tmp_path):
    spec = _spec("a-pm", 1, "rt-two-messages")
    recorded = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=1)
    assert recorded.steps[0].wakes[0].tool_calls == 2
    rec = _record_to_recording(recorded, tmp_path / "r.cassette.json")
    replay = conduct(SessionFactory, [(_cassette_spec_of(spec), world["pm"][1])], world["clock"],
                     steps=1, max_tool_calls=1, replay=rec)
    assert replay.ended == "diverged" and replay.reason.endswith(":ended"), replay.reason
    assert all(e.usage is None or e.usage.cost_usd == 0 for w in replay.steps[0].wakes
               for e in w.exchanges)


def test_held_halt_before_a_replay_moves_nothing(SessionFactory, world, rt_scripts, tmp_path, gov):
    spec = _spec("a-pm", 1, "rt-hold")
    recorded = conduct(SessionFactory, [(spec, world["pm"][1])], world["clock"], steps=1)
    rec = _record_to_recording(recorded, tmp_path / "r.cassette.json")
    before = _events(SessionFactory)
    (gov / "HALT").write_text("stop")
    run = conduct(SessionFactory, [(_cassette_spec_of(spec), world["pm"][1])], world["clock"],
                  steps=1, replay=rec)
    assert run.ended == "halted" and _events(SessionFactory) == before
    assert json.dumps(record_json(run))  # serialisable


# A FIFO path: a blocking open would stall the conductor before the ``S_ISREG`` check. On this
# platform (Darwin, the Mac mini) the open returns and the file is refused; the guard keeps it so
# (on Linux an ``O_RDONLY`` open of a FIFO blocks: ``O_NONBLOCK`` would make it portable).
def test_held_reading_a_fifo_refuses_instead_of_hanging(tmp_path):
    fifo = tmp_path / "fifo.cassette.json"
    os.mkfifo(fifo)
    outcome: list[object] = []

    def go():
        try:
            cassette.read(fifo)
            outcome.append("read")
        except CassetteError as exc:
            outcome.append(exc)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(2.0)
    hung = t.is_alive()
    if hung:  # release the reader so the test process does not keep a blocked thread
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        t.join(2.0)
    assert not hung, "cassette.read blocked on a FIFO for 2s instead of refusing it"
    assert outcome and isinstance(outcome[0], CassetteError)
