"""Operator command line: set up the database, seed the first admin, run.

    uv run fund-env init-db          # create/upgrade schema via alembic
    uv run fund-env seed-admin       # create the first management agent (prints key once)
    uv run fund-env seed-runtime     # create the Runtime's clock identity (prints key once)
    uv run fund-env rotate-runtime-key   # new Runtime key, the old one dies (prints key once)
    uv run fund-env create-pod       # create a trading pod and fund it
    uv run fund-env fund-pod         # change a pod's allocation
    uv run fund-env check-orders     # run one pending-limit-order sweep now
    uv run fund-env start-backtest --start 2024-01-02T14:30:00Z   # empty DB → backtest run
    uv run fund-env rebuild-state    # rebuild derived tables from the ledger
    uv run fund-env serve            # start the API server

Kept dependency-free (argparse) so it works the moment the package installs.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import date, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from app.config import REPO_ROOT, get_settings
from app.db.base import session_scope
from app.db.models import AgentRole
from app.ledger.compare import LedgerFileError, compare, ledger_rows, locate, rows_document
from app.ledger.rebuild import rebuild_state
from app.logging_setup import setup_logging
from app.registry.pods import create_pod, fund_pod
from app.registry.service import (
    RegistryError,
    check_reserved_identities,
    get_or_create_system_agent,
    register_agent,
    rotate_runtime_key,
    seed_runtime_agent,
)
from app.run_clock import RunClockError, install_run_clock, run_minds, start_backtest

#: Commands that do not run on the database's clock: ``init-db`` may find no
#: schema yet, ``start-backtest`` creates the clock, ``serve`` installs it itself.
_NO_RUN_CLOCK = frozenset({"init-db", "start-backtest", "serve", "compare-ledgers",
                           "export-ledger", "gates"})


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    # alembic.ini's ``script_location = migrations`` is relative to the working directory, so
    # ``init-db`` failed from anywhere but the repo root (found planning M-002): make it absolute.
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def cmd_init_db(_: argparse.Namespace) -> int:
    """Bring the database schema up to the latest migration."""
    command.upgrade(_alembic_config(), "head")
    print("Database schema is up to date (alembic head).")
    return 0


def cmd_seed_admin(args: argparse.Namespace) -> int:
    """Create the first management agent so it can register everyone else."""
    with session_scope() as session:
        try:
            agent, api_key = register_agent(
                session,
                name=args.name,
                role=AgentRole.management,
                charter_ref=args.charter_ref,
            )
        except RegistryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    print("Management agent created.")
    print(f"  id:   {agent.id}")
    print(f"  name: {agent.name}")
    print(f"  role: {agent.role.value}")
    print()
    print("API KEY (shown once — store it now, it is not retrievable later):")
    print(f"  {api_key}")
    return 0


def cmd_seed_runtime(_: argparse.Namespace) -> int:
    """Create the Runtime's identity, the hand that moves a backtest's clock."""
    with session_scope() as session:
        try:
            agent, api_key = seed_runtime_agent(session)
        except RegistryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    print("Runtime identity created (it may read and advance the clock, nothing else).")
    print(f"  id:   {agent.id}")
    print(f"  name: {agent.name}")
    print()
    print("API KEY (shown once — give it to the Runtime only, never to a firm agent):")
    print(f"  {api_key}")
    return 0


def cmd_rotate_runtime_key(_: argparse.Namespace) -> int:
    """Replace the Runtime's key; the old one stops working at once (B-041)."""
    with session_scope() as session:
        try:
            agent, api_key = rotate_runtime_key(session)
        except RegistryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        agent_id = agent.id

    print(f"Runtime identity {agent_id} has a new key; the old key no longer works.")
    print()
    print("API KEY (shown once — give it to the Runtime only, never to a firm agent):")
    print(f"  {api_key}")
    return 0


def cmd_create_pod(args: argparse.Namespace) -> int:
    """Create a trading pod and (optionally) give it its starting cash."""
    with session_scope() as session:
        try:
            pod = create_pod(session, name=args.name)
            if args.allocation:
                fund_pod(
                    session,
                    pod_id=pod.id,
                    delta=args.allocation,
                    actor=get_or_create_system_agent(session),
                    reason="initial allocation",
                )
        except RegistryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        pod_id, pod_name, allocation = pod.id, pod.name, pod.current_allocation

    print(f"Pod created: id={pod_id} name={pod_name} allocation=${allocation:,.2f}")
    print(f"Attach a PM with:  fund-env seed-admin  → then POST /agents/register "
          f'{{"name": "...", "role": "pm", "pod_id": {pod_id}}}')
    return 0


def cmd_fund_pod(args: argparse.Namespace) -> int:
    """Add to (or, with a negative delta, take from) a pod's allocation."""
    with session_scope() as session:
        try:
            pod = fund_pod(
                session,
                pod_id=args.pod_id,
                delta=args.delta,
                actor=get_or_create_system_agent(session),
                reason=args.reason,
            )
        except RegistryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        pod_id, allocation = pod.id, pod.current_allocation

    print(f"Pod {pod_id} allocation is now ${allocation:,.2f}")
    return 0


def cmd_check_orders(_: argparse.Namespace) -> int:
    """Run the pending-limit-order sweep once, right now."""
    from app.oms.monitor import check_pending_orders

    with session_scope() as session:
        result = check_pending_orders(session)
    print(
        f"Checked {result.checked} pending order(s): "
        f"{len(result.filled)} filled, {len(result.rejected)} rejected."
    )
    if result.unpriced:
        print(f"  No price available for: {', '.join(sorted(set(result.unpriced)))}")
    return 0


def cmd_start_backtest(args: argparse.Namespace) -> int:
    """Open a backtest run in an empty database (ADR-027)."""
    try:
        start = datetime.fromisoformat(args.start)
    except ValueError:
        print(f"Error: --start {args.start!r} is not an ISO-8601 time", file=sys.stderr)
        return 1
    with session_scope() as session:
        try:
            clock = start_backtest(session, start=start)
        except (RunClockError, ValueError) as exc:  # ValueError: no world configured
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        now = clock.now()

    print(f"Backtest run started: the clock is at {now.isoformat()}.")
    print("It moves only by POST /clock/advance, with the Runtime's key "
          "(fund-env seed-runtime). Seed agents and pods next.")
    return 0


def cmd_compare_ledgers(args: argparse.Namespace) -> int:
    """Exit 0 if the ledgers are equal but for the one allowed difference, 1 if they differ,
    2 if a path is not a readable fund database. Read-only, touches no configured database."""
    try:
        recorded, replayed = ledger_rows(args.recorded), ledger_rows(args.replayed)
    except LedgerFileError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    result = compare(recorded, replayed)
    # Where the first difference sits in the run (null, not 0, when equal): M-002's verdict names it.
    where = (None if result.first_difference is None
             else locate(recorded, result.first_difference)
             or locate(replayed, result.first_difference))
    print(json.dumps({**dataclasses.asdict(result), "locate": where}, sort_keys=True))
    return 0 if result.equal else 1


def cmd_export_ledger(args: argparse.Namespace) -> int:
    """Print the ledger of the database at ``path`` as a canonical rows document (the cassette's
    recorded ledger). Read-only; exit 2 if the path is not a readable fund database."""
    try:
        print(rows_document(ledger_rows(args.database)))
    except LedgerFileError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    """Judge a strategy-v1 rule on a bars file with the validation gates and print the verdict
    (JSON). Pure: reads no database and no feed, so anyone can rerun a pitch's numbers on any
    world. Exit 2 if a file or the rule is not readable."""
    from pydantic import ValidationError

    from app.strategy.files import BarsFileError, read_bars
    from app.strategy.gates import judge
    from app.strategy.rule import EvaluationError, StrategyRule, evaluate

    fee = get_settings().oms.fee_rate
    try:
        if args.attempts < 1:
            raise ValueError("--attempts counts this strategy itself: at least 1")
        bars = read_bars(args.bars)
        rule = StrategyRule.model_validate_json(args.rule.read_text())
        start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
        mine = evaluate(rule, bars, start=start, end=end, fee_rate=fee)
        others = {}
        for spec in args.other or []:
            name, _, path = spec.partition("=")
            if not name or not path:
                raise ValueError(f"--other wants NAME=RULE_FILE, not {spec!r}")
            theirs = evaluate(StrategyRule.model_validate_json(Path(path).read_text()), bars,
                              start=start, end=end, fee_rate=fee)
            others[name] = (theirs.days, theirs.returns)
    except (OSError, ValueError, ValidationError, BarsFileError, EvaluationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    verdict = judge(mine, attempts=args.attempts, others=others, law=get_settings().gates)
    print(json.dumps({"rule": rule.model_dump(), **verdict}, sort_keys=True))
    return 0


def cmd_run_minds(_: argparse.Namespace) -> int:
    """Print what drove this run's minds, as the ledger proves it (B-051): ``{"minds": [...]}``,
    or ``{"minds": null}`` for a live run or a declaration the ledger does not support."""
    with session_scope() as session:
        minds = run_minds(session)
    print(json.dumps({"minds": None if minds is None else list(minds)}))
    return 0


def cmd_rebuild_state(_: argparse.Namespace) -> int:
    with session_scope() as session:
        state = rebuild_state(session)
    print(
        f"Rebuilt derived state: {len(state.cash)} cash balance(s), "
        f"{len(state.positions)} position(s)."
    )
    return 0


def cmd_generation_report(args: argparse.Namespace) -> int:
    """Print the generation report of the run in the configured database: each month's fitness
    table, who was let go and why, who was hired, and the library of lessons. Read-only."""
    from app.capital.report import generation_report, render_generations

    with session_scope() as session:
        report = generation_report(session)
        session.rollback()
    print(json.dumps(report, sort_keys=True) if args.json else render_generations(report))
    return 0


def cmd_quarter_report(args: argparse.Namespace) -> int:
    """Print the quarter report of the run in the configured database: each pod's equity week by
    week, its P&L gross and net of thinking, the re-weighings, the deaths and the hires. Read-only.
    (An operator's command, not an agent's tool: a new tool would change the full tool list a
    recorded mind was shown, and its replay would diverge.)"""
    from app.capital.report import quarter_report, render
    from app.marketdata import get_provider

    with session_scope() as session:
        report = quarter_report(session, provider=get_provider(), every_days=args.every_days)
        session.rollback()
    print(json.dumps(report, sort_keys=True) if args.json else render(report))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    cfg = get_settings().server
    uvicorn.run(
        "app.main:app",
        host=args.host or cfg.host,
        port=args.port or cfg.port,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fund-env", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="create/upgrade the database schema")
    p_init.set_defaults(func=cmd_init_db)

    p_seed = sub.add_parser("seed-admin", help="create the first management agent")
    p_seed.add_argument("--name", default="management", help="agent name (default: management)")
    p_seed.add_argument("--charter-ref", default=None, help="optional charter reference")
    p_seed.set_defaults(func=cmd_seed_admin)

    p_rt = sub.add_parser(
        "seed-runtime", help="create the Runtime's clock identity (one per database)"
    )
    p_rt.set_defaults(func=cmd_seed_runtime)

    p_rot = sub.add_parser(
        "rotate-runtime-key", help="give the Runtime's identity a new key (the old one dies)"
    )
    p_rot.set_defaults(func=cmd_rotate_runtime_key)

    p_pod = sub.add_parser("create-pod", help="create a trading pod")
    p_pod.add_argument("--name", required=True, help="pod name (unique)")
    p_pod.add_argument(
        "--allocation", type=float, default=0.0,
        help="starting virtual cash (default: 0)",
    )
    p_pod.set_defaults(func=cmd_create_pod)

    p_fund = sub.add_parser("fund-pod", help="change a pod's allocation")
    p_fund.add_argument("--pod-id", type=int, required=True)
    p_fund.add_argument("--delta", type=float, required=True, help="negative withdraws")
    p_fund.add_argument("--reason", default=None)
    p_fund.set_defaults(func=cmd_fund_pod)

    p_check = sub.add_parser(
        "check-orders", help="run one pending-limit-order sweep immediately"
    )
    p_check.set_defaults(func=cmd_check_orders)

    p_bt = sub.add_parser(
        "start-backtest", help="open a backtest run in an empty database"
    )
    p_bt.add_argument(
        "--start", required=True,
        help="simulated start, ISO-8601 with timezone (e.g. 2024-01-02T14:30:00Z)",
    )
    p_bt.set_defaults(func=cmd_start_backtest)

    p_cmp = sub.add_parser(
        "compare-ledgers",
        help="read-only: is REPLAYED's ledger RECORDED's but for the run_minds_declared payload?",
    )
    p_cmp.add_argument("recorded", type=Path, help="the recorded run's database file")
    p_cmp.add_argument("replayed", type=Path, help="the replay's database file")
    p_cmp.set_defaults(func=cmd_compare_ledgers)

    p_exp = sub.add_parser(
        "export-ledger",
        help="read-only: print DATABASE's ledger as a canonical rows document (JSON)",
    )
    p_exp.add_argument("database", type=Path, help="a fund database file")
    p_exp.set_defaults(func=cmd_export_ledger)

    p_gates = sub.add_parser(
        "gates", help="read-only: judge a strategy rule on a bars file with the validation gates"
    )
    p_gates.add_argument("bars", type=Path,
                         help="JSON: {ticker: [[day, open, high, low, close, volume], ...]} "
                              "(or a prices-v1 package)")
    p_gates.add_argument("rule", type=Path, help="JSON: a strategy-v1 rule")
    p_gates.add_argument("--start", required=True, help="first day of the judged window (ISO)")
    p_gates.add_argument("--end", required=True, help="the day after the window (ISO, exclusive)")
    p_gates.add_argument("--attempts", type=int, default=1,
                         help="how many strategies the pod tried, this one included (default 1)")
    p_gates.add_argument("--other", action="append", metavar="NAME=RULE_FILE",
                         help="another pod's rule, run on the same bars (repeatable)")
    p_gates.set_defaults(func=cmd_gates)

    p_minds = sub.add_parser(
        "run-minds", help="read-only: what drove this run's minds, as the ledger proves it"
    )
    p_minds.set_defaults(func=cmd_run_minds)

    p_rebuild = sub.add_parser("rebuild-state", help="rebuild derived tables from events")
    p_rebuild.set_defaults(func=cmd_rebuild_state)

    p_qr = sub.add_parser("quarter-report", help="print the capital machine's quarter report")
    p_qr.add_argument("--every-days", type=int, default=7, choices=range(1, 91),
                      metavar="N", help="days between two columns (default 7)")
    p_qr.add_argument("--json", action="store_true", help="the report as JSON")
    p_qr.set_defaults(func=cmd_quarter_report)

    p_gr = sub.add_parser("generation-report", help="print each month's generation and the library")
    p_gr.add_argument("--json", action="store_true", help="the report as JSON")
    p_gr.set_defaults(func=cmd_generation_report)

    p_serve = sub.add_parser("serve", help="run the API server")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--reload", action="store_true", help="auto-reload (dev)")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    if args.command not in _NO_RUN_CLOCK:
        # A backtest database's operator commands stamp the run's simulated now,
        # never today's: one live stamp would hold every later event (ADR-025).
        # And in the run's own world, or not at all (B-037).
        # And never on a database whose reserved identities are broken (B-041).
        try:
            with session_scope() as session:
                check_reserved_identities(session)
                install_run_clock(session)
        except (RunClockError, ValueError, RegistryError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
