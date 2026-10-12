"""Operator command line: set up the database, seed the first admin, run.

    uv run fund-env init-db          # create/upgrade schema via alembic
    uv run fund-env seed-admin       # create the first management agent (prints key once)
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
import sys
from datetime import datetime

from alembic import command
from alembic.config import Config as AlembicConfig

from app.config import REPO_ROOT, get_settings
from app.db.base import session_scope
from app.db.models import AgentRole
from app.ledger.rebuild import rebuild_state
from app.logging_setup import setup_logging
from app.registry.pods import create_pod, fund_pod
from app.registry.service import (
    RegistryError,
    get_or_create_system_agent,
    register_agent,
)
from app.run_clock import RunClockError, install_run_clock, start_backtest

#: Commands that do not run on the database's clock: ``init-db`` may find no
#: schema yet, ``start-backtest`` creates the clock, ``serve`` installs it itself.
_NO_RUN_CLOCK = frozenset({"init-db", "start-backtest", "serve"})


def _alembic_config() -> AlembicConfig:
    return AlembicConfig(str(REPO_ROOT / "alembic.ini"))


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
        except RunClockError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        now = clock.now()

    print(f"Backtest run started: the clock is at {now.isoformat()}.")
    print("It moves only by POST /clock/advance (management). Seed agents and pods next.")
    return 0


def cmd_rebuild_state(_: argparse.Namespace) -> int:
    with session_scope() as session:
        state = rebuild_state(session)
    print(
        f"Rebuilt derived state: {len(state.cash)} cash balance(s), "
        f"{len(state.positions)} position(s)."
    )
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

    p_rebuild = sub.add_parser("rebuild-state", help="rebuild derived tables from events")
    p_rebuild.set_defaults(func=cmd_rebuild_state)

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
        try:
            with session_scope() as session:
                install_run_clock(session)
        except (RunClockError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
