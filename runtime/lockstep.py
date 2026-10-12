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
colleague (red-team 0015 H1). After an early end the clock is never advanced
again. If an advance fails, physics is asked where the clock is, and the step
records that (it may have moved before the failure, H3).

Before step 0 the conductor checks what it is handed, not what it is told: the
clock key's ``/me`` must be the ``runtime`` role, ``/clock`` must say
``backtest``, spec ids must be unique, every mind's key must be its spec's role
and pod, and no App agent may be handed in twice (H2); ``steps`` and
``days_per_step`` must be plain ints in range. Every act goes over HTTP; physics
decides what is allowed.

The record is returned, not stored: R-4 writes it to a cassette. Provisioning
minds from their specs (binding the spec's name to the App agent) is R-3b-2;
until then the caller hands in each mind's client.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mcp_server.client import FundAPIError, FundClient
from runtime.gate import decide_batch
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

    try:
        me = await clock.get("/me")
        now = await clock.get("/clock")
    except FundAPIError as exc:
        return RunRecord("refused", f"clock_unreadable:{exc.status_code}", label)
    if not isinstance(me, dict) or me.get("role") != "runtime":
        return RunRecord("refused", "clock_identity", label)
    if not isinstance(now, dict) or now.get("mode") != "backtest":
        return RunRecord("refused", "not_backtest", label)
    # Red-team 0015 H2: one App agent is one mind. Every key is read before step 0;
    # a key that is not its spec's agent, or an agent handed in twice, refuses the run.
    agents: set[int] = set()
    for mind in ordered:
        try:
            who = await mind.client.get("/me")
        except FundAPIError as exc:
            return RunRecord("refused", f"mind_unreadable:{mind.spec.id}:{exc.status_code}", label)
        if not isinstance(who, dict) or (who.get("role"), who.get("pod_id")) != (
                mind.spec.role, mind.spec.pod):
            return RunRecord("refused", f"identity_mismatch:{mind.spec.id}", label)
        if who.get("id") in agents or type(who.get("id")) is not int:
            return RunRecord("refused", f"duplicate_agent:{mind.spec.id}", label)
        agents.add(who["id"])

    done: list[StepRecord] = []
    retired: list[str] = []

    def end(ended: str, reason: str | None = None) -> RunRecord:
        return RunRecord(ended, reason or ended, label, tuple(done), tuple(retired))

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
            # so the record says what the ledger says.
            done.append(StepRecord(step, at, tuple(wakes), await _moved_from(clock, at)))
            return end("error", f"advance_failed:{exc.status_code}")
        done.append(StepRecord(step, at, tuple(wakes), _now_of(moved)))
        if done[-1].advanced_to is None:  # it moved, but the record cannot say where
            return end("error", "clock_malformed")
    return end("completed")


async def _key_dead(client: FundClient) -> bool:
    """True only if physics answers 401 for this key: deactivated, not unreachable."""
    try:
        await client.get("/me")
    except FundAPIError as exc:
        return exc.status_code == 401
    return False


async def _moved_from(clock: FundClient, at: str) -> str | None:
    """Where the clock is after a failed advance, if it moved off ``at``; else ``None``.
    If physics cannot be asked either, ``None``: the record cannot know (the reason
    still names the failure)."""
    try:
        now = _now_of(await clock.get("/clock"))
    except FundAPIError:
        return None
    return now if now is not None and now != at else None


def _now_of(answer: Any) -> str | None:
    """The ``now`` of a ``/clock`` or advance answer; ``None`` if it has none
    (audit c24 NOTE 2: a malformed answer ends the run in a record, not a raise)."""
    now = answer.get("now") if isinstance(answer, dict) else None
    return now if type(now) is str else None
