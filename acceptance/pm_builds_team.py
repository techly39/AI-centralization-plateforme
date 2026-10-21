"""Acceptance demo — a PM builds its own team: it asks for an analyst it describes (a charter in its
words, a model from the pool, a thinking budget), physics grants or refuses it by name, the
Runtime hires it the next morning into the PM's pod, and the analyst's research and thinking are
the pod's.

Costs $0 and needs no network.

  A  scripted, through the app's HTTP API, on one made-up market, each world in its own process
     (its own database and laws). Every morning a stand-in for the Runtime fills each open team
     place; the meter charges each awake mind's thinking.
       default  two pods (alpha, beta), the team law on (two analysts a pod, a $0.40 team budget,
                Haiku only), the generation law on, from 20 September to 1 October:
                  the yes case: alpha's PM asks for an analyst and it is hired the next morning;
                  the no cases: a model outside the pool, a budget past what is left, a third
                  analyst, one agent past the Human's cap: each refused by name, in the ledger;
                  the analyst is refused when it pitches, trades or asks for an analyst (403,
                  logged); it researches, reads the library, messages its PM;
                  its backtests are in the attempts alpha's pitch is judged with;
                  its thinking is in alpha's thinking at September's end (its fitness);
                  alpha's PM lets one analyst go: its key stops answering;
                  beta's PM is deactivated: its analyst goes with it, its waiting place closes;
                  a flood of messages is cut at the day's quota;
                  every consequence is visible through the minds' own tools;
                  rebuilding from the ledger gives the same books.
       off      the same firm with the team law off: a request is refused (the law is off) and
                no team place or agent appears
  B0 (next session) the same hosted through the Runtime, scripted minds, replay IDENTICAL
  B  (next session) real Haiku PMs offered a team, recorded; physics' answers checked

    uv run python acceptance/pm_builds_team.py        # exit 0 = the idea works
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
ORIGIN = date(2023, 1, 1)
START = date(2024, 9, 20)
DAYS = 11                       # to 1 October: September's end is measured
HAIKU, SONNET = "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0, "top_n": 5,
            "universe": [f"K{k:02d}" for k in range(20)]}
TEAM_BUDGET = 0.40
CHARTER = ("You are the analyst of pod alpha. Find a momentum rule on the K sector that survives "
           "the gates; backtest few, well-chosen variants and message me the best one.")

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILED.append(name)
    return ok


def h(key: str) -> dict:
    return {"X-API-Key": key}


# --- one world, in its own process --------------------------------------------------------------

def live_world(name: str) -> int:
    on = name == "default"
    tmp = tempfile.TemporaryDirectory(prefix="fund-team-")
    for k in [k for k in os.environ if k.startswith("FUND_")]:
        del os.environ[k]
    os.environ.update({
        "FUND_DATABASE_URL": f"sqlite:///{Path(tmp.name) / 'fund.db'}",
        "FUND_MARKETDATA__PROVIDER": "static", "FUND_LOGGING__LEVEL": "ERROR",
        "FUND_GENERATION__ON": "true", "FUND_GENERATION__GRACE_DAYS": "20",
        "FUND_TEAM__ON": "true" if on else "false", "FUND_TEAM__MAX_ANALYSTS": "2",
        "FUND_TEAM__BUDGET_USD": str(TEAM_BUDGET), "FUND_TEAM__MODELS": json.dumps([HAIKU])})
    sys.path.insert(0, str(REPO))

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.cli import main as fund_env
    from app.db.base import session_scope
    from app.db.models import AgentRole, Event
    from app.main import create_app
    from app.marketdata import BarsProvider, set_provider
    from app.marketdata.made_up import Family, MadeUpMarket, bars
    from app.registry import population
    from app.registry.pods import create_pod
    from app.registry.service import register_agent, seed_runtime_agent
    from app.run_clock import start_backtest

    # The Human's agent cap, as the Human's file states it, in a file this world owns.
    human = Path(tmp.name) / "human.yaml"
    population.HUMAN_FILE = human

    def cap(n: int) -> None:
        human.write_text(f"firm:\n  max_agents_total: {n}\n", encoding="utf-8")

    cap(200)
    market = MadeUpMarket(seed=SEED, origin=ORIGIN, pivot=START,
                          days=(START - ORIGIN).days + DAYS + 5, noise=0.010, planted=0.004,
                          families=[Family(prefix="K", width=20, fate="edge", rate=0.0)])
    assert fund_env(["init-db"]) == 0
    set_provider(BarsProvider(bars(market)))
    with session_scope() as s:
        start_backtest(s, start=datetime.combine(START, datetime.min.time(), UTC))
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        _, runtime = seed_runtime_agent(s)
        ids = {pod: create_pod(s, name=pod).id for pod in ("alpha", "beta")}
    client = TestClient(create_app())
    client.__enter__()
    keys: dict[str, str] = {}
    agents: dict[str, int] = {}
    spent: dict[str, float] = {}
    for pod in ids:
        r = client.post("/agents/register", headers=h(admin), json={
            "name": f"pm-{pod}", "role": "pm", "pod_id": ids[pod]})
        assert r.status_code == 201, r.text
        keys[pod], agents[pod] = r.json()["api_key"], r.json()["id"]

    def ask(who: str, *, model: str = HAIKU, budget: float = 0.15, charter: str = CHARTER):
        return client.post("/team/analysts", headers=h(keys[who]), json={
            "charter": charter, "model": model, "budget_usd": budget})

    def morning() -> list[dict]:
        """The Runtime's stand-in: fill every open team place, oldest first."""
        made = []
        for place in client.get("/team/places", headers=h(admin)).json():
            if place["status"] != "open":
                continue
            r = client.post(f"/team/places/{place['id']}/fill", headers=h(admin))
            if r.status_code == 201:
                a = r.json()["agent"]
                keys[a["name"]], agents[a["name"]] = a["api_key"], a["id"]
                made.append(r.json())
        return made

    def think(who: str, usd: float) -> None:
        spent[who] = spent.get(who, 0.0) + usd
        r = client.post("/metering/usage", headers=h(runtime), json={
            "agent_id": agents[who], "key_ref": f"key-{who}",
            "usd_micros_total": round(spent[who] * 1e6)})
        assert r.status_code == 200, r.text

    def advance() -> None:
        assert client.post("/clock/advance", headers=h(runtime),
                           json={"days": 1}).status_code == 200

    try:
        if on:
            run_default(client, h, keys, agents, ask, morning, think, advance, cap, admin, ids)
        else:
            r = ask("alpha")
            team = client.get("/team", headers=h(keys["alpha"])).json()
            check("off: a PM's request is refused, by name: the team law is off",
                  r.status_code == 409 and "team law is off" in r.json()["detail"]
                  and team["law_on"] is False and team["refused"], r.text)
            hired = morning()
            listed = client.get("/agents", headers=h(admin)).json()
            check("off: no team place is opened and no analyst appears",
                  not hired and not client.get("/team/places", headers=h(admin)).json()
                  and not any(a["role"] == "analyst" for a in listed),
                  f"{len(listed)} agents, roles {sorted({a['role'] for a in listed})}")
        with session_scope() as s:
            ledger = [(e.id, e.ts.date().isoformat(), e.type,
                       {**e.payload_json, "_actor": e.actor_agent_id})
                      for e in s.scalars(select(Event).order_by(Event.id))]
        if on:
            ledger_checks(ledger, agents)
            rebuilt()
    finally:
        client.__exit__(None, None, None)
        set_provider(None)
    return 0 if not FAILED else 1


def run_default(client, h, keys, agents, ask, morning, think, advance, cap, admin, ids) -> None:
    # Day 0, 20 September: the yes case, then the no cases.
    yes = ask("alpha")
    check("A: alpha's PM asks for an analyst (Haiku, $0.15): granted, a team place waits for the "
          "morning (the 'yes' case)", yes.status_code == 201 and yes.json()["status"] == "open"
          and yes.json()["charter"] == CHARTER, yes.text[:200])
    pool = ask("alpha", model=SONNET)
    over = ask("alpha", budget=0.30)
    check("A: a model outside the team law's pool is refused, by name",
          pool.status_code == 409 and "pool" in pool.json()["detail"], pool.text[:200])
    check("A: a budget past what is left of the pod's team budget is refused, by name "
          "($0.25 left of $0.40)", over.status_code == 409 and "$0.25 is left" in over.json()["detail"],
          over.text[:200])
    for who in ("alpha", "beta"):
        think(who, 0.02)
    advance()

    # Day 1: the morning's hire.
    hired = morning()
    a1 = hired[0]["agent"] if hired else {}
    me = client.get("/me", headers=h(keys.get(a1.get("name"), "none"))).json()
    check("A: the next morning the Runtime hires it: an analyst in alpha, its key answering",
          len(hired) == 1 and a1.get("role") == "analyst" and a1.get("pod_id") == me.get("pod_id")
          and a1.get("name") == "alpha-analyst-1" and me.get("role") == "analyst",
          f"{a1.get('name')} in pod {a1.get('pod_id')}")
    second = ask("alpha", budget=0.10, charter="Second analyst: check the first one's work.")
    third = ask("alpha", budget=0.05, charter="A third.")
    check("A: a second analyst is granted; a third is refused, by name: the pod's limit of two",
          second.status_code == 201 and third.status_code == 409
          and "already holds 2 analysts" in third.json()["detail"], third.text[:200])
    analyst = keys["alpha-analyst-1"]
    research = client.post("/research/backtests", headers=h(analyst), json={"rule": MOMENTUM})
    research2 = client.post("/research/backtests", headers=h(analyst), json={
        "rule": {**MOMENTUM, "lookback": 60}})
    check("A: the analyst researches: its backtests are its pod's, numbered among the pod's "
          "attempts", research.status_code == 201 and research2.status_code == 201
          and research2.json().get("attempt") == 2, f"{research.status_code} {research2.text[:120]}")
    pitch = client.post("/pitches", headers=h(analyst), json={
        "hypothesis": "x", "data_needed": "prices", "team": "me", "budget_usd": 0.0,
        "rule": MOMENTUM})
    order = client.post("/orders", headers=h(analyst), json={
        "ticker": "K00", "side": "buy", "qty": 1, "price_type": "market", "justification": "x"})
    hire = client.post("/team/analysts", headers=h(analyst), json={
        "charter": "an analyst of my own", "model": HAIKU, "budget_usd": 0.05})
    check("A: the analyst is refused when it pitches, trades or asks for an analyst (403 each)",
          (pitch.status_code, order.status_code, hire.status_code) == (403, 403, 403),
          f"pitch {pitch.status_code}, order {order.status_code}, request {hire.status_code}")
    lib = client.get("/library", headers=h(analyst))
    msg = client.post("/messages", headers=h(analyst), json={
        "to": f"agent:{agents['alpha']}", "body": "Lookback 20 looks best so far."})
    mine = client.get("/team", headers=h(analyst))
    check("A: the analyst reads the library, messages its PM and reads its own charter",
          lib.status_code == 200 and msg.status_code == 201 and mine.status_code == 200
          and mine.json()["places"][0]["charter"] == CHARTER,
          f"library {lib.status_code}, message {msg.status_code}, team {mine.status_code}")
    flood = [client.post("/messages", headers=h(analyst), json={
        "to": f"agent:{agents['alpha']}", "body": "x" * 9_000}).status_code for _ in range(4)]
    check("A: a flood of messages is cut at the day's quota (20 000 characters an agent a day)",
          flood == [201, 201, 429, 429], f"answers {flood}")
    for who in ("alpha", "beta"):
        think(who, 0.02)
    think("alpha-analyst-1", 0.05)
    advance()

    # Day 2: the second analyst hired; the cap's no case; alpha's PM pitches, then lets one go.
    morning()
    with_cap = len([a for a in client.get("/agents", headers=h(admin)).json()
                    if a["status"] != "inactive"])
    cap(with_cap + 1)        # room for one, not two
    first_b = ask("beta", budget=0.10, charter="Beta's analyst: research the K sector.")
    cap(with_cap)            # now not even one: the place beta was granted would pass the cap
    second_b = ask("beta", budget=0.10, charter="Beta's second analyst.")
    cap(200)
    check("A: past the Human's agent cap (the waiting places counted), a request is refused, by "
          "name", first_b.status_code == 201 and second_b.status_code == 409
          and "cap" in second_b.json()["detail"], second_b.text[:200])
    p = client.post("/pitches", headers=h(keys["alpha"]), json={
        "hypothesis": "Slow diffusion of information: recent winners keep winning.",
        "data_needed": "daily prices", "team": "my two analysts", "budget_usd": 0.25,
        "rule": MOMENTUM})
    verdict = (p.json() or {}).get("verdict") or {} if p.status_code == 201 else {}
    pod_research = client.get("/research/backtests", headers=h(keys["alpha"])).json()
    check("A: alpha's pitch is judged with its analyst's backtests in the deflated Sharpe's N",
          p.status_code == 201 and verdict.get("attempts") == len(pod_research) + 1 == 3,
          f"attempts {verdict.get('attempts')}: {len(pod_research)} research by "
          f"{sorted({r.get('agent_id') for r in pod_research})} + the pitch")
    team = client.get("/team", headers=h(keys["alpha"])).json()
    a2 = next(x for x in team["places"] if x["place_no"] == 2)
    gone = client.post(f"/team/places/{a2['id']}/let-go", headers=h(keys["alpha"]))
    after = client.get("/me", headers=h(keys["alpha-analyst-2"]))
    other = client.post(f"/team/places/{a2['id']}/let-go", headers=h(keys["beta"]))
    check("A: alpha's PM lets its second analyst go: its key stops answering; beta's PM cannot "
          "touch alpha's team", gone.status_code == 200 and gone.json()["status"] == "let_go"
          and after.status_code == 401 and other.status_code == 403,
          f"let go {gone.status_code}, its /me {after.status_code}, beta's try {other.status_code}")
    team = client.get("/team", headers=h(keys["alpha"])).json()
    check("A: alpha's PM sees its whole team through its own tool: each place's status, charter, "
          "budget and spending, the budget left, the refusals with their reasons",
          [x["status"] for x in team["places"]] == ["working", "let_go"]
          and abs(team["budget_used_usd"] - 0.15) < 1e-9
          and abs(team["budget_left_usd"] - 0.25) < 1e-9
          and abs(team["places"][0]["spent_usd"] - 0.05) < 1e-9
          and len(team["refused"]) == 3 and all(r["reason"] for r in team["refused"]),
          f"places {[(x['name'], x['status']) for x in team['places']]}, used "
          f"${team['budget_used_usd']:.2f}, left ${team['budget_left_usd']:.2f}, "
          f"{len(team['refused'])} refusals")
    for who in ("alpha", "beta"):
        think(who, 0.02)
    advance()

    # Day 3: beta's analyst hired; beta asks for another; then beta's PM is deactivated.
    morning()
    waiting = ask("beta", budget=0.10, charter="Beta's second analyst, again.")
    b1 = keys.get("beta-analyst-1", "none")
    off = client.post(f"/agents/{agents['beta']}/deactivate", headers=h(admin))
    beta = client.get("/team", headers=h(admin), params={"pod_id": ids["beta"]}).json()
    check("A: beta's PM is deactivated: its analyst goes with it (key 401) and its waiting place "
          "closes, never filled", waiting.status_code == 201 and off.status_code == 200
          and client.get("/me", headers=h(b1)).status_code == 401
          and sorted(x["status"] for x in beta["places"]) == ["closed", "let_go"],
          f"beta's places {[(x['name'], x['status'], (x['ended'] or {}).get('reason')) for x in beta['places']]}")
    forged = client.post("/agents/register", headers=h(admin), json={
        "name": "cio", "role": "management"})
    steal = client.post(f"/team/places/{waiting.json()['id']}/fill",
                        headers=h(forged.json()["api_key"]))
    check("A: a firm mind cannot fill a team place (only the operator's registrar hires)",
          steal.status_code == 403, f"{steal.status_code}")
    for _ in range(DAYS - 3):
        think("alpha", 0.02)
        think("alpha-analyst-1", 0.01)
        advance()


def ledger_checks(ledger, agents: dict) -> None:
    def of(t: str) -> list[dict]:
        return [p for _, _, ty, p in ledger if ty == t]

    gens = of("generation_ended")
    rows = {r["pod_name"]: r for r in (gens[0]["pods"] if gens else [])}
    alpha = rows.get("alpha", {})
    # The meter's last total for each of alpha's minds, summed apart from physics.
    last: dict[int, int] = {}
    for p in of("cost_metered"):
        last[p["agent_id"]] = p["usd_micros_total"]
    expected = sum(last.get(agents[w], 0) for w in ("alpha", "alpha-analyst-1",
                                                    "alpha-analyst-2")) / 1e6
    analyst_part = last.get(agents["alpha-analyst-1"], 0) / 1e6
    check("A: at September's end alpha's thinking holds its analyst's: its fitness pays for its "
          "team", bool(gens) and abs(alpha.get("thinking_usd", -1) - expected) < 1e-9
          and analyst_part > 0,
          f"alpha thought ${alpha.get('thinking_usd')} (its analysts' part ${analyst_part:.2f}); "
          f"fitness {alpha.get('fitness_usd')}")
    refused = of("team_request_refused")
    check("A: every refusal is in the ledger with its reason (pool, budget, limit, cap)",
          len(refused) == 4 and all(p["reason"] for p in refused),
          "; ".join(p["reason"][:60] for p in refused))
    denied = sorted(p["action"] for p in of("permission_denied")
                    if p["_actor"] == agents["alpha-analyst-1"])
    check("A: the analyst's refused pitch, order and request are logged",
          denied == ["place_order", "request_team", "submit_pitch"], f"logged: {denied}")


def rebuilt() -> None:
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
    check("A: rebuilding from the ledger gives the same cash, positions, pods", before == after)


# --- B0 and B: the Runtime (next session) -------------------------------------------------------

def rehearsal() -> None:
    check("B0: the team hosted through the Runtime, scripted minds, replay IDENTICAL", False,
          "not built yet: the Runtime's onboarding of team places")


def recorded() -> None:
    check("B: real Haiku PMs offered a team, recorded, physics' answers checked", False,
          "not recorded yet")


def main() -> int:
    for name in ("default", "off"):
        print(f"\nA ({name}): scripted, in its own process", flush=True)
        r = subprocess.run([sys.executable, __file__, "--world", name], cwd=REPO,
                           capture_output=True, text=True, timeout=1800)
        print(r.stdout.rstrip())
        if r.returncode != 0:
            fails = [ln for ln in r.stdout.splitlines() if ln.startswith("[FAIL]")]
            FAILED.extend(fails or [f"world {name}: exit {r.returncode}"])
            if not fails:
                print(r.stderr.strip()[-2000:])
    print("\nB0: the team hosted through the Runtime", flush=True)
    rehearsal()
    print("\nB: real PMs offered a team, recorded", flush=True)
    recorded()
    print(f"\n{'PASS' if not FAILED else 'FAIL'}: {len(FAILED)} check(s) failed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--world"]:
        raise SystemExit(live_world(sys.argv[2]))
    raise SystemExit(main())
