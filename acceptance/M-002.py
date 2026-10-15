"""Acceptance check for M-002 — a run is a self-contained proof object (Era I EC2 path, vision M2).

A recorded month must be re-livable from ONE file: ``fund-runtime replay --cassette F --verify``
rebuilds the recorded world from the recipe inside F, replays every mind from its tape at $0, and
says either ``IDENTICAL: <n> events, 0 differences, $0`` or ``DIVERGED at step <s>, wake <id>, ...``.

  Part A  record a hosted 31-step month (``backtest --world``): a canonical v2 cassette that
          carries parameters, spec digests, per-wake model/tools digest, the world recipe and the
          exported ledger, and never the world key.
  Part B  verify from an empty directory with nothing but the file (and the world key, by design).
  Part C  a tampered reply (a halved order) reads DIVERGED at its step and wake.
  Part D  a tampered ledger row only (every tape still matches) reads DIVERGED at its step.
  Part E  a setup error (wrong key, no key, unknown tool) is never read as DIVERGED.
  Part F  a v1 cassette and a cassette without a world are refused by name.

Self-contained: stdlib + subprocess; imports neither ``app`` nor ``runtime``. Offline, no LLM, fake
money, leaves nothing behind.

    uv run python acceptance/M-002.py        # exit 0 = the capability works
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPECS = "specs/desk-month"
WORLD_FILE = REPO / SPECS / "world.json"
KEY = hashlib.sha256(b"fund-acceptance-M-002/1").hexdigest()
OTHER_KEY = hashlib.sha256(b"other-world").hexdigest()
STEPS = 31

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)
    return ok


def canon(doc: object) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(doc: object) -> str:
    return hashlib.sha256(canon(doc).encode("ascii")).hexdigest()


def runtime(env: dict[str, str], *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", "run", "--project", str(REPO), "fund-runtime", *args], cwd=cwd,
                          env=env, capture_output=True, text=True, timeout=900)


def verdict(r: subprocess.CompletedProcess[str]) -> tuple[str, dict | None]:
    """(line 1 of stdout, the evidence JSON after it)."""
    first, _, rest = r.stdout.partition("\n")
    try:
        return first, json.loads(rest)
    except ValueError:
        return first, None


def write(path: Path, doc: object) -> Path:
    path.write_text(canon(doc), encoding="ascii")
    return path


def tampered(tmp: Path, name: str, doc: object) -> Path:
    return write(tmp / name, doc)


def never_diverged(r: subprocess.CompletedProcess[str]) -> bool:
    return "DIVERGED" not in r.stdout and "DIVERGED" not in r.stderr


def wakes(doc: dict) -> list[tuple[int, dict]]:
    return [(s["step"], w) for s in doc["outcome"]["run"]["steps"] for w in s.get("wakes") or []]


def main() -> int:
    started = time.monotonic()
    if (REPO / "governance" / "HALT").exists():
        print("governance/HALT exists: not running")
        return 1
    with tempfile.TemporaryDirectory(prefix="fund-m002-") as t:
        tmp = Path(t)
        vtmp = tmp / "vtmp"
        vtmp.mkdir()
        sentinel = tmp / "sentinel.db"
        env = {k: v for k, v in os.environ.items() if not k.startswith("FUND_")}
        env.update({"FUND_MARKETDATA__SYNTHETIC_KEY": KEY, "TMPDIR": str(vtmp),
                    "FUND_DATABASE_URL": f"sqlite:///{sentinel}"})
        cassette = tmp / "m.cassette.json"

        # ---- Part A
        r = runtime(env, "backtest", "--world", f"{SPECS}/world.json", "--specs", SPECS,
                    "--input", f"{SPECS}/input.json", "--steps", str(STEPS),
                    "--cassette", str(cassette), cwd=REPO)
        if not check("A: backtest --world records the month", r.returncode == 0 and cassette.exists(),
                     f"exit {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}"):
            return finish(started)
        try:
            outcome = json.loads(r.stdout)
        except ValueError:
            outcome = {}
        run = outcome.get("run") or {}
        all_wakes = [w for s in run.get("steps", []) for w in s.get("wakes") or []]
        check("A: completed, 31 steps, 62 wakes, all done",
              run.get("ended") == "completed" and len(run.get("steps", [])) == STEPS
              and len(all_wakes) == 2 * STEPS and all(w.get("ended") == "done" for w in all_wakes),
              f"ended={run.get('ended')} steps={len(run.get('steps', []))} wakes={len(all_wakes)}")
        text = cassette.read_text(encoding="ascii")
        doc = json.loads(text)
        check("A: file is mode 0600 and canonical",
              stat.S_IMODE(cassette.stat().st_mode) == 0o600 and text == canon(doc))
        check("A: v2 top-level keys",
              set(doc) == {"cassette_version", "hash_format", "ledger", "outcome", "parameters",
                           "redactions", "specs", "world"} and doc.get("cassette_version") == 2)
        check("A: parameters recorded",
              doc.get("parameters") == {"days_per_step": 1, "max_tool_calls": 64, "steps": STEPS,
                                        "workflow_input": {"universe": ["SYNA", "SYNB"]}},
              str(doc.get("parameters")))
        specs = doc.get("specs") or []
        check("A: specs sorted by id, each digest right",
              len(specs) == 2 and [s["spec"]["id"] for s in specs] == sorted(s["spec"]["id"] for s in specs)
              and all(s["sha256"] == sha(s["spec"]) for s in specs))
        check("A: every wake carries model and a 64-hex tools_sha256",
              all("model" in w and isinstance(w.get("tools_sha256"), str)
                  and len(w["tools_sha256"]) == 64 for _, w in wakes(doc)))
        check("A: world is the recipe", doc.get("world") == {"recipe": json.loads(WORLD_FILE.read_text())})
        ledger = doc.get("ledger") or {}
        rows = ledger.get("rows") or []
        n = len(rows)
        types = [row[3] for row in rows]
        check("A: ledger exported", ledger.get("ledger_format") == "fund-ledger-rows/1" and n > 0
              and types[:1] == ["run_started"], f"{n} rows")
        declared = [row for row in rows if row[3] == "run_minds_declared"]
        check("A: one minds declaration (scripted), 31 clock advances",
              len(declared) == 1 and json.loads(declared[0][4]) == {"minds": ["scripted"]}
              and types.count("clock_advanced") == STEPS)
        check("A: the world key is nowhere", KEY not in text and KEY not in r.stdout + r.stderr)
        check("A: no stray database, no temp world left", not sentinel.exists() and not any(vtmp.iterdir()))
        if n == 0:
            return finish(started)

        # ---- Part B
        elsewhere = tmp / "elsewhere"
        elsewhere.mkdir()
        lone = elsewhere / "m.cassette.json"
        lone.write_text(text, encoding="ascii")
        r = runtime(env, "replay", "--cassette", "m.cassette.json", "--verify", cwd=elsewhere)
        line, ev = verdict(r)
        check("B: verify from an empty directory is IDENTICAL",
              r.returncode == 0 and line.startswith(f"IDENTICAL: {n} events, 0 differences, $0"),
              f"exit {r.returncode}: {line or r.stderr.strip()[-300:]}")
        ev = ev or {}
        check("B: evidence", ev.get("events") == n and (ev.get("replay") or {}).get("ended") == "completed"
              and (ev.get("compare") or {}).get("equal") is True
              and (ev.get("compare") or {}).get("allowed") == 1 and ev.get("replay_usd") == 0, str(ev)[:300])
        check("B: nothing left behind", os.listdir(elsewhere) == ["m.cassette.json"]
              and not any(vtmp.iterdir()) and not sentinel.exists())

        # ---- Part C
        target = None
        for s, w in wakes(doc):
            if s >= 5 and w["spec_id"] == "b-pm":
                for m in w["transcript"]:
                    for c in m.get("tool_calls") or []:
                        if m["role"] == "assistant" and c["name"] == "place_order" and target is None:
                            target = (s, c)
        if check("C: a place_order to tamper exists", target is not None, "tamper target moved"):
            s, call = target
            d2 = copy.deepcopy(doc)
            for s2, w in wakes(d2):
                for m in w["transcript"]:
                    for c in m.get("tool_calls") or []:
                        if s2 == s and w["spec_id"] == "b-pm" and c["id"] == call["id"]:
                            q = c["arguments"]["qty"]
                            c["arguments"]["qty"] = max(1, q // 2) if q != max(1, q // 2) else q + 1
            r = runtime(env, "replay", "--cassette", str(tampered(tmp, "c.cassette.json", d2)),
                        "--verify", cwd=elsewhere)
            line, ev = verdict(r)
            check("C: tampered reply reads DIVERGED at its step and wake",
                  r.returncode == 1 and line.startswith(f"DIVERGED at step {s}, wake b-pm, turn ")
                  and ((ev or {}).get("where") or {}).get("kind") == "world", f"exit {r.returncode}: {line}")

        # ---- Part D
        advances = [row[0] for row in rows if row[3] == "clock_advanced"]
        victim = next((i for i, row in enumerate(rows) if row[0] > advances[11]), None)
        if check("D: a row after the 12th advance exists", victim is not None):
            d3 = copy.deepcopy(doc)
            d3["ledger"]["rows"][victim][4] += " "
            r = runtime(env, "replay", "--cassette", str(tampered(tmp, "d.cassette.json", d3)),
                        "--verify", cwd=elsewhere)
            line, ev = verdict(r)
            ev = ev or {}
            check("D: tampered ledger row reads DIVERGED at its step, tapes all matched",
                  r.returncode == 1 and line.startswith("DIVERGED at step 12")
                  and (ev.get("where") or {}).get("event_id") == rows[victim][0]
                  and (ev.get("replay") or {}).get("ended") == "completed", f"exit {r.returncode}: {line}")

        # ---- Part E
        r = runtime({**env, "FUND_MARKETDATA__SYNTHETIC_KEY": OTHER_KEY}, "replay", "--cassette",
                    str(lone), "--verify", cwd=elsewhere)
        line, _ = verdict(r)
        check("E1: wrong world key is a SETUP ERROR (exit 3) at event 1",
              r.returncode == 3 and line.startswith("SETUP ERROR") and "event 1 (run_started)" in line
              and never_diverged(r), f"exit {r.returncode}: {line}")
        noenv = {k: v for k, v in env.items() if k != "FUND_MARKETDATA__SYNTHETIC_KEY"}
        r = runtime(noenv, "replay", "--cassette", str(lone), "--verify", cwd=elsewhere)
        check("E2: no key is exit 2, nothing spawned", r.returncode == 2 and never_diverged(r)
              and not any(vtmp.iterdir()), f"exit {r.returncode}: {r.stderr.strip()[-200:]}")
        d4 = copy.deepcopy(doc)
        for entry in d4["specs"]:
            if entry["spec"]["id"] == "b-pm":
                entry["spec"]["tools"] = ["no_such_tool"]
                entry["sha256"] = sha(entry["spec"])
        r = runtime(env, "replay", "--cassette", str(tampered(tmp, "e.cassette.json", d4)),
                    "--verify", cwd=elsewhere)
        line, _ = verdict(r)
        check("E3: an unknown tool is a SETUP ERROR (exit 3), never DIVERGED",
              r.returncode == 3 and "unknown_tool" in line and never_diverged(r),
              f"exit {r.returncode}: {line}")

        # ---- Part F
        v1 = {"cassette_version": 1, "hash_format": doc["hash_format"], "outcome": doc["outcome"],
              "redactions": 0}
        r = runtime(env, "replay", "--cassette", str(tampered(tmp, "f1.cassette.json", v1)),
                    "--verify", cwd=elsewhere)
        check("F1: v1 is refused by name (exit 2)", r.returncode == 2 and "cassette version 1" in r.stderr,
              f"exit {r.returncode}: {r.stderr.strip()[-200:]}")
        d5 = {**doc, "world": None, "ledger": None}
        r = runtime(env, "replay", "--cassette", str(tampered(tmp, "f2.cassette.json", d5)),
                    "--verify", cwd=elsewhere)
        check("F2: a cassette without a world is refused by name (exit 2)",
              r.returncode == 2 and "no world" in r.stderr, f"exit {r.returncode}: {r.stderr.strip()[-200:]}")
        check("end: no temp world left", not any(vtmp.iterdir()) and not sentinel.exists())
    return finish(started)


def finish(started: float) -> int:
    elapsed = time.monotonic() - started
    check("runs in under 15 minutes", elapsed < 900, f"{elapsed:.0f}s")
    if FAILED:
        print(f"\nREJECTED: {len(FAILED)} check(s) failed: {', '.join(FAILED)}")
        return 1
    print("\nACCEPTED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
