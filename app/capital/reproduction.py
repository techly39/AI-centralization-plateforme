"""Reproduction as physics (idea: designs that work reproduce with variation; first slice, designs
reproduce). Selection alone removes what fails (:mod:`app.capital.generation`); nothing carried
what works forward. Off unless the run's law turns it on (``reproduction:`` in ``config.yaml``, or
a world's recipe), so every run recorded before it replays as it was.

1. **A pod's design** (:func:`design_of`) is on the record: its PM's model (a hire's, from its
   vacancy; a founding PM's, as its registrar declared it at registration) and its rule (the one
   the capital machine seeded, else its last eligible pitch, else its last pitch). Its **family**
   is its founder's pod: a child belongs to its parent's family, every other pod founds its own.
2. **The parent.** When a place is freed (:func:`child_of`, called as the vacancy opens), the
   parent is the fittest pod of the generation last measured (at a month's end, the one being
   measured) whose fitness is above zero and which is still alive (not closed, a PM still working
   there, not let go). Ties go to the older pod. No such pod: the hiring law's plain hire.
3. **The child** gets its parent's model and rule with **exactly one change**, drawn by
   ``random.Random(f"{seed}:{vacancy number}")`` from every change one step away: another model of
   the hiring law's pool, the lookback or the rebalance moved one rung of its ladder
   (:data:`LOOKBACKS`, :data:`REBALANCES`), or one name more or fewer held. The vacancy names the
   parent, the change and the inherited rule; the child reads them (``GET /vacancies/{id}``, its
   capital view). The rule is a starting point: the child still pitches and passes the gates.
4. **The family's attempts.** A rule chosen as the best of a family has been tried by the family:
   the vacancy freezes the parent's attempts as they stood (its own research and pitches, plus
   what it inherited), and every pitch of the child counts them in the deflated Sharpe's N
   (:func:`inherited_attempts`). Only the parent's line: a sibling's attempts are not counted
   (a known hole, ``tests/test_redteam_designs_reproduce.py``).
5. **Diversity.** Each month's end (:func:`diversity`) counts the distinct designs alive and the
   largest family's share of the live pods; when one family holds every live pod (two or more),
   that is written as a finding (``diversity_collapsed``).

Nothing here moves money or makes an agent: the vacancy's fill is the hiring law's.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import HiringConfig, ReproductionConfig, get_settings
from app.db.models import Agent, AgentRole, AgentStatus, Event, Pod
from app.ledger.events import (
    EVENT_AGENT_REGISTERED,
    EVENT_CAPITAL_SEEDED,
    EVENT_GENERATION_ENDED,
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_SUBMITTED,
    EVENT_VACANCY_FILLED,
    EVENT_VACANCY_OPENED,
)

#: The rungs a lookback moves along, one at a time (days of history behind a score).
LOOKBACKS = (5, 10, 20, 40, 60, 120, 250)
#: The rungs a rebalance moves along (days between rebalances).
REBALANCES = (1, 2, 5, 10, 21, 63)
#: The verdicts of a pod still alive after its month's end.
ALIVE = ("stays", "too_new")


def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def reproduction_law(session: Session) -> ReproductionConfig:
    """The law this run reproduces by: the one frozen into its first vacancy (absent there: off),
    else today's."""
    first = session.scalar(select(Event).where(Event.type == EVENT_VACANCY_OPENED)
                           .order_by(Event.id).limit(1))
    if first is None:
        return get_settings().reproduction
    return ReproductionConfig.model_validate(first.payload_json.get("reproduction") or {})


# --- a pod's design -----------------------------------------------------------------------------

def hire_of(session: Session, pod_id: int) -> dict[str, Any] | None:
    """The hire a vacancy named for the pod it filled, ``None`` for a pod no vacancy made."""
    filled = next((e for e in _events(session, EVENT_VACANCY_FILLED)
                   if e.payload_json.get("pod_id") == pod_id), None)
    if filled is None:
        return None
    opened = session.get(Event, filled.payload_json["vacancy_id"])
    if opened is None or opened.type != EVENT_VACANCY_OPENED:
        return None
    return opened.payload_json["hire"]


def _rule_of(session: Session, pod_id: int) -> dict[str, Any] | None:
    seed = next((e for e in _events(session, EVENT_CAPITAL_SEEDED)
                 if e.payload_json.get("pod_id") == pod_id), None)
    if seed is not None:
        return dict(seed.payload_json["rule"])
    eligible = {e.payload_json.get("pitch_id") for e in _events(session, EVENT_PITCH_JUDGED)
                if e.payload_json.get("eligible") is True}
    pitches = [e for e in _events(session, EVENT_PITCH_SUBMITTED)
               if e.payload_json.get("pod_id") == pod_id]
    best = [e for e in pitches if e.id in eligible] or pitches
    return dict(best[-1].payload_json["rule"]) if best else None


def design_of(session: Session, pod_id: int) -> dict[str, Any]:
    """The pod's design from the ledger: its PM's model, its rule, its family."""
    pod = session.get(Pod, pod_id)
    hire = hire_of(session, pod_id)
    if hire is not None:
        model = hire.get("model")
    else:   # a founding PM's, as registered (an agent never changes pod; only a PM's counts)
        model = next((e.payload_json["model"] for e in _events(session, EVENT_AGENT_REGISTERED)
                      if e.payload_json.get("pod_id") == pod_id
                      and e.payload_json.get("role") == "pm" and e.payload_json.get("model")),
                     None)
    family = (hire or {}).get("family") or {"pod_id": pod_id,
                                             "pod_name": pod.name if pod else None}
    return {"pod_id": pod_id, "pod_name": pod.name if pod else None, "model": model,
            "rule": _rule_of(session, pod_id), "family": family}


def _signature(design: dict[str, Any]) -> str:
    return json.dumps([design["model"], design["rule"]], sort_keys=True)


# --- the parent and the child -------------------------------------------------------------------

def _alive(session: Session, pod_id: int) -> bool:
    pod = session.get(Pod, pod_id)
    return pod is not None and pod.status != "closed" and session.scalar(
        select(Agent.id).where(Agent.pod_id == pod_id, Agent.status == AgentStatus.active,
                               Agent.role == AgentRole.pm)
        .limit(1)) is not None


def last_generation(session: Session) -> tuple[int, list[dict[str, Any]]] | None:
    last = session.scalar(select(Event).where(Event.type == EVENT_GENERATION_ENDED)
                          .order_by(Event.id.desc()).limit(1))
    return None if last is None else (last.payload_json["generation"], last.payload_json["pods"])


def choose_parent(session: Session, *, generation: int,
                  rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The fittest pod of ``rows`` (one generation's table) still alive with fitness above zero."""
    fit = [r for r in rows if r.get("verdict") in ALIVE and r.get("fitness_usd") is not None
           and r["fitness_usd"] > 0 and _alive(session, r["pod_id"])]
    if not fit:
        return None
    best = max(fit, key=lambda r: (r["fitness_usd"], -r["pod_id"]))
    return {"pod_id": best["pod_id"], "pod_name": best["pod_name"], "generation": generation,
            "fitness_usd": best["fitness_usd"]}


def _rungs(value: int, ladder: tuple[int, ...]) -> list[int]:
    lower = [x for x in ladder if x < value]
    higher = [x for x in ladder if x > value]
    return ([lower[-1]] if lower else []) + ([higher[0]] if higher else [])


def changes(design: dict[str, Any], models: tuple[str, ...]) -> list[dict[str, Any]]:
    """Every change one step away from ``design``, each a valid design (in a fixed order)."""
    from app.strategy.rule import StrategyRule

    out: list[dict[str, Any]] = []
    if design["model"] is not None:
        out += [{"what": "model", "from": design["model"], "to": m}
                for m in dict.fromkeys(models) if m != design["model"]]
    rule = design["rule"]
    if rule:
        steps = [("lookback", n) for n in _rungs(rule["lookback"], LOOKBACKS)]
        steps += [("rebalance_every", n) for n in _rungs(rule["rebalance_every"], REBALANCES)]
        steps += [("top_n", rule["top_n"] + d) for d in (-1, 1)]
        for key, value in steps:
            try:
                StrategyRule.model_validate({**rule, key: value})
            except ValueError:
                continue
            out.append({"what": key, "from": rule[key], "to": value})
    return out


def child_of(session: Session, *, number: int, hiring: HiringConfig,
             measured: tuple[int, list[dict[str, Any]]] | None = None) -> dict[str, Any] | None:
    """The child a vacancy (its ``number``) hires under the reproduction law: what goes into its
    ``hire`` besides names, budget and charter. ``measured``: the generation being measured
    (``(number, rows)``), else the last one written. ``None``: the law is off, no pod is fit, or
    the fittest has no change one step away (the plain hire)."""
    law = reproduction_law(session)
    if not law.on:
        return None
    measured = measured or last_generation(session)
    if measured is None:
        return None
    parent = choose_parent(session, generation=measured[0], rows=measured[1])
    if parent is None:
        return None
    design = design_of(session, parent["pod_id"])
    options = changes(design, hiring.models)
    if not options:
        return None
    change = random.Random(f"{law.seed}:{number}").choice(options)
    rule = design["rule"] and {**design["rule"], **({change["what"]: change["to"]}
                                                    if change["what"] != "model" else {})}
    from app.strategy.service import pod_attempts   # the gates read the capital machine

    return {"model": change["to"] if change["what"] == "model" else design["model"],
            "parent": {**parent, "model": design["model"], "rule": design["rule"]},
            "family": design["family"], "change": change, "inherited_rule": rule,
            "lineage_attempts": pod_attempts(session, parent["pod_id"])}


def inherited_attempts(session: Session, pod_id: int) -> int:
    """The research and pitches a child's family made before it was born (0 for any other pod)."""
    return int((hire_of(session, pod_id) or {}).get("lineage_attempts") or 0)


# --- diversity ----------------------------------------------------------------------------------

def diversity(session: Session, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The month's end's diversity: of the pods alive after it, how many distinct designs, how
    many pods each family holds, and the largest family's share (null with no live pod)."""
    live = [design_of(session, r["pod_id"]) for r in rows if r.get("verdict") in ALIVE]
    families = Counter(d["family"]["pod_name"] for d in live)
    largest = max(sorted(families), key=lambda f: families[f], default=None)
    return {"live_pods": len(live), "designs": len({_signature(d) for d in live}),
            "families": dict(sorted(families.items())), "largest_family": largest,
            "largest_share": None if not live else families[largest] / len(live),
            "collapsed": len(live) >= 2 and len(families) == 1}
