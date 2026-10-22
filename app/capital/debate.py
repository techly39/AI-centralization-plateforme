"""The debate as physics (idea: the pitch, then a full report; first slice, a pitch is argued before
its seed). Off unless the run's capital law sets ``debate_days`` (frozen into ``capital_opened``),
so every run recorded before it replays as it was.

1. **Opened by the sweep.** Under the law, the capital machine's sweep (:mod:`app.capital.service`)
   does not pay an eligible pitch's seed at once: the first time it would, it opens the pitch's
   debate (``debate_opened``) with the day it closes, ``debate_days`` later. Only a pitch the
   machine would seed is debated: one the gates found eligible (read from the ``pitch_judged``
   event physics writes), of a pod not closed and not seeded, with a long-only rule.
2. **The thread** (:func:`argue`): the firm's reviewers (role ``reviewer``, centre minds the
   operator makes) and the pitch's own PM write in it while it is open (``debate_argued``), at most
   :data:`MAX_POSTS` each. Nobody else, nowhere else.
3. **The verdict** (:func:`rule`): the firm's manager rules once, while it is open
   (``pitch_ruled``): ``seed`` (paid at the next sweep) or ``hold`` (the sweep refuses the seed,
   with the manager's reason, which the PM reads in its pitch's capital answer). Silent, the seed
   is paid at the first sweep on or after the closing day. The manager names no amount and cannot
   seed what the gates or the centre refuse: the sweep still checks the pod, the centre's cash and
   the copy gate as it pays.
4. Refusals are in the ledger (``debate_refused``), with the reason the caller reads.

Nothing here moves money: the sweep pays or refuses. A debate is folded from the ledger alone.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Agent, AgentRole, Event, Pod
from app.ledger.events import (
    EVENT_CAPITAL_SEED_REFUSED,
    EVENT_CAPITAL_SEEDED,
    EVENT_DEBATE_ARGUED,
    EVENT_DEBATE_OPENED,
    EVENT_DEBATE_REFUSED,
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_RULED,
    EVENT_PITCH_SUBMITTED,
    append_event,
    ledger_now,
)
from app.oms.service import OMS_LOCK

#: The longest post in a thread, and the longest reason for a verdict.
MAX_ARGUMENT = 2000
MAX_REASON = 1000
#: Posts one author may write in one debate.
MAX_POSTS = 5
VERDICTS = ("seed", "hold")


class DebateError(Exception):
    """An argument or a verdict physics will not take. ``status`` is the HTTP answer."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class NotYourDebate(Exception):
    """A PM reaching another pod's debate: the API answers 403 and logs it."""


def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def debate_days(session: Session) -> int:
    """The run's debate law: days an eligible pitch waits for its verdict (0: no debate)."""
    from app.capital.service import run_law

    return run_law(session).debate_days


# --- the debates, folded from the ledger ---------------------------------------------------------

def debates(session: Session) -> dict[int, dict[str, Any]]:
    """Every debate, by pitch id: ``{pitch_id, pod_id, opened_on, closes_on, thread, verdict,
    capital}`` (``verdict``/``capital``: ``None`` until ruled / until the sweep paid or refused)."""
    out: dict[int, dict[str, Any]] = {}
    for e in _events(session, EVENT_DEBATE_OPENED, EVENT_DEBATE_ARGUED, EVENT_PITCH_RULED,
                     EVENT_CAPITAL_SEEDED, EVENT_CAPITAL_SEED_REFUSED):
        p = e.payload_json
        if e.type == EVENT_DEBATE_OPENED:
            out[p["pitch_id"]] = {"pitch_id": p["pitch_id"], "pod_id": p["pod_id"],
                                  "opened_on": p["opened_on"], "closes_on": p["closes_on"],
                                  "thread": [], "verdict": None, "capital": None}
            continue
        d = out.get(p.get("pitch_id"))
        if d is None:
            continue
        on = e.ts.date().isoformat()
        if e.type == EVENT_DEBATE_ARGUED:
            d["thread"].append({"post_no": p["post_no"], "by": p["by_name"], "role": p["role"],
                                "on": on, "text": p["text"], "_by": p["by"]})
        elif e.type == EVENT_PITCH_RULED:
            d["verdict"] = {"verdict": p["verdict"], "reason": p["reason"], "by": p["by_name"],
                            "on": on}
            d["ruled_event"] = e.id
        elif e.type == EVENT_CAPITAL_SEEDED:
            d["capital"] = {"outcome": "seeded", "on": on, "seed_usd": p["seed_usd"]}
        else:
            d["capital"] = {"outcome": "refused", "on": on, "reason": p["reason"]}
    return out


def is_open(debate: dict[str, Any], today: date) -> bool:
    """May the thread still be written in and the verdict given? Until its closing day, while no
    verdict is given and the sweep has neither paid nor refused it."""
    return (debate["verdict"] is None and debate["capital"] is None
            and today.isoformat() < debate["closes_on"])


def debating_pods(session: Session) -> set[int]:
    """Pods whose pitch is in its debate now (open: before its closing day, no verdict, no capital
    answer): such a pod has not failed to earn a seed, its seed is being argued (the generation
    law does not judge it). A debate that closed but was not paid (the centre short, the copy
    check without data) shelters nothing: its pod is judged as with no law (red-team)."""
    today = ledger_now(session).date()
    return {d["pod_id"] for d in debates(session).values() if is_open(d, today)}


# --- the sweep's side ----------------------------------------------------------------------------

def open_debate(session: Session, *, pitch: dict[str, Any], days: int, actor: Agent) -> Event:
    """Open ``pitch``'s debate today (the caller, the sweep, owns the transaction)."""
    today = ledger_now(session).date()
    return append_event(session, type=EVENT_DEBATE_OPENED, actor_agent_id=actor.id, payload={
        "pitch_id": pitch["pitch_id"], "pod_id": pitch["pod_id"], "opened_on": today.isoformat(),
        "closes_on": (today + timedelta(days=days)).isoformat()})


def seed_decision(debate: dict[str, Any] | None, today: date) -> str:
    """What the sweep does with a debated pitch today: ``open`` (no debate yet), ``wait``,
    ``hold`` (refuse the seed) or ``pay``."""
    if debate is None:
        return "open"
    verdict = (debate["verdict"] or {}).get("verdict")
    if verdict == "hold":
        return "hold"
    if verdict == "seed" or today.isoformat() >= debate["closes_on"]:
        return "pay"
    return "wait"


def queued_behind(session: Session, debate: dict[str, Any]) -> list[int]:
    """The pod's other eligible pitches submitted while ``debate`` was argued, before its hold:
    a hold binds them too, so the rule the manager held is not paid through a copy queued behind
    it (red-team). Neither seeded nor refused yet; oldest first."""
    answered = {e.payload_json["pitch_id"] for e in _events(
        session, EVENT_CAPITAL_SEEDED, EVENT_CAPITAL_SEED_REFUSED)}
    return [p["pitch_id"] for p in (e.payload_json for e in _events(session, EVENT_PITCH_JUDGED))
            if p.get("pod_id") == debate["pod_id"] and p.get("eligible") is True
            and debate["pitch_id"] < p["pitch_id"] < debate["ruled_event"]
            and p["pitch_id"] not in answered]


def hold_reason(debate: dict[str, Any]) -> str:
    v = debate["verdict"]
    return (f"the firm's manager held it after its debate ({v['by']}, {v['on']}): "
            f"{v['reason']}")


# --- the thread and the verdict ------------------------------------------------------------------

def _refuse(session: Session, *, pitch_id: int, act: str, reason: str, actor: Agent,
            status: int = 409) -> DebateError:
    append_event(session, type=EVENT_DEBATE_REFUSED, actor_agent_id=actor.id, payload={
        "pitch_id": pitch_id, "act": act, "reason": reason, "by": actor.id,
        "by_name": actor.name})
    session.commit()
    return DebateError(status, reason)


def _no_debate_reason(session: Session, pitch_id: int) -> str:
    """Why ``pitch_id`` has no debate to argue or rule on."""
    submitted = session.get(Event, pitch_id)
    if submitted is None or submitted.type != EVENT_PITCH_SUBMITTED:
        return f"there is no pitch {pitch_id}"
    if debate_days(session) == 0:
        return "the firm has no debate law: an eligible pitch is seeded the next morning"
    judged = next((e.payload_json for e in _events(session, EVENT_PITCH_JUDGED)
                   if e.payload_json.get("pitch_id") == pitch_id), None)
    if judged is None or judged.get("eligible") is not True:
        return (f"pitch {pitch_id} is not eligible: the gates refused it, so it is never "
                "debated and never seeded")
    return (f"pitch {pitch_id} has no debate: a debate opens at the first morning's sweep "
            "after an eligible pitch, only for a pitch the centre would seed (its pod not "
            "closed, not seeded, a long-only rule)")


def _closed_reason(debate: dict[str, Any], today: date) -> str | None:
    pitch_id = debate["pitch_id"]
    if debate["capital"] is not None:
        return f"pitch {pitch_id}'s debate is over: the centre has {debate['capital']['outcome']} it"
    if debate["verdict"] is not None:
        return (f"pitch {pitch_id}'s debate is over: the manager ruled "
                f"{debate['verdict']['verdict']!r} on {debate['verdict']['on']}")
    if today.isoformat() >= debate["closes_on"]:
        return (f"pitch {pitch_id}'s debate closed on {debate['closes_on']}: with no verdict the "
                "law's seed stands")
    return None


def own_pitch(session: Session, pitch_id: int, actor: Agent) -> bool:
    """Is ``pitch_id`` a pitch of ``actor``'s own pod?"""
    submitted = session.get(Event, pitch_id)
    return (submitted is not None and submitted.type == EVENT_PITCH_SUBMITTED
            and actor.pod_id is not None and submitted.payload_json.get("pod_id") == actor.pod_id)


def argue(session: Session, *, pitch_id: int, text: str, actor: Agent) -> dict[str, Any]:
    """``actor`` (a reviewer, or the pitch's own PM: the caller checked the role) writes ``text``
    in ``pitch_id``'s thread; commits. Returns the debate as ``actor`` reads it. A PM writing in
    another pod's debate is the caller's 403 (:class:`NotYourDebate`)."""
    text = text.strip()
    if not text or len(text) > MAX_ARGUMENT:
        raise DebateError(422, f"an argument is 1 to {MAX_ARGUMENT} characters")
    with OMS_LOCK:     # no sweep between the read and the post
        debate = debates(session).get(pitch_id)
        if actor.role != AgentRole.reviewer and not own_pitch(session, pitch_id, actor):
            # Asked before anything else, with one answer for every pitch not its own: no
            # other pod's pitch is told apart from another (red-team: the gates' verdict leaked).
            raise NotYourDebate(f"pitch {pitch_id} is not your pod's: a PM argues only its own "
                                "pod's pitch")
        if debate is None:
            # A reviewer reads no pod's pitches: one answer for every pitch not in debate (auditor:
            # the reason told it whether the gates refused another pod's pitch).
            raise _refuse(session, pitch_id=pitch_id, act="argue", actor=actor,
                          reason=(f"pitch {pitch_id} has no debate"
                                  if actor.role == AgentRole.reviewer
                                  else _no_debate_reason(session, pitch_id)))
        today = ledger_now(session).date()
        if (why := _closed_reason(debate, today)) is not None:
            raise _refuse(session, pitch_id=pitch_id, act="argue", actor=actor, reason=why)
        mine = sum(1 for post in debate["thread"] if post["_by"] == actor.id)
        if mine >= MAX_POSTS:
            raise _refuse(session, pitch_id=pitch_id, act="argue", actor=actor,
                          reason=f"you have written {MAX_POSTS} posts in pitch {pitch_id}'s "
                                 "thread: that is the most one author writes in one debate")
        append_event(session, type=EVENT_DEBATE_ARGUED, actor_agent_id=actor.id, payload={
            "pitch_id": pitch_id, "post_no": len(debate["thread"]) + 1, "text": text,
            "by": actor.id, "by_name": actor.name, "role": actor.role.value})
        session.commit()
        return debate_view(session, pitch_id)


def rule(session: Session, *, pitch_id: int, verdict: str, reason: str,
         actor: Agent) -> dict[str, Any]:
    """The manager (the caller checked the role) rules on ``pitch_id``'s debate; commits."""
    reason = reason.strip()
    if verdict not in VERDICTS:
        raise DebateError(422, f"a verdict is one of {', '.join(VERDICTS)}")
    if len(reason) > MAX_REASON:
        raise DebateError(422, f"a reason is at most {MAX_REASON} characters")
    if verdict == "hold" and not reason:
        raise DebateError(422, "a hold says why: the PM reads your reason")
    with OMS_LOCK:     # no sweep between the read and the verdict
        debate = debates(session).get(pitch_id)
        if debate is None:
            raise _refuse(session, pitch_id=pitch_id, act="rule", actor=actor,
                          reason=_no_debate_reason(session, pitch_id))
        today = ledger_now(session).date()
        if (why := _closed_reason(debate, today)) is not None:
            raise _refuse(session, pitch_id=pitch_id, act="rule", actor=actor, reason=why)
        append_event(session, type=EVENT_PITCH_RULED, actor_agent_id=actor.id, payload={
            "pitch_id": pitch_id, "pod_id": debate["pod_id"], "verdict": verdict,
            "reason": reason, "by": actor.id, "by_name": actor.name})
        session.commit()
        return debate_view(session, pitch_id)


# --- what a reader sees --------------------------------------------------------------------------

def _pitch_parts(session: Session) -> tuple[dict[int, Event], dict[int, dict[str, Any]]]:
    submitted = {e.id: e for e in _events(session, EVENT_PITCH_SUBMITTED)}
    judged = {e.payload_json.get("pitch_id"): e.payload_json
              for e in _events(session, EVENT_PITCH_JUDGED)}
    return submitted, judged


def _view(session: Session, debate: dict[str, Any], today: date, submitted: dict[int, Event],
          judged: dict[int, dict[str, Any]]) -> dict[str, Any]:
    pitch = submitted[debate["pitch_id"]]
    p, j = pitch.payload_json, judged.get(debate["pitch_id"]) or {}
    pod = session.get(Pod, debate["pod_id"])
    status = ("open" if is_open(debate, today) else "ruled" if debate["verdict"] is not None
              and debate["capital"] is None else "over" if debate["capital"] is not None
              else "closed")
    return {
        "pitch_id": debate["pitch_id"], "pod_id": debate["pod_id"],
        "pod_name": pod.name if pod is not None else None,
        "opened_on": debate["opened_on"], "closes_on": debate["closes_on"], "status": status,
        "pitch": {"submitted_on": pitch.ts.date().isoformat(), "hypothesis": p.get("hypothesis"),
                  "data_needed": p.get("data_needed"), "rule": p.get("rule"),
                  "gates": j.get("gates"), "performance": j.get("performance"),
                  "window": j.get("window"), "attempts": j.get("attempts")},
        "thread": [{k: v for k, v in post.items() if k != "_by"} for post in debate["thread"]],
        "verdict": debate["verdict"], "capital": debate["capital"]}


def debate_view(session: Session, pitch_id: int) -> dict[str, Any]:
    submitted, judged = _pitch_parts(session)
    debate = debates(session)[pitch_id]
    return _view(session, debate, ledger_now(session).date(), submitted, judged)


def list_debates(session: Session, *, pod_id: int | None, open_only: bool) -> list[dict[str, Any]]:
    """Every debate (of one pod, or of all), oldest first; only the open ones with ``open_only``."""
    today = ledger_now(session).date()
    submitted, judged = _pitch_parts(session)
    return [_view(session, d, today, submitted, judged)
            for _, d in sorted(debates(session).items())
            if (pod_id is None or d["pod_id"] == pod_id) and (not open_only or is_open(d, today))]


def law_text(days: int) -> str:
    """The debate law in plain words, for every reader of the capital view."""
    return (f"A pitch the gates find eligible is argued before its seed: at the next morning's "
            f"sweep its debate opens for {days} day{'s' if days != 1 else ''}. The firm's "
            f"reviewers argue it in its thread and its PM may answer there (read_debates, "
            f"argue_pitch). The firm's manager may rule once while it is open: seed (paid the "
            f"next morning) or hold (the seed is refused, with the manager's reason, and so is "
            f"every other pitch its pod made while it was argued). With no "
            f"verdict the seed is paid the morning the debate closes. The manager never names an "
            f"amount and never seeds what the gates or the centre refuse.")
