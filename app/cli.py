"""Operator command line: set up the database, seed the first admin, run.

    uv run fund-env init-db          # create/upgrade schema via alembic
    uv run fund-env seed-admin       # create the first management agent (prints key once)
    uv run fund-env rebuild-state    # rebuild derived tables from the ledger
    uv run fund-env serve            # start the API server

Kept dependency-free (argparse) so it works the moment the package installs.
"""

from __future__ import annotations

import argparse
import sys

from alembic import command
from alembic.config import Config as AlembicConfig

from app.config import REPO_ROOT, get_settings
from app.db.base import session_scope
from app.db.models import AgentRole
from app.ledger.rebuild import rebuild_state
from app.logging_setup import setup_logging
from app.registry.service import RegistryError, register_agent


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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
