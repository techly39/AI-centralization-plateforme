"""Acceptance demo — real AI agents (a PM and two analysts) live a backtest month on fake money.

The month was lived once, by real language models through OpenRouter, each agent on its own
metered key, and recorded in ``evidence/real-agents-backtest/month.cassette.json``. This check
spends $0 and needs no network: it reads that recording and replays it.

  A  the recording: a v2 cassette with its world recipe and ledger, and no provider key in it
  B  the minds: three real-model minds (one PM, two analysts) of one pod, on the metered provider
  C  the month: 31 days lived to the end; every wake got its own day's data package, and no bar
     in it is later than that day
  D  they acted: the PM placed orders that physics accepted, each analyst messaged the PM
  E  the cost: every agent's key spent money; the system's ledger holds exactly what each key
     cost; the total stays inside the Human's monthly cap
  F  the replay: ``fund-runtime replay --verify`` from the file alone says IDENTICAL, at $0
  then a plain report: day by day, what each agent did and what it cost.

Self-contained: stdlib + subprocess; imports neither ``app`` nor ``runtime``.

    uv run python acceptance/real_agents_backtest.py        # exit 0 = the idea works
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evidence" / "real-agents-backtest" / "month.cassette.json"
#: The world's seed. Not secret from the Human (agents never see the repo); the cassette never
#: carries it, so whoever verifies must know it (ADR-045).
KEY = hashlib.sha256(b"fund-real-agents-backtest/1").hexdigest()
STEPS = 31
PACKAGE = "prices-v1"
SECRET = re.compile(r"sk-or-[A-Za-z0-9-]{8,}")

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)
    return ok


def finish(started: float) -> int:
    print(f"\n{len(FAILED)} failed · {time.monotonic() - started:.0f} s")
    for name in FAILED:
        print(f"  FAILED: {name}")
    return 1 if FAILED else 0


def wakes(doc: dict) -> list[tuple[dict, dict]]:
    return [(s, w) for s in doc["outcome"]["run"]["steps"] for w in s.get("wakes") or []]


def context(wake: dict) -> dict:
    """The wake's first user message: what the Runtime handed the mind."""
    for m in wake.get("transcript") or []:
        if m["role"] == "user":
            try:
                return json.loads(m["content"])
            except ValueError:
                return {}
    return {}


def calls(wake: dict) -> list[tuple[dict, dict | None]]:
    """Every tool call of the wake with the result that answered it."""
    results = {m.get("tool_call_id"): m for m in wake.get("transcript") or [] if m["role"] == "tool"}
    return [(c, results.get(c["id"])) for m in wake.get("transcript") or []
            if m["role"] == "assistant" for c in m.get("tool_calls") or []]


def main() -> int:
    started = time.monotonic()
    if (REPO / "governance" / "HALT").exists():
        print("governance/HALT exists: not running")
        return 1

    # ---- A
    if not check("A: the recorded month exists", EVIDENCE.is_file(), str(EVIDENCE.relative_to(REPO))):
        return finish(started)
    text = EVIDENCE.read_text(encoding="ascii")
    doc = json.loads(text)
    check("A: a v2 cassette with its world and ledger",
          doc.get("cassette_version") == 2 and isinstance(doc.get("world"), dict)
          and bool((doc.get("ledger") or {}).get("rows")))
    check("A: no provider key anywhere in it", SECRET.search(text) is None)
    check("A: the world key is not in it", KEY not in text)

    # ---- B
    specs = [e["spec"] for e in doc.get("specs") or []]
    roles = sorted(s["role"] for s in specs)
    check("B: a PM and two analysts of one pod",
          roles == ["analyst", "analyst", "pm"] and len({s.get("pod") for s in specs}) == 1, str(roles))
    check("B: every mind is a real model on the metered provider",
          all(s["provider"] == "openrouter" and s.get("model") for s in specs),
          ", ".join(f"{s['id']}={s['provider']}/{s.get('model')}" for s in specs))
    run = doc["outcome"].get("run") or {}

    # ---- C
    steps = run.get("steps") or []
    check("C: the month was lived to the end",
          doc["outcome"].get("ended") == "completed" and len(steps) == STEPS,
          f"ended={doc['outcome'].get('ended')} steps={len(steps)}")
    late, missing = [], []
    for step, w in wakes(doc):
        day = step["at"][:10]
        pkg = context(w).get("package") or {}
        if pkg.get("name") != PACKAGE or pkg.get("day") != day:
            missing.append(f"{step['step']}:{w['spec_id']}")
            continue
        for ticker, bars in (pkg.get("bars") or {}).items():   # rows: [day, open, high, low, close, volume]
            if not bars or any(str(row[0])[:10] > day for row in bars):
                late.append(f"{step['step']}:{w['spec_id']}:{ticker}")
    check("C: every wake got its own day's package", not missing and bool(wakes(doc)),
          f"{len(wakes(doc))} wakes" + (f"; missing {missing[:5]}" if missing else ""))
    check("C: no package shows tomorrow, and none is empty", not late, str(late[:5]))

    # ---- D
    pm = next((s["id"] for s in specs if s["role"] == "pm"), None)
    analysts = [s["id"] for s in specs if s["role"] == "analyst"]
    orders = [(step["step"], c) for step, w in wakes(doc) if w["spec_id"] == pm
              for c, r in calls(w) if c["name"] == "place_order" and r and not r.get("is_error")]
    check("D: the PM placed orders physics accepted", len(orders) > 0, f"{len(orders)} orders")
    for a in analysts:
        sent = [c for _, w in wakes(doc) if w["spec_id"] == a for c, r in calls(w)
                if c["name"] == "send_message" and r and not r.get("is_error")]
        check(f"D: analyst {a} messaged the pod", len(sent) > 0, f"{len(sent)} messages")

    # ---- E
    metering = doc["outcome"].get("metering") or {}
    keys = metering.get("keys") or []
    check("E: one key per agent, each one spent",
          len(keys) == len(specs) and all(k["spent_usd_micros"] > 0 for k in keys),
          ", ".join(f"{k['spec_id']}=${k['spent_usd_micros'] / 1e6:.4f}" for k in keys))
    sync = metering.get("sync") or {}
    check("E: every dollar reached the ledger",
          sync.get("posted") == len(keys) and not sync.get("refused") and not sync.get("halted")
          and sync.get("error") is None, json.dumps(sync, sort_keys=True))
    agent_of = {k["spec_id"]: k["agent_id"] for k in keys}
    last: dict[int, int] = {}
    for row in doc["ledger"]["rows"]:
        if row[3] == "cost_metered":
            body = json.loads(row[4])
            last[body["agent_id"]] = body["usd_micros_total"]
    check("E: the ledger's cost per agent is the meter's",
          all(last.get(agent_of[k["spec_id"]]) == k["spent_usd_micros"] for k in keys))
    cap = metering.get("cap_usd_micros")
    total = metering.get("total_usd_micros", 0)
    check("E: the month's total is inside the monthly cap",
          isinstance(cap, int) and 0 < total <= cap, f"${total / 1e6:.4f} of ${(cap or 0) / 1e6:.0f}")

    # ---- F
    with tempfile.TemporaryDirectory(prefix="fund-real-agents-") as t:
        tmp = Path(t)
        (tmp / "vtmp").mkdir()
        lone = tmp / "month.cassette.json"
        lone.write_text(text, encoding="ascii")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("FUND_", "OPENROUTER")) and k.lower() not in {
                   "http_proxy", "https_proxy", "all_proxy"}}
        # No provider key exists in this process, and any outbound HTTP goes to a dead proxy.
        env.update({"FUND_MARKETDATA__SYNTHETIC_KEY": KEY, "TMPDIR": str(tmp / "vtmp"),
                    "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
                    "FUND_DATABASE_URL": f"sqlite:///{tmp / 'sentinel.db'}"})
        r = subprocess.run(["uv", "run", "--project", str(REPO), "fund-runtime", "replay",
                            "--cassette", lone.name, "--verify"], cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=900)
        line, _, rest = r.stdout.partition("\n")
        try:
            ev = json.loads(rest)
        except ValueError:
            ev = {}
        check("F: replay --verify from the file alone is IDENTICAL",
              r.returncode == 0 and line.startswith("IDENTICAL:"),
              f"exit {r.returncode}: {line or r.stderr.strip()[-300:]}")
        check("F: the replay cost $0 and the metered rows are reported apart",
              ev.get("replay_usd") == 0 and (ev.get("metered_block") or {}).get("rows") == len(keys),
              json.dumps({k: ev.get(k) for k in ("replay_usd", "metered_block")}, sort_keys=True))

    report(doc, specs, keys)
    return finish(started)


def report(doc: dict, specs: list[dict], keys: list[dict]) -> None:
    """What a person wants to see: who did what, each day, and what it cost."""
    print("\n== The month, as the agents lived it ==")
    names = {s["id"]: f"{s['name']} ({s['role']}, {s.get('model')})" for s in specs}
    per_day: dict[str, list[str]] = defaultdict(list)
    for step, w in wakes(doc):
        did = defaultdict(int)
        for c, r in calls(w):
            did[c["name"] + ("!" if r and r.get("is_error") else "")] += 1
        said = next((m["content"] for m in reversed(w.get("transcript") or [])
                     if m["role"] == "assistant" and m.get("content")), "")
        usd = sum((x.get("usage") or {}).get("cost_usd", 0) for x in w.get("exchanges") or [])
        acts = ", ".join(f"{n}×{k}" for k, n in sorted(did.items())) or "nothing"
        per_day[step["at"][:10]].append(
            f"  {w['spec_id']:<12} {acts:<55} ${usd:.4f}  {said[:90]!r}")
    for day in sorted(per_day):
        print(day)
        for line in per_day[day]:
            print(line)
    book = []
    for step, w in wakes(doc):
        for c, r in calls(w):
            if c["name"] == "get_portfolio" and r and not r.get("is_error"):
                try:
                    book.append((step["at"][:10], json.loads(r["content"])["total_value"]))
                except (ValueError, KeyError, TypeError):
                    pass
    if book:
        print("\n== The pod's book, as the PM last saw it each day ==")
        print("  " + "  ".join(f"{d[5:]} ${v:,.0f}" for d, v in book))
        first, last = book[0][1], book[-1][1]
        print(f"  from ${first:,.0f} to ${last:,.0f} ({(last / first - 1) * 100:+.2f}%), before thinking costs")
    print("\n== Cost, charged by the system ==")
    for k in keys:
        print(f"  {names.get(k['spec_id'], k['spec_id'])}: ${k['spent_usd_micros'] / 1e6:.4f} "
              f"of a ${k['limit_usd_micros'] / 1e6:.2f} key")


if __name__ == "__main__":
    sys.exit(main())
