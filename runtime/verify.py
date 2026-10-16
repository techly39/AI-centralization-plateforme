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
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from runtime import cassette, packages, world
from runtime.cassette import CassetteError
from runtime.gate import METERED_PROVIDERS
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


#: The fields physics writes in a ``cost_metered`` row's body, no more, no less.
COST_ROW_FIELDS = frozenset({"agent_id", "pod_id", "key_ref", "usd_micros_total"})


def metered_block(rows: list[list[Any]], outcome: dict[str, Any],
                  metered: bool = False) -> list[list[Any]] | str:
    """The recorded ledger's trailing block of metered cost rows (ADR-044 §6, ADR-047), ``[]`` for
    a run that metered nothing, or why the block is not the recording's own (a string).

    A metered run's one sync posts, after its last step, one ``cost_metered`` row per key that
    spent. The block is the maximal run of such rows at the end of the ledger; it is the
    recording's only if it holds exactly one row per key the outcome says was posted, each with
    that key's agent, label and total, all by one actor that is none of the run's minds. It is
    reported apart, never folded into the comparison.

    Red-team 0029: the block is the same file's word against itself, so it must also be what
    physics could have written: posted by the ``runtime`` identity, each body exactly physics'
    fields with the pod its agent was registered in, and each key's total at least what the
    recorded turns of its mind say they cost. A run of metered minds (``metered``) has a block."""
    metering = outcome.get("metering")
    k = 0
    while k < len(rows) and len(rows[-1 - k]) == 5 and rows[-1 - k][3] == "cost_metered":
        k += 1
    if not isinstance(metering, dict):
        if k:
            return "cost rows end the ledger of a run that metered nothing"
        return "the run's minds are metered, but it records no cost" if metered else []
    block = rows[len(rows) - k:]
    keys = metering.get("keys") if isinstance(metering.get("keys"), list) else []
    posted = (metering.get("sync") or {}).get("posted")
    if k == 0 or posted != k:
        return f"{k} cost rows end the ledger; the recorded sync posted {posted}"
    want = {(key.get("agent_id"), key.get("key_ref"), key.get("spent_usd_micros"))
            for key in keys if isinstance(key, dict)}
    minds = {a for _, a in ((p[0], p[1]) for p in (outcome.get("run") or {}).get("agents") or [])}
    registered = _registrations(rows[:len(rows) - k])
    floors = _tape_floors(outcome)
    seen = set()
    for row in block:
        try:
            body = json.loads(row[4])
            got = (body["agent_id"], body["key_ref"], body["usd_micros_total"])
        except (ValueError, KeyError, TypeError):
            return f"event {row[0]} is not a well-formed cost row"
        if not isinstance(body, dict) or set(body) != COST_ROW_FIELDS:
            return f"event {row[0]} is not a well-formed cost row"
        if got not in want or got in seen or type(got[2]) is not int or got[0] not in minds:
            return f"event {row[0]} is not one of the recorded keys' totals"
        if got[0] not in registered or body["pod_id"] != registered[got[0]][1]:
            return f"event {row[0]} charges a pod its agent is not in"
        seen.add(got)
    for key in keys:
        if isinstance(key, dict) and (key.get("agent_id"), key.get("key_ref"),
                                      key.get("spent_usd_micros")) in seen:
            floor = floors.get(key.get("spec_id"), 0)
            if key["spent_usd_micros"] < floor:
                return (f"the key of {key.get('spec_id')} is charged {key['spent_usd_micros']} µ$, "
                        f"less than its recorded turns cost ({floor} µ$)")
    actors = {row[2] for row in block}
    if len(actors) != 1 or actors & minds \
            or registered.get(next(iter(actors)), (None, None))[0] != "runtime":
        return "the cost rows were not all posted by the Runtime"
    return block


def _registrations(rows: list[list[Any]]) -> dict[Any, tuple[Any, Any]]:
    """agent_id -> (role, pod_id), as the ledger registered them."""
    out: dict[Any, tuple[Any, Any]] = {}
    for row in rows:
        if len(row) == 5 and row[3] == "agent_registered":
            try:
                body = json.loads(row[4])
                out[body["agent_id"]] = (body["role"], body["pod_id"])
            except (ValueError, KeyError, TypeError):
                continue
    return out


def _tape_floors(outcome: dict[str, Any]) -> dict[str, int]:
    """spec id -> whole micro-dollars its recorded turns said they cost (rounded down)."""
    out: dict[str, int] = {}
    for step in (outcome.get("run") or {}).get("steps") or []:
        for w in step.get("wakes") or []:
            for e in w.get("exchanges") or []:
                usage = e.get("usage") if isinstance(e, dict) else None
                cost = usage.get("cost_usd") if isinstance(usage, dict) else None
                if type(cost) in (int, float) and cost > 0:
                    micros = int((Decimal(repr(float(cost))) * 1_000_000).to_integral_value(ROUND_FLOOR))
                    out[w.get("spec_id")] = out.get(w.get("spec_id"), 0) + micros
    return out


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
        if (package := cas.parameters.get("package")) is not None:
            packages.check(package, cas.parameters["workflow_input"])
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
    block = metered_block(recorded, cas.outcome, any(s.provider in METERED_PROVIDERS for s in specs))
    if isinstance(block, str):
        v = Verdict("DIVERGED", EXIT_DIVERGED, f"DIVERGED at the metered cost rows: {block}",
                    {"kind": "metered_block", "step": None, "wake": None})
        return v.code, v.line + "\n" + _evidence(v.name, len(recorded), v.where, None, {}, None,
                                                  os.stat(path).st_size, cas.redactions), ""
    if block:
        # ADR-044 §6 / ADR-047: what the replay must leave is the recorded ledger without its
        # trailing block of metered cost rows (a replay spends nothing, so posts nothing).
        recorded = recorded[:-len(block)]
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
                    max_tool_calls=cas.parameters["max_tool_calls"], replay=rec,
                    package=cas.parameters.get("package"))
            finally:
                hosted_world.stop()
            if outcome.get("ended") == "completed":
                rows_file = hosted_world.tmp / "recorded.ledger.json"
                _write_rows(rows_file, {**cas.ledger, "rows": recorded})
                compare = await asyncio.to_thread(hosted_world.compare_with, rows_file)
    except world.WorldError as exc:
        if exc.reason == "halted":
            v = Verdict("HALTED", EXIT_HALTED, "HALTED: the Human's HALT stopped the replay")
        else:
            v = Verdict("SETUP ERROR", EXIT_SETUP, f"SETUP ERROR: world: {exc.reason}")
        return v.code, v.line + "\n" + _evidence(v.name, events, v.where, None, {}, None, size,
                                                  cas.redactions), ""
    v = verdict_of(outcome, compare, recorded, events)
    if v.name == "IDENTICAL" and block:
        v = Verdict(v.name, v.code, v.line + f" (+{len(block)} metered cost rows of the recorded "
                    "run, reported apart)", v.where)
    return v.code, v.line + "\n" + _evidence(
        v.name, events, v.where, _replay_usd(outcome),
        {"ended": outcome.get("ended"), "reason": outcome.get("reason")}, compare, size,
        cas.redactions, block), ""


def _evidence(name: str, events: int, where: dict[str, Any] | None, usd: float | None,
              replay: dict[str, Any], compare: dict[str, Any] | None, size: int,
              redactions: int, block: list[list[Any]] | None = None) -> str:
    equal = compare.get("equal") if isinstance(compare, dict) else None
    return json.dumps({
        "metered_block": ({"rows": len(block), "usd_micros": sum(
            json.loads(r[4])["usd_micros_total"] for r in block)} if block else None),
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

