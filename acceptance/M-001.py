"""Acceptance check for M-001 — a metered pod month (Era I EC4, vision M4).

A two-mind pod (an Analyst that under-reports its own cost, a silent PM) lives a 31-step month on
the fake *metered* provider under an injected numeric cap, against a local App. The check asks
whether every (fake) dollar a mind spent is charged by the system to that mind, and whether the
mind's own report no longer counts:

  Part B  the real law (cap null) refuses the same specs before physics is told anything.
  Part C  an injected cap smaller than the minds' budgets is refused before physics is told.
  Part A  under an injected cap that fits, the month completes; the provisioner's charges, the
          ledger's ``cost_metered`` rows and the App's per-agent metering read agree to the micro-
          dollar; the meter, not the self-report, decides the pod's cost.

Self-contained: it starts its own App on a temporary database, imports ``runtime`` (the Runtime is
what is being checked) but never ``app``, and leaves nothing behind. Offline (localhost only), no
LLM, no real money. The numeric cap exists only in this process, by rebinding the Runtime's law
file to a temporary one (ADR-044); the Human's real cap stays null and HALT stays the real HALT.

    uv run python acceptance/M-001.py        # exit 0 = the capability works
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SPECS = REPO / "specs" / "metered-month"
WORLD_KEY = hashlib.sha256(b"fund-acceptance-M-001/1").hexdigest()
STEPS = 31
BUDGET_MICROS = 20_000_000

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)
    return ok


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", "run", "fund-env", *args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)


def get(base: str, path: str, key: str) -> tuple[int, object]:
    req = urllib.request.Request(base + path, headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def events(db: Path) -> list[tuple[int, str, int | None, dict]]:
    """Every event of the ledger, read from the file as a reader would (read-only)."""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        rows = con.execute("SELECT id, type, actor_agent_id, payload_json FROM events "
                           "ORDER BY id").fetchall()
    return [(i, t, a, json.loads(p) if p else {}) for i, t, a, p in rows]


def run_cli_inprocess(argv: list[str]) -> tuple[int, dict | None, str]:
    """``fund-runtime`` in this process (so the injected law applies): (exit, outcome, stderr)."""
    from runtime import cli as runtime_cli

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = runtime_cli.main(argv)
    try:
        outcome = json.loads(out.getvalue())
    except ValueError:
        outcome = None
    return code, outcome, err.getvalue()


def main() -> int:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fund-m001-") as tmp:
        tmpdir = Path(tmp)
        db = tmpdir / "m001.db"
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {k: v for k, v in os.environ.items() if not k.startswith("FUND_")}
        env["FUND_DATABASE_URL"] = f"sqlite:///{db}"
        env["FUND_MARKETDATA__PROVIDER"] = "synthetic"
        env["FUND_MARKETDATA__SYNTHETIC_KEY"] = WORLD_KEY   # names a throwaway synthetic market
        keys: dict[str, str] = {}
        for args in (["init-db"], ["start-backtest", "--start", "2024-01-02T14:30:00Z"],
                     ["seed-admin", "--name", "m001-mgmt"], ["seed-runtime"],
                     ["create-pod", "--name", "desk-1", "--allocation", "1000000"]):
            r = cli(env, *args)
            m = re.search(r"\bfk_\S+", r.stdout)
            if m:
                keys[args[0]] = m.group(0)
            if not check(f"setup: fund-env {args[0]}", r.returncode == 0,
                         "" if r.returncode == 0 else (r.stdout + r.stderr).strip()[-300:]):
                return 1
        server = subprocess.Popen(["uv", "run", "fund-env", "serve", "--port", str(port)],
                                  cwd=REPO, env=env, stdout=open(tmpdir / "serve.log", "w"),
                                  stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"{base}/health", timeout=2):
                        break
                except OSError:
                    time.sleep(0.3)
            else:
                check("setup: App answers /health", False)
                return 1
            run_env = {**env, "FUND_RUNTIME__SERVER_URL": base,
                       "FUND_RUNTIME__REGISTRAR_KEY": keys["seed-admin"],
                       "FUND_RUNTIME__CLOCK_KEY": keys["seed-runtime"]}
            try:
                part_b(db, base, keys, run_env, tmpdir)
                part_c(db, base, keys, run_env, tmpdir)
                part_a(db, base, keys, run_env, tmpdir)
            except Exception as exc:  # noqa: BLE001 - a crash is a failed check, with its cause
                check("the check itself ran to the end", False, f"{type(exc).__name__}: {exc}")
        finally:
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    print(f"elapsed {time.monotonic() - started:.1f}s")
    if FAILED:
        print(f"REJECTED: {len(FAILED)} failed: {FAILED}")
        return 1
    print("ACCEPTED")
    return 0


def snapshot(db: Path, base: str, keys: dict[str, str]) -> tuple[int, object]:
    return len(events(db)), get(base, "/agents", keys["seed-admin"])[1]


def part_b(db: Path, base: str, keys: dict[str, str], run_env: dict[str, str], tmpdir: Path) -> None:
    """The real law refuses before physics is told. (Passes today: the control.)"""
    from runtime import governance

    law = governance.read_governance()
    if law.halted:
        check("the Human's HALT is not set", False, "HALT is set: the check stops")
        raise SystemExit(1)
    before = snapshot(db, base, keys)
    cmd = ["backtest", "--specs", str(SPECS), "--steps", str(STEPS), "--input", str(SPECS / "input.json")]
    if law.monthly_llm_usd_cap is None:
        r = subprocess.run(["uv", "run", "fund-runtime", *cmd], cwd=REPO, env=run_env,
                           capture_output=True, text=True, timeout=300)
        code, outcome, why = r.returncode, json.loads(r.stdout or "null"), "the real law, cap null"
    else:  # the Human answered Q-0001: keep this check true by pointing the process at a null law
        null_law = tmpdir / "null-law" / "human.yaml"
        null_law.parent.mkdir()
        null_law.write_text("firm:\n  monthly_llm_usd_cap: null\n")
        saved, governance.HUMAN_YAML = governance.HUMAN_YAML, null_law
        os.environ.update(run_env)
        try:
            code, outcome, _ = run_cli_inprocess(cmd)
        finally:
            governance.HUMAN_YAML = saved
        why = f"a null law (the real cap is {law.monthly_llm_usd_cap})"
    after = snapshot(db, base, keys)
    reason = (outcome or {}).get("reason")
    check(f"{why}: refused provision:wake_refused:a-analyst:cap_null — ledger unchanged "
          f"({before[0]} events)",
          code == 1 and (outcome or {}).get("ended") == "refused"
          and reason == "provision:wake_refused:a-analyst:cap_null"
          and outcome.get("registered") == [] and "metering" not in outcome
          and before == after
          and not any(t == "run_minds_declared" for _, t, _, _ in events(db)),
          f"exit {code}, ended {(outcome or {}).get('ended')}, reason {reason}")


def inject_cap(tmpdir: Path, cap: int) -> None:
    from runtime import governance

    path = tmpdir / f"law-{cap}" / "human.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"firm:\n  monthly_llm_usd_cap: {cap}\n")
    governance.HUMAN_YAML = path  # HALT_FILE stays the real one


def part_c(db: Path, base: str, keys: dict[str, str], run_env: dict[str, str], tmpdir: Path) -> None:
    """Budgets over the cap are refused before physics is told."""
    os.environ.update(run_env)
    inject_cap(tmpdir, 30)
    before = snapshot(db, base, keys)
    code, outcome, _ = run_cli_inprocess(
        ["backtest", "--specs", str(SPECS), "--steps", str(STEPS), "--input", str(SPECS / "input.json")])
    reason = (outcome or {}).get("reason")
    check("injected cap $30 < Σ budgets $40: refused provision:budget_over_cap — ledger unchanged",
          code == 1 and reason == "provision:budget_over_cap" and snapshot(db, base, keys) == before,
          f"exit {code}, reason {reason}")


def part_a(db: Path, base: str, keys: dict[str, str], run_env: dict[str, str], tmpdir: Path) -> None:
    """The metered month."""
    os.environ.update(run_env)
    inject_cap(tmpdir, 50)
    code, outcome, err = run_cli_inprocess(
        ["backtest", "--specs", str(SPECS), "--steps", str(STEPS), "--input", str(SPECS / "input.json")])
    if not check("metered month under an injected cap of $50: completed, exit 0",
                 code == 0 and outcome is not None and outcome.get("ended") == "completed",
                 f"exit {code}, ended {(outcome or {}).get('ended')}, reason {(outcome or {}).get('reason')}"
                 f"{' ' + err.strip()[-200:] if err.strip() else ''}"):
        return
    wakes = [w for st in outcome["run"]["steps"] for w in st["wakes"]]
    evs = events(db)
    check("62 wakes, all done; the ledger declares scripted minds before any firm act",
          len(wakes) == 2 * STEPS and all(w["ended"] == "done" for w in wakes)
          and [p for _, t, _, p in evs if t == "run_minds_declared"] == [{"minds": ["scripted"]}],
          f"{len(wakes)} wakes")
    check("the PM traded: the month is not empty",
          any(t == "order_filled" for _, t, _, _ in evs))

    st, agents = get(base, "/agents", keys["seed-admin"])
    by_name = {a["name"]: a["id"] for a in agents}
    spec_agent = {"a-analyst": by_name["desk-1-analyst"], "b-pm": by_name["desk-1-pm"]}
    metering = outcome.get("metering") or {}
    mkeys = metering.get("keys") or []
    exch = {sid: sum(len(w["exchanges"]) for w in wakes if w["spec_id"] == sid) for sid in spec_agent}
    check("two keys, one per spec, each bound to its agent's id, within its limit, one charge "
          "per model turn",
          len(mkeys) == 2 and all(
              k["agent_id"] == spec_agent[k["spec_id"]] and 0 < k["spent_usd_micros"] <= k["limit_usd_micros"]
              == BUDGET_MICROS and k["charges"] == exch[k["spec_id"]] for k in mkeys),
          str([(k["spec_id"], k["agent_id"], k["spent_usd_micros"], k["charges"]) for k in mkeys]))
    prov = {k["agent_id"]: k["spent_usd_micros"] for k in mkeys}
    check("cap kept: Σ limits ≤ $50 and Σ spent ≤ Σ limits",
          sum(k["limit_usd_micros"] for k in mkeys) <= 50_000_000
          and sum(prov.values()) <= sum(k["limit_usd_micros"] for k in mkeys))

    # The whole-ledger invariant (EC4), folded from the file, not from any App read.
    ledger_max: dict[str, int] = {}
    bound: dict[str, int] = {}
    for _, t, _, p in evs:
        if t == "cost_metered":
            ledger_max[p["key_ref"]] = max(ledger_max.get(p["key_ref"], 0), p["usd_micros_total"])
            bound.setdefault(p["key_ref"], p["agent_id"])
    st, read = get(base, "/metering/agents", keys["seed-admin"])
    read = read or {}
    app_total = read.get("total_usd_micros")
    app_by_agent = {a["agent_id"]: a for a in read.get("agents", [])}
    total = sum(prov.values())
    check(f"Σ provisioner == Σ ledger per-key max == Σ App = {total} micro-dollars (exact)",
          st == 200 and total > 0 and sum(ledger_max.values()) == total == app_total
          == sum(a["metered_usd_micros"] for a in app_by_agent.values())
          and {bound[k["key_ref"]]: ledger_max[k["key_ref"]] for k in mkeys} == prov
          and all(app_by_agent.get(aid, {}).get("metered_usd_micros") == v for aid, v in prov.items()),
          f"GET /metering/agents -> {st}")

    runtime_id = next(a["id"] for a in agents if a["role"] == "runtime")
    metered_rows = [(i, a) for i, t, a, _ in evs if t == "cost_metered"]
    last_advance = max(i for i, t, _, _ in evs if t == "clock_advanced")
    check(f"one sync, after the last step: exactly 2 cost_metered rows, by the runtime, the last "
          f"two events, after advance #{last_advance}",
          len(metered_rows) == 2 and all(a == runtime_id for _, a in metered_rows)
          and [i for i, _ in metered_rows] == [evs[-2][0], evs[-1][0]]
          and metered_rows[0][0] > last_advance,
          f"events #{[i for i, _ in metered_rows]}")

    self_rep = {aid: a["self_reported_usd"] for aid, a in app_by_agent.items()}
    analyst, pm = spec_agent["a-analyst"], spec_agent["b-pm"]
    gaps_ok = all(
        a["self_report_gap_usd"] == round(a["self_reported_usd"] - a["metered_usd_micros"] / 1e6, 2)
        and a["self_report_gap_usd"] != 0 for a in app_by_agent.values())
    check("self-report no longer counts: analyst reported $0.31, PM $0.00, both gaps non-zero",
          self_rep.get(analyst) == 0.31 and self_rep.get(pm) == 0.0 and gaps_ok
          and read.get("conflicts") == 0 and read.get("malformed") == 0,
          str({a: (v["self_reported_usd"], v["self_report_gap_usd"]) for a, v in app_by_agent.items()}))

    st, board = get(base, "/metrics/leaderboard", keys["seed-admin"])
    st2, pod = get(base, "/metrics/pod/1", keys["seed-admin"])
    row = next((r for r in (board or {}).get("rows", []) if r["pod_id"] == 1), {})
    cost = (pod or {}).get("cost", {})
    meter_usd = round(total / 1e6, 2)
    check(f"leaderboard pod 1 charges the meter (${meter_usd:.2f}), not the self-report ($0.31)",
          row.get("total_usd_cost") == row.get("metered_usd_cost") == meter_usd
          and cost.get("self_reported_usd_cost") == 0.31
          and row.get("cost_adjusted_pnl") == round(row["pnl"] - row["total_usd_cost"], 2),
          f"row {row}")
    for k in mkeys:
        print(f"  {k['spec_id']:10} agent {k['agent_id']} key {k['key_ref']} limit "
              f"${k['limit_usd_micros'] / 1e6:.2f} charges {k['charges']} "
              f"meter ${k['spent_usd_micros'] / 1e6:.6f}")


if __name__ == "__main__":
    sys.exit(main())
