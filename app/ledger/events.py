"""Append-only event store (TRD §5, principle 4).

The ledger is the source of truth. Anything that changes state appends an
``Event`` here through :func:`append_event`; derived tables are rebuilt from it.
Event ``type`` strings are centralised as constants so producers and reducers
cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, case, func, literal, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Event
from app.db.types import UTCDateTime
from app.finite import json_problem
from app.limits import MAX_LEDGER_DEPTH

# --- Canonical event types --------------------------------------------------
# Lifecycle / audit events (no derived-state effect):
EVENT_AGENT_REGISTERED = "agent_registered"
EVENT_AGENT_DEACTIVATED = "agent_deactivated"
EVENT_AGENT_KEY_ROTATED = "agent_key_rotated"  # payload: {agent_id} — never the key or its hash
EVENT_PERMISSION_DENIED = "permission_denied"
EVENT_HALT_REFUSED = "halt_refused"       # payload: {method, path, role}

EVENT_MESSAGE_SENT = "message_sent"       # payload: {message_id, to, from_agent_id}

# The run's time (ADR-027, app/run_clock.py). A backtest ledger opens with
# ``run_started``; its simulated now moves only by ``clock_advanced``.
EVENT_RUN_STARTED = "run_started"         # payload: {mode, start, look_ahead_guard, world}
EVENT_CLOCK_ADVANCED = "clock_advanced"   # payload: {from, to, minutes}
# What drives the run's minds, as the Runtime declares it (ADR-032 (p)).
EVENT_RUN_MINDS_DECLARED = "run_minds_declared"  # payload: {minds: [kind, ...] sorted}

# Self-reported agent activity (TRD §7). Audit only: the app cannot verify these
# numbers, it can only guarantee they were reported by the agent they name.
EVENT_COST_REPORTED = "cost_reported"     # payload: {cost_id, tokens_in, tokens_out, usd_cost}
EVENT_TASK_STARTED = "task_started"       # payload: {task_id, subject}
EVENT_TASK_ENDED = "task_ended"           # payload: {task_id, subject, seconds, outcome}

# System-reported cost (ADR-041): the Runtime's provisioner says what a key has
# cost in total so far. Cumulative integer micro-dollars; audit only (the
# metrics fold these events, there is no table).
EVENT_COST_METERED = "cost_metered"       # payload: {agent_id, pod_id, key_ref, usd_micros_total}

# Strategy science (app/strategy/service.py). Audit only: the read side folds them, no table.
EVENT_RESEARCH_BACKTEST_RUN = "research_backtest_run"  # payload: {pod_id, agent_id, attempt, rule, window, performance}
EVENT_PITCH_SUBMITTED = "pitch_submitted"  # payload: {pod_id, agent_id, hypothesis, data_needed, team, budget_usd, rule}
EVENT_PITCH_JUDGED = "pitch_judged"        # payload: {pitch_id, pod_id, window, attempts, eligible, gates, performance, law}

# The capital machine (app/capital/service.py). Audit only: money moves by allocation_set and
# order_filled; the pod's stage is mirrored on its row (rebuild_state re-derives it).
EVENT_CAPITAL_OPENED = "capital_opened"            # payload: {law, firm_capital_usd}
EVENT_CAPITAL_SEEDED = "capital_seeded"            # payload: {pod_id, pitch_id, seed_usd, rule, cost_at_seed_usd}
EVENT_CAPITAL_SEED_REFUSED = "capital_seed_refused"  # payload: {pod_id, pitch_id, reason}
EVENT_CAPITAL_REALLOCATED = "capital_reallocated"  # payload: {day, inputs: {centre_cash, pods}, result}
EVENT_POD_STAGE_CHANGED = "pod_stage_changed"      # payload: {pod_id, from, to, drawdown, index, high_water}
EVENT_CAPITAL_SWEEP_FAILED = "capital_sweep_failed"  # payload: {error}: the machine skipped this advance

# Hiring (app/capital/hiring.py): a pod the ladder closed opens a vacancy; a registrar fills it
# with a new pod and PM (the agent_registered follows), or the Runtime refuses the hire.
EVENT_VACANCY_OPENED = "vacancy_opened"  # payload: {vacancy_no, pod_id, pod_name, post_mortem, hire, law}
EVENT_VACANCY_FILLED = "vacancy_filled"  # payload: {vacancy_id, pod_id, pod_name, agent_id, agent_name, model, budget_usd}
EVENT_HIRE_REFUSED = "hire_refused"      # payload: {vacancy_id, reason, by}
EVENT_HIRE_FAILED = "hire_failed"        # payload: {vacancy_id, pod_id, agent_id, reason}: the hired pod is closed, the vacancy open again

# Generations (app/capital/generation.py): at each month's end every pod's fitness; a PM who failed
# is let go (its agent deactivated; an unseeded pod closed, a vacancy opened) and its lesson kept.
EVENT_GENERATION_ENDED = "generation_ended"  # payload: {generation, month, from, to, law, pods: [...]}
EVENT_DIVERSITY_COLLAPSED = "diversity_collapsed"  # payload: {generation, month, family, live_pods, designs, finding}
EVENT_PM_LET_GO = "pm_let_go"            # payload: {lesson_no, agent_id, agent_name, pod_id, pod_name, reason, why, pod_closed, generation, lesson}

# Teams (app/capital/team.py): a PM asks for an analyst; physics grants a team place or refuses;
# a registrar fills the place (the agent_registered follows) the next morning; the PM lets it go.
EVENT_TEAM_PLACE_OPENED = "team_place_opened"  # payload: {place_no, pod_id, pod_name, asked_by, asked_by_name, name, role, model, budget_usd, charter, law}
EVENT_TEAM_REQUEST_REFUSED = "team_request_refused"  # payload: {pod_id, agent_id, reason, asked}
EVENT_TEAM_PLACE_FILLED = "team_place_filled"  # payload: {place_id, pod_id, agent_id, agent_name, model, budget_usd}
EVENT_TEAM_HIRE_REFUSED = "team_hire_refused"  # payload: {place_id, reason, by}: the place stays open
EVENT_TEAM_PLACE_CLOSED = "team_place_closed"  # payload: {place_id, pod_id, reason}: never filled
EVENT_TEAM_MEMBER_LET_GO = "team_member_let_go"  # payload: {place_id, pod_id, agent_id, agent_name, reason, by}

# Management (app/capital/management.py): a manager mind picks a freed place's hire among the
# candidates its vacancy lists, briefs the new PM, and writes the firm's direction.
EVENT_HIRE_PICKED = "hire_picked"        # payload: {vacancy_id, candidate, brief, by, by_name}
EVENT_HIRE_PICK_REFUSED = "hire_pick_refused"  # payload: {vacancy_id, candidate, reason, by}
EVENT_DIRECTION_SET = "direction_set"    # payload: {direction_no, text, by, by_name}

# OMS lifecycle events (audit only — no effect on derived state):
EVENT_ORDER_PLACED = "order_placed"       # payload: {order_id, pod_id, ticker, side, ...}
EVENT_ORDER_REJECTED = "order_rejected"   # payload: {order_id, reason, detail}
EVENT_ORDER_CANCELLED = "order_cancelled" # payload: {order_id}

# State-changing events consumed by the rebuild reducers. Every reducer-backed
# event MUST carry ``pod_id`` in its payload: that is how the incremental
# applier (app/ledger/apply.py) knows which derived rows to load and rewrite.
EVENT_ALLOCATION_SET = "allocation_set"   # payload: {pod_id, delta}
EVENT_ORDER_FILLED = "order_filled"       # payload: {pod_id, ticker, side, qty, fill_price, fee}

# --- What no agent reads (B-049, ADR-034) -------------------------------------
# The operator's facts about the experiment stay in the ledger, whole, for
# physics and the operator's tools. An agent reads an event only as
# ``EventOut``, which replaces each field named here with :data:`WITHHELD`:
# the world's generating law (drift, volatility, symbols, fingerprint) is an
# edge no participant may hold, and what drives the minds is the scientists'
# label, not a fact of the world.
WITHHELD = "withheld"
AGENT_WITHHELD_FIELDS: dict[str, frozenset[str]] = {
    EVENT_RUN_STARTED: frozenset({"world"}),
    EVENT_RUN_MINDS_DECLARED: frozenset({"minds"}),
    EVENT_COST_METERED: frozenset({"key_ref"}),
}


def agent_payload(type: str, payload: dict | None) -> dict:
    """A new dict: ``payload`` as an agent may read it. Never mutates ``payload``."""
    hidden = AGENT_WITHHELD_FIELDS.get(type, frozenset())
    return {k: (WITHHELD if k in hidden else v) for k, v in (payload or {}).items()}


def append_event(
    session: Session,
    *,
    type: str,
    actor_agent_id: int | None,
    payload: dict | None = None,
    at: datetime | None = None,
) -> Event:
    """Append one immutable event, timestamped from the injected clock.

    ``at`` stamps the event at a given moment instead of the clock's (still under
    the floor). Only for the backtest advance (ADR-029): it records the new now
    *before* the process clock moves, so no reader sees a now the ledger has not
    committed (red-team 0009).

    The caller owns the transaction (commit/rollback). We flush so the event's
    ``id`` is populated for anyone who needs it in the same unit of work.

    Raises ``ValueError`` for a payload holding ``NaN``/``±inf`` or an int beyond
    ±2**53 anywhere, or nested deeper than ``MAX_LEDGER_DEPTH``: the ledger stays
    standard JSON that any tool can replay (ADR-024).

    Ledger time never runs backwards (ADR-025): the event is stamped with the
    clock, or with the latest stamp already in the ledger if the clock is behind
    it. So id order and time order are one order, and a day bucket never holds an
    event the live fold applied after a later day's.
    """
    problem = json_problem(payload or {}, max_depth=MAX_LEDGER_DEPTH)
    if problem:
        raise ValueError(f"{problem} in {type!r} event payload")
    clock = get_clock()
    _refuse_wrong_run_clock(session, type, clock.mode)
    event = Event(
        ts=_not_before_latest(clock.now() if at is None else at),
        actor_agent_id=actor_agent_id,
        type=type,
        payload_json=payload or {},
    )
    session.add(event)
    session.flush()
    return event


class RunClockMismatch(RuntimeError):
    """This process's clock is not its database's run clock (ADR-027)."""


def _refuse_wrong_run_clock(session: Session, type: str, mode: str) -> None:
    """A backtest ledger takes only backtest stamps, and a live one none.

    A process learns its run's clock when it starts; a server already running
    on a file that ``start-backtest`` then opened would otherwise stamp today
    into a 2024 run, for good (red-team 0007). One indexed read per append.
    """
    first = session.scalar(select(Event.type).order_by(Event.id).limit(1))
    backtest_ledger = first == EVENT_RUN_STARTED or (
        first is None and type == EVENT_RUN_STARTED
    )
    if backtest_ledger != (mode == "backtest"):
        raise RunClockMismatch(
            f"the {mode} clock of this process does not belong to this database's "
            f"{'backtest' if backtest_ledger else 'live'} run: restart the server"
        )


def ledger_now(session: Session) -> datetime:
    """The time the next event would be stamped with: ``max(clock, latest ts)``.

    What ``GET /clock`` tells agents (ADR-026): after the clock steps back the
    ledger holds its stamps (ADR-025), and a read of the raw clock would then
    disagree with the stamp on the agent's very next order.
    """
    return session.scalar(select(_not_before_latest(get_clock().now())))


def _not_before_latest(now: datetime) -> ColumnElement[datetime]:
    """``max(now, latest ts in the ledger)``, evaluated inside the INSERT itself.

    One statement, so the floor is read under the same write lock the row is
    written with (SQLite serialises writers): no other append can land between
    reading the latest stamp and using it. ``CASE`` rather than ``max(a, b)``
    because Postgres spells two-argument max ``GREATEST``. An empty ledger gives
    ``NULL > now`` → not true → ``now``.
    """
    clock_now = literal(now, UTCDateTime)
    latest = select(func.max(Event.ts)).scalar_subquery()
    return case((latest > clock_now, latest), else_=clock_now)


def read_events(
    session: Session,
    *,
    actor_agent_id: int | None = None,
    type: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> Sequence[Event]:
    """Query the ledger in append order — the order live state was folded in."""
    stmt = select(Event)
    if actor_agent_id is not None:
        stmt = stmt.where(Event.actor_agent_id == actor_agent_id)
    if type is not None:
        stmt = stmt.where(Event.type == type)
    if since is not None:
        stmt = stmt.where(Event.ts >= since)
    stmt = stmt.order_by(Event.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return session.execute(stmt).scalars().all()
