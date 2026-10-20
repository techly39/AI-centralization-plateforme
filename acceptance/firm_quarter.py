"""Acceptance demo — the firm lives a quarter: several PMs compete for the same capital for three
simulated months, pods die and are replaced, and the Human gets a quarter report.

Costs $0 and needs no network.

  A  scripted, in this process, on one made-up market (stdlib ``random``, one fixed seed), through
     the app's HTTP API, for a quarter (91 days). Four sectors with four fates nobody inside knows:
       edge   E  momentum keeps paying                  → seeded, raised by the algorithm
       noise  N  pure noise, no edge on any day         → never eligible, never seeded
       sink   S  bleeds 0.4 % a day from the first day  → closed by the ladder → a hire
       crash  C  quiet, then three days of −5 % on day 40 → closed at once  → a hire
     Two sectors no one holds (F, G: an edge each) are where the hires look. The hiring law allows
     4 live pods. Every morning: the onboarding (a stand-in for the Runtime's) fills each open
     vacancy; each PM reads its mandate and sends the orders; the meter charges each PM's thinking
     (a scripted price per morning: the hire on G is an expensive mind). Every five days the
     algorithm re-weighs capital by each pod's score net of that thinking.
     The run's capital law tells PMs everything (``tell_pms``): a seeded pod's later pitch gets an
     answer, and the capital view carries the hiring law.
  B  (session 2) the same quarter with real PMs, recorded; ``replay --verify`` IDENTICAL for $0.

    uv run python acceptance/firm_quarter.py        # exit 0 = the idea works
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory(prefix="fund-firm-quarter-")
for k in [k for k in os.environ if k.startswith("FUND_")]:
    del os.environ[k]
os.environ["FUND_DATABASE_URL"] = f"sqlite:///{Path(TMP.name) / 'fund.db'}"
os.environ["FUND_MARKETDATA__PROVIDER"] = "static"
os.environ["FUND_LOGGING__LEVEL"] = "ERROR"
os.environ["FUND_HIRING__MAX_LIVE_PODS"] = "4"
os.environ["FUND_CAPITAL__TELL_PMS"] = "true"
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402
from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.capital.allocation import PodTrack, reallocate  # noqa: E402
from app.capital.report import quarter_report, render  # noqa: E402
from app.cli import main as fund_env  # noqa: E402
from app.config import CapitalConfig  # noqa: E402
from app.db.base import session_scope  # noqa: E402
from app.db.models import AgentRole, CashBalance, Event, Pod, Position  # noqa: E402
from app.ledger.rebuild import rebuild_state  # noqa: E402
from app.main import create_app  # noqa: E402
from app.marketdata import BarsProvider, get_provider, set_provider  # noqa: E402
from app.marketdata.made_up import Family, MadeUpMarket, bars  # noqa: E402
from app.registry.pods import create_pod  # noqa: E402
from app.registry.service import register_agent, seed_runtime_agent  # noqa: E402
from app.run_clock import start_backtest  # noqa: E402

SEED = 7
ORIGIN = date(2023, 1, 1)
START = date(2024, 9, 1)
QUARTER = 91
NOISE, PLANTED = 0.010, 0.004
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0}
#: family: (width, fate, rate)
FAMILIES = {"E": (20, "edge", 0.0), "N": (20, "noise", 0.0), "S": (10, "sink", 0.004),
            "C": (10, "crash", 40), "F": (20, "edge", 0.0), "G": (20, "edge", 0.0)}
#: the founding pods: pod → its sector
FOUNDING = {"edge": "E", "noise": "N", "sink": "S", "crash": "C"}
#: vacancy number → the sector its new PM pitches on
HIRES = {1: "F", 2: "G"}
LIMIT = 4
#: what each PM's thinking costs a morning, by pod (the meter charges it; USD)
#: (the second hire is an expensive mind, $400 a morning, a stand-in for a whole team: a real
#: model's morning costs cents, which the recorded run will show)
PRICE = {"edge": 20.0, "noise": 20.0, "sink": 20.0, "crash": 20.0, "hire-1": 20.0,
         "hire-2": 400.0}
#: the morning the edge PM pitches a second rule (its pod is already seeded)
SECOND_PITCH_DAY = 12

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)
    return ok


MARKET = MadeUpMarket(seed=SEED, origin=ORIGIN, pivot=START,
                      days=(START - ORIGIN).days + QUARTER + 5, noise=NOISE, planted=PLANTED,
                      families=[Family(prefix=p, width=w, fate=fate, rate=rate)
                                for p, (w, fate, rate) in FAMILIES.items()])


def rule(family: str, top_n: int = 5) -> dict:
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
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.pods: dict[str, dict] = {}
        for name, pod_id in ids.items():
            r = self.client.post("/agents/register", headers=h(self.admin),
                                 json={"name": f"pm-{name}", "role": "pm", "pod_id": pod_id})
            assert r.status_code == 201, r.text
            self.pods[name] = {"id": pod_id, "key": r.json()["api_key"],
                               "agent": r.json()["id"], "spent": 0.0}
        self.live_after_fill: list[int] = []
        self.hired: dict[int, dict] = {}
        self.seen: dict[str, object] = {}

    def pitch(self, name: str, family: str, top_n: int = 5) -> dict:
        r = self.client.post("/pitches", headers=h(self.pods[name]["key"]), json={
            "hypothesis": "Slow diffusion of information: recent winners keep winning.",
            "data_needed": "daily prices", "team": "the PM alone", "budget_usd": 0.0,
            "rule": rule(family, top_n)})
        assert r.status_code == 201, r.text
        return r.json()

    def think(self, name: str) -> None:
        """The meter: the PM's key's total grows by its price for the morning."""
        p = self.pods[name]
        p["spent"] += PRICE[name]
        r = self.client.post("/metering/usage", headers=h(self.runtime), json={
            "agent_id": p["agent"], "key_ref": f"key-{name}",
            "usd_micros_total": round(p["spent"] * 1e6)})
        assert r.status_code == 200, r.text

    def morning(self, day: int) -> None:
        """The onboarding stand-in: every open vacancy, oldest first, is offered for a fill."""
        r = self.client.get("/vacancies", headers=h(self.admin))
        assert r.status_code == 200, r.text
        for v in r.json():
            if v["status"] != "open":
                continue
            r = self.client.post(f"/vacancies/{v['id']}/fill", headers=h(self.admin))
            if r.status_code != 201:
                continue
            done = r.json()
            agent, name = done["agent"], done["vacancy"]["filled"]["pod_name"]
            with session_scope() as s:
                self.live_after_fill.append(
                    sum(1 for p in s.scalars(select(Pod)) if p.status != "closed"))
            self.pods[name] = {"id": agent["pod_id"], "key": agent["api_key"],
                               "agent": agent["id"], "spent": 0.0}
            # The new PM's first morning: its post-mortem, the law it lives under, then a pitch.
            read = self.client.get(f"/vacancies/{v['id']}", headers=h(agent["api_key"]))
            capital = self.client.get("/capital", headers=h(agent["api_key"]))
            verdict = self.pitch(name, HIRES.get(v["vacancy_no"], "N"))
            self.hired[v["vacancy_no"]] = {"day": day, "pod": name, "read": read.json(),
                                           "capital": capital.json(), "pitch": verdict}

    def live(self) -> None:
        for day in range(QUARTER):
            self.morning(day)
            if day == SECOND_PITCH_DAY:
                self.seen["second"] = self.pitch("edge", "E", top_n=4)
                self.seen["edge_pitches"] = self.client.get(
                    "/pitches", headers=h(self.pods["edge"]["key"])).json()
                self.seen["edge_capital"] = self.client.get(
                    "/capital", headers=h(self.pods["edge"]["key"])).json()
            for name, p in self.pods.items():
                self.think(name)
                r = self.client.get("/mandate", headers=h(p["key"]))
                if r.status_code != 200:
                    continue
                for order in r.json()["orders"]:
                    self.client.post("/orders", headers=h(p["key"]), json={
                        "ticker": order["ticker"], "side": order["side"], "qty": order["qty"],
                        "price_type": "market", "justification": "my rule's rebalance"})
            r = self.client.post("/clock/advance", headers=h(self.runtime), json={"days": 1})
            assert r.status_code == 200, r.text


# --- the checks ---------------------------------------------------------------------------------

def checks(firm: Firm, founding: dict[str, dict]) -> dict:
    ids = {n: p["id"] for n, p in firm.pods.items()}
    names = {v: k for k, v in ids.items()}
    with session_scope() as s:
        seeded = {e["pod_id"]: e for e in events(s, "capital_seeded")}
        stages = events(s, "pod_stage_changed")
        opened = events(s, "vacancy_opened")
        filled = events(s, "vacancy_filled")
        moves = [e for e in events(s, "allocation_set") if e.get("source") == "capital"]
        realloc = events(s, "capital_reallocated")
        law = CapitalConfig.model_validate(events(s, "capital_opened")[0]["law"])

    # A1: the gates and the seeds
    v = {n: founding[n]["verdict"]["eligible"] for n in FOUNDING}
    check("A1: edge, sink and crash pitch eligible rules and are seeded; noise is not eligible, "
          "never seeded",
          v == {"edge": True, "noise": False, "sink": True, "crash": True}
          and {ids[n] for n in ("edge", "sink", "crash")} <= set(seeded)
          and ids["noise"] not in seeded, f"eligible {v}; seeded "
          f"{sorted(names[p] for p in seeded if p in names)}")

    # A2: the edge pod is raised, never cut by the ladder
    raises = [m for m in moves if m["pod_id"] == ids["edge"] and m["delta"] > 0
              and "raise" in m["reason"]]
    edge_stages = [e["to"] for e in stages if e["pod_id"] == ids["edge"]]
    check("A2: the algorithm raises the edge pod; the ladder never touches it",
          len(raises) >= 1 and not edge_stages,
          f"{len(raises)} raise(s), ${sum(m['delta'] for m in raises):,.0f} in all")

    # A3: the sinking and the crashing pods die and are replaced
    closed = {e["pod_id"]: e for e in stages if e["to"] == "closed"}
    check("A3: the ladder closes the sinking and the crashing pods, and only them",
          set(closed) == {ids["sink"], ids["crash"]},
          ", ".join(f"{names[p]} on {e['_ts'].date()} at {e['worst_drawdown']:.1%} down"
                    for p, e in closed.items()))
    hires = {f["vacancy_id"]: f for f in filled}
    ok = len(opened) == 2 and all(o["_id"] in hires for o in opened)
    detail = []
    for n, hire in sorted(firm.hired.items()):
        o = next((o for o in opened if o["_id"] == hire["read"]["id"]), None)
        late = (hires[o["_id"]]["_ts"].date() - o["_ts"].date()).days if o else None
        ok = ok and o is not None and late is not None and late <= 1 and (
            hire["read"]["post_mortem"]["pod_id"] == o["pod_id"])
        detail.append(f"{hire['pod']} replaces {o and names.get(o['pod_id'])} "
                      f"{late} day(s) after the close")
    check("A3: each close opens a vacancy; the next morning a new PM is hired and reads the dead "
          "pod's post-mortem", ok, "; ".join(detail))
    hire_seeded = [firm.hired[n]["pod"] for n in firm.hired
                   if firm.hired[n]["pitch"]["verdict"]["eligible"]
                   and ids[firm.hired[n]["pod"]] in seeded]
    check("A3: both hires pitch an eligible rule and earn a seed",
          sorted(hire_seeded) == ["hire-1", "hire-2"], f"seeded: {hire_seeded}")
    check("A4: the live-pod limit holds at every hire",
          bool(firm.live_after_fill) and all(n <= LIMIT for n in firm.live_after_fill),
          f"live pods after each fill: {firm.live_after_fill} (limit {LIMIT})")

    # A5: thinking cost decides a rank. Every re-weighing is redone from its recorded input with
    # no thinking cost: where the order of two scored pods differs, the cost turned it.
    flips, same, costly = [], [], {}
    for event in realloc:
        rows = {r["pod_id"]: r for r in event["result"]["pods"] if r["viability"] is not None}
        tracks = [PodTrack.from_input(p) for p in event["inputs"]["pods"]]
        free = reallocate([PodTrack(**{**t.__dict__, "cost_usd": 0.0}) for t in tracks],
                          centre_cash=event["inputs"]["centre_cash"], law=law)
        gross = {r["pod_id"]: r["viability"] for r in free["pods"] if r["viability"] is not None}
        cost = {t.pod_id: t.cost_usd for t in tracks}
        for a in rows:
            for b in rows:
                if a != b and gross[a] > gross[b] and rows[a]["viability"] < rows[b]["viability"]:
                    (flips if cost[a] > cost[b] else same).append(
                        (event["day"], names[a], gross[a], rows[a]["viability"], cost[a],
                         names[b], gross[b], rows[b]["viability"], cost[b]))
    check("A5: a pod that scores higher before thinking cost ranks lower after it (the costly "
          "mind), and the cheap one above it",
          bool(flips), "; ".join(
              f"{d}: {a} {ga:.2f} > {b} {gb:.2f} before cost, {va:.2f} < {vb:.2f} after "
              f"(${ca:,.0f} vs ${cb:,.0f} of thinking)" for d, a, ga, va, ca, b, gb, vb, cb
              in flips[:2]) or "no rank turned")
    check("A5: ... and no rank turns but by the cost: a pod no costlier than another keeps its "
          "order", not same, f"{len(realloc)} re-weighings")

    # A6: what the PMs could see
    second = firm.seen["second"]
    answer = (second.get("capital") or {})
    listed = next((p for p in firm.seen["edge_pitches"] if p["id"] == second["id"]), {})
    first_id = seeded[ids["edge"]]["pitch_id"]
    check("A6: the edge PM's later pitch is answered at once: its pod already runs its seeded pitch",
          second["verdict"]["eligible"] and answer.get("outcome") == "not_seeded"
          and f"#{first_id}" in answer.get("reason", "") and listed.get("capital") == answer,
          answer.get("reason", "no answer"))
    law_seen = [firm.seen["edge_capital"].get("hiring")] + [
        hire["capital"].get("hiring") for hire in firm.hired.values()]
    check("A6: every PM's capital view carries the hiring law",
          all(x and "new PM is hired" in x["law"] and x["max_live_pods"] == LIMIT
              for x in law_seen), (law_seen[0] or {}).get("law", "absent"))

    # A7: the ledger is the truth
    with session_scope() as s:
        before = _snapshot(s)
        rebuild_state(s)
        s.flush()
        after_ = _snapshot(s)
        s.rollback()
    check("A7: rebuilding from the ledger gives the same cash, positions, pods", before == after_)
    return {"names": names}


def _snapshot(s) -> dict:
    return {"cash": sorted((c.pod_id, round(c.balance, 6)) for c in s.scalars(select(CashBalance))),
            "positions": sorted((p.pod_id, p.ticker, round(p.qty, 9), round(p.avg_cost, 9))
                                for p in s.scalars(select(Position))),
            "pods": sorted((p.id, p.name, p.status, round(p.current_allocation, 6))
                           for p in s.scalars(select(Pod)))}


def report_checks(firm: Firm) -> dict:
    """A8: the quarter report, from the API, against an independent sum of the money."""
    r = firm.client.get("/capital/report", headers=h(firm.admin))
    denied = firm.client.get("/capital/report", headers=h(firm.pods["edge"]["key"]))
    with session_scope() as s:
        direct = quarter_report(s, provider=get_provider())
        cash = sum(c.balance for c in s.scalars(select(CashBalance)))
    rep = r.json() if r.status_code == 200 else {}
    check("A8: the quarter report reads from the API (management), not by a PM",
          r.status_code == 200 and rep == _jsonish(direct) and denied.status_code == 403,
          f"management {r.status_code}, a PM {denied.status_code}")
    if not rep:
        return {}
    pods = {p["name"]: p for p in rep["pods"]}
    # Money is kept: the firm's equity is its capital plus every pod's gross P&L, and the pods'
    # equity on the last day is their cash plus their holdings (an independent sum).
    firm_end = rep["firm"][-1]
    made = sum(p["pnl_gross_usd"] for p in rep["pods"])
    check("A8: money is kept: the firm's last-day equity is its capital plus every pod's P&L",
          abs(firm_end - (rep["firm_capital_usd"] + made)) < 1.0,
          f"${firm_end:,.0f} = ${rep['firm_capital_usd']:,.0f} + ${made:,.0f}")
    weeks = len(rep["weeks"])
    check("A8: the report holds every week of the quarter, each pod's P&L gross and net of "
          "thinking, the deaths and the hires",
          rep["weeks"][0] == rep["opened_on"] and rep["weeks"][-1] == rep["today"]
          and weeks >= QUARTER // 7
          and all(abs(p["pnl_net_usd"] - (p["pnl_gross_usd"] - p["thinking_usd"])) < 1e-6
                  for p in rep["pods"])
          and pods["sink"]["closed_on"] and pods["crash"]["closed_on"]
          and "hired" in pods["hire-1"]["origin"] and pods["noise"]["put_in_usd"] == 0
          and cash > 0, f"{weeks} columns; {len(rep['happened'])} happenings")
    return rep


def _jsonish(doc):
    import json
    return json.loads(json.dumps(doc, default=str))


def main() -> int:
    started = time.monotonic()
    if (REPO / "governance" / "HALT").exists():
        print("governance/HALT exists: not running")
        return 1
    logger.remove()
    firm = Firm()
    try:
        founding = {name: firm.pitch(name, fam) for name, fam in FOUNDING.items()}
        founding = {n: {"verdict": p["verdict"]} for n, p in founding.items()}
        firm.live()
        checks(firm, founding)
        rep = report_checks(firm)
        if rep:
            print("\n" + render(rep))
    finally:
        firm.client.__exit__(None, None, None)
        set_provider(None)
    print(f"\n{len(FAILED)} failed · {time.monotonic() - started:.0f} s")
    for name in FAILED:
        print(f"  FAILED: {name}")
    TMP.cleanup()
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
