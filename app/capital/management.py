"""Management as physics (idea: management above the pods; first slice, a manager chooses the hires).
A multi-manager fund has a management above its pods: it sees every pod, sets the firm's direction
and chooses who is hired; the algorithm, not management, moves the capital. Off unless the run's
law turns it on (``management:`` in ``config.yaml``, or a world's recipe), so every run recorded
before it replays as it was.

1. **The manager** is an agent of role ``manager`` (:mod:`app.registry.permissions`): only the
   operator's registrar makes one, with no pod. It reads every pod and picks; it never registers,
   deactivates, moves capital, trades or pitches. Its thinking has no pod: it is the centre's cost,
   never a pod's fitness.
2. **The board** (:func:`board`): every pod not closed, as the ledger and the market say it is
   now: cash, positions, exposures, the centre's capital in it, its stage and drawdown, its
   thinking cost, its last month's fitness, its design; and the firm's centre. ``read_cross_pod``.
3. **The candidates.** Under the law, a freed place's vacancy (:func:`app.capital.hiring.
   open_vacancy`) lists every hire the law allows (:func:`candidates`): its own default (the hire
   the law names without a manager), a child of each other fit pod of the generation measured
   (fittest first, ``other_parents`` of them), and a plain hire on each model of the hiring pool,
   each saying what it would be. The place waits ``wait_days`` before the Runtime may fill it.
4. **The pick** (:func:`pick`): the manager names one candidate, once, while the place is open,
   with a brief for the new PM (``hire_picked``); the fill then hires exactly that (the vacancy's
   names, budget and charter, the candidate's design). Silent, the default stands. Refused, in the
   ledger (``hire_pick_refused``): the law was off when the place was freed, a candidate not on
   the list, a second pick, a filled place.
5. **The direction** (:func:`set_direction`): the manager's words to the firm (``direction_set``);
   the latest is in every reader's capital view, once one is written.

Nothing here moves money or makes an agent: the fill is the hiring law's, through the registrar.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import HiringConfig, ManagementConfig, get_settings
from app.db.models import Agent, AgentRole, AgentStatus, Event, Pod
from app.ledger.events import (
    EVENT_DIRECTION_SET,
    EVENT_GENERATION_ENDED,
    EVENT_HIRE_PICK_REFUSED,
    EVENT_HIRE_PICKED,
    EVENT_VACANCY_OPENED,
    append_event,
    ledger_now,
)
from app.oms.service import OMS_LOCK

#: The longest brief a manager may hand a new PM, and the longest direction.
MAX_BRIEF = 2000
MAX_DIRECTION = 2000


class ManagementError(Exception):
    """A pick or a direction physics will not take. ``status`` is the HTTP answer."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def management_law(session: Session) -> ManagementConfig:
    """The law this run is managed by: the one frozen into its first vacancy (absent there: off),
    else today's."""
    first = session.scalar(select(Event).where(Event.type == EVENT_VACANCY_OPENED)
                           .order_by(Event.id).limit(1))
    if first is None:
        return get_settings().management
    return ManagementConfig.model_validate(first.payload_json.get("management") or {})


# --- the candidates -----------------------------------------------------------------------------

def _money(x: float) -> str:
    return f"${x:,.0f}"


def _describe(hire: dict[str, Any]) -> str:
    if hire.get("design") == "child":
        p, c = hire["parent"], hire["change"]
        model = (f"its model {p['model']}" if p["model"] is not None
                 else "its model not on the record")
        return (f"a child of {p['pod_name']} (fitness {_money(p['fitness_usd'])} in generation "
                f"{p['generation']}): {model} and its rule with one change ({c['what']} "
                f"{c['from']} -> {c['to']}); it runs {hire['model']} and counts its family's "
                f"{hire['lineage_attempts']} attempts at every pitch")
    return f"a plain hire on {hire['model']}, no inherited rule"


def candidates(session: Session, *, number: int, hiring: HiringConfig, default: dict[str, Any],
               measured: tuple[int, list[dict[str, Any]]] | None) -> list[dict[str, Any]]:
    """Every hire the law allows for the ``number``-th vacancy, the law's ``default`` first. Each
    is ``{id, default, what, hire}``; ``hire`` is the design part a pick puts in the vacancy's hire
    (``model``, and under the reproduction law ``design`` and a child's parent, change, rule)."""
    from app.capital.reproduction import (
        HIRE_FRAME,
        child_from,
        fit_parents,
        last_generation,
        reproduction_law,
    )

    law = management_law(session)
    design = {k: v for k, v in default.items() if k not in HIRE_FRAME}
    out = [design]
    reproducing = reproduction_law(session).on
    if reproducing:
        measured = measured or last_generation(session)
        taken = (default.get("parent") or {}).get("pod_id")
        others = [p for p in (fit_parents(session, generation=measured[0], rows=measured[1])
                              if measured else []) if p["pod_id"] != taken]
        for parent in others[:law.other_parents]:
            child = child_from(session, parent=parent, number=number, hiring=hiring,
                               salt=f":{parent['pod_id']}")
            if child is not None:
                out.append({"design": "child", **child,
                            "model": child["model"] or hiring.models[0]})
    for model in dict.fromkeys(hiring.models):
        plain = {"model": model, **({"design": "plain"} if reproducing else {})}
        if plain not in out:
            out.append(plain)
    return [{"id": f"c{k}", "default": k == 1, "what": _describe(hire), "hire": hire}
            for k, hire in enumerate(out, start=1)]


def fill_from(opened_on: date, law: ManagementConfig) -> date:
    """The first morning the Runtime may fill a listed place: after the manager's days to pick."""
    return opened_on + timedelta(days=law.wait_days)


# --- the pick -----------------------------------------------------------------------------------

def _refuse(session: Session, *, vacancy_id: int, candidate: str, reason: str,
            actor: Agent) -> ManagementError:
    append_event(session, type=EVENT_HIRE_PICK_REFUSED, actor_agent_id=actor.id, payload={
        "vacancy_id": vacancy_id, "candidate": candidate, "reason": reason, "by": actor.name})
    session.commit()
    return ManagementError(409, reason)


def pick(session: Session, *, vacancy_id: int, candidate: str, brief: str,
         actor: Agent) -> dict[str, Any]:
    """The manager picks ``candidate`` for an open vacancy, with a brief for the new PM; commits.
    Returns the vacancy as it is now."""
    from app.capital.hiring import HiringError, vacancy

    brief = brief.strip()
    if len(brief) > MAX_BRIEF:
        raise ManagementError(422, f"a brief is at most {MAX_BRIEF} characters")
    with OMS_LOCK:     # no fill between the read and the pick
        try:
            found = vacancy(session, vacancy_id)
        except HiringError as exc:
            raise ManagementError(exc.status, exc.detail) from exc
        listed = found.get("candidates")
        if listed is None:
            raise _refuse(session, vacancy_id=vacancy_id, candidate=candidate, actor=actor,
                          reason=f"vacancy {vacancy_id} lists no candidates: the management law "
                                 "was off when its place was freed (the law's hire stands)")
        if found["status"] != "open":
            raise _refuse(session, vacancy_id=vacancy_id, candidate=candidate, actor=actor,
                          reason=f"vacancy {vacancy_id} is already filled")
        if found.get("picked") is not None:
            raise _refuse(session, vacancy_id=vacancy_id, candidate=candidate, actor=actor,
                          reason=f"vacancy {vacancy_id} already has its pick "
                                 f"({found['picked']['candidate']}): a place is picked once")
        if candidate not in {c["id"] for c in listed}:
            raise _refuse(session, vacancy_id=vacancy_id, candidate=candidate, actor=actor,
                          reason=f"{candidate!r} is not a candidate of vacancy {vacancy_id} "
                                 f"(its list: {', '.join(c['id'] for c in listed)})")
        append_event(session, type=EVENT_HIRE_PICKED, actor_agent_id=actor.id, payload={
            "vacancy_id": vacancy_id, "candidate": candidate, "brief": brief,
            "by": actor.id, "by_name": actor.name})
        session.commit()
        return vacancy(session, vacancy_id)


# --- the direction ------------------------------------------------------------------------------

def set_direction(session: Session, *, text: str, actor: Agent) -> dict[str, Any]:
    """The manager writes the firm's direction; commits."""
    text = text.strip()
    if not text or len(text) > MAX_DIRECTION:
        raise ManagementError(422, f"a direction is 1 to {MAX_DIRECTION} characters")
    append_event(session, type=EVENT_DIRECTION_SET, actor_agent_id=actor.id, payload={
        "direction_no": len(_events(session, EVENT_DIRECTION_SET)) + 1, "text": text,
        "by": actor.id, "by_name": actor.name})
    session.commit()
    return direction(session)


def direction(session: Session) -> dict[str, Any] | None:
    """The firm's latest direction, ``None`` while none is written."""
    last = session.scalar(select(Event).where(Event.type == EVENT_DIRECTION_SET)
                          .order_by(Event.id.desc()).limit(1))
    if last is None:
        return None
    p = last.payload_json
    return {"direction_no": p["direction_no"], "text": p["text"], "by": p["by_name"],
            "set_on": last.ts.date().isoformat()}


def brief_of(session: Session, pod_id: int) -> dict[str, Any] | None:
    """The manager's brief to the PM hired into ``pod_id`` (``None``: no pick made its hire)."""
    from app.capital.hiring import vacancies

    found = next((v for v in vacancies(session) if (v.get("picked") or {}).get("brief")
                  and v["filled"] is not None and v["filled"]["pod_id"] == pod_id), None)
    if found is None:
        return None
    p = found["picked"]
    return {"text": p["brief"], "by": p["by"], "on": p["on"], "candidate": p["candidate"],
            "what": next(c["what"] for c in found["candidates"] if c["id"] == p["candidate"])}


# --- the board ----------------------------------------------------------------------------------

def board(session: Session) -> dict[str, Any]:
    """Every pod not closed and the firm's centre, as the ledger and the market say now."""
    from app.capital.hiring import hiring_law, live_pods, vacancies
    from app.capital.reproduction import design_of
    from app.capital.service import book, capital_view
    from app.metrics.metering import metered_by_agent
    from app.oms.portfolio import build_portfolio

    now = ledger_now(session)
    machine = book(session)
    scores = {r["pod_id"]: r for r in capital_view(session, pod_id=None, cross=True)["pods"]}
    costs: dict[int | None, float] = {}
    for row in metered_by_agent(session).values():
        costs[row.pod_id] = costs.get(row.pod_id, 0.0) + row.usd_micros / 1e6
    last = session.scalar(select(Event).where(Event.type == EVENT_GENERATION_ENDED)
                          .order_by(Event.id.desc()).limit(1))
    measured = {} if last is None else {r["pod_id"]: r for r in last.payload_json["pods"]}
    pods = []
    for pod in session.scalars(select(Pod).where(Pod.status != "closed").order_by(Pod.id)):
        staff = list(session.scalars(select(Agent).where(
            Agent.pod_id == pod.id, Agent.status == AgentStatus.active).order_by(Agent.id)))
        book_ = build_portfolio(session, pod_id=pod.id, now=now)
        value = book_.total_value
        mv = [p.market_value or 0.0 for p in book_.positions]
        entry = machine["pods"].get(pod.id)
        score = (scores.get(pod.id) or {}).get("last_score") or {}
        row = measured.get(pod.id)
        design = design_of(session, pod.id)
        pods.append({
            "pod_id": pod.id, "pod_name": pod.name, "stage": pod.status,
            "pms": [a.name for a in staff if a.role == AgentRole.pm],
            "team": [a.name for a in staff if a.role == AgentRole.analyst],
            "cash_usd": book_.cash,
            "positions": [{"ticker": p.ticker, "qty": p.qty, "market_value_usd": p.market_value}
                          for p in book_.positions],
            "total_value_usd": value,
            # Statistics without a book are null, not 0.
            "gross_exposure": (sum(abs(x) for x in mv) / value) if value > 0 else None,
            "net_exposure": (sum(mv) / value) if value > 0 else None,
            "pricing_errors": book_.pricing_errors,
            "seeded": entry is not None,
            "capital_from_centre_usd": entry["allocated"] if entry else None,
            "drawdown": score.get("drawdown"),
            "thinking_usd": costs.get(pod.id, 0.0),
            "last_generation": None if row is None else {
                k: row.get(k) for k in ("pnl_usd", "thinking_usd", "fitness_usd", "verdict")},
            "design": {"model": design["model"], "family": design["family"]["pod_name"],
                       "rule": design["rule"]}})
    law = hiring_law(session)
    return {
        "as_of": now.isoformat(),
        "centre": {"cash_usd": machine["centre_cash"],
                   # Thinking no pod holds (the manager's): the centre's cost.
                   "thinking_usd": costs.get(None, 0.0)},
        "live_pods": live_pods(session), "max_live_pods": law.max_live_pods,
        "generation": None if last is None else last.payload_json["generation"],
        "open_vacancies": [{"id": v["id"], "pod_name": v["pod_name"],
                            "fill_from": v.get("fill_from"), "picked": v.get("picked")}
                           for v in vacancies(session) if v["status"] == "open"],
        "direction": direction(session),
        "pods": pods}
