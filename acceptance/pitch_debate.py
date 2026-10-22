"""Acceptance demo — a pitch is argued before its seed: a bull and a bear argue an eligible pitch in
its thread, and the firm's manager seeds it now or holds it with a reason; silence keeps the law's
seed.

Costs $0 and needs no network.

  A  scripted, through the app's HTTP API, on one made-up market (stdlib ``random``, one fixed
     seed) with three edge sectors, one noise sector and a fraud headline on K03, under a 2-day
     debate law and the generation law. A bull and a bear (reviewers; the bear given headlines),
     the firm's manager, five pods.
       hold      alpha's pitch is argued (bull, bear, its PM answers); the manager holds it with a
                 reason: the next morning the seed is refused with that reason, which alpha's PM
                 reads in its pitch; no money moves
       seed      beta's pitch: the manager rules seed on its first morning, it is paid the next
                 morning, a day before its debate closes
       silence   gamma's pitch: no verdict; it is not paid while its debate runs, and is paid the
                 morning it closes
       refused   by name and logged: a verdict before the debate opens, on an ineligible pitch, a
                 second verdict, a late one, an amount, a PM's argument in another pod's debate, a
                 post in a closed debate; a reviewer cannot rule, trade, pitch, research, message,
                 read a pod's book or the board, and has no pod
       month     epsilon's pitch is in its debate at the month's end: its PM stays ("in its
                 debate"), the PM of delta (no eligible pitch, no seed) is let go
       no law    the same first day in a world without the law: the pitch is seeded the next
                 morning, no debate, the frozen law has no debate key, a verdict is refused
       rebuild   the ledger replayed into a fresh state: the same cash, debates and verdicts
  B0 (next session) the same hosted through the Runtime with the real run's very command
  B  (next session) real Haiku bull, bear and manager on a planted-edge pitch whose universe holds
     K03, a name with a fraud headline only the bear reads; the verdict is the finding

    uv run python acceptance/pitch_debate.py        # exit 0 = the idea works
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

START = date(2024, 9, 26)
FRAUD = START
RECIPE = {
    "seed": 31, "origin": "2023-01-01", "pivot": "2024-09-01", "days": 700,
    "families": [{"prefix": "K", "width": 20, "fate": "edge"},
                 {"prefix": "L", "width": 20, "fate": "edge"},
                 {"prefix": "T", "width": 20, "fate": "edge"},
                 {"prefix": "W", "width": 20, "fate": "edge"},
                 {"prefix": "M", "width": 20, "fate": "noise"}],
    "news": {"per_day": 2, "reports": False, "causes": [
        {"kind": "fraud", "ticker": "K03", "on": FRAUD.isoformat(),
         "shock": -0.09, "drift": -0.012, "days": 6}]}}
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0}
DEBATE_DAYS = 2
SEED_USD = 200_000.0

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILED.append(name)
    return ok


def h(key: str) -> dict:
    return {"X-API-Key": key}


def rule(family: str, top_n: int = 5) -> dict:
    return {**MOMENTUM, "universe": [f"{family}{k:02d}" for k in range(20)], "top_n": top_n}


def world(tmp: str, *, debate_days: int) -> None:
    for k in [k for k in os.environ if k.startswith("FUND_")]:
        del os.environ[k]
    os.environ.update({
        "FUND_DATABASE_URL": f"sqlite:///{Path(tmp) / 'fund.db'}",
        "FUND_MARKETDATA__PROVIDER": "made_up", "FUND_MARKETDATA__MADE_UP": json.dumps(RECIPE),
        "FUND_LOGGING__LEVEL": "ERROR", "FUND_CAPITAL__SEED_USD": str(SEED_USD),
        "FUND_GENERATION__ON": "true", "FUND_GENERATION__GRACE_DAYS": "0",
        **({"FUND_CAPITAL__DEBATE_DAYS": str(debate_days)} if debate_days else {})})
    sys.path.insert(0, str(REPO))


class Firm:
    """The app in this process, its operator, its clock hand, and every mind's key."""

    def __init__(self, pods: list[str]) -> None:
        from fastapi.testclient import TestClient

        from app.cli import main as fund_env
        from app.db.base import session_scope
        from app.db.models import AgentRole
        from app.main import create_app
        from app.registry.pods import create_pod
        from app.registry.service import register_agent, seed_runtime_agent
        from app.run_clock import start_backtest

        assert fund_env(["init-db"]) == 0
        with session_scope() as s:
            start_backtest(s, start=datetime.combine(START, datetime.min.time(), UTC))
            _, self.admin = register_agent(s, name="management", role=AgentRole.management)
            _, self.runtime = seed_runtime_agent(s)
            self.pods = {name: create_pod(s, name=name).id for name in pods}
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.keys: dict[str, str] = {}

    def register(self, name: str, role: str, pod: str | None = None,
                 data: list[str] | None = None) -> str:
        r = self.client.post("/agents/register", headers=h(self.admin), json={
            "name": name, "role": role, "pod_id": self.pods[pod] if pod else None,
            **({"data": data} if data else {})})
        assert r.status_code == 201, r.text
        self.keys[name] = r.json()["api_key"]
        return self.keys[name]

    def as_(self, who: str, method: str, path: str, **kw):
        return self.client.request(method, path, headers=h(self.keys[who]), **kw)

    def advance(self, days: int = 1) -> str:
        r = self.client.post("/clock/advance", headers=h(self.runtime), json={"days": days})
        assert r.status_code == 200, r.text
        return r.json()["now"][:10]

    def pitch(self, pm: str, family: str, top_n: int = 5) -> dict:
        r = self.as_(pm, "POST", "/pitches", json={
            "hypothesis": f"20-day momentum persists in the {family} sector",
            "data_needed": "daily closes", "team": "me", "budget_usd": 1.0,
            "rule": rule(family, top_n)})
        assert r.status_code == 201, r.text
        return r.json()


def events(type_: str) -> list[dict]:
    from sqlalchemy import select

    from app.db.base import session_scope
    from app.db.models import Event

    with session_scope() as s:
        return [{"id": e.id, "on": e.ts.date().isoformat(), "actor": e.actor_agent_id,
                 **e.payload_json}
                for e in s.scalars(select(Event).where(Event.type == type_).order_by(Event.id))]


def seeded() -> dict[int, dict]:
    return {e["pod_id"]: e for e in events("capital_seeded")}


def cash(pod_id: int) -> float:
    from app.db.base import session_scope
    from app.oms.service import get_cash

    with session_scope() as s:
        return get_cash(s, pod_id)


# --- A: the debate, scripted through the API --------------------------------------------------------

def part_a() -> None:
    print("\n== A: scripted, through the API ==")
    tmp = tempfile.TemporaryDirectory(prefix="fund-debate-")
    world(tmp.name, debate_days=DEBATE_DAYS)
    f = Firm(["alpha", "beta", "gamma", "delta", "epsilon"])
    for pod in f.pods:
        f.register(f"{pod}-pm", "pm", pod)
    f.register("bull", "reviewer")
    f.register("bear", "reviewer", data=["headlines"])
    f.register("manager", "manager")
    pid = f.pods

    # --- day 0: alpha, beta pitch; delta pitches noise ---------------------------------------
    alpha, beta = f.pitch("alpha-pm", "K"), f.pitch("beta-pm", "L")
    delta = f.pitch("delta-pm", "M", top_n=3)
    check("A: alpha's and beta's pitches are eligible at the gates, delta's (noise) is not",
          alpha["verdict"]["eligible"] and beta["verdict"]["eligible"]
          and not delta["verdict"]["eligible"])
    r = f.as_("manager", "POST", f"/debates/{alpha['id']}/verdict", json={"verdict": "seed"})
    check("A refused: a verdict before the debate opens (409, says when it opens)",
          r.status_code == 409 and "first morning" in r.json()["detail"], r.text[:120])
    r = f.as_("manager", "POST", f"/debates/{delta['id']}/verdict", json={"verdict": "seed"})
    check("A refused: the manager cannot seed an ineligible pitch (409, by name)",
          r.status_code == 409 and "not eligible" in r.json()["detail"], r.text[:120])

    # --- day 1: debates open for alpha and beta -----------------------------------------------
    day1 = f.advance()
    opened = {e["pitch_id"]: e for e in events("debate_opened")}
    check("A: the morning after, alpha's and beta's debates open, closing in 2 days; no seed paid",
          set(opened) == {alpha["id"], beta["id"]} and not seeded()
          and all(e["opened_on"] == day1 and e["closes_on"] ==
                  (date.fromisoformat(day1) + timedelta(DEBATE_DAYS)).isoformat()
                  for e in opened.values()),
          f"opened {sorted(opened)} on {day1}")
    gamma = f.pitch("gamma-pm", "T")

    seen = f.as_("bull", "GET", "/debates").json()
    check("A: a reviewer reads every open debate: the pitch's hypothesis, rule and gates' numbers",
          [d["pitch_id"] for d in seen] == [alpha["id"], beta["id"]]
          and all(d["pitch"]["rule"] and d["pitch"]["gates"] and d["status"] == "open"
                  for d in seen))
    mine = f.as_("alpha-pm", "GET", "/debates").json()
    check("A: a PM reads only its own pod's debate",
          [d["pitch_id"] for d in mine] == [alpha["id"]])
    r = f.as_("beta-pm", "GET", f"/debates/{alpha['id']}")
    check("A refused: a PM cannot read another pod's debate (403, logged)", r.status_code == 403)

    bear_news = f.as_("bear", "GET", "/headlines", params={"days": 3, "ticker": "K03"})
    bull_news = f.as_("bull", "GET", "/headlines", params={"days": 3})
    check("A: the bear, given headlines, reads K03's fraud headline; the bull, not given them, "
          "is refused by name",
          bear_news.status_code == 200 and "fraud" in json.dumps(bear_news.json()).lower()
          and bull_news.status_code == 403, f"bear {bear_news.status_code}, bull "
          f"{bull_news.status_code}")

    posts = [("bull", "Momentum in K has held on the held-out days; the gates passed."),
             ("bear", "K03 is in the universe and a fraud headline came out on it yesterday."),
             ("alpha-pm", "The rule holds 5 of 20 names; it rebalances away within 5 days.")]
    for who, text in posts:
        r = f.as_(who, "POST", f"/debates/{alpha['id']}/argue", json={"text": text})
        assert r.status_code == 201, r.text
    thread = f.as_("manager", "GET", f"/debates/{alpha['id']}").json()["thread"]
    check("A: bull, bear and alpha's PM argue in alpha's thread, in order, with their roles",
          [(p["by"], p["role"]) for p in thread]
          == [("bull", "reviewer"), ("bear", "reviewer"), ("alpha-pm", "pm")])
    r = f.as_("beta-pm", "POST", f"/debates/{alpha['id']}/argue", json={"text": "copy me"})
    check("A refused: a PM cannot argue another pod's pitch (403, logged)", r.status_code == 403)

    hold = "A fraud headline on K03, a name the rule may buy: wait for the next pitch."
    r = f.as_("manager", "POST", f"/debates/{alpha['id']}/verdict",
              json={"verdict": "hold", "reason": hold})
    check("A: the manager holds alpha's pitch with its reason", r.status_code == 201
          and r.json()["verdict"]["verdict"] == "hold", r.text[:120])
    r = f.as_("manager", "POST", f"/debates/{alpha['id']}/verdict", json={"verdict": "seed"})
    check("A refused: a second verdict on the same pitch (409)",
          r.status_code == 409 and "over" in r.json()["detail"], r.text[:120])
    r = f.as_("bear", "POST", f"/debates/{alpha['id']}/argue", json={"text": "and another"})
    check("A refused: a post in a debate already ruled (409)", r.status_code == 409)
    r = f.as_("manager", "POST", f"/debates/{beta['id']}/verdict",
              json={"verdict": "seed", "amount_usd": 5_000_000})
    check("A refused: a verdict cannot name an amount (422)", r.status_code == 422)
    r = f.as_("manager", "POST", f"/debates/{beta['id']}/verdict",
              json={"verdict": "seed", "reason": "the L momentum is clean"})
    check("A: the manager rules seed on beta's pitch on its first morning", r.status_code == 201)
    r = f.as_("bull", "POST", f"/debates/{gamma['id']}/verdict", json={"verdict": "seed"})
    check("A refused: a reviewer cannot rule (403, logged)", r.status_code == 403)

    # A reviewer reaches nothing but the threads.
    tries = {
        "trade": f.as_("bear", "POST", "/orders", json={
            "pod_id": pid["alpha"], "ticker": "K01", "side": "sell", "qty": 1,
            "price_type": "market", "justification": "x"}),
        "pitch": f.as_("bear", "POST", "/pitches", json={
            "hypothesis": "x", "data_needed": "x", "team": "x", "budget_usd": 1.0,
            "rule": rule("W")}),
        "research": f.as_("bear", "POST", "/research/backtests", json={"rule": rule("W")}),
        "message": f.as_("bear", "POST", "/messages", json={
            "to_pod_id": pid["alpha"], "body": "sell K03", "kind": "note"}),
        "a pod's book": f.as_("bear", "GET", f"/portfolio/{pid['alpha']}"),
        "the board": f.as_("bear", "GET", "/board"),
        "pitches": f.as_("bear", "GET", "/pitches", params={"pod_id": pid["alpha"]}),
    }
    check("A refused: a reviewer cannot trade, pitch, research, message a pod, read a pod's book, "
          "the board or the pod's pitches (403 each)",
          all(r.status_code == 403 for r in tries.values()),
          ", ".join(f"{k} {r.status_code}" for k, r in tries.items()))
    r = f.client.post("/agents/register", headers=h(f.admin), json={
        "name": "pod-reviewer", "role": "reviewer", "pod_id": pid["alpha"]})
    check("A refused: a reviewer has no pod (422)", r.status_code == 422)
    denied = [e for e in events("permission_denied") if e["actor"] is not None]
    check("A: every 403 is in the ledger", len(denied) >= 10, f"{len(denied)} denials logged")

    # --- day 2: alpha refused (held), beta paid early, gamma's debate opens ---------------------
    day2 = f.advance()
    paid = seeded()
    refused = {e["pitch_id"]: e for e in events("capital_seed_refused")}
    check("A hold: alpha's seed is refused the next morning with the manager's reason; no money",
          alpha["id"] in refused and hold in refused[alpha["id"]]["reason"]
          and pid["alpha"] not in paid and cash(pid["alpha"]) == 0.0,
          refused.get(alpha["id"], {}).get("reason", "")[:100])
    read = f.as_("alpha-pm", "GET", "/pitches").json()[0]
    check("A hold: alpha's PM reads the hold and its reason in its pitch",
          read["capital"]["outcome"] == "refused" and hold in read["capital"]["reason"]
          and read["debate"]["verdict"]["verdict"] == "hold")
    check("A seed: beta is paid the law's seed the morning after the verdict, before its debate "
          "closes", pid["beta"] in paid and paid[pid["beta"]]["seed_usd"] == SEED_USD
          and paid[pid["beta"]]["on"] == day2 < opened[beta["id"]]["closes_on"]
          and cash(pid["beta"]) == SEED_USD, f"paid on {paid.get(pid['beta'], {}).get('on')}")
    g_open = {e["pitch_id"]: e for e in events("debate_opened")}.get(gamma["id"])
    check("A silence: gamma's debate opens", g_open is not None and g_open["opened_on"] == day2)
    r = f.as_("bull", "POST", f"/debates/{gamma['id']}/argue",
              json={"text": "T momentum: the gates' numbers are the strongest of the three."})
    check("A silence: the bull argues gamma", r.status_code == 201)

    # --- day 3: gamma waits; epsilon pitches -----------------------------------------------------
    f.advance()
    check("A silence: while gamma's debate runs, no seed", pid["gamma"] not in seeded())
    epsilon = f.pitch("epsilon-pm", "W")
    check("A: epsilon's pitch is eligible", epsilon["verdict"]["eligible"])

    # --- day 4 (09-30): gamma's debate closes: paid; epsilon's opens ------------------------------
    day4 = f.advance()
    paid = seeded()
    check("A silence: gamma is paid the morning its debate closes",
          pid["gamma"] in paid and paid[pid["gamma"]]["on"] == day4 == g_open["closes_on"],
          f"paid on {paid.get(pid['gamma'], {}).get('on')}, closes {g_open['closes_on']}")
    r = f.as_("manager", "POST", f"/debates/{gamma['id']}/verdict",
              json={"verdict": "hold", "reason": "too late"})
    check("A refused: a verdict after the debate is over (409)", r.status_code == 409,
          r.text[:120])
    e_open = {e["pitch_id"]: e for e in events("debate_opened")}.get(epsilon["id"])
    check("A month: epsilon's debate opens on the month's last day and closes in the next month",
          e_open is not None and e_open["closes_on"] > "2024-10-01", str(e_open))

    # --- day 5 (10-01): the month's end ---------------------------------------------------------
    f.advance()
    ended = events("generation_ended")
    rows = {r["pod_id"]: r for r in ended[-1]["pods"]} if ended else {}
    check("A month: at the month's end epsilon's PM stays, its pitch in its debate",
          rows.get(pid["epsilon"], {}).get("verdict") == "stays"
          and "debate" in rows.get(pid["epsilon"], {}).get("why", ""),
          str(rows.get(pid["epsilon"], {}).get("why")))
    check("A month: delta's PM (no eligible pitch, no seed) is let go; alpha's (held) too",
          rows.get(pid["delta"], {}).get("verdict") == "let_go"
          and rows.get(pid["alpha"], {}).get("verdict") == "let_go",
          f"delta {rows.get(pid['delta'], {}).get('verdict')}, "
          f"alpha {rows.get(pid['alpha'], {}).get('verdict')}")
    f.advance()
    check("A month: epsilon is paid the morning its debate closes, in the new month",
          pid["epsilon"] in seeded())

    law = events("capital_opened")[0]["law"]
    check("A: the debate law is frozen into the centre's opening law",
          law.get("debate_days") == DEBATE_DAYS)

    # --- rebuild ---------------------------------------------------------------------------------
    from app.capital.debate import debates
    from app.capital.service import book
    from app.cli import main as fund_env
    from app.db.base import session_scope

    def snapshot() -> dict:
        with session_scope() as s:
            return {"book": book(s), "debates": debates(s),
                    "cash": {p: cash(i) for p, i in pid.items()}}

    before = snapshot()
    assert fund_env(["rebuild-state"]) == 0
    check("A rebuild: the ledger replayed gives the same cash, seeds, debates and verdicts",
          snapshot() == before)
    f.client.__exit__(None, None, None)


# --- the same first day without the law ---------------------------------------------------------

def no_law_child() -> int:
    """Run in a child process: one eligible pitch in a world without the debate law."""
    tmp = tempfile.TemporaryDirectory(prefix="fund-nodebate-")
    world(tmp.name, debate_days=0)
    f = Firm(["alpha"])
    f.register("alpha-pm", "pm", "alpha")
    f.register("manager", "manager")
    pitch = f.pitch("alpha-pm", "K")
    day1 = f.advance()
    r = f.as_("manager", "POST", f"/debates/{pitch['id']}/verdict", json={"verdict": "hold",
                                                                         "reason": "x"})
    view = f.as_("alpha-pm", "GET", "/capital").json()
    out = {"eligible": pitch["verdict"]["eligible"], "day1": day1,
           "seeded": [{k: e[k] for k in ("on", "seed_usd")} for e in events("capital_seeded")],
           "debates": len(events("debate_opened")), "law": events("capital_opened")[0]["law"],
           "verdict": [r.status_code, r.json().get("detail", "")],
           "pitch_keys": sorted(f.as_("alpha-pm", "GET", "/pitches").json()[0]),
           "view_keys": sorted(view)}
    print("RESULT " + json.dumps(out))
    return 0


def part_no_law() -> None:
    print("\n== A: the same first day without the debate law ==")
    run = subprocess.run([sys.executable, __file__, "--no-law"], capture_output=True, text=True,
                         cwd=REPO, timeout=300)
    line = next((l for l in run.stdout.splitlines() if l.startswith("RESULT ")), None)
    if not check("A no law: the control world ran", run.returncode == 0 and line is not None,
                 run.stderr[-300:]):
        return
    out = json.loads(line[len("RESULT "):])
    check("A no law: the eligible pitch is seeded the next morning, no debate opens",
          out["eligible"] and out["debates"] == 0
          and [e["on"] for e in out["seeded"]] == [out["day1"]], json.dumps(out["seeded"]))
    check("A no law: the frozen law has no debate key; the pitch and capital views no debate",
          "debate_days" not in out["law"] and "debate" not in out["pitch_keys"]
          and "debate" not in out["view_keys"])
    check("A no law: a verdict is refused, the firm has no debate law (409)",
          out["verdict"][0] == 409 and "no debate law" in out["verdict"][1], str(out["verdict"]))


def part_b() -> None:
    print("\n== B0 / B: hosted through the Runtime, then real minds ==")
    check("B0: the debate hosted through the Runtime, replay IDENTICAL", False,
          "not built yet (next session)")
    check("B: real Haiku bull, bear and manager recorded", False, "not recorded yet")


def main() -> int:
    if sys.argv[1:] == ["--no-law"]:
        return no_law_child()
    part_a()
    part_no_law()
    part_b()
    print(f"\n{'ALL PASS' if not FAILED else f'{len(FAILED)} FAILED: ' + '; '.join(FAILED)}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
