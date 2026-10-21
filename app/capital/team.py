"""Teams as physics (idea: pods, a PM and a small team; first slice, a PM builds its team). Until
now every mind was a PM and every decision about people a law. Here a PM decides that another
agent exists: it asks for an analyst it describes, and pays for it from its pod.

1. **The request.** A PM of a living pod asks for an analyst (``POST /team/analysts``): a charter
   in its own words, a model from the team law's pool, a thinking budget. Physics grants it
   (``team_place_opened``, the law frozen into the run's first) or refuses it by name
   (``team_request_refused``): the law is off, the pod is closed, the model is not in the pool,
   the pod already holds its law's number of analysts (working or waiting), the budget does not
   fit what is left of the pod's team budget, or one more agent would pass the Human's agent cap
   (the places still waiting count as agents).
2. **The fill.** The next morning a registrar (the Runtime's onboarding) fills the place: physics
   makes the analyst in the PM's own pod (``agent_registered``, then ``team_place_filled``) and
   hands its key back once; the Runtime mints its thinking key with the granted budget as its
   limit, under the cap, or refuses the hire (``team_hire_refused``: the place stays open). Only
   the operator's registrar fills or refuses (:func:`app.registry.permissions.may_hire`). A place
   whose PM or pod is gone before the fill is closed (``team_place_closed``), never filled.
3. **The work.** An analyst researches (its backtests carry its pod, so they are the pod's
   attempts at the PM's next pitch), reads the library and messages; the permission matrix
   refuses it pitches, orders and team requests. Its metered thinking carries its pod, so it
   lowers the pod's fitness and the capital score like the PM's own.
4. **Letting go.** The PM lets an analyst go, or withdraws a place not yet filled
   (``POST /team/places/{id}/let-go``). When the pod's last PM goes (let go, deactivated) or the
   risk ladder closes the pod, its team goes too (:func:`team_follows`): ``team_member_let_go``
   for each analyst, ``team_place_closed`` for each place still waiting.

A pod's team budget counts each analyst's key limit while it works or waits, and what it spent
once it is gone (the rest of a dead key is never spent, so it is not counted). Nothing here moves
money.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TeamConfig, get_settings
from app.db.models import Agent, AgentRole, AgentStatus, Event, Pod
from app.ledger.events import (
    EVENT_TEAM_HIRE_REFUSED,
    EVENT_TEAM_MEMBER_LET_GO,
    EVENT_TEAM_PLACE_CLOSED,
    EVENT_TEAM_PLACE_FILLED,
    EVENT_TEAM_PLACE_OPENED,
    EVENT_TEAM_REQUEST_REFUSED,
    append_event,
)
from app.metrics.metering import metered_by_agent
from app.oms.service import OMS_LOCK
from app.registry.permissions import may_hire
from app.registry.population import over_cap
from app.registry.service import deactivate_agent, register_agent

#: The longest charter a PM may write for its analyst.
MAX_CHARTER = 2000
#: The longest refusal reason the Runtime may write.
MAX_REASON = 200
MAX_NAME_TRIES = 100
_TYPES = (EVENT_TEAM_PLACE_OPENED, EVENT_TEAM_PLACE_FILLED, EVENT_TEAM_HIRE_REFUSED,
          EVENT_TEAM_PLACE_CLOSED, EVENT_TEAM_MEMBER_LET_GO)


class TeamError(Exception):
    """A request, fill or letting-go physics will not do. ``status`` is the HTTP answer."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def team_law(session: Session) -> TeamConfig:
    """The law this run builds teams by: the one frozen into its first granted request, else
    today's."""
    first = session.scalar(select(Event).where(Event.type == EVENT_TEAM_PLACE_OPENED)
                           .order_by(Event.id).limit(1))
    if first is None:
        return get_settings().team
    return TeamConfig.model_validate(first.payload_json["law"])


# --- the places, folded from the ledger ---------------------------------------------------------

def places(session: Session, pod_id: int | None = None) -> list[dict[str, Any]]:
    """Every team place of the run (of ``pod_id``), oldest first. ``status``: ``open`` (granted,
    waiting for the morning's hire), ``working``, ``let_go`` or ``closed`` (never filled)."""
    out: dict[int, dict[str, Any]] = {}
    for event in _events(session, *_TYPES):
        p = event.payload_json
        if event.type == EVENT_TEAM_PLACE_OPENED:
            out[event.id] = {
                "id": event.id, "place_no": p["place_no"], "pod_id": p["pod_id"],
                "pod_name": p["pod_name"], "opened_on": event.ts.date().isoformat(),
                "asked_by": p["asked_by"], "asked_by_name": p["asked_by_name"],
                "name": p["name"], "role": p["role"], "model": p["model"],
                "budget_usd": p["budget_usd"], "charter": p["charter"], "status": "open",
                "member": None, "refusals": [], "ended": None}
            continue
        place = out.get(p.get("place_id"))
        if place is None:
            continue    # names no place of this run: nothing to fold (never fails the read)
        on = event.ts.date().isoformat()
        if event.type == EVENT_TEAM_PLACE_FILLED:
            place["status"] = "working"
            place["member"] = {"agent_id": p["agent_id"], "agent_name": p["agent_name"],
                               "hired_on": on}
        elif event.type == EVENT_TEAM_HIRE_REFUSED:
            place["refusals"].append({"on": on, "reason": p["reason"], "by": p["by"]})
        elif event.type == EVENT_TEAM_PLACE_CLOSED:
            place["status"] = "closed"
            place["ended"] = {"on": on, "reason": p["reason"]}
        else:
            place["status"] = "let_go"
            place["ended"] = {"on": on, "reason": p["reason"], "by": p["by"]}
    found = list(out.values())
    return found if pod_id is None else [x for x in found if x["pod_id"] == pod_id]


def place(session: Session, place_id: int) -> dict[str, Any]:
    found = next((x for x in places(session) if x["id"] == place_id), None)
    if found is None:
        raise TeamError(404, f"no team place {place_id}")
    return found


def team_members(session: Session, pod_id: int) -> set[int]:
    """The agent ids the pod's team places hired (working or gone): known from the ledger only,
    never from a charter_ref a registrar writes."""
    return {x["member"]["agent_id"] for x in places(session, pod_id) if x["member"] is not None}


def _spent(session: Session) -> dict[int, int]:
    return {agent: row.usd_micros for agent, row in metered_by_agent(session).items()}


def budget_used(session: Session, pod_id: int, held: list[dict[str, Any]] | None = None) -> float:
    """USD of the pod's team budget taken: a waiting or working analyst's key limit, a gone one's
    spending."""
    spent = _spent(session)
    used = 0.0
    for x in places(session, pod_id) if held is None else held:
        if x["status"] in ("open", "working"):
            used += float(x["budget_usd"])
        elif x["member"] is not None:
            used += min(float(x["budget_usd"]), spent.get(x["member"]["agent_id"], 0) / 1e6)
    return used


def team_of(session: Session, pod_id: int) -> dict[str, Any]:
    """The pod's team as its PM and analysts read it (``GET /team``): the law, every place, the
    team budget taken and left, and every request physics refused."""
    law = team_law(session)
    held = places(session, pod_id)
    spent = _spent(session)
    for x in held:
        x["spent_usd"] = (None if x["member"] is None
                          else spent.get(x["member"]["agent_id"], 0) / 1e6)
    used = budget_used(session, pod_id, held)
    refused = [{"on": e.ts.date().isoformat(), "asked_by": e.payload_json["agent_id"],
                "reason": e.payload_json["reason"], "asked": e.payload_json["asked"]}
               for e in _events(session, EVENT_TEAM_REQUEST_REFUSED)
               if e.payload_json.get("pod_id") == pod_id]
    return {
        "pod_id": pod_id, "law_on": law.on,
        "law": (f"A PM may ask for an analyst (request_analyst): a charter in its own words, a "
                f"model from {list(law.models)}, a thinking budget. The pod holds at most "
                f"{law.max_analysts} analysts (working or waiting); all its analysts' keys "
                f"together may hold ${law.budget_usd:.2f} (a let-go analyst counts what it spent). "
                f"A granted analyst is hired the next morning into your pod. It researches (its "
                f"backtests are your pod's attempts at your next pitch), reads the library and "
                f"messages; it cannot pitch, trade or ask for analysts. Its thinking is your "
                f"pod's: it lowers your fitness and capital score. Let it go with "
                f"let_go_analyst." if law.on else "The team law is off in this firm."),
        "max_analysts": law.max_analysts, "models": list(law.models),
        "budget_usd": law.budget_usd, "budget_used_usd": used,
        "budget_left_usd": max(0.0, law.budget_usd - used),
        "analysts_held": sum(1 for x in held if x["status"] in ("open", "working")),
        "places": held, "refused": refused}


# --- the request --------------------------------------------------------------------------------

def _refuse_request(session: Session, *, actor: Agent, reason: str, asked: dict[str, Any]) -> None:
    append_event(session, type=EVENT_TEAM_REQUEST_REFUSED, actor_agent_id=actor.id, payload={
        "pod_id": actor.pod_id, "agent_id": actor.id, "reason": reason, "asked": asked})
    session.commit()
    raise TeamError(409, reason)


def request_analyst(session: Session, *, actor: Agent, charter: str, model: str,
                    budget_usd: float) -> dict[str, Any]:
    """A PM asks for an analyst: granted (the open place) or refused by name, written; commits.
    The caller has checked the role (``Action.REQUEST_TEAM``)."""
    charter = charter.strip()
    if not charter or len(charter) > MAX_CHARTER:
        raise TeamError(422, f"a charter is 1 to {MAX_CHARTER} characters")
    asked = {"model": model, "budget_usd": budget_usd}
    with OMS_LOCK:   # one request at a time, and none while a sweep closes pods
        try:
            law = team_law(session)
            pod = session.get(Pod, actor.pod_id) if actor.pod_id is not None else None
            held = places(session, actor.pod_id) if pod is not None else []
            waiting = sum(1 for x in places(session) if x["status"] == "open")
            reason = None
            if not law.on:
                reason = "the team law is off in this firm: no PM may ask for analysts"
            elif actor.role != AgentRole.pm or actor.status != AgentStatus.active or pod is None:
                reason = "only an active PM of a pod asks for analysts"
            elif pod.status == "closed":
                reason = "your pod is closed: a closed pod hires no one"
            elif model not in law.models:
                reason = f"the model {model!r} is not in the team law's pool {list(law.models)}"
            elif sum(1 for x in held if x["status"] in ("open", "working")) >= law.max_analysts:
                reason = (f"your pod already holds {law.max_analysts} analysts (working or "
                          f"waiting): the team law's limit")
            elif budget_used(session, pod.id, held) + budget_usd > law.budget_usd + 1e-9:
                left = max(0.0, law.budget_usd - budget_used(session, pod.id, held))
                reason = (f"a ${budget_usd:.2f} budget does not fit: ${left:.2f} is left of your "
                          f"pod's ${law.budget_usd:.2f} team budget")
            elif (over := over_cap(session, adding=waiting + 1)) is not None:
                reason = f"{over}; {waiting} granted analysts are still waiting to be hired"
            if reason is not None:
                _refuse_request(session, actor=actor, reason=reason, asked=asked)
            number = sum(1 for x in held) + 1
            event = append_event(session, type=EVENT_TEAM_PLACE_OPENED, actor_agent_id=actor.id,
                                 payload={
                                     "place_no": number, "pod_id": pod.id, "pod_name": pod.name,
                                     "asked_by": actor.id, "asked_by_name": actor.name,
                                     "name": f"{pod.name}-analyst-{number}", "role": "analyst",
                                     "model": model, "budget_usd": budget_usd,
                                     "charter": charter, "law": law.model_dump(mode="json")})
            session.commit()
            return place(session, event.id)
        except TeamError:
            raise
        except Exception:
            session.rollback()
            raise


# --- the fill -----------------------------------------------------------------------------------

def _pm_gone(session: Session, x: dict[str, Any]) -> str | None:
    """Why the place's pod can no longer hire, else ``None``."""
    pod = session.get(Pod, x["pod_id"])
    if pod is None or pod.status == "closed":
        return "its pod is closed"
    asker = session.get(Agent, x["asked_by"])
    if asker is None or asker.status != AgentStatus.active or asker.pod_id != x["pod_id"]:
        return "the PM who asked for it is gone"
    return None


def _free_name(session: Session, base: str) -> str | None:
    taken = {n.casefold() for n in session.scalars(select(Agent.name))}
    for k in range(1, MAX_NAME_TRIES + 1):
        name = base if k == 1 else f"{base}-{k}"
        if name.casefold() not in taken:
            return name
    return None


def fill(session: Session, *, place_id: int, actor: Agent) -> tuple[dict[str, Any], Agent, str]:
    """Fill an open team place: the analyst in its PM's pod, ``team_place_filled``; commits.
    Returns the place, the analyst and its plaintext key (once). A place whose PM or pod is gone is
    closed (409); one more agent past the Human's cap is refused (409, the place stays open)."""
    if not may_hire(session, actor):
        raise TeamError(403, "only the operator's registrar hires: a firm mind does not fill or "
                             "refuse a team place")
    with OMS_LOCK:
        try:
            x = place(session, place_id)
            if x["status"] != "open":
                raise TeamError(409, f"team place {place_id} is {x['status']}, not open")
            if (gone := _pm_gone(session, x)) is not None:
                append_event(session, type=EVENT_TEAM_PLACE_CLOSED, actor_agent_id=actor.id,
                             payload={"place_id": place_id, "pod_id": x["pod_id"],
                                      "reason": gone})
                session.commit()
                raise TeamError(409, f"team place {place_id} is closed: {gone}")
            name = _free_name(session, x["name"])
            problem = over_cap(session) or (
                None if name is not None else f"no free name for the hire after {x['name']!r}")
            if problem is not None:
                append_event(session, type=EVENT_TEAM_HIRE_REFUSED, actor_agent_id=actor.id,
                             payload={"place_id": place_id, "reason": problem, "by": actor.name})
                session.commit()
                raise TeamError(409, problem)
            agent, key = register_agent(session, name=name, role=AgentRole.analyst,
                                        pod_id=x["pod_id"], charter_ref=f"team:{place_id}",
                                        actor_agent_id=actor.id)
            append_event(session, type=EVENT_TEAM_PLACE_FILLED, actor_agent_id=actor.id, payload={
                "place_id": place_id, "pod_id": x["pod_id"], "agent_id": agent.id,
                "agent_name": agent.name, "model": x["model"], "budget_usd": x["budget_usd"]})
            session.commit()
            return place(session, place_id), agent, key
        except TeamError:
            raise
        except Exception:
            session.rollback()
            raise


def refuse(session: Session, *, place_id: int, reason: str, actor: Agent) -> dict[str, Any]:
    """The Runtime's refusal of a team hire (its key does not fit the cap): written, the place
    stays open; commits."""
    if not may_hire(session, actor):
        raise TeamError(403, "only the operator's registrar hires: a firm mind does not fill or "
                             "refuse a team place")
    reason = " ".join(reason.split())
    if not reason or len(reason) > MAX_REASON:
        raise TeamError(422, f"a reason is 1 to {MAX_REASON} characters")
    with OMS_LOCK:
        x = place(session, place_id)
        if x["status"] != "open":
            raise TeamError(409, f"team place {place_id} is {x['status']}, not open")
        append_event(session, type=EVENT_TEAM_HIRE_REFUSED, actor_agent_id=actor.id,
                     payload={"place_id": place_id, "reason": reason, "by": actor.name})
        session.commit()
        return place(session, place_id)


# --- letting go ---------------------------------------------------------------------------------

def _end(session: Session, x: dict[str, Any], *, reason: str, actor: Agent | None) -> Event | None:
    """End one place: a waiting place closes, a working analyst is deactivated and let go. The
    caller owns the transaction."""
    by = actor.id if actor is not None else None
    if x["status"] == "open":
        return append_event(session, type=EVENT_TEAM_PLACE_CLOSED, actor_agent_id=by, payload={
            "place_id": x["id"], "pod_id": x["pod_id"], "reason": reason})
    if x["status"] != "working":
        return None
    member = session.get(Agent, x["member"]["agent_id"])
    if member is not None and member.status != AgentStatus.inactive:
        deactivate_agent(session, agent_id=member.id, actor_agent_id=by)
    return append_event(session, type=EVENT_TEAM_MEMBER_LET_GO, actor_agent_id=by, payload={
        "place_id": x["id"], "pod_id": x["pod_id"], "agent_id": x["member"]["agent_id"],
        "agent_name": x["member"]["agent_name"], "reason": reason,
        "by": actor.name if actor is not None else None})


def let_go(session: Session, *, place_id: int, actor: Agent) -> dict[str, Any]:
    """The pod's PM lets its analyst go, or withdraws a place not yet filled; commits."""
    with OMS_LOCK:
        try:
            x = place(session, place_id)
        except TeamError:
            x = None
        if (x is None or actor.role != AgentRole.pm or actor.status != AgentStatus.active
                or actor.pod_id != x["pod_id"]):
            # Not found and not yours answer alike.
            raise TeamError(403, f"team place {place_id} is not one of your pod's")
        if x["status"] not in ("open", "working"):
            raise TeamError(409, f"team place {place_id} is {x['status']}")
        _end(session, x, reason="let go by its PM" if x["status"] == "working"
             else "withdrawn by its PM", actor=actor)
        session.commit()
        return place(session, place_id)


def team_follows(session: Session, *, pod_id: int, reason: str, actor: Agent | None,
                 force: bool = False) -> list[Event]:
    """The pod's team goes when its last PM goes (``force``: when the pod itself closes): every
    working analyst let go, every waiting place closed. The caller owns the transaction."""
    if not force and session.scalar(select(Agent.id).where(
            Agent.pod_id == pod_id, Agent.role == AgentRole.pm,
            Agent.status == AgentStatus.active).limit(1)) is not None:
        return []
    made = []
    for x in places(session, pod_id):
        if (ended := _end(session, x, reason=reason, actor=actor)) is not None:
            made.append(ended)
    return made
