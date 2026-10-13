"""Compare two ledgers: did a replay leave the ledger the recording left? (ADR-040 (1)(4)).

A cassette replay that ends ``completed`` says every wake matched its tape. It does **not**
say the ledger is the recorded one; only this comparison, against the *original* database,
does (the cassette carries no ledger digest).

The law is strict: the two ledgers have the same length and every row is equal **as raw
text** (id, ts, actor, type, ``payload_json``), with exactly one allowed difference — the
single ``run_minds_declared`` row (ADR-032 (p)): a recorded run declares what drove its minds
(``scripted`` or ``model``…) and its replay declares ``{"minds": ["cassette"]}``; id, ts, actor
and type must still be equal. Derived tables are not compared: they rebuild from the ledger
(``fund-env rebuild-state``). A difference anywhere else is a finding, never a reason to widen
this law.

Read-only: the files are opened ``mode=ro`` and a missing path is an error, never a new
database. The Runtime does not import this module: it stays ledger-blind (ADR-022, ADR-040).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ledger.events import EVENT_RUN_MINDS_DECLARED
from app.run_clock import MIND_KINDS

#: ``(id, ts, actor_agent_id, type, payload_json)`` exactly as the database stores them.
Row = tuple[int, str, "int | None", str, str]

#: What a replay declares: the one payload the allowed difference may end in.
REPLAYED_DECLARATION = {"minds": ["cassette"]}


class LedgerFileError(Exception):
    """A path is missing, unreadable, or not a fund database."""


@dataclass(frozen=True)
class LedgerComparison:
    equal: bool
    #: How many rows differed in the one way the law allows (0 or 1).
    allowed: int
    #: ``id`` of the first event that differs (or the first one a shorter ledger lacks);
    #: ``None`` (null, not 0) when the ledgers are equal.
    first_difference: int | None
    detail: str


def ledger_rows(path: Path) -> list[Row]:
    """Every event of the database at ``path``, by id, as stored. Never creates a file."""
    path = Path(path)
    if not path.is_file():
        raise LedgerFileError(f"{path}: not a file")
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT id, ts, actor_agent_id, type, payload_json FROM events ORDER BY id"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise LedgerFileError(f"{path}: not a readable fund database ({exc.__class__.__name__})") from exc
    return [tuple(r) for r in rows]  # type: ignore[misc]


def compare(recorded: list[Row], replayed: list[Row]) -> LedgerComparison:
    """The law above, over two lists of raw rows."""
    allowed = 0
    for a, b in zip(recorded, replayed):
        if a == b:
            continue
        if allowed == 0 and _is_the_allowed_difference(a, b):
            allowed = 1
            continue
        return LedgerComparison(False, allowed, a[0], f"event {a[0]} ({a[3]}) differs from the replay's")
    if len(recorded) != len(replayed):
        longer = recorded if len(recorded) > len(replayed) else replayed
        first = longer[min(len(recorded), len(replayed))]
        return LedgerComparison(False, allowed, first[0],
                                f"{len(recorded)} recorded events, {len(replayed)} replayed")
    return LedgerComparison(True, allowed, None, "equal" if not allowed
                            else "equal but for the run_minds_declared payload")


def _is_the_allowed_difference(recorded: Row, replayed: Row) -> bool:
    if recorded[:4] != replayed[:4] or recorded[3] != EVENT_RUN_MINDS_DECLARED:
        return False
    try:
        was, now = json.loads(recorded[4]), json.loads(replayed[4])
    except ValueError:
        return False
    return now == REPLAYED_DECLARATION and _is_a_declaration(was)


def _is_a_declaration(payload: Any) -> bool:
    if not isinstance(payload, dict) or set(payload) != {"minds"}:
        return False
    kinds = payload["minds"]
    return (isinstance(kinds, list) and bool(kinds)
            and all(type(k) is str and k in MIND_KINDS for k in kinds))
