"""The quarter report (idea: the firm lives a quarter): what the Human reads about a run of the
multi-manager machine. A pure function of the ledger and the market's closes; it moves nothing.

* **Week by week**: each pod's equity (its capital and what it made of it), the centre's cash and
  the firm's equity, on the centre's opening day and every ``every_days`` after, and today.
* **Each pod**: where it came from (founding, or hired into a dead pod's vacancy), its PMs, its
  seed, its stage, when and how deep the ladder closed it; the capital put in and taken back; its
  P&L **gross** (equity minus the net money put in) and **net of thinking** (minus every dollar its
  minds' keys were metered); the thinking per day.
* **The re-weighings**: for each, every scored pod's ``t`` before thinking cost and after (the
  viability the algorithm ranks by), and the move it made: where thinking cost changed a rank, it
  shows.
* **What happened**: seeds, refusals, ladder steps, vacancies, hires and refused hires, in order.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capital.service import SOURCE, _pod_cost_usd, book, opened_law
from app.db.models import Agent, Event, Pod
from app.ledger.events import (
    EVENT_ALLOCATION_SET,
    EVENT_CAPITAL_REALLOCATED,
    EVENT_CAPITAL_SEED_REFUSED,
    EVENT_CAPITAL_SEEDED,
    EVENT_HIRE_REFUSED,
    EVENT_POD_STAGE_CHANGED,
    EVENT_VACANCY_FILLED,
    EVENT_VACANCY_OPENED,
    ledger_now,
)
from app.marketdata import MarketDataProvider
from app.metrics.equity import DailyCloseCache, build_equity_curve

HAPPENINGS = (EVENT_CAPITAL_SEEDED, EVENT_CAPITAL_SEED_REFUSED, EVENT_POD_STAGE_CHANGED,
              EVENT_VACANCY_OPENED, EVENT_VACANCY_FILLED, EVENT_HIRE_REFUSED)


def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def _gross_t(row: dict[str, Any]) -> float | None:
    """The score's ``t`` with no thinking cost: what the pod's returns alone say."""
    if row.get("mean") is None or not row.get("sd"):
        return None
    return row["mean"] / row["sd"] * math.sqrt(row["days"])


def quarter_report(session: Session, *, provider: MarketDataProvider,
                   every_days: int = 7) -> dict[str, Any]:
    """The report at the ledger's now (see the module). ``opened_on`` null: the centre never opened
    (no eligible pitch yet), so there is no machine to report on."""
    opened = opened_law(session)
    if opened is None:
        return {"opened_on": None, "today": None, "weeks": [], "pods": [], "centre": [],
                "firm": [], "reweighings": [], "happened": []}
    law, opened_event = opened
    now = ledger_now(session)
    start, today = opened_event.ts.date(), now.date()
    weeks = [start + timedelta(days=k) for k in range(0, (today - start).days + 1, every_days)]
    if weeks[-1] != today:
        weeks.append(today)
    state = book(session)
    names = {p.id: p.name for p in session.scalars(select(Pod))}
    pms: dict[int, list[str]] = {}
    for a in session.scalars(select(Agent).order_by(Agent.id)):
        if a.pod_id is not None:
            pms.setdefault(a.pod_id, []).append(a.name)
    costs = _pod_cost_usd(session)
    hired = {e.payload_json["pod_id"]: e for e in _events(session, EVENT_VACANCY_FILLED)}
    vacancy_of = {e.id: e.payload_json for e in _events(session, EVENT_VACANCY_OPENED)}
    flows: dict[int, list[tuple[date, float, bool]]] = {}
    for e in _events(session, EVENT_ALLOCATION_SET):
        p = e.payload_json
        flows.setdefault(p["pod_id"], []).append(
            (e.ts.date(), float(p["delta"]), p.get("source") == SOURCE))
    closes_at = {e.payload_json["pod_id"]: e for e in _events(session, EVENT_POD_STAGE_CHANGED)
                 if e.payload_json["to"] == "closed"}

    cache = DailyCloseCache(provider)
    pods = []
    for pod_id in sorted(names):
        curve = build_equity_curve(session, pod_id=pod_id, provider=provider, as_of=now,
                                   closes=cache, live_price=False)
        by_week = []
        for day in weeks:
            seen = [p.equity for p in curve.points if p.on <= day]
            by_week.append(seen[-1] if seen else None)
        equity = curve.points[-1].equity if curve.points else 0.0
        mine = flows.get(pod_id, [])
        put_in = sum(d for _, d, cap in mine if cap and d > 0)
        taken_back = -sum(d for _, d, cap in mine if cap and d < 0)
        contributed = sum(d for _, d, _ in mine)
        thinking = costs.get(pod_id, 0.0)
        entry = state["pods"].get(pod_id)
        close = closes_at.get(pod_id)
        origin = "founding"
        if pod_id in hired:
            filled = hired[pod_id].payload_json
            dead = vacancy_of.get(filled["vacancy_id"], {})
            origin = (f"hired {hired[pod_id].ts.date().isoformat()} into vacancy "
                      f"#{filled['vacancy_id']} (replacing {dead.get('pod_name', '?')})")
        pnl = equity - contributed if (mine or curve.points) else 0.0
        pods.append({
            "pod_id": pod_id, "name": names[pod_id], "pms": pms.get(pod_id, []),
            "origin": origin, "seeded_on": entry["seeded_on"] if entry else None,
            "pitch_id": entry["pitch_id"] if entry else None,
            "stage": entry["stage"] if entry else "never seeded",
            "closed_on": close.ts.date().isoformat() if close else None,
            "closed_at_drawdown": close.payload_json["worst_drawdown"] if close else None,
            "equity_by_week": by_week, "equity_usd": equity,
            "put_in_usd": put_in, "taken_back_usd": taken_back,
            "pnl_gross_usd": pnl, "thinking_usd": thinking, "pnl_net_usd": pnl - thinking,
            "return_on_capital_gross": pnl / put_in if put_in > 0 else None,
            "return_on_capital_net": (pnl - thinking) / put_in if put_in > 0 else None,
            "pricing_errors": curve.pricing_errors})

    centre = []
    for day in weeks:
        moved = sum(d for mine in flows.values() for on, d, cap in mine if cap and on <= day)
        centre.append(law.firm_capital_usd - moved)
    firm = [c + sum(p["equity_by_week"][i] or 0.0 for p in pods) for i, c in enumerate(centre)]

    reweighings = []
    for e in _events(session, EVENT_CAPITAL_REALLOCATED):
        rows = []
        for row in e.payload_json["result"]["pods"]:
            rows.append({"pod_id": row["pod_id"], "name": names.get(row["pod_id"]),
                         "days": row["days"], "t_gross": _gross_t(row),
                         "t_net": row.get("t"), "cost_per_day": row.get("cost_per_day"),
                         "viability": row["viability"], "equity": row["equity"],
                         "move": row["move"]})
        reweighings.append({"day": e.payload_json["day"], "pods": rows})

    happened = []
    for e in _events(session, *HAPPENINGS):
        p = e.payload_json
        pod = names.get(p.get("pod_id"), str(p.get("pod_id")))
        what = {
            EVENT_CAPITAL_SEEDED: lambda: f"seeded ${p['seed_usd']:,.0f} for pitch #{p['pitch_id']}",
            EVENT_CAPITAL_SEED_REFUSED: lambda: f"seed refused for pitch #{p['pitch_id']}: "
                                                f"{p['reason']}",
            EVENT_POD_STAGE_CHANGED: lambda: f"{p['from']} → {p['to']} at "
                                             f"{p['worst_drawdown']:.1%} down",
            EVENT_VACANCY_OPENED: lambda: f"vacancy #{e.id} opened",
            EVENT_VACANCY_FILLED: lambda: f"hired {p['agent_name']} ({p['model']}) into a new "
                                          f"pod, vacancy #{p['vacancy_id']}",
            EVENT_HIRE_REFUSED: lambda: f"hire for vacancy #{p['vacancy_id']} refused: "
                                        f"{p['reason']}",
        }[e.type]()
        happened.append({"on": e.ts.date().isoformat(), "pod": pod, "what": what})

    return {"opened_on": start.isoformat(), "today": today.isoformat(),
            "weeks": [d.isoformat() for d in weeks], "pods": pods, "centre": centre,
            "firm": firm, "reweighings": reweighings, "happened": happened,
            "firm_capital_usd": law.firm_capital_usd}


def _money(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{'-' if x < 0 else ''}${abs(x) / 1e3:,.0f}k" if abs(x) >= 1e4 else (
        f"{'-' if x < 0 else ''}${abs(x):,.0f}")


def _cents(x: float | None) -> str:
    """Thinking costs cents: a whole-dollar figure would show every pod's as $0."""
    return "-" if x is None else f"{'-' if x < 0 else ''}${abs(x):,.2f}"


def render(report: dict[str, Any]) -> str:
    """The report as text, for a person."""
    if report["opened_on"] is None:
        return "The centre never opened: no eligible pitch, no capital moved."
    out = [f"Quarter report, {report['opened_on']} to {report['today']}"]
    pods = report["pods"]
    out.append("\nEquity by week (capital the centre put in, and what each pod made of it):")
    out.append("  week of     " + "".join(f"{p['name'][:11]:>12}" for p in pods)
               + f"{'centre':>12}{'firm':>12}")
    for i, day in enumerate(report["weeks"]):
        out.append(f"  {day}  " + "".join(f"{_money(p['equity_by_week'][i]):>12}" for p in pods)
                   + f"{_money(report['centre'][i]):>12}{_money(report['firm'][i]):>12}")
    out.append("\nEach pod:")
    for p in pods:
        out.append(f"  {p['name']} ({', '.join(p['pms']) or 'no PM'}; {p['origin']}): "
                   f"{p['stage']}" + (f", closed {p['closed_on']} at "
                                      f"{p['closed_at_drawdown']:.1%} down" if p["closed_on"] else ""))
        if p["put_in_usd"] > 0:
            out.append(f"    put in {_money(p['put_in_usd'])}, taken back "
                       f"{_money(p['taken_back_usd'])}; P&L {_money(p['pnl_gross_usd'])} gross, "
                       f"thinking ${p['thinking_usd']:,.2f}, {_money(p['pnl_net_usd'])} net "
                       f"({p['return_on_capital_net']:+.2%} on the capital put in)")
        else:
            out.append(f"    never funded; thinking ${p['thinking_usd']:,.2f}")
    if report["reweighings"]:
        last = report["reweighings"][-1]
        out.append(f"\nThe last re-weighing ({last['day']}): t before thinking cost → after "
                   "(the algorithm ranks by the viability)")
        for r in sorted(last["pods"], key=lambda r: -(r["viability"] or -1e9)):
            fmt = lambda x: "null" if x is None else f"{x:+.2f}"  # noqa: E731
            out.append(f"  {r['name']:<12} {r['days']:>3} days  t {fmt(r['t_gross'])} → "
                       f"{fmt(r['t_net'])}  viability {fmt(r['viability'])}  move "
                       f"{_money(r['move'])}")
    out.append("\nWhat happened:")
    for h in report["happened"]:
        out.append(f"  {h['on']}  {h['pod']}: {h['what']}")
    return "\n".join(out)


# --- the generation report (idea: every month is a generation) -----------------------------------

def generation_report(session: Session) -> dict[str, Any]:
    """Each month's generation as the ledger holds it: every pod's fitness (P&L that month minus
    its thinking that month) and verdict, who was let go and why, who was hired in the month; then
    the library of lessons. A pure function of the ledger (the numbers are physics' own, written
    at each month's end); it moves nothing."""
    from app.capital.generation import library

    ended = _events(session, "generation_ended")
    let_go = _events(session, "pm_let_go")
    filled = _events(session, EVENT_VACANCY_FILLED)
    out = []
    for e in ended:
        g = e.payload_json
        first, last = date.fromisoformat(g["from"]), date.fromisoformat(g["to"])
        gone = [{"on": x.ts.date().isoformat(), "pm": x.payload_json["agent_name"],
                 "pod": x.payload_json["pod_name"], "why": x.payload_json["why"]}
                for x in let_go if x.payload_json.get("generation") == g["generation"]
                or (x.payload_json.get("generation") is None and first <= x.ts.date() <= last)]
        hired = [{"on": x.ts.date().isoformat(), "pm": x.payload_json["agent_name"],
                  "pod": x.payload_json["pod_name"]}
                 for x in filled if first <= x.ts.date() <= last]
        out.append({"generation": g["generation"], "month": g["month"], "from": g["from"],
                    "to": g["to"], "pods": g["pods"], "let_go": gone, "hired": hired,
                    **({"diversity": g["diversity"]} if "diversity" in g else {})})
    return {"generations": out, "library": library(session),
            "family_tree": family_tree(session),
            "today": ledger_now(session).date().isoformat()}


def family_tree(session: Session) -> list[dict[str, Any]]:
    """Under the reproduction law, every pod with its children (the hires its design fathered),
    each with its model and the one change it was born with; ``[]`` when no hire was made under
    it. Founding pods and plain hires are roots. A pure function of the ledger: a pod's name and
    stage are the events' (a pod row is not an event), so a recording alone draws the same tree."""
    from app.capital.reproduction import design_of
    from app.ledger.rebuild import stage_from

    opened = {e.id: e.payload_json for e in _events(session, EVENT_VACANCY_OPENED)}
    if not any("design" in v["hire"] for v in opened.values()):
        return []
    born = {e.payload_json["pod_id"]: opened.get(e.payload_json["vacancy_id"], {}).get("hire", {})
            for e in _events(session, EVENT_VACANCY_FILLED)}
    names: dict[int, str | None] = {}
    stages: dict[int, str] = {}
    for e in _events(session, "agent_registered", "generation_ended", "pm_let_go",
                     EVENT_VACANCY_FILLED, EVENT_POD_STAGE_CHANGED, "hire_failed"):
        p = e.payload_json
        rows = p["pods"] if e.type == "generation_ended" else [p]
        for row in rows:
            if row.get("pod_id") is not None:
                names[row["pod_id"]] = row.get("pod_name") or names.get(row["pod_id"])
        if (staged := stage_from(e)) is not None:
            stages[staged[0]] = staged[1]
    nodes: dict[int, dict[str, Any]] = {}
    for pod_id in sorted(names):
        design = design_of(session, pod_id)
        if pod_id not in born and design["model"] is None and design["rule"] is None:
            continue    # a pod no one ever ran (an operator's spare)
        hire = born.get(pod_id, {})
        name = names[pod_id] or design["pod_name"] or f"pod {pod_id}"
        nodes[pod_id] = {"pod_id": pod_id, "pod_name": name, "stage": stages.get(pod_id, "active"),
                         "model": design["model"], "rule": design["rule"],
                         "parent": (hire.get("parent") or {}).get("pod_id"),
                         "change": hire.get("change"), "children": []}
    roots = []
    for node in nodes.values():
        parent = nodes.get(node["parent"]) if node["parent"] is not None else None
        (parent["children"] if parent is not None else roots).append(node)
    return roots


def _tree_lines(node: dict[str, Any], depth: int) -> list[str]:
    rule = node["rule"] or {}
    what = (f"lookback {rule.get('lookback')}, rebalance {rule.get('rebalance_every')}, "
            f"top {rule.get('top_n')} of {(rule.get('universe') or ['?'])[0][:1]}..."
            if rule else "no rule")
    born = "" if not node["change"] else (f"born with {node['change']['what']} "
                                          f"{node['change']['from']} -> {node['change']['to']}; "
                                          f"its rule now: ")
    lines = [f"  {'    ' * depth}{'└─ ' if depth else ''}{node['pod_name']} ({node['stage']}): "
             f"{node['model'] or 'model not declared'}; {born}{what}"]
    for child in node["children"]:
        lines += _tree_lines(child, depth + 1)
    return lines


def render_generations(report: dict[str, Any]) -> str:
    """The generation report as text, for a person."""
    if not report["generations"]:
        return "No generation has ended: the generation law is off, or no month has turned."
    out = [f"Generation report, to {report['today']}"]
    for g in report["generations"]:
        out.append(f"\nGeneration {g['generation']} ({g['month']}, {g['from']} to {g['to']}):")
        out.append(f"  {'pod':<12}{'PM':<14}{'P&L':>10}{'thinking':>11}{'fitness':>10}  verdict")
        for p in g["pods"]:
            out.append(f"  {p['pod_name'][:11]:<12}{(', '.join(p['pms']) or '-')[:13]:<14}"
                       f"{_money(p['pnl_usd']):>10}{_cents(p['thinking_usd']):>11}"
                       f"{_money(p['fitness_usd']):>10}  {p['verdict']}: {p['why']}")
        for x in g["let_go"]:
            out.append(f"  let go {x['on']}: {x['pm']} ({x['pod']}), {x['why']}")
        for x in g["hired"]:
            out.append(f"  hired {x['on']}: {x['pm']} into {x['pod']}")
        if (d := g.get("diversity")) is not None:
            share = "-" if d["largest_share"] is None else f"{d['largest_share']:.0%}"
            out.append(f"  diversity: {d['live_pods']} live pods, {d['designs']} distinct designs, "
                       f"largest family {d['largest_family'] or '-'} ({share})"
                       + ("  FINDING: one family holds every live pod" if d["collapsed"] else ""))
    if report.get("family_tree"):
        out.append("\nThe family tree (a child is its parent's design with one change):")
        for root in report["family_tree"]:
            out += _tree_lines(root, 0)
    out.append("\nThe library (every PM reads it):")
    for item in report["library"]:
        lesson = item["lesson"]
        tried = "; ".join(
            f"#{p['pitch_id']} {(p['rule'] or {}).get('signal')} "
            f"{'eligible' if p['eligible'] else 'failed ' + ', '.join(p['failed_gates'])}"
            for p in lesson["pitches"]) or "no pitch"
        out.append(f"  {item['lesson_no']}. {item['on']} {', '.join(item['pms'])} "
                   f"({item['pod_name']}): {item['why']}. Tried: {tried}. "
                   f"{lesson['research_backtests']} research backtests, thinking "
                   f"${lesson['thinking_cost_usd']:,.2f}.")
    return "\n".join(out)
