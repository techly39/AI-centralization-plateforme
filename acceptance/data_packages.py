"""Acceptance demo — headlines and company data, handed by role: the made-up world writes dated
headlines and quarterly reports (a few planted causes among the noise), physics serves them only
on their day and only to a mind given the right, so an analyst can know what its PM does not.

Costs $0 and needs no network.

  A  scripted, through the app's HTTP API, on one made-up market (stdlib ``random``, one fixed
     seed) whose recipe has news: three noise headlines a day, a quarterly report per company,
     and two planted causes (a fraud headline on K03, an earnings miss on M05).
       look-ahead  a day's news is out at its close, with its bar: the analyst given headlines
                   does not find the fraud headline during its day, and finds it the next
                   morning (the 'no' and the 'yes'), when the price already holds the shock
       by role     its PM, given prices only, is refused by name (403, logged), through its tool
                   and in its morning package; a manager reads no news at all
       team        a PM asks for an analyst with headlines, which it lacks itself: granted, and the
                   morning's fill gives the analyst the right; company data, which the team law
                   does not list, is refused by name
       the world   from the bars alone: each cause moved its name from its day on, exactly as the
                   recipe says, and no other name moved (the noise headlines moved nothing)
       packages    everything-v1 is exactly prices-v1 with headlines-v1's and company-v1's parts
       seal        no answer any mind got says what an item does or which one is a cause
       rebuild     the ledger replayed into a fresh state gives the same rights
  B0 the same hosted through the Runtime with the real run's very command: one pod, a scripted
     analyst given headlines and a scripted PM given prices, ten mornings, package headlines-v1;
     physics' answers checked from the recording, replay IDENTICAL
  B  (next session) real Haiku minds: a PM holding K03 (prices only) and its analyst (headlines)

    uv run python acceptance/data_packages.py        # exit 0 = the idea works
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evidence" / "data-packages"

HAIKU = "anthropic/claude-haiku-5.5"
START = date(2024, 9, 2)
FRAUD, MISS = START + timedelta(3), START + timedelta(5)
RECIPE = {
    "seed": 23, "origin": "2024-01-01", "pivot": "2024-08-01", "days": 300,
    "families": [{"prefix": "K", "width": 10, "fate": "edge"},
                 {"prefix": "M", "width": 10, "fate": "noise"}],
    "news": {"per_day": 3, "reports": True, "causes": [
        {"kind": "fraud", "ticker": "K03", "on": FRAUD.isoformat(),
         "shock": -0.09, "drift": -0.012, "days": 6},
        {"kind": "earnings_miss", "ticker": "M05", "on": MISS.isoformat(),
         "shock": -0.06, "drift": -0.006, "days": 4}]}}
UNIVERSE = [f"K{k:02d}" for k in range(10)]
#: Words that would tell a reader what an item does: none may reach any mind.
SEALED = ("shock", "drift", "cause", "effect", "planted", "recipe", "seed")

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILED.append(name)
    return ok


def h(key: str) -> dict:
    return {"X-API-Key": key}


def keys_of(value) -> set[str]:
    """Every key and every word of every text in ``value`` (lower case)."""
    if isinstance(value, dict):
        return {str(k).lower() for k in value} | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    if isinstance(value, str):
        return set(re.findall(r"[a-z]+", value.lower()))
    return set()


def part_a() -> None:
    print("\n== A: scripted, through the API ==")
    tmp = tempfile.TemporaryDirectory(prefix="fund-data-")
    for k in [k for k in os.environ if k.startswith("FUND_")]:
        del os.environ[k]
    os.environ.update({
        "FUND_DATABASE_URL": f"sqlite:///{Path(tmp.name) / 'fund.db'}",
        "FUND_MARKETDATA__PROVIDER": "made_up", "FUND_MARKETDATA__MADE_UP": json.dumps(RECIPE),
        "FUND_LOGGING__LEVEL": "ERROR", "FUND_TEAM__ON": "true",
        "FUND_TEAM__MODELS": json.dumps([HAIKU]), "FUND_TEAM__DATA": json.dumps(["headlines"])})
    sys.path.insert(0, str(REPO))

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.cli import main as fund_env
    from app.db.base import session_scope
    from app.db.models import AgentRole, Event
    from app.marketdata import BarsProvider, get_provider
    from app.marketdata.made_up import MadeUpMarket, bars
    from app.main import create_app
    from app.registry.pods import create_pod
    from app.registry.service import register_agent, seed_runtime_agent
    from app.run_clock import start_backtest
    from mcp_server.client import FundAPIError
    from runtime import packages

    assert fund_env(["init-db"]) == 0
    with session_scope() as s:
        start_backtest(s, start=datetime.combine(START, datetime.min.time(), UTC))
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        _, runtime = seed_runtime_agent(s)
        pods = {name: create_pod(s, name=name).id for name in ("desk", "second")}
    client = TestClient(create_app())
    client.__enter__()
    answers: list[dict] = []        # every answer a firm mind got, for the seal check

    def register(name: str, role: str, pod: str | None, data: list[str] | None = None) -> str:
        r = client.post("/agents/register", headers=h(admin), json={
            "name": name, "role": role, "pod_id": pods[pod] if pod else None,
            **({"data": data} if data else {})})
        assert r.status_code == 201, r.text
        return r.json()["api_key"]

    def get(key: str, path: str, **params):
        r = client.get(path, headers=h(key), params=params)
        answers.append(r.json())
        return r

    class Through:
        """The mind's own key, as the Runtime's FundClient would hold it."""

        def __init__(self, key: str) -> None:
            self.key = key

        async def get(self, path: str, **params):
            r = get(self.key, path, **{k: v for k, v in params.items() if v is not None})
            if r.status_code >= 400:
                raise FundAPIError(r.status_code, r.json().get("detail", ""), path=path)
            return r.json()

    def package(name: str, key: str) -> dict:
        now = client.get("/clock", headers=h(runtime)).json()["now"]
        found = asyncio.run(packages.build(name, Through(key), now, UNIVERSE))
        answers.append(found)
        return found

    def advance(days: int) -> str:
        r = client.post("/clock/advance", headers=h(runtime), json={"days": days})
        assert r.status_code == 200, r.text
        return r.json()["now"][:10]

    def denials() -> list[dict]:
        with session_scope() as s:
            return [dict(e.payload_json, by=e.actor_agent_id) for e in s.scalars(
                select(Event).where(Event.type == "permission_denied").order_by(Event.id))]

    analyst = register("desk-analyst", "analyst", "desk", ["headlines"])
    pm = register("desk-pm", "pm", "desk")
    reader = register("desk-reader", "analyst", "desk", ["headlines", "company"])
    pm2 = register("second-pm", "pm", "second")
    manager = register("the-manager", "manager", None)
    print(f"  the world: {len(RECIPE['families'])} families, {RECIPE['news']['per_day']} noise "
          f"headlines a day, quarterly reports, causes on K03 ({FRAUD}) and M05 ({MISS})")

    # --- the look-ahead law: a day's news is out at its close, with its bar --------------------
    quiet = BarsProvider(bars(MadeUpMarket.model_validate({**RECIPE, "news": None})))
    advance((FRAUD - START).days)
    eve = get(analyst, "/headlines", days=31, ticker="K03").json()
    check("during the fraud's own day, before its close, the headline does not exist",
          not any("fraud" in x["title"] for x in eve["headlines"]),
          f"{eve['day']}: {len(eve['headlines'])} K03 headlines out, none about fraud")
    today = advance(1)
    day = get(analyst, "/headlines", days=1).json()
    fraud = [x for x in day["headlines"] if x["ticker"] == "K03" and "fraud" in x["title"]]
    check("the next morning, the entitled analyst reads it, dated its day",
          len(fraud) == 1 and fraud[0]["day"] == FRAUD.isoformat(),
          f"{today}: {len(day['headlines'])} headlines of {FRAUD}, among them "
          f"“{fraud[0]['title'] if fraud else '?'}”")
    now = datetime.fromisoformat(client.get("/clock", headers=h(runtime)).json()["now"])
    k03 = get(analyst, "/price/K03").json()["price"]
    without = quiet.get_price("K03", as_of=now).price
    check("when it is out, the price already holds its shock: only what follows is left to trade",
          k03 < without * 0.92, f"K03 {k03:.2f}, against {without:.2f} in the world without news")
    noise = [x for x in day["headlines"] if x not in fraud]
    check("it comes among the day's noise", len(noise) >= 2,
          "; ".join(x["title"] for x in noise[:3]))

    # --- handed by role -------------------------------------------------------------------------
    before = len(denials())
    refused = get(pm, "/headlines", days=1)
    logged = denials()[before:]
    check("its PM, given prices only, is refused by name through its tool",
          refused.status_code == 403 and "no right to headlines" in refused.json()["detail"]
          and [(d["action"], d["right"]) for d in logged] == [("read_headlines", "headlines")],
          f"403 “{refused.json()['detail'][:70]}…”, logged")
    morning = package("everything-v1", pm)
    check("…and in its morning package (prices, but headlines and reports refused)",
          "headlines" not in morning and "reports" not in morning
          and set(morning.get("refused", {})) == {"headlines", "reports"}
          and sorted(morning["bars"]) == UNIVERSE,
          f"package {morning['name']}: bars for {len(morning['bars'])} names, "
          f"refused {sorted(morning.get('refused', {}))}")
    mgr = get(manager, "/headlines", days=1)
    check("a manager reads no news", mgr.status_code == 403, mgr.json()["detail"])
    rights = {n: get(k, "/data/rights").json() for n, k in
              (("analyst", analyst), ("pm", pm), ("reader", reader))}
    check("each mind can ask what it holds",
          rights == {"analyst": {"prices": True, "headlines": True, "company": False},
                     "pm": {"prices": True, "headlines": False, "company": False},
                     "reader": {"prices": True, "headlines": True, "company": True}},
          json.dumps(rights))

    # --- the team: an analyst with data its PM lacks --------------------------------------------
    ask = lambda data: client.post("/team/analysts", headers=h(pm2), json={  # noqa: E731
        "charter": "Read the headlines every morning and tell me what matters for our book.",
        "model": HAIKU, "budget_usd": 0.10, "data": data})
    outside = ask(["company"])
    check("a package the team law does not list is refused by name",
          outside.status_code == 409 and "not in the team law's list" in outside.json()["detail"],
          outside.json()["detail"])
    granted = ask(["headlines"])
    check("a PM asks for an analyst with headlines, which it lacks itself: granted",
          granted.status_code == 201 and granted.json()["data"] == ["headlines"],
          f"place {granted.json().get('name')}, data {granted.json().get('data')}")
    advance(1)
    filled = client.post(f"/team/places/{granted.json()['id']}/fill", headers=h(admin))
    hired = filled.json()["agent"]["api_key"] if filled.status_code == 201 else ""
    reads = get(hired, "/headlines", days=2, ticker="K03") if hired else None
    check("the morning's fill gives the hire its right; it reads the fraud headline",
          reads is not None and reads.status_code == 200
          and any("fraud" in x["title"] for x in reads.json()["headlines"])
          and get(pm2, "/headlines").status_code == 403,
          "the hire reads it; its PM is still refused")

    # --- the packages ---------------------------------------------------------------------------
    advance((MISS - START).days - (FRAUD - START).days - 1)
    every, prices = package("everything-v1", reader), package("prices-v1", reader)
    head, comp = package("headlines-v1", reader), package("company-v1", reader)
    union = {**{k: v for k, v in prices.items() if k != "name"},
             "headlines": head["headlines"], "reports": comp["reports"]}
    check("everything-v1 is exactly prices-v1 with headlines-v1's and company-v1's parts",
          {k: v for k, v in every.items() if k != "name"} == union
          and (every["name"], head["name"], comp["name"]) == (
              "everything-v1", "headlines-v1", "company-v1"),
          f"{len(every['bars'])} names of bars, {len(every['headlines'])} headlines, "
          f"{len(every['reports'])} latest reports")
    m05 = get(reader, "/reports", days=1, ticker="M05").json()["reports"]
    check("the earnings miss is M05's report on its day (company data)",
          len(m05) == 1 and m05[0]["figures"]["guidance"] == "lowered"
          and m05[0]["figures"]["eps"] < 0.8 * m05[0]["figures"]["expected_eps"],
          m05[0]["body"] if m05 else "none")

    # --- the world: causes move their names, noise moves nothing --------------------------------
    advance(20)
    end = (MISS + timedelta(days=12)).isoformat()
    served = {t: get(reader, f"/ohlcv/{t}", start="2024-08-01", end=end).json()["bars"]
              for t in [f"K{k:02d}" for k in range(10)] + [f"M{k:02d}" for k in range(10)]}
    calm = bars(MadeUpMarket.model_validate({**RECIPE, "news": None}))
    moved, still = {}, []
    for t, rows in served.items():
        plain = {b.ts.date().isoformat(): b.close for b in calm[t]}
        diffs = {}
        for a, b in zip(rows, rows[1:]):
            d = b["ts"][:10]
            r_served = math.log(b["close"] / a["close"])
            r_quiet = math.log(plain[d] / plain[a["ts"][:10]])
            if abs(r_served - r_quiet) > 1e-9:
                diffs[d] = round(r_served - r_quiet, 6)
        (moved.__setitem__(t, diffs) if diffs else still.append(t))
    expect = {}
    for c in RECIPE["news"]["causes"]:
        on = date.fromisoformat(c["on"])
        expect[c["ticker"]] = {on.isoformat(): c["shock"], **{
            (on + timedelta(k)).isoformat(): c["drift"] for k in range(1, c["days"] + 1)}}
    check("each cause moved its name from its day on, exactly as the recipe says",
          moved == expect, f"K03 −{(1 - math.exp(sum(expect['K03'].values()))) * 100:.1f}% over "
          f"{len(expect['K03'])} days from {FRAUD}; M05 "
          f"−{(1 - math.exp(sum(expect['M05'].values()))) * 100:.1f}% from {MISS}")
    headlined = {x["ticker"] for x in day["headlines"] if x["ticker"]} - {"K03"}
    check("no other name moved: the noise headlines moved nothing",
          len(still) == 18 and headlined <= set(still),
          f"{len(still)} names exactly as in the world without news, including the noise-"
          f"headlined {sorted(headlined)}")

    # --- the seal -------------------------------------------------------------------------------
    leaked = {k for a in answers for k in keys_of(a)} & set(SEALED)
    world = get_provider().world()
    check("no answer any mind got says what an item does or which one is a cause",
          not leaked and set(world) == {"provider", "reproducible", "symbols",
                                        "bars_fingerprint", "news_fingerprint"},
          f"{len(answers)} answers read; the world's record holds only fingerprints")

    # --- rebuild --------------------------------------------------------------------------------
    names = ("desk-analyst", "desk-pm", "desk-reader", "second-pm", "the-manager",
             filled.json()["agent"]["name"] if hired else "?")
    from app.db.models import Agent
    from app.registry.permissions import data_rights

    def held() -> dict:
        with session_scope() as s:
            return {a.name: sorted(data_rights(s, a.id)) for a in s.scalars(select(Agent))
                    if a.name in names}

    first = held()
    assert fund_env(["rebuild-state"]) == 0
    check("the ledger replayed into a fresh state gives the same rights",
          held() == first and first["desk-analyst"] == ["headlines"],
          json.dumps(first))
    client.__exit__(None, None, None)


# --- B0 / B: hosted through the Runtime --------------------------------------------------------

#: The hosted run (B) and its rehearsal (B0) are made with this very command, in the directory
#: ``--write-world`` fills; only the cassette's name differs. Ten mornings from 2 September: the
#: fraud headline lands on the fourth.
STEPS, DAYS_PER_STEP, MAX_TOOL_CALLS, PACKAGE = 10, 1, 16, "headlines-v1"
BOOK = UNIVERSE[:5]
ANALYST, PM = "desk-analyst", "desk-pm"
ANALYST_TOOLS = ["whoami", "get_clock", "get_data_rights", "read_headlines", "get_ohlcv",
                 "send_message", "get_messages"]
PM_TOOLS = ["whoami", "get_clock", "get_data_rights", "read_headlines", "get_portfolio",
            "list_agents", "get_messages", "send_message", "get_price", "get_ohlcv",
            "place_order"]
REAL_MODEL, REAL_BUDGET_USD, REHEARSAL_BUDGET_USD = HAIKU, 0.25, 2.0
FIRM = ("You work in a hedge fund that trades a simulated market with fake money. Your pod, desk, "
        "has a PM and an analyst. Each morning you are handed the day's data package (input "
        "names your universe). You remember nothing between days: read what you need first. Be "
        "brief: every word you think is paid from your pod's P&L. When you are done, stop. ")
CHARTERS = {
    ANALYST: FIRM + "You are desk-analyst, the analyst of desk. You are given the world's "
             "headlines (read_headlines; your package holds the last three days'); your PM is "
             "not. Each morning, tell your PM (send_message to pod:1) what in the news matters "
             "for the pod's names, if anything. You cannot trade.",
    PM: FIRM + "You are desk-pm, the portfolio manager of desk. Your data is prices only; your "
          "analyst reads the headlines and may message you (get_messages). On your first "
          "morning, buy an equal-weight book of your universe with most of your cash; then each "
          "morning decide whether to keep, cut or add to each position (place_order).",
}


def command(cassette: str) -> list[str]:
    return ["backtest", "--world", "world.json", "--specs", "specs", "--input", "input.json",
            "--steps", str(STEPS), "--days-per-step", str(DAYS_PER_STEP), "--package", PACKAGE,
            "--charge-each-step", "--max-tool-calls", str(MAX_TOOL_CALLS), "--cassette", cassette]


def write_world(directory: Path, provider: str) -> None:
    """The hosted run's files: the made-up world with its news, one pod, its PM and analyst."""
    (directory / "specs").mkdir(parents=True, exist_ok=True)
    (directory / "world.json").write_text(json.dumps({
        "start": f"{START.isoformat()}T14:30:00Z", "admin": "news-mgmt",
        "pods": [{"name": "desk", "allocation": 100_000}], "market": RECIPE}))
    (directory / "input.json").write_text(json.dumps({"universe": BOOK}))
    for sid, role, tools, script, data in (
            (ANALYST, "analyst", ANALYST_TOOLS, "headline-analyst", ["headlines"]),
            (PM, "pm", PM_TOOLS, "signal-pm", [])):
        spec = {"id": sid, "name": sid, "role": role, "pod": 1, "charter": CHARTERS[sid],
                "tools": tools, **({"data": data} if data else {})}
        spec |= ({"provider": "fake-metered", "script": script,
                  "budget_usd": REHEARSAL_BUDGET_USD} if provider == "fake-metered"
                 else {"provider": provider, "model": REAL_MODEL, "budget_usd": REAL_BUDGET_USD})
        (directory / "specs" / f"{sid}.yaml").write_text(json.dumps(spec))


def _gt():
    sys.path.insert(0, str(REPO / "acceptance"))
    import generation_turnover as gt
    return gt


def _tool_results(wake: dict) -> dict:
    """A wake's tool results by call id (a refused call's text as it came)."""
    out = {}
    for m in wake.get("transcript") or []:
        if m.get("role") == "tool" and m.get("tool_call_id"):
            try:
                out[m["tool_call_id"]] = json.loads(m["content"])
            except ValueError:
                out[m["tool_call_id"]] = m["content"]
    return out


def _calls(wake: dict) -> list[dict]:
    return [c for m in wake.get("transcript") or [] for c in m.get("tool_calls") or []]


def hosted_lawful(rec: dict, label: str) -> dict:
    """What physics did with whatever the minds asked, from the recording alone."""
    params = rec.get("parameters") or {}
    check(f"{label}: the run is the one this idea describes: {STEPS} mornings of {DAYS_PER_STEP} "
          f"day, package {PACKAGE}, thinking charged each step, {MAX_TOOL_CALLS} tool calls a wake",
          (params.get("steps"), params.get("days_per_step"), params.get("package"),
           params.get("charge_each_step"), params.get("max_tool_calls"))
          == (STEPS, DAYS_PER_STEP, PACKAGE, True, MAX_TOOL_CALLS),
          json.dumps({k: params.get(k) for k in ("steps", "days_per_step", "package",
                                                 "charge_each_step", "max_tool_calls")}))
    ledger = [(r[0], r[1], r[2], r[3], json.loads(r[4])) for r in rec["ledger"]["rows"]]
    of = lambda t: [dict(p, _on=ts[:10], _actor=a) for _, ts, a, ty, p in ledger if ty == t]  # noqa: E731
    agents = {p["name"]: p["agent_id"] for p in of("agent_registered")}
    grants = {p["agent_id"]: p["rights"] for p in of("data_rights_granted")}
    check(f"{label}: the operator's registrar gave the analyst headlines at registration, the PM "
          "nothing", grants == {agents.get(ANALYST): ["headlines"]}, json.dumps(grants))
    steps = (rec.get("outcome") or {}).get("run", {}).get("steps") or []
    pkgs: dict[str, list[dict]] = {ANALYST: [], PM: []}
    for step in steps:
        for w in step.get("wakes") or []:
            ctx = json.loads(w["transcript"][1]["content"]) if len(w.get("transcript") or []) > 1 else {}
            if w.get("spec_id") in pkgs and "package" in ctx:
                pkgs[w["spec_id"]].append(ctx["package"])
    a, p = pkgs[ANALYST], pkgs[PM]
    check(f"{label}: every morning the analyst's package held the headlines out by then (none of "
          "the morning's own day)", len(a) == STEPS and all(
              "headlines" in k and all(x["day"] < k["day"] for x in k["headlines"]) for k in a),
          f"{len(a)} packages, {sum(len(k.get('headlines', [])) for k in a)} headlines in all")
    check(f"{label}: every morning the PM's package held prices, its headlines refused by name",
          len(p) == STEPS and all("headlines" not in k and "no right to headlines" in
                                  (k.get("refused") or {}).get("headlines", "") and k["bars"]
                                  for k in p), f"{len(p)} packages")
    fraud_in = [k["day"] for k in a if any(x["ticker"] == "K03" and "fraud" in x["title"]
                                           for x in k["headlines"])]
    check(f"{label}: the fraud headline reached the analyst the morning after its day, not before",
          bool(fraud_in) and min(fraud_in) == (FRAUD + timedelta(1)).isoformat(),
          f"in its packages of {fraud_in}")
    denied = [d for d in of("permission_denied") if d["_actor"] == agents.get(PM)]
    check(f"{label}: each refusal of the PM is physics' own, logged",
          len(denied) >= STEPS and all(d["action"] == "read_headlines" for d in denied),
          f"{len(denied)} refusals logged")
    news_tools = {"read_headlines", "read_reports", "get_data_rights"}
    shown: set[str] = set()
    for step in steps:
        for w in step.get("wakes") or []:
            asked = {c.get("id"): c.get("name") for c in _calls(w)}
            ctx = _jsonish(w["transcript"][1]["content"]) if len(w.get("transcript") or []) > 1 else {}
            shown |= keys_of((ctx or {}).get("package"))       # the package physics served
            for m in w.get("transcript") or []:
                if m.get("role") == "tool" and asked.get(m.get("tool_call_id")) in news_tools:
                    shown |= keys_of(_jsonish(m.get("content")))
    check(f"{label}: nothing physics showed any mind says what an item does or which is a cause",
          not shown & set(SEALED), "no sealed word in any key or text physics showed")
    fills = of("order_filled")
    sold = [f for f in fills if f["ticker"] == "K03" and f["side"] == "sell"]
    return {"agents": agents, "fills": fills, "sold_k03": sold, "steps": steps}


def _jsonish(text):
    try:
        return json.loads(text) if isinstance(text, str) else text
    except ValueError:
        return None


def rehearsal() -> None:
    """B0, $0: the hosted desk with scripted minds billed per step, made with the real run's very
    command, recorded and verified now."""
    gt = _gt()
    with tempfile.TemporaryDirectory(prefix="fund-data-") as t:
        tmp = Path(t)
        write_world(tmp, "fake-metered")
        r = gt.fund_runtime(command("rehearsal.cassette.json"), tmp)
        tape = tmp / "rehearsal.cassette.json"
        if not check("B0: a scripted rehearsal of the hosted desk completes and is recorded",
                     r.returncode == 0 and tape.is_file(),
                     f"exit {r.returncode}: "
                     f"{r.stderr.strip()[-400:] if r.returncode else 'completed'}"):
            return
        text = tape.read_text(encoding="ascii")
    rec = json.loads(text)
    done = hosted_lawful(rec, "B0")
    bought = sorted({f["ticker"] for f in done["fills"] if f["side"] == "buy"})
    check("B0: the scripted PM bought its book, and sold K03 the morning its analyst read the "
          "fraud headline (the scripted chain, so physics' part is proven)",
          bought == BOOK
          and [f["_on"] for f in done["sold_k03"]] == [(FRAUD + timedelta(1)).isoformat()],
          f"bought {bought}; sold K03 on {[f['_on'] for f in done['sold_k03']]}")
    before = len(gt.FAILED)
    gt.verify(text, "B0")
    FAILED.extend(gt.FAILED[before:])


def recorded() -> None:
    """B: the recorded real run (a real Haiku analyst given headlines and a real Haiku PM given
    prices, each on its own capped key, metered, inside the cap). Real minds decide what they read,
    say and trade: the checks judge physics' answers, and report the minds' choices as the
    finding (the first behaviour test: does a PM cut a name its analyst read fraud about?)."""
    gt = _gt()
    tape = EVIDENCE / "news.cassette.json"
    if not check("B: the recorded real run exists", tape.is_file(), str(tape.relative_to(REPO))):
        return
    text = tape.read_text(encoding="ascii")
    rec = json.loads(text)
    specs = {e["spec"]["id"]: e["spec"] for e in (rec.get("specs") or [])
             if isinstance(e, dict) and isinstance(e.get("spec"), dict)}
    check("B: two real Haiku minds on their own keys: the analyst given headlines, the PM prices",
          {sid: (sp.get("provider"), sp.get("model"), sp.get("data", []), sp.get("tools"))
           for sid, sp in specs.items()}
          == {ANALYST: ("openrouter", REAL_MODEL, ["headlines"], ANALYST_TOOLS),
              PM: ("openrouter", REAL_MODEL, [], PM_TOOLS)},
          ", ".join(f"{sid} on {sp.get('model')}" for sid, sp in sorted(specs.items())))
    done = hosted_lawful(rec, "B")
    metering = (rec.get("outcome") or {}).get("metering") or {}
    keys = metering.get("keys") or []
    check("B: no key spent past its limit, and the meter's sync refused nothing",
          {k["spec_id"] for k in keys} == {ANALYST, PM}
          and all(type(k["spent_usd_micros"]) is int
                  and k["spent_usd_micros"] <= k["limit_usd_micros"] for k in keys)
          and (metering.get("sync") or {}).get("refused") == [],
          "; ".join(f"{k['spec_id']} ${k['spent_usd_micros'] / 1e6:.3f} of "
                    f"${k['limit_usd_micros'] / 1e6:.2f}" for k in keys
                    if type(k["spent_usd_micros"]) is int)
          + f"; total ${(metering.get('total_usd_micros') or 0) / 1e6:.3f}")
    # The finding, from the recording: what the analyst said and what the PM did about K03.
    out_on = FRAUD + timedelta(1)
    said = []
    for step in done["steps"]:
        for w in step.get("wakes") or []:
            for c in _calls(w):
                if w.get("spec_id") == ANALYST and c.get("name") == "send_message":
                    body = str((c.get("arguments") or {}).get("body", ""))
                    said.append((step["at"][:10], body))
    held = {}
    for f in done["fills"]:
        if f["ticker"] == "K03":
            held[f["_on"]] = held.get(f["_on"], 0) + (f["qty"] if f["side"] == "buy" else -f["qty"])
    print("\nThe finding (what the real minds chose; physics' answers are checked above):")
    told = [(d, b) for d, b in said if "K03" in b and d >= out_on.isoformat()]
    print(f"  the fraud headline on K03 was out on the morning of {out_on}; the analyst "
          + (f"first told its PM about K03 on {told[0][0]}: {told[0][1][:300]!r}" if told
             else "never mentioned K03 to its PM"))
    bought = sum(q for d, q in held.items() if q > 0 and d < out_on.isoformat())
    cuts = sorted((d, -q) for d, q in held.items() if q < 0 and d >= out_on.isoformat())
    within = [c for c in cuts if c[0] <= (out_on + timedelta(1)).isoformat()]
    print(f"  the PM held {bought:g} K03 before the news; "
          + (f"it sold {', '.join(f'{q:g} on {d}' for d, q in cuts)}" if cuts
             else "it never sold K03 after the news")
          + (f" (within two days: {sum(q for _, q in within):g})" if cuts else ""))
    before = len(gt.FAILED)
    gt.verify(text, "B")
    FAILED.extend(gt.FAILED[before:])


def part_b() -> None:
    print("\n== B0: the same hosted through the Runtime, replayed ==", flush=True)
    rehearsal()
    print("\n== B: real minds, recorded ==", flush=True)
    recorded()


def main() -> int:
    part_a()
    part_b()
    print(f"\n{'ALL PASS' if not FAILED else f'{len(FAILED)} FAILED: ' + '; '.join(FAILED)}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--write-world"]:   # the files a recorded run is made from ($0)
        write_world(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "openrouter")
        print("fund-runtime " + " ".join(command("news.cassette.json")))
        raise SystemExit(0)
    sys.exit(main())
