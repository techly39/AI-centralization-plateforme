"""Survey probe: measure what reading the rest of the repo suggested (S-003b, cycle 5).

Companion to ``survey_probe_physics.py``. That one inspected ``app/`` from the
inside on a temp DB; this one looks at everything around it — the suite, root
files, credentials lying about — and reports, never asserts.

The probe process does **not** import ``app`` and writes nothing; R2's
``pytest --collect-only`` subprocess does import it (collection only, no cache
provider; Python may still write ``__pycache__``). The one place it touches the
Human's ``fund.db`` (R1) opens it with SQLite's ``mode=ro&immutable=1``: no write,
no lock file, no journal. It never prints a key, only whether its hash matches.

Usage:
    uv run python scripts/survey_probe_repo.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sqlite3
import stat
import subprocess
import sys
import tomllib
from collections import Counter
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout


def r1_committed_key() -> None:
    """Is the API key hard-coded in ``test_api.py`` live in ``fund.db``?

    Cycle 6 (S-004) redacted the key from the tree, but it stays in git history,
    so when the working copy holds no key the probe reads the version just
    before the last commit that touched a key line.
    """
    print("R1  hard-coded key in test_api.py")
    pattern = r"\bfk_[A-Za-z0-9_\-]{20,}"
    path = REPO / "test_api.py"
    keys = re.findall(pattern, path.read_text()) if path.exists() else []
    print(f"    keys in the working tree: {len(keys)}")
    if not keys:
        # git's -G takes POSIX ERE: no \b.
        git_pattern = "fk_[A-Za-z0-9_-]{20,}"
        changed = git("log", "-1", "--format=%H", "-G", git_pattern, "--", "test_api.py").strip()
        if changed:
            before = git("show", f"{changed}^:test_api.py")
            keys = re.findall(pattern, before)
            print(f"    keys in git history (before {changed[:7]}): {len(keys)}")
            if not before:
                # Root commit, or the file did not exist before: the last key
                # change was an addition, so this lookup cannot see the key.
                print(f"    WARNING: no test_api.py before {changed[:7]}; history lookup inconclusive")
    tracked = bool(git("ls-files", "test_api.py").strip())
    print(f"    file tracked by git: {tracked}")
    commits = git("log", "--format=%h", "--", "test_api.py").split()
    print(f"    commits containing the file: {len(commits)}")
    on_origin = bool(git("branch", "-r", "--contains", commits[-1]).strip()) if commits else False
    print(f"    first such commit reachable from a remote branch: {on_origin}")
    db_path = REPO / "fund.db"
    if not keys or not db_path.exists():
        print("    fund.db check: skipped")
        return
    uri = f"file:{db_path}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        for key in keys:
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
            row = conn.execute(
                "SELECT id, name, role, status FROM agents WHERE api_key_hash = ?",
                (digest,),
            ).fetchone()
            if row is None:
                print("    matches an agent in fund.db: no")
            else:
                print(
                    f"    matches an agent in fund.db: YES — id={row[0]} name={row[1]!r} "
                    f"role={row[2]} status={row[3]}"
                )


def r2_suite_shape() -> None:
    """Tests collected per file, from pytest itself (not from grepping ``def test_``)."""
    print("R2  suite shape (pytest --collect-only)")
    # pyproject's addopts already has -q; one more makes -qq, which prints
    # "path: N" per file instead of one line per test.
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, check=False,
    ).stdout
    per_file: Counter[str] = Counter()
    for line in out.splitlines():
        match = re.fullmatch(r"(tests/\S+\.py): (\d+)", line.strip())
        if match:
            per_file[match.group(1)] = int(match.group(2))
    for path, n in sorted(per_file.items(), key=lambda kv: -kv[1]):
        print(f"    {n:4d}  {path}")
    print(f"    {sum(per_file.values()):4d}  total collected")
    root_tests = [p.name for p in REPO.glob("test_*.py")]
    print(f"    test_*.py at repo root (outside testpaths, never collected): {root_tests}")


def r3_dependencies() -> None:
    """Imports used by non-physics code vs what ``pyproject.toml`` declares."""
    print("R3  dependencies of root/scripts code")
    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    declared = " ".join(project["project"]["dependencies"]).lower()
    for module in ["requests"]:
        present = importlib.util.find_spec(module) is not None
        print(f"    {module}: importable={present} declared={module in declared}")


def r4_local_files() -> None:
    """Untracked local files that matter: are they ignored, and how protected."""
    print("R4  local files")
    for name in ["agents.local.json", "fund.db", ".DS_Store", "legacy/.DS_Store"]:
        path = REPO / name
        if not path.exists():
            print(f"    {name}: absent")
            continue
        ignored = bool(git("check-ignore", name).strip())
        mode = stat.filemode(path.stat().st_mode)
        print(f"    {name}: ignored={ignored} mode={mode}")
    ui = REPO / "ui"
    if ui.is_dir():
        print(f"    ui/: {len(list(ui.iterdir()))} entries (git cannot track an empty dir)")
    tracked_ignored = git("ls-files", "-ci", "--exclude-standard").split()
    print(f"    tracked files the .gitignore would now exclude: {tracked_ignored}")


def main() -> None:
    for probe in (r1_committed_key, r2_suite_shape, r3_dependencies, r4_local_files):
        probe()
        print()


if __name__ == "__main__":
    main()
