"""A metered month is a proof object too (ADR-047, on ADR-044 §6): recorded in a world of its own
with its data packages, it verifies IDENTICAL with its trailing cost rows reported apart; a cost
row that is not the recording's reads DIVERGED; no provider key ever reaches the file."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

from runtime import cassette, cli, verify, world
from tests.hosted_month import DESK

KEY = hashlib.sha256(b"fund-tests-metered-cassette/1").hexdigest()
STEPS = 3


def _metered_desk(directory: Path) -> Path:
    directory.mkdir()
    for path in DESK.glob("*.yaml"):
        spec = yaml.safe_load(path.read_text())
        spec.update(provider="fake-metered", budget_usd=2.0)
        (directory / path.name).write_text(yaml.safe_dump(spec))
    return directory


def _main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("metered")
    path = d / "m.cassette.json"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(world.WORLD_KEY_ENV, KEY)
        mp.setenv("FUND_DATABASE_URL", f"sqlite:///{d / 'sentinel.db'}")
        code, out, err = _main("backtest", "--world", str(DESK / "world.json"),
                               "--specs", str(_metered_desk(d / "specs")),
                               "--input", str(DESK / "input.json"), "--steps", str(STEPS),
                               "--package", "prices-v1", "--cassette", str(path))
    assert code == 0, err[-2000:]
    return path


def _verify(path: Path) -> tuple[int, str, dict]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(world.WORLD_KEY_ENV, KEY)
        code, out, _ = _main("replay", "--cassette", str(path), "--verify")
    line, _, rest = out.partition("\n")
    return code, line, json.loads(rest) if rest.strip() else {}


def test_a_metered_month_verifies_identical_with_its_cost_rows_apart(recorded) -> None:
    doc = json.loads(recorded.read_text(encoding="ascii"))
    assert doc["parameters"]["package"] == "prices-v1"
    keys = doc["outcome"]["metering"]["keys"]
    rows = doc["ledger"]["rows"]
    assert [r[3] for r in rows[-len(keys):]] == ["cost_metered"] * len(keys)
    code, line, ev = _verify(recorded)
    assert code == 0 and line == (f"IDENTICAL: {len(rows) - len(keys)} events, 0 differences, $0 "
                                  "(allowed: run_minds_declared scripted -> cassette) "
                                  f"(+{len(keys)} metered cost rows of the recorded run, reported apart)")
    assert ev["metered_block"] == {"rows": len(keys),
                                   "usd_micros": sum(k["spent_usd_micros"] for k in keys)}
    assert ev["replay_usd"] == 0


def _tampered(recorded: Path, tmp_path: Path, edit) -> Path:
    doc = json.loads(recorded.read_text(encoding="ascii"))
    edit(doc)
    path = tmp_path / "t.cassette.json"
    path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="ascii")
    return path


def _bump_last_cost(doc) -> None:
    body = json.loads(doc["ledger"]["rows"][-1][4])
    body["usd_micros_total"] += 1
    doc["ledger"]["rows"][-1][4] = json.dumps(body, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("edit, why", [
    (_bump_last_cost, "not one of the recorded keys' totals"),
    (lambda d: d["ledger"]["rows"].pop(), "the recorded sync posted"),
    (lambda d: d["ledger"]["rows"].append(copy.deepcopy(d["ledger"]["rows"][-1])), "the recorded sync posted"),
])
def test_a_cost_row_that_is_not_the_recordings_reads_diverged(recorded, tmp_path, edit, why) -> None:
    code, line, ev = _verify(_tampered(recorded, tmp_path, edit))
    assert code == verify.EXIT_DIVERGED and line.startswith("DIVERGED at the metered cost rows")
    assert why in line and ev["where"]["kind"] == "metered_block"


def test_cost_rows_on_a_run_that_metered_nothing_are_not_explained_away(recorded, tmp_path) -> None:
    code, line, _ = _verify(_tampered(recorded, tmp_path, lambda d: d["outcome"].pop("metering")))
    assert code == verify.EXIT_DIVERGED and "metered nothing" in line


def test_a_provider_key_never_reaches_a_cassette() -> None:
    text, n = cassette.redact_count('{"a": "sk-or-v1-abcdef0123456789", "b": "fk_abc"}')
    assert n == 2 and "sk-or-v1" not in text and "sk-or-<redacted>" in text
