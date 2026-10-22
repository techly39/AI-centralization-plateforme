"""Acceptance demo — headlines and company data, handed by role: the made-up world writes dated
headlines and quarterly reports (a few planted causes among the noise), physics serves them only
on their day and only to a mind given the right, so an analyst can know what its PM does not.

Costs $0 and needs no network.

  A  scripted, through the app's HTTP API, on one made-up market (stdlib ``random``, one fixed
     seed) whose recipe has news: three noise headlines a day, a quarterly report per company,
     and two planted causes (a fraud headline on K03, an earnings miss on M05).
       look-ahead  the analyst given headlines does not find the fraud headline the day before,
                   and finds it on its day (the 'no' and the 'yes')
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
  B0 (next session) the same hosted through the Runtime with the real run's very command
  B  (next session) real Haiku minds: a PM holding K03 (prices only) and its analyst (headlines)

    uv run python acceptance/data_packages.py        # exit 0 = the idea works
"""

from __future__ import annotations

import asyncio
import json
import math
import os
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
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
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
    from app.marketdata import get_provider
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

    # --- the look-ahead law: the day before, then the day ---------------------------------------
    advance((FRAUD - START).days - 1)
    eve = get(analyst, "/headlines", days=31, ticker="K03").json()
    check("the day before, the fraud headline does not exist",
          not any("fraud" in x["title"] for x in eve["headlines"]),
          f"{eve['day']}: {len(eve['headlines'])} K03 headlines in the last 31 days, none about fraud")
    today = advance(1)
    day = get(analyst, "/headlines", days=1).json()
    fraud = [x for x in day["headlines"] if x["ticker"] == "K03" and "fraud" in x["title"]]
    check("on its day, the entitled analyst reads it",
          len(fraud) == 1 and fraud[0]["day"] == today == FRAUD.isoformat(),
          f"{today}: {len(day['headlines'])} headlines, among them “{fraud[0]['title'] if fraud else '?'}”")
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
    check("the morning's fill gives the hire its right; it reads yesterday's fraud headline",
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
    quiet = bars(MadeUpMarket.model_validate({**RECIPE, "news": None}))
    moved, still = {}, []
    for t, rows in served.items():
        plain = {b.ts.date().isoformat(): b.close for b in quiet[t]}
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


def part_b() -> None:
    print("\n== B0 / B: the Runtime and real minds ==")
    check("B0: hosted through the Runtime with the real run's command, replay IDENTICAL",
          (EVIDENCE / "rehearsal").is_dir(), "not built yet")
    check("B: real Haiku minds recorded, replay IDENTICAL for $0",
          (EVIDENCE / "cassette.json").is_file(), "not recorded yet")


def main() -> int:
    part_a()
    part_b()
    print(f"\n{'ALL PASS' if not FAILED else f'{len(FAILED)} FAILED: ' + '; '.join(FAILED)}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
