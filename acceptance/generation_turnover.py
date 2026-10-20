"""Acceptance demo — a generation turns over: at each month's end the firm measures every pod net of
its thinking, lets go the PMs who failed, keeps their lessons in a library every PM reads, and
hires into the freed places.

Costs $0 and needs no network.

  A  scripted, in this process, on one made-up market (stdlib ``random``, one fixed seed), through
     the app's HTTP API, for three months (Sep, Oct, Nov 2024; the clock lands on Dec 1). The run's
     laws turn the generation law on (a PM is judged after 20 days in its pod) and allow 3 live
     pods. Every morning a stand-in for the Runtime: it hires into each open vacancy, wakes each PM
     whose key still answers (a let-go PM's answers 401: it is retired and spends nothing more),
     and the meter charges each awake PM's thinking ($20 a morning).
       edge   pitches the edge sector K on day 0 → seeded → stays every month
       noise  pitches the noise sector M twice → never seeded → let go at September's end; its
              place is hired the next morning
       crash  pitches the crashing sector R → seeded → closed by the ladder mid-September → its PM
              let go at the close
       hire-1 (into the crash's place, mid-September) pitches noise, then on Oct 5 the edge sector
              T → at September's end it is too new to judge; seeded in October; stays
       hire-2 (into the noise pod's place, Oct 1) pitches noise twice → let go at October's end
       hire-3 (Nov 1) reads the library first, pitches the edge sector W → seeded → stays
     An empty pod the operator made at the start holds no place under the live-pod limit.
  B0 the same run hosted, through the Runtime, recorded: the let-go minds retired, replay IDENTICAL
     (not built yet: session 2)
  B  real PMs (Haiku 5.5), three generations, recorded: IDENTICAL for $0 (session 3)

    uv run python acceptance/generation_turnover.py        # exit 0 = the idea works
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory(prefix="fund-generation-")
for k in [k for k in os.environ if k.startswith("FUND_")]:
    del os.environ[k]
os.environ["FUND_DATABASE_URL"] = f"sqlite:///{Path(TMP.name) / 'fund.db'}"
os.environ["FUND_MARKETDATA__PROVIDER"] = "static"
os.environ["FUND_LOGGING__LEVEL"] = "ERROR"
os.environ["FUND_HIRING__MAX_LIVE_PODS"] = "3"
os.environ["FUND_CAPITAL__TELL_PMS"] = "true"
os.environ["FUND_GENERATION__ON"] = "true"
os.environ["FUND_GENERATION__GRACE_DAYS"] = "20"
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.capital.report import generation_report, render_generations  # noqa: E402
from app.cli import main as fund_env  # noqa: E402
from app.db.base import session_scope  # noqa: E402
from app.db.models import Agent, AgentRole, AgentStatus, CashBalance, Event, Pod, Position  # noqa: E402
from app.ledger.rebuild import rebuild_state  # noqa: E402
from app.main import create_app  # noqa: E402
from app.marketdata import BarsProvider, set_provider  # noqa: E402
from app.marketdata.made_up import Family, MadeUpMarket, bars  # noqa: E402
from app.registry.pods import create_pod  # noqa: E402
from app.registry.service import register_agent, seed_runtime_agent  # noqa: E402
from app.run_clock import start_backtest  # noqa: E402

SEED = 7
ORIGIN = date(2023, 1, 1)
START = date(2024, 9, 1)
DAYS = 91                       # Sep 1 .. Nov 30; the last advance lands on Dec 1
NOISE, PLANTED = 0.010, 0.004
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0}
#: family: (width, fate, rate)   (crash: the day after the pivot its three falls begin)
FAMILIES = {"K": (20, "edge", 0.0), "M": (20, "noise", 0.0), "R": (10, "crash", 15),
            "T": (20, "edge", 0.0), "W": (20, "edge", 0.0)}
FOUNDING = {"edge": "K", "noise": "M", "crash": "R"}
PRICE = 20.0                    # what a morning of thinking costs, USD
LIMIT = 3
GRACE = 20
#: what each PM pitches, and when: (pod, day of its own or a date) -> sector, top_n
PLAN = {("edge", 0): ("K", 5), ("noise", 0): ("M", 5), ("noise", 10): ("M", 4),
        ("crash", 0): ("R", 5),
        ("hire-1", "first"): ("M", 5), ("hire-1", date(2024, 10, 5)): ("T", 5),
        ("hire-2", "first"): ("M", 5), ("hire-2", date(2024, 10, 15)): ("M", 4),
        ("hire-3", "first"): ("W", 5)}

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)
    return ok


MARKET = MadeUpMarket(seed=SEED, origin=ORIGIN, pivot=START,
                      days=(START - ORIGIN).days + DAYS + 5, noise=NOISE, planted=PLANTED,
                      families=[Family(prefix=p, width=w, fate=fate, rate=rate)
                                for p, (w, fate, rate) in FAMILIES.items()])


def rule(family: str, top_n: int) -> dict:
    return {**MOMENTUM, "universe": [f"{family}{k:02d}" for k in range(FAMILIES[family][0])],
            "top_n": top_n}


def h(key: str) -> dict:
    return {"X-API-Key": key}


def events(s, type_: str) -> list[dict]:
    return [dict(e.payload_json, _id=e.id, _ts=e.ts) for e in
            s.scalars(select(Event).where(Event.type == type_).order_by(Event.id))]


class Firm:
    def __init__(self) -> None:
        assert fund_env(["init-db"]) == 0
        set_provider(BarsProvider(bars(MARKET)))
        with session_scope() as s:
            start_backtest(s, start=datetime.combine(START, datetime.min.time(), UTC))
            _, self.admin = register_agent(s, name="management", role=AgentRole.management)
            _, self.runtime = seed_runtime_agent(s)
            ids = {name: create_pod(s, name=name).id for name in FOUNDING}
            self.spare = create_pod(s, name="spare").id     # an empty pod: no PM, no money
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.pods: dict[str, dict] = {}
        for name, pod_id in ids.items():
            self._join(name, pod_id, *self._register(f"pm-{name}", pod_id), day=0)
        self.retired: dict[str, date] = {}
        self.refused_after: dict[str, list[int]] = {}
        self.fills: list[dict] = []
        self.first_reads: dict[str, dict] = {}

    def _register(self, name: str, pod_id: int) -> tuple[str, int]:
        r = self.client.post("/agents/register", headers=h(self.admin),
                             json={"name": name, "role": "pm", "pod_id": pod_id})
        assert r.status_code == 201, r.text
        return r.json()["api_key"], r.json()["id"]

    def _join(self, name: str, pod_id: int, key: str, agent: int, day: int) -> None:
        self.pods[name] = {"id": pod_id, "key": key, "agent": agent, "spent": 0.0,
                           "joined": day, "pitches": []}

    def today(self) -> date:
        return date.fromisoformat(self.client.get("/clock", headers=h(self.runtime))
                                  .json()["now"][:10])

    def pitch(self, name: str, family: str, top_n: int) -> None:
        r = self.client.post("/pitches", headers=h(self.pods[name]["key"]), json={
            "hypothesis": "Slow diffusion of information: recent winners keep winning.",
            "data_needed": "daily prices", "team": "the PM alone", "budget_usd": 0.0,
            "rule": rule(family, top_n)})
        assert r.status_code == 201, r.text
        self.pods[name]["pitches"].append(r.json())

    def think(self, name: str) -> None:
        p = self.pods[name]
        p["spent"] += PRICE
        r = self.client.post("/metering/usage", headers=h(self.runtime), json={
            "agent_id": p["agent"], "key_ref": f"key-{name}",
            "usd_micros_total": round(p["spent"] * 1e6)})
        assert r.status_code == 200, r.text

    def hire(self, day: int) -> None:
        """The onboarding stand-in: every open vacancy, oldest first, is offered for a fill."""
        for v in self.client.get("/vacancies", headers=h(self.admin)).json():
            if v["status"] != "open":
                continue
            r = self.client.post(f"/vacancies/{v['id']}/fill", headers=h(self.admin))
            with session_scope() as s:
                staffed = {a.pod_id for a in s.scalars(select(Agent).where(
                    Agent.status == AgentStatus.active))}
                live = [p.name for p in s.scalars(select(Pod)) if p.status != "closed"
                        and p.id in staffed]
            self.fills.append({"vacancy": v, "status": r.status_code, "live_after": live})
            if r.status_code != 201:
                continue
            agent, name = r.json()["agent"], r.json()["vacancy"]["filled"]["pod_name"]
            self._join(name, agent["pod_id"], agent["api_key"], agent["id"], day)

    def wake(self, name: str, day: int) -> None:
        p = self.pods[name]
        if self.client.get("/me", headers=h(p["key"])).status_code == 401:
            # Let go: the Runtime retires the mind; it never wakes (nor spends) again. What it
            # would get if it tried anyway, once:
            if name not in self.retired:
                self.retired[name] = self.today()
                self.refused_after[name] = [
                    self.client.get("/pitches", headers=h(p["key"])).status_code,
                    self.client.get("/library", headers=h(p["key"])).status_code]
            return
        self.think(name)
        first = day == p["joined"]
        if first and name.startswith("hire-"):
            self.first_reads[name] = {
                "library": self.client.get("/library", headers=h(p["key"])).json(),
                "capital": self.client.get("/capital", headers=h(p["key"])).json(),
                "on": self.today()}
        own = day - p["joined"]
        for key in ((name, "first") if first else None, (name, own), (name, self.today())):
            if key in PLAN and not (key[1] == own and name.startswith("hire-")):
                self.pitch(name, *PLAN[key])
        r = self.client.get("/mandate", headers=h(p["key"]))
        if r.status_code == 200:
            for order in r.json()["orders"]:
                self.client.post("/orders", headers=h(p["key"]), json={
                    "ticker": order["ticker"], "side": order["side"], "qty": order["qty"],
                    "price_type": "market", "justification": "my rule's rebalance"})

    def live(self) -> None:
        for day in range(DAYS):
            self.hire(day)
            for name in list(self.pods):
                self.wake(name, day)
            r = self.client.post("/clock/advance", headers=h(self.runtime), json={"days": 1})
            assert r.status_code == 200, r.text


# --- the checks ---------------------------------------------------------------------------------

def checks(firm: Firm) -> None:
    ids = {n: p["id"] for n, p in firm.pods.items()}
    names = {v: k for k, v in ids.items()}
    with session_scope() as s:
        gens = events(s, "generation_ended")
        gone = events(s, "pm_let_go")
        seeded = {e["pod_id"]: e for e in events(s, "capital_seeded")}
        closes = {e["pod_id"]: e for e in events(s, "pod_stage_changed") if e["to"] == "closed"}
        opened = events(s, "vacancy_opened")
        filled = events(s, "vacancy_filled")
        status = {a.name: a.status for a in s.scalars(select(Agent))}
        pods = {p.name: p.status for p in s.scalars(select(Pod))}
        metered = [(e["agent_id"], e["usd_micros_total"], e["_id"])
                   for e in events(s, "cost_metered")]

    # G1: three generations, one per month, each with every pod's fitness = P&L - thinking
    months = [g["month"] for g in gens]
    check("G1: a generation ends at each month's turn: three in three months",
          months == ["2024-09", "2024-10", "2024-11"],
          ", ".join(f"#{g['generation']} {g['month']} measured {g['_ts'].date()}" for g in gens))
    ok, detail = True, []
    for g in gens:
        for p in g["pods"]:
            if p["pnl_usd"] is not None:
                ok = ok and abs(p["fitness_usd"] - (p["pnl_usd"] - p["thinking_usd"])) < 1e-6
    # the thinking each generation charged a pod, summed independently from the meter's rows
    agent_pod = {p["agent"]: p["id"] for p in firm.pods.values()}
    for g in gens:
        since = max((x["_id"] for x in gens if x["generation"] == g["generation"] - 1), default=0)
        for p in g["pods"]:
            totals: dict[int, tuple[int, int]] = {}
            for agent, total, eid in metered:
                if agent_pod.get(agent) == p["pod_id"] and eid <= g["_id"]:
                    before, now = totals.get(agent, (0, 0))
                    totals[agent] = (total if eid <= since else before, total)
            spent = sum(now - before for before, now in totals.values()) / 1e6
            ok = ok and abs(spent - p["thinking_usd"]) < 1e-6
        detail.append(f"#{g['generation']}: " + ", ".join(
            f"{p['pod_name']} {p['fitness_usd'] if p['fitness_usd'] is None else round(p['fitness_usd'])}"
            for p in g["pods"]))
    check("G1: every pod's fitness is its P&L that month minus its thinking that month (the "
          "meter's rows, summed apart)", ok, "; ".join(detail))

    # G2: the never-seeded PM goes at September's end; its place is hired the next morning
    by_pm = {e["agent_name"]: e for e in gone}
    noise = by_pm.get("pm-noise")
    v_noise = next((o for o in opened if o["pod_id"] == ids["noise"]), None)
    f_noise = next((f for f in filled if v_noise and f["vacancy_id"] == v_noise["_id"]), None)
    check("G2: the noise PM (never seeded, 30 days in) is let go at September's end, its pod "
          "closed, a vacancy opened with its lesson",
          noise is not None and noise["reason"] == "no_seed" and noise["generation"] == 1
          and status["pm-noise"] == AgentStatus.inactive and pods["noise"] == "closed"
          and v_noise is not None and v_noise["post_mortem"]["reason"] == "no_seed",
          (noise or {}).get("why", "not let go"))
    check("G2: ... it stops waking (its key answers 401: retired, no more thinking), and a call "
          "it tries is refused",
          firm.retired.get("noise") == date(2024, 10, 1)
          and firm.refused_after.get("noise") == [401, 401]
          and firm.pods["noise"]["spent"] == PRICE * 30,
          f"retired {firm.retired.get('noise')}, its calls answered "
          f"{firm.refused_after.get('noise')}, ${firm.pods['noise']['spent']:.0f} of thinking")
    check("G2: ... and the freed place is hired the next morning",
          f_noise is not None and f_noise["_ts"].date() == date(2024, 10, 1),
          f"{f_noise and f_noise['agent_name']} on {f_noise and f_noise['_ts'].date()}")

    # G3: the crash PM goes at the close itself
    crash = by_pm.get("pm-crash")
    closed = closes.get(ids["crash"])
    check("G3: the crash pod's PM is let go at the ladder's close, the post-mortem its lesson",
          crash is not None and closed is not None and crash["reason"] == "closed"
          and crash["_ts"] == closed["_ts"] and "post_mortem" in crash["lesson"]
          and status["pm-crash"] == AgentStatus.inactive,
          f"closed {closed and closed['_ts'].date()} at "
          f"{closed and closed['worst_drawdown']:.1%} down; let go "
          f"{crash and crash['_ts'].date()}")

    # G4: a PM hired late in the month is not judged that month; seeded later, it stays
    row = lambda gen, pod: next((p for p in gens[gen]["pods"] if p["pod_id"] == ids.get(pod)), {})  # noqa: E731
    check("G4: hire-1, hired mid-September and not yet seeded, is too new to judge at "
          "September's end; seeded in October, it stays",
          row(0, "hire-1").get("verdict") == "too_new" and ids["hire-1"] in seeded
          and seeded[ids["hire-1"]]["_ts"].date().month == 10
          and row(1, "hire-1").get("verdict") == "stays" and status["hire-1-pm"] == "active",
          f"Sep: {row(0, 'hire-1').get('why')}; Oct: {row(1, 'hire-1').get('why')}")

    # G5: the seeded PM stays every generation
    check("G5: the edge PM, seeded on its first pitch, stays every generation",
          [row(i, "edge").get("verdict") for i in range(3)] == ["stays"] * 3
          and status["pm-edge"] == "active")

    # G6: the next never-seeded hire goes at October's end; the third hire reads the library
    h2 = by_pm.get("hire-2-pm")
    check("G6: hire-2 (two noise pitches) is let go at October's end",
          h2 is not None and h2["generation"] == 2 and pods["hire-2"] == "closed",
          (h2 or {}).get("why", "not let go"))
    read = firm.first_reads.get("hire-3", {})
    lib = read.get("library") or []
    check("G6: hire-3, on its first morning, reads the library through its own key: every "
          "lesson so far, each with what the pod tried",
          [x["pms"] for x in lib] == [["pm-crash"], ["pm-noise"], ["hire-2-pm"]]
          and all("pitches" in x["lesson"] for x in lib)
          and ids["hire-3"] in seeded and status["hire-3-pm"] == "active",
          "; ".join(f"{x['lesson_no']}. {x['pms'][0]}: {x['why']}" for x in lib))
    law = (read.get("capital") or {}).get("generation") or {}
    check("G6: the capital view every PM reads states the generation law",
          "let go" in law.get("law", "") and law.get("grace_days") == GRACE,
          law.get("law", "absent")[:120])

    # G7: the live-pod limit counts no empty pod
    check("G7: the live-pod limit (3) holds at every hire, and an empty pod holds no place "
          "(the operator's spare pod, a let-go PM's closed pod)",
          bool(firm.fills) and all(f["status"] == 201 for f in firm.fills)
          and all(len(f["live_after"]) <= LIMIT for f in firm.fills) and pods["spare"] != "closed",
          "; ".join(f"{f['vacancy']['pod_name']} → live after: {f['live_after']}"
                    for f in firm.fills))

    # G8: the ledger is the truth
    with session_scope() as s:
        before = _snapshot(s)
        rebuild_state(s)
        s.flush()
        after = _snapshot(s)
        s.rollback()
    check("G8: rebuilding from the ledger gives the same cash, positions, pods", before == after)

    with session_scope() as s:
        report = generation_report(s)
        text = render_generations(report)
        s.rollback()
    print("\n" + text + "\n")
    check("G9: the generation report prints from the ledger: three generations, who went, the "
          "library", len(report["generations"]) == 3 and len(report["library"]) == 3
          and "pm-noise" in text and "hire-2-pm" in text)


def _snapshot(s) -> dict:
    return {"cash": sorted((c.pod_id, round(c.balance, 6)) for c in s.scalars(select(CashBalance))),
            "positions": sorted((p.pod_id, p.ticker, round(p.qty, 9))
                                for p in s.scalars(select(Position))),
            "pods": sorted((p.id, p.status, round(p.current_allocation, 6))
                           for p in s.scalars(select(Pod)))}


# --- B: the same months as a hosted world, lived by the Runtime ----------------------------------

#: The hosted world's key (ADR-045: never in the cassette; whoever verifies must know it).
KEY = hashlib.sha256(b"fund-generation-turnover/1").hexdigest()
DAYS_PER_STEP = 3
STEPS = 31                      # Sep 1 + 93 days: the clock lands on Dec 3
#: the founding pods' names in the hosted world (the minds read them: no fate in a name)
HOSTED = {"edge": "pod-1", "noise": "pod-2", "crash": "pod-3"}
#: what each hire pitches in the scripted rehearsal, by its PM's name
HIRED = {"hire-1-pm": "T", "hire-2-pm": "M", "hire-3-pm": "W"}
FIRM = (
    "You work in a hedge fund that trades a simulated market with fake money. Several pods, each "
    "run by its own PM, compete for the same capital. A pod gets capital only after its PM pitches "
    "a strategy and it passes the fund's validation gates; an eligible pitch earns a small seed "
    "and trades forward. Every month is a generation: get_capital shows the laws, including who "
    "is let go at a month's end. Be brief: every word you think is paid from your pod's P&L.")
WORLD = {"start": f"{START.isoformat()}T14:30:00Z", "admin": "generation-mgmt",
         "pods": [{"name": HOSTED[name], "allocation": 0} for name in FOUNDING],
         "market": MARKET.model_dump(mode="json"),
         "laws": {"capital": {"tell_pms": True},
                  "hiring": {"max_live_pods": LIMIT, "charter": "You are a newly hired PM. " + FIRM,
                             "budget_usd": 0.20},
                  "generation": {"on": True, "grace_days": GRACE}}}


def write_world(directory: Path, provider: str) -> None:
    """The hosted run's files: the world, the input, the three PMs, the hiring template."""
    (directory / "specs").mkdir(parents=True, exist_ok=True)
    (directory / "world.json").write_text(json.dumps(WORLD))
    found = {f"{HOSTED[name]}-pm": FOUNDING[name] for name in FOUNDING}
    doc = {"sectors": {pm: [f"{fam}{k:02d}" for k in range(FAMILIES[fam][0])]
                       for pm, fam in found.items()}}
    if provider == "scripted":   # each scripted PM pitches its sector once; each hire, its own
        doc["pitch_rules"] = {pm: rule(fam, 5) for pm, fam in {**found, **HIRED}.items()}
    (directory / "input.json").write_text(json.dumps(doc))
    for pod, pm in enumerate(found, start=1):
        spec = {"id": pm, "name": pm, "role": "pm", "pod": pod,
                "charter": f"You are {pm}, the PM of pod-{pod}. " + FIRM,
                "provider": "scripted", "script": "pitch-pm"}
        (directory / "specs" / f"{pm}.yaml").write_text(json.dumps(spec))
    (directory / "hire.yaml").write_text(json.dumps({"provider": "scripted",
                                                     "script": "pitch-pm"}))


def fund_runtime(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("FUND_", "OPENROUTER")) and k.lower() not in {
               "http_proxy", "https_proxy", "all_proxy"}}
    (cwd / "vtmp").mkdir(exist_ok=True)
    env.update({"FUND_MARKETDATA__SYNTHETIC_KEY": KEY, "TMPDIR": str(cwd / "vtmp"),
                "FUND_DATABASE_URL": f"sqlite:///{cwd / 'sentinel.db'}",
                "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"})
    return subprocess.run(["uv", "run", "--project", str(REPO), "fund-runtime", *argv], cwd=cwd,
                          env=env, capture_output=True, text=True, timeout=1800)


def verify(text: str, label: str) -> None:
    with tempfile.TemporaryDirectory(prefix="fund-generation-") as t:
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


def turnover_chain(doc: dict, label: str) -> None:
    """The generations, as the recorded ledger tells them, and the Runtime's retirements."""
    rows = [(r[0], r[3], json.loads(r[4])) for r in (doc.get("ledger") or {}).get("rows") or []]
    of = lambda t: [p for _, t2, p in rows if t2 == t]  # noqa: E731
    gens = of("generation_ended")
    gone = {p["agent_name"]: p for p in of("pm_let_go")}
    run = (doc.get("outcome") or {}).get("run") or {}
    hired = [h["spec_id"] for h in run.get("hires") or [] if h["outcome"] == "hired"]
    check(f"{label}: three generations end, one at each month's turn",
          [g["month"] for g in gens] == ["2024-09", "2024-10", "2024-11"],
          ", ".join(f"#{g['generation']} {g['month']}" for g in gens))
    check(f"{label}: the noise PM and the next never-seeded hire go at their month's end, the "
          "crash PM at its close",
          (gone.get("pod-2-pm") or {}).get("generation") == 1
          and (gone.get("hire-2-pm") or {}).get("generation") == 2
          and (gone.get("pod-3-pm") or {}).get("reason") == "closed" and len(gone) == 3,
          "; ".join(f"{n}: {p['why']}" for n, p in gone.items()))
    retired = dict(zip(run.get("retired") or [], run.get("retired_at") or []))
    check(f"{label}: the Runtime retired every let-go mind the next morning, and hired three PMs "
          "into the freed places",
          set(retired) == {"pod-2-pm", "pod-3-pm", "hire-2"} and hired == ["hire-1", "hire-2",
                                                                           "hire-3"],
          f"retired {retired}; hired {hired}")


def rehearsal() -> None:
    """B0, $0: the hosted months with scripted minds, recorded and verified now."""
    with tempfile.TemporaryDirectory(prefix="fund-generation-") as t:
        tmp = Path(t)
        write_world(tmp, "scripted")
        r = fund_runtime(["backtest", "--world", "world.json", "--specs", "specs", "--hire",
                          "hire.yaml", "--input", "input.json", "--steps", str(STEPS),
                          "--days-per-step", str(DAYS_PER_STEP),
                          "--cassette", "rehearsal.cassette.json"], tmp)
        tape = tmp / "rehearsal.cassette.json"
        if not check("B0: a scripted rehearsal of the hosted months completes and is recorded",
                     r.returncode == 0 and tape.is_file(), f"exit {r.returncode}: "
                     f"{r.stderr.strip()[-300:] if r.returncode else 'completed'}"):
            return
        text = tape.read_text(encoding="ascii")
    turnover_chain(json.loads(text), "B0")
    verify(text, "B0")


def main() -> int:
    print("A: three months, scripted, in process")
    firm = Firm()
    try:
        firm.live()
        checks(firm)
    finally:
        firm.client.__exit__(None, None, None)
        set_provider(None)
    print("\nB0: the same months hosted, through the Runtime, replayed")
    rehearsal()
    print("\nB: real PMs, three generations, recorded")
    check("B: real run recorded, replay IDENTICAL for $0, generation report", False,
          "not recorded yet")
    print(f"\n{'PASS' if not FAILED else 'FAIL'}: {len(FAILED)} check(s) failed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
