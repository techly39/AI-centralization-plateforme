"""The dependency law (bible/03_WORLD.md §1, ADR-022), enforced.

    runtime ──HTTP/MCP──▶ app ──imports──▶ quant, truman   (pure libraries)
    ui ──HTTP──▶ app
    mcp_server ──HTTP──▶ app       (imports only app.config + app.limits)
    scripts ──MCP/HTTP──▶ app      (except named in-process probes)
    nothing imports runtime or legacy;  app never imports runtime, ui, mcp, or any LLM SDK
    quant and truman never import app

Two detectors, because "0 violations" from one detector is a statement about
the detector (cycle 7):

1. **Static** — every ``import`` / ``from … import`` in every file of a layer,
   including imports inside functions, read with ``ast``.
2. **Dynamic** — import the layer's entry points in a fresh interpreter and look
   at ``sys.modules``. This catches what the source does not show: a third-party
   dependency that pulls an LLM SDK in behind physics' back.

The static scanner is itself tested against a planted tree, so a scanner that
silently finds nothing fails the suite.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Top-level module names of LLM SDKs and agent frameworks. Physics (Art. 3.1)
#: and the pure libraries never load any of them. Dotted entries match a
#: submodule of a shared namespace (``google``).
LLM_SDKS = frozenset({
    "anthropic", "openai", "openrouter", "litellm", "groq", "mistralai", "cohere",
    "ollama", "together", "google.generativeai", "google.genai", "vertexai",
    "transformers", "vllm", "llama_cpp",
    "langchain", "langchain_core", "langchain_community", "langchain_openai",
    "langchain_anthropic", "langgraph", "llama_index", "crewai", "autogen",
    "autogen_agentchat", "agents", "claude_agent_sdk", "claude_code_sdk",
    "pydantic_ai", "smolagents", "dspy", "semantic_kernel", "haystack",
})

#: Repo packages that are layers of the world (or tooling around it).
REPO_PACKAGES = frozenset({
    "app", "migrations", "mcp_server", "runtime", "truman", "quant", "ui",
    "scripts", "tests", "legacy",
})

#: The only ``app`` modules the MCP wrapper may load: settings and the pure
#: constants clients must agree with physics on. Never the DB, the ledger,
#: the OMS — the wrapper reaches those only over HTTP (ADR-022).
MCP_SERVER_MAY_IMPORT_FROM_APP = frozenset({"app", "app.config", "app.limits"})

#: Operator scripts that run physics in-process on a throwaway database, by
#: design. Every other script is a client (HTTP/MCP) and never imports ``app``.
IN_PROCESS_SCRIPTS = frozenset({"scripts/survey_probe_physics.py"})


@dataclass(frozen=True)
class Layer:
    name: str
    path: str  # relative to the repo root
    forbidden: frozenset[str]
    #: ``app`` modules allowed although ``app`` is forbidden (exact names).
    app_allowlist: frozenset[str] = field(default_factory=frozenset)
    #: Files exempt from the ``app`` ban (repo-relative POSIX paths).
    app_exempt_files: frozenset[str] = field(default_factory=frozenset)


_NOT_PHYSICS = frozenset({"runtime", "ui", "mcp_server", "scripts", "tests", "legacy"})

LAYERS = (
    # Physics. Also never speaks MCP itself: the MCP layer wraps it from outside.
    Layer("app", "app", _NOT_PHYSICS | {"mcp"} | LLM_SDKS),
    Layer("migrations", "migrations", _NOT_PHYSICS | {"mcp"} | LLM_SDKS),
    # Pure deterministic libraries physics may import.
    Layer("quant", "quant", _NOT_PHYSICS | {"app", "mcp"} | LLM_SDKS),
    Layer("truman", "truman", _NOT_PHYSICS | {"app", "mcp"} | LLM_SDKS),
    # One agent's doorway: an HTTP client of the App.
    Layer("mcp_server", "mcp_server",
          frozenset({"app", "runtime", "ui", "scripts", "tests", "legacy"}) | LLM_SDKS,
          app_allowlist=MCP_SERVER_MAY_IMPORT_FROM_APP),
    # Wakes agents; may call LLMs (through metered keys); reaches the App over HTTP/MCP.
    Layer("runtime", "runtime", frozenset({"app", "ui", "scripts", "tests", "legacy"})),
    Layer("ui", "ui", frozenset({"app", "runtime", "scripts", "tests", "legacy"}) | LLM_SDKS),
    # Operator tools: clients, except the named in-process probes.
    Layer("scripts", "scripts", frozenset({"app", "runtime", "tests", "legacy"}) | LLM_SDKS,
          app_exempt_files=IN_PROCESS_SCRIPTS),
)

#: Directories that hold Python but are not layers, and why.
NOT_LAYERS = {
    "tests": "the suite may import every layer",
    "legacy": "frozen pre-Bible POC (cycle 6: keep); nothing may import it",
    "loop": "human-owned runner (Art. 6)",
}

#: Loose ``.py`` files at the repo root. ``test_api.py`` awaits `git rm` (S-004b, P-0002).
ROOT_FILES_ALLOWED = frozenset({"test_api.py"})


# --- the scanner ---------------------------------------------------------------


def imported_modules(source: str, module_name: str, is_package: bool) -> set[str]:
    """Every module a file imports, as dotted names, wherever the import sits.

    ``from a.b import c`` yields both ``a.b`` and ``a.b.c`` (``c`` may be a
    submodule: ``from google import genai``). Relative imports are resolved
    against ``module_name``. ``__import__("x")`` and ``import_module("x")``
    with a literal name count too; a computed name cannot be seen statically.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _is_dynamic_import(node.func):
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = module_name.split(".")
                base = parts if is_package else parts[:-1]
                base = base[: len(base) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if module:
                found.add(module)
            found.update(
                f"{module}.{alias.name}" if module else alias.name
                for alias in node.names if alias.name != "*"
            )
    return found


def _is_dynamic_import(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in {"__import__", "import_module"}
    return isinstance(func, ast.Attribute) and func.attr == "import_module"


def _matches(module: str, banned: str) -> bool:
    return module == banned or module.startswith(banned + ".")


def _allowed(module: str, allowlist: frozenset[str]) -> bool:
    """``app.config`` and a name imported from it (``app.config.get_settings``) —
    but a name imported from the bare package (``from app import db``) is not."""
    parent = module.rpartition(".")[0]
    return module in allowlist or (parent in allowlist and parent != "app")


def violations(root: Path, layer: Layer) -> list[str]:
    """``file: module`` for every import in the layer that breaks its law."""
    out: list[str] = []
    for path in sorted((root / layer.path).rglob("*.py")):
        rel = path.relative_to(root)
        is_package = path.name == "__init__.py"
        parts = rel.with_suffix("").parts
        module_name = ".".join(parts[:-1] if is_package else parts)
        for module in sorted(imported_modules(path.read_text(), module_name, is_package)):
            for banned in layer.forbidden:
                if not _matches(module, banned):
                    continue
                if banned == "app" and (
                    _allowed(module, layer.app_allowlist)
                    or rel.as_posix() in layer.app_exempt_files
                ):
                    continue
                out.append(f"{rel}: {module}")
                break
    return out


def python_dirs(root: Path) -> set[str]:
    """Top-level, non-hidden directories that contain Python source."""
    return {
        p.name for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".") and any(p.rglob("*.py"))
    }


# --- the law, on this repo -----------------------------------------------------------


@pytest.mark.parametrize("layer", LAYERS, ids=lambda layer: layer.name)
def test_layer_obeys_dependency_law(layer: Layer) -> None:
    assert violations(REPO_ROOT, layer) == []


def test_the_scanner_actually_read_physics() -> None:
    """Guard against a vacuous pass: the scan sees physics and its imports."""
    files = list((REPO_ROOT / "app").rglob("*.py"))
    assert len(files) >= 40
    seen = set().union(*(
        imported_modules(f.read_text(), "app.x", False) for f in files
    ))
    assert {"sqlalchemy", "fastapi", "app.clock"} <= seen


def test_every_python_directory_is_placed_in_the_law() -> None:
    """A new top-level package must get a law before it can land."""
    placed = {layer.path for layer in LAYERS} | set(NOT_LAYERS)
    assert python_dirs(REPO_ROOT) - placed == set()


def test_no_unplaced_python_at_the_repo_root() -> None:
    loose = {p.name for p in REPO_ROOT.glob("*.py")}
    assert loose - ROOT_FILES_ALLOWED == set()


def test_nothing_imports_legacy_or_runtime_outside_tests() -> None:
    for layer in LAYERS:
        assert "legacy" in layer.forbidden, layer.name
        if layer.name != "runtime":
            assert "runtime" in layer.forbidden, layer.name


# --- dynamic: what actually loads ------------------------------------------------------


def _loaded_modules(*imports: str) -> list[str]:
    code = (
        "import importlib, json, sys\n"
        f"for m in {list(imports)!r}: importlib.import_module(m)\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    # No FUND_* overrides or PYTHONPATH from the caller: the probe sees the repo only.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("FUND_") and k != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True,
        text=True, timeout=120, check=True,
    )
    return json.loads(done.stdout)


def test_physics_loads_no_llm_sdk_even_transitively() -> None:
    loaded = _loaded_modules("app.main", "app.cli", "app.scheduler")
    assert "app.main" in loaded  # the probe really imported physics
    bad = [m for m in loaded if any(_matches(m, sdk) for sdk in LLM_SDKS)]
    assert bad == []
    assert not any(_matches(m, "mcp") or _matches(m, "mcp_server") for m in loaded)


def test_mcp_server_loads_no_physics_internals() -> None:
    """The wrapper holds one key and talks HTTP; it never opens the database."""
    loaded = _loaded_modules("mcp_server.server", "mcp_server.tools")
    assert "mcp_server.tools" in loaded
    from_app = {m for m in loaded if _matches(m, "app")}
    assert from_app <= MCP_SERVER_MAY_IMPORT_FROM_APP, sorted(from_app)
    assert "sqlalchemy" not in loaded


# --- the scanner, on a planted tree ----------------------------------------------------


def _plant(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_scanner_catches_planted_violations(tmp_path: Path) -> None:
    _plant(tmp_path, {
        "app/__init__.py": "",
        "app/top.py": "import anthropic.types\n",
        "app/nested.py": "def f():\n    from openai import OpenAI\n",
        "app/namespace.py": "from google import genai\n",
        "app/sideways.py": "from runtime.spec import AgentSpec\n",
        "app/sub/__init__.py": "from .. import ledger\nfrom .. import runtime\n",  # app.*
        "app/dynamic.py": (
            "import importlib\n__import__('openai')\n"
            "def f():\n    importlib.import_module('runtime.spec')\n"
        ),
        "app/clean.py": "import sqlalchemy\nfrom app.clock import get_clock\nfrom . import clock\n",
        "mcp_server/tools.py": (
            "from app.limits import X\nfrom app.config import get_settings\n"
            "from app.db.base import engine\nfrom app import db\n"
        ),
        "scripts/client.py": "import app.main\n",
        "scripts/survey_probe_physics.py": "from app.main import create_app\n",
        "quant/ic.py": "from app.clock import get_clock\n",
    })
    by_name = {layer.name: layer for layer in LAYERS}
    assert violations(tmp_path, by_name["app"]) == [
        "app/dynamic.py: openai",
        "app/dynamic.py: runtime.spec",
        "app/namespace.py: google.genai",
        "app/nested.py: openai",
        "app/nested.py: openai.OpenAI",
        "app/sideways.py: runtime.spec",
        "app/sideways.py: runtime.spec.AgentSpec",
        "app/top.py: anthropic.types",
    ]
    assert violations(tmp_path, by_name["mcp_server"]) == [
        "mcp_server/tools.py: app.db",
        "mcp_server/tools.py: app.db.base",
        "mcp_server/tools.py: app.db.base.engine",
    ]
    assert violations(tmp_path, by_name["scripts"]) == ["scripts/client.py: app.main"]
    assert violations(tmp_path, by_name["quant"]) == [
        "quant/ic.py: app.clock",
        "quant/ic.py: app.clock.get_clock",
    ]


def test_relative_imports_resolve() -> None:
    assert imported_modules("from . import clock", "app.ledger", True) >= {"app.ledger.clock"}
    assert imported_modules("from ..db import base", "app.ledger.rebuild", False) >= {
        "app.db", "app.db.base",
    }
    # A relative import never leaves its top package: this is app.runtime, not runtime.
    assert imported_modules("from .. import runtime", "app.sub", True) == {"app", "app.runtime"}
