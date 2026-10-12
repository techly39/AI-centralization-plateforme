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

import json
import os
import re
import secrets
import signal
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
    if (REPO / "governance" / "HALT").exists():
        print("governance/HALT exists — not starting anything (Constitution Art. 5).")
        return 1
    with tempfile.TemporaryDirectory(prefix="fund-smoke-") as tmp:
        tmpdir = Path(tmp)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        # Drop every inherited FUND_* override so the run is defined by config.yaml + these two.
        env = {k: v for k, v in os.environ.items() if not k.startswith("FUND_")}
        env["FUND_DATABASE_URL"] = f"sqlite:///{tmpdir / 'smoke.db'}"
        env["FUND_MCP__API_BASE_URL"] = base

        r = run_cli(env, "init-db")
        detail = r.stdout.strip() if r.returncode == 0 else (r.stdout + r.stderr).strip()[-300:]
        if not step("fund-env init-db", r.returncode == 0, detail):
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
            try:
                docs_ok = urllib.request.urlopen(f"{base}/docs", timeout=5).status == 200
            except OSError as exc:
                docs_ok = False
                print(f"       {exc}")
            ok = step("GET /docs", docs_ok)
            mcp_env = {**env, "FUND_MCP__API_KEY": key.group(0)}
            ok &= anyio.run(mcp_check, mcp_env, tmpdir / "mcp.log")
        finally:
            # SIGINT is the Ctrl-C an operator sends; a graceful shutdown exits 0.
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=10)
                killed = False
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
                killed = True
            server_log.close()
        ok &= step("server stopped cleanly on SIGINT", not killed and server.returncode == 0,
                   f"rc={server.returncode}")
    ok &= backtest_check()
    return 0 if ok else 1


def stop(server: subprocess.Popen) -> bool:
    """SIGINT, as an operator would; True if it shut down cleanly."""
    server.send_signal(signal.SIGINT)
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()
        return False
    return server.returncode == 0


def backtest_check() -> bool:
    """The desk month's first days through the operator's commands (R-3b-2c-1): a
    synthetic backtest database, ``fund-env serve`` on it, and ``fund-runtime
    backtest`` provisioning ``specs/desk-month`` and conducting the run."""
    with tempfile.TemporaryDirectory(prefix="fund-smoke-bt-") as tmp:
        tmpdir = Path(tmp)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {k: v for k, v in os.environ.items() if not k.startswith("FUND_")}
        env["FUND_DATABASE_URL"] = f"sqlite:///{tmpdir / 'backtest.db'}"
        env["FUND_MARKETDATA__PROVIDER"] = "synthetic"
        env["FUND_MARKETDATA__SYNTHETIC_KEY"] = secrets.token_hex(32)
        keys = {}
        for args in (["init-db"], ["start-backtest", "--start", "2024-01-02T14:30:00Z"],
                     ["seed-admin", "--name", "smoke-mgmt"], ["seed-runtime"],
                     ["create-pod", "--name", "desk-1", "--allocation", "1000000"]):
            r = run_cli(env, *args)
            key = re.search(r"\bfk_\S+", r.stdout)
            if key:
                keys[args[0]] = key.group(0)
            if not step(f"backtest db: fund-env {args[0]}", r.returncode == 0,
                        "" if r.returncode == 0 else (r.stdout + r.stderr).strip()[-300:]):
                return False
        server_log = (tmpdir / "serve.log").open("w")
        server = subprocess.Popen(
            ["uv", "run", "fund-env", "serve", "--port", str(port)],
            cwd=REPO, env=env, stdout=server_log, stderr=subprocess.STDOUT,
        )
        try:
            if not step("backtest db: fund-env serve answers /health", wait_for_health(base)):
                print((tmpdir / "serve.log").read_text()[-2000:])
                return False
            run_env = {**env, "FUND_RUNTIME__SERVER_URL": base,
                       "FUND_RUNTIME__REGISTRAR_KEY": keys.get("seed-admin", ""),
                       "FUND_RUNTIME__CLOCK_KEY": keys.get("seed-runtime", "")}
            r = subprocess.run(
                ["uv", "run", "fund-runtime", "backtest", "--specs", "specs/desk-month",
                 "--input", "specs/desk-month/input.json", "--steps", "5"],
                cwd=REPO, env=run_env, capture_output=True, text=True, timeout=300,
            )
            try:
                out = json.loads(r.stdout)
                wakes = [w for st in out["run"]["steps"] for w in st["wakes"]]
                # An order the PM placed and physics accepted (its tool result is no error).
                filled = [m for w in wakes if w["spec_id"] == "b-pm" for m in w["transcript"]
                          if m["role"] == "tool" and m["tool_call_id"].startswith("order:")
                          and not m["is_error"]]
                fine = (r.returncode == 0 and out["ended"] == "completed"
                        and out["registered"] == ["a-analyst", "b-pm"] and len(wakes) == 10
                        and all(w["ended"] == "done" and w["tool_failures"] == 0 for w in wakes)
                        and filled
                        and not any(k in r.stdout + r.stderr for k in keys.values()))
                detail = (f"{out['ended']}, {len(out['run']['steps'])} steps, {len(wakes)} wakes,"
                          f" {len(filled)} orders accepted")
            except (ValueError, KeyError, TypeError):
                fine, detail = False, (r.stdout + r.stderr).strip()[-300:]
            ok = step("fund-runtime backtest: specs/desk-month lives 5 days", fine, detail)
        finally:
            clean = stop(server)
            server_log.close()
        return ok & step("backtest server stopped cleanly on SIGINT", clean)


if __name__ == "__main__":
    sys.exit(main())
