"""A run's time is a fact of its ledger (ADR-027, TRD §9, B-004 slice a).

**A run is a database.** A live run is any database whose ledger does not open
with ``run_started``; a backtest run is a *fresh* database whose first event is
``run_started {mode: "backtest", start}``. Live and backtest stamps therefore
never share a ledger, so the ADR-025 floor and ``ledger_now`` are per run by
construction — there is no ``run_id`` column a query could forget to filter on.

**Backtest time moves only forward, only by ``clock_advanced``.** The
:class:`~app.clock.BacktestClock` a process runs on is its copy of the latest
``run_started.start`` / ``clock_advanced.to``; :func:`install_run_clock`
rebuilds it from the ledger on every start, so a restart resumes where the run
was. :func:`advance` is the one way to move it: bounded per step
(:data:`~app.limits.MAX_ADVANCE_MINUTES`), never backwards, never past the real
now (the world has no data from the future to show).

**A run lives in one world** (B-037): ``run_started`` records the market's
:meth:`~app.marketdata.base.MarketDataProvider.world` — a secret key only as a
fingerprint — and :func:`install_run_clock` refuses a process whose provider
describes another.

Who may advance is a permission (``Action.CONTROL_CLOCK``, never universal);
what an advance does next — the pending-order sweep — is the caller's
(:mod:`app.api.clock`), the same sweep the live scheduler runs on a timer.

**A run says what drives its minds** (ADR-032 (p)): ``run_minds_declared
{minds}``, by the same hand that moves the clock. Physics cannot see behind a
key, so this is a declaration, not a measurement. What physics can guarantee is
*when* it was made: once, before the clock has moved and before any firm agent
has written an event, so it precedes every event a firm agent wrote (a read
writes nothing). :func:`run_minds` trusts a declaration only if the ledger's
order still says so.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.clock import BacktestClock, get_clock, set_clock, wall_now
from app.db.models import Agent, Base, Event
from app.ledger.events import (
    EVENT_AGENT_REGISTERED,
    EVENT_CLOCK_ADVANCED,
    EVENT_RUN_MINDS_DECLARED,
    EVENT_RUN_STARTED,
    append_event,
    ledger_now,
)
from app.limits import MAX_ADVANCE_MINUTES
from app.marketdata import get_provider
from app.marketdata.base import LIVE_QUOTE_WINDOW
from app.oms.service import OMS_LOCK
from app.registry.permissions import PHYSICS_ROLES

#: What may drive a run's minds (ADR-032 (p)): code (``scripted``), recorded
#: model output played back (``cassette``), or a model answering now
#: (``model``). Closed, so a label is one of three things a reader understands.
MIND_KINDS: frozenset[str] = frozenset({"scripted", "cassette", "model"})


#: Does market data refuse anything not known by the simulated now? Yes since
#: B-005 (ADR-028): the guard is in the ``MarketDataProvider`` base. Runs opened
#: before it record ``False`` in their ``run_started``, so no reader mistakes
#: them for honest backtests.
LOOK_AHEAD_GUARD = True

#: How far behind the real now a backtest's clock must stay: within it, a live
#: feed answers with its current quote, which a simulated "earlier" must not see.
#: Strictly: the feed's window is inclusive, so the edge itself is refused
#: (red-team 0008).
_REAL_NOW_MARGIN = LIVE_QUOTE_WINDOW


class RunClockError(Exception):
    """The clock cannot do that in this run (live mode, a bad step, a used DB)."""


class RunMindsError(Exception):
    """This run cannot take that declaration of its minds (live, late, twice, unknown)."""


def start_backtest(session: Session, *, start: datetime) -> BacktestClock:
    """Open a backtest run in an empty database, its clock at ``start``.

    Refuses a database holding anything at all: a backtest that inherited a
    live ledger would inherit its stamps (the floor) and its agents' history.
    The caller commits.
    """
    if start.tzinfo is None:
        raise RunClockError("start must carry a timezone (use UTC, e.g. ...Z)")
    start = start.astimezone(timezone.utc)
    if start >= wall_now() - _REAL_NOW_MARGIN:
        raise RunClockError(
            "a backtest must start in the past (at least "
            f"{_REAL_NOW_MARGIN.seconds} s ago): the future has no data"
        )
    for table in Base.metadata.sorted_tables:
        if session.scalar(select(func.count()).select_from(table)):
            raise RunClockError(
                f"this database is not empty ({table.name} has rows): a backtest "
                "is its own database — point FUND_DATABASE_URL at a new file"
            )
    world = get_provider().world()
    clock = BacktestClock(start)
    set_clock(clock)
    append_event(
        session,
        type=EVENT_RUN_STARTED,
        actor_agent_id=None,
        payload={
            "mode": clock.mode,
            "start": _iso(start),
            "look_ahead_guard": LOOK_AHEAD_GUARD,
            "world": world,
        },
    )
    return clock


def install_run_clock(session: Session) -> BacktestClock | None:
    """Put this process on its database's clock; ``None`` for a live run.

    A live run leaves the installed clock alone (the default is live; tests
    install their own). A backtest run gets a ``BacktestClock`` at the latest
    ``run_started.start`` / ``clock_advanced.to`` in the ledger.
    """
    first = session.scalar(select(Event).order_by(Event.id).limit(1))
    if first is None or first.type != EVENT_RUN_STARTED:
        return None
    _require_same_world(first.payload_json)
    latest = session.scalar(
        select(Event)
        .where(Event.type.in_((EVENT_RUN_STARTED, EVENT_CLOCK_ADVANCED)))
        .order_by(Event.id.desc())
        .limit(1)
    )
    payload = latest.payload_json
    moment = payload["to"] if latest.type == EVENT_CLOCK_ADVANCED else payload["start"]
    clock = BacktestClock(datetime.fromisoformat(moment))
    set_clock(clock)
    return clock


def advance(
    session: Session, *, minutes: int, actor_agent_id: int
) -> tuple[datetime, datetime]:
    """Move a backtest clock ``minutes`` forward and record it; commits.

    Returns ``(from, to)``. Under ``OMS_LOCK``, so no order is priced or filled
    while the world's now is moving.
    """
    clock = get_clock()
    if not isinstance(clock, BacktestClock):
        raise RunClockError(
            f"the clock is in {clock.mode} mode: only a backtest run's clock is "
            "advanced; live time is the world's own"
        )
    if not 0 < minutes <= MAX_ADVANCE_MINUTES:
        raise RunClockError(f"a step is 1..{MAX_ADVANCE_MINUTES} minutes")
    with OMS_LOCK:
        # From the ledger's now, not the copy: another process on this database
        # (an operator command) may have stamped later than this one's clock.
        start = ledger_now(session)
        end = start + timedelta(minutes=minutes)
        if end >= wall_now() - _REAL_NOW_MARGIN:
            raise RunClockError(
                "a backtest cannot pass the real now (less "
                f"{_REAL_NOW_MARGIN.seconds} s): the world has no data from the "
                "future to show"
            )
        # Ledger first, clock second (red-team 0009): reads of now take no lock,
        # so a clock moved before the commit showed the next day's prices to
        # anyone polling — and a failed commit then took the day back. Once
        # committed, ledger_now is already `end` whatever this copy says.
        try:
            append_event(
                session,
                type=EVENT_CLOCK_ADVANCED,
                actor_agent_id=actor_agent_id,
                payload={"from": _iso(start), "to": _iso(end), "minutes": minutes},
                at=end,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        clock.move_to(end)
    return start, end


def declare_minds(
    session: Session, *, minds: Sequence[str], actor_agent_id: int
) -> Event:
    """Record what drives this run's minds; commits. Refuses (:class:`RunMindsError`)
    a live run, a kind not in :data:`MIND_KINDS`, an empty list, a second
    declaration, and one made after the clock moved or a firm agent acted.

    Under ``OMS_LOCK``, as an advance is. Writes that take no lock (a message) can
    still land between the check and the append; :func:`run_minds` reads the
    order the ledger kept, so such a declaration counts for nothing.
    """
    if (not isinstance(minds, Sequence) or isinstance(minds, str)
            or not all(isinstance(k, str) for k in minds)):
        raise RunMindsError("minds is a list of kinds")
    kinds = sorted(set(minds))
    unknown = [k for k in kinds if k not in MIND_KINDS]
    if not kinds or unknown:
        raise RunMindsError(
            f"minds are one or more of {', '.join(sorted(MIND_KINDS))}"
            + (f" (not {', '.join(map(repr, unknown))})" if unknown else "")
        )
    with OMS_LOCK:
        if not _is_backtest(session):
            raise RunMindsError(
                "only a backtest run declares its minds: a live run's agents are "
                "not conducted"
            )
        if _first_declaration(session) is not None:
            raise RunMindsError("this run has declared its minds already: once per run")
        if _acted_before(session, None):
            raise RunMindsError(
                "too late: the clock has moved or a firm agent has acted, and a "
                "declaration must cover everything the run's agents did"
            )
        try:
            event = append_event(
                session,
                type=EVENT_RUN_MINDS_DECLARED,
                actor_agent_id=actor_agent_id,
                payload={"minds": kinds},
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        # The ledger has the last word (red-team 0017 H1/H2): a firm act that took
        # no lock, or another process's declaration, may have landed first. The
        # event stays (append-only), but the caller is told it counts for nothing.
        first = _first_declaration(session)
        if first is None or first.id != event.id or _acted_before(session, event.id):
            raise RunMindsError(
                "lost a race: a firm agent acted or another declaration landed "
                "first, so the ledger does not take this one"
            )
    return event


def run_minds(session: Session) -> tuple[str, ...] | None:
    """The kinds this run declared, or ``None``: a live run, no declaration, a first
    declaration the ledger shows came after a firm agent acted or the clock moved,
    or one that an agent older than it acted under. Only the first declaration is
    ever read.

    A declaration names kinds, not agents, so it covers only the agents
    registered after it (red-team 0017 H4): an older agent's key could be in any
    hand. The one act an older agent may take afterwards is registering (the
    operator's registrar making the run's minds): that trusts the registrar's
    holder, and a registered agent is itself covered.
    """
    if not _is_backtest(session):
        return None
    first = _first_declaration(session)
    if first is None or _acted_before(session, first.id) or _older_agent_acted_after(
        session, first.id
    ):
        return None
    return tuple(first.payload_json["minds"])


def _is_backtest(session: Session) -> bool:
    first = session.scalar(select(Event).order_by(Event.id).limit(1))
    return first is not None and first.type == EVENT_RUN_STARTED


def _first_declaration(session: Session) -> Event | None:
    """The first declaration written by a physics hand. Only :func:`declare_minds`
    writes the type today; the reader does not rely on that (audit c28 NOTE 3)."""
    physics = select(Agent.id).where(Agent.role.in_(PHYSICS_ROLES))
    return session.scalar(
        select(Event)
        .where(Event.type == EVENT_RUN_MINDS_DECLARED, Event.actor_agent_id.in_(physics))
        .order_by(Event.id)
        .limit(1)
    )


def _acted_before(session: Session, before_id: int | None) -> bool:
    """Has the clock moved, or has a firm agent (any non-physics actor) written an
    event — before event ``before_id``, or at all if ``None``?"""
    firm_actors = select(Agent.id).where(Agent.role.not_in(PHYSICS_ROLES))
    query = select(Event.id).where(
        or_(
            Event.type == EVENT_CLOCK_ADVANCED,
            Event.actor_agent_id.in_(firm_actors),
        )
    )
    if before_id is not None:
        query = query.where(Event.id < before_id)
    return session.scalar(query.limit(1)) is not None


def _older_agent_acted_after(session: Session, declared_id: int) -> bool:
    """Did a firm agent not registered after event ``declared_id`` write anything
    but a registration after it?"""
    firm_actors = select(Agent.id).where(Agent.role.not_in(PHYSICS_ROLES))
    registered = func.json_extract(Event.payload_json, "$.agent_id")
    # No NULL in the set: one would make NOT IN NULL for every row, failing open.
    registered_after = select(registered).where(
        Event.type == EVENT_AGENT_REGISTERED, Event.id > declared_id, registered.is_not(None)
    )
    query = select(Event.id).where(
        Event.id > declared_id,
        Event.type != EVENT_AGENT_REGISTERED,
        Event.actor_agent_id.in_(firm_actors),
        Event.actor_agent_id.not_in(registered_after),
    )
    return session.scalar(query.limit(1)) is not None


def _require_same_world(run_started: dict) -> None:
    """Refuse to put a process on a run whose ledger names another market.

    One run, one world (B-037): a server restarted with another key, other
    symbols or another provider would splice two markets into one ledger, and
    nothing in it would say where. Runs opened before worlds were recorded
    carry none and are let through — their ledger never claimed one.
    """
    recorded = run_started.get("world")
    if recorded is None:
        return
    installed = get_provider().world()
    if installed != recorded:
        differs = sorted(
            k for k in recorded.keys() | installed.keys()
            if recorded.get(k) != installed.get(k)
        )
        raise RunClockError(
            "this backtest run lives in another world than the configured market "
            f"(differs in: {', '.join(differs)}): serve it with the provider, "
            "symbols and key it was started with"
        )


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()
