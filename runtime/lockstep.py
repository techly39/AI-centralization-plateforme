"""The lockstep conductor: a backtest lived one step at a time (ADR-032 (5), R-3b).

For every step:

1. **HALT** is read; under HALT nothing more happens (no wake, no advance).
2. Every mind wakes **once, one at a time, in spec-id order** through
   :func:`runtime.native.wake` — which runs its own gates (cap, HALT before every
   turn and call, identity, tool budget).
3. HALT is read again, then the clock moves one step with the **runtime
   identity's key** (ADR-033): the only hand on a backtest's time that no mind holds.

The run ends ``completed`` after ``steps`` steps, or early:

* ``halted`` — HALT before a step, inside a wake, or before an advance;
* ``refused`` — a wake was refused (a mind the run names did not wake: the world
  must not move on without it), or the run itself was refused before step 0;
* ``error`` — the clock would not advance, or its answer had no ``now``.

A mind that crashes (``error``) or spends its tool budget is data, recorded in
its step, and the run goes on. So is a mind whose agent was **deactivated inside
the world** (its key gets 401): it is *retired* — recorded, never woken again —
and the run goes on, so no firm agent can stop the world's time by firing a
colleague (red-team 0015 H1). If every mind is retired, the world still lives
its remaining steps with no one awake: the clock is the Runtime's, not the
minds' (audit c24 NOTE 4). Any other refused wake — ``no_identity`` while the
key still answers, say — still ends the run. After an early end the clock is never advanced
again. If an advance fails, physics is asked where the clock is, and the step
records that (it may have moved before the failure, H3).

Before step 0 the conductor checks what it is handed, not what it is told: the
clock key's ``/me`` must be the ``runtime`` role, ``/clock`` must say
``backtest``, spec ids must be unique, every mind's key must be its spec's name,
role and pod, and no App agent may be handed in twice (H2); ``steps`` and
``days_per_step`` must be plain ints in range. Every act goes over HTTP; physics
decides what is allowed.

The record is returned, not stored: R-4 writes it to a cassette. The minds come
from :func:`runtime.provision.provision`, which registers each App agent from its
spec (ADR-032 (n)); a caller may still hand in clients it made, and the name
check holds them to their specs.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from mcp_server.client import FundAPIError, FundClient
from runtime.gate import ZERO_COST_ADAPTERS, ZERO_COST_PROVIDERS, decide_batch
from runtime.native import DEFAULT_MAX_TOOL_CALLS, WakeRecord, wake
from runtime.spec import AgentSpec

#: The longest run one call may ask for, and the longest step: a decade of days.
MAX_STEPS = 3660
MAX_DAYS_PER_STEP = 366


@dataclass(frozen=True)
class Mind:
    """A spec and the client that acts as its App agent."""

    spec: AgentSpec
    client: FundClient


@dataclass(frozen=True)
class StepRecord:
    step: int
    #: The world's now when the step began (``/clock``), ISO-8601.
    at: str
    wakes: tuple[WakeRecord, ...]
    #: The world's now after the advance; ``None`` if the step ended the run first.
    advanced_to: str | None


@dataclass(frozen=True)
class RunRecord:
    #: ``completed`` | ``halted`` | ``refused`` | ``error``
    ended: str
    #: Why, as a short code: ``ended`` itself, or e.g. ``wake_refused:pm-a:cap_null``.
    reason: str
    #: The providers that woke, sorted and joined: ``scripted`` for a scripted run.
    minds: str
    steps: tuple[StepRecord, ...] = ()
    #: Spec ids whose agent was deactivated inside the world; they woke no more.
    retired: tuple[str, ...] = ()
    #: The step each of ``retired`` was retired at, in the same order (audit c24 NOTE 5).
    retired_at: tuple[int, ...] = ()


async def run_backtest(
    minds: Sequence[Mind],
    clock: FundClient,
    *,
    steps: int,
    days_per_step: int = 1,
    workflow_input: Mapping[str, Any] | None = None,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> RunRecord:
    """Live ``steps`` steps of a backtest with ``minds``, the clock in the Runtime's hand."""
    for value, top in ((steps, MAX_STEPS), (days_per_step, MAX_DAYS_PER_STEP)):
        if type(value) is not int or not 0 <= value <= top:
            raise ValueError(f"steps and days_per_step are plain ints in [0, {top}]")
    if days_per_step == 0:
        raise ValueError("days_per_step is at least 1: a step that does not move time is no step")
    ordered = sorted(minds, key=lambda m: m.spec.id)
    label = "+".join(sorted({m.spec.provider for m in ordered}))
    if len({m.spec.id for m in ordered}) != len(ordered):
        return RunRecord("refused", "duplicate_spec_id", label)
    # The input is copied once, deeply, here: every wake of the run sees the same
    # document, whoever else holds a nested value (red-team 0015 H4).
    step_input = copy.deepcopy(dict(workflow_input or {}))

    refusal = await check_clock(clock)
    if refusal is not None:
        return RunRecord("refused", refusal, label)
    # Red-team 0015 H2: one App agent is one mind. Every key is read before step 0;
    # a key that is not its spec's agent, or an agent handed in twice, refuses the run.
    agents: set[int] = set()
    for mind in ordered:
        try:
            who = await mind.client.get("/me")
        except FundAPIError as exc:
            return RunRecord("refused", f"mind_unreadable:{mind.spec.id}:{exc.status_code}", label)
        if not isinstance(who, dict) or (who.get("name"), who.get("role"), who.get("pod_id")) != (
                mind.spec.name, mind.spec.role, mind.spec.pod):
            return RunRecord("refused", f"identity_mismatch:{mind.spec.id}", label)
        if type(who.get("id")) is not int:
            return RunRecord("refused", f"identity_mismatch:{mind.spec.id}", label)
        if who["id"] in agents:
            return RunRecord("refused", f"duplicate_agent:{mind.spec.id}", label)
        agents.add(who["id"])

    done: list[StepRecord] = []
    retired: list[str] = []
    retired_at: list[int] = []

    def end(ended: str, reason: str | None = None) -> RunRecord:
        return RunRecord(ended, reason or ended, label, tuple(done), tuple(retired),
                         tuple(retired_at))

    for step in range(steps):
        if not decide_batch().allowed:
            return end("halted")
        try:
            at = _now_of(await clock.get("/clock"))
        except FundAPIError as exc:
            return end("error", f"clock_unreadable:{exc.status_code}")
        if at is None:
            return end("error", "clock_malformed")
        wakes: list[WakeRecord] = []
        stop: tuple[str, str] | None = None
        for mind in ordered:
            if mind.spec.id in retired:
                continue
            record = await wake(mind.spec, mind.client, workflow_input=step_input,
                                max_tool_calls=max_tool_calls)
            wakes.append(record)
            if record.ended == "halted":
                stop = ("halted", "halted")
            elif record.ended == "refused":
                if record.reason == "no_identity" and await _key_dead(mind.client):
                    # Red-team 0015 H1: the agent was deactivated by an act inside the
                    # world (e.g. management firing it). That is data, not a reason for
                    # the world's time to stop: the mind is retired and the run goes on.
                    retired.append(mind.spec.id)
                    retired_at.append(step)
                    continue
                stop = ("refused", f"wake_refused:{mind.spec.id}:{record.reason}")
            if stop:
                break
        if stop is None and not decide_batch().allowed:
            stop = ("halted", "halted")
        if stop is not None:
            done.append(StepRecord(step, at, tuple(wakes), None))
            return end(*stop)
        try:
            moved = await clock.post("/clock/advance", {"days": days_per_step})
        except FundAPIError as exc:
            # Red-team 0015 H3: physics may have committed the advance and failed
            # after it (the sweep, the connection). Ask physics where the clock is,
            # so the record says what the ledger says; if physics cannot say either,
            # the reason says the record does not know (audit c24 WARN 1).
            known, now = await _moved_from(clock, at)
            done.append(StepRecord(step, at, tuple(wakes), now))
            return end("error", f"advance_failed:{exc.status_code}"
                       + ("" if known else ":clock_unknown"))
        done.append(StepRecord(step, at, tuple(wakes), _now_of(moved)))
        if done[-1].advanced_to is None:  # it moved, but the record cannot say where
            return end("error", "clock_malformed")
    return end("completed")


async def check_clock(clock: FundClient) -> str | None:
    """Why ``clock`` cannot conduct a backtest, or ``None`` if it can: its key's
    ``/me`` must be the ``runtime`` role and ``/clock`` must say ``backtest``.
    A caller about to register agents asks first (``fund-runtime backtest``):
    a live database must not gain a run's agents."""
    try:
        me = await clock.get("/me")
        now = await clock.get("/clock")
    except FundAPIError as exc:
        return f"clock_unreadable:{exc.status_code}"
    if not isinstance(me, dict) or me.get("role") != "runtime":
        return "clock_identity"
    if not isinstance(now, dict) or now.get("mode") != "backtest":
        return "not_backtest"
    return None


#: Physics' kind for each zero-cost provider (``app.run_clock.MIND_KINDS``; a test
#: pins the copy). Any other mind is a model answering now: ``model``.
_KIND = {"scripted": "scripted", "cassette": "cassette"}


def mind_kinds(specs: Sequence[AgentSpec]) -> list[str]:
    """The kinds physics records for minds made from ``specs``, sorted. A mind is
    ``scripted`` or ``cassette`` only if its provider *and* its adapter are
    zero-cost (the gate's own sets): ``scripted`` through ``openclaw`` runs
    OpenClaw's model (audit c28 WARN 1). Anything else is declared ``model``."""
    def kind(s: AgentSpec) -> str:
        if s.provider in ZERO_COST_PROVIDERS and s.adapter in ZERO_COST_ADAPTERS:
            return _KIND.get(s.provider, "model")
        return "model"
    return sorted({kind(s) for s in specs})


async def declare_minds(clock: FundClient, specs: Sequence[AgentSpec]) -> str | None:
    """Tell physics what drives this run's minds (``POST /run/minds``, ADR-032
    (p)); ``None`` if it took the declaration, else why not. Physics takes it only
    before the clock moves and before any firm agent acts, so a caller declares
    before it registers anyone."""
    try:
        await clock.post("/run/minds", {"minds": mind_kinds(specs)})
    except FundAPIError as exc:
        return f"minds_refused:{exc.status_code}"
    return None


def record_json(record: Any) -> Any:
    """A record as plain JSON values: dataclasses → objects, tuples → arrays,
    transcript messages → their JSON dump. A transcript keeps tool results as
    they came, so it may hold a key a tool returned (``register_agent``): whoever
    prints or stores it redacts (``runtime.cassette.redact``)."""
    if dataclasses.is_dataclass(record) and not isinstance(record, type):
        return {f.name: record_json(getattr(record, f.name)) for f in dataclasses.fields(record)}
    if isinstance(record, BaseModel):
        return record.model_dump(mode="json")
    if isinstance(record, (list, tuple)):
        return [record_json(x) for x in record]
    return record


async def _key_dead(client: FundClient) -> bool:
    """True only if physics answers 401 for this key: deactivated, not unreachable."""
    try:
        await client.get("/me")
    except FundAPIError as exc:
        return exc.status_code == 401
    return False


async def _moved_from(clock: FundClient, at: str) -> tuple[bool, str | None]:
    """``(known, now)`` after a failed advance: ``now`` is where the clock is if it
    moved off ``at``, else ``None``. ``known`` is false if physics could not be
    asked, or answered without a ``now``: then ``None`` means "cannot say"."""
    try:
        now = _now_of(await clock.get("/clock"))
    except FundAPIError:
        return False, None
    if now is None:
        return False, None
    return True, (now if now != at else None)


def _now_of(answer: Any) -> str | None:
    """The ``now`` of a ``/clock`` or advance answer; ``None`` if it has none
    (audit c24 NOTE 2: a malformed answer ends the run in a record, not a raise)."""
    now = answer.get("now") if isinstance(answer, dict) else None
    return now if type(now) is str else None
