"""Replay: a recorded run drives the minds again, at $0 (R-4b-1, ADR-038).

A cassette (:mod:`runtime.cassette`) holds a completed run's record: for every wake the
transcript and one exchange per model turn (the hash of the request, and the usage). This
module turns it into data a conductor can replay from:

* :class:`Recording` — the cassette, validated. ``tape(step, spec_id)`` is the :class:`Tape`
  of one wake: per turn, the hash of the request the mind was asked, the reply it gave (or
  ``None``: the turn failed), and the transcript before it.
* :class:`CassetteProvider` — the mind the name ``cassette`` builds (:mod:`runtime.registry`).
  It holds one tape. It answers a request only if the request hashes to the recorded one;
  any other request is a :class:`ReplayMiss`. Its replies carry zero usage: the recorded cost
  belongs to the original run.
* :meth:`Recording.divergence` — after a replayed wake, where and why it left the recording.

The first divergence ends the run (``diverged``, see :mod:`runtime.lockstep`); a miss is never
covered over. Kinds, decided from the two records and never from reason strings:

* ``unrecorded`` — the replay asked for a turn the recording does not have;
* ``world`` — the transcript before the turn differs: the world answered differently;
* ``key`` — the same, except the recording holds a redacted minted key (a minted key is
  fresh randomness: such a run cannot replay byte for byte, ADR-037);
* ``surface`` — the transcript is equal but the request is not: the tools or the model changed;
* ``ended`` — every request matched, but the wake ended differently or earlier.

Responses are not hashed: a cassette whose replies were edited while the request hashes were
kept would replay those replies (R-4b-2 compares the ledgers; ADR-038 says so).

Imports only the standard library, :mod:`runtime.providers` and :mod:`runtime.cassette`: a
mind that can reach nothing (``test_the_replay_module_has_no_reach``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from runtime import cassette
from runtime.providers import (
    CompletionRequest,
    CompletionResponse,
    Message,
    Usage,
)

_SHA = r"[0-9a-f]{64}"


class RecordingError(ValueError):
    """The cassette is a file, but not a run that can be replayed."""


class ReplayMiss(Exception):
    """The mind was asked something the recording does not hold."""


class ReplayedFailure(Exception):
    """The recorded turn failed (the provider raised, or its reply was refused)."""


@dataclass(frozen=True)
class Turn:
    """One recorded model turn."""
    request_sha256: str
    #: ``None``: the recorded turn failed and no assistant message answers it.
    response: CompletionResponse | None
    #: The recorded (redacted) transcript before this turn.
    prefix: tuple[Message, ...]

    def __post_init__(self) -> None:
        # Data, not code (red-team 0018 H3): exact types, so a str subclass that equals every
        # hash, or a "reply" with its own model_copy, cannot be a turn.
        if type(self.request_sha256) is not str or not re.fullmatch(_SHA, self.request_sha256):
            raise RecordingError("a request hash is 64 lowercase hex digits")
        if self.response is not None and type(self.response) is not CompletionResponse:
            raise RecordingError("a recorded reply is a CompletionResponse")
        if type(self.prefix) is not tuple or any(type(m) is not Message for m in self.prefix):
            raise RecordingError("a recorded prefix is a tuple of Messages")


@dataclass(frozen=True)
class Tape:
    """One recorded wake: its turns, and how it ended."""
    turns: tuple[Turn, ...] = ()
    ended: str = ""
    tool_calls: int = 0
    #: What the recorded wake asked of the model, and the digest of the tools its requests carried
    #: (cassette v2). ``None``: a scripted mind has no model; a hand-built tape has neither.
    model: str | None = None
    tools_sha256: str | None = None

    def __post_init__(self) -> None:
        if (type(self.turns) is not tuple or any(type(t) is not Turn for t in self.turns)
                or type(self.ended) is not str or type(self.tool_calls) is not int
                or self.tool_calls < 0
                or not all(v is None or type(v) is str for v in (self.model, self.tools_sha256))):
            raise RecordingError("a tape is a tuple of Turns, how the wake ended and its calls")


class CassetteProvider:
    """The mind of provider ``cassette``: a tape and a cursor, nothing else."""

    name = "cassette"
    spends_money = False

    def __init__(self, tape: Tape) -> None:
        self._turns = tape.turns
        self._next = 0

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        i = self._next
        self._next += 1
        if i >= len(self._turns):
            raise ReplayMiss(f"turn {i} is past the recording")
        turn = self._turns[i]
        if cassette.request_sha256(request) != turn.request_sha256:
            raise ReplayMiss(f"turn {i} is not the recorded request")
        if turn.response is None:
            raise ReplayedFailure(f"turn {i} failed when it was recorded")
        # A copy: nothing the mind holds can rewrite the tape. Usage is zero: a replay spends nothing.
        return turn.response.model_copy(deep=True, update={"usage": Usage()})


def _text(messages: Any) -> str:
    return json.dumps([m.model_dump(mode="json") for m in messages], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _assistants(messages: Any) -> list[int]:
    return [i for i, m in enumerate(messages) if m.role == "assistant"]


@dataclass(frozen=True)
class HireRecord:
    """One hiring decision of a run (:mod:`runtime.onboarding`): data, so it lives here."""
    step: int
    vacancy_id: int
    spec_id: str
    #: ``hired`` | ``refused:<code>`` (``budget_over_cap``, ``wake_gate:<reason>``, ``physics:409``,
    #: ``key_over_cap``, ``no_key_room``). ``spec_id`` is the hired mind's (its pod's name), or the
    #: law's ``hire-<n>`` for a refusal.
    outcome: str
    agent_id: int | None = None
    #: The reason the Runtime posted to physics, word for word (a replay posts the same).
    reason: str | None = None

    def __post_init__(self) -> None:
        if (type(self.step) is not int or self.step < 0 or type(self.vacancy_id) is not int
                or type(self.spec_id) is not str or not re.fullmatch(r"hire-[0-9]{1,6}(-[0-9]{1,4})?", self.spec_id)
                or type(self.outcome) is not str
                or not re.fullmatch(r"hired|refused:[a-z_]+(:[a-z0-9_]+)?", self.outcome)
                or not (self.agent_id is None or type(self.agent_id) is int)
                or not (self.reason is None or (type(self.reason) is str and 0 < len(self.reason) <= 200))):
            raise RecordingError("a hire record is malformed")
        # Only a hire, or a hire whose key the month could not hold, names an agent.
        with_agent = self.outcome in ("hired", "refused:key_over_cap")
        if with_agent != (self.agent_id is not None) or (with_agent and self.reason is not None):
            raise RecordingError("a hire record is malformed")


class Recording:
    """A completed run's cassette, validated, as tapes (build with :meth:`load` or
    :meth:`from_outcome`)."""

    def __init__(self, steps: int, tapes: Mapping[tuple[int, str], Tape],
                 calendar: tuple[tuple[str, str], ...] = (),
                 hires: tuple[HireRecord, ...] = ()) -> None:
        if type(steps) is not int or not all(
                type(k) is tuple and len(k) == 2 and type(k[0]) is int and type(k[1]) is str
                and type(t) is Tape for k, t in tapes.items()):
            raise RecordingError("a recording is a step count and Tapes keyed by (step, spec id)")
        if calendar != () and (len(calendar) != steps or not all(
                type(c) is tuple and len(c) == 2 and all(type(x) is str for x in c)
                for c in calendar)):
            raise RecordingError("a calendar is empty, or one (at, advanced_to) pair per step")
        self.steps = steps
        self._tapes = dict(tapes)
        #: ``(at, advanced_to)`` per recorded step; empty for a hand-built recording.
        self._calendar = calendar
        self.spec_ids = frozenset(spec_id for _, spec_id in self._tapes)
        if type(hires) is not tuple or any(type(h) is not HireRecord for h in hires):
            raise RecordingError("hires are a tuple of HireRecords")
        #: Every hiring decision of the recorded run, and the minds it hired (their wakes are in
        #: the tapes from the step they were hired on).
        self.hires = hires
        self.hired_ids = frozenset(h.spec_id for h in hires if h.outcome == "hired")
        if len(self.hired_ids) != sum(h.outcome == "hired" for h in hires):
            raise RecordingError("a mind is hired twice")
        for h in hires:
            if h.outcome == "hired" and any(k[1] == h.spec_id and k[0] < h.step for k in self._tapes):
                raise RecordingError(f"{h.spec_id} woke before it was hired")

    @classmethod
    def load(cls, path: Path) -> Recording:
        return cls.from_outcome(cassette.read(path).outcome)

    @classmethod
    def from_outcome(cls, outcome: Mapping[str, Any]) -> Recording:
        run = outcome.get("run") if isinstance(outcome, Mapping) else None
        if not isinstance(run, dict):
            raise RecordingError("the cassette holds no run")
        if run.get("ended") != "completed":
            raise RecordingError(f"only a completed run replays, not {run.get('ended')!r}")
        if run.get("retired"):
            raise RecordingError("a run in which a mind was retired does not replay yet")
        steps = run.get("steps")
        if not isinstance(steps, list):
            raise RecordingError("the run has no steps")
        tapes: dict[tuple[int, str], Tape] = {}
        calendar: list[tuple[str, str]] = []
        for n, step in enumerate(steps):
            if not isinstance(step, dict) or step.get("step") != n:
                raise RecordingError(f"step {n} is out of order")
            if type(step.get("at")) is not str or type(step.get("advanced_to")) is not str:
                raise RecordingError(f"step {n}: a completed step has a start and a landing time")
            calendar.append((step["at"], step["advanced_to"]))
            for wake in step.get("wakes") or []:
                try:
                    spec_id = wake["spec_id"]
                    if type(spec_id) is not str or (n, spec_id) in tapes:
                        raise RecordingError(f"step {n}: a mind wakes twice, or has no id")
                    tapes[(n, spec_id)] = _tape(wake)
                except (KeyError, TypeError, ValueError, ValidationError) as exc:
                    if isinstance(exc, RecordingError):
                        raise
                    raise RecordingError(f"step {n}: a wake is malformed ({type(exc).__name__})") from exc
        try:
            hires = tuple(HireRecord(**h) for h in run.get("hires") or [])
        except TypeError as exc:
            raise RecordingError("a hire record is malformed") from exc
        if any(h.step >= len(steps) for h in hires):
            raise RecordingError("a hire record is past the run's last step")
        return cls(len(steps), tapes, tuple(calendar), hires)

    def calendar(self, step: int) -> tuple[str, str] | None:
        """``(at, advanced_to)`` the recording had for ``step``; ``None`` for a hand-built one."""
        return self._calendar[step] if 0 <= step < len(self._calendar) else None

    def tape(self, step: int, spec_id: str) -> Tape:
        """The wake recorded at ``step`` for ``spec_id``; an empty tape if none was."""
        return self._tapes.get((step, spec_id), Tape())

    def divergence(self, step: int, record: Any) -> str | None:
        """``"<seq>:<kind>"`` where the replayed ``record`` (a ``runtime.native.WakeRecord``, not
        imported here: this module reaches nothing) left the recording, else ``None``."""
        tape = self.tape(step, record.spec_id)
        stops = _assistants(record.transcript)
        for i, exchange in enumerate(record.exchanges):
            if i >= len(tape.turns):
                return f"{i}:unrecorded"
            turn = tape.turns[i]
            if exchange.request_sha256 == turn.request_sha256:
                continue
            replayed = record.transcript[:stops[i]] if i < len(stops) else record.transcript
            if cassette.redact(_text(replayed)) != _text(turn.prefix):
                return f"{i}:world"
            # c32 NOTE 5: a changed tool surface or model is a surface change even when a redacted
            # key sits in the prefix; only an unchanged surface with a key in it reads as ``key``.
            if (record.tools_sha256, record.model) != (tape.tools_sha256, tape.model):
                return f"{i}:surface"
            return f"{i}:key" if cassette._REDACTED in _text(turn.prefix) else f"{i}:surface"
        if len(record.exchanges) < len(tape.turns) or (record.ended, record.tool_calls) != (
                tape.ended, tape.tool_calls):
            return f"{len(record.exchanges)}:ended"
        return None


def _tape(wake: Mapping[str, Any]) -> Tape:
    messages = tuple(Message.model_validate(m) for m in wake["transcript"])
    exchanges = wake["exchanges"]
    stops = _assistants(messages)
    # Every wake of a completed run asked at least one turn: a wake with none was refused, and a
    # refusal is a retirement (red-team 0018 H4) or a bug, never something to replay.
    if not exchanges or wake["ended"] == "refused":
        raise RecordingError("a completed run holds no refused or turn-less wake")
    if (any(type(e["seq"]) is not int for e in exchanges)
            or [e["seq"] for e in exchanges] != list(range(len(exchanges)))):
        raise RecordingError("exchanges are not numbered 0..n-1")
    failed = [e["usage"] is None for e in exchanges]
    if any(failed[:-1]):
        raise RecordingError("only the last exchange of a wake can have failed")
    if len(stops) != len(exchanges) - sum(failed):
        raise RecordingError("assistant messages and answered exchanges differ")
    turns = []
    for i, e in enumerate(exchanges):
        digest = e["request_sha256"]
        if type(digest) is not str or not re.fullmatch(_SHA, digest):
            raise RecordingError("a request hash is not 64 lowercase hex digits")
        if e["usage"] is None:
            response, prefix = None, messages
        else:
            reply = messages[stops[i]]
            response = CompletionResponse(content=reply.content, tool_calls=reply.tool_calls,
                                          usage=Usage.model_validate(e["usage"]))
            prefix = messages[:stops[i]]
        turns.append(Turn(digest, response, prefix))
    ended, calls = wake["ended"], wake["tool_calls"]
    if type(ended) is not str or type(calls) is not int:
        raise RecordingError("a wake's end is malformed")
    model, tools_digest = wake["model"], wake["tools_sha256"]
    if (model is not None and type(model) is not str) or type(tools_digest) is not str or not re.fullmatch(
            _SHA, tools_digest):
        raise RecordingError("a wake records its model and its tools' digest")
    return Tape(tuple(turns), ended, calls, model, tools_digest)


def as_cassette(spec: Any) -> Any:
    """``spec`` as a spec for the replay: the same mind and model, provider ``cassette``, no
    script, no budget (a replay spends nothing; ADR-047 §6)."""
    return type(spec).model_validate({**spec.model_dump(), "provider": "cassette", "script": None,
                                      "budget_usd": 0.0})
