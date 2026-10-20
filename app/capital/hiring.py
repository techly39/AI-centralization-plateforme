"""Hiring as physics (idea: a dead pod is replaced). High turnover is the heart of a multi-manager
fund: a pod the risk ladder closes is replaced by a new PM who must pitch to earn capital.

1. **The vacancy.** When the ladder closes a pod (:mod:`app.capital.service`), the same transaction
   writes ``vacancy_opened``: the dead pod, its **post-mortem** (:func:`post_mortem`, a pure
   function of the ledger at the close) and the **hire** the law names: the new pod's and PM's
   names, the model (the law's pool, in turn), the thinking budget and the charter. The hiring law
   (``hiring:`` in ``config.yaml``) is frozen into the run's first vacancy and every later one
   repeats it, so a run is judged by the law it hired with. A halved or reduce-only pod opens none.
2. **The fill.** A registrar (``register_agents``: management, the Runtime's onboarding) fills an
   open vacancy: physics makes the new pod and its PM (``agent_registered``, then
   ``vacancy_filled``) and hands the PM's key back once. Refused, in the ledger (``hire_refused``),
   when the firm already has its law's number of live pods; a vacancy is filled once. Only a
   registrar the operator made fills or refuses (the API's check): a firm mind does not hire.
   A hired PM deactivated before its pod earns a seed is a failed hire (``hire_failed``): its
   empty pod is closed and the vacancy opens again. The new pod has no capital: its PM pitches, and an eligible pitch earns
   a seed at the next sweep like any other.
3. **The refusal.** The cap on thinking is the Runtime's law, not physics': when the hire's budget
   does not fit it, the Runtime says so (``POST /vacancies/{id}/refuse``) and the vacancy stays
   open, in the ledger, for a later morning.

Nothing here moves money. Pods and agents are rows the hire creates; the ledger names each one
(``vacancy_filled``, ``agent_registered``), so an audit finds every hired pod's origin.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.capital.allocation import PodTrack, worst_drawdown
from app.config import HiringConfig, get_settings
from app.db.models import Agent, AgentRole, AgentStatus, Event, Pod
from app.ledger.events import (
    EVENT_ALLOCATION_SET,
    EVENT_CAPITAL_SEEDED,
    EVENT_HIRE_FAILED,
    EVENT_HIRE_REFUSED,
    EVENT_PITCH_SUBMITTED,
    EVENT_POD_STAGE_CHANGED,
    EVENT_VACANCY_FILLED,
    EVENT_VACANCY_OPENED,
    append_event,
)
from app.oms.service import OMS_LOCK
from app.registry.pods import create_pod
from app.registry.service import register_agent

SOURCE = "capital"   # app.capital.service.SOURCE (that module imports this one)
#: The longest reason a refusal may carry.
MAX_REASON = 200
#: How many ``hire-<n>-<k>`` names a fill tries before it is refused.
MAX_NAME_TRIES = 100


class HiringError(Exception):
    """A fill or a refusal physics will not do. ``status`` is the HTTP answer."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def hiring_law(session: Session) -> HiringConfig:
    """The law this run hires by: the one frozen into its first vacancy, else today's."""
    first = session.scalar(select(Event).where(Event.type == EVENT_VACANCY_OPENED)
                           .order_by(Event.id).limit(1))
    if first is None:
        return get_settings().hiring
    return HiringConfig.model_validate(first.payload_json["law"])


def live_pods(session: Session) -> int:
    """Pods that are not closed."""
    return int(session.scalar(select(func.count()).select_from(Pod)
                              .where(Pod.status != "closed")) or 0)


# --- the post-mortem ----------------------------------------------------------------------------

def post_mortem(session: Session, *, pod_id: int, record: PodTrack) -> dict[str, Any]:
    """What the dead pod was and how it died, from the ledger alone, at the close: the pitch the
    centre funded (hypothesis and rule), its forward days and their return, the ladder's steps with
    the drawdown at each, the capital put in and taken back, and its thinking cost since the seed.
    Its successor reads it (``GET /vacancies/{id}``) and the Runtime hands it to the first wake."""
    pod = session.get(Pod, pod_id)
    seed = next(e for e in _events(session, EVENT_CAPITAL_SEEDED)
                if e.payload_json["pod_id"] == pod_id)
    pitch = session.get(Event, seed.payload_json["pitch_id"])
    pitched = pitch.payload_json if pitch is not None and pitch.type == EVENT_PITCH_SUBMITTED else {}
    ladder = [{"on": e.ts.date().isoformat(), "from": e.payload_json["from"],
               "to": e.payload_json["to"], "drawdown": e.payload_json["drawdown"],
               "worst_drawdown": e.payload_json.get("worst_drawdown")}
              for e in _events(session, EVENT_POD_STAGE_CHANGED)
              if e.payload_json["pod_id"] == pod_id]
    flows = [float(e.payload_json["delta"]) for e in _events(session, EVENT_ALLOCATION_SET)
             if e.payload_json["pod_id"] == pod_id and e.payload_json.get("source") == SOURCE]
    growth = math.prod(1.0 + r for r in record.returns) if record.returns else None
    pms = sorted(a.name for a in session.scalars(select(Agent).where(
        Agent.pod_id == pod_id, Agent.role == AgentRole.pm)))
    return {
        "pod_id": pod_id, "pod_name": pod.name if pod is not None else None, "pms": pms,
        "pitch": {"pitch_id": seed.payload_json["pitch_id"],
                  "hypothesis": pitched.get("hypothesis"), "rule": seed.payload_json["rule"]},
        "seeded_on": seed.ts.date().isoformat(),
        "closed_on": ladder[-1]["on"] if ladder else None,
        "forward_days": len(record.returns),
        # Statistics without history are null, not 0.
        "forward_return": None if growth is None else growth - 1.0,
        "worst_drawdown": worst_drawdown(record.returns) if record.returns else None,
        "ladder": ladder,
        "capital": {"put_in_usd": sum(f for f in flows if f > 0),
                    "taken_back_usd": -sum(f for f in flows if f < 0)},
        "thinking_cost_usd": record.cost_usd,
    }


# --- the vacancy --------------------------------------------------------------------------------

def open_vacancy(session: Session, *, pod_id: int, record: PodTrack, actor: Agent) -> Event:
    """Write the vacancy a closed pod leaves: its post-mortem and the hire the law names. Called by
    the capital machine in the close's own transaction (under :data:`OMS_LOCK`)."""
    law = hiring_law(session)
    number = len(_events(session, EVENT_VACANCY_OPENED)) + 1
    hire = {"pod_name": f"hire-{number}", "pm_name": f"hire-{number}-pm", "role": "pm",
            "model": law.models[(number - 1) % len(law.models)], "budget_usd": law.budget_usd,
            "charter": law.charter}
    return append_event(session, type=EVENT_VACANCY_OPENED, actor_agent_id=actor.id, payload={
        "vacancy_no": number, "pod_id": pod_id,
        "pod_name": session.get(Pod, pod_id).name,
        "post_mortem": post_mortem(session, pod_id=pod_id, record=record),
        "hire": hire, "law": law.model_dump(mode="json")})


def vacancies(session: Session) -> list[dict[str, Any]]:
    """Every vacancy of the run, oldest first, folded from the ledger: ``status`` is ``open`` or
    ``filled``; ``filled`` names the new pod and PM; ``refusals`` lists every refused hire."""
    out: dict[int, dict[str, Any]] = {}
    for event in _events(session, EVENT_VACANCY_OPENED, EVENT_VACANCY_FILLED, EVENT_HIRE_REFUSED,
                         EVENT_HIRE_FAILED):
        p = event.payload_json
        if event.type != EVENT_VACANCY_OPENED and p.get("vacancy_id") not in out:
            continue    # names no vacancy of this run: nothing to fold (never fails the read)
        if event.type == EVENT_VACANCY_OPENED:
            out[event.id] = {"id": event.id, "vacancy_no": p["vacancy_no"],
                             "opened_on": event.ts.date().isoformat(), "pod_id": p["pod_id"],
                             "pod_name": p["pod_name"], "status": "open", "hire": p["hire"],
                             "post_mortem": p["post_mortem"], "filled": None, "refusals": [],
                             "failed": []}
        elif event.type == EVENT_HIRE_FAILED:
            out[p["vacancy_id"]]["status"] = "open"
            out[p["vacancy_id"]]["filled"] = None
            out[p["vacancy_id"]]["failed"].append(
                {"on": event.ts.date().isoformat(), "pod_id": p["pod_id"],
                 "agent_id": p["agent_id"], "reason": p["reason"]})
        elif event.type == EVENT_VACANCY_FILLED:
            out[p["vacancy_id"]]["status"] = "filled"
            out[p["vacancy_id"]]["filled"] = {
                "on": event.ts.date().isoformat(), "pod_id": p["pod_id"],
                "pod_name": p["pod_name"], "agent_id": p["agent_id"],
                "agent_name": p["agent_name"]}
        else:
            out[p["vacancy_id"]]["refusals"].append(
                {"on": event.ts.date().isoformat(), "reason": p["reason"], "by": p["by"]})
    return list(out.values())


def vacancy(session: Session, vacancy_id: int) -> dict[str, Any]:
    found = next((v for v in vacancies(session) if v["id"] == vacancy_id), None)
    if found is None:
        raise HiringError(404, f"no vacancy {vacancy_id}")
    return found


def _refuse(session: Session, *, vacancy_id: int, reason: str, actor: Agent) -> None:
    append_event(session, type=EVENT_HIRE_REFUSED, actor_agent_id=actor.id,
                 payload={"vacancy_id": vacancy_id, "reason": reason, "by": actor.name})


def fill(session: Session, *, vacancy_id: int, actor: Agent) -> tuple[dict[str, Any], Agent, str]:
    """Fill an open vacancy: the new pod, its PM, ``vacancy_filled``; commits. Returns the vacancy
    as it is now, the PM and its plaintext key (handed out once, as ``/agents/register`` does).
    A refusal physics decides (the pod limit) is written to the ledger, then raised. The names are
    the law's (``hire-<n>``, ``hire-<n>-pm``), or the first free ``hire-<n>-<k>`` when someone
    already took them (red-team: a name squatted in advance must not block the vacancy)."""
    with OMS_LOCK:  # one fill at a time, and none while a sweep closes pods
        try:
            found = vacancy(session, vacancy_id)
            if found["status"] != "open":
                raise HiringError(409, f"vacancy {vacancy_id} is already filled")
            law = hiring_law(session)
            hire = found["hire"]
            problem = None
            names = _free_names(session, hire["pod_name"])
            if live_pods(session) >= law.max_live_pods:
                problem = (f"the firm is at its limit of {law.max_live_pods} live pods "
                           f"(the hiring law)")
            elif names is None:
                problem = f"no free name for the hire after {hire['pod_name']!r}"
            if problem is not None:
                _refuse(session, vacancy_id=vacancy_id, reason=problem, actor=actor)
                session.commit()
                raise HiringError(409, problem)
            pod_name, pm_name = names
            pod = create_pod(session, name=pod_name)
            agent, key = register_agent(session, name=pm_name, role=AgentRole.pm,
                                        pod_id=pod.id, charter_ref=f"vacancy:{vacancy_id}",
                                        actor_agent_id=actor.id)
            append_event(session, type=EVENT_VACANCY_FILLED, actor_agent_id=actor.id, payload={
                "vacancy_id": vacancy_id, "pod_id": pod.id, "pod_name": pod.name,
                "agent_id": agent.id, "agent_name": agent.name, "model": hire["model"],
                "budget_usd": hire["budget_usd"]})
            session.commit()
            return vacancy(session, vacancy_id), agent, key
        except HiringError:
            raise
        except Exception:
            session.rollback()
            raise


def _free_names(session: Session, base: str) -> tuple[str, str] | None:
    """``(pod name, PM name)``: the law's, else the first ``<base>-<k>`` pair nobody holds."""
    taken = ({n.casefold() for n in session.scalars(select(Pod.name))},
             {n.casefold() for n in session.scalars(select(Agent.name))})
    for k in range(1, MAX_NAME_TRIES + 1):
        pod_name = base if k == 1 else f"{base}-{k}"
        if pod_name.casefold() not in taken[0] and f"{pod_name}-pm".casefold() not in taken[1]:
            return pod_name, f"{pod_name}-pm"
    return None


def hire_failed(session: Session, *, agent: Agent, actor: Agent | None) -> Event | None:
    """A hired PM was deactivated before its pod earned a seed, and no one else works there: the
    hire failed. Its empty pod is closed (it holds no money: nothing to recall, and it no longer
    holds a live-pod place) and the vacancy is open again for a new hire (red-team: a dead hire
    must not leave the dead pod unreplaced). The caller owns the transaction. ``None``: nothing to
    do (not the current hire of an open-for-business vacancy, money in the pod, or a colleague
    still active).

    A hire is known from the ledger only: the vacancy whose standing fill names this agent and
    its pod. Never from ``charter_ref``, which any registrar writes (auditor: a forged
    ``vacancy:<id>`` broke the vacancy list for good, made an agent no one could deactivate, and
    reopened a filled vacancy for a second hire)."""
    if agent.pod_id is None:
        return None
    current = next((v for v in vacancies(session) if v["status"] == "filled"
                    and v["filled"]["agent_id"] == agent.id
                    and v["filled"]["pod_id"] == agent.pod_id), None)
    if current is None:
        return None
    pod = session.get(Pod, agent.pod_id)
    if pod is None or pod.status == "closed":
        return None
    # Money in the pod, from the machine or anyone: not an empty pod, so not this law's to close.
    if any(e.payload_json.get("pod_id") == pod.id
           for e in _events(session, EVENT_CAPITAL_SEEDED, EVENT_ALLOCATION_SET)):
        return None
    if session.scalar(select(func.count()).select_from(Agent).where(
            Agent.pod_id == pod.id, Agent.status == AgentStatus.active)):
        return None
    pod.status = "closed"
    return append_event(session, type=EVENT_HIRE_FAILED,
                        actor_agent_id=actor.id if actor is not None else None, payload={
                            "vacancy_id": current["id"], "pod_id": pod.id,
                            "agent_id": agent.id,
                            "reason": "its hired PM was deactivated before any seed"})


def refuse(session: Session, *, vacancy_id: int, reason: str, actor: Agent) -> dict[str, Any]:
    """The Runtime's refusal of a hire (its budget does not fit the cap): written, the vacancy
    stays open; commits."""
    reason = " ".join(reason.split())
    if not reason or len(reason) > MAX_REASON:
        raise HiringError(422, f"a reason is 1 to {MAX_REASON} characters")
    with OMS_LOCK:
        found = vacancy(session, vacancy_id)
        if found["status"] != "open":
            raise HiringError(409, f"vacancy {vacancy_id} is already filled")
        _refuse(session, vacancy_id=vacancy_id, reason=reason, actor=actor)
        session.commit()
        return vacancy(session, vacancy_id)
