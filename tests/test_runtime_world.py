"""M-002 (ADR-045): the Runtime hosts a world of its own (``runtime/world.py``).

Claims under test: a recipe is validated (nothing it holds can become an option, a path or a
second command); the children get a scrubbed environment with exactly three ``FUND_*`` variables;
genesis is the operator's commands, every option one ``--opt=value`` token, in the world's own
directory; a failed genesis or a HALT leaves nothing behind (HALT starts nothing); the server is
stopped and the directory removed on every path; ``backtest --world`` writes a cassette that holds
the recipe and the ledger and never the world key, and touches no database but its own.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from runtime import cassette, cli, world
from runtime.world import SUBCOMMANDS, WorldError, child_env, hosted, parse_recipe
from tests.hosted_month import DESK, WORLD_KEY

RECIPE = {"admin": "desk-mgmt", "pods": [{"allocation": 1000000, "name": "desk-1"}],
          "start": "2024-01-02T14:30:00Z"}


# --- the recipe -------------------------------------------------------------------------

def test_the_desk_recipe_is_valid() -> None:
    assert world.load_world(DESK / "world.json") == RECIPE


@pytest.mark.parametrize("label, change", [
    ("leading dash admin", lambda d: d.update(admin="-x")),
    ("uppercase admin", lambda d: d.update(admin="Desk")),
    ("long admin", lambda d: d.update(admin="a" * 64)),
    ("naive start", lambda d: d.update(start="2024-01-02T14:30:00")),
    ("not a date", lambda d: d.update(start="--help")),
    ("start with a space", lambda d: d.update(start="2024-01-02 14:30:00Z")),
    ("no pods", lambda d: d.update(pods=[])),
    ("17 pods", lambda d: d.update(pods=[{"name": f"p{i}", "allocation": 1} for i in range(17)])),
    ("NaN allocation", lambda d: d["pods"][0].update(allocation=float("nan"))),
    ("infinite allocation", lambda d: d["pods"][0].update(allocation=float("inf"))),
    ("1e13 allocation", lambda d: d["pods"][0].update(allocation=1e13)),
    ("negative allocation", lambda d: d["pods"][0].update(allocation=-1)),
    ("pod name an option", lambda d: d["pods"][0].update(name="--x")),
    ("extra key", lambda d: d.update(extra=1)),
    ("extra pod key", lambda d: d["pods"][0].update(extra=1)),
    ("missing start", lambda d: d.pop("start")),
])
def test_recipe_refuses_bad_values(label, change) -> None:
    doc = json.loads(json.dumps(RECIPE))
    change(doc)
    with pytest.raises(WorldError, match="recipe_invalid"):
        parse_recipe(doc)


def test_load_world_refuses_unreadable_and_oversize_files(tmp_path: Path) -> None:
    for name, raw in {"missing": None, "junk": b"not json", "list": b"[]",
                      "big": b" " * (world.MAX_RECIPE_BYTES + 1)}.items():
        path = tmp_path / f"{name}.json"
        if raw is not None:
            path.write_bytes(raw)
        with pytest.raises(WorldError):
            world.load_world(path)


def test_world_key_comes_from_the_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(world.WORLD_KEY_ENV, raising=False)
    with pytest.raises(WorldError, match="world_key_missing"):
        world.world_key()
    monkeypatch.setenv(world.WORLD_KEY_ENV, "  ")
    with pytest.raises(WorldError, match="world_key_missing"):
        world.world_key()
    monkeypatch.setenv(world.WORLD_KEY_ENV, WORLD_KEY)
    assert world.world_key() == WORLD_KEY


# --- the children's environment ---------------------------------------------------------

def test_child_env_drops_every_fund_variable_but_the_three(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FUND_DATABASE_URL", "FUND_RUNTIME__CLOCK_KEY", "FUND_RUNTIME__REGISTRAR_KEY",
                 "FUND_MCP__API_KEY", "FUND_MARKETDATA__PROVIDER", "FUND_ANYTHING"):
        monkeypatch.setenv(name, "inherited")
    monkeypatch.setenv("PATH_KEPT", "yes")
    env = child_env(Path("/w/world.db"), "k" * 64)
    assert {k for k in env if k.startswith("FUND_")} == {
        "FUND_DATABASE_URL", "FUND_MARKETDATA__PROVIDER", world.WORLD_KEY_ENV}
    assert env["FUND_DATABASE_URL"] == "sqlite:////w/world.db"
    assert env["FUND_MARKETDATA__PROVIDER"] == "synthetic" and env[world.WORLD_KEY_ENV] == "k" * 64
    assert env["PATH_KEPT"] == "yes"  # only FUND_* is scrubbed


# --- genesis, with a stand-in for fund-env ----------------------------------------------

STUB = '''#!/usr/bin/env python3
import json, os, sys
log = os.environ["STUB_LOG"]
with open(log, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(),
                         "fund": sorted(k for k in os.environ if k.startswith("FUND_"))}}) + "\\n")
sub = sys.argv[1]
if sub == os.environ.get("STUB_FAIL"):
    print("boom", file=sys.stderr)
    sys.exit(1)
if sub in ("seed-admin", "seed-runtime"):
    print("API KEY (shown once)")
    print("  fk_" + sub.replace("-", "") + "x" * 20)
'''


@pytest.fixture
def stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "fund-env"
    path.write_text(STUB.format())
    path.chmod(0o755)
    log = tmp_path / "stub.log"
    monkeypatch.setattr(world, "fund_env", lambda: path)
    monkeypatch.setenv("STUB_LOG", str(log))
    work = tmp_path / "tmp"
    work.mkdir()
    monkeypatch.setenv("TMPDIR", str(work))
    monkeypatch.setattr("tempfile.tempdir", None)  # re-read TMPDIR
    return log


def _calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_genesis_argv_is_equals_form_and_listed_subcommands_only(stub: Path, tmp_path: Path) -> None:
    async def go() -> Path:
        async with hosted(RECIPE, WORLD_KEY) as w:
            assert (w.registrar_key, w.clock_key) == ("fk_seedadminxxxxxxxxxxxxxxxxxxxx",
                                                      "fk_seedruntimexxxxxxxxxxxxxxxxxxxx")
            return w.tmp
    tmp = asyncio.run(go())
    calls = _calls(stub)
    assert [c["argv"] for c in calls] == [
        ["init-db"], ["start-backtest", "--start=2024-01-02T14:30:00Z"],
        ["seed-admin", "--name=desk-mgmt"], ["seed-runtime"],
        ["create-pod", "--name=desk-1", "--allocation=1000000.0"]]
    assert all(c["argv"][0] in SUBCOMMANDS for c in calls)
    assert all(a.startswith("--") and "=" in a for c in calls for a in c["argv"][1:])
    assert {c["cwd"] for c in calls} == {str(tmp)}  # the world's own directory
    assert {tuple(c["fund"]) for c in calls} == {(
        "FUND_DATABASE_URL", "FUND_MARKETDATA__PROVIDER", "FUND_MARKETDATA__SYNTHETIC_KEY")}
    assert not tmp.exists() and os.listdir(tmp_path / "tmp") == []  # removed on the way out


def test_a_command_off_the_list_or_with_a_bare_option_is_refused(tmp_path: Path) -> None:
    for argv in (["rm", "-rf"], ["create-pod", "--name", "x"], ["init-db", "-v"]):
        with pytest.raises(WorldError, match="command_not_allowed"):
            world._run(Path("/bin/true"), argv, {}, tmp_path)


def test_failed_genesis_is_a_world_error_and_cleans_up(
        stub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUB_FAIL", "seed-runtime")

    async def go() -> None:
        async with hosted(RECIPE, WORLD_KEY):
            raise AssertionError("not reached")
    with pytest.raises(WorldError) as caught:
        asyncio.run(go())
    assert caught.value.reason == "genesis:seed-runtime:1" and caught.value.detail == "boom"
    assert [c["argv"][0] for c in _calls(stub)] == [
        "init-db", "start-backtest", "seed-admin", "seed-runtime"]  # stopped at the failure
    assert os.listdir(tmp_path / "tmp") == []


def test_halt_spawns_nothing(stub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime import governance
    halt = tmp_path / "HALT"
    halt.write_text("")
    monkeypatch.setattr(governance, "HALT_FILE", halt)

    async def go() -> None:
        async with hosted(RECIPE, WORLD_KEY):
            raise AssertionError("not reached")
    with pytest.raises(WorldError, match="halted"):
        asyncio.run(go())
    assert _calls(stub) == [] and os.listdir(tmp_path / "tmp") == []


# --- the real thing ---------------------------------------------------------------------

def test_server_is_stopped_and_the_directory_removed_on_every_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tempfile.tempdir", None)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    seen: dict = {}

    async def go() -> None:
        async with hosted(RECIPE, WORLD_KEY) as w:
            await w.serve()
            seen.update(server=w._server, tmp=w.tmp, url=w.url)
            raise RuntimeError("the run blew up")
    with pytest.raises(RuntimeError, match="blew up"):
        asyncio.run(go())
    assert seen["server"].poll() is not None  # stopped
    assert not seen["tmp"].exists()


def test_hosted_backtest_writes_world_and_ledger_e2e(hosted_cassette) -> None:
    rec = hosted_cassette
    cas = cassette.read(rec.path)
    assert stat.S_IMODE(rec.path.stat().st_mode) == 0o600
    assert cas.world == {"recipe": RECIPE}
    rows = cas.ledger["rows"]
    assert rows[0][3] == "run_started"
    declared = [r for r in rows if r[3] == "run_minds_declared"]
    assert len(declared) == 1 and json.loads(declared[0][4]) == {"minds": ["scripted"]}
    assert sum(r[3] == "clock_advanced" for r in rows) == 3
    assert (cas.parameters["steps"], cas.outcome["run"]["ended"]) == (3, "completed")
    # The world key is nowhere: not in the file, not on stdout, not on stderr.
    raw = rec.path.read_text(encoding="ascii")
    assert WORLD_KEY not in raw + rec.stdout + rec.stderr
    assert rec.outcome["ended"] == "completed"


def test_hosted_run_leaves_the_operators_database_untouched(hosted_cassette) -> None:
    """The recording ran under a planted ``FUND_DATABASE_URL``: no command honoured it."""
    assert not hosted_cassette.sentinel.exists()


def test_hosted_cassette_is_the_same_bytes_twice(hosted_cassette, tmp_path: Path) -> None:
    """Determinism: the same recipe, key, specs and parameters give byte-equal cassettes (no
    minted key is in the file)."""
    from tests.hosted_month import record
    again = record(tmp_path)
    assert again.path.read_bytes() == hosted_cassette.path.read_bytes()


# --- the command ------------------------------------------------------------------------

def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return ["backtest", "--specs", str(DESK), "--steps", "2", *extra,
            "--cassette", str(tmp_path / "x.cassette.json")]


def test_world_and_server_are_exclusive(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv(world.WORLD_KEY_ENV, WORLD_KEY)
    code = cli.main(_argv(tmp_path, "--world", str(DESK / "world.json"),
                          "--server", "http://127.0.0.1:1"))
    assert code == 2 and "exclusive" in capsys.readouterr().err


def test_world_needs_a_cassette_and_a_key_and_a_valid_recipe(
        tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv(world.WORLD_KEY_ENV, WORLD_KEY)
    no_cassette = ["backtest", "--specs", str(DESK), "--steps", "2", "--world",
                   str(DESK / "world.json")]
    assert cli.main(no_cassette) == 2 and "--cassette" in capsys.readouterr().err
    monkeypatch.delenv(world.WORLD_KEY_ENV)
    assert cli.main(_argv(tmp_path, "--world", str(DESK / "world.json"))) == 2
    assert "world_key_missing" in capsys.readouterr().err
    monkeypatch.setenv(world.WORLD_KEY_ENV, WORLD_KEY)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**RECIPE, "admin": "-x"}))
    assert cli.main(_argv(tmp_path, "--world", str(bad))) == 2
    assert "recipe_invalid" in capsys.readouterr().err
    assert not (tmp_path / "x.cassette.json").exists()  # nothing began


def test_world_ignores_the_runtime_keys_in_the_environment(
        tmp_path: Path, monkeypatch, capsys) -> None:
    """A hosted run mints its own keys: ``FUND_RUNTIME__*`` neither required nor read."""
    monkeypatch.delenv(cli.REGISTRAR_KEY_ENV, raising=False)
    monkeypatch.delenv(cli.CLOCK_KEY_ENV, raising=False)
    monkeypatch.setenv(world.WORLD_KEY_ENV, "nothex")  # genesis refuses it: exit 1, not a usage error
    code = cli.main(_argv(tmp_path, "--world", str(DESK / "world.json")))
    err = capsys.readouterr().err
    assert code == 1 and "genesis:init-db" in err and "KEY" not in err.replace("synthetic_key", "")
    assert not (tmp_path / "x.cassette.json").exists()
