"""The capital machine as physics (idea: capital follows results). Runs on every backtest clock
advance, before the pending-order sweep, under the :data:`~app.oms.service.OMS_LOCK` the whole
advance holds, as the system identity; one transaction.

1. **Open.** The first time an eligible pitch exists, the centre opens with the law of the day
   (``capital:`` in ``config.yaml``), frozen into ``capital_opened``: the run is judged by it.
   Before that the machine does nothing, so a run with no eligible pitch is untouched.
2. **The ladder**, every advance, for every live machine pod: its forward return index, high-water
   mark and the worst drawdown it has lived (:mod:`app.capital.allocation`); a stage that climbs is
   ``pod_stage_changed``,
   mirrored on the pod's row (the order system reads it). Halved → half its equity goes back to the
   centre; reduce-only → its pending buys are cancelled; closed → every pending order cancelled,
   every position sold, all its cash back to the centre, and a vacancy opens
   (:mod:`app.capital.hiring`).
3. **Seeds.** Each eligible pitch of a pod the machine has not seeded gets ``seed_usd`` from the
   centre (``capital_seeded``, then ``allocation_set``), if the centre holds it. A long-short rule
   is refused, once, in the ledger: the order system cannot short yet; so is a rule that fails the
   correlation gate against a mandate the centre already funds (checked again as the seed is paid).
4. **Re-weighing**, every ``reallocate_every_days``: :func:`app.capital.allocation.reallocate` on
   every live pod's forward record; ``capital_reallocated`` holds its whole input and its result;
   cuts are recalled first, raises paid after.

Money only moves by ``allocation_set`` (marked ``source: capital``) and by fills: the centre's cash
is the law's capital minus every capital ``allocation_set``. A recall sells a slice of each
position pro rata at the market (:func:`app.oms.service.force_sell`) when the pod's cash is short,
and never takes more than the centre's stake (:func:`centre_stake`): money the world gave a pod
before its seed stays in the pod, even when it is closed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capital.allocation import (
    STAGES,
    PodTrack,
    climb,
    drawdown,
    reallocate,
    worst_drawdown,
)
from app.capital.hiring import hiring_law, open_vacancy
from app.config import CapitalConfig, get_settings
from app.db.models import Agent, Event, Order, OrderSide, OrderStatus, Pod, Position
from app.ledger.events import (
    EVENT_ALLOCATION_SET,
    EVENT_CAPITAL_OPENED,
    EVENT_CAPITAL_REALLOCATED,
    EVENT_CAPITAL_SEED_REFUSED,
    EVENT_CAPITAL_SEEDED,
    EVENT_CAPITAL_SWEEP_FAILED,
    EVENT_ORDER_CANCELLED,
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_SUBMITTED,
    EVENT_POD_STAGE_CHANGED,
    append_event,
    ledger_now,
)
from app.ledger.reducers import QTY_EPSILON
from app.marketdata import MarketDataError, MarketDataProvider
from app.metrics.equity import build_equity_curve
from app.metrics.metering import metered_by_agent
from app.metrics.performance import EquityPoint, daily_returns
from app.oms.errors import OMSError
from app.oms.service import OMS_LOCK, force_sell, get_cash
from app.registry.halt import is_halted
from app.registry.pods import fund_pod
from app.registry.service import get_or_create_system_agent

SOURCE = "capital"
CAPITAL_EVENTS = (EVENT_CAPITAL_OPENED, EVENT_CAPITAL_SEEDED, EVENT_CAPITAL_SEED_REFUSED,
                  EVENT_CAPITAL_REALLOCATED, EVENT_POD_STAGE_CHANGED, EVENT_CAPITAL_SWEEP_FAILED)


# --- the book, folded from the ledger ------------------------------------------------------------

def _events(session: Session, *types: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type.in_(types)).order_by(Event.id)))


def opened_law(session: Session) -> tuple[CapitalConfig, Event] | None:
    """The law the run's centre opened with, or ``None`` before it opened."""
    first = session.scalar(select(Event).where(Event.type == EVENT_CAPITAL_OPENED)
                           .order_by(Event.id).limit(1))
    if first is None:
        return None
    return CapitalConfig.model_validate(first.payload_json["law"]), first


def run_law(session: Session) -> CapitalConfig:
    """The law this run is judged by: the one its centre opened with, else today's."""
    opened = opened_law(session)
    return opened[0] if opened is not None else get_settings().capital


def book(session: Session) -> dict[str, Any]:
    """The machine as the ledger alone says it is: the centre and every pod it seeded.

    ``pods[pod_id]`` = ``{seeded, pitch_id, rule, seeded_on, cost_at_seed_usd, stage, allocated}``
    (``allocated`` = the net capital the centre has put in: every capital ``allocation_set``)."""
    opened = opened_law(session)
    pods: dict[int, dict[str, Any]] = {}
    moved = 0.0
    for event in _events(session, EVENT_CAPITAL_SEEDED, EVENT_POD_STAGE_CHANGED,
                         EVENT_ALLOCATION_SET):
        p = event.payload_json
        if event.type == EVENT_CAPITAL_SEEDED:
            pods[p["pod_id"]] = {"seeded": event.id, "pitch_id": p["pitch_id"], "rule": p["rule"],
                                 "seeded_on": event.ts.date().isoformat(),
                                 "cost_at_seed_usd": p["cost_at_seed_usd"], "stage": "active",
                                 "allocated": 0.0}
        elif event.type == EVENT_POD_STAGE_CHANGED:
            pods[p["pod_id"]]["stage"] = p["to"]
        elif p.get("source") == SOURCE:
            moved += float(p["delta"])
            pods[p["pod_id"]]["allocated"] += float(p["delta"])
    return {"law": opened[0].model_dump() if opened else None,
            "opened_on": opened[1].ts.date().isoformat() if opened else None,
            "centre_cash": (opened[0].firm_capital_usd - moved) if opened else None,
            "pods": pods}


def _pod_cost_usd(session: Session) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in metered_by_agent(session).values():
        if row.pod_id is not None:
            out[row.pod_id] = out.get(row.pod_id, 0.0) + row.usd_micros / 1e6
    return out


def track(session: Session, *, pod_id: int, entry: dict[str, Any], provider: MarketDataProvider,
          now: datetime, costs: dict[int, float]) -> PodTrack:
    """A machine pod's forward record: daily equity from its seed day on, valued at the closes
    known at ``now``; returns with flows at the day's start (money moves at the open)."""
    seeded_on = date.fromisoformat(entry["seeded_on"])
    curve = build_equity_curve(session, pod_id=pod_id, provider=provider, as_of=now,
                               live_price=False)
    points = [p for p in curve.points if p.on >= seeded_on]
    # The day before the seed: what the pod held then (nothing, for a pod the machine made; the
    # world's allocation, for one the world funded first), so the seed is a flow and not a gain
    # (red-team, capital machine). The seed day's return is earned on that plus the seed.
    before = [p for p in curve.points if p.on < seeded_on]
    series = [EquityPoint(on=seeded_on - timedelta(days=1),
                          equity=before[-1].equity if before else 0.0)] + points
    returns = daily_returns(series, flows_at="start")
    days = [p.on.isoformat() for prev, p in zip(series, series[1:])
            if prev.equity + p.net_flow > 0]
    _, _, dd = drawdown(returns)
    equity = points[-1].equity if points else 0.0
    cost = max(0.0, costs.get(pod_id, 0.0) - float(entry["cost_at_seed_usd"]))
    return PodTrack(pod_id=pod_id, seeded=entry["seeded"], stage=entry["stage"], equity=equity,
                    days=tuple(days), returns=tuple(returns), cost_usd=cost, drawdown=dd)


def centre_stake(session: Session, *, record: PodTrack) -> float:
    """What the centre's share of a pod is worth now: each capital flow into (or out of) the pod,
    grown by the pod's return index since the day it moved, as fund units are. A recall never
    takes more: money the world gave a pod before its seed is not the centre's (red-team)."""
    growth = list(zip(record.days, record.returns))
    stake = 0.0
    for event in _events(session, EVENT_ALLOCATION_SET):
        p = event.payload_json
        if p.get("source") != SOURCE or p.get("pod_id") != record.pod_id:
            continue
        moved_on = event.ts.date().isoformat()
        grown = float(p["delta"])
        for day, r in growth:
            if day >= moved_on:
                grown *= 1.0 + r
        stake += grown
    return max(0.0, stake)


# --- moving money ------------------------------------------------------------------------------

def _cancel_pending(session: Session, *, pod_id: int, buys_only: bool, actor: Agent,
                    why: str) -> list[int]:
    stmt = select(Order).where(Order.pod_id == pod_id, Order.status == OrderStatus.pending)
    if buys_only:
        stmt = stmt.where(Order.side == OrderSide.buy)
    cancelled = []
    for order in session.scalars(stmt.order_by(Order.id)):
        order.status = OrderStatus.cancelled
        order.status_reason = why
        session.flush()
        append_event(session, type=EVENT_ORDER_CANCELLED, actor_agent_id=actor.id, payload={
            "order_id": order.id, "pod_id": pod_id, "ticker": order.ticker, "reason": why})
        cancelled.append(order.id)
    return cancelled


def recall(session: Session, *, pod_id: int, amount: float | None, actor: Agent,
           provider: MarketDataProvider, why: str, stake: float) -> float:
    """Bring ``amount`` of a pod's capital back to the centre (``None``: everything, every position
    sold), never more than the centre's ``stake`` in it (:func:`centre_stake`). Sells a slice of
    each position pro rata when its cash is short. Returns what moved."""
    if amount is not None:
        amount = min(amount, stake)
        if amount <= 0:
            return 0.0
    cash = get_cash(session, pod_id)
    positions = list(session.scalars(select(Position).where(Position.pod_id == pod_id)
                                     .order_by(Position.ticker)))
    if amount is None or amount > cash:
        fee_rate = get_settings().oms.fee_rate
        prices: dict[str, float] = {}
        for pos in positions:
            try:
                prices[pos.ticker] = provider.get_price(pos.ticker, as_of=ledger_now(session)).price
            except MarketDataError:
                logger.bind(pod_id=pod_id, ticker=pos.ticker).warning("recall: no price, kept")
        value = sum(pos.qty * prices[pos.ticker] for pos in positions if pos.ticker in prices)
        share = 1.0 if amount is None or value <= 0 else min(
            1.0, (amount - cash) * (1.0 + 2 * fee_rate) / value)
        for pos in positions:
            if pos.ticker not in prices:
                continue
            qty = pos.qty if share >= 1.0 - 1e-9 else pos.qty * share
            if qty <= QTY_EPSILON:
                continue
            force_sell(session, pod_id=pod_id, ticker=pos.ticker, qty=qty, actor=actor,
                       reason=why, provider=provider)
        cash = get_cash(session, pod_id)
    moved = max(0.0, min(stake, cash) if amount is None else min(amount, cash))
    if moved > 0:
        fund_pod(session, pod_id=pod_id, delta=-moved, actor=actor, reason=why, source=SOURCE)
    return moved


def _set_stage(session: Session, *, pod_id: int, old: str, new: str, record: PodTrack,
               law: CapitalConfig, actor: Agent, provider: MarketDataProvider) -> None:
    index, high, dd = drawdown(record.returns)
    worst = worst_drawdown(record.returns)
    stake = centre_stake(session, record=record)
    append_event(session, type=EVENT_POD_STAGE_CHANGED, actor_agent_id=actor.id, payload={
        "pod_id": pod_id, "from": old, "to": new, "drawdown": dd, "worst_drawdown": worst,
        "index": index, "high_water": high, "equity": record.equity, "centre_stake": stake,
        "ladder": {"halve_at": law.halve_at, "reduce_only_at": law.reduce_only_at,
                   "close_at": law.close_at}})
    session.get(Pod, pod_id).status = new
    rank = STAGES.index
    if new == "closed":
        _cancel_pending(session, pod_id=pod_id, buys_only=False, actor=actor,
                        why="the pod was closed by the risk ladder")
        recall(session, pod_id=pod_id, amount=None, actor=actor, provider=provider, stake=stake,
               why=f"risk ladder: {worst:.1%} down from the high-water mark, the pod is closed")
        # The firm recruits (idea: a dead pod is replaced): the vacancy, its post-mortem and the
        # hire the law names, in the close's own transaction.
        open_vacancy(session, pod_id=pod_id, record=record, actor=actor)
        return
    if rank(old) < rank("halved") <= rank(new):
        recall(session, pod_id=pod_id, amount=stake / 2, actor=actor, provider=provider,
               stake=stake,
               why=f"risk ladder: {worst:.1%} down from the high-water mark, capital halved")
    if new == "reduce_only":
        _cancel_pending(session, pod_id=pod_id, buys_only=True, actor=actor,
                        why="the pod is reduce-only (risk ladder): buys cancelled")


# --- the sweep ---------------------------------------------------------------------------------

def eligible_unseeded(session: Session, seeded_pods: set[int]) -> list[dict[str, Any]]:
    refused = {e.payload_json["pitch_id"] for e in _events(session, EVENT_CAPITAL_SEED_REFUSED)}
    submitted = {e.id: e.payload_json for e in _events(session, EVENT_PITCH_SUBMITTED)}
    out, seen = [], set(seeded_pods)
    for judged in _events(session, EVENT_PITCH_JUDGED):
        p = judged.payload_json
        pitch_id, pod_id = p.get("pitch_id"), p.get("pod_id")
        if p.get("eligible") is not True or pitch_id in refused or pod_id in seen:
            continue
        if pitch_id not in submitted:
            continue
        seen.add(pod_id)
        out.append({"pitch_id": pitch_id, "pod_id": pod_id, "rule": submitted[pitch_id]["rule"]})
    return out


def _copy_check(session: Session, *, pitch: dict[str, Any], provider: MarketDataProvider
                ) -> dict[str, Any] | None:
    """The correlation gate, run again as the seed is paid, against every other pod's mandate the
    centre ever funded (closed pods too, and seeds paid earlier in this sweep). The pitch-time gate
    saw the ledger of its moment; this sees the seeds as they are paid, so no order of pitches (nor
    two pitches at once) gets two seeds for one rule (auditor). ``None``: nothing to compare with."""
    from app.strategy.service import seed_correlation  # the strategy desk reads this module

    against = {f"pod {pod} mandate": entry["rule"]
               for pod, entry in sorted(book(session)["pods"].items())
               if pod != pitch["pod_id"]}
    if not against:
        return None
    settings = get_settings()
    return seed_correlation(session, rule=pitch["rule"], against=against, provider=provider,
                            law=settings.gates, fee_rate=settings.oms.fee_rate)


def _due(session: Session, today: date, opened_on: date, law: CapitalConfig) -> bool:
    last = session.scalar(select(Event).where(Event.type == EVENT_CAPITAL_REALLOCATED)
                          .order_by(Event.id.desc()).limit(1))
    since = opened_on if last is None else date.fromisoformat(last.payload_json["day"])
    return (today - since).days >= law.reallocate_every_days


def sweep(session: Session, *, provider: MarketDataProvider) -> dict[str, Any] | None:
    """Run the machine once at the ledger's now; commits. ``None``: nothing to do (no centre and no
    eligible pitch, or the world is halted). Otherwise what happened, for the log."""
    with OMS_LOCK:
        if is_halted():
            return None
        try:
            done = _sweep(session, provider=provider)
            session.commit()
            return done
        except Exception:
            session.rollback()
            raise


def _sweep(session: Session, *, provider: MarketDataProvider) -> dict[str, Any] | None:
    state = book(session)
    eligible = eligible_unseeded(session, set(state["pods"]))
    if state["law"] is None and not eligible:
        return None
    system = get_or_create_system_agent(session)
    now = ledger_now(session)
    if state["law"] is None:
        law = get_settings().capital
        append_event(session, type=EVENT_CAPITAL_OPENED, actor_agent_id=system.id,
                     payload={"law": law.model_dump(), "firm_capital_usd": law.firm_capital_usd})
        state = book(session)
    law = CapitalConfig.model_validate(state["law"])
    done: dict[str, Any] = {"stages": [], "seeded": [], "refused": [], "reallocated": False}
    costs = _pod_cost_usd(session)

    for pod_id, entry in sorted(state["pods"].items()):
        if entry["stage"] == "closed":
            continue
        record = track(session, pod_id=pod_id, entry=entry, provider=provider, now=now,
                       costs=costs)
        # The worst drawdown the pod has lived, not only today's: a fall and a recovery inside one
        # advance of several days still climbs the ladder (red-team). Stages only climb, so this
        # is the ladder checked on every day.
        new = climb(entry["stage"], worst_drawdown(record.returns), law)
        if new != entry["stage"]:
            _set_stage(session, pod_id=pod_id, old=entry["stage"], new=new, record=record,
                       law=law, actor=system, provider=provider)
            done["stages"].append((pod_id, new))

    for pitch in eligible:
        pod = session.get(Pod, pitch["pod_id"])
        reason = None
        if pod is None:
            reason = "the pod no longer exists"
        elif pod.status == "closed":
            reason = "the pod is closed"
        elif pitch["rule"].get("side") != "long_only":
            reason = "a long-short rule: the order system cannot short yet, so it cannot trade it"
        gate = None
        if reason is None:
            if book(session)["centre_cash"] < law.seed_usd:
                continue    # the centre is short today; the pitch waits
            try:
                gate = _copy_check(session, pitch=pitch, provider=provider)
            except MarketDataError as exc:
                # One pitch's feed trouble must not stall the ladder for every pod (auditor):
                # this pitch waits for the next advance.
                logger.bind(pod_id=pitch["pod_id"]).warning("copy check: no data, waits: {}", exc)
                continue
            if gate is not None and gate["result"] == "fail":
                reason = (f"it moves like a rule the centre already funds (correlation "
                          f"{gate['value']:.2f} above {gate['threshold']:.2f})")
        if reason is not None:
            append_event(session, type=EVENT_CAPITAL_SEED_REFUSED, actor_agent_id=system.id,
                         payload={"pod_id": pitch["pod_id"], "pitch_id": pitch["pitch_id"],
                                  "reason": reason, **({"gate": gate} if gate else {})})
            done["refused"].append(pitch["pitch_id"])
            continue
        if book(session)["centre_cash"] < law.seed_usd:
            continue    # the centre is short today; the pitch waits
        append_event(session, type=EVENT_CAPITAL_SEEDED, actor_agent_id=system.id, payload={
            "pod_id": pitch["pod_id"], "pitch_id": pitch["pitch_id"], "seed_usd": law.seed_usd,
            "rule": pitch["rule"], "cost_at_seed_usd": costs.get(pitch["pod_id"], 0.0)})
        fund_pod(session, pod_id=pitch["pod_id"], delta=law.seed_usd, actor=system,
                 reason=f"seed: eligible pitch #{pitch['pitch_id']}", source=SOURCE)
        done["seeded"].append(pitch["pod_id"])

    state = book(session)
    if _due(session, now.date(), date.fromisoformat(state["opened_on"]), law):
        live = [track(session, pod_id=pod_id, entry=entry, provider=provider, now=now,
                      costs=costs)
                for pod_id, entry in sorted(state["pods"].items()) if entry["stage"] != "closed"]
        inputs = {"centre_cash": state["centre_cash"], "pods": [p.as_input() for p in live]}
        result = reallocate(live, centre_cash=state["centre_cash"], law=law)
        append_event(session, type=EVENT_CAPITAL_REALLOCATED, actor_agent_id=system.id,
                     payload={"day": now.date().isoformat(), "law": law.model_dump(),
                              "inputs": inputs, "result": result})
        moves = {row["pod_id"]: row["move"] for row in result["pods"]}
        records = {p.pod_id: p for p in live}
        for pod_id, move in sorted(moves.items()):
            if move < 0:
                recall(session, pod_id=pod_id, amount=-move, actor=system, provider=provider,
                       stake=centre_stake(session, record=records[pod_id]),
                       why="capital re-weighed: cut")
        for row in sorted(result["pods"], key=lambda r: -(r["viability"] or 0.0)):
            move = row["move"]
            if move > 0:
                move = min(move, book(session)["centre_cash"])
                if move > 0:
                    fund_pod(session, pod_id=row["pod_id"], delta=move, actor=system,
                             reason="capital re-weighed: raise", source=SOURCE)
        done["reallocated"] = True
    return done


def safe_sweep(session: Session, *, provider: MarketDataProvider) -> dict[str, Any] | None:
    """:func:`sweep` for the clock advance, which has already moved and committed: a failure of
    the machine (rolled back whole) is logged loudly, never turned into a failed advance; the next
    advance runs the machine again. The skip is written to the ledger too (``capital_sweep_failed``,
    auditor): a day the ladder did not judge is never silent."""
    try:
        return sweep(session, provider=provider)
    except OMSError as exc:
        logger.warning("capital sweep skipped: {}", exc)
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.exception("capital sweep failed")
        error = f"{type(exc).__name__}: {exc}"
    try:
        append_event(session, type=EVENT_CAPITAL_SWEEP_FAILED, actor_agent_id=None,
                     payload={"error": error[:500]})
        session.commit()
    except Exception:  # noqa: BLE001 - the log above already says it loudly
        session.rollback()
        logger.exception("capital sweep failure could not be recorded")
    return None


#: What a pod's score row says about another pod: shown only to a reader with ``read_cross_pod``.
CROSS_POD_SCORE = ("corr_with", "corr")


def capital_view(session: Session, *, pod_id: int | None, cross: bool) -> dict[str, Any]:
    """The allocation table: the law, and each machine pod's stage, capital and latest score (one
    pod's row, or every pod's for ``None``). The centre's cash is the firm's, shown with ``None``.
    Without ``cross`` (a pod member), the score keeps how much the correlation cost the pod, not
    which pod it moves like nor how much (red-team: a slow oracle of another pod's book)."""
    state = book(session)
    latest = session.scalar(select(Event).where(Event.type == EVENT_CAPITAL_REALLOCATED)
                            .order_by(Event.id.desc()).limit(1))
    scores = ({row["pod_id"]: row for row in latest.payload_json["result"]["pods"]}
              if latest is not None else {})
    rows = []
    for pid, entry in sorted(state["pods"].items()):
        if pod_id is not None and pid != pod_id:
            continue
        last = scores.get(pid)
        if last is not None and not cross:
            last = {k: v for k, v in last.items() if k not in CROSS_POD_SCORE}
        rows.append({"pod_id": pid, "stage": entry["stage"], "pitch_id": entry["pitch_id"],
                     "seeded_on": entry["seeded_on"], "allocated_usd": entry["allocated"],
                     "rule": entry["rule"], "last_score": last,
                     "last_scored_on": latest.payload_json["day"] if pid in scores else None})
    view = {"opened_on": state["opened_on"], "law": state["law"],
            "centre_cash_usd": state["centre_cash"] if pod_id is None else None, "pods": rows}
    law = run_law(session)
    if law.tell_pms:
        # The hiring law, announced to every reader (cycle 51: no PM knew a closed pod is replaced).
        hiring = hiring_law(session)
        view["hiring"] = {
            "law": (f"When the risk ladder closes a pod ({law.close_at:.0%} down from its "
                    "high-water mark), every position is sold and all its capital goes back to the "
                    "centre; a vacancy opens with the pod's post-mortem, and on a later morning a "
                    "new PM is hired into a new pod in its place. A closed pod never reopens."),
            "max_live_pods": hiring.max_live_pods, "new_pm_budget_usd": hiring.budget_usd}
    return view
