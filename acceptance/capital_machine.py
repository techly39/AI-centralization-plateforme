"""Acceptance demo — capital follows results: eligible pods trade forward with a seed, an algorithm
moves capital to what works, and the drawdown ladder cuts what bleeds.

Costs $0 and needs no network: a made-up market (stdlib ``random``, one fixed seed), a backtest
database in a temporary directory, the app in this process (its HTTP API through a test client).

The market, five families of names. Before the pitch day every family has a planted edge (each
name's drift wanders slowly, so 20-day momentum predicts); from the pitch day on:
  P  the edge goes on                         → pod "edge"   (long the 5 best of 20)
  Q  each Q name moves exactly like its P twin  → pod "twin"   (same rule on Q: different at the
                                                  pitch, a copy of "edge" forward)
  N  pure noise, the edge is gone             → pod "faded"  (same rule on N)
  B  the whole sector collapses               → pod "bleeder" (long the 2 best of 10)
  R  the edge goes on                         → pod "shorty" (long-short on R: eligible, no seed)

  A  the pitch: every rule is eligible at the gates on the held-out days; the long-short one is
     refused a seed (the order system cannot short), the four others are seeded at the next day
  B  a hundred forward days: each seeded pod's PM (a scripted mind) sends its rule's orders through
     POST /orders; the runtime advances the clock; the machine runs at every advance
       B1 the edge's capital grows several times and is never cut
       B2 the twin is penalised for moving like the older edge pod, and does not grow like it
       B3 the faded pod is never raised and ends at or below its seed
       B4 the bleeder is halved at 5 %, made reduce-only at 7.5 % (its buy refused, 403, logged),
          closed at 10 % with every share sold and its money back; a closed pod's sell is refused
  C  reproducible: every re-weighing redone from the inputs in its event gives the same moves; a
     control with one pod's thinking cost raised scores it lower (cost 0 changes nothing);
     rebuilding from the ledger gives the same cash, positions, capital and stages
  then a plain report: the allocation table through time and the bleeder's ladder.

    uv run python acceptance/capital_machine.py        # exit 0 = the idea works
"""

from __future__ import annotations

import math
import os
import random
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory(prefix="fund-capital-machine-")
for k in [k for k in os.environ if k.startswith("FUND_")]:
    del os.environ[k]
os.environ["FUND_DATABASE_URL"] = f"sqlite:///{Path(TMP.name) / 'fund.db'}"
os.environ["FUND_MARKETDATA__PROVIDER"] = "static"
os.environ["FUND_LOGGING__LEVEL"] = "ERROR"
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402
from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.capital.allocation import PodTrack, reallocate  # noqa: E402
from app.capital.mandate import mandate_orders  # noqa: E402
from app.capital.service import book  # noqa: E402
from app.cli import main as fund_env  # noqa: E402
from app.config import CapitalConfig  # noqa: E402
from app.db.base import session_scope  # noqa: E402
from app.db.models import AgentRole, CashBalance, Event, Pod, Position  # noqa: E402
from app.ledger.rebuild import rebuild_state  # noqa: E402
from app.main import create_app  # noqa: E402
from app.marketdata import Bar, BarsProvider, set_provider  # noqa: E402
from app.registry.pods import create_pod  # noqa: E402
from app.registry.service import register_agent, seed_runtime_agent  # noqa: E402
from app.run_clock import start_backtest  # noqa: E402

SEED = 7
ORIGIN = date(2023, 1, 1)
PITCH_DAY = date(2024, 9, 1)       # the clock opens here; the gates judge the 180 days before
FORWARD = 100                      # forward days lived after the pitch
NOISE, PLANTED = 0.010, 0.004     # daily sd of the noise; stationary sd of each name's drift
MOMENTUM = {"language": "strategy-v1", "signal": "momentum", "lookback": 20,
            "rebalance_every": 5, "side": "long_only", "gross": 1.0}
PODS = {   # name: (family, top_n, side)
    "edge": ("P", 5, "long_only"), "twin": ("Q", 5, "long_only"),
    "faded": ("N", 5, "long_only"), "bleeder": ("B", 2, "long_only"),
    "shorty": ("R", 3, "long_short"),
}
WIDTH = {"P": 20, "Q": 20, "N": 20, "B": 10, "R": 20}

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)
    return ok


# --- the made-up market -------------------------------------------------------------------------

def market() -> dict[str, list[Bar]]:
    rng = random.Random(SEED)
    days = (PITCH_DAY - ORIGIN).days + FORWARD + 5
    pitch = (PITCH_DAY - ORIGIN).days
    innovation = PLANTED * math.sqrt(1 - 0.99**2)
    logret: dict[str, list[float]] = {}
    for family, width in WIDTH.items():
        for k in range(width):
            name, mu, path = f"{family}{k:02d}", rng.gauss(0, PLANTED), []
            for d in range(days):
                mu = 0.99 * mu + innovation * rng.gauss(0, 1)
                eps = rng.gauss(0, 1)
                if d < pitch or family in ("P", "R"):
                    path.append(mu + NOISE * eps)
                elif family == "N":
                    path.append(NOISE * eps)
                elif family == "B":
                    path.append(-0.006 + 0.004 * eps)
                else:  # Q: its P twin's move, from the pitch day on
                    path.append(logret[f"P{k:02d}"][d])
            logret[name] = path
    bars = {}
    for name, path in logret.items():
        price, rows = 40.0 + 3 * (sum(map(ord, name)) % 7), []
        for d, r in enumerate(path):
            opened, price = price, price * math.exp(r)
            ts = datetime.combine(ORIGIN + timedelta(d), datetime.min.time(), UTC)
            rows.append(Bar(ts=ts, open=opened, high=max(opened, price) * 1.002,
                            low=min(opened, price) * 0.998, close=price, volume=5e7 / price))
        bars[name] = rows
    return bars


# --- the run ------------------------------------------------------------------------------------

def h(key: str) -> dict:
    return {"X-API-Key": key}


def setup() -> tuple[TestClient, dict, str]:
    assert fund_env(["init-db"]) == 0
    set_provider(BarsProvider(market()))
    with session_scope() as s:
        start_backtest(s, start=datetime.combine(PITCH_DAY, datetime.min.time(), UTC))
        _, admin = register_agent(s, name="management", role=AgentRole.management)
        _, runtime = seed_runtime_agent(s)
        ids = {name: create_pod(s, name=name).id for name in PODS}
    client = TestClient(create_app())
    client.__enter__()
    pods = {}
    for name, pod_id in ids.items():
        r = client.post("/agents/register", headers=h(admin),
                        json={"name": f"pm-{name}", "role": "pm", "pod_id": pod_id})
        assert r.status_code == 201, r.text
        pods[name] = {"id": pod_id, "key": r.json()["api_key"]}
    return client, pods, runtime


def pitch(client: TestClient, pods: dict) -> None:
    verdicts = {}
    for name, (family, top_n, side) in PODS.items():
        rule = {**MOMENTUM, "universe": [f"{family}{k:02d}" for k in range(WIDTH[family])],
                "top_n": top_n, "side": side}
        r = client.post("/pitches", headers=h(pods[name]["key"]), json={
            "hypothesis": "Slow diffusion of information: recent winners keep winning.",
            "data_needed": "daily prices", "team": "the PM alone", "budget_usd": 0.0,
            "rule": rule})
        assert r.status_code == 201, r.text
        verdicts[name] = r.json()["verdict"]
    check("A: every rule is eligible at the gates on the held-out days",
          all(v["eligible"] for v in verdicts.values()),
          ", ".join(f"{n} {'eligible' if v['eligible'] else 'NOT eligible'} "
                    f"(IC {next(g for g in v['gates'] if g['gate'] == 'ic')['value']:.3f})"
                    for n, v in verdicts.items()))


def live(client: TestClient, pods: dict, runtime: str) -> dict:
    """The forward days. Returns what the report and the checks need."""
    history, refusals = [], []
    for day in range(FORWARD):
        with session_scope() as s:
            machine = book(s)["pods"]
            plans = {name: mandate_orders(s, pod_id=p["id"], provider=PROVIDER)
                     for name, p in pods.items()
                     if p["id"] in machine and machine[p["id"]]["stage"] != "closed"}
        for name, plan in plans.items():
            for order in plan["orders"]:
                r = client.post("/orders", headers=h(pods[name]["key"]), json={
                    "ticker": order["ticker"], "side": order["side"], "qty": order["qty"],
                    "price_type": "market", "justification": "my rule's rebalance"})
                if r.status_code != 201:
                    refusals.append((day, name, order["side"], r.status_code, r.json()["detail"]))
        r = client.post("/clock/advance", headers=h(runtime), json={"days": 1})
        assert r.status_code == 200, r.text
        with session_scope() as s:
            state = book(s)
            history.append({"day": day + 1, "centre": state["centre_cash"],
                            "pods": {n: dict(state["pods"].get(p["id"], {}),
                                             equity=_equity(s, p["id"]))
                                     for n, p in pods.items()}})
    return {"history": history, "refusals": refusals}


def _equity(s, pod_id: int) -> float:
    cash = s.get(CashBalance, pod_id)
    value = cash.balance if cash else 0.0
    for pos in s.scalars(select(Position).where(Position.pod_id == pod_id)):
        value += pos.qty * PROVIDER.get_price(pos.ticker, as_of=_now(s)).price
    return value


def _now(s):
    from app.ledger.events import ledger_now
    return ledger_now(s)


def events(s, type_: str) -> list[dict]:
    return [dict(e.payload_json, _id=e.id, _ts=e.ts) for e in
            s.scalars(select(Event).where(Event.type == type_).order_by(Event.id))]


# --- the checks ---------------------------------------------------------------------------------

def checks(pods: dict, run: dict, client: TestClient, runtime: str) -> None:
    ids = {n: p["id"] for n, p in pods.items()}
    with session_scope() as s:
        seeded = {e["pod_id"] for e in events(s, "capital_seeded")}
        refused = events(s, "capital_seed_refused")
        allocs = [e for e in events(s, "allocation_set") if e.get("source") == "capital"]
        stages = events(s, "pod_stage_changed")
        realloc = events(s, "capital_reallocated")
        law = CapitalConfig.model_validate(events(s, "capital_opened")[0]["law"])
    check("A: the long-short pitch is refused a seed, in the ledger, and the four others seeded",
          seeded == {ids[n] for n in ("edge", "twin", "faded", "bleeder")}
          and [r["pod_id"] for r in refused] == [ids["shorty"]],
          f"refused: {refused[0]['reason'] if refused else None}")

    def flows(name: str) -> list[float]:
        return [a["delta"] for a in allocs if a["pod_id"] == ids[name]]

    last = run["history"][-1]["pods"]
    edge_cap = sum(flows("edge"))
    check("B1: the edge's capital grows several times its seed",
          edge_cap >= 5 * law.seed_usd, f"seed ${law.seed_usd:,.0f} → capital ${edge_cap:,.0f}, "
          f"equity ${last['edge']['equity']:,.0f}")
    check("B1: the edge pod is never cut (no withdrawal, no ladder stage)",
          all(d > 0 for d in flows("edge")) and not any(e["pod_id"] == ids["edge"] for e in stages),
          f"{len(flows('edge'))} moves, all raises")

    twin_rows = [row for e in realloc for row in e["result"]["pods"] if row["pod_id"] == ids["twin"]]
    penalised = [row for row in twin_rows if row.get("corr_with") == ids["edge"]
                 and (row.get("corr") or 0) > 0.5]
    check("B2: the twin is penalised for moving like the older edge pod",
          len(penalised) > 0 and all(r["corr_factor"] < 0.5 for r in penalised),
          f"{len(penalised)} re-weighings saw ρ > 0.5 with edge; last ρ "
          f"{penalised[-1]['corr']:.2f} → its score ×{penalised[-1]['corr_factor']:.2f}"
          if penalised else "never penalised")
    edge_rows = [row for e in realloc for row in e["result"]["pods"] if row["pod_id"] == ids["edge"]]
    check("B2: ... and the edge, the original, never is",
          all((r.get("corr") is None) for r in edge_rows))
    twin_cap = sum(flows("twin"))
    check("B2: the twin does not grow like the edge", twin_cap < edge_cap / 3,
          f"twin ${twin_cap:,.0f} vs edge ${edge_cap:,.0f}")

    faded = flows("faded")
    check("B3: the faded pod is never raised and ends at or below its seed",
          faded[0] == law.seed_usd and all(d < 0 for d in faded[1:])
          and sum(faded) <= law.seed_usd,
          f"moves {[round(d) for d in faded]}, ends ${last['faded']['equity']:,.0f}")

    bleed = [e for e in stages if e["pod_id"] == ids["bleeder"]]
    path = [(e["from"], e["to"], round(e["drawdown"], 4)) for e in bleed]
    check("B4: the bleeder climbs the ladder in order: halved, reduce-only, closed",
          [e["to"] for e in bleed] == ["halved", "reduce_only", "closed"]
          and law.halve_at <= bleed[0]["drawdown"] < law.reduce_only_at
          and law.reduce_only_at <= bleed[1]["drawdown"] < law.close_at
          and bleed[2]["drawdown"] >= law.close_at, str(path))
    halved_at = bleed[0]["_id"] if bleed else 0
    cut = [a for a in allocs if a["pod_id"] == ids["bleeder"] and a["_id"] > halved_at][:1]
    check("B4: halving sent about half its equity back to the centre",
          bool(cut) and abs(-cut[0]["delta"] / bleed[0]["equity"] - 0.5) < 0.01,
          f"${-cut[0]['delta']:,.0f} of ${bleed[0]['equity']:,.0f}" if cut else "no recall")
    buys = [r for r in run["refusals"] if r[1] == "bleeder" and r[2] == "buy"]
    check("B4: once reduce-only, its buy is refused (403, logged)",
          bool(buys) and all(r[3] == 403 for r in buys), buys[0][4] if buys else "no refused buy")
    with session_scope() as s:
        denied = [e for e in events(s, "permission_denied") if "reduce-only" in str(e)]
        closed_pod = s.get(Pod, ids["bleeder"])
        left = list(s.scalars(select(Position).where(Position.pod_id == ids["bleeder"])))
        cash = s.get(CashBalance, ids["bleeder"])
        status = closed_pod.status
    check("B4: ... and each refusal is in the ledger", len(denied) == len(buys), f"{len(denied)}")
    check("B4: closed: every share sold, every dollar back at the centre",
          status == "closed" and not left and abs(cash.balance) < 0.01,
          f"pod status {status}, {len(left)} positions, cash ${cash.balance:,.2f}")
    r = client.post("/orders", headers=h(pods["bleeder"]["key"]), json={
        "ticker": "B00", "side": "sell", "qty": 1, "price_type": "market",
        "justification": "one last sell"})
    check("B4: a closed pod's order is refused", r.status_code == 403,
          f"{r.status_code}: {r.json()['detail']}")

    # C: redo every re-weighing from the inputs in its event.
    same = all(reallocate([PodTrack.from_input(p) for p in e["inputs"]["pods"]],
                          centre_cash=e["inputs"]["centre_cash"],
                          law=CapitalConfig.model_validate(e["law"])) == e["result"]
               for e in realloc)
    check("C: every re-weighing redone from its event's inputs gives the same moves", same,
          f"{len(realloc)} re-weighings")
    probe = next(e for e in reversed(realloc)
                 if any(row["pod_id"] == ids["edge"] and row["move"] > 0
                        for row in e["result"]["pods"]))
    tracks = [PodTrack.from_input(p) for p in probe["inputs"]["pods"]]
    kwargs = {"centre_cash": probe["inputs"]["centre_cash"],
              "law": CapitalConfig.model_validate(probe["law"])}
    base = {r["pod_id"]: r for r in reallocate(tracks, **kwargs)["pods"]}
    costly = [PodTrack(**{**t.__dict__, "cost_usd": 0.5 * t.equity})
              if t.pod_id == ids["edge"] else t for t in tracks]
    dear = {r["pod_id"]: r for r in reallocate(costly, **kwargs)["pods"]}
    check("C: a thinking cost of half its capital scores the edge lower and moves less to it",
          dear[ids["edge"]]["viability"] < base[ids["edge"]]["viability"]
          and dear[ids["edge"]]["move"] < base[ids["edge"]]["move"],
          f"viability {base[ids['edge']]['viability']:.2f} → {dear[ids['edge']]['viability']:.2f}, "
          f"move ${base[ids['edge']]['move']:,.0f} → ${dear[ids['edge']]['move']:,.0f}")

    with session_scope() as s:
        before = _snapshot(s)
        rebuild_state(s)
        s.flush()
        after = _snapshot(s)
        machine = book(s)["pods"]
        rows = {p.id: p for p in s.scalars(select(Pod))}
        agree = all(abs(rows[i].current_allocation - e["allocated"]) < 1e-6
                    and rows[i].status == e["stage"] for i, e in machine.items())
        s.rollback()
    check("C: rebuilding from the ledger gives the same cash, positions, capital and stages",
          before == after and agree)


def _snapshot(s) -> dict:
    return {"cash": sorted((c.pod_id, round(c.balance, 6)) for c in s.scalars(select(CashBalance))),
            "positions": sorted((p.pod_id, p.ticker, round(p.qty, 9), round(p.avg_cost, 9))
                                for p in s.scalars(select(Position))),
            "pods": sorted((p.id, p.status, round(p.current_allocation, 6))
                           for p in s.scalars(select(Pod)))}


def report(pods: dict, run: dict) -> None:
    print("\nThe allocation table (equity at the day's last close, $k; stage when not active):")
    names = [n for n in PODS if n != "shorty"]
    print("  day   centre " + "".join(f"{n:>16}" for n in names))
    for row in run["history"]:
        if row["day"] % 10 and row["day"] != 1:
            continue
        cells = []
        for n in names:
            p = row["pods"][n]
            stage = p.get("stage", "-")
            cells.append(f"{p['equity'] / 1e3:>9,.0f}" + (f" {stage[:6]:>6}" if stage != "active"
                                                          else "       "))
        print(f"  {row['day']:>3} {row['centre'] / 1e3:>8,.0f} " + "".join(cells))
    print("\nRefused orders:")
    for day, name, side, code, detail in run["refusals"][:5]:
        print(f"  day {day + 1}: {name} {side} → {code}: {detail}")


PROVIDER: BarsProvider


def main() -> int:
    global PROVIDER
    started = time.monotonic()
    logger.remove()
    client, pods, runtime = setup()
    from app.marketdata import get_provider
    PROVIDER = get_provider()
    try:
        pitch(client, pods)
        run = live(client, pods, runtime)
        checks(pods, run, client, runtime)
        report(pods, run)
    finally:
        client.__exit__(None, None, None)
        set_provider(None)
    print(f"\n{len(FAILED)} failed · {time.monotonic() - started:.0f} s")
    for name in FAILED:
        print(f"  FAILED: {name}")
    TMP.cleanup()
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
