"""Acceptance demo — designs reproduce: a freed place is filled by a child of the month's fittest
pod, its parent's model and rule with one change, its parent named, and the firm watches its own
diversity.

Costs $0 and needs no network.

  A  scripted, through the app's HTTP API, on one made-up market (stdlib ``random``, one fixed
     seed), each world in its own process (its own database and laws). Every morning a stand-in
     for the Runtime hires into each open vacancy, wakes each PM whose key still answers, and the
     meter charges each awake PM's thinking ($20 a morning). The founding PMs' registrar declares
     each one's model.
       default   three months, three founding pods (edge: a sector with an edge; noise; crash: a
                 sector that crashes), the reproduction law on. The crash pod closes mid-September,
                 before any month is measured: its place gets the plain hire. At September's end the
                 noise PM goes: its place gets a child of the fittest pod (edge), with one change.
                 Each child pitches the rule it inherited first.
       collapse  two founding pods and room for two: the noise pod's place goes to edge's child,
                 so at October's end one family holds every live pod: the finding is written
       nofit     two noise pods, both let go at September's end: no pod earned more than it
                 thought, so both places get the plain hire
       off       the default world with the law off: the hires are the hiring law's, as before
  B0 the generation-turnover months hosted, through the Runtime, the law on, scripted minds:
     the hires are the fittest pod's children, each handed its parent, change and rule; the
     family tree from the recording alone; replay --verify IDENTICAL
  B  (next session) real Haiku PMs, recorded; the hires are the fittest pod's children

    uv run python acceptance/designs_reproduce.py        # exit 0 = the idea works
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SEED = 7
REPRODUCTION_SEED = 11
ORIGIN = date(2023, 1, 1)
START = date(2024, 9, 1)
NOISE, PLANTED = 0.010, 0.004
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0}
#: family: (width, fate, rate)   (crash: the day after the pivot its three falls begin)
FAMILIES = {"K": (20, "edge", 0.0), "M": (20, "noise", 0.0), "N": (20, "noise", 0.0),
            "R": (10, "crash", 15), "T": (20, "edge", 0.0), "W": (20, "edge", 0.0)}
HAIKU, SONNET = "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"
POOL = (HAIKU, SONNET)
PRICE = 20.0                    # what a morning of thinking costs, USD
GRACE = 20
INHERITED = "inherited"         # a plan entry: pitch the rule the vacancy handed you

#: name: (founding pods {pod: model}, live-pod limit, days, plan, law on)
#: plan: (pod, day of its own | "first" | a date) -> (sector, top_n) or INHERITED
DEFAULT_PLAN = {("edge", 0): ("K", 5), ("noise", 0): ("M", 5), ("noise", 10): ("M", 4),
                ("crash", 0): ("R", 5),
                ("hire-1", "first"): ("M", 5), ("hire-1", date(2024, 10, 5)): ("T", 5),
                ("hire-2", "first"): INHERITED, ("hire-2", 10): ("M", 4),
                ("hire-3", "first"): INHERITED, ("hire-3", 2): ("W", 5)}
WORLDS = {
    "default": ({"edge": HAIKU, "noise": SONNET, "crash": HAIKU}, 3, 91, DEFAULT_PLAN, True),
    "collapse": ({"edge": HAIKU, "noise": SONNET}, 2, 61,
                 {("edge", 0): ("K", 5), ("noise", 0): ("M", 5),
                  ("hire-1", "first"): INHERITED, ("hire-1", 2): ("T", 5)}, True),
    "nofit": ({"noise-a": HAIKU, "noise-b": SONNET}, 2, 30,
              {("noise-a", 0): ("M", 5), ("noise-b", 0): ("N", 5)}, True),
    "off": ({"edge": HAIKU, "noise": SONNET, "crash": HAIKU}, 3, 91, DEFAULT_PLAN, False),
}

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILED.append(name)
    return ok


def rule(family: str, top_n: int) -> dict:
    return {**MOMENTUM, "universe": [f"{family}{k:02d}" for k in range(FAMILIES[family][0])],
            "top_n": top_n}


def h(key: str) -> dict:
    return {"X-API-Key": key}


# --- one world, in its own process --------------------------------------------------------------

def live_world(name: str) -> int:
    founding, limit, days, plan, on = WORLDS[name]
    tmp = tempfile.TemporaryDirectory(prefix="fund-reproduce-")
    for k in [k for k in os.environ if k.startswith("FUND_")]:
        del os.environ[k]
    os.environ.update({
        "FUND_DATABASE_URL": f"sqlite:///{Path(tmp.name) / 'fund.db'}",
        "FUND_MARKETDATA__PROVIDER": "static", "FUND_LOGGING__LEVEL": "ERROR",
        "FUND_HIRING__MAX_LIVE_PODS": str(limit), "FUND_HIRING__MODELS": json.dumps(list(POOL)),
        "FUND_CAPITAL__TELL_PMS": "true", "FUND_GENERATION__ON": "true",
        "FUND_GENERATION__GRACE_DAYS": str(GRACE),
        "FUND_REPRODUCTION__ON": "true" if on else "false",
        "FUND_REPRODUCTION__SEED": str(REPRODUCTION_SEED)})
    sys.path.insert(0, str(REPO))

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.cli import main as fund_env
    from app.db.base import session_scope
    from app.db.models import AgentRole, Event
    from app.main import create_app
    from app.marketdata import BarsProvider, set_provider
    from app.marketdata.made_up import Family, MadeUpMarket, bars
    from app.registry.pods import create_pod
    from app.registry.service import register_agent, seed_runtime_agent
    from app.run_clock import start_backtest

    market = MadeUpMarket(seed=SEED, origin=ORIGIN, pivot=START,
                          days=(START - ORIGIN).days + days + 5, noise=NOISE, planted=PLANTED,
                          families=[Family(prefix=p, width=w, fate=fate, rate=rate)
                                    for p, (w, fate, rate) in FAMILIES.items()])
    assert fund_env(["init-db"]) == 0
    set_provider(BarsProvider(bars(market)))
    with session_scope() as s:
        start_backtest(s, start=datetime.combine(START, datetime.min.time(), UTC))
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        _, runtime = seed_runtime_agent(s)
        ids = {pod: create_pod(s, name=pod).id for pod in founding}
    client = TestClient(create_app())
    client.__enter__()
    pods: dict[str, dict] = {}
    seen: dict[str, dict] = {}       # what each hire read through its own key on its first morning

    def join(pod: str, pod_id: int, key: str, agent: int, day: int) -> None:
        pods[pod] = {"id": pod_id, "key": key, "agent": agent, "spent": 0.0, "joined": day,
                     "pitches": []}

    for pod, model in founding.items():
        r = client.post("/agents/register", headers=h(admin), json={
            "name": f"pm-{pod}", "role": "pm", "pod_id": ids[pod], "model": model})
        assert r.status_code == 201, r.text
        join(pod, ids[pod], r.json()["api_key"], r.json()["id"], 0)

    def today() -> date:
        return date.fromisoformat(client.get("/clock", headers=h(runtime)).json()["now"][:10])

    def pitch(pod: str, what) -> None:
        if what == INHERITED:
            body = seen[pod]["vacancy"]["hire"].get("inherited_rule")
            if body is None:
                return              # a plain hire inherits nothing
        else:
            body = rule(*what)
        r = client.post("/pitches", headers=h(pods[pod]["key"]), json={
            "hypothesis": "Slow diffusion of information: recent winners keep winning.",
            "data_needed": "daily prices", "team": "the PM alone", "budget_usd": 0.0,
            "rule": body})
        assert r.status_code == 201, r.text
        pods[pod]["pitches"].append(r.json())

    def hire(day: int) -> None:
        for v in client.get("/vacancies", headers=h(admin)).json():
            if v["status"] != "open":
                continue
            r = client.post(f"/vacancies/{v['id']}/fill", headers=h(admin))
            if r.status_code == 201:
                agent = r.json()["agent"]
                join(r.json()["vacancy"]["filled"]["pod_name"], agent["pod_id"],
                     agent["api_key"], agent["id"], day)
                pods[r.json()["vacancy"]["filled"]["pod_name"]]["vacancy_id"] = v["id"]

    def wake(pod: str, day: int) -> None:
        p = pods[pod]
        if client.get("/me", headers=h(p["key"])).status_code == 401:
            return                  # let go: retired, it never wakes again
        p["spent"] += PRICE
        assert client.post("/metering/usage", headers=h(runtime), json={
            "agent_id": p["agent"], "key_ref": f"key-{pod}",
            "usd_micros_total": round(p["spent"] * 1e6)}).status_code == 200
        first = day == p["joined"]
        if first and "vacancy_id" in p:
            seen[pod] = {
                "vacancy": client.get(f"/vacancies/{p['vacancy_id']}", headers=h(p["key"])).json(),
                "capital": client.get("/capital", headers=h(p["key"])).json()}
        own = day - p["joined"]
        for key in ((pod, "first") if first else None, (pod, own), (pod, today())):
            if key in plan and not (key[1] == own and first and (pod, "first") in plan):
                pitch(pod, plan[key])
        r = client.get("/mandate", headers=h(p["key"]))
        if r.status_code == 200:
            for order in r.json()["orders"]:
                client.post("/orders", headers=h(p["key"]), json={
                    "ticker": order["ticker"], "side": order["side"], "qty": order["qty"],
                    "price_type": "market", "justification": "my rule's rebalance"})

    try:
        for day in range(days):
            hire(day)
            for pod in list(pods):
                wake(pod, day)
            r = client.post("/clock/advance", headers=h(runtime), json={"days": 1})
            assert r.status_code == 200, r.text
        hire(days)                  # the morning after: the last month's freed places
        with session_scope() as s:
            ledger = [(e.id, e.ts.date().isoformat(), e.type, e.payload_json)
                      for e in s.scalars(select(Event).order_by(Event.id))]
        CHECKS[name](ledger, pods, seen)
        if name == "default":
            rebuilt_and_reported()
    finally:
        client.__exit__(None, None, None)
        set_provider(None)
    return 0 if not FAILED else 1


# --- what each world must show ------------------------------------------------------------------

LOOKBACKS = (5, 10, 20, 40, 60, 120, 250)
REBALANCES = (1, 2, 5, 10, 21, 63)


def of(ledger, type_: str) -> list[dict]:
    return [dict(p, _id=i, _on=d) for i, d, t, p in ledger if t == type_]


def one_rung(what: str, a, b) -> bool:
    """Is ``a`` -> ``b`` one step, as the law defines a step (written apart from physics)?"""
    if what == "model":
        return a != b and b in POOL
    if what == "top_n":
        return abs(a - b) == 1
    ladder = LOOKBACKS if what == "lookback" else REBALANCES
    between = [x for x in ladder if min(a, b) < x < max(a, b)]
    return a != b and b in ladder and not between


def founder_design(ledger, pod_id: int) -> tuple[str | None, dict | None]:
    model = next((p.get("model") for p in of(ledger, "agent_registered")
                  if p["pod_id"] == pod_id and p.get("model")), None)
    seed = next((p["rule"] for p in of(ledger, "capital_seeded") if p["pod_id"] == pod_id), None)
    return model, seed


def fittest(rows: list[dict]) -> dict | None:
    fit = [r for r in rows if r["verdict"] in ("stays", "too_new") and r["fitness_usd"] is not None
           and r["fitness_usd"] > 0]
    return max(fit, key=lambda r: (r["fitness_usd"], -r["pod_id"])) if fit else None


def children(ledger, label: str, pods: dict | None = None, seen: dict | None = None
             ) -> list[dict]:
    """Every child vacancy, checked against the ledger: its parent the fittest living pod of the
    generation measured before it, exactly one change one step away, the parent's attempts
    frozen; in process (``pods``, ``seen``), the child's own key showing it all and its first
    pitch counting its family's attempts."""
    gens = of(ledger, "generation_ended")
    filled = {p["vacancy_id"]: p for p in of(ledger, "vacancy_filled")}
    kids = [v for v in of(ledger, "vacancy_opened") if v["hire"].get("design") == "child"]
    for v in kids:
        hire, parent = v["hire"], v["hire"]["parent"]
        # the generation it was born of: the last one written before it, or the one being written
        # at this month's end (its vacancy comes just before its generation_ended)
        gen = next((g for g in gens if g["_id"] > v["_id"]
                    and g["generation"] == parent["generation"]), None) or next(
            (g for g in reversed(gens) if g["_id"] < v["_id"]), None)
        best = fittest(gen["pods"]) if gen else None
        model, seeded = founder_design(ledger, parent["pod_id"])
        if parent["pod_id"] in {f["pod_id"] for f in filled.values()}:   # a hired parent
            parent_hire = next(o["hire"] for o in of(ledger, "vacancy_opened")
                               if filled.get(o["_id"], {}).get("pod_id") == parent["pod_id"])
            model = parent_hire["model"]
        child = (hire["model"], hire["inherited_rule"])
        diffs = [k for k in ("lookback", "rebalance_every", "top_n", "universe", "signal",
                             "side", "gross") if (seeded or {}).get(k) != (child[1] or {}).get(k)]
        # an undeclared parent model is no design to inherit: the child's is the hiring law's
        diffs += ["model"] if model is not None and model != child[0] else []
        ch = hire["change"]
        tries = sum(1 for t in ("research_backtest_run", "pitch_submitted") for p in of(ledger, t)
                    if p["pod_id"] == parent["pod_id"] and p["_id"] < v["_id"])
        check(f"{label}: vacancy {v['vacancy_no']} ({v['pod_name']}): its hire is a child of the "
              f"fittest living pod of generation {parent['generation']}",
              best is not None and best["pod_id"] == parent["pod_id"]
              and abs(best["fitness_usd"] - parent["fitness_usd"]) < 1e-6,
              f"parent {parent['pod_name']} (fitness ${parent['fitness_usd']:,.0f}); the table's "
              f"fittest: {best and best['pod_name']}")
        check(f"{label}: ... with exactly one change from its parent's model and seeded rule, one "
              "step away", diffs == [ch["what"]] and one_rung(ch["what"], ch["from"], ch["to"])
              and model == parent["model"] and seeded == parent["rule"],
              f"{ch['what']} {ch['from']} -> {ch['to']}; differs in {diffs}")
        check(f"{label}: ... and its family's attempts frozen at its birth (the parent's research "
              "and pitches, counted apart)", hire["lineage_attempts"] == tries,
              f"{hire['lineage_attempts']} in the vacancy, {tries} in the ledger before it")
        pod = filled.get(v["_id"], {}).get("pod_name")
        if pod is None or pods is None:
            continue
        read = seen.get(pod, {})
        fam = (((read.get("capital") or {}).get("generation") or {}).get("your_pod") or {}).get(
            "family") or {}
        check(f"{label}: {pod} sees through its own key who its parent is, its change and its "
              "inherited rule (its vacancy, its capital view)",
              (read.get("vacancy") or {}).get("hire", {}).get("parent") == parent
              and fam.get("parent") == parent and fam.get("change") == ch
              and fam.get("inherited_rule") == hire["inherited_rule"]
              and fam.get("inherited_attempts") == tries,
              fam.get("note", "no family in its capital view"))
        first = (pods.get(pod, {}).get("pitches") or [None])[0]
        verdict = (first or {}).get("verdict") or {}
        own = sum(1 for t in ("research_backtest_run", "pitch_submitted") for p in of(ledger, t)
                  if p["pod_id"] == pods[pod]["id"] and p["_id"] <= (first or {}).get("id", 0))
        check(f"{label}: {pod}'s first pitch (its inherited rule) is judged with its family's "
              "attempts in the deflated Sharpe's N",
              first is not None and first["rule"] == hire["inherited_rule"]
              and verdict.get("attempts") == own + tries
              and verdict.get("inherited_attempts") == tries,
              f"attempts {verdict.get('attempts')} = its own {own} + its family's {tries}; "
              f"eligible: {verdict.get('eligible')}"
              + (f", failed {[g['gate'] for g in verdict.get('gates', []) if g['result'] == 'fail']}"
                 if verdict else ""))
    return kids


def diversity_holds(ledger, label: str) -> list[dict]:
    """Each month's end's diversity, recomputed from its own table and the ledger's families."""
    opened = {v["_id"]: v["hire"] for v in of(ledger, "vacancy_opened")}
    born = {p["pod_id"]: opened.get(p["vacancy_id"], {}) for p in of(ledger, "vacancy_filled")}

    def family(pod_id: int, name: str) -> str:
        return (born.get(pod_id, {}).get("family") or {}).get("pod_name") or name

    bad, lines = [], []
    for g in of(ledger, "generation_ended"):
        live = [r for r in g["pods"] if r["verdict"] in ("stays", "too_new")]
        fams = {family(r["pod_id"], r["pod_name"]) for r in live}
        d = g.get("diversity") or {}
        share = (max(sum(1 for r in live if family(r["pod_id"], r["pod_name"]) == f)
                     for f in fams) / len(live)) if live else None
        if (d.get("live_pods") != len(live) or len(d.get("families") or {}) != len(fams)
                or d.get("largest_share") != share
                or d.get("collapsed") != (len(live) >= 2 and len(fams) == 1)):
            bad.append(g["month"])
        lines.append(f"{g['month']}: {d.get('live_pods')} live, {d.get('designs')} designs, "
                     f"families {d.get('families')}")
    check(f"{label}: each month's end measures diversity (live pods, distinct designs, the largest "
          "family's share), recomputed apart", not bad and bool(lines),
          "; ".join(lines) + (f"; BAD {bad}" if bad else ""))
    return of(ledger, "diversity_collapsed")


def check_default(ledger, pods: dict, seen: dict) -> None:
    regs = {p["name"]: p.get("model") for p in of(ledger, "agent_registered")}
    check("default: each founding PM's model is on the record, as its registrar declared it",
          (regs.get("pm-edge"), regs.get("pm-noise"), regs.get("pm-crash")) == (HAIKU, SONNET,
                                                                               HAIKU),
          f"pm-edge {regs.get('pm-edge')}, pm-noise {regs.get('pm-noise')}, "
          f"pm-crash {regs.get('pm-crash')}")
    opened = of(ledger, "vacancy_opened")
    gens = of(ledger, "generation_ended")
    first = opened[0] if opened else {}
    check("default: the crash pod's place, freed mid-September before any month was measured, "
          "gets the plain hire", first.get("pod_name") == "crash"
          and first.get("hire", {}).get("design") == "plain" and gens
          and first["_id"] < gens[0]["_id"] and "parent" not in first.get("hire", {}),
          f"vacancy 1 opened {first.get('_on')}: {first.get('hire', {}).get('design')}")
    kids = children(ledger, "default", pods, seen)
    second = opened[1] if len(opened) > 1 else {}
    check("default: the noise pod's place, freed at September's end, gets a child of edge (the "
          "'yes' case; nofit is the 'no')", second.get("pod_name") == "noise"
          and second.get("hire", {}).get("design") == "child"
          and second["hire"]["parent"]["pod_name"] == "edge",
          f"vacancy 2: {second.get('hire', {}).get('design')} of "
          f"{second.get('hire', {}).get('parent', {}).get('pod_name')}")
    check("default: every hire under the law is named: a child or the plain hire",
          all(v["hire"].get("design") in ("child", "plain") for v in opened) and len(kids) >= 1,
          ", ".join(f"vacancy {v['vacancy_no']} ({v['pod_name']}): {v['hire']['design']}"
                    + (f" of {v['hire']['parent']['pod_name']}, {v['hire']['change']['what']} "
                       f"{v['hire']['change']['from']} -> {v['hire']['change']['to']}"
                       if v["hire"]["design"] == "child" else "") for v in opened))
    collapsed = diversity_holds(ledger, "default")
    check("default: no family holds every live pod, and no finding is written (the 'no' case)",
          not collapsed, f"{len(collapsed)} finding(s)")


def check_collapse(ledger, pods: dict, seen: dict) -> None:
    children(ledger, "collapse", pods, seen)
    collapsed = diversity_holds(ledger, "collapse")
    check("collapse: at October's end one family (edge's) holds every live pod: the finding is "
          "written", len(collapsed) == 1 and collapsed[0]["month"] == "2024-10"
          and collapsed[0]["family"] == "edge", "; ".join(c["finding"] for c in collapsed)
          or "no finding")


def check_nofit(ledger, pods: dict, seen: dict) -> None:
    gens = of(ledger, "generation_ended")
    opened = of(ledger, "vacancy_opened")
    rows = gens[0]["pods"] if gens else []
    check("nofit: at September's end no pod earned more than it thought (no fitness above zero)",
          bool(rows) and fittest(rows) is None,
          ", ".join(f"{r['pod_name']} ${r['fitness_usd']:,.0f}" for r in rows))
    check("nofit: so both freed places get the plain hire (the 'no' case), the models in turn",
          len(opened) == 2 and all(v["hire"]["design"] == "plain" and "parent" not in v["hire"]
                                   for v in opened)
          and [v["hire"]["model"] for v in opened] == [POOL[0], POOL[1]],
          ", ".join(f"vacancy {v['vacancy_no']}: {v['hire']['design']}, {v['hire']['model']}"
                    for v in opened))


def check_off(ledger, pods: dict, seen: dict) -> None:
    opened = of(ledger, "vacancy_opened")
    keys = {"pod_name", "pm_name", "role", "model", "budget_usd", "charter"}
    check("off: with the law off, every hire is the hiring law's, as before (no design, no parent, "
          "the models in turn)", len(opened) == 3
          and all(set(v["hire"]) == keys and "reproduction" not in v for v in opened)
          and [v["hire"]["model"] for v in opened] == [POOL[0], POOL[1], POOL[0]],
          ", ".join(f"vacancy {v['vacancy_no']}: {v['hire']['model']}" for v in opened))
    check("off: no month's end measures diversity, no pitch counts inherited attempts",
          all("diversity" not in g for g in of(ledger, "generation_ended"))
          and not of(ledger, "diversity_collapsed")
          and all("inherited_attempts" not in p for p in of(ledger, "pitch_judged")))


CHECKS = {"default": check_default, "collapse": check_collapse, "nofit": check_nofit,
          "off": check_off}


def rebuilt_and_reported() -> None:
    from sqlalchemy import select

    from app.capital.report import generation_report, render_generations
    from app.db.base import session_scope
    from app.db.models import CashBalance, Pod, Position
    from app.ledger.rebuild import rebuild_state

    def snap(s) -> dict:
        return {"cash": sorted((c.pod_id, round(c.balance, 6))
                               for c in s.scalars(select(CashBalance))),
                "positions": sorted((p.pod_id, p.ticker, round(p.qty, 9))
                                    for p in s.scalars(select(Position))),
                "pods": sorted((p.id, p.status, round(p.current_allocation, 6))
                               for p in s.scalars(select(Pod)))}

    with session_scope() as s:
        before = snap(s)
        rebuild_state(s)
        s.flush()
        after = snap(s)
        s.rollback()
    check("default: rebuilding from the ledger gives the same cash, positions, pods",
          before == after)
    with session_scope() as s:
        report = generation_report(s)
        text = render_generations(report)
        s.rollback()
    print("\n" + text + "\n")
    tree = {n["pod_name"]: [c["pod_name"] for c in n["children"]]
            for n in report["family_tree"]}
    check("default: the generation report shows the family tree and each month's diversity",
          bool(tree.get("edge")) and "family tree" in text and "diversity:" in text,
          f"roots and their children: {tree}")


# --- B0: the default months hosted, lived by the Runtime ----------------------------------------

def first_input(wake: dict | None) -> dict | None:
    """The ``input`` a mind was handed in its first message of a wake (a JSON document)."""
    for m in (wake or {}).get("transcript") or []:
        if m.get("role") == "user":
            try:
                return (json.loads(m["content"]) or {}).get("input")
            except (TypeError, ValueError):
                return None
    return None


def rebuilt_report(rec: dict) -> dict:
    """The generation report from a recording alone: its ledger rows into an empty database, the
    derived tables rebuilt from them (the family tree reads pods), then the report."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.capital.report import generation_report
    from app.clock import BacktestClock, get_clock, set_clock
    from app.db.base import Base
    from app.db.models import Event
    from app.ledger.rebuild import rebuild_state

    rows = (rec.get("ledger") or {}).get("rows") or []
    stamp = lambda ts: datetime.fromisoformat(ts).replace(tzinfo=UTC)  # noqa: E731
    saved = get_clock()
    with tempfile.TemporaryDirectory(prefix="fund-reproduce-report-") as t:
        engine = create_engine(f"sqlite:///{Path(t) / 'report.db'}")
        Base.metadata.create_all(engine)
        try:
            set_clock(BacktestClock(stamp(rows[-1][1])))
            with Session(engine) as s:
                for r in rows:
                    s.add(Event(id=r[0], ts=stamp(r[1]), actor_agent_id=r[2], type=r[3],
                                payload_json=json.loads(r[4])))
                s.flush()
                rebuild_state(s)
                s.flush()
                return generation_report(s)
        finally:
            set_clock(saved)
            engine.dispose()


def rehearsal() -> None:
    """B0, $0: the generation-turnover world (the same market, minds and command) with the
    reproduction law on, scripted minds billed per step, recorded and verified now."""
    sys.path.insert(0, str(REPO / "acceptance"))
    import generation_turnover as gt

    law = {"on": True, "seed": REPRODUCTION_SEED}
    with tempfile.TemporaryDirectory(prefix="fund-reproduce-") as t:
        tmp = Path(t)
        gt.write_world(tmp, "fake-metered")
        doc = json.loads((tmp / "world.json").read_text())
        doc["laws"]["reproduction"] = law
        (tmp / "world.json").write_text(json.dumps(doc))
        r = gt.fund_runtime(["backtest", "--world", "world.json", "--specs", "specs", "--hire",
                             "hire.yaml", "--input", "input.json", "--steps", str(gt.STEPS),
                             "--days-per-step", str(gt.DAYS_PER_STEP), "--charge-each-step",
                             "--cassette", "rehearsal.cassette.json"], tmp)
        tape = tmp / "rehearsal.cassette.json"
        if not check("B0: a scripted rehearsal of the hosted months, the law on, completes and is "
                     "recorded", r.returncode == 0 and tape.is_file(),
                     f"exit {r.returncode}: "
                     f"{r.stderr.strip()[-300:] if r.returncode else 'completed'}"):
            return
        text = tape.read_text(encoding="ascii")
    rec = json.loads(text)
    ledger = [(row[0], row[1][:10], row[3], json.loads(row[4])) for row in rec["ledger"]["rows"]]
    before = len(gt.FAILED)
    gt.lawful(rec, "B0")         # the generation law still holds, children or not
    FAILED.extend(gt.FAILED[before:])
    kids = children(ledger, "B0")
    check("B0: the hosted firm hired at least one child, and every hire is named child or plain",
          bool(kids) and all(v["hire"].get("design") in ("child", "plain")
                             for v in of(ledger, "vacancy_opened")),
          ", ".join(f"vacancy {v['vacancy_no']}: {v['hire'].get('design')}"
                    for v in of(ledger, "vacancy_opened")))
    filled = {p["vacancy_id"]: p["agent_name"] for p in of(ledger, "vacancy_filled")}
    agents = dict((rec["outcome"]["run"] or {}).get("agents") or [])
    told = []
    for v in kids:
        spec = next((sp for sp, a in agents.items()
                     if a == next((p["agent_id"] for p in of(ledger, "vacancy_filled")
                                   if p["vacancy_id"] == v["_id"]), None)), None)
        first = next((w for st in rec["outcome"]["run"]["steps"] for w in st["wakes"]
                      if w["spec_id"] == spec and w.get("transcript")), None)
        given = first_input(first)
        hire = v["hire"]
        told.append(filled.get(v["_id"], "?") if given is not None
                    and (given.get("parent") or {}).get("pod_id") == hire["parent"]["pod_id"]
                    and given.get("change") == hire["change"]
                    and given.get("inherited_rule") == hire["inherited_rule"]
                    and given.get("vacancy_id") == v["_id"] else None)
    check("B0: each hosted child's first wake is handed its parent, its change and its inherited "
          "rule (the very ones its vacancy holds)", bool(told) and None not in told,
          f"told: {told}")
    diversity_holds(ledger, "B0")
    report = rebuilt_report(rec)
    check("B0: the generation report from the recording alone shows the family tree",
          any(n["children"] for n in report["family_tree"]),
          "; ".join(f"{n['pod_name']} -> {[c['pod_name'] for c in n['children']]}"
                    for n in report["family_tree"]))
    before = len(gt.FAILED)
    gt.verify(text, "B0")
    FAILED.extend(gt.FAILED[before:])


# --- the demo -----------------------------------------------------------------------------------

def main() -> int:
    for name in WORLDS:
        print(f"\nA ({name}): {WORLDS[name][2]} days, scripted, in its own process", flush=True)
        r = subprocess.run([sys.executable, __file__, "--world", name], cwd=REPO,
                           capture_output=True, text=True, timeout=1800)
        print(r.stdout.rstrip())
        if r.returncode != 0:
            fails = [ln for ln in r.stdout.splitlines() if ln.startswith("[FAIL]")]
            FAILED.extend(fails or [f"world {name}: exit {r.returncode}"])
            if not fails:
                print(r.stderr.strip()[-2000:])
    print("\nB0: the default months hosted, through the Runtime, replayed", flush=True)
    rehearsal()
    print(f"\n{'PASS' if not FAILED else 'FAIL'}: {len(FAILED)} check(s) failed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--world"]:
        raise SystemExit(live_world(sys.argv[2]))
    raise SystemExit(main())
