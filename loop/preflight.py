#!/usr/bin/env python3
"""Loop preflight. HUMAN-ONLY FILE (Constitution Art. 6).

Usage (from the repo root, via `uv run python loop/preflight.py ...`):
  (no args)     run every check before a cycle. Exit codes:
                  0  go
                  10 go, but run a DIAGNOSIS cycle (failure limit reached)
                  20 stop for today (daily cycle limit or daily USD budget reached)
                  1  stop the loop (halt, seal broken, open incident, repeated failure)
  --post N LOG  after a run: N = last cycle number before the run, LOG = its output file.
                Records the run's cost. Counts the run only if state/loop_status.json advanced;
                a usage/rate-limit stop exits 30 and is not counted (the runner stops).
  --cost LOG    print the USD cost of one run, read from its output file
  --last-cycle  print the cycle number in state/loop_status.json
  --spent-today print the USD spent by Builder runs today
  --get a.b.c   print a value from governance/human.yaml

Reference hashes live OUTSIDE the repo ($FIRM_HOME/protected.sha256, default ~/.firm),
written by loop/seal.sh, so nothing inside the repo can forge them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
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
    ".claude/commands",
    ".claude/agents",
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
    # A cycle starts only if its whole budget still fits under today's cap: the day never overshoots.
    spent, cap, per_cycle = spent_today(), cfg.get("max_usd_per_day"), float(cfg.get("max_usd_per_cycle", 0))
    if cap is not None and spent + per_cycle > float(cap):
        stop(f"daily budget reached (${spent:.2f} spent, a cycle may cost ${per_cycle:.2f}, "
             f"cap ${float(cap):.2f}).", 20)

    failures = int(FAILURES.read_text()) if FAILURES.exists() else 0
    limit = int(cfg.get("max_consecutive_failures", 3))
    if failures > limit:
        stop(f"{failures} consecutive failed cycles, diagnosis included. Read state/BLOCKED.md, "
             f"then delete {FAILURES} to resume.")
    if failures == limit:
        stop("failure limit reached — run one diagnosis cycle.", 10)

    print("PREFLIGHT: go")


LIMIT_MARKERS = re.compile(
    r"usage limit|rate.?limit|limit reached|limit will reset|resets at|429|overloaded|quota",
    re.IGNORECASE,
)


def spent_today() -> float:
    """USD spent by Builder runs today, summed from the cost= field of $FIRM_HOME/cycles.log."""
    if not CYCLES_LOG.exists():
        return 0.0
    today = dt.date.today().isoformat()
    total = 0.0
    for line in CYCLES_LOG.read_text().splitlines():
        m = re.search(r"\bcost=([0-9.]+)", line)
        if line.startswith(today) and m:
            total += float(m.group(1))
    return total


def run_cost(log_text: str) -> float:
    """total_cost_usd from the `claude -p --output-format json` result; 0 if unreadable."""
    for line in reversed(log_text.strip().splitlines()):
        try:
            return float(json.loads(line).get("total_cost_usd") or 0)
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            continue
    return 0.0


def read_log(logfile: str | None) -> str:
    if not logfile:
        return ""
    try:
        return Path(logfile).read_text(errors="replace")[-20000:]
    except OSError:
        return ""


def last_cycle() -> int:
    status_file = ROOT / "state" / "loop_status.json"
    try:
        return int(json.loads(status_file.read_text()).get("cycle", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0


def post(before: int, logfile: str | None) -> None:
    """Classify the run that just ended. Exit codes:
         0  a real cycle ran (merged / failed / blocked) — counted toward the daily caps
         30 no cycle ran because of a usage/rate limit — not counted, the runner stops
    A run that did not advance state/loop_status.json is NEVER counted as merged.
    """
    FIRM_HOME.mkdir(parents=True, exist_ok=True)
    status_file = ROOT / "state" / "loop_status.json"
    after = last_cycle()
    log_text = read_log(logfile)
    cost = run_cost(log_text)

    if after > before:
        try:
            result = json.loads(status_file.read_text()).get("result", "failed")
        except (OSError, json.JSONDecodeError):
            result = "failed"
    elif LIMIT_MARKERS.search(log_text) and cost == 0:
        print("POST: no cycle ran — usage/rate limit hit. Not counted.")
        sys.exit(30)
    else:
        result = "failed"
        print("POST: the run did not advance state/loop_status.json — counted as failed.")

    with CYCLES_LOG.open("a") as fh:
        fh.write(f"{dt.date.today().isoformat()} cycle={after} result={result} cost={cost:.4f}\n")
    failures = int(FAILURES.read_text()) if FAILURES.exists() else 0
    failures = 0 if result == "merged" else failures + 1
    FAILURES.write_text(str(failures))
    print(f"POST: result={result} cost=${cost:.2f} spent_today=${spent_today():.2f} "
          f"consecutive_failures={failures}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--post":
        post(int(sys.argv[2]) if len(sys.argv) > 2 else 0, sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) > 2 and sys.argv[1] == "--cost":
        print(f"{run_cost(read_log(sys.argv[2])):.4f}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--last-cycle":
        print(last_cycle())
    elif len(sys.argv) > 1 and sys.argv[1] == "--spent-today":
        print(f"{spent_today():.2f}")
    elif len(sys.argv) > 2 and sys.argv[1] == "--get":
        print(get(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--hashes":
        print(json.dumps(current_hashes(), indent=1, sort_keys=True))
    else:
        check()
