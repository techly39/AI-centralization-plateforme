"""M-002 (ADR-045): cassette v2 — the proof object's file.

Claims under test: the document is canonical (sorted, compact, ASCII) and round-trips; version 1
is refused **by name** everywhere; the size cap binds the writer and the reader at its boundary;
the top-level keys, the parameters' ranges and the shapes of specs / world / ledger are exact;
the reader is total (a ``Cassette`` or a ``CassetteError``, nothing else); redaction cannot merge
two keys.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from runtime import cassette
from runtime.cassette import HASH_FORMAT, CassetteError
from runtime.providers import ToolSpec
from tests.cassette_parts import PARTS


def _doc_of(outcome=None, **more) -> dict:
    text, _ = cassette.dumps(outcome if outcome is not None else {"run": None}, **(PARTS | more))
    return json.loads(text)


def _put(path: Path, doc) -> Path:
    path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="ascii")
    return path


def test_v2_document_is_sorted_compact_ascii_and_round_trips(tmp_path: Path) -> None:
    ledger = {"ledger_format": cassette.LEDGER_FORMAT, "rows": [[1, "t", None, "run_started", "{}"]]}
    path = tmp_path / "r.cassette.json"
    specs = [{"id": "b", "x": "é"}, {"id": "a"}]
    cassette.write(path, {"run": None}, parameters=PARTS["parameters"], specs=specs,
                   world={"recipe": {"admin": "m"}}, ledger=ledger)
    text = path.read_text(encoding="ascii")
    doc = json.loads(text)
    assert text == json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert set(doc) == {"cassette_version", "hash_format", "ledger", "outcome", "parameters",
                        "redactions", "specs", "world"} and doc["cassette_version"] == 2
    got = cassette.read(path)
    assert (got.outcome, got.redactions, got.parameters) == ({"run": None}, 0, PARTS["parameters"])
    assert [e["spec"]["id"] for e in got.specs] == ["a", "b"]  # sorted by id
    assert all(e["sha256"] == cassette.spec_sha256(e["spec"]) for e in got.specs)
    assert (got.world, got.ledger) == ({"recipe": {"admin": "m"}}, ledger)


def test_v1_is_refused_by_name(tmp_path: Path) -> None:
    """Counter-example to 'v1 is still read': a hand-built canonical v1 file."""
    path = _put(tmp_path / "v1.cassette.json", {
        "cassette_version": 1, "hash_format": HASH_FORMAT, "outcome": {"run": None},
        "redactions": 0})
    with pytest.raises(CassetteError, match="cassette version 1"):
        cassette.read(path)
    with pytest.raises(CassetteError, match="version 2 only"):
        cassette.read(_put(tmp_path / "v3.cassette.json", {"cassette_version": 3}))
    with pytest.raises(CassetteError, match="version 2 only"):  # True == 1 in Python
        cassette.read(_put(tmp_path / "vt.cassette.json", {"cassette_version": True}))


def test_size_cap_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = tmp_path / "ok.cassette.json"
    cassette.write(good, {"run": None}, **PARTS)
    size = good.stat().st_size
    monkeypatch.setattr(cassette, "MAX_CASSETTE_BYTES", size)
    assert cassette.read(good).outcome == {"run": None}  # at the cap: read
    monkeypatch.setattr(cassette, "MAX_CASSETTE_BYTES", size - 1)
    with pytest.raises(CassetteError, match="over"):  # one over: refused
        cassette.read(good)
    link = tmp_path / "l.cassette.json"
    link.symlink_to(good)
    monkeypatch.setattr(cassette, "MAX_CASSETTE_BYTES", size)
    with pytest.raises(CassetteError):  # the cap does not loosen the other refusals
        cassette.read(link)
    fifo = tmp_path / "f.cassette.json"
    os.mkfifo(fifo)
    with pytest.raises(CassetteError):
        cassette.read(fifo)


def test_writer_refuses_over_cap_and_leaves_no_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cassette, "MAX_CASSETTE_BYTES", 100)
    path = tmp_path / "big.cassette.json"
    with pytest.raises(CassetteError, match="over"):
        cassette.write(path, {"padding": "x" * 200}, **PARTS)
    assert not path.exists()


@pytest.mark.parametrize("change", [
    lambda d: d.pop("ledger"), lambda d: d.pop("parameters"), lambda d: d.pop("specs"),
    lambda d: d.pop("world"), lambda d: d.update(extra=1), lambda d: d.update(redactions=-1),
    lambda d: d.update(redactions=True), lambda d: d.update(hash_format="other"),
    lambda d: d.update(outcome=[]),
])
def test_exact_top_level_keys_and_types(tmp_path: Path, change) -> None:
    doc = _doc_of()
    change(doc)
    with pytest.raises(CassetteError):
        cassette.read(_put(tmp_path / "x.cassette.json", doc))


@pytest.mark.parametrize("field, value", [
    ("steps", 0), ("steps", 3661), ("steps", True), ("steps", 1.0), ("days_per_step", 0),
    ("days_per_step", 367), ("max_tool_calls", 1025), ("max_tool_calls", -1),
    ("workflow_input", []), ("workflow_input", None),
])
def test_parameters_are_range_checked_on_read(tmp_path: Path, field: str, value) -> None:
    doc = _doc_of()
    doc["parameters"][field] = value
    with pytest.raises(CassetteError, match="parameters"):
        cassette.read(_put(tmp_path / "p.cassette.json", doc))
    bad = dict(PARTS["parameters"], **{field: value})
    with pytest.raises(CassetteError, match="parameters"):  # the writer refuses the same
        cassette.dumps({"run": None}, parameters=bad, specs=PARTS["specs"])


def test_parameter_bounds_are_the_conductors() -> None:
    from runtime import cli, lockstep
    assert cassette.STEPS_RANGE == (1, lockstep.MAX_STEPS)
    assert cassette.DAYS_PER_STEP_RANGE == (1, lockstep.MAX_DAYS_PER_STEP)
    assert cassette.MAX_TOOL_CALLS_RANGE == (0, cli.MAX_TOOL_CALLS)


def test_bad_specs_world_and_ledger_are_refused(tmp_path: Path) -> None:
    rows_ok = {"ledger_format": cassette.LEDGER_FORMAT, "rows": [1]}
    for field, value in (("specs", [{"sha256": "0" * 64}]), ("specs", [{"sha256": "x", "spec": {}}]),
                         ("specs", {}), ("world", {"recipe": []}), ("world", {}),
                         ("ledger", {"ledger_format": "other", "rows": []}), ("ledger", rows_ok)):
        doc = _doc_of()
        doc[field] = value
        with pytest.raises(CassetteError):
            cassette.read(_put(tmp_path / f"{field}.cassette.json", doc))


def test_spec_sha256_golden() -> None:
    """sha256 of the canonical JSON ``{"a":"x","b":1}``, written out by hand."""
    assert cassette.spec_sha256({"b": 1, "a": "x"}) == (
        "cdab067e9f3beb32d1252cfd63e492592fecbf591b0d08cadb24bb17f3864246")


def test_tools_sha256_is_of_the_tools_in_order() -> None:
    a = ToolSpec(name="a", description="x", input_schema={})
    b = ToolSpec(name="b", description="x", input_schema={})
    assert cassette.tools_sha256([a, b]) == cassette.tools_sha256([a.model_copy(), b.model_copy()])
    assert cassette.tools_sha256([a, b]) != cassette.tools_sha256([b, a])
    assert cassette.tools_sha256([a]) != cassette.tools_sha256([a, b])


def test_redaction_collision_refused_at_write(tmp_path: Path) -> None:
    """Two keys that differ only in a minted key would collapse into one: refused, no file."""
    path = tmp_path / "c.cassette.json"
    with pytest.raises(CassetteError, match="twice"):
        cassette.write(path, {"run": {"fk_" + "A" * 43: 1, "fk_" + "B" * 43: 2}}, **PARTS)
    assert not path.exists()


def test_the_reader_is_total(tmp_path: Path) -> None:
    for i, raw in enumerate((b"", b"\xff", b"[]", b"{}", b'{"cassette_version":2}', b"null",
                             b"[" * 100000)):
        path = tmp_path / f"t{i}.cassette.json"
        path.write_bytes(raw)
        with pytest.raises(CassetteError):
            cassette.read(path)
