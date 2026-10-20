"""A world the Runtime hosts for itself: the recorded run's own database (M-002, ADR-045).

``fund-runtime backtest --world FILE`` and ``fund-runtime replay --verify`` need a fresh database
whose genesis is exactly the recipe in ``FILE`` (or in the cassette), because the ledger alone is
not a genesis (pods and the ``system`` agent leave no event) and the Runtime is ledger-blind
(ADR-022/033/040). So this module builds the world with physics' own **operator commands**
(``fund-env init-db``, ``start-backtest``, ``seed-admin``, ``seed-runtime``, ``create-pod``),
serves it on a loopback port, and, when the run is over, asks physics to write the ledger down
(``fund-env export-ledger``) or to compare two ledgers (``fund-env compare-ledgers``). It never
opens a database itself and imports nothing from ``app``.

**This is the only module of the Runtime that starts a process** (pinned by an AST test), and the
only program it starts is ``<this interpreter's bin>/fund-env`` (no ``PATH`` lookup), with the
sub-commands in :data:`SUBCOMMANDS`, every option as one ``--opt=value`` token (a value can never
be read as an option), a working directory that is the world's own temporary directory, and an
environment holding **no** ``FUND_*`` variable but the three it sets: its own database, the
synthetic market and the world key. The world key is never printed, logged or stored: it comes
from the environment (red-team 0010) and goes to the children by environment only. The server is
stopped and the directory removed on every path out, an exception or an interrupt too.

HALT is read before anything is started (Art. 5); the conductor reads it again at every step.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from runtime.cassette import LEDGER_FORMAT, redact
from runtime.governance import read_governance

#: The environment variable that names the world's synthetic market (a throwaway secret).
WORLD_KEY_ENV = "FUND_MARKETDATA__SYNTHETIC_KEY"
#: The only ``fund-env`` sub-commands this module runs.
SUBCOMMANDS = frozenset({"init-db", "start-backtest", "seed-admin", "seed-runtime", "create-pod",
                         "serve", "export-ledger", "compare-ledgers"})
#: A recipe file bigger than this is refused (64 KiB).
MAX_RECIPE_BYTES = 64 * 1024
MAX_PODS = 16
MAX_EXTRA_SYMBOLS = 50
_NAME = r"^[a-z][a-z0-9-]{0,62}$"
_KEY = re.compile(r"\bfk_\S+")
_SERVE_WAIT_SECONDS = 60
_COMMAND_TIMEOUT = 300


class WorldError(Exception):
    """The world could not be built, served, read or compared. ``reason`` is a short code; it
    never holds output of a child (which can hold a key)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        #: The tail of a failed child's stderr, keys redacted: for the operator's terminal only.
        self.detail = detail


class PodRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(pattern=_NAME)
    allocation: float = Field(ge=0, le=1e12)


class WorldRecipe(BaseModel):
    """What the operator would type to open a run: its start, its management agent, its pods."""
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    start: str
    admin: str = Field(pattern=_NAME)
    pods: tuple[PodRecipe, ...] = Field(min_length=1, max_length=MAX_PODS)
    #: Symbols that join the configured synthetic market (``config.yaml``), each with its price
    #: on the market's first day (ADR-048: a universe wide enough for many predictions).
    extra_symbols: dict[str, float] | None = Field(default=None, max_length=MAX_EXTRA_SYMBOLS)
    #: A made-up market with a planted law instead of the synthetic one (physics validates it:
    #: ``app/marketdata/made_up.py``), e.g. a sector that collapses so the ladder closes a pod.
    market: dict[str, Any] | None = None

    @field_validator("extra_symbols")
    @classmethod
    def _symbols_are_tickers_with_prices(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is not None and not all(re.fullmatch(r"[A-Z][A-Z0-9]{0,15}", t) and 0 < p <= 1e6
                                         for t, p in value.items()):
            raise ValueError("extra_symbols: upper-case tickers, each priced in (0, 1e6]")
        return value

    @field_validator("start")
    @classmethod
    def _start_is_an_aware_iso_moment(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9TZ:.+\-]{10,40}", value):
            raise ValueError("start is an ISO-8601 moment")
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("start carries a timezone")
        return value


def parse_recipe(doc: Any) -> WorldRecipe:
    """``doc`` (parsed JSON) as a recipe, else :class:`WorldError`."""
    try:
        return WorldRecipe.model_validate(doc)
    except (ValidationError, TypeError, ValueError) as exc:
        raise WorldError(f"recipe_invalid:{type(exc).__name__}") from exc


def load_world(path: Path) -> dict[str, Any]:
    """The recipe file at ``path`` as a JSON object (validated), else :class:`WorldError`."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_RECIPE_BYTES + 1)
        if len(raw) > MAX_RECIPE_BYTES:
            raise WorldError("recipe_too_big")
        doc = json.loads(raw.decode("utf-8"))
    except WorldError:
        raise
    except (OSError, ValueError) as exc:
        raise WorldError(f"recipe_unreadable:{type(exc).__name__}") from exc
    parse_recipe(doc)
    return doc


def world_key() -> str:
    """The world key, from the environment only."""
    key = os.environ.get(WORLD_KEY_ENV, "")
    if not key.strip() or "\x00" in key or len(key) > 512:
        raise WorldError("world_key_missing")
    return key


def fund_env() -> Path:
    """``fund-env`` next to this interpreter; never looked up on ``PATH``."""
    path = Path(sys.executable).parent / "fund-env"
    if not path.is_file():
        raise WorldError("fund_env_missing")
    return path


def child_env(db: Path, key: str, extra_symbols: dict[str, float] | None = None,
              market: dict[str, Any] | None = None) -> dict[str, str]:
    """The environment of every child: the parent's, minus each ``FUND_*``, plus exactly the
    world's own database, its market (the synthetic one with the recipe's extra symbols, or the
    recipe's made-up market) and its key."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("FUND_")}
    env["FUND_DATABASE_URL"] = f"sqlite:///{db}"
    env["FUND_MARKETDATA__PROVIDER"] = "synthetic" if market is None else "made_up"
    env[WORLD_KEY_ENV] = key
    if extra_symbols:
        env["FUND_MARKETDATA__SYNTHETIC_SYMBOLS"] = json.dumps(extra_symbols, sort_keys=True)
    if market is not None:
        env["FUND_MARKETDATA__MADE_UP"] = json.dumps(market, sort_keys=True)
    return env


def _run(program: Path, argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``fund-env SUBCOMMAND ...`` to its end. The sub-command must be on the list."""
    if argv[0] not in SUBCOMMANDS or any(a.startswith("-") and "=" not in a for a in argv[1:]):
        raise WorldError("command_not_allowed")
    try:
        return subprocess.run([str(program), *argv], cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=_COMMAND_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorldError(f"{argv[0]}:{type(exc).__name__}") from exc


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class World:
    """A hosted world: its directory, database, the two keys and (once served) its server."""
    tmp: Path
    db: Path
    registrar_key: str = field(repr=False)
    clock_key: str = field(repr=False)
    env: dict[str, str] = field(repr=False)
    url: str | None = None
    _server: subprocess.Popen[bytes] | None = field(default=None, repr=False)

    async def serve(self) -> str:
        """Start ``fund-env serve`` on a loopback port; its URL once ``/health`` answers."""
        if self._server is not None:
            raise WorldError("already_serving")
        port = _free_port()
        log = open(self.tmp / "serve.log", "wb")  # noqa: SIM115 - closed by stop()
        try:
            self._server = subprocess.Popen(
                [str(fund_env()), "serve", "--host=127.0.0.1", f"--port={port}"], cwd=self.tmp,
                env=self.env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        except (OSError, WorldError) as exc:
            log.close()
            raise WorldError("serve_failed") from exc
        finally:
            log.close()  # the child holds its own descriptor
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + _SERVE_WAIT_SECONDS
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            while time.monotonic() < deadline:
                if self._server.poll() is not None:
                    raise WorldError("server_exited")
                try:
                    if (await client.get(f"{url}/health")).status_code == 200:
                        self.url = url
                        return url
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.3)
        raise WorldError("server_not_ready")

    def stop(self) -> None:
        """Stop the server (SIGINT, then kill); idempotent."""
        server, self._server, self.url = self._server, None, None
        if server is None:
            return
        if server.poll() is None:
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

    def export_ledger(self) -> dict[str, Any]:
        """The world's ledger as the cassette's ``ledger`` block (physics wrote it down)."""
        r = _run(fund_env(), ["export-ledger", str(self.db)], self.env, self.tmp)
        if r.returncode != 0:
            raise WorldError(f"export-ledger:{r.returncode}")
        try:
            doc = json.loads(r.stdout)
        except ValueError as exc:
            raise WorldError("export-ledger:unreadable") from exc
        if (type(doc) is not dict or doc.get("ledger_format") != LEDGER_FORMAT
                or type(doc.get("rows")) is not list):
            raise WorldError("export-ledger:malformed")
        return doc

    def compare_with(self, rows_file: Path) -> dict[str, Any]:
        """Physics' verdict on the recorded ledger in ``rows_file`` against this world's: the JSON
        of ``fund-env compare-ledgers`` (``equal``, ``allowed``, ``first_difference``, ``locate``)."""
        r = _run(fund_env(), ["compare-ledgers", str(rows_file), str(self.db)], self.env, self.tmp)
        if r.returncode not in (0, 1):  # 2: a file physics could not read: not a verdict
            raise WorldError(f"compare-ledgers:{r.returncode}")
        try:
            doc = json.loads(r.stdout)
        except ValueError as exc:
            raise WorldError("compare-ledgers:unreadable") from exc
        if type(doc) is not dict or type(doc.get("equal")) is not bool:
            raise WorldError("compare-ledgers:malformed")
        return doc


def _genesis(recipe: WorldRecipe, tmp: Path, env: dict[str, str]) -> tuple[str, str]:
    """Open the run with the operator's own commands; ``(registrar_key, clock_key)``."""
    program = fund_env()
    keys: dict[str, str] = {}
    steps = [["init-db"], ["start-backtest", f"--start={recipe.start}"],
             ["seed-admin", f"--name={recipe.admin}"], ["seed-runtime"],
             *(["create-pod", f"--name={p.name}", f"--allocation={p.allocation!r}"]
               for p in recipe.pods)]
    for argv in steps:
        r = _run(program, argv, env, tmp)
        if r.returncode != 0:
            raise WorldError(f"genesis:{argv[0]}:{r.returncode}", redact(r.stderr)[-400:].strip())
        if argv[0] in {"seed-admin", "seed-runtime"}:
            found = _KEY.search(r.stdout)
            if found is None:
                raise WorldError(f"genesis:{argv[0]}:no_key")
            keys[argv[0]] = found.group(0)
    return keys["seed-admin"], keys["seed-runtime"]


@asynccontextmanager
async def hosted(recipe_doc: dict[str, Any], key: str) -> AsyncIterator[World]:
    """A fresh world for ``recipe_doc`` (a validated recipe object) under world key ``key``:
    built, not yet served. On the way out the server is stopped and the directory removed."""
    recipe = parse_recipe(recipe_doc)
    if read_governance().halted:  # before anything starts (Art. 5)
        raise WorldError("halted")
    fund_env()
    tmp = Path(tempfile.mkdtemp(prefix="fund-world-")).resolve()
    world: World | None = None
    try:
        db = tmp / "world.db"
        env = child_env(db, key, recipe.extra_symbols, recipe.market)
        registrar, clock = await asyncio.to_thread(_genesis, recipe, tmp, env)
        world = World(tmp, db, registrar, clock, env)
        yield world
    finally:
        if world is not None:
            world.stop()
        shutil.rmtree(tmp, ignore_errors=True)
