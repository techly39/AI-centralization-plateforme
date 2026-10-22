"""Acceptance demo — a manager chooses the hires: one manager mind reads every pod, picks who fills
a freed place among the hires the law allows, briefs the new PM and sets the firm's direction; it
never moves capital, hires or fires by itself.

Costs $0 and needs no network.

  A  scripted, through the app's HTTP API, on one made-up market (stdlib ``random``, one fixed
     seed), each world in its own process (its own database and laws). Three founding pods (edge
     and steady: sectors with an edge; noise), the generation and reproduction laws on. Every
     morning a stand-in for the Runtime fills each open vacancy it may, wakes the manager and each
     PM, and the meter charges their thinking. At September's end the noise PM goes.
       pick    the management law on: the freed place lists its candidates (the law's own hire,
               the fittest pod's child, first; the other fit pod's child; a plain hire on each
               model) and waits a day; the manager writes the firm's direction, picks the other
               fit pod's child with a brief, and is
               refused by name what it may not do; the next morning exactly its pick is hired
       silent  the law on, the manager says nothing: the law's own hire stands (the 'no' case)
       off     the law off: no list, no wait, a pick refused; the hire is the law's, as before
     The silent world's hire must be the off world's: silence is today's law exactly.
  B0 (next session) the same through the Runtime with the real run's very command, replay IDENTICAL
  B  (next session) a real Haiku manager over a generation run, recorded; replay for $0

    uv run python acceptance/manager_chooses_hires.py        # exit 0 = the idea works
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SEED = 7
REPRODUCTION_SEED = 11
ORIGIN = date(2023, 1, 1)
START = date(2024, 9, 1)
DAYS = 33                       # September and the first mornings of October
NOISE, PLANTED = 0.010, 0.004
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0}
#: family: (width, fate)
FAMILIES = {"K": (20, "edge"), "M": (20, "noise"), "T": (20, "edge")}
HAIKU, SONNET = "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"
POOL = (HAIKU, SONNET)
PRICE = 20.0                    # what a PM's morning of thinking costs, USD
MANAGER_PRICE = 5.0             # what the manager's morning costs, USD
GRACE = 20
FOUNDING = {"edge": HAIKU, "steady": SONNET, "noise": SONNET}
PLAN = {("edge", 0): ("K", 5), ("steady", 0): ("T", 5), ("noise", 0): ("M", 5),
        ("noise", 10): ("M", 4)}
DIRECTION = "Keep the book in the sectors that pay; fewer names beat more; cut thinking you do not use."
BRIEF = "You descend from the firm's second-fittest pod, not its fittest: test your inherited rule first."
#: name: (management law on, the manager picks)
WORLDS = {"pick": (True, True), "silent": (True, False), "off": (False, False)}

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


def of(ledger, type_: str) -> list[dict]:
    return [dict(p, _id=i, _on=d) for i, d, t, p in ledger if t == type_]


#: What a hire is, apart from the place's names, budget and charter.
FRAME = ("pod_name", "pm_name", "role", "budget_usd", "charter")


def design(hire: dict) -> dict:
    return {k: v for k, v in hire.items() if k not in FRAME}


# --- one world, in its own process --------------------------------------------------------------

def live_world(name: str) -> int:
    on, picks = WORLDS[name]
    tmp = tempfile.TemporaryDirectory(prefix="fund-manager-")
    for k in [k for k in os.environ if k.startswith("FUND_")]:
        del os.environ[k]
    os.environ.update({
        "FUND_DATABASE_URL": f"sqlite:///{Path(tmp.name) / 'fund.db'}",
        "FUND_MARKETDATA__PROVIDER": "static", "FUND_LOGGING__LEVEL": "ERROR",
        "FUND_HIRING__MAX_LIVE_PODS": "3", "FUND_HIRING__MODELS": json.dumps(list(POOL)),
        "FUND_CAPITAL__TELL_PMS": "true", "FUND_GENERATION__ON": "true",
        "FUND_GENERATION__GRACE_DAYS": str(GRACE),
        "FUND_REPRODUCTION__ON": "true", "FUND_REPRODUCTION__SEED": str(REPRODUCTION_SEED),
        "FUND_MANAGEMENT__ON": "true" if on else "false"})
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
                          days=(START - ORIGIN).days + DAYS + 5, noise=NOISE, planted=PLANTED,
                          families=[Family(prefix=p, width=w, fate=fate)
                                    for p, (w, fate) in FAMILIES.items()])
    assert fund_env(["init-db"]) == 0
    set_provider(BarsProvider(bars(market)))
    with session_scope() as s:
        start_backtest(s, start=datetime.combine(START, datetime.min.time(), UTC))
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        _, runtime = seed_runtime_agent(s)
        ids = {pod: create_pod(s, name=pod).id for pod in FOUNDING}
    client = TestClient(create_app())
    client.__enter__()
    pods: dict[str, dict] = {}
    seen: dict[str, dict] = {}       # what the hire read through its own key on its first morning
    tried: dict[str, object] = {}    # the manager's attempts at what it may not do: HTTP status
    boards: list[dict] = []

    def join(pod: str, pod_id: int, key: str, agent: int, day: int) -> None:
        pods[pod] = {"id": pod_id, "key": key, "agent": agent, "spent": 0.0, "joined": day}

    for pod, model in FOUNDING.items():
        r = client.post("/agents/register", headers=h(admin), json={
            "name": f"pm-{pod}", "role": "pm", "pod_id": ids[pod], "model": model})
        assert r.status_code == 201, r.text
        join(pod, ids[pod], r.json()["api_key"], r.json()["id"], 0)
    r = client.post("/agents/register", headers=h(admin), json={"name": "ceo", "role": "manager"})
    assert r.status_code == 201, r.text
    boss = {"key": r.json()["api_key"], "agent": r.json()["id"], "spent": 0.0}

    def charge(agent: int, key_ref: str, spent: float) -> None:
        assert client.post("/metering/usage", headers=h(runtime), json={
            "agent_id": agent, "key_ref": key_ref,
            "usd_micros_total": round(spent * 1e6)}).status_code == 200

    def hire(day: int) -> None:
        for v in client.get("/vacancies", headers=h(admin)).json():
            if v["status"] != "open":
                continue
            r = client.post(f"/vacancies/{v['id']}/fill", headers=h(admin))
            if r.status_code == 201:
                agent = r.json()["agent"]
                pod = r.json()["vacancy"]["filled"]["pod_name"]
                join(pod, agent["pod_id"], agent["api_key"], agent["id"], day)
                pods[pod]["vacancy_id"] = v["id"]
            else:
                tried.setdefault(f"fill:{v['id']}:{day}", r.status_code)

    def manage(day: int) -> None:
        boss["spent"] += MANAGER_PRICE
        charge(boss["agent"], "key-ceo", boss["spent"])
        board = client.get("/board", headers=h(boss["key"])).json()
        boards.append(board)
        if picks and board["direction"] is None:
            assert client.post("/direction", headers=h(boss["key"]),
                               json={"text": DIRECTION}).status_code == 201
        for v in board["open_vacancies"]:
            if not picks or v["picked"] is not None:
                continue
            tried["pick_not_listed"] = client.post(
                f"/vacancies/{v['id']}/pick", headers=h(boss["key"]),
                json={"candidate": "c9", "brief": "x"}).status_code
            other = next((c["id"] for c in v["candidates"] if not c["default"]
                          and c["what"].startswith("a child of")), None)
            r = client.post(f"/vacancies/{v['id']}/pick", headers=h(boss["key"]),
                            json={"candidate": other, "brief": BRIEF})
            assert r.status_code == 200, r.text
            tried["second_pick"] = client.post(
                f"/vacancies/{v['id']}/pick", headers=h(boss["key"]),
                json={"candidate": "c1"}).status_code
        if day == 1:     # what the manager may not do, each refused by name
            some_pm = pods["noise"]["agent"]
            for what, path, body in (
                    ("register", "/agents/register", {"name": "x", "role": "pm",
                                                      "pod_id": pods["noise"]["id"]}),
                    ("deactivate", f"/agents/{some_pm}/deactivate", None),
                    ("trade", "/orders", {"ticker": "K00", "side": "buy", "qty": 1,
                                          "price_type": "market", "justification": "x"}),
                    ("pitch", "/pitches", {"hypothesis": "x", "data_needed": "x", "team": "x",
                                           "budget_usd": 0.0, "rule": rule("K", 5)})):
                tried[what] = client.post(path, headers=h(boss["key"]), json=body).status_code
            tried["pm_reads_board"] = client.get("/board",
                                                 headers=h(pods["noise"]["key"])).status_code
            tried["pm_sets_direction"] = client.post(
                "/direction", headers=h(pods["noise"]["key"]), json={"text": "x"}).status_code

    def pitch(pod: str, what) -> None:
        r = client.post("/pitches", headers=h(pods[pod]["key"]), json={
            "hypothesis": "Slow diffusion of information: recent winners keep winning.",
            "data_needed": "daily prices", "team": "the PM alone", "budget_usd": 0.0,
            "rule": rule(*what)})
        assert r.status_code == 201, r.text

    def wake(pod: str, day: int) -> None:
        p = pods[pod]
        if client.get("/me", headers=h(p["key"])).status_code == 401:
            return                  # let go: it never wakes again
        p["spent"] += PRICE
        charge(p["agent"], f"key-{pod}", p["spent"])
        if day == p["joined"] and "vacancy_id" in p:
            seen[pod] = {
                "vacancy": client.get(f"/vacancies/{p['vacancy_id']}", headers=h(p["key"])).json(),
                "capital": client.get("/capital", headers=h(p["key"])).json()}
            inherited = seen[pod]["vacancy"]["hire"].get("inherited_rule")
            if inherited:
                r = client.post("/pitches", headers=h(p["key"]), json={
                    "hypothesis": "My family's rule.", "data_needed": "daily prices",
                    "team": "the PM alone", "budget_usd": 0.0, "rule": inherited})
                assert r.status_code == 201, r.text
        if (pod, day - p["joined"]) in PLAN and "vacancy_id" not in p:
            pitch(pod, PLAN[(pod, day - p["joined"])])
        r = client.get("/mandate", headers=h(p["key"]))
        if r.status_code == 200:
            for order in r.json()["orders"]:
                client.post("/orders", headers=h(p["key"]), json={
                    "ticker": order["ticker"], "side": order["side"], "qty": order["qty"],
                    "price_type": "market", "justification": "my rule's rebalance"})

    try:
        for day in range(DAYS):
            hire(day)
            manage(day)
            for pod in list(pods):
                wake(pod, day)
            r = client.post("/clock/advance", headers=h(runtime), json={"days": 1})
            assert r.status_code == 200, r.text
        filled = [v for v in client.get("/vacancies", headers=h(admin)).json()
                  if v["status"] == "filled"]
        if filled:   # a pick after the hire, and the manager filling or refusing a place itself
            tried["pick_unlisted_place" if not on else "pick_after_fill"] = client.post(
                f"/vacancies/{filled[0]['id']}/pick", headers=h(boss["key"]),
                json={"candidate": "c1"}).status_code
            tried["manager_fills"] = client.post(f"/vacancies/{filled[0]['id']}/fill",
                                                 headers=h(boss["key"])).status_code
            tried["manager_refuses"] = client.post(f"/vacancies/{filled[0]['id']}/refuse",
                                                   headers=h(boss["key"]),
                                                   json={"reason": "x"}).status_code
        # every PM still working reads the direction (if one was written) in its capital view
        tried["direction_read_by"] = sorted(
            pod for pod, p in pods.items() if client.get("/me", headers=h(p["key"])).status_code
            == 200 and (client.get("/capital", headers=h(p["key"])).json().get("direction")
                        or {}).get("text") == DIRECTION)
        tried["working"] = sorted(pod for pod, p in pods.items()
                                  if client.get("/me", headers=h(p["key"])).status_code == 200)
        final_board = client.get("/board", headers=h(boss["key"])).json()
        with session_scope() as s:
            ledger = [(e.id, e.ts.date().isoformat(), e.type, e.payload_json)
                      for e in s.scalars(select(Event).order_by(Event.id))]
            tried["acts"] = sorted({e.type for e in s.scalars(select(Event).where(
                Event.actor_agent_id == boss["agent"]))})
        CHECKS[name](ledger, pods, seen, tried, boards, final_board, boss)
        rebuilt(name)
    finally:
        client.__exit__(None, None, None)
        set_provider(None)
    return 0 if not FAILED else 1


# --- what each world must show ------------------------------------------------------------------

def the_vacancy(ledger) -> dict:
    """The noise pod's vacancy (the only one of these months), as opened."""
    opened = [v for v in of(ledger, "vacancy_opened") if v["pod_name"] == "noise"]
    return opened[0] if len(opened) == 1 else {}


def facts(ledger) -> None:
    """What main compares across worlds: the hire each world made into noise's place."""
    v = the_vacancy(ledger)
    filled = next((p for p in of(ledger, "vacancy_filled") if p["vacancy_id"] == v.get("_id")),
                  None)
    picked = next((p for p in of(ledger, "hire_picked") if p["vacancy_id"] == v.get("_id")), None)
    hire = v.get("hire") or {}
    if picked is not None:
        hire = {**{k: hire[k] for k in FRAME},
                **next(c["hire"] for c in v["candidates"] if c["id"] == picked["candidate"])}
    print("FACTS " + json.dumps({"hire": hire, "opened_on": v.get("_on"),
                                 "filled_on": (filled or {}).get("_on")}, sort_keys=True))


def thinking_lawful(ledger, label: str, final_board: dict, boss: dict) -> None:
    gens = of(ledger, "generation_ended")
    rows = gens[0]["pods"] if gens else []
    # each PM is charged PRICE a morning it is awake, the manager MANAGER_PRICE: a pod whose
    # thinking held a manager's dollar would not be a whole number of PM mornings
    whole = lambda usd: abs(usd / PRICE - round(usd / PRICE)) < 1e-9  # noqa: E731
    check(f"{label}: the manager's thinking is the centre's: the board's centre holds every "
          "dollar of it, and no pod's month or board row counts any",
          abs(final_board["centre"]["thinking_usd"] - boss["spent"]) < 1e-6 and bool(rows)
          and all(whole(r["thinking_usd"]) for r in rows)
          and all(whole(p["thinking_usd"]) for p in final_board["pods"]),
          f"centre ${final_board['centre']['thinking_usd']:,.2f} (the manager spent "
          f"${boss['spent']:,.2f}); September's pods: "
          + ", ".join(f"{r['pod_name']} ${r['thinking_usd']:,.0f}" for r in rows))


def board_shows_every_pod(boards: list[dict], label: str) -> None:
    first = boards[0] if boards else {}
    keys = {"cash_usd", "positions", "gross_exposure", "net_exposure", "capital_from_centre_usd",
            "stage", "drawdown", "thinking_usd", "last_generation", "design"}
    later = next((b for b in boards if any(p["positions"] for p in b["pods"])), {})
    check(f"{label}: the manager's board shows every pod: cash, positions, exposures, capital from "
          "the centre, stage, drawdown, thinking cost, last month's fitness, design",
          sorted(p["pod_name"] for p in first.get("pods", [])) == sorted(FOUNDING)
          and all(keys <= set(p) for p in first["pods"]) and bool(later),
          "; ".join(f"{p['pod_name']}: cash ${p['cash_usd']:,.0f}, {len(p['positions'])} "
                    f"names, gross {p['gross_exposure'] if p['gross_exposure'] is None else round(p['gross_exposure'], 2)}, "
                    f"from the centre {p['capital_from_centre_usd']}, {p['design']['model']}"
                    for p in later.get("pods", [])))


def listed_lawfully(ledger, label: str) -> dict:
    """The freed place's list, checked against the month's table and the law (written apart)."""
    v = the_vacancy(ledger)
    listed = v.get("candidates") or []
    gens = of(ledger, "generation_ended")
    rows = gens[0]["pods"] if gens else []
    fit = sorted((r for r in rows if r["verdict"] in ("stays", "too_new")
                  and r["fitness_usd"] is not None and r["fitness_usd"] > 0),
                 key=lambda r: (-r["fitness_usd"], r["pod_id"]))
    parents = [(c["hire"].get("parent") or {}).get("pod_name") for c in listed]
    plain = [c["hire"]["model"] for c in listed if c["hire"].get("design") == "plain"]
    check(f"{label}: the place freed at September's end lists every hire the law allows: the law's "
          "own first (a child of the fittest), a child of the other fit pod, a plain hire on each "
          "model of the pool",
          len(fit) == 2 and listed and listed[0]["default"] and listed[0]["id"] == "c1"
          and design(v["hire"]) == listed[0]["hire"]
          and parents[:2] == [fit[0]["pod_name"], fit[1]["pod_name"]]
          and plain == list(POOL) and sum(c["default"] for c in listed) == 1,
          "; ".join(f"{c['id']}{' (default)' if c['default'] else ''}: {c['what']}"
                    for c in listed) or "no list")
    bad = []
    for c in listed:
        hire = c["hire"]
        if hire.get("design") != "child":
            continue
        p, ch, mine = hire["parent"], hire["change"], hire["inherited_rule"]
        diffs = [k for k in set(p["rule"] or {}) | set(mine or {})
                 if (p["rule"] or {}).get(k) != (mine or {}).get(k)]
        diffs += ["model"] if p["model"] != hire["model"] else []
        family = {p["pod_id"]}
        tries = sum(1 for t in ("research_backtest_run", "pitch_submitted") for e in of(ledger, t)
                    if e["pod_id"] in family and e["_id"] < v["_id"])
        if diffs != [ch["what"]] or hire["lineage_attempts"] != tries or p["model"] is None:
            bad.append(f"{c['id']}: differs in {diffs}, change {ch['what']}; attempts "
                       f"{hire['lineage_attempts']} vs {tries}")
    check(f"{label}: each child on the list is its parent's model and rule with exactly the one "
          "change it names, and carries its family's attempts", not bad,
          "; ".join(bad) or "each child exact")
    return v


def waited(ledger, label: str, v: dict) -> None:
    filled = next((p for p in of(ledger, "vacancy_filled") if p["vacancy_id"] == v.get("_id")),
                  None)
    day = (date.fromisoformat(v["_on"]) + timedelta(days=1)).isoformat() if v else None
    check(f"{label}: the place waits one day for the manager: the fill is not taken on the morning "
          "it opens and is made the next", v.get("fill_from") == day and filled is not None
          and filled["_on"] == day and not of(ledger, "hire_refused"),
          f"opened {v.get('_on')}, fill from {v.get('fill_from')}, filled "
          f"{(filled or {}).get('_on')}")


def check_pick(ledger, pods, seen, tried, boards, final_board, boss) -> None:
    board_shows_every_pod(boards, "pick")
    v = listed_lawfully(ledger, "pick")
    waited(ledger, "pick", v)
    picked = of(ledger, "hire_picked")
    other = next((c for c in v.get("candidates", []) if c["id"] == "c2"), {})
    second = (other.get("hire", {}).get("parent") or {}).get("pod_name")
    check("pick: the manager picked the other fit pod's child, not the law's own hire, with a "
          "brief (the 'yes' case)", len(picked) == 1 and picked[0]["candidate"] == "c2"
          and picked[0]["brief"] == BRIEF and picked[0]["by_name"] == "ceo"
          and second is not None and not other.get("default"),
          f"{[(p['candidate'], p['by_name']) for p in picked]}: {other.get('what')}")
    hired = next((name for name, p in pods.items() if p.get("vacancy_id") == v.get("_id")), None)
    read = seen.get(hired, {})
    hire = (read.get("vacancy") or {}).get("hire") or {}
    capital = read.get("capital") or {}
    check("pick: the next morning exactly the pick is hired: its design under the place's names, "
          "budget and charter", hired is not None and design(hire) == other.get("hire")
          and all(hire.get(k) == v["hire"][k] for k in FRAME),
          f"{hired}: {hire.get('design')} of {(hire.get('parent') or {}).get('pod_name')}, on "
          f"{hire.get('model')}, change {(hire.get('change') or {}).get('what')}")
    family = ((capital.get("generation") or {}).get("your_pod") or {}).get("family") or {}
    check("pick: the new PM reads, through its own key, its brief, the firm's direction and its "
          f"parent ({second})", (capital.get("brief") or {}).get("text") == BRIEF
          and (capital.get("direction") or {}).get("text") == DIRECTION
          and (family.get("parent") or {}).get("pod_name") == second,
          f"brief: {(capital.get('brief') or {}).get('text')!r}; direction: "
          f"{(capital.get('direction') or {}).get('text')!r}")
    check("pick: every PM still working reads the firm's direction in its capital view",
          bool(tried.get("working")) and tried.get("direction_read_by") == tried.get("working"),
          f"read by {tried.get('direction_read_by')}")
    refused = {p["candidate"]: p["reason"] for p in of(ledger, "hire_pick_refused")}
    check("pick: refused by name and written in the ledger: a pick not on the list, a second pick, "
          "a pick after the hire",
          (tried.get("pick_not_listed"), tried.get("second_pick"), tried.get("pick_after_fill"))
          == (409, 409, 409) and len(refused) == 2
          and len(of(ledger, "hire_pick_refused")) == 3,
          "; ".join(p["reason"] for p in of(ledger, "hire_pick_refused")))
    denied = [p for p in of(ledger, "permission_denied")]
    check("pick: the manager may not register, deactivate, trade, pitch, fill or refuse a place, "
          "and a PM may not read the board or set the direction: each refused (403) and logged",
          all(tried.get(k) == 403 for k in ("register", "deactivate", "trade", "pitch",
                                            "manager_fills", "manager_refuses", "pm_reads_board",
                                            "pm_sets_direction")) and len(denied) >= 8,
          ", ".join(f"{k} {tried.get(k)}" for k in ("register", "deactivate", "trade", "pitch",
                                                     "manager_fills", "manager_refuses",
                                                     "pm_reads_board", "pm_sets_direction")))
    check("pick: the manager moved no money and made no one: its only acts in the ledger are its "
          "picks, its direction and its refusals",
          set(tried.get("acts") or []) <= {"hire_picked", "hire_pick_refused", "direction_set",
                                            "permission_denied"},
          f"its acts: {tried.get('acts')}")
    thinking_lawful(ledger, "pick", final_board, boss)
    facts(ledger)


def check_silent(ledger, pods, seen, tried, boards, final_board, boss) -> None:
    v = listed_lawfully(ledger, "silent")
    waited(ledger, "silent", v)
    hired = next((name for name, p in pods.items() if p.get("vacancy_id") == v.get("_id")), None)
    hire = ((seen.get(hired) or {}).get("vacancy") or {}).get("hire") or {}
    capital = (seen.get(hired) or {}).get("capital") or {}
    check("silent: the manager said nothing: the law's own hire (a child of the fittest) is hired "
          "(the 'no' case)", not of(ledger, "hire_picked") and hired is not None
          and hire == v["hire"] and hire.get("design") == "child",
          f"{hired}: {hire.get('design')} of {(hire.get('parent') or {}).get('pod_name')}")
    check("silent: no brief and no direction in the new PM's capital view",
          bool(capital) and "brief" not in capital and "direction" not in capital)
    thinking_lawful(ledger, "silent", final_board, boss)
    facts(ledger)


def check_off(ledger, pods, seen, tried, boards, final_board, boss) -> None:
    v = the_vacancy(ledger)
    filled = next((p for p in of(ledger, "vacancy_filled") if p["vacancy_id"] == v.get("_id")),
                  None)
    check("off: with the law off the place lists no candidates and does not wait: it is filled "
          "the morning it opens", bool(v) and "candidates" not in v and "fill_from" not in v
          and "management" not in v and filled is not None and filled["_on"] == v["_on"],
          f"opened {v.get('_on')}, filled {(filled or {}).get('_on')}")
    check("off: a pick is refused by name: the law was off when the place was freed",
          tried.get("pick_unlisted_place") == 409 and any(
              "lists no candidates" in p["reason"] for p in of(ledger, "hire_pick_refused")),
          f"{tried.get('pick_unlisted_place')}")
    facts(ledger)


CHECKS = {"pick": check_pick, "silent": check_silent, "off": check_off}


def rebuilt(label: str) -> None:
    from sqlalchemy import select

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
    check(f"{label}: rebuilding from the ledger gives the same cash, positions, pods",
          before == after)


# --- B0: the generation months hosted, lived by the Runtime, a manager mind among the minds ------

def _dr():
    sys.path.insert(0, str(REPO / "acceptance"))
    import designs_reproduce as dr
    return dr


#: The hosted world: the generation-turnover months, the reproduction law (its second edition:
#: a family's attempts) and the management law on, and the firm's manager among the minds.
REPRODUCTION_LAW = {"on": True, "seed": REPRODUCTION_SEED, "edition": 2}
MANAGEMENT_LAW = {"on": True}
MANAGER = "ceo"
MANAGER_TOOLS = ["whoami", "get_clock", "read_board", "get_vacancy", "pick_hire",
                 "get_direction", "set_direction"]
MANAGER_CHARTER = (
    "You are ceo, the manager of a hedge fund that trades a simulated market with fake money. "
    "Several pods, each run by its own PM, compete for the firm's capital; an algorithm, not you, "
    "moves the capital, and the laws, not you, let a PM go. Your board (read_board) shows every "
    "pod: its cash, positions, exposures, the capital the centre put in, its risk stage and "
    "drawdown, what its thinking costs and last month's fitness (its P&L net of thinking), and "
    "its design (model, family). When a place is freed, its vacancy lists every hire the law "
    "allows (candidates c1, c2, ...; c1 is the law's own choice) and waits one day for you: you "
    "may pick one with pick_hire and write a brief for the new PM, once; if you say nothing, c1 "
    "is hired. You may write the firm's direction (set_direction): every PM reads it. You cannot "
    "trade, pitch, hire, fire or move capital. Your thinking is paid by the firm's centre: be "
    "brief. You remember nothing between days: read the board first. When you are done, stop.")
REAL_MANAGER_BUDGET_USD = 0.30
#: The rehearsal's scripted manager: it writes the direction and picks c2 for every listed place
#: (a place whose list has no c2 refuses it by name; the law's own hire then stands).
REHEARSAL_MANAGER = {"pick": "c2", "brief": BRIEF, "direction": DIRECTION}


def command(cassette: str) -> list[str]:
    return _dr().command(cassette)


def write_world(directory: Path, provider: str) -> None:
    """The hosted run's files: the generation-turnover world, both laws on, and the manager."""
    dr = _dr()
    dr.write_world(directory, provider)
    doc = json.loads((directory / "world.json").read_text())
    doc["laws"]["reproduction"] = REPRODUCTION_LAW
    doc["laws"]["management"] = MANAGEMENT_LAW
    (directory / "world.json").write_text(json.dumps(doc))
    given = json.loads((directory / "input.json").read_text())
    if provider == "fake-metered":
        given["manager"] = REHEARSAL_MANAGER
    (directory / "input.json").write_text(json.dumps(given))
    spec = {"id": MANAGER, "name": MANAGER, "role": "manager", "charter": MANAGER_CHARTER,
            "tools": MANAGER_TOOLS}
    spec |= ({"provider": "fake-metered", "script": "firm-manager",
              "budget_usd": dr._gt().REHEARSAL_BUDGET_USD} if provider == "fake-metered"
             else {"provider": provider, "model": HAIKU, "budget_usd": REAL_MANAGER_BUDGET_USD})
    (directory / "specs" / f"{MANAGER}.yaml").write_text(json.dumps(spec))


def settings(rec: dict, label: str) -> None:
    """The run is the one this idea describes: written before the real run, passed first by the
    rehearsal made with the very command."""
    gt = _dr()._gt()
    params = rec.get("parameters") or {}
    laws = (((rec.get("world") or {}).get("recipe") or {}).get("laws") or {})
    check(f"{label}: the run is the one this idea describes: {gt.STEPS} steps of "
          f"{gt.DAYS_PER_STEP} days, thinking charged each step, {_dr().MAX_TOOL_CALLS} tool calls "
          "a wake, the generation, reproduction (second edition) and management laws on",
          (params.get("steps"), params.get("days_per_step"), params.get("charge_each_step"),
           params.get("max_tool_calls"), laws.get("reproduction"), laws.get("management"),
           (laws.get("generation") or {}).get("on"))
          == (gt.STEPS, gt.DAYS_PER_STEP, True, _dr().MAX_TOOL_CALLS, REPRODUCTION_LAW,
              MANAGEMENT_LAW, True),
          f"{params.get('steps')} steps of {params.get('days_per_step')} days, charged "
          f"{params.get('charge_each_step')}, {params.get('max_tool_calls')} tool calls a wake, "
          f"reproduction {laws.get('reproduction')}, management {laws.get('management')}")


def hosted_lawful(rec: dict, label: str) -> list[dict]:
    """Whatever the manager chose, physics answered by the law (written before the real run was
    seen): every freed place listed and waited; a pick was taken only from its list, once, before
    the fill, by the manager; each fill hired exactly the pick, or the law's own hire when none;
    the new PM was handed its brief; the manager's thinking was the centre's; it made no one,
    moved no money. Returns the listed vacancies, each with what became of it."""
    dr = _dr()
    rows = rec["ledger"]["rows"]
    ledger = [(r[0], r[1][:10], r[3], json.loads(r[4])) for r in rows]
    actor = {r[0]: r[2] for r in rows}
    run = (rec.get("outcome") or {}).get("run") or {}
    agents = dict(run.get("agents") or [])
    boss = agents.get(MANAGER)
    opened = of(ledger, "vacancy_opened")
    filled = {p["vacancy_id"]: p for p in of(ledger, "vacancy_filled")}
    picks = of(ledger, "hire_picked")
    refusals = of(ledger, "hire_pick_refused")
    out, bad = [], []
    for v in opened:
        listed = v.get("candidates") or []
        mine = [p for p in picks if p["vacancy_id"] == v["_id"]]
        fill = filled.get(v["_id"])
        if not listed or v.get("fill_from") is None:
            bad.append(f"vacancy {v['vacancy_no']}: not listed")
            continue
        if listed[0]["hire"] != design(v["hire"]) or not listed[0]["default"]:
            bad.append(f"vacancy {v['vacancy_no']}: c1 is not the law's own hire")
        if len(mine) > 1 or any(p["candidate"] not in {c["id"] for c in listed} for p in mine):
            bad.append(f"vacancy {v['vacancy_no']}: picks {[p['candidate'] for p in mine]}")
        if any(actor[p["_id"]] != boss for p in mine):
            bad.append(f"vacancy {v['vacancy_no']}: a pick not the manager's")
        if fill is not None:
            if fill["_on"] < v["fill_from"]:
                bad.append(f"vacancy {v['vacancy_no']}: filled {fill['_on']} before "
                           f"{v['fill_from']}")
            if any(p["_id"] > fill["_id"] for p in mine):
                bad.append(f"vacancy {v['vacancy_no']}: a pick taken after the fill")
        want = (next(c["hire"] for c in listed if c["id"] == mine[0]["candidate"])
                if mine and (fill is None or mine[0]["_id"] < fill["_id"]) else listed[0]["hire"])
        spec = next((sp for sp, a in agents.items() if fill and a == fill["agent_id"]), None)
        first = next((w for st in run.get("steps") or [] for w in st["wakes"]
                      if w["spec_id"] == spec and w.get("transcript")), None)
        given = dr.first_input(first) or {}
        if fill is not None:
            # the hire's design is what its first wake was handed and its PM was registered as
            hired = {k: given.get(k) for k in ("parent", "change", "inherited_rule")
                     if k in want}
            if hired != {k: want[k] for k in hired} or (
                    bool(mine) != ("brief" in given)
                    or (mine and (given.get("brief") or {}).get("text") != mine[0]["brief"])):
                bad.append(f"vacancy {v['vacancy_no']}: its hire was not handed its pick or brief")
        out.append({"vacancy_no": v["vacancy_no"], "pod_name": v["pod_name"],
                    "listed": [c["id"] + ("*" if c["default"] else "") for c in listed],
                    "picked": mine[0]["candidate"] if mine else None,
                    "brief": mine[0]["brief"] if mine else None,
                    "hired": None if fill is None else fill["pod_name"],
                    "design": want.get("design"),
                    "parent": (want.get("parent") or {}).get("pod_name"),
                    "model": want.get("model")})
    refused_lawfully = all(
        r["reason"] and actor[r["_id"]] == boss and (
            r["candidate"] not in {c["id"] for v in opened if v["_id"] == r["vacancy_id"]
                                   for c in v.get("candidates") or []}
            or any(p["vacancy_id"] == r["vacancy_id"] and p["_id"] < r["_id"] for p in picks)
            or (filled.get(r["vacancy_id"]) or {}).get("_id", 1e18) < r["_id"])
        for r in refusals)
    check(f"{label}: every freed place listed the law's hires (c1 the law's own) and waited a day; "
          "every pick was the manager's, from its list, once, before the fill; each fill hired "
          "exactly the pick (or c1 when none) and handed the new PM its brief",
          bool(opened) and not bad and refused_lawfully,
          "; ".join(f"vacancy {o['vacancy_no']} ({o['pod_name']}): list {o['listed']}, picked "
                    f"{o['picked']}, hired {o['hired']} = {o['design']}"
                    + (f" of {o['parent']}" if o["parent"] else "") + f" on {o['model']}"
                    for o in out) + f"; {len(refusals)} pick(s) refused by name"
          + (f"; BAD {bad}" if bad else "") + ("" if refused_lawfully else "; BAD refusal"))
    acts = sorted({t for i, _, t, _ in ledger if actor[i] == boss and boss is not None})
    check(f"{label}: the manager moved no money and made no one: its only acts are picks, "
          "directions, refusals and its own reports",
          boss is not None and set(acts) <= {"hire_picked", "hire_pick_refused",
                                             "direction_set", "permission_denied",
                                             "task_reported", "cost_reported"},
          f"its acts: {acts}")
    costs = [p for p in of(ledger, "cost_metered") if p.get("agent_id") == boss]
    check(f"{label}: the manager's thinking was metered as the run lived and is the centre's (no "
          "pod holds it)", bool(costs) and all(p.get("pod_id") is None for p in costs),
          f"{len(costs)} cost rows, ${max((p['usd_micros_total'] for p in costs), default=0) / 1e6:.3f}")
    return out


def rehearsal() -> None:
    """B0, $0: the hosted months with scripted minds (the manager among them) billed per step,
    made with the real run's very command, recorded and verified now."""
    dr, gt = _dr(), _dr()._gt()
    with tempfile.TemporaryDirectory(prefix="fund-manager-") as t:
        tmp = Path(t)
        write_world(tmp, "fake-metered")
        r = gt.fund_runtime(command("rehearsal.cassette.json"), tmp)
        tape = tmp / "rehearsal.cassette.json"
        if not check("B0: a scripted rehearsal of the hosted months, a manager among the minds, "
                     "completes and is recorded", r.returncode == 0 and tape.is_file(),
                     f"exit {r.returncode}: "
                     f"{r.stderr.strip()[-300:] if r.returncode else 'completed'}"):
            return
        text = tape.read_text(encoding="ascii")
    rec = json.loads(text)
    settings(rec, "B0")
    before = len(gt.FAILED)
    gt.lawful(rec, "B0")         # the generation law still holds, a manager or not
    FAILED.extend(gt.FAILED[before:])
    done = hosted_lawful(rec, "B0")
    check("B0: the scripted manager picked a hire that is not the law's own, and it was hired",
          any(o["picked"] not in (None, "c1") and o["hired"] for o in done),
          ", ".join(f"vacancy {o['vacancy_no']}: {o['picked']}" for o in done))
    ledger = [(r[0], r[1][:10], r[3], json.loads(r[4])) for r in rec["ledger"]["rows"]]
    said = of(ledger, "direction_set")
    check("B0: the manager wrote the firm's direction once", len(said) == 1
          and said[0]["text"] == DIRECTION, f"{len(said)} direction(s)")
    before = len(gt.FAILED)
    gt.verify(text, "B0")
    FAILED.extend(gt.FAILED[before:])


EVIDENCE = REPO / "evidence" / "manager-chooses-hires" / "manager.cassette.json"


def recorded() -> None:
    check("B: the recorded real run exists", EVIDENCE.is_file(), str(EVIDENCE.relative_to(REPO)))


# --- the demo -----------------------------------------------------------------------------------

def main() -> int:
    seen: dict[str, dict] = {}
    for name in WORLDS:
        print(f"\nA ({name}): {DAYS} days, scripted, in its own process", flush=True)
        r = subprocess.run([sys.executable, __file__, "--world", name], cwd=REPO,
                           capture_output=True, text=True, timeout=1800)
        out = [ln for ln in r.stdout.splitlines() if not ln.startswith("FACTS ")]
        seen[name] = next((json.loads(ln[6:]) for ln in r.stdout.splitlines()
                           if ln.startswith("FACTS ")), {})
        print("\n".join(out))
        if r.returncode != 0:
            fails = [ln for ln in out if ln.startswith("[FAIL]")]
            FAILED.extend(fails or [f"world {name}: exit {r.returncode}"])
            if not fails:
                print(r.stderr.strip()[-2000:])
    silent, off = seen.get("silent", {}).get("hire"), seen.get("off", {}).get("hire")
    check("A: a silent manager leaves exactly today's law: the silent world hires the very design "
          "the law-off world hires", silent is not None and silent == off,
          f"silent {design(silent or {})}; off {design(off or {})}")
    print("\nB0: the same hosted, through the Runtime, replayed", flush=True)
    rehearsal()
    print("\nB: a real manager over a generation run, recorded", flush=True)
    recorded()
    print(f"\n{'PASS' if not FAILED else 'FAIL'}: {len(FAILED)} check(s) failed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--world"]:
        raise SystemExit(live_world(sys.argv[2]))
    if sys.argv[1:2] == ["--write-world"]:   # the files a recorded run is made from ($0)
        write_world(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "openrouter")
        print("fund-runtime " + " ".join(command("manager.cassette.json")))
        raise SystemExit(0)
    raise SystemExit(main())
