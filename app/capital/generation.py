"""Generations as physics (idea: every month is a generation; first slice, a generation turns
over). A multi-manager fund marks its book every month and lets go the managers who did not earn
their place; what they learnt is kept. Off unless the run's law turns it on (``generation:`` in
``config.yaml``, or a world's recipe), so every run recorded before it replays as it was.

1. **The month's end.** At the first clock advance whose day is in a later month than the
   generation's start, after the capital machine has run, physics ends the generation:
   ``generation_ended`` holds every pod that lived in it, with its P&L that month (its daily
   equity changes, net of capital moved in or out), its thinking cost that month (the meter's
   totals since the last generation ended) and the difference, its **fitness**. A pod's statistics
   without a day in the month are ``null``, not 0.
2. **Who goes.** A PM whose pod the risk ladder closed is let go at the close
   (:func:`let_go_closed`, called by the capital machine in the close's transaction). At the
   month's end a PM whose pod never earned a seed is let go, once it has worked there at least the
   law's ``grace_days`` (a PM hired late in the month is judged at the next month's end). A PM
   whose pod holds a seed stays.
3. **Letting go.** The agent is deactivated (its key answers 401 from then on: the Runtime retires
   its mind, and it spends nothing more); ``pm_let_go`` carries why and its **lesson**, a pure
   function of the ledger. An unseeded pod is empty: it is closed (it holds no money and no
   live-pod place) and a vacancy opens in its place, its lesson as the post-mortem; the next
   morning the Runtime hires into it (:mod:`app.capital.hiring`). A closed pod's vacancy is the
   ladder's own.
4. **The library.** Every lesson, oldest first (:func:`library`): every agent reads it
   (``GET /library``), so the firm learns across generations, not only the successor.

Nothing here moves money: closes and recalls are the ladder's, seeds and raises the capital
machine's. Physics acts as the system identity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import GenerationConfig, get_settings
from app.db.models import Agent, AgentRole, AgentStatus, Event, Pod
from app.ledger.events import (
    EVENT_AGENT_REGISTERED,
    EVENT_CAPITAL_SEEDED,
    EVENT_GENERATION_ENDED,
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_SUBMITTED,
    EVENT_PM_LET_GO,
    EVENT_POD_STAGE_CHANGED,
    EVENT_RESEARCH_BACKTEST_RUN,
    EVENT_RUN_STARTED,
    append_event,
    ledger_now,
)
from app.marketdata import MarketDataProvider
from app.metrics.equity import build_equity_curve
from app.metrics.metering import metered_by_agent
from app.oms.service import OMS_LOCK
from app.registry.halt import is_halted
from app.registry.service import deactivate_agent, get_or_create_system_agent

LET_GO_CLOSED = "closed"        # its pod was closed by the risk ladder
LET_GO_NO_SEED = "no_seed"      # its pod never earned a seed


def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def generation_law(session: Session) -> GenerationConfig:
    """The law this run's generations live by: the one frozen into its first ``generation_ended``,
    else today's."""
    first = session.scalar(select(Event).where(Event.type == EVENT_GENERATION_ENDED)
                           .order_by(Event.id).limit(1))
    if first is None:
        return get_settings().generation
    return GenerationConfig.model_validate(first.payload_json["law"])


def _run_start(session: Session) -> date | None:
    started = session.scalar(select(Event).where(Event.type == EVENT_RUN_STARTED)
                             .order_by(Event.id).limit(1))
    if started is None:
        return None
    return datetime.fromisoformat(started.payload_json["start"]).date()


def _first_of_month(day: date) -> date:
    return day.replace(day=1)


def _registered_on(session: Session) -> dict[int, date]:
    return {e.payload_json["agent_id"]: e.ts.date() for e in _events(session, EVENT_AGENT_REGISTERED)}


def _seeded_pods(session: Session) -> set[int]:
    return {e.payload_json["pod_id"] for e in _events(session, EVENT_CAPITAL_SEEDED)}


def _cost_by_pod(session: Session, upto_event_id: int | None) -> dict[int, int]:
    """Micro-dollars of metered thinking per pod, as the ledger stood at ``upto_event_id``."""
    out: dict[int, int] = {}
    for row in metered_by_agent(session, upto_event_id=upto_event_id).values():
        if row.pod_id is not None:
            out[row.pod_id] = out.get(row.pod_id, 0) + row.usd_micros
    return out


# --- the lesson ---------------------------------------------------------------------------------

def lesson_of(session: Session, *, pod_id: int, reason: str,
              post_mortem: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a pod tried and how it ended, from the ledger alone: its PMs, the days they worked, how
    many research backtests they ran, every pitch with the gates it failed, what the centre did with
    it, its whole thinking cost, and why its PM went. A ladder-closed pod's post-mortem (its rule,
    forward days, the ladder's steps) comes with it."""
    pod = session.get(Pod, pod_id)
    pms = sorted(a.name for a in session.scalars(select(Agent).where(
        Agent.pod_id == pod_id, Agent.role == AgentRole.pm)))
    judged = {e.payload_json.get("pitch_id"): e.payload_json
              for e in _events(session, EVENT_PITCH_JUDGED)}
    pitches = []
    for e in _events(session, EVENT_PITCH_SUBMITTED):
        p = e.payload_json
        if p.get("pod_id") != pod_id:
            continue
        verdict = judged.get(e.id) or {}
        rule = p.get("rule") or {}
        pitches.append({
            "pitch_id": e.id, "on": e.ts.date().isoformat(), "hypothesis": p.get("hypothesis"),
            "rule": {k: rule.get(k) for k in ("signal", "lookback", "top_n", "rebalance_every",
                                              "side", "universe") if k in rule},
            "eligible": verdict.get("eligible"),
            "failed_gates": [g.get("gate") for g in verdict.get("gates") or []
                             if g.get("result") == "fail"]})
    research = sum(1 for e in _events(session, EVENT_RESEARCH_BACKTEST_RUN)
                   if e.payload_json.get("pod_id") == pod_id)
    agents = {a.id for a in session.scalars(select(Agent).where(Agent.pod_id == pod_id))}
    since = min((d for a, d in _registered_on(session).items() if a in agents), default=None)
    cost = _cost_by_pod(session, None).get(pod_id, 0)
    now = ledger_now(session).date()
    return {
        "pod_id": pod_id, "pod_name": pod.name if pod is not None else None, "pms": pms,
        "reason": reason, "worked_from": since.isoformat() if since else None,
        "let_go_on": now.isoformat(),
        "days_worked": (now - since).days if since else None,
        "research_backtests": research, "pitches": pitches,
        "seeded": pod_id in _seeded_pods(session),
        "thinking_cost_usd": cost / 1e6,
        **({"post_mortem": post_mortem} if post_mortem is not None else {}),
    }


def _why(reason: str, lesson: dict[str, Any], law: GenerationConfig) -> str:
    if reason == LET_GO_CLOSED:
        return "its pod was closed by the risk ladder"
    tried = len(lesson["pitches"])
    return (f"its pod earned no seed in {lesson['days_worked']} days (the generation law judges a "
            f"PM after {law.grace_days} days): {tried} pitch{'es' if tried != 1 else ''}, "
            f"{sum(1 for p in lesson['pitches'] if p['eligible'])} eligible")


# --- letting go ---------------------------------------------------------------------------------

def _let_go(session: Session, *, pod_id: int, reason: str, actor: Agent, generation: int | None,
            post_mortem: dict[str, Any] | None = None) -> list[Event]:
    """Let every active agent of ``pod_id`` go, with the pod's lesson; an unseeded pod is closed
    and a vacancy opens in its place. The caller owns the transaction (and holds OMS_LOCK)."""
    from app.capital.hiring import open_vacancy   # hiring reads the capital machine, which reads us

    law = generation_law(session)
    staff = list(session.scalars(select(Agent).where(
        Agent.pod_id == pod_id, Agent.status == AgentStatus.active).order_by(Agent.id)))
    if not staff:
        return []
    lesson = lesson_of(session, pod_id=pod_id, reason=reason, post_mortem=post_mortem)
    why = _why(reason, lesson, law)
    close = reason == LET_GO_NO_SEED
    pod = session.get(Pod, pod_id)
    made = []
    for agent in staff:
        deactivate_agent(session, agent_id=agent.id, actor_agent_id=actor.id)
        made.append(append_event(session, type=EVENT_PM_LET_GO, actor_agent_id=actor.id, payload={
            "lesson_no": len(_events(session, EVENT_PM_LET_GO)) + 1, "agent_id": agent.id,
            "agent_name": agent.name, "pod_id": pod_id, "pod_name": pod.name, "reason": reason,
            "why": why, "pod_closed": close, "generation": generation, "lesson": lesson}))
    if close and pod.status != "closed":
        pod.status = "closed"
        session.flush()
        open_vacancy(session, pod_id=pod_id, actor=actor, lesson=lesson)
    return made


def let_go_closed(session: Session, *, pod_id: int, post_mortem: dict[str, Any],
                  actor: Agent) -> list[Event]:
    """The risk ladder closed ``pod_id``: under the generation law its PMs go now, with the
    post-mortem as their lesson (cycle 54: a closed pod's PM kept waking, and spending, until the
    run ended). Called by the capital machine in the close's own transaction."""
    if not generation_law(session).on:
        return []
    return _let_go(session, pod_id=pod_id, reason=LET_GO_CLOSED, actor=actor, generation=None,
                   post_mortem=post_mortem)


# --- the month's end ----------------------------------------------------------------------------

def _window(session: Session) -> tuple[int, date, int | None] | None:
    """``(number, first day, the last generation's event id)`` of the generation now running."""
    last = session.scalar(select(Event).where(Event.type == EVENT_GENERATION_ENDED)
                          .order_by(Event.id.desc()).limit(1))
    if last is not None:
        return (last.payload_json["generation"] + 1, date.fromisoformat(last.payload_json["to"])
                + timedelta(days=1), last.id)
    start = _run_start(session)
    return None if start is None else (1, start, None)


def _measure(session: Session, *, pod: Pod, first: date, last: date, provider: MarketDataProvider,
             costs_then: dict[int, int], costs_now: dict[int, int], now: datetime) -> dict[str, Any]:
    curve = build_equity_curve(session, pod_id=pod.id, provider=provider, as_of=now,
                               live_price=False)
    before = [p for p in curve.points if p.on < first]
    days = [p for p in curve.points if first <= p.on <= last]
    pnl = None
    if days:
        prev = before[-1].equity if before else 0.0
        pnl = 0.0
        for p in days:
            pnl += p.equity - prev - p.net_flow
            prev = p.equity
    thinking = (costs_now.get(pod.id, 0) - costs_then.get(pod.id, 0)) / 1e6
    return {"pod_id": pod.id, "pod_name": pod.name, "stage": pod.status,
            "seeded": pod.id in _seeded_pods(session), "days": len(days), "pnl_usd": pnl,
            "thinking_usd": thinking, "fitness_usd": None if pnl is None else pnl - thinking,
            "equity_usd": days[-1].equity if days else None}


def turnover(session: Session, *, provider: MarketDataProvider) -> dict[str, Any] | None:
    """End the generation if the month has turned; commits. ``None``: the law is off, the world is
    halted, or the month has not turned."""
    with OMS_LOCK:
        if is_halted():
            return None
        try:
            done = _turnover(session, provider=provider)
            session.commit()
            return done
        except Exception:
            session.rollback()
            raise


def _turnover(session: Session, *, provider: MarketDataProvider) -> dict[str, Any] | None:
    law = generation_law(session)
    if not law.on:
        return None
    window = _window(session)
    if window is None:
        return None
    number, first, since_id = window
    now = ledger_now(session)
    month = _first_of_month(now.date())
    if month <= first:
        return None     # the month has not turned since the generation began
    last = month - timedelta(days=1)
    system = get_or_create_system_agent(session)
    costs_then = {} if since_id is None else _cost_by_pod(session, since_id)
    costs_now = _cost_by_pod(session, None)
    let_go_in = {e.payload_json["pod_id"] for e in _events(session, EVENT_PM_LET_GO)
                 if since_id is None or e.id > since_id}
    closed_in = {e.payload_json["pod_id"] for e in _events(session, EVENT_POD_STAGE_CHANGED)
                 if e.payload_json.get("to") == "closed" and (since_id is None or e.id > since_id)}
    registered = _registered_on(session)
    seeded = _seeded_pods(session)

    rows = []
    to_let_go: list[int] = []
    for pod in session.scalars(select(Pod).order_by(Pod.id)):
        if pod.status == "closed" and pod.id not in let_go_in | closed_in:
            continue    # it ended in an earlier generation
        row = _measure(session, pod=pod, first=first, last=last, provider=provider,
                       costs_then=costs_then, costs_now=costs_now, now=now)
        staff = list(session.scalars(select(Agent).where(
            Agent.pod_id == pod.id, Agent.status == AgentStatus.active,
            Agent.role == AgentRole.pm).order_by(Agent.id)))
        row["pms"] = [a.name for a in staff]
        if pod.status == "closed":
            row["verdict"], row["why"] = "ended", (
                "closed by the risk ladder" if pod.id in closed_in else "its PM was let go")
        elif not staff:
            row["verdict"], row["why"] = "empty", "no PM works there"
        elif pod.id in seeded:
            row["verdict"], row["why"] = "stays", "its pod holds a seed"
        else:
            tenure = min((month - registered.get(a.id, month)).days for a in staff)
            if tenure >= law.grace_days:
                row["verdict"], row["why"] = "let_go", "no seed this month"
                to_let_go.append(pod.id)
            else:
                row["verdict"], row["why"] = "too_new", (
                    f"{tenure} days in its pod, judged after {law.grace_days}")
        rows.append(row)
    ended = append_event(session, type=EVENT_GENERATION_ENDED, actor_agent_id=system.id, payload={
        "generation": number, "month": first.strftime("%Y-%m"), "from": first.isoformat(),
        "to": last.isoformat(), "law": law.model_dump(mode="json"), "pods": rows})
    gone = []
    for pod_id in to_let_go:
        gone += _let_go(session, pod_id=pod_id, reason=LET_GO_NO_SEED, actor=system,
                        generation=number)
    logger.bind(generation=number).info("generation ended: {} pods, {} let go", len(rows), len(gone))
    return {"generation": number, "event_id": ended.id, "let_go": [e.payload_json["agent_id"]
                                                                 for e in gone]}


def safe_turnover(session: Session, *, provider: MarketDataProvider) -> dict[str, Any] | None:
    """:func:`turnover` for the clock advance, which has already moved and committed: a failure is
    logged loudly and the next advance tries again (the month stays unturned until it succeeds)."""
    try:
        return turnover(session, provider=provider)
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("generation turnover failed")
        return None


# --- the library --------------------------------------------------------------------------------

def library(session: Session) -> list[dict[str, Any]]:
    """Every lesson the firm has kept, oldest first: who went, from which pod, when, why, and what
    the pod tried. One entry per pod let go (its PMs together)."""
    out: dict[tuple[int, str], dict[str, Any]] = {}
    for e in _events(session, EVENT_PM_LET_GO):
        p = e.payload_json
        key = (p["pod_id"], p["reason"])
        if key in out:
            out[key]["pms"].append(p["agent_name"])
            continue
        out[key] = {"lesson_no": len(out) + 1, "on": e.ts.date().isoformat(),
                    "generation": p["generation"], "pod_name": p["pod_name"],
                    "pms": [p["agent_name"]], "reason": p["reason"], "why": p["why"],
                    "lesson": p["lesson"]}
    return list(out.values())


def announcement(session: Session) -> dict[str, Any] | None:
    """The generation law in plain words, for every PM's capital view (``None`` while it is off)."""
    law = generation_law(session)
    if not law.on:
        return None
    window = _window(session)
    now = ledger_now(session).date()
    nxt = (_first_of_month(now) + timedelta(days=32)).replace(day=1)
    return {
        "law": (f"Every month is a generation. At each month's end the firm measures every pod's "
                f"fitness: its P&L that month minus its thinking cost that month. A PM whose pod "
                f"has not earned a seed by then, after at least {law.grace_days} days in it, is "
                f"let go: its key stops working and its pod closes. A PM whose pod the risk "
                f"ladder closes is let go at the close. Each departure's lesson goes to the "
                f"library (read_library), which every PM can read; a new PM is hired into the "
                f"freed place."),
        "grace_days": law.grace_days, "generation": window[0] if window else None,
        "next_judged_on": nxt.isoformat()}
