"""Research backtests and pitches: the gates as physics (idea: the pitch and the gates).

Two acts, each one event in the ledger; no table (the read side folds the events, so the ledger
alone rebuilds everything):

* ``research_backtest_run`` — a pod member runs a strategy-v1 rule over a window of the past
  that ends before the **held-out window** (the last ``gates.holdout_days`` days before today).
  Every one is counted for the pod, forever.
* ``pitch_submitted`` + ``pitch_judged`` — the pod's PM pitches a rule with its economic
  hypothesis, the data it needs, the team and budget asked. Physics runs the rule on the held-out
  window (``[today - holdout_days, today)``: every bar had ended, so no look-ahead) and the gates
  judge it with ``N`` = every research backtest and every pitch of the pod, this one included.
  The hypothesis is recorded, never judged here: no LLM in physics (the firm's debate will).

Bars come from the provider at ``ledger_now`` (the look-ahead guard holds for every read), with
enough earlier days for the rule's lookback and the impact window. The verdict grants nothing: it
says "eligible" or not; capital is the allocation's business.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.capital.service import book as capital_book
from app.capital.service import eligible_unseeded
from app.config import GatesConfig
from app.db.models import Agent, Event
from app.ledger.events import (
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_SUBMITTED,
    EVENT_RESEARCH_BACKTEST_RUN,
    append_event,
    ledger_now,
)
from app.marketdata import (
    Bar,
    InvalidRequestError,
    LookAheadError,
    MarketDataProvider,
    UnknownTickerError,
)
from app.strategy.gates import correlation_gate, judge, performance
from app.strategy.rule import IMPACT_WINDOW, Evaluation, EvaluationError, StrategyRule, evaluate

#: Days of research window when the caller names none.
DEFAULT_RESEARCH_DAYS = 365
#: Every pitch's hypothesis row: recorded, judged later by the firm's debate, never by physics.
HYPOTHESIS_ROW = {"gate": "hypothesis", "result": "recorded", "value": None, "threshold": None,
                  "note": "the economic story is recorded here and judged by the firm's own "
                          "process (a debate, later), never by physics"}


class StrategyRequestError(ValueError):
    """The request cannot be run (a window into the held-out days, an unknown ticker): 422."""


class NotAPodMember(ValueError):
    """Research and pitches belong to a pod: the caller has none (403)."""


def holdout_start(session: Session, law: GatesConfig) -> tuple[date, date]:
    """``(first held-out day, today)`` at the ledger's now."""
    today = ledger_now(session).date()
    return today - timedelta(days=law.holdout_days), today


def _bars(provider: MarketDataProvider, session: Session, rule: StrategyRule, start: date,
          end: date) -> dict[str, list[Bar]]:
    # Calendar days behind the first decision: lookback or the impact window, in trading days
    # (≈ 5 of every 7 calendar days, plus holidays), so the first rebalance can already score.
    warmup = timedelta(days=int(1.6 * max(rule.lookback, IMPACT_WINDOW)) + 10)
    now = ledger_now(session)
    out = {}
    for ticker in rule.universe:
        try:
            out[ticker] = provider.get_ohlcv(ticker, start=start - warmup, end=end,
                                             interval="1d", as_of=now)
        except (UnknownTickerError, InvalidRequestError, LookAheadError) as exc:
            raise StrategyRequestError(f"{ticker}: {exc}") from exc
    return out


def _evaluate(provider: MarketDataProvider, session: Session, rule: StrategyRule, start: date,
              end: date, fee_rate: float) -> Evaluation:
    try:
        return evaluate(rule, _bars(provider, session, rule, start, end), start=start, end=end,
                        fee_rate=fee_rate)
    except EvaluationError as exc:
        raise StrategyRequestError(str(exc)) from exc


def pod_attempts(session: Session, pod_id: int) -> int:
    """Every research backtest and every pitch the pod ever made (the deflated Sharpe's N)."""
    pod = func.json_extract(Event.payload_json, "$.pod_id")
    return session.scalar(
        select(func.count()).select_from(Event).where(
            Event.type.in_((EVENT_RESEARCH_BACKTEST_RUN, EVENT_PITCH_SUBMITTED)), pod == pod_id)
    ) or 0


def _pod_of(actor: Agent) -> int:
    if actor.pod_id is None:
        raise NotAPodMember("research and pitches belong to a pod, and you have none")
    return actor.pod_id


def run_research(session: Session, *, actor: Agent, rule: StrategyRule, start: date | None,
                 end: date | None, provider: MarketDataProvider, law: GatesConfig,
                 fee_rate: float) -> dict[str, Any]:
    """Run ``rule`` on a research window and record it; returns the recorded backtest."""
    pod_id = _pod_of(actor)
    held_from, _ = holdout_start(session, law)
    end = end or held_from
    start = start or end - timedelta(days=DEFAULT_RESEARCH_DAYS)
    if end > held_from:
        raise StrategyRequestError(
            f"research may only use days before {held_from.isoformat()}: the last "
            f"{law.holdout_days} days are held out, and pitches are judged on them")
    if not start < end:
        raise StrategyRequestError("start must be before end")
    if (end - start).days > law.research_max_days:
        raise StrategyRequestError(f"a research window is at most {law.research_max_days} days")
    evaluation = _evaluate(provider, session, rule, start, end, fee_rate)
    payload = {
        "pod_id": pod_id,
        "agent_id": actor.id,
        "attempt": pod_attempts(session, pod_id) + 1,
        "rule": rule.model_dump(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "performance": performance(evaluation),
    }
    event = append_event(session, type=EVENT_RESEARCH_BACKTEST_RUN, actor_agent_id=actor.id,
                         payload=payload)
    return {"id": event.id, "at": event.ts, **payload}


def _latest_pitches(session: Session, *, besides: int) -> dict[int, dict[str, Any]]:
    """Each other pod's latest pitch (its submitted payload), by pod."""
    latest: dict[int, dict[str, Any]] = {}
    for event in session.scalars(select(Event).where(Event.type == EVENT_PITCH_SUBMITTED)
                                 .order_by(Event.id)):
        pod = event.payload_json.get("pod_id")
        if pod != besides:
            latest[pod] = event.payload_json
    return latest


def _series(provider: MarketDataProvider, session: Session, rules: dict[str, dict[str, Any]],
            start: date, end: date, fee_rate: float
            ) -> dict[str, tuple[Sequence[date], Sequence[float]]]:
    """Each named rule's daily returns on the window, for the correlation gate."""
    out: dict[str, tuple[Sequence[date], Sequence[float]]] = {}
    for name, rule_json in rules.items():
        try:
            theirs = _evaluate(provider, session, StrategyRule.model_validate(rule_json),
                               start, end, fee_rate)
        except StrategyRequestError:
            # Another pod's rule this window cannot carry (a ticker gone): no correlation to
            # measure with it, which never blocks this pod (null, not 0).
            out[name] = ((), ())
            continue
        out[name] = (theirs.days, theirs.returns)
    return out


def seed_correlation(session: Session, *, rule: dict[str, Any], against: dict[str, dict[str, Any]],
                     provider: MarketDataProvider, law: GatesConfig, fee_rate: float
                     ) -> dict[str, Any]:
    """The correlation gate's row for ``rule`` against ``against`` (name → rule) on today's
    held-out window: the capital machine's last check before it pays a seed (auditor). A rule this
    window cannot carry gets a null row, as at the pitch."""
    start, today = holdout_start(session, law)
    try:
        mine = _evaluate(provider, session, StrategyRule.model_validate(rule), start, today,
                         fee_rate)
    except StrategyRequestError as exc:
        return {"gate": "correlation", "result": "null", "value": None,
                "threshold": law.max_correlation, "against": {}, "note": str(exc)}
    return correlation_gate(mine, _series(provider, session, against, start, today, fee_rate),
                            law)


def submit_pitch(session: Session, *, actor: Agent, rule: StrategyRule, hypothesis: str,
                 data_needed: str, team: str, budget_usd: float,
                 provider: MarketDataProvider, law: GatesConfig, fee_rate: float
                 ) -> dict[str, Any]:
    """Judge ``rule`` on the held-out window and record the pitch and its verdict."""
    pod_id = _pod_of(actor)
    start, today = holdout_start(session, law)
    evaluation = _evaluate(provider, session, rule, start, today, fee_rate)
    # Compared with each other pod's latest pitch, with the rule every live pod the capital machine
    # seeded trades, and with the pitch each other unseeded pod will be seeded with at the next
    # advance: a later pitch of the original must never free a copy of the rule that is (or is
    # about to be) its mandate to earn a second seed (red-team and auditor, capital machine).
    compared = {f"pod {pod}": pitch["rule"]
                for pod, pitch in sorted(_latest_pitches(session, besides=pod_id).items())}
    # A closed pod's mandate too: the ladder's verdict on a rule is not undone by a fresh seed.
    # (The machine checks again when it pays a seed, :func:`seed_correlation`: no order of pitches
    # gets two seeds for one rule.)
    seeded = capital_book(session)["pods"]
    for pod, entry in sorted(seeded.items()):
        if pod != pod_id:
            compared[f"pod {pod} mandate"] = entry["rule"]
    for waiting in eligible_unseeded(session, set(seeded) | {pod_id}):
        compared[f"pod {waiting['pod_id']} seed"] = waiting["rule"]
    others = _series(provider, session, compared, start, today, fee_rate)
    attempts = pod_attempts(session, pod_id) + 1
    submitted = append_event(session, type=EVENT_PITCH_SUBMITTED, actor_agent_id=actor.id, payload={
        "pod_id": pod_id, "agent_id": actor.id, "hypothesis": hypothesis,
        "data_needed": data_needed, "team": team, "budget_usd": budget_usd,
        "rule": rule.model_dump()})
    verdict = judge(evaluation, attempts=attempts, others=others, law=law)
    judged = {
        "pitch_id": submitted.id,
        "pod_id": pod_id,
        "window": {"start": start.isoformat(), "end": today.isoformat()},
        "attempts": attempts,
        "eligible": verdict["eligible"],
        "gates": [*verdict["gates"], HYPOTHESIS_ROW],
        "performance": verdict["performance"],
        "law": law.model_dump(),
    }
    append_event(session, type=EVENT_PITCH_JUDGED, actor_agent_id=actor.id, payload=judged)
    return pitch_view(submitted, judged)


def pitch_view(submitted: Event, judged: dict[str, Any] | None) -> dict[str, Any]:
    """One pitch as the read side shows it: what was asked, and the verdict."""
    return {"id": submitted.id, "submitted_at": submitted.ts, **submitted.payload_json,
            "verdict": judged}


def list_pitches(session: Session, *, pod_id: int | None) -> list[dict[str, Any]]:
    """Every pitch (of one pod, or of all), oldest first, each with its verdict."""
    verdicts = {e.payload_json.get("pitch_id"): e.payload_json for e in session.scalars(
        select(Event).where(Event.type == EVENT_PITCH_JUDGED))}
    out = []
    for event in session.scalars(select(Event).where(Event.type == EVENT_PITCH_SUBMITTED)
                                 .order_by(Event.id)):
        if pod_id is None or event.payload_json.get("pod_id") == pod_id:
            out.append(pitch_view(event, verdicts.get(event.id)))
    return out


def list_research(session: Session, *, pod_id: int) -> list[dict[str, Any]]:
    """Every research backtest of a pod, oldest first."""
    pod = func.json_extract(Event.payload_json, "$.pod_id")
    return [{"id": e.id, "at": e.ts, **e.payload_json} for e in session.scalars(
        select(Event).where(Event.type == EVENT_RESEARCH_BACKTEST_RUN, pod == pod_id)
        .order_by(Event.id))]
