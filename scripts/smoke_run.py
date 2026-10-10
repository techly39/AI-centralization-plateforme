"""Does the fund actually start? A run check outside pytest.

The suite exercises the app in-process. This script checks the other half — the
way an agent host will meet the system: the real CLI builds a database, the real
``fund-env serve`` listens on a port, and a real MCP client launches
``fund-env-mcp`` over stdio with an API key and calls tools through it.

Everything happens in a fresh temporary directory, so ``fund.db`` and its
history are never touched. Like the other scripts here it is a client: it
imports ``mcp``, never ``app``.

Usage:
    uv run python scripts/smoke_run.py

Exit code 0 means every step passed; each step prints one line either way.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
# Read-only tools a management agent may call on an empty firm.
READ_TOOLS = ["get_health", "get_clock", "list_agents", "get_leaderboard", "list_events"]


def step(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    return ok


def run_cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "fund-env", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_health(url: str, deadline_s: float = 30.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            time.sleep(0.3)
    return False


async def mcp_check(env: dict[str, str], errlog_path: Path) -> bool:
    params = StdioServerParameters(command="uv", args=["run", "fund-env-mcp"], cwd=REPO, env=env)
    ok = True
    with errlog_path.open("w") as errlog:
        async with Client(stdio_client(params, errlog=errlog)) as client:
            tools = (await client.list_tools()).tools
            ok &= step("MCP handshake + list_tools", bool(tools), f"{len(tools)} tools")
            for name in READ_TOOLS:
                result = await client.call_tool(name, {})
                text = " ".join(b.text for b in result.content if getattr(b, "type", "") == "text")
                ok &= step(f"MCP call {name}", not result.is_error, text[:80].replace("\n", " "))
    return ok


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fund-smoke-") as tmp:
        tmpdir = Path(tmp)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "FUND_DATABASE_URL": f"sqlite:///{tmpdir / 'smoke.db'}",
            "FUND_MCP__API_BASE_URL": base,
        }
        env.pop("FUND_MCP__API_KEY", None)

        r = run_cli(env, "init-db")
        if not step("fund-env init-db", r.returncode == 0, r.stdout.strip()):
            return 1
        r = run_cli(env, "seed-admin", "--name", "smoke-mgmt")
        key = re.search(r"\bfk_\S+", r.stdout)
        if not step("fund-env seed-admin", r.returncode == 0 and key is not None):
            return 1
        r = run_cli(env, "create-pod", "--name", "smoke-pod", "--allocation", "1000000")
        if not step("fund-env create-pod", r.returncode == 0, (r.stdout.splitlines() or [r.stderr])[0]):
            return 1

        server_log = (tmpdir / "serve.log").open("w")
        server = subprocess.Popen(
            ["uv", "run", "fund-env", "serve", "--port", str(port)],
            cwd=REPO, env=env, stdout=server_log, stderr=subprocess.STDOUT,
        )
        try:
            if not step("fund-env serve answers /health", wait_for_health(base), base):
                print((tmpdir / "serve.log").read_text()[-2000:])
                return 1
            ok = step("GET /docs", urllib.request.urlopen(f"{base}/docs", timeout=5).status == 200)
            mcp_env = {**env, "FUND_MCP__API_KEY": key.group(0)}
            ok &= anyio.run(mcp_check, mcp_env, tmpdir / "mcp.log")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
            server_log.close()
        step("server stopped cleanly", server.returncode is not None, f"rc={server.returncode}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
