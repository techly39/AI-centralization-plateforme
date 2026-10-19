"""Acceptance demo — a dead pod is replaced: when the risk ladder closes a pod, a vacancy opens and the
firm hires a new PM who researches, pitches and can earn a seed.

Costs $0 and needs no network.

  A  scripted, in this process, on a made-up market (stdlib ``random``, one fixed seed), through the
     app's HTTP API. The hiring law allows 4 live pods; the firm opens with 5:
       edge    P  a planted edge that goes on                       (keeps the machine honest)
       sink-1  B  the sector collapses fast    → closed → vacancy 1
       sink-2  C  collapses slower             → closed → vacancy 2
       sink-3  D  quiet, then gaps down 14 %   → closed at once → vacancy 3
       dipper  S  falls about 6 % and holds    → halved, never closed: no vacancy
     Every morning the onboarding (here a stand-in for the Runtime's) tries to fill each open
     vacancy. With 4 live pods the hire is refused (the law's limit, in the ledger); when a second
     pod dies there is room and the oldest vacancy is filled: a new pod and a new PM, named, modelled
     and budgeted by the law. The new PM reads its post-mortem (no one else's), then pitches:
       hire-1 pitches the planted rule on fresh names (F)  → eligible → seeded → trades forward
       hire-2 pitches the same rule on pure noise (N)      → not eligible → no seed
     A vacancy is filled once; rebuilding from the ledger gives the same cash, positions, pods.
  B  the Runtime hires mid-run, in a hosted world whose market (a recipe: app/marketdata/made_up.py)
     crashes the one pod's sector 8 days after the pitch: the ladder closes it, a vacancy opens,
     the next morning ``fund-runtime backtest --hire`` fills it and the new PM wakes with the
     post-mortem; its pitch is judged and a seed follows the verdict.
       B0 a scripted rehearsal, recorded now: ``replay --verify`` IDENTICAL, $0
       B  the recorded real hire (``evidence/pod-replacement/hire.cassette.json``): a real model on
          its own metered key, inside the cap; ``replay --verify`` IDENTICAL from the file, $0

    uv run python acceptance/pod_replacement.py        # exit 0 = the idea works
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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory(prefix="fund-pod-replacement-")
for k in [k for k in os.environ if k.startswith("FUND_")]:
    del os.environ[k]
os.environ["FUND_DATABASE_URL"] = f"sqlite:///{Path(TMP.name) / 'fund.db'}"
os.environ["FUND_MARKETDATA__PROVIDER"] = "static"
os.environ["FUND_LOGGING__LEVEL"] = "ERROR"
os.environ["FUND_HIRING__MAX_LIVE_PODS"] = "4"
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402
from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.capital.service import book  # noqa: E402
from app.cli import main as fund_env  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.base import session_scope  # noqa: E402
from app.db.models import Agent, AgentRole, CashBalance, Event, Pod, Position  # noqa: E402
from app.ledger.rebuild import rebuild_state  # noqa: E402
from app.main import create_app  # noqa: E402
from app.marketdata import BarsProvider, get_provider, set_provider  # noqa: E402
from app.marketdata.made_up import Family, MadeUpMarket, bars  # noqa: E402
from app.registry.pods import create_pod  # noqa: E402
from app.registry.service import register_agent, seed_runtime_agent  # noqa: E402
from app.run_clock import start_backtest  # noqa: E402

SEED = 11
ORIGIN = date(2023, 1, 1)
PITCH_DAY = date(2024, 9, 1)
FORWARD = 75
NOISE, PLANTED = 0.010, 0.004
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0}
#: family: (width, what happens from the pitch day on)
FAMILIES = {"P": (20, "edge"), "B": (10, "sink:0.008"), "C": (10, "sink:0.004"),
            "D": (10, "crash:40"), "S": (10, "dip"), "F": (20, "edge"), "N": (20, "noise")}
FIRST = {"edge": ("P", 5), "sink-1": ("B", 2), "sink-2": ("C", 2), "sink-3": ("D", 2),
         "dipper": ("S", 2)}
HIRES = {1: ("F", 5), 2: ("N", 5)}    # vacancy number → the family its new PM pitches on
LIMIT = 4

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)
    return ok


# --- the made-up market -------------------------------------------------------------------------

#: The market, as a recipe (app/marketdata/made_up.py): the same one a hosted world can be built from.
MARKET = MadeUpMarket(seed=SEED, origin=ORIGIN, pivot=PITCH_DAY,
                      days=(PITCH_DAY - ORIGIN).days + FORWARD + 5, noise=NOISE, planted=PLANTED,
                      families=[Family(prefix=p, width=w, fate=fate.split(":")[0],
                                       rate=float(fate.split(":")[1]) if ":" in fate else 0.0)
                                for p, (w, fate) in FAMILIES.items()])


def rule(family: str, top_n: int) -> dict:
    return {**MOMENTUM, "universe": [f"{family}{k:02d}" for k in range(FAMILIES[family][0])],
            "top_n": top_n}


# --- the run ------------------------------------------------------------------------------------

def h(key: str) -> dict:
    return {"X-API-Key": key}


def events(s, type_: str) -> list[dict]:
    return [dict(e.payload_json, _id=e.id, _ts=e.ts, _actor=e.actor_agent_id) for e in
            s.scalars(select(Event).where(Event.type == type_).order_by(Event.id))]


class Firm:
    def __init__(self) -> None:
        assert fund_env(["init-db"]) == 0
        set_provider(BarsProvider(bars(MARKET)))
        self.provider = get_provider()
        with session_scope() as s:
            start_backtest(s, start=datetime.combine(PITCH_DAY, datetime.min.time(), UTC))
            _, self.admin = register_agent(s, name="management", role=AgentRole.management)
            _, self.runtime = seed_runtime_agent(s)
            ids = {name: create_pod(s, name=name).id for name in FIRST}
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.pods: dict[str, dict] = {}
        for name, pod_id in ids.items():
            r = self.client.post("/agents/register", headers=h(self.admin),
                                 json={"name": f"pm-{name}", "role": "pm", "pod_id": pod_id})
            assert r.status_code == 201, r.text
            self.pods[name] = {"id": pod_id, "key": r.json()["api_key"]}
        self.log: list[tuple] = []          # (day, what, detail)
        self.live_after_fill: list[int] = []
        self.hired: dict[int, dict] = {}    # vacancy number → what the new PM saw and did

    def pitch(self, name: str, family: str, top_n: int, hypothesis: str) -> dict:
        r = self.client.post("/pitches", headers=h(self.pods[name]["key"]), json={
            "hypothesis": hypothesis, "data_needed": "daily prices", "team": "the PM alone",
            "budget_usd": 0.0, "rule": rule(family, top_n)})
        assert r.status_code == 201, r.text
        return r.json()["verdict"]

    def morning(self, day: int) -> None:
        """The onboarding stand-in: every open vacancy, oldest first, is offered for a fill."""
        r = self.client.get("/vacancies", headers=h(self.admin))
        assert r.status_code == 200, r.text
        for v in r.json():
            if v["status"] != "open":
                continue
            r = self.client.post(f"/vacancies/{v['id']}/fill", headers=h(self.admin))
            if r.status_code != 201:
                self.log.append((day, f"vacancy {v['vacancy_no']} refused", r.json()["detail"]))
                continue
            done = r.json()
            agent, filled = done["agent"], done["vacancy"]
            with session_scope() as s:
                self.live_after_fill.append(
                    sum(1 for p in s.scalars(select(Pod)) if p.status != "closed"))
            self.log.append((day, f"vacancy {v['vacancy_no']} filled",
                             f"{filled['filled']['pod_name']} / {agent['name']}"))
            name = filled["filled"]["pod_name"]
            self.pods[name] = {"id": agent["pod_id"], "key": agent["api_key"]}
            self.first_wake(day, v["vacancy_no"], v["id"], name, done)

    def first_wake(self, day: int, number: int, vacancy_id: int, name: str, done: dict) -> None:
        """The new PM's first morning (a scripted mind): it reads its post-mortem, then pitches."""
        key = self.pods[name]["key"]
        read = self.client.get(f"/vacancies/{vacancy_id}", headers=h(key))
        family, top_n = HIRES.get(number, ("N", 5))
        verdict = self.pitch(name, family, top_n,
                             "Slow diffusion of information: recent winners keep winning; the "
                             "pod before me bet on a sector that collapsed.")
        self.hired[number] = {"day": day, "pod": name, "vacancy_id": vacancy_id,
                              "read_status": read.status_code, "read": read.json(),
                              "answer": done, "verdict": verdict, "family": family}

    def live(self) -> list[dict]:
        history = []
        for day in range(FORWARD):
            self.morning(day)
            for name, p in self.pods.items():
                # Each PM reads its own mandate (404 until its pod is seeded) and sends the orders.
                r = self.client.get("/mandate", headers=h(p["key"]))
                if r.status_code != 200:
                    continue
                for order in r.json()["orders"]:
                    self.client.post("/orders", headers=h(self.pods[name]["key"]), json={
                        "ticker": order["ticker"], "side": order["side"], "qty": order["qty"],
                        "price_type": "market", "justification": "my rule's rebalance"})
            r = self.client.post("/clock/advance", headers=h(self.runtime), json={"days": 1})
            assert r.status_code == 200, r.text
            with session_scope() as s:
                state = book(s)
                history.append({"day": day + 1, "stages": {
                    n: state["pods"].get(p["id"], {}).get("stage", "-")
                    for n, p in self.pods.items()}})
        return history


# --- the checks ---------------------------------------------------------------------------------

def checks(firm: Firm) -> None:
    ids = {n: p["id"] for n, p in firm.pods.items()}
    with session_scope() as s:
        opened = events(s, "vacancy_opened")
        filled = events(s, "vacancy_filled")
        refused = events(s, "hire_refused")
        stages = events(s, "pod_stage_changed")
        seeded = {e["pod_id"]: e for e in events(s, "capital_seeded")}
        fills = events(s, "order_filled")
        registered = {e["agent_id"]: e for e in events(s, "agent_registered")}
        agents = {a.id: a for a in s.scalars(select(Agent))}
        pods = {p.id: p for p in s.scalars(select(Pod))}
    law = get_settings().hiring
    closed = [e for e in stages if e["to"] == "closed"]

    # A1: a vacancy per closed pod, and only for a closed pod
    check("A1: three sinking pods are closed by the ladder, the dipper only halved",
          sorted(e["pod_id"] for e in closed) == sorted(ids[n] for n in ("sink-1", "sink-2", "sink-3"))
          and [e["to"] for e in stages if e["pod_id"] == ids["dipper"]] == ["halved"],
          f"closed {[pods[e['pod_id']].name for e in closed]}; dipper "
          f"{[e['to'] for e in stages if e['pod_id'] == ids['dipper']]}")
    same_tx = all(any(o["pod_id"] == c["pod_id"] and o["_ts"] == c["_ts"] and o["_id"] > c["_id"]
                      for o in opened) for c in closed)
    check("A1: each close opens one vacancy, at the close, and the halved pod opens none",
          [o["pod_id"] for o in opened] == [c["pod_id"] for c in closed] and same_tx
          and not any(o["pod_id"] == ids["dipper"] for o in opened),
          f"{len(opened)} vacancies for {len(closed)} closes")

    # A2: the post-mortem is the dead pod's own record
    pm1 = opened[0]["post_mortem"] if opened else {}
    ladder1 = [step["to"] for step in pm1.get("ladder", [])]
    seed1 = seeded.get(ids["sink-1"], {})
    check("A2: the post-mortem holds the dead pod's rule, its ladder and its money",
          pm1.get("pitch", {}).get("rule") == seed1.get("rule") and ladder1[-1:] == ["closed"]
          and (pm1.get("worst_drawdown") or 0) >= 0.10 and pm1["capital"]["put_in_usd"] > 0
          and pm1["capital"]["taken_back_usd"] > 0 and pm1["forward_days"] > 0,
          f"ladder {ladder1}, worst drawdown {pm1.get('worst_drawdown', 0):.1%}, "
          f"{pm1.get('forward_days')} forward days, return {pm1.get('forward_return', 0):.1%}"
          if pm1 else "no vacancy")

    # A3: the law's limit
    limit_refusals = [r for r in refused if "limit" in r["reason"]]
    check("A3: at 4 live pods the hire is refused (in the ledger), and waits for room",
          len(limit_refusals) > 0 and all(n <= LIMIT for n in firm.live_after_fill)
          and len(filled) == 2,
          f"{len(limit_refusals)} refusals ('{limit_refusals[0]['reason']}'); live pods after "
          f"each fill {firm.live_after_fill}" if limit_refusals else "no refusal")
    third = opened[2]["_id"] if len(opened) > 2 else None
    check("A3: the third vacancy is still open at the end: the firm is full",
          third is not None and not any(f["vacancy_id"] == third for f in filled))

    # A4: the hire is the law's
    ok = len(filled) == 2
    for f in filled:
        v = next(o for o in opened if o["_id"] == f["vacancy_id"])
        agent = agents.get(f["agent_id"])
        pod = pods.get(f["pod_id"])
        ok = ok and agent is not None and pod is not None and (
            agent.name, agent.role.value, agent.pod_id, agent.charter_ref) == (
            v["hire"]["pm_name"], "pm", pod.id, f"vacancy:{f['vacancy_id']}") and (
            pod.name == v["hire"]["pod_name"]) and f["agent_id"] in registered and (
            v["hire"]["model"] == law.models[(v["vacancy_no"] - 1) % len(law.models)]) and (
            v["hire"]["budget_usd"] == law.budget_usd)
    check("A4: each fill made the pod and the PM the law names, in the ledger",
          ok, "; ".join(f"vacancy {f['vacancy_id']} → {f['pod_name']} / {f['agent_name']} "
                        f"({f['model']}, ${f['budget_usd']:.2f})" for f in filled))
    vacancy_ids = {f["vacancy_id"] for f in filled}
    vid = next(iter(vacancy_ids), 1)
    again = firm.client.post(f"/vacancies/{vid}/fill", headers=h(firm.admin))
    pm_try = firm.client.post(f"/vacancies/{third or vid}/fill", headers=h(firm.pods["edge"]["key"]))
    check("A4: a vacancy is filled once; a PM cannot hire",
          again.status_code == 409 and pm_try.status_code == 403,
          f"again {again.status_code}, a PM {pm_try.status_code}")

    # A5: the new PM's first morning: its own post-mortem, no one else's
    h1, h2 = firm.hired.get(1), firm.hired.get(2)
    check("A5: the new PM reads the post-mortem of the pod it replaces",
          h1 is not None and h1["read_status"] == 200
          and h1["read"]["post_mortem"]["pod_id"] == ids["sink-1"],
          f"{h1['pod']} read vacancy {h1['vacancy_id']}: pod {h1['read']['post_mortem']['pod_name']}"
          if h1 else "no hire")
    other = (firm.client.get(f"/vacancies/{h2['vacancy_id']}", headers=h(firm.pods["hire-1"]["key"]))
             if h1 and h2 else None)
    check("A5: ... and not another vacancy's (403)", other is not None and other.status_code == 403,
          f"{other.status_code if other is not None else None}")

    # A6: an eligible hire earns a seed and trades; noise earns nothing
    p1 = ids.get("hire-1")
    p2 = ids.get("hire-2")
    check("A6: hire-1's pitch on the planted names is eligible, seeded, and trades forward",
          h1 is not None and h1["verdict"]["eligible"] and p1 in seeded
          and any(f["pod_id"] == p1 for f in fills),
          f"eligible {h1['verdict']['eligible']}, seed ${seeded[p1]['seed_usd']:,.0f}, "
          f"{sum(1 for f in fills if f['pod_id'] == p1)} fills" if h1 and p1 in seeded else
          f"verdict {h1['verdict']['eligible'] if h1 else None}")
    check("A6: hire-2's pitch on noise is not eligible and gets no seed",
          h2 is not None and not h2["verdict"]["eligible"] and p2 not in seeded,
          f"eligible {h2['verdict']['eligible']}" if h2 else "no second hire")

    # A7: the ledger is the truth
    with session_scope() as s:
        before = _snapshot(s)
        rebuild_state(s)
        s.flush()
        after_ = _snapshot(s)
        s.rollback()
    check("A7: rebuilding from the ledger gives the same cash, positions, pods", before == after_)


def _snapshot(s) -> dict:
    return {"cash": sorted((c.pod_id, round(c.balance, 6)) for c in s.scalars(select(CashBalance))),
            "positions": sorted((p.pod_id, p.ticker, round(p.qty, 9), round(p.avg_cost, 9))
                                for p in s.scalars(select(Position))),
            "pods": sorted((p.id, p.name, p.status, round(p.current_allocation, 6))
                           for p in s.scalars(select(Pod)))}


# --- B: the Runtime hires mid-run, in a hosted world -------------------------------------------

EVIDENCE = REPO / "evidence" / "pod-replacement" / "hire.cassette.json"
#: The hosted world's key (ADR-045: never in the cassette; whoever verifies must know it).
KEY = hashlib.sha256(b"fund-pod-replacement/1").hexdigest()
SECRET = re.compile(r"sk-or-[A-Za-z0-9-]{8,}")
#: The world: one pod whose sector crashes 8 days after the pivot; fresh names with an edge, and
#: noise, for whoever is hired to research.
WORLD = {"start": "2024-09-01T14:30:00Z", "admin": "hire-mgmt",
         "pods": [{"name": "doomed", "allocation": 0}],
         "market": {"seed": 11, "origin": "2023-01-01", "pivot": "2024-09-01", "days": 640,
                    "noise": NOISE, "planted": PLANTED, "families": [
                        {"prefix": "B", "width": 10, "fate": "crash", "rate": 8},
                        {"prefix": "F", "width": 20, "fate": "edge"},
                        {"prefix": "N", "width": 20, "fate": "noise"}]}}
STEPS, MAX_TOOL_CALLS = 24, 24
#: What a hired PM may do: read its post-mortem, research, pitch, read its capital and mandate, trade.
HIRE_TOOLS = ["whoami", "get_clock", "get_vacancy", "run_research_backtest",
              "list_research_backtests", "submit_pitch", "list_pitches", "get_capital",
              "get_mandate", "place_order", "get_portfolio"]
TEMPLATES = {"scripted": {"provider": "scripted", "script": "pitch-pm"},
             "openrouter": {"provider": "openrouter", "tools": HIRE_TOOLS}}


def write_world(directory: Path, template: str) -> None:
    """The hosted run's files: the world, the input, the doomed pod's PM, the hiring template."""
    (directory / "specs").mkdir(parents=True, exist_ok=True)
    (directory / "world.json").write_text(json.dumps(WORLD))
    doomed_rule = {**MOMENTUM, "universe": [f"B{k:02d}" for k in range(10)], "top_n": 2}
    rules = {"doomed-pm": doomed_rule}
    if template == "scripted":   # the scripted hire pitches the planted names
        rules["hire-1-pm"] = {**MOMENTUM, "universe": [f"F{k:02d}" for k in range(20)], "top_n": 5}
    (directory / "input.json").write_text(json.dumps({
        "universe": [f"F{k:02d}" for k in range(20)] + [f"N{k:02d}" for k in range(20)],
        "pitch_rules": rules}))
    (directory / "specs" / "doomed-pm.yaml").write_text(json.dumps({
        "id": "doomed-pm", "name": "doomed-pm", "role": "pm", "pod": 1, "provider": "scripted",
        "script": "pitch-pm", "charter": "Pitch once, then trade the mandate."}))
    (directory / "hire.yaml").write_text(json.dumps(TEMPLATES[template]))


def fund_runtime(argv: list[str], cwd: Path, *, offline: bool = True) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("FUND_", "OPENROUTER")) and k.lower() not in {
               "http_proxy", "https_proxy", "all_proxy"}}
    (cwd / "vtmp").mkdir(exist_ok=True)
    env.update({"FUND_MARKETDATA__SYNTHETIC_KEY": KEY, "TMPDIR": str(cwd / "vtmp"),
                "FUND_DATABASE_URL": f"sqlite:///{cwd / 'sentinel.db'}"})
    if offline:
        env.update({"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"})
    return subprocess.run(["uv", "run", "--project", str(REPO), "fund-runtime", *argv], cwd=cwd,
                          env=env, capture_output=True, text=True, timeout=900)


def verify(text: str, label: str) -> None:
    with tempfile.TemporaryDirectory(prefix="fund-pod-replacement-") as t:
        lone = Path(t) / "run.cassette.json"
        lone.write_text(text, encoding="ascii")
        r = fund_runtime(["replay", "--cassette", lone.name, "--verify"], Path(t))
        line, _, rest = r.stdout.partition("\n")
        try:
            ev = json.loads(rest)
        except ValueError:
            ev = {}
        check(f"{label}: replay --verify from the file alone is IDENTICAL, at $0",
              r.returncode == 0 and line.startswith("IDENTICAL:") and ev.get("replay_usd") == 0,
              f"exit {r.returncode}: {line or r.stderr.strip()[-300:]}")


def chain(doc: dict, label: str) -> dict:
    """The hire, as the recorded ledger and run tell it: close → vacancy → fill → the new PM's
    first wake with its post-mortem → its pitch → the verdict → a seed if and only if eligible."""
    rows = [(r[0], r[2], r[3], json.loads(r[4])) for r in (doc.get("ledger") or {}).get("rows") or []]
    run = (doc.get("outcome") or {}).get("run") or {}
    of = lambda t: [(i, a, p) for i, a, t2, p in rows if t2 == t]  # noqa: E731
    closed = [(i, p) for i, _, p in of("pod_stage_changed") if p["to"] == "closed"]
    opened = [(i, p) for i, _, p in of("vacancy_opened")]
    filled = [(i, p) for i, _, p in of("vacancy_filled")]
    hired = [h for h in run.get("hires") or [] if h["outcome"] == "hired"]
    ok = (len(closed) == 1 and len(opened) == 1 and opened[0][1]["pod_id"] == closed[0][1]["pod_id"]
          and opened[0][0] > closed[0][0] and len(filled) == 1
          and filled[0][1]["vacancy_id"] == opened[0][0] and len(hired) == 1
          and hired[0]["agent_id"] == filled[0][1]["agent_id"])
    check(f"{label}: the crash closes the pod, a vacancy opens, the next morning it is filled",
          ok, f"closed pod {closed[0][1]['pod_id']} at {closed[0][1]['drawdown']:.1%}; hire "
              f"{filled[0][1]['agent_name']} into pod {filled[0][1]['pod_id']} at step "
              f"{hired[0]['step']}" if ok else str((closed, opened, filled, hired))[:300])
    if not ok:
        return {}
    pod, agent, step = filled[0][1]["pod_id"], filled[0][1]["agent_id"], hired[0]["step"]
    wakes = [(s["step"], w) for s in run.get("steps") or [] for w in s.get("wakes") or []
             if w["spec_id"] == hired[0]["spec_id"]]
    first = json.loads(wakes[0][1]["transcript"][1]["content"]) if wakes else {}
    check(f"{label}: the new PM wakes that morning, handed the dead pod's post-mortem",
          bool(wakes) and wakes[0][0] == step
          and (first.get("input", {}).get("post_mortem") or {}).get("pod_name") == "doomed",
          f"{len(wakes)} wakes from step {wakes[0][0] if wakes else None}")
    research = [p for _, a, p in of("research_backtest_run") if p["pod_id"] == pod]
    pitches = [(i, p) for i, a, p in of("pitch_submitted") if p["pod_id"] == pod]
    judged = [p for _, _, p in of("pitch_judged") if p["pod_id"] == pod]
    seeded = [p for _, _, p in of("capital_seeded") if p["pod_id"] == pod]
    fills = [p for _, _, p in of("order_filled") if p["pod_id"] == pod]
    eligible = bool(judged) and judged[-1]["eligible"]
    check(f"{label}: the new PM pitched, the gates judged it, and the seed follows the verdict",
          len(pitches) >= 1 and len(judged) == len(pitches)
          and bool(seeded) == any(j["eligible"] for j in judged),
          f"{len(research)} research backtests, {len(pitches)} pitch(es), "
          f"{'ELIGIBLE' if eligible else 'not eligible'}, "
          f"{'seeded $' + format(seeded[0]['seed_usd'], ',.0f') if seeded else 'no seed'}, "
          f"{len(fills)} fills")
    return {"pod": pod, "agent": agent, "research": research, "pitches": pitches,
            "judged": judged, "seeded": seeded, "fills": fills, "wakes": wakes}


def rehearsal() -> None:
    """B0, $0: the same hosted run with a scripted hire, recorded and verified now."""
    with tempfile.TemporaryDirectory(prefix="fund-pod-replacement-") as t:
        tmp = Path(t)
        write_world(tmp, "scripted")
        r = fund_runtime(["backtest", "--world", "world.json", "--specs", "specs", "--hire",
                          "hire.yaml", "--input", "input.json", "--steps", str(STEPS),
                          "--max-tool-calls", str(MAX_TOOL_CALLS), "--cassette",
                          "rehearsal.cassette.json"], tmp)
        tape = tmp / "rehearsal.cassette.json"
        if not check("B0: a scripted rehearsal of the hosted run completes and is recorded",
                     r.returncode == 0 and tape.is_file(), f"exit {r.returncode}: "
                     f"{r.stderr.strip()[-300:] if r.returncode else 'completed'}"):
            return
        text = tape.read_text(encoding="ascii")
    chain(json.loads(text), "B0")
    verify(text, "B0")


def recorded() -> dict:
    """B: the recorded real hire (a real model, metered, inside the cap)."""
    if not check("B: the recorded real hire exists", EVIDENCE.is_file(),
                 str(EVIDENCE.relative_to(REPO))):
        return {}
    text = EVIDENCE.read_text(encoding="ascii")
    doc = json.loads(text)
    check("B: no provider key and no world key in it", SECRET.search(text) is None and KEY not in text)
    hiring = doc["parameters"].get("hiring") or {}
    keys = ((doc.get("outcome") or {}).get("metering") or {}).get("keys") or []
    hire_key = next((k for k in keys if k["spec_id"].startswith("hire-")), None)
    check("B: the hire is a real model on the metered provider, charged by the system",
          hiring.get("provider") == "openrouter" and hire_key is not None
          and hire_key["spent_usd_micros"] > 0
          and hire_key["limit_usd_micros"] == round(get_settings().hiring.budget_usd * 1e6),
          f"{hire_key['spec_id']}: ${hire_key['spent_usd_micros'] / 1e6:.4f} of a "
          f"${hire_key['limit_usd_micros'] / 1e6:.2f} key" if hire_key else "no key")
    seen = chain(doc, "B")
    if seen:
        check("B: the real PM researched before it pitched (every backtest counted)",
              len(seen["research"]) >= 1
              and [p["attempt"] for p in seen["research"]] == list(range(1, len(seen["research"]) + 1)))
    verify(text, "B")
    return {"doc": doc, **seen}


def report(firm: Firm, history: list[dict]) -> None:
    print("\nWhat happened, morning by morning (first of each kind):")
    seen = set()
    for day, what, detail in firm.log:
        kind = (what, detail[:20])
        if kind in seen:
            continue
        seen.add(kind)
        print(f"  day {day + 1:>3}: {what}: {detail}")
    print("\nStages through time (every 10 days):")
    names = list(firm.pods)
    print("  day " + "".join(f"{n:>13}" for n in names))
    for row in history:
        if row["day"] % 10 and row["day"] != 1:
            continue
        print(f"  {row['day']:>3} " + "".join(f"{row['stages'].get(n, ''):>13}" for n in names))
    if 1 in firm.hired:
        pm = firm.hired[1]["read"]["post_mortem"]
        print(f"\nThe post-mortem hire-1 read (vacancy {firm.hired[1]['vacancy_id']}):")
        print(f"  pod {pm['pod_name']} ({', '.join(pm['pms'])}), seeded {pm['seeded_on']}, "
              f"closed {pm['closed_on']} after {pm['forward_days']} forward days")
        print(f"  rule: {pm['pitch']['rule']['signal']} top {pm['pitch']['rule']['top_n']} of "
              f"{len(pm['pitch']['rule']['universe'])}; return {pm['forward_return']:.1%}, worst "
              f"drawdown {pm['worst_drawdown']:.1%}")
        for step in pm["ladder"]:
            print(f"    {step['on']}: {step['from']} → {step['to']} at {step['drawdown']:.1%}")
        print(f"  capital: ${pm['capital']['put_in_usd']:,.0f} in, "
              f"${pm['capital']['taken_back_usd']:,.0f} back")


def main() -> int:
    started = time.monotonic()
    if (REPO / "governance" / "HALT").exists():
        print("governance/HALT exists: not running")
        return 1
    logger.remove()
    firm = Firm()
    try:
        verdicts = {name: firm.pitch(name, fam, top, "Slow diffusion of information: recent "
                                     "winners keep winning.")
                    for name, (fam, top) in FIRST.items()}
        check("A0: the five first pods are eligible at the gates and the firm opens",
              all(v["eligible"] for v in verdicts.values()),
              ", ".join(f"{n} {'eligible' if v['eligible'] else 'NOT eligible'}"
                        for n, v in verdicts.items()))
        history = firm.live()
        checks(firm)
        report(firm, history)
    finally:
        firm.client.__exit__(None, None, None)
        set_provider(None)
    rehearsal()
    seen = recorded()
    report_hire(seen)
    print(f"\n{len(FAILED)} failed · {time.monotonic() - started:.0f} s")
    for name in FAILED:
        print(f"  FAILED: {name}")
    TMP.cleanup()
    return 1 if FAILED else 0


def report_hire(seen: dict) -> None:
    """The recorded hire, for the Human: the post-mortem it read, its research, its pitch, its words."""
    if not seen:
        return
    run = seen["doc"]["outcome"]["run"]
    print("\n== The recorded hire ==")
    for step, w in seen["wakes"]:
        said = next((m["content"] for m in reversed(w.get("transcript") or [])
                     if m["role"] == "assistant" and m.get("content")), "")
        calls = [c["name"] for m in w.get("transcript") or [] for c in m.get("tool_calls") or []]
        at = run["steps"][step]["at"][:10]
        print(f"  {at}: {', '.join(calls) or 'no tools'}")
        for line in said.strip().splitlines()[:6]:
            print(f"    {line}")
    for (_, pitch), verdict in zip(seen["pitches"], seen["judged"]):
        print(f"  Pitch: {pitch['hypothesis']}")
        print(f"  Rule: {json.dumps(pitch['rule'], sort_keys=True)}")
        print("  Gates: " + ", ".join(f"{g['gate']} {g['result']}" for g in verdict["gates"])
              + f" → {'ELIGIBLE' if verdict['eligible'] else 'not eligible'}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--write-world"]:   # the files the recorded run was made from ($0)
        write_world(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "openrouter")
        sys.exit(0)
    sys.exit(main())
