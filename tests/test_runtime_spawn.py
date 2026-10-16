"""M-002 (ADR-045): ``runtime/world.py`` is the only module of the Runtime that starts a process.

A static scan (``ast``) of every ``runtime/**/*.py`` for the ways Python starts one: importing
``subprocess``/``multiprocessing``/``pty``, ``os.system``/``popen``/``exec*``/``spawn*``/``fork*``,
``asyncio.create_subprocess_*``, and ``__import__``/``importlib`` games around those names. The
scanner is tested against planted trees, so a scanner that finds nothing fails the suite.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ALLOWED = {"runtime/world.py"}
_MODULES = {"subprocess", "multiprocessing", "pty", "pexpect", "sh", "plumbum"}
_OS_CALLS = ("system", "popen", "exec", "spawn", "fork", "posix_spawn", "startfile")


def spawns(source: str) -> list[str]:
    """What in ``source`` can start a process (empty: nothing)."""
    found: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] in _MODULES]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _MODULES:
                found.append(node.module or "")
            if node.module == "os" and any(a.name.startswith(_OS_CALLS) for a in node.names):
                found.append("from os import " + ",".join(a.name for a in node.names))
            if node.module == "asyncio" and any("subprocess" in a.name for a in node.names):
                found.append("from asyncio import subprocess")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith(_OS_CALLS) and isinstance(node.value, ast.Name) \
                    and node.value.id in {"os", "posix"}:
                found.append(f"{node.value.id}.{node.attr}")
            if node.attr.startswith("create_subprocess"):
                found.append(node.attr)
        elif isinstance(node, ast.Name) and node.id in {"__import__"}:
            found.append("__import__")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "import_module":
            found.append("import_module")
    return found


@pytest.mark.parametrize("planted", [
    "import subprocess\n",
    "from subprocess import run\n",
    "import multiprocessing.pool\n",
    "import os\nos.system('x')\n",
    "import os\nos.execv('/bin/sh', [])\n",
    "import os\nos.posix_spawn('/bin/sh', [], {})\n",
    "from os import popen\n",
    "import asyncio\nasyncio.create_subprocess_exec('x')\n",
    "x = __import__('sub' + 'process')\n",
    "import importlib\nimportlib.import_module('subprocess')\n",
])
def test_the_scanner_finds_every_way_to_start_a_process(planted: str) -> None:
    assert spawns(planted), planted


def test_the_scanner_ignores_what_starts_nothing() -> None:
    assert spawns("import os, json\nx = os.path.join('a', 'b')\nos.environ.get('X')\n"
                  "import asyncio\nasyncio.run(None)\n") == []


def test_only_world_py_starts_processes() -> None:
    files = sorted(p for p in (REPO / "runtime").rglob("*.py"))
    assert files and any(p.name == "world.py" for p in files)  # the scan sees the tree
    offenders = {str(p.relative_to(REPO)): spawns(p.read_text()) for p in files}
    assert {k for k, v in offenders.items() if v} == ALLOWED, offenders
    # world.py starts exactly fund-env: its only program is built from one place.
    world = (REPO / "runtime" / "world.py").read_text()
    assert world.count("subprocess.run(") == 1 and world.count("subprocess.Popen(") == 1


def test_world_py_imports_nothing_from_physics() -> None:
    tree = ast.parse((REPO / "runtime" / "world.py").read_text())
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                for a in n.names} | {(n.module or "").split(".")[0] for n in ast.walk(tree)
                                     if isinstance(n, ast.ImportFrom)}
    assert not imported & {"app", "mcp_server", "ui", "scripts", "truman", "quant", "legacy"}
