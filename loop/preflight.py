#!/usr/bin/env python3
"""Loop preflight. HUMAN-ONLY FILE (Constitution Art. 6).

Usage (from the repo root, via `uv run python loop/preflight.py ...`):
  (no args)     run every check before a cycle. Exit codes:
                  0  go
                  10 go, but run a DIAGNOSIS cycle (failure limit reached)
                  20 wait (daily cycle limit reached)
                  1  stop the loop (halt, seal broken, open incident, repeated failure)
  --post        after a cycle: read state/loop_status.json, update the failure counter
  --get a.b.c   print a value from governance/human.yaml

Reference hashes live OUTSIDE the repo ($FIRM_HOME/protected.sha256, default ~/.firm),
written by loop/seal.sh, so nothing inside the repo can forge them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FIRM_HOME = Path(os.environ.get("FIRM_HOME", Path.home() / ".firm"))
SEAL = FIRM_HOME / "protected.sha256"
FAILURES = FIRM_HOME / "failures"
CYCLES_LOG = FIRM_HOME / "cycles.log"
PROTECTED = [
    "bible/00_CONSTITUTION.md",
    "bible/01_GENESIS.md",
    "governance",
    "loop",
    ".claude/settings.json",
    ".claude/hooks",
]
UNSEALED = {"governance/HALT"}


def protected_files() -> list[Path]:
    files: list[Path] = []
    for p in PROTECTED:
        path = ROOT / p
        if path.is_dir():
            files += [f for f in sorted(path.rglob("*")) if f.is_file() and "__pycache__" not in f.parts]
        elif path.is_file():
            files.append(path)
    return [f for f in files if f.relative_to(ROOT).as_posix() not in UNSEALED]


def current_hashes() -> dict[str, str]:
    return {f.relative_to(ROOT).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in protected_files()}


def config() -> dict:
    return yaml.safe_load((ROOT / "governance" / "human.yaml").read_text()) or {}


def get(key: str):
    node = config()
    for part in key.split("."):
        node = node[part]
    return node


def stop(msg: str, code: int = 1) -> None:
    print(f"PREFLIGHT: {msg}")
    sys.exit(code)


def check() -> None:
    if (ROOT / "governance" / "HALT").exists():
        stop("governance/HALT exists.")

    if not SEAL.exists():
        stop(f"no seal at {SEAL}. Run loop/seal.sh once, as the Human.")
    sealed = json.loads(SEAL.read_text())
    now = current_hashes()
    if sealed != now:
        changed = sorted(set(sealed.items()) ^ set(now.items()))
        stop(f"protected files differ from the seal: {sorted({k for k, _ in changed})}. "
             "If you (the Human) changed them, run loop/seal.sh.")

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        # Not fatal: cycle step 0 inspects leftovers from a crashed cycle.
        print(f"PREFLIGHT: warning — working tree not clean:\n{dirty}")

    incidents = ROOT / "state" / "INCIDENTS.md"
    if incidents.exists():
        text = incidents.read_text()
        for block in text.split("\n## ")[1:]:
            if "severity: high" in block and "status: open" in block:
                stop("open high-severity incident in state/INCIDENTS.md.")

    cfg = config().get("builder", {})
    today = dt.date.today().isoformat()
    ran_today = 0
    if CYCLES_LOG.exists():
        ran_today = sum(1 for line in CYCLES_LOG.read_text().splitlines() if line.startswith(today))
    if ran_today >= int(cfg.get("max_cycles_per_day", 24)):
        stop(f"daily cycle limit reached ({ran_today}).", 20)

    failures = int(FAILURES.read_text()) if FAILURES.exists() else 0
    limit = int(cfg.get("max_consecutive_failures", 3))
    if failures > limit:
        stop(f"{failures} consecutive failed cycles, diagnosis included. Read state/BLOCKED.md, "
             f"then delete {FAILURES} to resume.")
    if failures == limit:
        stop("failure limit reached — run one diagnosis cycle.", 10)

    print("PREFLIGHT: go")


def post() -> None:
    FIRM_HOME.mkdir(parents=True, exist_ok=True)
    status_file = ROOT / "state" / "loop_status.json"
    result = "failed"
    if status_file.exists():
        try:
            result = json.loads(status_file.read_text()).get("result", "failed")
        except json.JSONDecodeError:
            pass
    failures = int(FAILURES.read_text()) if FAILURES.exists() else 0
    failures = 0 if result == "merged" else failures + 1
    FAILURES.write_text(str(failures))
    print(f"POST: result={result} consecutive_failures={failures}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--post":
        post()
    elif len(sys.argv) > 2 and sys.argv[1] == "--get":
        print(get(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--hashes":
        print(json.dumps(current_hashes(), indent=1, sort_keys=True))
    else:
        check()
