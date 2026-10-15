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

**A rows file** (``*.ledger.json``, M-002/ADR-045) is a database's ledger written down by
``fund-env export-ledger``: the same rows, as raw text, in one canonical JSON document. It is what
a cassette carries as the recorded ledger, so one file is enough to prove a replay identical.
:func:`ledger_rows` reads either; the law above is applied to the rows, whatever they came from.

"Raw text" means the values SQLite returns, compared with Python's ``==`` (a column's affinity
decides text vs number); the one allowed row is judged on its parsed JSON, so a hand-made
replay database could spell ``{"minds": ["cassette"]}`` differently than physics does. Physics
refuses a second declaration (``app.run_clock``), so two declarations cannot occur in a real
database.

Read-only: the files are opened ``mode=ro`` and a missing path is an error, never a new
database. That holds for the rollback-journal databases the App makes (no ``journal_mode``
pragma anywhere in ``app/``); a WAL-mode file would get ``-shm``/``-wal`` files beside it even
read-only (audit c33). The Runtime does not import this module: it stays ledger-blind
(ADR-022, ADR-040).
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ledger.events import EVENT_CLOCK_ADVANCED, EVENT_RUN_MINDS_DECLARED
from app.run_clock import MIND_KINDS

#: ``(id, ts, actor_agent_id, type, payload_json)`` exactly as the database stores them.
Row = tuple[int, str, "int | None", str, str]

#: The rows file's format name (the cassette's ``ledger.ledger_format``).
ROWS_FORMAT = "fund-ledger-rows/1"
#: A rows file bigger than this is refused (64 MiB).
MAX_ROWS_BYTES = 64 * 2**20
ROWS_SUFFIX = ".ledger.json"

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


def rows_document(rows: list[Row]) -> str:
    """The canonical rows-file text for ``rows``: sorted keys, compact, ASCII."""
    return json.dumps({"ledger_format": ROWS_FORMAT, "rows": [list(r) for r in rows]},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({k for k, _ in pairs}) != len(pairs):
        raise LedgerFileError("a key is used twice in one object")
    return dict(pairs)


def _refuse_constant(name: str) -> Any:
    raise LedgerFileError(f"{name} is not JSON")


def rows_from_document(doc: Any) -> list[Row]:
    """The rows of a parsed rows document, else :class:`LedgerFileError`: exactly the two keys,
    this format, and every row exactly ``[int > 0, str, int | None, str, str]`` with ids
    strictly increasing (a ledger's order)."""
    if (type(doc) is not dict or set(doc) != {"ledger_format", "rows"}
            or doc["ledger_format"] != ROWS_FORMAT or type(doc["rows"]) is not list):
        raise LedgerFileError(f"a rows document is {{ledger_format: {ROWS_FORMAT}, rows: [...]}}")
    rows: list[Row] = []
    last = 0
    for r in doc["rows"]:
        if (type(r) is not list or len(r) != 5 or type(r[0]) is not int or r[0] <= last
                or type(r[1]) is not str or not (r[2] is None or type(r[2]) is int)
                or type(r[3]) is not str or type(r[4]) is not str):
            raise LedgerFileError("a row is [id, ts, actor_agent_id, type, payload_json], ids "
                                  "strictly increasing")
        last = r[0]
        rows.append((r[0], r[1], r[2], r[3], r[4]))
    return rows


def read_rows_file(path: Path) -> list[Row]:
    """The rows of a ``*.ledger.json`` file, else :class:`LedgerFileError`. The file is untrusted:
    not a symlink, a regular file of at most :data:`MAX_ROWS_BYTES`, ASCII, no repeated key, no
    NaN, exact shape (:func:`rows_from_document`), and its text is :func:`rows_document`'s."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise LedgerFileError(f"{path}: cannot open ({exc.strerror})") from exc
    try:
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ROWS_BYTES:
                raise LedgerFileError(f"{path}: not a regular file of at most {MAX_ROWS_BYTES} bytes")
            raw = f.read(MAX_ROWS_BYTES + 1)
    except OSError as exc:
        raise LedgerFileError(f"{path}: cannot read ({exc.strerror})") from exc
    if len(raw) > MAX_ROWS_BYTES:
        raise LedgerFileError(f"{path}: over {MAX_ROWS_BYTES} bytes")
    try:
        text = raw.decode("ascii")
        doc = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_refuse_constant)
    except LedgerFileError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LedgerFileError(f"{path}: not a rows file ({exc.__class__.__name__})") from exc
    rows = rows_from_document(doc)
    if text != rows_document(rows):
        raise LedgerFileError(f"{path}: not in the canonical form export-ledger writes")
    return rows


def ledger_rows(path: Path) -> list[Row]:
    """Every event of the database at ``path`` (or of the rows file ``*.ledger.json`` there), by
    id, as stored. Never creates a file."""
    path = Path(path)
    if path.name.endswith(ROWS_SUFFIX):
        return read_rows_file(path)
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


def locate(rows: list[Row], event_id: int) -> dict[str, Any] | None:
    """Where event ``event_id`` sits in a run: ``step`` (how many ``clock_advanced`` rows precede
    it: the step whose wakes it belongs to), who acted, its type, and whether it is ``genesis``
    (before the minds' declaration: the world's own opening). ``None`` if no such event."""
    step = 0
    declared: int | None = None
    found: Row | None = None
    for row in rows:
        if row[3] == EVENT_RUN_MINDS_DECLARED and declared is None:
            declared = row[0]
        if row[0] == event_id:
            found = row
            break
        if row[3] == EVENT_CLOCK_ADVANCED:
            step += 1
    if found is None:
        return None
    return {"event_id": found[0], "step": step, "actor_agent_id": found[2], "type": found[3],
            "genesis": declared is None or found[0] < declared}


def _is_the_allowed_difference(recorded: Row, replayed: Row) -> bool:
    if recorded[:4] != replayed[:4] or recorded[3] != EVENT_RUN_MINDS_DECLARED:
        return False
    try:
        was, now = json.loads(recorded[4]), json.loads(replayed[4])
    except (ValueError, TypeError):  # not JSON text (a NULL or an integer in the column)
        return False
    return now == REPLAYED_DECLARATION and _is_a_declaration(was)


def _is_a_declaration(payload: Any) -> bool:
    if not isinstance(payload, dict) or set(payload) != {"minds"}:
        return False
    kinds = payload["minds"]
    return (isinstance(kinds, list) and bool(kinds)
            and all(type(k) is str and k in MIND_KINDS for k in kinds))
