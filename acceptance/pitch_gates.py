"""Acceptance demo — a real PM researches a strategy, pitches it, and the app's validation gates give
a verdict the Human can read.

Costs $0 and needs no network.

  A  the gates' controls, on markets made here (stdlib ``random``, fixed seeds), through the same
     pure engine physics uses (``fund-env gates``). A check that always says no would pass a
     no-only demo, so every gate must say yes once and no once:
       A1 pure noise: no seed is eligible
       A2 a planted signal (each name's drift wanders slowly, so 20-day momentum predicts the next
          5 days): eligible at 1 attempt on at least 4 of 5 seeds
       A3 the same planted strategy counted as 200 attempts: the deflated Sharpe is lower on every
          seed and fails on at least 4 of 5
       A4 capacity: the planted strategy passes in a deep market and fails in a thin one
       A5 correlation: a copy of another pod's strategy fails, an unrelated strategy passes, no
          other pod at all is null (null, not 0)
  B  the recorded real PM session (``evidence/pitch-gates/session.cassette.json``): a real model
     on its metered key ran research backtests and pitched; ``fund-runtime replay --verify`` from
     the file alone says IDENTICAL at $0; the ledger holds every research backtest (counted), the
     pitch and the gates' verdict on the held-out window, which no research window entered.
  then a plain report: the pitch, its research, and the gate table.

Self-contained: stdlib + subprocess; imports neither ``app`` nor ``runtime``.

    uv run python acceptance/pitch_gates.py        # exit 0 = the idea works
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evidence" / "pitch-gates" / "session.cassette.json"
#: The recorded session's world seed (ADR-045: not in the cassette; whoever verifies must know it).
KEY = hashlib.sha256(b"fund-pitch-gates/1").hexdigest()
SECRET = re.compile(r"sk-or-[A-Za-z0-9-]{8,}")

SEEDS = range(5)
TICKERS = [f"P{k:02d}" for k in range(20)]
ORIGIN = date(2021, 1, 1)
DAYS = 1100
WINDOW = ("2023-01-05", "2024-01-05")      # the judged (held-out) year
PLANTED = 0.0016                           # stationary sd of each name's daily drift
MOMENTUM = {"language": "strategy-v1", "universe": TICKERS, "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "top_n": 5, "side": "long_short", "gross": 1.0}
LOW_VOL = {**MOMENTUM, "signal": "low_volatility", "lookback": 60, "rebalance_every": 21}

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


def market(seed: int, drift_sd: float, dollar_volume: float = 5e7) -> dict:
    """Twenty names, daily bars, log-returns = drift + 1.5 % noise. The drift of each name is an
    AR(1) with persistence 0.99 and stationary sd ``drift_sd`` (0 = a pure random walk)."""
    rng = random.Random(seed)
    out = {}
    innovation = drift_sd * math.sqrt(1 - 0.99**2)
    for k, ticker in enumerate(TICKERS):
        price, mu, rows = 50.0 + k, 0.0, []
        for d in range(DAYS):
            mu = 0.99 * mu + innovation * rng.gauss(0, 1)
            opened, price = price, price * math.exp(mu + 0.015 * rng.gauss(0, 1))
            rows.append([(ORIGIN + timedelta(d)).isoformat(), opened, max(opened, price) * 1.002,
                         min(opened, price) * 0.998, price, dollar_volume / price])
        out[ticker] = rows
    return out


class Gates:
    """``fund-env gates`` over files in one temporary directory."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("FUND_")}
        self.env["FUND_DATABASE_URL"] = f"sqlite:///{tmp / 'unused.db'}"

    def file(self, name: str, doc: object) -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(doc))
        return path

    def __call__(self, bars: Path, rule: Path, attempts: int = 1, others: dict | None = None) -> dict:
        cmd = ["uv", "run", "--project", str(REPO), "fund-env", "gates", str(bars), str(rule),
               "--start", WINDOW[0], "--end", WINDOW[1], "--attempts", str(attempts)]
        for name, path in (others or {}).items():
            cmd += ["--other", f"{name}={path}"]
        r = subprocess.run(cmd, cwd=self.tmp, env=self.env, capture_output=True, text=True,
                           timeout=300)
        if r.returncode:
            raise RuntimeError(f"fund-env gates exit {r.returncode}: {r.stderr.strip()[-400:]}")
        return json.loads(r.stdout)


def gate(verdict: dict, name: str) -> dict:
    return next(g for g in verdict["gates"] if g["gate"] == name)


def fmt(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:.4g}"
    return str(value)


def controls() -> None:
    with tempfile.TemporaryDirectory(prefix="fund-pitch-gates-") as t:
        run = Gates(Path(t))
        momentum = run.file("momentum.json", MOMENTUM)
        low_vol = run.file("low_vol.json", LOW_VOL)
        noise, planted, planted200 = [], [], []
        for seed in SEEDS:
            noise.append(run(run.file(f"noise{seed}.json", market(seed, 0.0)), momentum))
            bars = run.file(f"planted{seed}.json", market(seed, PLANTED))
            planted.append(run(bars, momentum))
            planted200.append(run(bars, momentum, attempts=200))

        def row(vs: list[dict], g: str) -> str:
            return " ".join(f"{gate(v, g)['result']}({fmt(gate(v, g)['value'])})" for v in vs)

        check("A1: pure noise is never eligible", not any(v["eligible"] for v in noise),
              f"IC {row(noise, 'ic')}; deflated Sharpe {row(noise, 'deflated_sharpe')}")
        check("A2: the planted signal is eligible at 1 attempt on ≥ 4 of 5 seeds",
              sum(v["eligible"] for v in planted) >= 4,
              f"eligible {[v['eligible'] for v in planted]}; IC {row(planted, 'ic')}")
        lower = all(gate(b, "deflated_sharpe")["value"] < gate(a, "deflated_sharpe")["value"]
                    for a, b in zip(planted, planted200))
        failing = sum(gate(b, "deflated_sharpe")["result"] == "fail" for b in planted200)
        check("A3: 200 attempts deflate the same strategy's Sharpe below the bar (≥ 4 of 5)",
              lower and failing >= 4,
              f"1 attempt {row(planted, 'deflated_sharpe')} → 200 attempts "
              f"{row(planted200, 'deflated_sharpe')}")

        seed = next((s for s in SEEDS if planted[s]["eligible"]), 0)
        deep = gate(planted[seed], "capacity")
        thin = gate(run(run.file("thin.json", market(seed, PLANTED, dollar_volume=2e4)), momentum),
                    "capacity")
        check("A4: capacity passes in a deep market and fails in a thin one",
              deep["result"] == "pass" and thin["result"] == "fail",
              f"$50M/day: {deep['result']} ${fmt(deep['value'])}; $20k/day: {thin['result']} "
              f"${fmt(thin['value'])} (bar ${fmt(deep['threshold'])})")

        bars = run.file(f"planted{seed}.json", market(seed, PLANTED))
        copy = gate(run(bars, momentum, others={"pod-2": momentum}), "correlation")
        apart = gate(run(bars, momentum, others={"pod-2": low_vol}), "correlation")
        alone = gate(planted[seed], "correlation")
        check("A5: correlation fails a copy, passes an unrelated strategy, is null alone",
              copy["result"] == "fail" and apart["result"] == "pass" and alone["result"] == "null"
              and alone["value"] is None,
              f"copy {fmt(copy['value'])}, low-vol {fmt(apart['value'])}, alone {fmt(alone['value'])}")


def session(started: float) -> None:
    if not check("B: the recorded real PM session exists", EVIDENCE.is_file(),
                 str(EVIDENCE.relative_to(REPO))):
        return
    text = EVIDENCE.read_text(encoding="ascii")
    doc = json.loads(text)
    check("B: no provider key and no world key in it", SECRET.search(text) is None and KEY not in text)
    specs = [e["spec"] for e in doc.get("specs") or []]
    check("B: the mind is a real model on the metered provider",
          any(s["role"] == "pm" and s["provider"] == "openrouter" and s.get("model") for s in specs),
          ", ".join(f"{s['id']}={s['provider']}/{s.get('model')}" for s in specs))
    rows = [(r[3], json.loads(r[4])) for r in (doc.get("ledger") or {}).get("rows") or []]
    research = [p for t, p in rows if t == "research_backtest_run"]
    pitches = [p for t, p in rows if t == "pitch_submitted"]
    judged = [p for t, p in rows if t == "pitch_judged"]
    check("B: the PM ran research backtests, each one counted",
          len(research) > 0 and [p["attempt"] for p in research] == list(range(1, len(research) + 1)),
          f"{len(research)} research backtests")
    check("B: the PM pitched and the gates judged it", len(pitches) >= 1 and len(judged) == len(pitches))
    if judged:
        verdict = judged[-1]
        holdout_start = verdict["window"]["start"]
        check("B: no research window entered the held-out window",
              all(p["window"]["end"] <= holdout_start for p in research),
              f"held out from {holdout_start}")
        check("B: the deflated Sharpe counted every attempt",
              gate(verdict, "deflated_sharpe")["attempts"] == len(research) + len(pitches))
        check("B: the gate table has every gate with a number or null",
              {g["gate"] for g in verdict["gates"]} >= {"ic", "deflated_sharpe", "capacity",
                                                        "correlation", "hypothesis"})

    with tempfile.TemporaryDirectory(prefix="fund-pitch-gates-") as t:
        tmp = Path(t)
        (tmp / "vtmp").mkdir()
        lone = tmp / "session.cassette.json"
        lone.write_text(text, encoding="ascii")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("FUND_", "OPENROUTER")) and k.lower() not in {
                   "http_proxy", "https_proxy", "all_proxy"}}
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
        check("B: replay --verify from the file alone is IDENTICAL, at $0",
              r.returncode == 0 and line.startswith("IDENTICAL:") and ev.get("replay_usd") == 0,
              f"exit {r.returncode}: {line or r.stderr.strip()[-300:]}")
    report(doc, pitches, judged, research)


def report(doc: dict, pitches: list[dict], judged: list[dict], research: list[dict]) -> None:
    """What the Human wants to read: the pitch, the work behind it, the verdict, the PM's words."""
    for pitch, verdict in zip(pitches, judged):
        print(f"\n== Pitch {verdict.get('pitch_id')} by pod {pitch.get('pod_id')} ==")
        print(f"  Hypothesis: {pitch.get('hypothesis')}")
        print(f"  Data needed: {pitch.get('data_needed')}")
        print(f"  Team and budget asked: {pitch.get('team')} · ${pitch.get('budget_usd')}")
        print(f"  The rule: {json.dumps(pitch.get('rule'), sort_keys=True)}")
        print(f"\n  Research behind it ({len(research)} backtests, all counted):")
        for p in research:
            perf = p.get("performance") or {}
            print(f"    #{p['attempt']:<3} {p['rule']['signal']:<15} lookback {p['rule']['lookback']:<4}"
                  f" every {p['rule']['rebalance_every']:<3} {p['window']['start']}→{p['window']['end']}"
                  f"  Sharpe {fmt(perf.get('sharpe'))}  IC {fmt(perf.get('mean_ic'))}")
        print(f"\n  The gates, on the held-out window {verdict['window']['start']} → "
              f"{verdict['window']['end']}:")
        for g in verdict["gates"]:
            print(f"    {g['gate']:<16} {g['result'].upper():<12} {fmt(g.get('value')):>14}"
                  f"   bar {fmt(g.get('threshold'))}")
        print(f"  Verdict: {'ELIGIBLE for capital' if verdict['eligible'] else 'NOT eligible'}")
    print("\n== The PM, in its own words, at the end of each day ==")
    for step in (doc.get("outcome") or {}).get("run", {}).get("steps") or []:
        for w in step.get("wakes") or []:
            said = next((m["content"] for m in reversed(w.get("transcript") or [])
                         if m["role"] == "assistant" and m.get("content")), "")
            print(f"  day {step['step'] + 1} ({step['at'][:10]}):")
            for line in said.strip().splitlines():
                print(f"    {line}")
    keys = ((doc.get("outcome") or {}).get("metering") or {}).get("keys") or []
    print("\n== Cost, charged by the system ==")
    for k in keys:
        print(f"  {k['spec_id']}: ${k['spent_usd_micros'] / 1e6:.4f} of a "
              f"${k['limit_usd_micros'] / 1e6:.2f} key")


def main() -> int:
    started = time.monotonic()
    if (REPO / "governance" / "HALT").exists():
        print("governance/HALT exists: not running")
        return 1
    controls()
    session(started)
    return finish(started)


if __name__ == "__main__":
    sys.exit(main())
