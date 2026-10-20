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
  B  the same quarter as a hosted world (the recipe the real run is made from: the market, four
     pods, and the world's own laws: ``tell_pms`` on, at most 4 live pods), lived by the Runtime:
     ``fund-runtime backtest --world --hire``, three days a step.
       B0 a scripted rehearsal, recorded now: the same deaths and hires, ``replay --verify``
          IDENTICAL, $0
       B  (next session) four real PMs and their hires, recorded; IDENTICAL from the file, $0

    uv run python acceptance/firm_quarter.py        # exit 0 = the idea works
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
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
from sqlalchemy import func, select  # noqa: E402

from app.capital.allocation import PodTrack, reallocate  # noqa: E402
from app.capital.report import quarter_report, render  # noqa: E402
from app.cli import main as fund_env  # noqa: E402
from app.config import CapitalConfig  # noqa: E402
from app.db.base import session_scope  # noqa: E402
from app.db.models import AgentRole, CashBalance, Event, Pod, Position  # noqa: E402
from app.ledger.events import ledger_now  # noqa: E402
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
        self.views: dict[str, list[tuple[int, dict]]] = {}

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
                # What the PM reads of its own pod each morning, and where the ledger stood then.
                with session_scope() as s:
                    at = s.scalar(select(func.max(Event.id)))
                view = self.client.get("/capital", headers=h(p["key"])).json()
                self.views.setdefault(name, []).append((at, view))
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

    consequences(firm, ids, seeded, stages, moves)

    # A7: the ledger is the truth
    with session_scope() as s:
        before = _snapshot(s)
        rebuild_state(s)
        s.flush()
        after_ = _snapshot(s)
        s.rollback()
    check("A7: rebuilding from the ledger gives the same cash, positions, pods", before == after_)
    return {"names": names}


def _first_view_after(firm: Firm, name: str, event_id: int) -> tuple[dict | None, dict | None]:
    """The PM's own capital row on the last morning before ``event_id`` and the first after it."""
    before = after = None
    for at, view in firm.views.get(name, []):
        row = (view.get("pods") or [None])[0]
        if at < event_id:
            before = row
        elif after is None:
            after = row
    return before, after


def consequences(firm: Firm, ids: dict, seeded: dict, stages: list, moves: list) -> None:
    """A9: every consequence physics gives a PM's act, seen by that PM through its own tools only
    (its key, the routes its tools call), the morning after: a real mind can act on nothing else.
    (Cycle 51 spent a real trial on a refusal no PM could see.)"""
    names = {v: k for k, v in ids.items()}
    key = {n: firm.pods[n]["key"] for n in firm.pods}
    own_pitches = {n: firm.client.get("/pitches", headers=h(key[n])).json() for n in key}

    # Judged: a rule with no edge reads why it is not eligible.
    noise = own_pitches["noise"][0]["verdict"]
    failed = [g["gate"] for g in noise.get("gates") or [] if g["result"] == "fail"]
    check("A9: the noise PM reads on its pitch that it is not eligible, and which gates failed",
          noise["eligible"] is False and bool(failed), f"failed: {failed}")

    # Seeded: the pitch says so, and the next morning's capital view holds the money.
    seen = []
    for pod_id, e in seeded.items():
        n = names[pod_id]
        pitch = next((p for p in own_pitches[n] if p["id"] == e["pitch_id"]), {})
        _, row = _first_view_after(firm, n, e["_id"])
        seen.append((n, (pitch.get("capital") or {}).get("outcome") == "seeded"
                     and row is not None and row["allocated_usd"] > 0
                     and row["pitch_id"] == e["pitch_id"]))
    check("A9: every seeded PM reads 'seeded' on its pitch and the money in its capital view the "
          "next morning", bool(seen) and all(ok for _, ok in seen),
          ", ".join(f"{n} {'seen' if ok else 'UNSEEN'}" for n, ok in seen))

    # Raised, cut, halved: every move of the centre's money shows in the PM's view next morning,
    # in the direction it went.
    unseen = []
    for e in moves:
        n = names.get(e["pod_id"])
        if n is None or n not in firm.views:
            continue
        before, after = _first_view_after(firm, n, e["_id"])
        if before is None or after is None:
            continue   # the seed itself (no morning before), or a move on the last night
        net = sum(m["delta"] for m in moves if m["pod_id"] == e["pod_id"]
                  and _first_view_after(firm, n, m["_id"]) == (before, after))
        diff = after["allocated_usd"] - before["allocated_usd"]
        if net and not (abs(diff - net) < 1e-6 * max(1.0, abs(net))):
            unseen.append(f"{n}: moved {net:+,.0f}, saw {diff:+,.0f}")
    raised = [e for e in moves if e["delta"] > 0 and "raise" in e["reason"]]
    cut = [e for e in moves if e["delta"] < 0]
    check("A9: every raise and cut of a pod's capital shows, to the dollar, in its PM's capital "
          "view the next morning", bool(raised) and bool(cut) and not unseen,
          f"{len(raised)} raise(s), {len(cut)} cut(s); " + ("; ".join(unseen[:3]) or "all seen"))

    # The ladder: every stage a pod reaches is in its PM's view the next morning.
    unseen = []
    for e in stages:
        n = names[e["pod_id"]]
        _, row = _first_view_after(firm, n, e["_id"])
        if row is None or row["stage"] != e["to"]:
            unseen.append(f"{n} {e['to']} (saw {row and row['stage']})")
    check("A9: every step of the risk ladder (halved, reduce-only, closed) is in the PM's capital "
          "view the next morning", bool(stages) and not unseen,
          ", ".join(f"{names[e['pod_id']]} {e['to']}" for e in stages) + (
              f"; UNSEEN {unseen}" if unseen else ""))

    # Closed: the dead pod's PM is told why at every door it tries.
    told = {}
    for n in ("sink", "crash"):
        mandate = firm.client.get("/mandate", headers=h(key[n]))
        order = firm.client.post("/orders", headers=h(key[n]), json={
            "ticker": f"{FOUNDING[n]}00", "side": "buy", "qty": 1, "price_type": "market",
            "justification": "trying again"})
        book_ = firm.client.get(f"/portfolio/{ids[n]}", headers=h(key[n])).json()
        again = firm.pitch(n, FOUNDING[n])
        told[n] = {"mandate": mandate.status_code == 409 and "closed" in mandate.json()["detail"],
                   "order": order.status_code == 403 and "closed" in json.dumps(order.json()),
                   "book": book_["positions"] == [],
                   "pitch": "closed" in (again.get("capital") or {}).get("reason", "")}
    check("A9: a closed pod's PM is told 'closed' by its mandate, its orders and its pitches, and "
          "reads an empty book", all(all(t.values()) for t in told.values()),
          "; ".join(f"{n}: " + ", ".join(f"{k} {'told' if v else 'NOT TOLD'}" for k, v in t.items())
                    for n, t in told.items()))
    capital_hire = [hire["capital"].get("hiring") for hire in firm.hired.values()]
    check("A9: a hired PM reads the dead pod's post-mortem and the hiring law on its first morning",
          bool(firm.hired) and all(hire["read"].get("post_mortem") for hire in firm.hired.values())
          and all(capital_hire), f"{len(firm.hired)} hire(s)")


def _snapshot(s) -> dict:
    return {"cash": sorted((c.pod_id, round(c.balance, 6)) for c in s.scalars(select(CashBalance))),
            "positions": sorted((p.pod_id, p.ticker, round(p.qty, 9), round(p.avg_cost, 9))
                                for p in s.scalars(select(Position))),
            "pods": sorted((p.id, p.name, p.status, round(p.current_allocation, 6))
                           for p in s.scalars(select(Pod)))}


def report_checks(firm: Firm) -> dict:
    """A8: the quarter report, as the operator prints it, against an independent sum of the money."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fund_env(["quarter-report", "--json"])
    with session_scope() as s:
        direct = quarter_report(s, provider=get_provider())
        # The pods' money, counted apart from the report: cash plus every holding at today's close.
        now = ledger_now(s)
        held = sum(c.balance for c in s.scalars(select(CashBalance))) + sum(
            p.qty * get_provider().get_price(p.ticker, as_of=now).price
            for p in s.scalars(select(Position)))
    rep = json.loads(out.getvalue()) if code == 0 else {}
    check("A8: the operator prints the quarter report (fund-env quarter-report), from the ledger",
          code == 0 and rep == _jsonish(direct), f"exit {code}")
    if not rep:
        return {}
    pods = {p["name"]: p for p in rep["pods"]}
    # Money is kept: the firm's last-day equity is the centre's cash plus every pod's cash and
    # holdings (counted apart), and it is the firm's capital plus every pod's gross P&L.
    firm_end = rep["firm"][-1]
    made = sum(p["pnl_gross_usd"] for p in rep["pods"])
    check("A8: money is kept: the firm's last-day equity is the centre's cash plus the pods' cash "
          "and holdings, and its capital plus every pod's P&L",
          abs(firm_end - (rep["centre"][-1] + held)) < 1.0
          and abs(firm_end - (rep["firm_capital_usd"] + made)) < 1.0,
          f"${firm_end:,.0f} = ${rep['centre'][-1]:,.0f} + ${held:,.0f} = "
          f"${rep['firm_capital_usd']:,.0f} + ${made:,.0f}")
    weeks = len(rep["weeks"])
    check("A8: the report holds every week of the quarter, each pod's P&L gross and net of "
          "thinking, the deaths and the hires",
          rep["weeks"][0] == rep["opened_on"] and rep["weeks"][-1] == rep["today"]
          and weeks >= QUARTER // 7
          and all(abs(p["pnl_net_usd"] - (p["pnl_gross_usd"] - p["thinking_usd"])) < 1e-6
                  for p in rep["pods"])
          and pods["sink"]["closed_on"] and pods["crash"]["closed_on"]
          and "hired" in pods["hire-1"]["origin"] and pods["noise"]["put_in_usd"] == 0,
          f"{weeks} columns; {len(rep['happened'])} happenings")
    return rep


def _jsonish(doc):
    return json.loads(json.dumps(doc, default=str))


# --- B: the quarter as a hosted world, lived by the Runtime ---------------------------------------

#: The hosted world's key (ADR-045: never in the cassette; whoever verifies must know it).
KEY = hashlib.sha256(b"fund-firm-quarter/1").hexdigest()
DAYS_PER_STEP = 3
STEPS = QUARTER // DAYS_PER_STEP
WORLD = {"start": f"{START.isoformat()}T14:30:00Z", "admin": "quarter-mgmt",
         "pods": [{"name": name, "allocation": 0} for name in FOUNDING],
         "market": MARKET.model_dump(mode="json"),
         "laws": {"capital": {"tell_pms": True}, "hiring": {"max_live_pods": LIMIT}}}
PM_TOOLS = ["whoami", "get_clock", "run_research_backtest", "list_research_backtests",
            "submit_pitch", "list_pitches", "get_capital", "get_mandate", "place_order",
            "get_portfolio"]


def write_world(directory: Path, provider: str) -> None:
    """The hosted run's files: the world, the input, the four PMs, the hiring template."""
    (directory / "specs").mkdir(parents=True, exist_ok=True)
    (directory / "world.json").write_text(json.dumps(WORLD))
    rules = {}
    if provider == "scripted":   # the scripted PMs pitch their sector; the hires, F and G
        rules = {f"{name}-pm": rule(fam) for name, fam in FOUNDING.items()}
        rules |= {f"hire-{n}-pm": rule(fam) for n, fam in HIRES.items()}
    (directory / "input.json").write_text(json.dumps({
        "sectors": {f"{name}-pm": [f"{FOUNDING[name]}{k:02d}"
                                   for k in range(FAMILIES[FOUNDING[name]][0])]
                    for name in FOUNDING},
        "unheld": [f"{fam}{k:02d}" for fam in HIRES.values() for k in range(FAMILIES[fam][0])],
        "pitch_rules": rules}))
    for pod, name in enumerate(FOUNDING, start=1):
        spec = {"id": f"{name}-pm", "name": f"{name}-pm", "role": "pm", "pod": pod,
                "charter": "Pitch once, then trade the mandate."}
        spec |= ({"provider": "scripted", "script": "pitch-pm"} if provider == "scripted"
                 else {"provider": provider, "tools": PM_TOOLS})
        (directory / "specs" / f"{name}-pm.yaml").write_text(json.dumps(spec))
    hire = ({"provider": "scripted", "script": "pitch-pm"} if provider == "scripted"
            else {"provider": provider, "tools": PM_TOOLS + ["get_vacancy"]})
    (directory / "hire.yaml").write_text(json.dumps(hire))


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
    with tempfile.TemporaryDirectory(prefix="fund-firm-quarter-") as t:
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


def quarter_chain(doc: dict, label: str) -> None:
    """The quarter, as the recorded ledger tells it: who was seeded, raised, closed and hired."""
    rows = [(r[0], r[3], json.loads(r[4])) for r in (doc.get("ledger") or {}).get("rows") or []]
    of = lambda t: [(i, p) for i, t2, p in rows if t2 == t]  # noqa: E731
    pods = {k: name for k, name in enumerate(FOUNDING, start=1)}
    for _, p in of("vacancy_filled"):
        pods[p["pod_id"]] = p["pod_name"]
    seeded = {pods.get(p["pod_id"]) for _, p in of("capital_seeded")}
    closed = [(i, pods.get(p["pod_id"])) for i, p in of("pod_stage_changed") if p["to"] == "closed"]
    opened = [(i, p) for i, p in of("vacancy_opened")]
    filled = [(i, p) for i, p in of("vacancy_filled")]
    raised = [p for _, p in of("allocation_set")
              if p.get("source") == "capital" and "raise" in p["reason"]]
    run = (doc.get("outcome") or {}).get("run") or {}
    hired = [h for h in run.get("hires") or [] if h["outcome"] == "hired"]
    check(f"{label}: edge, sink and crash are seeded, noise never; sink and crash are closed",
          {"edge", "sink", "crash"} <= seeded and "noise" not in seeded
          and sorted(n for _, n in closed) == ["crash", "sink"],
          f"seeded {sorted(x for x in seeded if x)}; closed {[n for _, n in closed]}")
    check(f"{label}: each close opens a vacancy and the Runtime fills it with a new PM, who earns "
          "a seed", len(opened) == 2 and [f["vacancy_id"] for _, f in filled]
          == [i for i, _ in opened] and len(hired) == 2
          and {"hire-1", "hire-2"} <= seeded,
          ", ".join(f"{f['pod_name']} / {f['agent_name']}" for _, f in filled))
    law = (of("capital_opened") or [(0, {})])[0][1].get("law") or {}
    hiring = (opened[0][1].get("law") or {}) if opened else {}
    check(f"{label}: the world lives by its recipe's laws: PMs are told, at most {LIMIT} live pods",
          law.get("tell_pms") is True and hiring.get("max_live_pods") == LIMIT,
          f"tell_pms {law.get('tell_pms')}, max_live_pods {hiring.get('max_live_pods')}")
    check(f"{label}: the algorithm raises capital, net of thinking", bool(raised),
          f"{len(raised)} raise(s) to {sorted({pods.get(p['pod_id']) for p in raised})}")


def rehearsal() -> None:
    """B0, $0: the hosted quarter with scripted minds, recorded and verified now."""
    with tempfile.TemporaryDirectory(prefix="fund-firm-quarter-") as t:
        tmp = Path(t)
        write_world(tmp, "scripted")
        r = fund_runtime(["backtest", "--world", "world.json", "--specs", "specs", "--hire",
                          "hire.yaml", "--input", "input.json", "--steps", str(STEPS),
                          "--days-per-step", str(DAYS_PER_STEP), "--max-tool-calls", "40",
                          "--cassette", "rehearsal.cassette.json"], tmp)
        tape = tmp / "rehearsal.cassette.json"
        if not check("B0: a scripted rehearsal of the hosted quarter completes and is recorded",
                     r.returncode == 0 and tape.is_file(), f"exit {r.returncode}: "
                     f"{r.stderr.strip()[-300:] if r.returncode else 'completed'}, "
                     f"{tape.stat().st_size / 1e6:.1f} MB" if tape.is_file() else ""):
            return
        text = tape.read_text(encoding="ascii")
    quarter_chain(json.loads(text), "B0")
    verify(text, "B0")


EVIDENCE = REPO / "evidence" / "firm-quarter" / "quarter.cassette.json"


def recorded() -> None:
    """B: the recorded real quarter (real PMs, metered, inside the cap). The next session records
    it; until then this check fails: the idea is not done without real minds."""
    if not check("B: the recorded real quarter exists", EVIDENCE.is_file(),
                 str(EVIDENCE.relative_to(REPO))):
        return
    text = EVIDENCE.read_text(encoding="ascii")
    quarter_chain(json.loads(text), "B")
    verify(text, "B")


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
    rehearsal()
    recorded()
    print(f"\n{len(FAILED)} failed · {time.monotonic() - started:.0f} s")
    for name in FAILED:
        print(f"  FAILED: {name}")
    TMP.cleanup()
    return 1 if FAILED else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--write-world"]:   # the files a recorded run is made from ($0)
        write_world(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "openrouter")
        sys.exit(0)
    sys.exit(main())
