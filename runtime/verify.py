"""``fund-runtime replay --cassette F --verify``: is this recorded run proven? (M-002, ADR-045)

From **one file** (plus the world key, by design: it is a secret and never in the file) the
Runtime rebuilds the recorded world from the cassette's recipe, replays every mind from its tape
at $0, and asks physics whether the ledger it left is the recorded one. The verdict is a machine
fact, on stdout's first line, with a distinct exit code each:

====  ===========  ==========================================================================
exit  first line   meaning
====  ===========  ==========================================================================
0     IDENTICAL    the replay ended ``completed`` and physics' ``compare-ledgers`` found the
                   ledgers equal but for the one allowed difference (the minds' declaration)
1     DIVERGED     a tape left the recording (``at step S, wake W, turn T``), the calendar
                   moved differently, or the replay completed and the ledger is not the
                   recorded one (``at step S, wake W | physics, event E (type)``)
2     (stderr)     the command or the file is wrong: version 1, no world, no key, malformed
3     SETUP ERROR  the world could not be rebuilt as recorded, or the replay could not run
                   (a refusal, an error): **never** read as DIVERGED
4     HALTED       the Human's HALT stopped it
====  ===========  ==========================================================================

Only a tape divergence or an unequal ledger after ``completed`` reads DIVERGED (:func:`verdict_of`).
After the first line comes one JSON object of evidence.

**What IDENTICAL proves**: reproducibility: these tapes, in this world, under this checkout's
physics, leave this ledger. Not authorship (a consistent forger can write a valid cassette of a
different run), and the final reply text and the usage of a wake are not hashed (pinned limit).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from runtime import cassette, world
from runtime.cassette import CassetteError
from runtime.registry import ProviderRefused, check_spec
from runtime.replay import Recording, RecordingError, as_cassette
from runtime.spec import SpecError, specs_from_cassette

EXIT_IDENTICAL, EXIT_DIVERGED, EXIT_USAGE, EXIT_SETUP, EXIT_HALTED = 0, 1, 2, 3, 4
_CALENDAR = {"calendar_at": "the clock stood on another date than the recording's",
             "calendar_landed": "an advance landed on another date than the recording's"}
_MEANING = {"world": "the mind was shown a world the recording did not show",
            "key": "a key minted in the world differed (redacted in the file)",
            "surface": "the request's surface (tools or model) differed",
            "unrecorded": "the mind asked a turn the recording does not have",
            "ended": "the wake ended differently than recorded"}


@dataclass(frozen=True)
class Verdict:
    name: str
    code: int
    line: str
    where: dict[str, Any] | None = None


def _usage(message: str) -> Verdict:
    return Verdict("USAGE", EXIT_USAGE, message)


def verdict_of(outcome: dict[str, Any], compare: dict[str, Any] | None,
               rows: list[list[Any]], events: int) -> Verdict:
    """The verdict of a replay's ``outcome`` (``ended``/``reason``/``run``) and physics' ``compare``
    (``None``: not asked), pure. ``rows`` are the recorded ledger's, ``events`` their number."""
    ended, reason = outcome.get("ended"), str(outcome.get("reason"))
    if ended == "completed":
        if not isinstance(compare, dict) or type(compare.get("equal")) is not bool:
            return Verdict("SETUP ERROR", EXIT_SETUP, "SETUP ERROR: the replay completed but "
                           "physics gave no comparison")
        if compare["equal"]:
            allowed = compare.get("allowed")
            note = (f" (allowed: run_minds_declared {_declared(rows)} -> cassette)"
                    if allowed == 1 else "")
            return Verdict("IDENTICAL", EXIT_IDENTICAL,
                           f"IDENTICAL: {events} events, 0 differences, $0{note}")
        return _ledger_divergence(outcome, compare, rows)
    if ended == "diverged":
        return _tape_divergence(reason)
    if ended == "halted":
        return Verdict("HALTED", EXIT_HALTED, "HALTED: the Human's HALT stopped the replay")
    # refused | error | anything else: the replay could not run as recorded; that is not a
    # statement about the recording (c32 NOTE 4).
    return Verdict("SETUP ERROR", EXIT_SETUP, f"SETUP ERROR: the replay could not run ({ended}): {reason}")


def _declared(rows: list[list[Any]]) -> str:
    for row in rows:
        if len(row) == 5 and row[3] == "run_minds_declared":
            try:
                return "+".join(json.loads(row[4])["minds"])
            except (ValueError, KeyError, TypeError):
                break
    return "?"


def _tape_divergence(reason: str) -> Verdict:
    """``diverged:<spec>:<step>:<seq>:<kind>`` (a mind left its tape) or
    ``diverged:clock:<step>:0:calendar_*`` (the calendar)."""
    parts = reason.split(":")
    if len(parts) != 5 or parts[0] != "diverged" or not parts[2].isdigit() or not parts[3].isdigit():
        return Verdict("SETUP ERROR", EXIT_SETUP, f"SETUP ERROR: an unreadable divergence: {reason}")
    _, who, step, seq, kind = parts
    if kind in _CALENDAR:
        return Verdict("DIVERGED", EXIT_DIVERGED,
                       f"DIVERGED at step {step}, the calendar ({kind}): {_CALENDAR[kind]}",
                       {"kind": kind, "step": int(step), "wake": None, "turn": None})
    return Verdict("DIVERGED", EXIT_DIVERGED,
                   f"DIVERGED at step {step}, wake {who}, turn {seq}: {kind} - "
                   f"{_MEANING.get(kind, 'left the recording')}",
                   {"kind": kind, "step": int(step), "wake": who, "turn": int(seq)})


def _ledger_divergence(outcome: dict[str, Any], compare: dict[str, Any],
                       rows: list[list[Any]]) -> Verdict:
    """Every tape matched and the replay completed, but physics says the ledger is not the
    recorded one: name the event, its step and who acted."""
    where = compare.get("locate")
    first = compare.get("first_difference")
    if not isinstance(where, dict):
        return Verdict("DIVERGED", EXIT_DIVERGED,
                       f"DIVERGED at event {first}: the ledger differs from the recorded one",
                       {"kind": "ledger", "event_id": first, "step": None, "wake": None, "type": None})
    agents = {a: s for s, a in ((p[0], p[1]) for p in (outcome.get("run") or {}).get("agents") or [])}
    mind = agents.get(where.get("actor_agent_id"))
    who = f"wake {mind}" if mind is not None else "physics"
    recorded = next((r for r in rows if r and r[0] == where.get("event_id")), None)
    kind = "key" if recorded is not None and cassette._REDACTED in str(recorded[4]) else "ledger"
    return Verdict(
        "DIVERGED", EXIT_DIVERGED,
        f"DIVERGED at step {where['step']}, {who}, event {where['event_id']} ({where['type']}): "
        f"{'a minted key differed (redacted in the file)' if kind == 'key' else 'the ledger differs from the recorded one'}",
        {"kind": kind, "step": where["step"], "wake": mind, "event_id": where["event_id"],
         "type": where["type"], "actor_agent_id": where.get("actor_agent_id"),
         "genesis": where.get("genesis")})


def _replay_usd(outcome: dict[str, Any]) -> float:
    total = 0.0
    for step in (outcome.get("run") or {}).get("steps") or []:
        for w in step.get("wakes") or []:
            for e in w.get("exchanges") or []:
                usage = e.get("usage")
                if isinstance(usage, dict):
                    total += float(usage.get("cost_usd") or 0)
    return total


def _write_rows(path: Path, ledger: dict[str, Any]) -> None:
    text = json.dumps(ledger, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(text)


def _first_unlike(fresh: list[Any], recorded: list[Any]) -> int | None:
    """Index of the first fresh genesis row that is not the recorded ledger's, else ``None``."""
    for i, row in enumerate(fresh):
        if i >= len(recorded) or row != recorded[i]:
            return i
    return None


async def verify(path: Path) -> tuple[int, str, str]:
    """``(exit code, stdout, stderr)`` of ``replay --cassette PATH --verify``."""
    def usage(message: str) -> tuple[int, str, str]:
        return EXIT_USAGE, "", f"fund-runtime: {message}\n"

    try:
        cas = cassette.read(path)
        size = os.stat(path).st_size
    except (CassetteError, OSError) as exc:
        return usage(f"{path}: {exc}")
    if cas.world is None or cas.ledger is None:
        return usage(f"{path} carries no world: verify needs a run recorded with --world")
    try:
        specs = specs_from_cassette(cas.specs)
        rec = Recording.from_outcome(cas.outcome)
        recipe = cas.world["recipe"]
        world.parse_recipe(recipe)
        if {s.id for s in specs} != rec.spec_ids:
            return usage("the cassette's specs are not the recording's minds: their ids differ")
        if cas.parameters["steps"] != rec.steps:
            return usage("the cassette's parameters disagree with its recording (steps)")
        for spec in specs:  # the recorded spec itself must be one a mind is built from
            check_spec(spec)
        minds = [as_cassette(s) for s in specs]
        for mind in minds:
            check_spec(mind)
        key = world.world_key()
    except (SpecError, RecordingError, world.WorldError, ProviderRefused, ValueError,
            ValidationError) as exc:
        return usage(f"{path}: {getattr(exc, 'reason', None) or exc}")
    recorded = cas.ledger["rows"]
    events = len(recorded)

    from runtime import cli  # the conductor; imported here so cli can import this module lazily
    outcome: dict[str, Any] = {}
    compare: dict[str, Any] | None = None
    try:
        async with world.hosted(recipe, key) as hosted_world:
            fresh = (await asyncio.to_thread(hosted_world.export_ledger))["rows"]
            i = _first_unlike(fresh, recorded)
            if i is not None:
                row = fresh[i]
                return (EXIT_SETUP,
                        f"SETUP ERROR: the world is not the recorded one: event {row[0]} "
                        f"({row[3]}) differs\n" + _evidence(
                            "SETUP ERROR", events, None, None, {}, None, size, cas.redactions), "")
            url = await hosted_world.serve()
            try:
                outcome = await cli._conduct(
                    minds, url, hosted_world.registrar_key, hosted_world.clock_key, None,
                    steps=rec.steps, days_per_step=cas.parameters["days_per_step"],
                    workflow_input=cas.parameters["workflow_input"],
                    max_tool_calls=cas.parameters["max_tool_calls"], replay=rec)
            finally:
                hosted_world.stop()
            if outcome.get("ended") == "completed":
                rows_file = hosted_world.tmp / "recorded.ledger.json"
                _write_rows(rows_file, cas.ledger)
                compare = await asyncio.to_thread(hosted_world.compare_with, rows_file)
    except world.WorldError as exc:
        if exc.reason == "halted":
            v = Verdict("HALTED", EXIT_HALTED, "HALTED: the Human's HALT stopped the replay")
        else:
            v = Verdict("SETUP ERROR", EXIT_SETUP, f"SETUP ERROR: world: {exc.reason}")
        return v.code, v.line + "\n" + _evidence(v.name, events, v.where, None, {}, None, size,
                                                  cas.redactions), ""
    v = verdict_of(outcome, compare, recorded, events)
    return v.code, v.line + "\n" + _evidence(
        v.name, events, v.where, _replay_usd(outcome),
        {"ended": outcome.get("ended"), "reason": outcome.get("reason")}, compare, size,
        cas.redactions), ""


def _evidence(name: str, events: int, where: dict[str, Any] | None, usd: float | None,
              replay: dict[str, Any], compare: dict[str, Any] | None, size: int,
              redactions: int) -> str:
    equal = compare.get("equal") if isinstance(compare, dict) else None
    return json.dumps({
        "verdict": name, "events": events,
        "differences": 0 if equal is True else None,  # null, not 0: the first one is all physics names
        "allowed": compare.get("allowed") if isinstance(compare, dict) else None,
        "replay_usd": usd, "where": where, "replay": replay or None, "compare": compare,
        "cassette": {"bytes": size, "redactions": redactions}}, indent=2, sort_keys=True) + "\n"


def main(path: Path) -> int:
    """Run :func:`verify`, print its two streams, return its exit code."""
    code, out, err = asyncio.run(verify(path))
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code

