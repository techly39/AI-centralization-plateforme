"""Stand up two agents to talk to each other, through the real MCP surface.

The first management key has to come from the operator CLI — something must
exist before anything can be registered. Everything after that is done the way
an agent would do it: this script is an MCP client holding management's key, and
it calls ``register_agent`` exactly as a management agent would.

    uv run fund-env init-db
    uv run fund-env seed-admin --name mgmt
    uv run fund-env create-pod --name demo-pod --allocation 1000000
    uv run fund-env serve                      # in another terminal
    uv run python scripts/setup_demo_firm.py --management-key fk_... --pod-id 1

It writes the new keys to ``agents.local.json`` — that file is a set of
credentials, so it is gitignored, and the keys are unrecoverable if you lose it.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
KEYFILE = ROOT / "agents.local.json"


async def call(client: Client, tool: str, arguments: dict) -> dict:
    result = await client.call_tool(tool, arguments)
    text = "\n".join(b.text for b in result.content if getattr(b, "type", "") == "text")
    if result.is_error:
        raise RuntimeError(f"{tool}: {text}")
    blocks = []
    for block in result.content:
        if getattr(block, "type", "") == "text":
            try:
                blocks.append(json.loads(block.text))
            except json.JSONDecodeError:
                blocks.append(block.text)
    return blocks[0] if len(blocks) == 1 else blocks


async def run(args: argparse.Namespace) -> int:
    command, *command_args = shlex.split(args.mcp_command)
    params = StdioServerParameters(
        command=command,
        args=command_args,
        cwd=str(ROOT),
        env={
            **os.environ,
            "FUND_MCP__API_KEY": args.management_key,
            "FUND_MCP__API_BASE_URL": args.api_url,
        },
    )

    async with Client(stdio_client(params)) as client:
        health = await call(client, "get_health", {})
        print(f"fund API: {health['status']}, clock {health['clock_mode']}")

        existing = await call(client, "list_agents", {})
        by_name = {row["name"]: row for row in existing}
        print(f"directory has {len(existing)} agent(s): "
              f"{', '.join(sorted(by_name)) or '(empty)'}")

        created: dict[str, dict] = {}
        wanted = [
            (args.analyst_name, "analyst", args.pod_id, ["semis", "ai-infra"]),
            (args.pm_name, "pm", args.pod_id, None),
        ]
        for name, role, pod_id, domains in wanted:
            if name in by_name:
                print(f"  ! {name} already exists (id {by_name[name]['id']}) — "
                      "its key was shown once at registration and cannot be re-read. "
                      "Use --analyst-name/--pm-name to make fresh ones.")
                continue
            agent = await call(client, "register_agent", {
                "name": name,
                "role": role,
                "pod_id": pod_id,
                "research_domains": domains,
            })
            created[name] = agent
            print(f"  + registered {name}: agent:{agent['id']} ({role}, pod {pod_id})")

        if not created:
            print("\nNothing new to write.")
            return 0

        record = json.loads(KEYFILE.read_text()) if KEYFILE.exists() else {}
        record.update({
            name: {"id": a["id"], "role": a["role"], "pod_id": a.get("pod_id"),
                   "api_key": a["api_key"]}
            for name, a in created.items()
        })
        KEYFILE.write_text(json.dumps(record, indent=2) + "\n")
        KEYFILE.chmod(0o600)
        print(f"\nkeys written to {KEYFILE.relative_to(ROOT)} (mode 600, gitignored)")

        print("\nOpen two terminals and run one of these in each:\n")
        for name, agent in created.items():
            other = next((n for n in created if n != name), None)
            to = f" --to agent:{created[other]['id']}" if other else ""
            print(f"  uv run python scripts/agent_console.py --as {name}{to} \\")
            print(f"      --api-key {agent['api_key']}")
            print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--management-key", required=True,
                        help="key printed by `fund-env seed-admin`")
    parser.add_argument("--pod-id", type=int, required=True,
                        help="pod the two agents belong to (`fund-env create-pod`)")
    parser.add_argument("--analyst-name", default="sara")
    parser.add_argument("--pm-name", default="marcus")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mcp-command", default="uv run fund-env-mcp")
    args = parser.parse_args(argv)

    try:
        return anyio.run(run, args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
