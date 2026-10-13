"""``fund-env compare-ledgers`` and ``app.ledger.compare`` (ADR-040 (1)(4), cycle 33).

The law: equal length, every row equal as raw text, one allowed difference: the single
``run_minds_declared`` payload (any valid kind list -> ``{"minds": ["cassette"]}``).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app import cli
from app.db.models import Event
from app.ledger.compare import LedgerFileError, compare, ledger_rows

DECL = "run_minds_declared"


def _payload(**kw) -> str:
    return json.dumps(kw)


def _ledger(minds: list[str] | None = None) -> list[tuple]:
    rows = [(1, "2026-01-02T00:00:00", None, "run_started", _payload(world="w")),
            (2, "2026-01-02T00:00:00", 3, "agent_registered", _payload(agent_id=4))]
    if minds is not None:
        rows.append((3, "2026-01-02T00:00:00", 3, DECL, _payload(minds=minds)))
    rows.append((4, "2026-01-02T00:00:00", 4, "message_sent", _payload(text="hi")))
    return rows


def _db(path: Path, rows: list[tuple]) -> Path:
    con = sqlite3.connect(path)
    cols = ", ".join(f"{c.name} {c.type.compile()}" for c in Event.__table__.columns)
    con.execute(f"CREATE TABLE events ({cols})")  # the real column set, no FK needed to compare
    con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()
    return path


def test_equal_ledgers_compare_equal() -> None:
    r = compare(_ledger(["cassette"]), _ledger(["cassette"]))
    assert (r.equal, r.allowed, r.first_difference) == (True, 0, None)
    r = compare(_ledger(), _ledger())
    assert (r.equal, r.allowed, r.first_difference) == (True, 0, None)


@pytest.mark.parametrize("was", [["scripted"], ["model"], ["cassette", "model"], ["scripted", "model"]])
def test_only_the_minds_declaration_may_differ(was) -> None:
    r = compare(_ledger(was), _ledger(["cassette"]))
    assert (r.equal, r.allowed, r.first_difference) == (True, 1, None)


def _swap(rows: list[tuple], index: int, **fields) -> list[tuple]:
    names = ("id", "ts", "actor", "type", "payload")
    row = dict(zip(names, rows[index]))
    row.update(fields)
    out = list(rows)
    out[index] = tuple(row[n] for n in names)
    return out


DECLARED = ["scripted"]
CASES = {
    "payload of another event": (_ledger(DECLARED), _swap(_ledger(["cassette"]), 0, payload=_payload(world="x")), 1),
    "message payload": (_ledger(DECLARED), _swap(_ledger(["cassette"]), 3, payload=_payload(text="ho")), 4),
    "declaration ts": (_ledger(DECLARED), _swap(_ledger(["cassette"]), 2, ts="2026-01-03T00:00:00"), 3),
    "declaration actor": (_ledger(DECLARED), _swap(_ledger(["cassette"]), 2, actor=9), 3),
    "declaration id": (_ledger(DECLARED), _swap(_ledger(["cassette"]), 2, id=30), 3),
    "replay declares scripted": (_ledger(["model"]), _ledger(["scripted"]), 3),
    "replay declares cassette+model": (_ledger(DECLARED), _ledger(["cassette", "model"]), 3),
    "replay declaration has an extra key": (
        _ledger(DECLARED), _swap(_ledger(["cassette"]), 2, payload=_payload(minds=["cassette"], x=1)), 3),
    "recorded payload is not a kind list": (
        _swap(_ledger(["scripted"]), 2, payload=_payload(minds=["wizard"])), _ledger(["cassette"]), 3),
    "recorded payload has an extra key": (
        _swap(_ledger(["scripted"]), 2, payload=_payload(minds=["scripted"], x=1)), _ledger(["cassette"]), 3),
    "recorded payload is NULL": (
        _swap(_ledger(["scripted"]), 2, payload=None), _ledger(["cassette"]), 3),
    "recorded payload is an integer": (
        _swap(_ledger(["scripted"]), 2, payload=7), _ledger(["cassette"]), 3),
    "recorded payload is not json": (
        _swap(_ledger(["scripted"]), 2, payload="not json"), _ledger(["cassette"]), 3),
    "no declaration in the replay": (_ledger(DECLARED), _ledger(), 3),
    "no declaration in the recording": (_ledger(), _ledger(["cassette"]), 4),  # first differing recorded id
    "a replay trailing event": (_ledger(["cassette"]), _ledger(["cassette"]) + [
        (5, "2026-01-02T00:00:00", 4, "message_sent", _payload(text="more"))], 5),
    "a recorded trailing event": (_ledger(["cassette"]) + [
        (5, "2026-01-02T00:00:00", 4, "message_sent", _payload(text="more"))], _ledger(["cassette"]), 5),
    "an event type": (_ledger(DECLARED), _swap(_ledger(["cassette"]), 3, type="message_read"), 4),
    "whitespace only in a payload": (
        _ledger(["cassette"]), _swap(_ledger(["cassette"]), 0, payload='{"world":  "w"}'), 1),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_other_difference_is_a_difference(name) -> None:
    recorded, replayed, where = CASES[name]
    r = compare(recorded, replayed)
    assert r.equal is False and r.first_difference == where, (name, r)


def test_two_declarations_in_one_ledger_allow_only_the_first_difference() -> None:
    two = _ledger(["scripted"]) + [(5, "2026-01-02T00:00:00", 3, DECL, _payload(minds=["scripted"]))]
    other = _ledger(["cassette"]) + [(5, "2026-01-02T00:00:00", 3, DECL, _payload(minds=["cassette"]))]
    r = compare(two, other)
    assert r.equal is False and r.allowed == 1 and r.first_difference == 5


def test_compare_ledgers_cli_exit_codes(tmp_path: Path, capsys) -> None:
    a = _db(tmp_path / "a.db", _ledger(["scripted"]))
    b = _db(tmp_path / "b.db", _ledger(["cassette"]))
    c = _db(tmp_path / "c.db", _swap(_ledger(["cassette"]), 3, payload=_payload(text="ho")))
    assert cli.main(["compare-ledgers", str(a), str(b)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"allowed": 1, "detail": "equal but for the run_minds_declared payload",
                   "equal": True, "first_difference": None}
    assert cli.main(["compare-ledgers", str(a), str(c)]) == 1
    assert json.loads(capsys.readouterr().out)["first_difference"] == 4
    missing = tmp_path / "missing.db"
    assert cli.main(["compare-ledgers", str(a), str(missing)]) == 2
    assert not missing.exists()  # an error, never a new database
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert cli.main(["compare-ledgers", str(a), str(empty)]) == 2
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not sqlite" * 100)
    assert cli.main(["compare-ledgers", str(junk), str(a)]) == 2
    assert cli.main(["compare-ledgers", str(tmp_path), str(a)]) == 2  # a directory


def test_compare_opens_read_only(tmp_path: Path) -> None:
    a = _db(tmp_path / "a.db", _ledger(["scripted"]))
    b = _db(tmp_path / "b.db", _ledger(["cassette"]))
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (a, b)]
    assert cli.main(["compare-ledgers", str(a), str(b)]) == 0
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in (a, b)] == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.db", "b.db"]  # no journal, no -wal
    with pytest.raises(LedgerFileError):
        ledger_rows(tmp_path / "nope.db")
