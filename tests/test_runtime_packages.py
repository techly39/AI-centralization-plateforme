"""The day's data package (runtime/packages.py): each wake is handed its own day, never tomorrow."""

from __future__ import annotations

import json

import pytest

from runtime import packages
from tests.test_runtime_cli_backtest import _run, keys, specs  # noqa: F401 - fixtures
from tests.test_runtime_lockstep import gov, live_afterwards, woke, world  # noqa: F401 - fixtures


def _input(tmp_path, doc) -> str:
    (tmp_path / "input.json").write_text(json.dumps(doc))
    return str(tmp_path / "input.json")


def _context(wake: dict) -> dict:
    return json.loads(wake["transcript"][1]["content"])


def test_every_wake_gets_its_own_days_package_and_nothing_later(
        SessionFactory, keys, specs, woke, tmp_path, capsys) -> None:
    code, out, err = _run(SessionFactory, [
        "--specs", str(specs), "--steps", "4", "--package", "prices-v1",
        "--input", _input(tmp_path, {"universe": ["NVDA", "AAPL", "AAPL"]})], capsys)
    assert code == 0 and out["ended"] == "completed", err
    days = []
    for step in out["run"]["steps"]:
        day = step["at"][:10]
        for w in step["wakes"]:
            pkg = _context(w)["package"]
            assert (pkg["name"], pkg["day"], pkg["columns"]) == (
                "prices-v1", day, ["day", "open", "high", "low", "close", "volume"])
            assert sorted(pkg["bars"]) == ["AAPL", "NVDA"]        # sorted, once each
            assert all(row[0] <= day for rows in pkg["bars"].values() for row in rows)
            assert all(len(row) == 6 for rows in pkg["bars"].values() for row in rows)
        days.append(day)
    assert len(set(days)) == 4                                     # a new day every step
    first, last = (_context(out["run"]["steps"][i]["wakes"][0])["package"] for i in (0, 3))
    assert first["bars"]["AAPL"] and last["bars"]["AAPL"][-1][0] > first["bars"]["AAPL"][-1][0]


def test_a_run_without_a_package_shows_none(SessionFactory, keys, specs, woke, capsys) -> None:
    code, out, _ = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert code == 0 and "package" not in _context(out["run"]["steps"][0]["wakes"][0])


def test_an_unknown_ticker_is_listed_unavailable_not_hidden(
        SessionFactory, keys, specs, woke, tmp_path, capsys) -> None:
    code, out, _ = _run(SessionFactory, [
        "--specs", str(specs), "--steps", "1", "--package", "prices-v1",
        "--input", _input(tmp_path, {"universe": ["AAPL", "NOPE/../agents"]})], capsys)
    assert code == 0
    pkg = _context(out["run"]["steps"][0]["wakes"][0])["package"]
    assert list(pkg["bars"]) == ["AAPL"] and set(pkg["unavailable"]) == {"NOPE/../agents"}


@pytest.mark.parametrize("name, doc", [("prices-v9", {"universe": ["SYNA"]}),
                                       ("prices-v1", {}), ("prices-v1", {"universe": []}),
                                       ("prices-v1", {"universe": [".."]}),
                                       ("prices-v1", {"universe": "SYNA"})])
def test_a_package_the_run_cannot_have_is_a_usage_error(
        SessionFactory, keys, specs, woke, tmp_path, capsys, name, doc) -> None:
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "1",
                                           "--package", name, "--input", _input(tmp_path, doc)],
                          capsys)
    assert code == 2 and out is None and woke == [] and "package" in err


def test_the_package_names_are_known() -> None:
    assert packages.PACKAGES == frozenset({"prices-v1"})
