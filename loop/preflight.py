#!/usr/bin/env python3
"""Loop preflight and out-of-band referee. HUMAN-ONLY FILE (Constitution Art. 6).

Builder v3 (ADR-046): the unit of work is an idea from bible/IDEAS_BOOK.md (protocol/CYCLE.md); a "cycle" is one session
of `claude -p "/cycle <mode>"`. This file decides the mode, and after each session it measures and
verifies what the session claims — outside the Builder's reach, so a claim cannot grade itself.

Usage (from the repo root, via `uv run python loop/preflight.py ...`):
  (no args)       run every check before a session. Exit codes:
                    0  go
                    10 go, but run a DIAGNOSIS session (failure limit reached)
                    20 stop for today (daily session limit or daily USD cap reached)
                    1  stop the loop (halt, seal broken, team misconfigured, open incident,
                       repeated failure)
  --mode          print the next session's mode: plan | build (missions.json + cycles.log)
  --post N LOG MODE START
                  after a session: N = last cycle before it, LOG = its output file, MODE = its mode,
                  START = its start time (epoch seconds). Verifies main and the mission's acceptance
                  check out of band, appends to cycles.log and metrics.jsonl. A session cut off by a
                  usage/rate limit exits 30 (result=limit: not a cycle, not a failure).
  --reset-wait LOG  seconds to wait for the usage limit named in LOG to reset (+3 min), or -1
  --regression    re-run every done mission's acceptance check on main → $FIRM_HOME/regression.json
  --sandbox-settings  print the --settings JSON that puts the session's shell in the OS sandbox
  --cost LOG      print the USD cost of one session, read from its output file
  --apply-team    write builder.team models/efforts into the .claude/agents/ frontmatter
  --last-cycle    print the cycle number in state/loop_status.json
  --spent-today   print the USD spent by Builder sessions today
  --get a.b.c     print a value from governance/human.yaml ("" for null)

Reference hashes live OUTSIDE the repo ($FIRM_HOME/protected.sha256, default ~/.firm),
written by loop/seal.sh, so nothing inside the repo can forge them. So do the referee's records.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FIRM_HOME = Path(os.environ.get("FIRM_HOME", Path.home() / ".firm"))
SEAL = FIRM_HOME / "protected.sha256"
FAILURES = FIRM_HOME / "failures"
CYCLES_LOG = FIRM_HOME / "cycles.log"
METRICS = FIRM_HOME / "metrics.jsonl"
ACCEPTANCE_LEDGER = FIRM_HOME / "acceptance.json"
REGRESSION = FIRM_HOME / "regression.json"
VERIFIED_MAIN = FIRM_HOME / "verified_main"
VERIFY_DIR = FIRM_HOME / "verify"          # a detached git worktree the referee checks out
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
AGENT_ROLES = ("auditor", "red-team", "worker")    # Builder v3 (ADR-046): no architect, no validator
SESSION_ROLES = ("lead", "lead_hard", "helpers")
MODELS = {"opus", "sonnet", "haiku", "fable"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
RESULTS = {"merged", "progress", "planned", "failed", "blocked"}
GOOD_RESULTS = {"merged", "progress", "planned"}


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


def builder_cfg() -> dict:
    return config().get("builder", {}) or {}


def get(key: str):
    node = config()
    for part in key.split("."):
        node = node[part]
    return node


def num(value) -> float | None:
    """A cap from human.yaml: None (no cap) or a float."""
    return None if value is None or value == "" else float(value)


def stop(msg: str, code: int = 1) -> None:
    print(f"PREFLIGHT: {msg}")
    sys.exit(code)


def git(*args: str, cwd: Path = ROOT, check: bool = False) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


# --- the team -------------------------------------------------------------------------

def team() -> dict[str, dict]:
    return builder_cfg().get("team", {}) or {}


def team_errors() -> list[str]:
    """Everything wrong with builder.team: a typo here would burn a session, so it stops the loop."""
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

    dirty = git("status", "--porcelain")
    if dirty:
        # Not fatal: session step 0 inspects leftovers from an interrupted session.
        print(f"PREFLIGHT: warning — working tree not clean:\n{dirty}")

    incidents = ROOT / "state" / "INCIDENTS.md"
    if incidents.exists():
        text = incidents.read_text()
        for block in text.split("\n## ")[1:]:
            if "severity: high" in block and "status: open" in block:
                stop("open high-severity incident in state/INCIDENTS.md.")

    cfg = builder_cfg()
    today = dt.date.today().isoformat()
    ran_today = 0
    if CYCLES_LOG.exists():
        # A session cut off by a usage limit is not a cycle: it costs dollars, not a cycle slot.
        ran_today = sum(1 for line in CYCLES_LOG.read_text().splitlines()
                        if line.startswith(today) and " result=limit " not in line)
    if ran_today >= int(cfg.get("max_cycles_per_day") or 24):
        stop(f"daily session limit reached ({ran_today}).", 20)
    # Dollar caps are optional (null = none). With a per-session cap, a session starts only if its
    # whole budget fits under today's cap; without one, only if today's cap is not yet reached.
    spent, cap, per_cycle = spent_today(), num(cfg.get("max_usd_per_day")), num(cfg.get("max_usd_per_cycle"))
    if cap is not None and spent + (per_cycle or 0.0) > cap:
        stop(f"daily budget reached (${spent:.2f} spent, cap ${cap:.2f}).", 20)

    failures = int(FAILURES.read_text()) if FAILURES.exists() else 0
    limit = int(cfg.get("max_consecutive_failures", 3))
    if failures > limit:
        stop(f"{failures} consecutive failed sessions, diagnosis included. Read state/BLOCKED.md, "
             f"then delete {FAILURES} to resume.")
    if failures == limit:
        stop("failure limit reached — run one diagnosis session.", 10)

    print("PREFLIGHT: go")


# --- missions and the session mode ----------------------------------------------------

def missions(root: Path = ROOT) -> list[dict]:
    try:
        data = json.loads((root / "state" / "missions.json").read_text())
        return [m for m in data.get("missions", []) if isinstance(m, dict) and m.get("id")]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def metrics_rows() -> list[dict]:
    if not METRICS.exists():
        return []
    rows = []
    for line in METRICS.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def accepted_since_last_plan() -> int:
    n = 0
    for row in metrics_rows():
        if row.get("mode") == "plan" and row.get("result") == "planned":
            n = 0
        elif row.get("accepted") is True:
            n += 1
    return n


def sessions_on(mission_id: str) -> int:
    return sum(1 for r in metrics_rows() if r.get("mode") == "build" and r.get("mission") == mission_id)


def next_mode() -> str:
    """plan | build — deterministic, from the repo's missions.json and the referee's own records."""
    ms = missions()
    done = {m["id"] for m in ms if m.get("status") == "done"}
    active = [m for m in ms if m.get("status") == "active"]
    open_branches = [b.strip(" *+") for b in git("branch", "--no-merged", "main").splitlines()
                     if b.strip(" *+").startswith(("mission/", "idea/"))]
    if active:
        m = active[0]
        est = int(m.get("estimate_sessions") or 2)
        if sessions_on(m["id"]) >= max(2 * est, est + 2):
            return "plan"    # a mission at twice its estimate is re-cut by a planner, not ground on
        return "build"
    if open_branches:
        return "build"
    if accepted_since_last_plan() >= int(builder_cfg().get("plan_every_missions") or 3):
        return "plan"
    ready = [m for m in ms if m.get("status") == "ready"
             and all(d in done for d in (m.get("depends_on") or []))]
    return "build" if ready else "plan"


# --- the out-of-band referee ----------------------------------------------------------

def run(cmd: list[str], cwd: Path, timeout_s: int) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("FIRM_BUILDER_SESSION", "VIRTUAL_ENV")}
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, env=env)
        return r.returncode, (r.stdout + r.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout_s}s"
    except OSError as e:
        return 127, str(e)


def checkout(ref: str) -> Path:
    """The referee's own detached worktree at `ref` (its .venv survives between checks)."""
    if not (VERIFY_DIR / ".git").exists():
        FIRM_HOME.mkdir(parents=True, exist_ok=True)
        git("worktree", "prune")
        git("worktree", "add", "--detach", "--force", str(VERIFY_DIR), ref, check=True)
    else:
        git("checkout", "--detach", "--force", ref, cwd=VERIFY_DIR, check=True)
        git("clean", "-fdq", cwd=VERIFY_DIR)
    return VERIFY_DIR


def acceptance_timeout() -> int:
    return int(float(builder_cfg().get("acceptance_timeout_minutes") or 20) * 60)


def run_acceptance(where: Path, path: str) -> tuple[bool | None, str]:
    if not (where / path).exists():
        return None, f"{path} does not exist"
    rc, out = run(["uv", "run", "--quiet", "python", path], where, acceptance_timeout())
    return rc == 0, out


def verify_main() -> dict:
    """Suite on main, once per new main commit. {'sha', 'green', 'passed', 'tail'}."""
    sha = git("rev-parse", "main")
    if VERIFIED_MAIN.exists():
        try:
            last = json.loads(VERIFIED_MAIN.read_text())
            if last.get("sha") == sha:
                return {**last, "fresh": False}
        except json.JSONDecodeError:
            pass
    where = checkout(sha)
    rc, out = run(["uv", "run", "--quiet", "pytest", "-p", "no:warnings", "-o", "addopts=", "-q"], where, 3600)
    m = re.search(r"(\d+) passed", out)
    res = {"sha": sha, "green": rc == 0, "passed": int(m.group(1)) if m else None, "tail": out[-600:]}
    VERIFIED_MAIN.write_text(json.dumps(res))
    return {**res, "fresh": True}


def acceptance_ledger() -> dict:
    try:
        return json.loads(ACCEPTANCE_LEDGER.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def track_acceptance(cycle: int) -> list[str]:
    """Record each mission's acceptance file the first time it is seen, and every later change."""
    ledger, changed = acceptance_ledger(), []
    for m in missions():
        path = m.get("acceptance")
        if not path or m.get("status") not in ("active", "done") or not (ROOT / path).exists():
            continue
        sha = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        rec = ledger.setdefault(m["id"], {"path": path, "first_seen_cycle": cycle, "sha": sha, "changes": 0,
                                          "red_first": None})
        if rec["sha"] != sha:
            rec["sha"], rec["changes"] = sha, rec["changes"] + 1
            changed.append(m["id"])
    ACCEPTANCE_LEDGER.write_text(json.dumps(ledger, indent=1, sort_keys=True))
    return changed


def red_first(mission_id: str, path: str) -> bool | None:
    """Did the acceptance check fail at the commit that added it? Checked once per mission."""
    ledger = acceptance_ledger()
    rec = ledger.get(mission_id) or {}
    if rec.get("red_first") is not None:
        return rec["red_first"]
    commits = git("log", "main", "--diff-filter=A", "--format=%H", "--", path).splitlines()
    if not commits:
        return None
    ok, _ = run_acceptance(checkout(commits[-1]), path)
    result = None if ok is None else (ok is False)
    ledger.setdefault(mission_id, {"path": path})["red_first"] = result
    ACCEPTANCE_LEDGER.write_text(json.dumps(ledger, indent=1, sort_keys=True))
    return result


def regression() -> dict:
    """Every done mission's acceptance check, re-run on main (before each planning session)."""
    sha = git("rev-parse", "main")
    results = {}
    for m in missions():
        if m.get("status") == "done" and m.get("acceptance"):
            ok, out = run_acceptance(checkout(sha), m["acceptance"])
            results[m["id"]] = {"pass": ok, "tail": out[-300:]}
    rep = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "main": sha, "results": results,
           "failing": sorted(k for k, v in results.items() if v["pass"] is not True)}
    REGRESSION.write_text(json.dumps(rep, indent=1))
    return rep


def lines_written(since_epoch: int) -> dict[str, int]:
    """Lines added+removed in commits made during the session, all branches, by kind of file."""
    out = git("log", "--all", "--no-merges", f"--since=@{since_epoch}", "--numstat", "--format=")
    kinds = {"product": 0, "tests": 0, "docs": 0, "other": 0}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        n, f = int(parts[0]) + int(parts[1]), parts[2]
        if re.match(r"(app|runtime|mcp_server|scripts|migrations)/", f):
            kinds["product"] += n
        elif re.match(r"(tests|acceptance)/", f):
            kinds["tests"] += n
        elif re.match(r"(state|bible|docs|protocol)/", f) or f.endswith(".md"):
            kinds["docs"] += n
        else:
            kinds["other"] += n
    return kinds


# --- cost, limits ---------------------------------------------------------------------

LIMIT_MARKERS = re.compile(
    r"usage limit|session limit|rate.?limit|limit reached|limit will reset|resets at|resets \d|429|"
    r"overloaded|quota",
    re.IGNORECASE,
)
# HTTP statuses that mean "the API would not serve us right now", not "the session went wrong".
LIMIT_STATUSES = {429, 529}


def spent_today() -> float:
    """USD spent by Builder sessions today, summed from the cost= field of $FIRM_HOME/cycles.log."""
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
    """The final `claude -p --output-format json` object in a session's log; {} if unreadable."""
    for line in reversed(log_text.strip().splitlines()):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            return d
    return {}


def limit_hit(log_text: str) -> str | None:
    """Why the session was cut off by the API (usage/rate limit, overload), or None."""
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


RESET_AT = re.compile(r"resets\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(([^)]+)\))?", re.IGNORECASE)


def reset_wait(log_text: str, now: dt.datetime | None = None) -> int:
    """Seconds until the usage limit in the log resets (+3 min margin), or -1 if unknown or too far."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    why = limit_hit(log_text) or ""
    m = RESET_AT.search(why) or RESET_AT.search(log_text)
    if not m:
        return -1
    hour, minute, ampm, tzname = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), m.group(4)
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return -1
    try:
        tz = ZoneInfo(tzname) if tzname else None
    except (ZoneInfoNotFoundError, ValueError):
        tz = None
    if now is None:
        now = dt.datetime.now(tz) if tz else dt.datetime.now().astimezone()
    elif tz is not None:
        now = now.astimezone(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    secs = int((target - now).total_seconds()) + 180
    max_wait = float(builder_cfg().get("max_wait_hours") or 6) * 3600
    return secs if secs <= max_wait else -1


def run_cost(log_text: str) -> float:
    try:
        return float(result_json(log_text).get("total_cost_usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def models_used(log_text: str) -> dict[str, float]:
    """{'opus': 2.1, 'sonnet': 1.3}: cost per model family in this session."""
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


def loop_status() -> dict:
    try:
        d = json.loads((ROOT / "state" / "loop_status.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def last_cycle() -> int:
    try:
        return int(loop_status().get("cycle", 0))
    except (ValueError, TypeError):
        return 0


def post(before: int, logfile: str | None, mode: str, start: int) -> None:
    """Classify and verify the session that just ended. Exit codes:
         0  a real session ran (merged / progress / planned / failed / blocked)
         30 the session was cut off by a usage/rate limit — cost logged (result=limit),
            the failure counter is untouched
    A session that did not advance state/loop_status.json is NEVER counted as a success, and a
    claimed merge that the referee cannot reproduce (main red, acceptance failing) counts as failed.
    """
    FIRM_HOME.mkdir(parents=True, exist_ok=True)
    after = last_cycle()
    log_text = read_log(logfile)
    d = result_json(log_text)
    cost = run_cost(log_text)
    used = models_used(log_text)
    models = ",".join(f"{m}:{c:.2f}" for m, c in sorted(used.items())) or "none"
    today = dt.date.today().isoformat()

    if after <= before:
        why = limit_hit(log_text)
        if why is not None:
            with CYCLES_LOG.open("a") as fh:
                fh.write(f"{today} cycle={before + 1} result=limit cost={cost:.4f} models={models} mode={mode}\n")
            append_metrics({"cycle": before + 1, "mode": mode, "result": "limit", "cost": round(cost, 4),
                            "why": why[:200], **session_numbers(d, start)})
            print(f"POST: the session was cut off by the API ({why}). Cost ${cost:.2f} logged; "
                  "not a cycle, not a failure — the next session resumes it.")
            sys.exit(30)

    status = loop_status() if after > before else {}
    result = status.get("result") if status.get("result") in RESULTS else "failed"
    if after <= before:
        print("POST: the session did not advance state/loop_status.json — counted as failed.")
    mission = status.get("mission")
    flags: list[str] = []
    row: dict = {"cycle": after if after > before else before + 1, "mode": mode, "mission": mission,
                 "claimed": status.get("result"), "cost": round(cost, 4), "models": used,
                 **session_numbers(d, start), "lines": lines_written(start)}

    changed = track_acceptance(row["cycle"])
    if changed:
        flags.append("acceptance_changed:" + "+".join(changed))

    main = verify_main()
    row["main_green"], row["tests_passed"] = main["green"], main["passed"]
    if not main["green"]:
        flags.append("main_red")
        result = "failed"

    if result == "merged" and mode == "build":
        m = next((x for x in missions() if x["id"] == mission), None)
        if m is None or not m.get("acceptance"):
            flags.append("merged_without_mission")
            result = "failed"
        else:
            ok, out = run_acceptance(checkout(main["sha"]), m["acceptance"])
            row["accepted"] = ok is True
            row["red_first"] = red_first(m["id"], m["acceptance"])
            if ok is not True:
                flags.append("false_done")
                row["acceptance_tail"] = out[-600:]
                result = "failed"
    if mode == "plan" and result == "planned":
        if not any(m.get("status") == "ready" for m in missions()):
            flags.append("plan_without_ready_mission")
            result = "failed"

    # Builder v3: only risk-tier ideas (physics: true) need the auditor. When the auditor runs on a
    # model the lead does not use, a merge with no usage of that model means the review was skipped.
    auditor_model = (team().get("auditor") or {}).get("model")
    lead_models = {(team().get(r) or {}).get("model") for r in ("lead", "lead_hard")}
    entry = next((x for x in missions() if x["id"] == mission), None) or {}
    if (result == "merged" and entry.get("physics") and auditor_model and auditor_model not in lead_models
            and not any(auditor_model in x for x in used)):
        flags.append(f"merged-without-{auditor_model}-usage")

    row["result"], row["flags"] = result, flags
    append_metrics(row)
    accepted = {True: "yes", False: "no"}.get(row.get("accepted"), "-")
    with CYCLES_LOG.open("a") as fh:
        fh.write(f"{today} cycle={row['cycle']} result={result} cost={cost:.4f} models={models}"
                 f"{' warn=' + ','.join(flags) if flags else ''} mode={mode} mission={mission or '-'} "
                 f"accepted={accepted} main={'green' if main['green'] else 'red'}\n")
    failures = int(FAILURES.read_text()) if FAILURES.exists() else 0
    failures = 0 if result in GOOD_RESULTS else failures + 1
    FAILURES.write_text(str(failures))
    print(f"POST: mode={mode} result={result} mission={mission or '-'} accepted={accepted} "
          f"main={'green' if main['green'] else 'RED'} cost=${cost:.2f} lines={row['lines']} "
          f"flags={','.join(flags) or 'none'} consecutive_failures={failures}")


def session_numbers(d: dict, start: int) -> dict:
    return {"ts": dt.datetime.now().isoformat(timespec="seconds"), "turns": d.get("num_turns"),
            "minutes": round((time.time() - start) / 60, 1) if start else None,
            "api_minutes": round((d.get("duration_api_ms") or 0) / 60000, 1)}


def append_metrics(row: dict) -> None:
    FIRM_HOME.mkdir(parents=True, exist_ok=True)
    with METRICS.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def sandbox_settings() -> str:
    sb = builder_cfg().get("sandbox") or {}
    if not sb.get("enabled"):
        return ""
    return json.dumps({"sandbox": {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,       # admin-required: repo settings cannot loosen it
        "failIfUnavailable": True,
        "excludedCommands": ["git push origin *"],
        "filesystem": {"allowWrite": list(sb.get("allow_write") or [])},
        "network": {"allowedDomains": list(sb.get("allowed_domains") or []),
                    "allowLocalBinding": True, "strictAllowlist": True},
    }})


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--post"]:
        post(int(a[1]) if len(a) > 1 else 0, a[2] if len(a) > 2 else None,
             a[3] if len(a) > 3 else "build", int(a[4]) if len(a) > 4 else 0)
    elif a[:1] == ["--mode"]:
        print(next_mode())
    elif a[:1] == ["--reset-wait"] and len(a) > 1:
        print(reset_wait(read_log(a[1])))
    elif a[:1] == ["--regression"]:
        rep = regression()
        print(f"regression: {len(rep['results'])} done missions, failing: {rep['failing'] or 'none'}")
    elif a[:1] == ["--sandbox-settings"]:
        print(sandbox_settings())
    elif a[:1] == ["--cost"] and len(a) > 1:
        print(f"{run_cost(read_log(a[1])):.4f}")
    elif a[:1] == ["--apply-team"]:
        apply_team()
    elif a[:1] == ["--last-cycle"]:
        print(last_cycle())
    elif a[:1] == ["--spent-today"]:
        print(f"{spent_today():.2f}")
    elif a[:1] == ["--get"] and len(a) > 1:
        v = get(a[1])
        print("" if v is None else v)
    elif a[:1] == ["--hashes"]:
        print(json.dumps(current_hashes(), indent=1, sort_keys=True))
    else:
        check()
