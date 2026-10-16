"""M-002 (ADR-045), physics side: a ledger as a file.

``fund-env export-ledger`` writes a database's ledger as a canonical rows document; a
``*.ledger.json`` is read anywhere a database is (``compare-ledgers``), under the same law
(``compare`` is untouched: equal length, raw rows, one allowed difference). ``locate`` says where
in the run an event sits. ``run-minds`` (B-051) prints what the ledger proves drove the minds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import cli
from app.ledger.compare import (
    LedgerFileError,
    compare,
    ledger_rows,
    locate,
    read_rows_file,
    rows_document,
)
from app.registry.service import seed_runtime_agent
from app.run_clock import declare_minds, start_backtest
from tests.test_ledger_compare import CASES, _db, _ledger, _payload
from tests.test_runtime_key import cli_on_test_db, live_afterwards  # noqa: F401 - fixtures

ADV = "clock_advanced"


def _export(db: Path, dest: Path, capsys) -> Path:
    assert cli.main(["export-ledger", str(db)]) == 0
    dest.write_text(capsys.readouterr().out.strip(), encoding="ascii")
    return dest


def _is_text_row(row: tuple) -> bool:
    return isinstance(row[4], str)


def test_export_ledger_round_trips_through_compare(tmp_path: Path, capsys) -> None:
    db = _db(tmp_path / "a.db", _ledger(["scripted"]))
    out = _export(db, tmp_path / "a.ledger.json", capsys)
    assert ledger_rows(out) == ledger_rows(db)
    assert out.read_text(encoding="ascii") == rows_document(ledger_rows(db))  # canonical
    other = _db(tmp_path / "b.db", _ledger(["cassette"]))
    assert cli.main(["compare-ledgers", str(out), str(other)]) == 0
    assert json.loads(capsys.readouterr().out)["allowed"] == 1


def test_export_ledger_is_read_only_and_refuses_what_is_not_a_fund_database(
        tmp_path: Path, capsys) -> None:
    db = _db(tmp_path / "a.db", _ledger(["scripted"]))
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    assert cli.main(["export-ledger", str(db)]) == 0
    capsys.readouterr()
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.db"]
    assert cli.main(["export-ledger", str(tmp_path / "missing.db")]) == 2
    assert not (tmp_path / "missing.db").exists()
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not sqlite" * 100)
    assert cli.main(["export-ledger", str(junk)]) == 2


@pytest.mark.parametrize("label, doc", [
    ("not an object", []),
    ("extra key", {"ledger_format": "fund-ledger-rows/1", "rows": [], "x": 1}),
    ("other format", {"ledger_format": "fund-ledger-rows/2", "rows": []}),
    ("rows not a list", {"ledger_format": "fund-ledger-rows/1", "rows": {}}),
    ("a short row", {"ledger_format": "fund-ledger-rows/1", "rows": [[1, "t", None, "x"]]}),
    ("bool as id", {"ledger_format": "fund-ledger-rows/1", "rows": [[True, "t", None, "x", "{}"]]}),
    ("float id", {"ledger_format": "fund-ledger-rows/1", "rows": [[1.0, "t", None, "x", "{}"]]}),
    ("zero id", {"ledger_format": "fund-ledger-rows/1", "rows": [[0, "t", None, "x", "{}"]]}),
    ("non-increasing ids", {"ledger_format": "fund-ledger-rows/1",
                            "rows": [[2, "t", None, "x", "{}"], [2, "t", None, "x", "{}"]]}),
    ("payload not text", {"ledger_format": "fund-ledger-rows/1", "rows": [[1, "t", None, "x", {}]]}),
    ("actor a string", {"ledger_format": "fund-ledger-rows/1", "rows": [[1, "t", "1", "x", "{}"]]}),
])
def test_rows_file_reader_is_strict(tmp_path: Path, label: str, doc) -> None:
    path = tmp_path / "x.ledger.json"
    path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="ascii")
    with pytest.raises(LedgerFileError):
        read_rows_file(path)
    with pytest.raises(LedgerFileError):  # ledger_rows dispatches on the suffix
        ledger_rows(path)


def test_rows_file_reader_refuses_the_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = tmp_path / "good.ledger.json"
    good.write_text(rows_document(_ledger(["scripted"])), encoding="ascii")
    assert len(read_rows_file(good)) == 4  # the control: the builder is right
    text = good.read_text(encoding="ascii")
    cases = {
        "pretty": json.dumps(json.loads(text), indent=2),
        "unsorted": '{"rows":' + text.split('"rows":', 1)[1].rsplit("}", 1)[0]
                    + ',"ledger_format":"fund-ledger-rows/1"}',
        "non-ascii": text.replace("run_started", "rün_started").encode("utf-8"),
        "NaN": text.replace('"rows":[', '"rows":[NaN,', 1),
        "duplicate key": '{"ledger_format":"fund-ledger-rows/1","ledger_format":"x","rows":[]}',
        "trailing": text + "\n",
        "too deep": "[" * 100_000,
        "empty": "",
    }
    for label, raw in cases.items():
        path = tmp_path / f"{label.replace(' ', '-')}.ledger.json"
        path.write_bytes(raw if isinstance(raw, bytes) else raw.encode("ascii"))
        with pytest.raises(LedgerFileError):
            read_rows_file(path)
    link = tmp_path / "link.ledger.json"
    link.symlink_to(good)
    with pytest.raises(LedgerFileError):
        read_rows_file(link)
    fifo = tmp_path / "fifo.ledger.json"
    os.mkfifo(fifo)
    with pytest.raises(LedgerFileError):
        read_rows_file(fifo)
    with pytest.raises(LedgerFileError):
        read_rows_file(tmp_path)  # a directory
    monkeypatch.setattr("app.ledger.compare.MAX_ROWS_BYTES", len(text) - 1)
    with pytest.raises(LedgerFileError, match="at most|over"):
        read_rows_file(good)
    monkeypatch.setattr("app.ledger.compare.MAX_ROWS_BYTES", len(text))
    assert len(read_rows_file(good)) == 4  # at the cap: read


@pytest.mark.parametrize("name", sorted(CASES))
def test_file_and_database_give_the_same_comparison(tmp_path: Path, name: str) -> None:
    recorded, replayed, _ = CASES[name]
    if not all(_is_text_row(r) for r in recorded + replayed):
        pytest.skip("a database can hold a non-text payload; a rows file cannot")
    if any([r[0] for r in rows] != sorted({r[0] for r in rows}) for rows in (recorded, replayed)):
        pytest.skip("a database is read ORDER BY id, so an export is always increasing")
    a_file = tmp_path / "a.ledger.json"
    a_file.write_text(rows_document(recorded), encoding="ascii")
    b_file = tmp_path / "b.ledger.json"
    b_file.write_text(rows_document(replayed), encoding="ascii")
    a_db = _db(tmp_path / "a.db", recorded)
    b_db = _db(tmp_path / "b.db", replayed)
    want = compare(ledger_rows(a_db), ledger_rows(b_db))
    assert compare(ledger_rows(a_file), ledger_rows(b_file)) == want
    assert compare(ledger_rows(a_file), ledger_rows(b_db)) == want  # mixed
    assert want == compare(recorded, replayed)


def test_rows_file_does_not_widen_the_law(tmp_path: Path, capsys) -> None:
    """Counter-example to 'a rows file is a looser comparison': a second declaration, or a replay
    that declares anything but ``cassette``, is unequal from a file as from a database."""
    two = _ledger(["scripted"]) + [(5, "2026-01-02T00:00:00", 3, "run_minds_declared",
                                    _payload(minds=["scripted"]))]
    other = _ledger(["cassette"]) + [(5, "2026-01-02T00:00:00", 3, "run_minds_declared",
                                      _payload(minds=["cassette"]))]
    scripted_again = _ledger(["scripted"])
    for label, (rec, rep) in {"two declarations": (two, other),
                              "replay declares scripted": (_ledger(["scripted"]), scripted_again),
                              "replay declares cassette+model": (
                                  _ledger(["scripted"]), _ledger(["cassette", "model"]))}.items():
        a, b = tmp_path / f"{len(label)}a.ledger.json", tmp_path / f"{len(label)}b.ledger.json"
        a.write_text(rows_document(rec), encoding="ascii")
        b.write_text(rows_document(rep), encoding="ascii")
        want = 0 if label == "replay declares scripted" else 1
        # A replay that declares "scripted" again is not the allowed difference: it is *equal*
        # with allowed == 0 (identical rows); the others must differ.
        code = cli.main(["compare-ledgers", str(a), str(b)])
        out = json.loads(capsys.readouterr().out)
        assert code == want, (label, out)
        if want == 1:
            assert out["equal"] is False and out["locate"] is not None


def test_compare_ledgers_names_where_the_first_difference_is(tmp_path: Path, capsys) -> None:
    rows = [(1, "t", None, "run_started", "{}"), (2, "t", 3, "run_minds_declared", '{"minds":["scripted"]}'),
            (3, "t", 4, "message_sent", "{}"), (4, "t", None, ADV, "{}"), (5, "t", 4, "message_sent", "{}"),
            (6, "t", None, ADV, "{}"), (7, "t", 5, "message_sent", "{}")]
    changed = list(rows)
    changed[6] = (7, "t", 5, "message_sent", "{ }")
    a, b = _db(tmp_path / "a.db", rows), _db(tmp_path / "b.db", changed)
    assert cli.main(["compare-ledgers", str(a), str(b)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["locate"] == {"event_id": 7, "step": 2, "actor_agent_id": 5, "type": "message_sent",
                             "genesis": False}
    assert cli.main(["compare-ledgers", str(a), str(a)]) == 0
    assert json.loads(capsys.readouterr().out)["locate"] is None  # null, not 0


def test_locate_counts_advances_and_flags_genesis() -> None:
    rows = [(1, "t", None, "run_started", "{}"), (2, "t", 1, "pod_funded", "{}"),
            (3, "t", 3, "run_minds_declared", '{"minds":["scripted"]}'),
            (4, "t", 4, "message_sent", "{}"), (5, "t", 3, ADV, "{}"),
            (6, "t", 4, "message_sent", "{}"), (7, "t", 3, ADV, "{}"), (8, "t", 4, "message_sent", "{}")]
    assert locate(rows, 1) == {"event_id": 1, "step": 0, "actor_agent_id": None,
                               "type": "run_started", "genesis": True}
    assert locate(rows, 2)["genesis"] is True
    assert locate(rows, 3)["genesis"] is False  # the declaration closes the genesis
    assert [locate(rows, i)["step"] for i in (4, 5, 6, 7, 8)] == [0, 0, 1, 1, 2]
    assert locate(rows, 99) is None and locate([], 1) is None


def test_init_db_works_from_another_working_directory(tmp_path: Path) -> None:
    """Found planning M-002: ``alembic.ini``'s relative ``script_location`` made ``init-db``
    depend on the cwd."""
    fund_env = Path(sys.executable).parent / "fund-env"
    env = {k: v for k, v in os.environ.items() if not k.startswith("FUND_")}
    db = tmp_path / "elsewhere.db"
    env["FUND_DATABASE_URL"] = f"sqlite:///{db}"
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    r = subprocess.run([str(fund_env), "init-db"], cwd=workdir, env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert db.is_file() and list(workdir.iterdir()) == []
    r = subprocess.run([str(fund_env), "export-ledger", str(db)], cwd=workdir, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and json.loads(r.stdout)["rows"] == []


def test_run_minds_command(cli_on_test_db, db, capsys) -> None:  # noqa: F811
    """B-051: the operator reads what the ledger proves drove the minds, without raw SQL."""
    from datetime import datetime, timezone
    assert cli.main(["run-minds"]) == 0
    assert json.loads(capsys.readouterr().out) == {"minds": None}  # a live run: no declaration
    start_backtest(db, start=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc))
    agent, _ = seed_runtime_agent(db)
    declare_minds(db, minds=["scripted"], actor_agent_id=agent.id)
    assert cli.main(["run-minds"]) == 0
    assert json.loads(capsys.readouterr().out) == {"minds": ["scripted"]}
