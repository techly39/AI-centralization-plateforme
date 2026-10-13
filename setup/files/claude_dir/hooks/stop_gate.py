#!/usr/bin/env python3
"""Stop hook for Builder loop sessions. HUMAN-ONLY FILE (Constitution Art. 6). ADR-042.

Runs when the Builder tries to end its session (Claude Code `Stop` event; hooks run outside the
sandbox). It turns two claims into checks, so "done" is decided by code, not by the agent:

  * result `merged`  → the tree is clean, we are on main, the mission's acceptance check passes and
                       the suite is green. Otherwise: blocked, with the failing output.
  * result `progress`→ everything is committed and state/PROGRESS.md names this cycle.

It only acts in loop sessions (FIRM_BUILDER_SESSION=1, set by loop/run.sh), never on HALT, and it
gives up after 3 blocks in one session (the runner's out-of-band referee still judges the claim).
Exit 2 + stderr = "keep working, here is why". Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_BLOCKS = 3


def sh(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr)[-2500:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except OSError as e:
        return 127, str(e)


def block(reason: str, counter: Path) -> None:
    counter.write_text(str(int(counter.read_text() or 0) + 1) if counter.exists() else "1")
    print(f"STOP GATE (ADR-042): {reason}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    if os.environ.get("FIRM_BUILDER_SESSION") != "1":
        return
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        data = {}
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    if (root / "governance" / "HALT").exists():
        return
    sid = hashlib.sha256(str(data.get("session_id", "")).encode()).hexdigest()[:16]
    counter = Path(tempfile.gettempdir()) / f"firm-stop-gate-{sid}"
    if counter.exists() and int(counter.read_text() or 0) >= MAX_BLOCKS:
        return

    try:
        status = json.loads((root / "state" / "loop_status.json").read_text())
    except (OSError, json.JSONDecodeError):
        return  # the runner counts a session that never wrote its status as failed
    result, cycle, mission = status.get("result"), status.get("cycle"), status.get("mission")
    _, dirty = sh(["git", "status", "--porcelain"], root, 30)

    if result == "progress":
        if dirty.strip():
            block("you are ending with uncommitted changes. Commit them on the mission branch and push "
                  "before stopping (protocol/CYCLE.md §5).", counter)
        progress = root / "state" / "PROGRESS.md"
        if not progress.exists() or f"{int(cycle or 0):04d}" not in progress.read_text():
            block(f"state/PROGRESS.md does not name cycle {cycle}. Rewrite the handoff for the next "
                  "session (protocol/CYCLE.md §5), commit, then stop.", counter)
        return

    if result == "merged":
        _, branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], root, 30)
        if branch.strip() != "main" or dirty.strip():
            block("result is `merged` but you are not on a clean `main`. Merge, commit state, then stop.",
                  counter)
        try:
            ms = json.loads((root / "state" / "missions.json").read_text()).get("missions", [])
        except (OSError, json.JSONDecodeError):
            ms = []
        m = next((x for x in ms if x.get("id") == mission), None)
        if not m or m.get("status") != "done" or not m.get("acceptance"):
            block(f"result is `merged` but mission {mission!r} is not `done` with an `acceptance` path "
                  "in state/missions.json.", counter)
        rc, out = sh(["uv", "run", "--quiet", "python", m["acceptance"]], root, 1500)
        if rc != 0:
            block(f"{m['acceptance']} fails on main (exit {rc}). The mission is not done:\n{out}", counter)
        rc, out = sh(["uv", "run", "--quiet", "pytest", "-p", "no:warnings", "-o", "addopts=", "-q", "-x"],
                     root, 1500)
        if rc != 0:
            block(f"the suite is red on main (exit {rc}):\n{out}", counter)


if __name__ == "__main__":
    main()
