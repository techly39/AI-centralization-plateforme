#!/usr/bin/env python3
"""Loop preflight. HUMAN-ONLY FILE (Constitution Art. 6).

Usage (from the repo root, via `uv run python loop/preflight.py ...`):
  (no args)     run every check before a cycle. Exit codes:
                  0  go
                  10 go, but run a DIAGNOSIS cycle (failure limit reached)
                  20 stop for today (daily cycle limit or daily USD budget reached)
                  1  stop the loop (halt, seal broken, team misconfigured, open incident,
                     repeated failure)
  --post N LOG  after a run: N = last cycle number before the run, LOG = its output file.
                Records cost and models used. Counts the run only if state/loop_status.json
                advanced. A session cut off by a usage/rate limit or an overloaded API exits 30:
                its cost is logged (result=limit, it counts toward the dollar caps), but it is
                not a cycle and not a failure — the next run resumes the interrupted cycle.
  --cost LOG    print the USD cost of one run, read from its output file
  --apply-team  write builder.team models/efforts into the .claude/agents/ frontmatter
                (loop/seal.sh runs this before sealing)
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

# The Builder team (builder.team in governance/human.yaml). Subagent roles map to a sealed
# .claude/agents/<role>.md whose frontmatter carries the model; frontmatter beats the
# CLAUDE_CODE_SUBAGENT_MODEL default (verified live 2026-10-12), which `helpers` sets.
AGENT_ROLES = ("architect", "auditor", "red-team")
SESSION_ROLES = ("lead", "lead_hard", "helpers")
MODELS = {"opus", "sonnet", "haiku", "fable"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}


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


# --- the team -------------------------------------------------------------------------

def team() -> dict[str, dict]:
    return config().get("builder", {}).get("team", {}) or {}


def team_errors() -> list[str]:
    """Everything wrong with builder.team: a typo here would burn a cycle, so it stops the loop."""
    t, errors = team(), []
    for role in SESSION_ROLES + AGENT_ROLES:
        spec = t.get(role)
        if not isinstance(spec, dict):
            errors.append(f"builder.team.{role} is missing")
            continue
        model, effort = spec.get("model"), spec.get("effort")
        if model not in MODELS and not str(model).startswith("claude-"):
            errors.append(f"builder.team.{role}.model {model!r} is not one of {sorted(MODELS)} or a claude-* id")
        if role != "helpers" and effort not in EFFORTS:
            errors.append(f"builder.team.{role}.effort {effort!r} is not one of {sorted(EFFORTS)}")
    for role in AGENT_ROLES:
        if not agent_file(role).exists():
            errors.append(f".claude/agents/{role}.md does not exist")
        elif role in t and isinstance(t[role], dict):
            fm = frontmatter(agent_file(role))
            for key in ("model", "effort"):
                if str(fm.get(key)) != str(t[role].get(key)):
                    errors.append(f".claude/agents/{role}.md has {key}: {fm.get(key)!r}, builder.team says "
                                  f"{t[role].get(key)!r} — run loop/seal.sh to apply the team")
    return errors


def agent_file(role: str) -> Path:
    return ROOT / ".claude" / "agents" / f"{role}.md"


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    out: dict[str, str] = {}
    if lines and lines[0] == "---":
        for line in lines[1:]:
            if line == "---":
                break
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def apply_team() -> None:
    """Write builder.team model/effort into each agent's frontmatter (idempotent)."""
    t = team()
    for role in AGENT_ROLES:
        path, spec = agent_file(role), t.get(role)
        if not path.exists() or not isinstance(spec, dict):
            continue
        lines = path.read_text().splitlines(keepends=True)
        end = next(i for i, line in enumerate(lines[1:], 1) if line.rstrip("\n") == "---")
        head = [line for line in lines[1:end] if not re.match(r"(model|effort)\s*:", line)]
        head += [f"model: {spec['model']}\n", f"effort: {spec['effort']}\n"]
        path.write_text("".join([lines[0], *head, *lines[end:]]))
        print(f"team: {role} → {spec['model']} ({spec['effort']})")


# --- checks ---------------------------------------------------------------------------

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

    errors = team_errors()
    if errors:
        stop("the Builder team is misconfigured:\n  " + "\n  ".join(errors))

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
        # A session cut off by a usage limit is not a cycle: it costs dollars, not a cycle slot.
        ran_today = sum(1 for line in CYCLES_LOG.read_text().splitlines()
                        if line.startswith(today) and " result=limit " not in line)
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
    r"usage limit|session limit|rate.?limit|limit reached|limit will reset|resets at|resets \d|429|"
    r"overloaded|quota",
    re.IGNORECASE,
)
# HTTP statuses that mean "the API would not serve us right now", not "the cycle went wrong".
LIMIT_STATUSES = {429, 529}


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


def result_json(log_text: str) -> dict:
    """The final `claude -p --output-format json` object in a run's log; {} if unreadable."""
    for line in reversed(log_text.strip().splitlines()):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            return d
    return {}


def limit_hit(log_text: str) -> str | None:
    """Why the session was cut off by the API (usage/rate limit, overload), or None.

    Read from the structured result first (api_error_status / api_error), then from the result
    text of an errored session, then — only if the log holds no result object at all — from the
    raw log. Spending money before the limit hit does not make it a failure (cycle 33: $1.01,
    architect done, then `usage_limit_reached`).
    """
    d = result_json(log_text)
    if d:
        status = d.get("api_error_status")
        error = str(d.get("api_error") or "")
        if status in LIMIT_STATUSES or re.search(r"limit|overloaded|quota", error, re.IGNORECASE):
            return f"{status or ''} {error} — {d.get('result', '')}".strip()
        if d.get("is_error") and LIMIT_MARKERS.search(str(d.get("result") or "")):
            return str(d.get("result"))
        return None
    m = LIMIT_MARKERS.search(log_text)
    return m.group(0) if m else None


def run_cost(log_text: str) -> float:
    try:
        return float(result_json(log_text).get("total_cost_usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def models_used(log_text: str) -> dict[str, float]:
    """{'opus': 2.1, 'sonnet': 1.3}: cost per model family in this run."""
    out: dict[str, float] = {}
    for model_id, usage in (result_json(log_text).get("modelUsage") or {}).items():
        family = next((m for m in MODELS if m in model_id), model_id)
        out[family] = out.get(family, 0.0) + float(usage.get("costUSD") or 0)
    return out


def read_log(logfile: str | None) -> str:
    if not logfile:
        return ""
    try:
        return Path(logfile).read_text(errors="replace")[-50000:]
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
         30 the session was cut off by a usage/rate limit — its cost is logged (result=limit),
            the failure counter is untouched, the runner stops
    A run that did not advance state/loop_status.json is NEVER counted as merged.
    """
    FIRM_HOME.mkdir(parents=True, exist_ok=True)
    status_file = ROOT / "state" / "loop_status.json"
    after = last_cycle()
    log_text = read_log(logfile)
    cost = run_cost(log_text)
    used = models_used(log_text)
    models = ",".join(f"{m}:{c:.2f}" for m, c in sorted(used.items())) or "none"

    if after > before:
        try:
            result = json.loads(status_file.read_text()).get("result", "failed")
        except (OSError, json.JSONDecodeError):
            result = "failed"
    else:
        why = limit_hit(log_text)
        if why is not None:
            with CYCLES_LOG.open("a") as fh:
                fh.write(f"{dt.date.today().isoformat()} cycle={before + 1} result=limit cost={cost:.4f} "
                         f"models={models}\n")
            print(f"POST: the session was cut off by the API ({why}). Cost ${cost:.2f} logged; "
                  "not a cycle, not a failure — the next run resumes it.")
            sys.exit(30)
        result = "failed"
        print("POST: the run did not advance state/loop_status.json — counted as failed.")

    warn = ""
    # Gate 5's auditor runs on its own model; a merge with no usage of that model means the
    # review was skipped or downgraded. Flag it for the Human (it cannot be hidden from this log).
    auditor_model = (team().get("auditor") or {}).get("model")
    if result == "merged" and auditor_model and not any(auditor_model in m for m in used):
        warn = f" warn=merged-without-{auditor_model}-usage"
    with CYCLES_LOG.open("a") as fh:
        fh.write(f"{dt.date.today().isoformat()} cycle={after} result={result} cost={cost:.4f} "
                 f"models={models}{warn}\n")
    failures = int(FAILURES.read_text()) if FAILURES.exists() else 0
    failures = 0 if result == "merged" else failures + 1
    FAILURES.write_text(str(failures))
    print(f"POST: result={result} cost=${cost:.2f} models={models} spent_today=${spent_today():.2f} "
          f"consecutive_failures={failures}{warn}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--post":
        post(int(sys.argv[2]) if len(sys.argv) > 2 else 0, sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) > 2 and sys.argv[1] == "--cost":
        print(f"{run_cost(read_log(sys.argv[2])):.4f}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--apply-team":
        apply_team()
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
