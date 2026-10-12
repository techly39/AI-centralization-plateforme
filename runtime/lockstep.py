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
* ``error`` — the clock would not advance.

A mind that crashes (``error``) or spends its tool budget is data, recorded in
its step, and the run goes on. After an early end the clock is never advanced
again, so the ledger shows exactly how far the run got.

Before step 0 the conductor checks what it is handed, not what it is told: the
clock key's ``/me`` must be the ``runtime`` role, ``/clock`` must say
``backtest``, spec ids must be unique, and ``steps`` and ``days_per_step`` must be
plain ints in range. Every act goes over HTTP; physics decides what is allowed.

The record is returned, not stored: R-4 writes it to a cassette. Provisioning
minds from their specs (binding the spec's name to the App agent) is R-3b-2;
until then the caller hands in each mind's client.
"""

from __future__ import annotations

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
    # The input is copied once, here: every wake of the run sees the same document.
    step_input = dict(workflow_input or {})

    try:
        me = await clock.get("/me")
        now = await clock.get("/clock")
    except FundAPIError as exc:
        return RunRecord("refused", f"clock_unreadable:{exc.status_code}", label)
    if not isinstance(me, dict) or me.get("role") != "runtime":
        return RunRecord("refused", "clock_identity", label)
    if not isinstance(now, dict) or now.get("mode") != "backtest":
        return RunRecord("refused", "not_backtest", label)

    done: list[StepRecord] = []

    def end(ended: str, reason: str | None = None) -> RunRecord:
        return RunRecord(ended, reason or ended, label, tuple(done))

    for step in range(steps):
        if not decide_batch().allowed:
            return end("halted")
        try:
            at = (await clock.get("/clock"))["now"]
        except FundAPIError as exc:
            return end("error", f"clock_unreadable:{exc.status_code}")
        wakes: list[WakeRecord] = []
        stop: tuple[str, str] | None = None
        for mind in ordered:
            record = await wake(mind.spec, mind.client, workflow_input=step_input,
                                max_tool_calls=max_tool_calls)
            wakes.append(record)
            if record.ended == "halted":
                stop = ("halted", "halted")
            elif record.ended == "refused":
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
            done.append(StepRecord(step, at, tuple(wakes), None))
            return end("error", f"advance_failed:{exc.status_code}")
        done.append(StepRecord(step, at, tuple(wakes), moved["now"]))
    return end("completed")
