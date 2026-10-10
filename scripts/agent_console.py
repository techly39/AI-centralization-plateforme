"""Be one AI agent, by hand.

This is a **real MCP client**. It launches ``fund-env-mcp`` as a subprocess over
stdio, performs the MCP handshake, discovers the tool list, and calls tools —
exactly what OpenClaw or the Claude Agent SDK does when it hosts an agent. The
only thing missing is the language model: *you* choose which tool to call and
what to put in it.

    you type  ──►  MCP client (this file)
                   └─► MCP server subprocess   (mcp_server/, holds your API key)
                       └─► HTTP  POST /messages
                           └─► FastAPI router   (authenticates, checks permissions)
                               └─► bus service  (addressing, visibility, ledger)
                                   └─► SQLite

Nothing here talks to the database, imports ``app``, or knows a fund rule. Every
permission you hit, every 403 you earn, and every row that gets written comes
from the real system. Run one console per agent, each with its own API key —
that is the same one-process-per-identity rule the MCP server documents.

Because the fund has no push channel (TRD §12: no websockets), incoming messages
appear only when this console *polls*. That is on by default and the poll is
printed, so the mechanism stays visible rather than feeling like magic.

Usage:
    uv run python scripts/agent_console.py --as sara
    uv run python scripts/agent_console.py --api-key fk_... --as marcus

Type /help once inside.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

try:  # makes the prompt redraw correctly when a message lands mid-typing
    import readline
except ImportError:  # pragma: no cover - Windows
    readline = None  # type: ignore[assignment]


# --- Presentation -----------------------------------------------------------

_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def dim(t: str) -> str:
    return _c("2", t)


def bold(t: str) -> str:
    return _c("1", t)


def red(t: str) -> str:
    return _c("31", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def blue(t: str) -> str:
    return _c("36", t)


PROMPT = "» "


def emit(text: str) -> None:
    """Print without destroying a half-typed command line.

    The poller prints from a different task than the one blocked on ``input()``.
    Clearing the line and redrawing the readline buffer afterwards is what keeps
    that from looking broken.
    """
    buffered = readline.get_line_buffer() if readline is not None else ""
    if _TTY and buffered:
        sys.stdout.write("\r\033[K")
        sys.stdout.write(text + "\n")
        sys.stdout.write(PROMPT + buffered)
    else:
        sys.stdout.write(text + "\n")
    sys.stdout.flush()


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return str(iso)


# --- MCP plumbing -----------------------------------------------------------

@dataclass
class ToolResult:
    ok: bool
    payload: Any = None
    error: str = ""


class Session:
    """One agent's live MCP session, plus the bookkeeping a real agent loop keeps."""

    def __init__(self, client: Client, *, trace: bool) -> None:
        self.client = client
        self.trace = trace
        self.tools: dict[str, Any] = {}
        # Identity, read from the app itself at startup (see `identify`). The
        # key decides it — nothing here is ever guessed from the command line.
        self.me_id: int | None = None
        self.me_name: str = "?"
        self.me_role: str = "?"
        self.me_pod: int | None = None
        # Polling state. `cursor` is the highest message id we have seen; it is
        # the only reliable way to page (ids are monotonic, timestamps are not).
        self.cursor: int = 0
        self.poll_seconds: float = 3.0
        self.polling = True
        self.own_sends: set[int] = set()
        self.directory: dict[int, dict] = {}
        self.default_to: str | None = None
        self.thread_id: str | None = None
        self.next_payload: dict | None = None

    async def call(self, tool: str, arguments: dict | None = None, *, quiet: bool = False) -> ToolResult:
        """Invoke one MCP tool, the way a model's tool-call would."""
        arguments = {k: v for k, v in (arguments or {}).items() if v is not None}
        if self.trace and not quiet:
            emit(dim(f"  → mcp call {tool}({json.dumps(arguments, default=str)})"))
        try:
            result = await self.client.call_tool(tool, arguments)
        except Exception as exc:  # transport died, tool unknown, etc.
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")

        text = "\n".join(
            b.text for b in result.content if getattr(b, "type", "") == "text"
        )
        if result.is_error:
            return ToolResult(False, error=text or "tool reported an error")

        blocks = []
        for block in result.content:
            if getattr(block, "type", "") != "text":
                continue
            try:
                blocks.append(json.loads(block.text))
            except json.JSONDecodeError:
                blocks.append(block.text)
        payload = blocks[0] if len(blocks) == 1 else blocks
        return ToolResult(True, payload=payload)

    # --- directory ----------------------------------------------------------

    async def refresh_directory(self) -> ToolResult:
        result = await self.call("list_agents", quiet=True)
        if result.ok:
            rows = result.payload if isinstance(result.payload, list) else [result.payload]
            self.directory = {r["id"]: r for r in rows if isinstance(r, dict)}
        return result

    def label(self, agent_id: int) -> str:
        row = self.directory.get(agent_id)
        if row is None:
            return f"agent:{agent_id}"
        pod = f", pod {row['pod_id']}" if row.get("pod_id") is not None else ""
        return f"{row['name']} ({row['role']}{pod})"

    def audience(self, to_ref: str) -> str:
        if to_ref == "broadcast":
            return "the whole firm"
        if to_ref.startswith("agent:"):
            target = int(to_ref.split(":", 1)[1])
            return "you" if target == self.me_id else self.label(target)
        if to_ref.startswith("pod:"):
            pod = to_ref.split(":", 1)[1]
            mine = " (yours)" if str(self.me_pod) == pod else ""
            return f"pod {pod}{mine}"
        return to_ref

    async def identify(self) -> ToolResult:
        """Ask the app who this key belongs to. One call, and it is the truth."""
        result = await self.call("whoami", quiet=True)
        if result.ok and isinstance(result.payload, dict):
            row = result.payload
            self.me_id, self.me_name = row["id"], row["name"]
            self.me_role, self.me_pod = row["role"], row["pod_id"]
        return result

    # --- messages -----------------------------------------------------------

    def render_message(self, msg: dict, *, incoming: bool) -> str:
        who = self.label(msg["from_agent"])
        if msg["from_agent"] == self.me_id:
            who = "you"
        arrow = blue("◀") if incoming else green("▶")
        head = f"{arrow} {dim(fmt_time(msg['ts']))}  {bold(who)} → {self.audience(msg['to'])}"
        if msg.get("thread_id"):
            head += dim(f"   [thread {msg['thread_id']}]")
        head += dim(f"   #{msg['id']}")
        lines = [head, f"   {msg['body']}"]
        if msg.get("structured_payload"):
            lines.append(dim(f"   payload {json.dumps(msg['structured_payload'])}"))
        return "\n".join(lines)

    async def seek_to_end(self) -> None:
        """Move the cursor past everything already said, without printing it.

        One call: ``latest=true`` returns the end of the ledger directly, so an
        agent joining a fund that has been running for a month pays the same
        startup cost as one joining an empty one.
        """
        result = await self.call(
            "get_messages", {"latest": True, "limit": 1}, quiet=True
        )
        if not result.ok:
            emit(red(f"  ✗ could not read history: {result.error}"))
            return
        rows = result.payload if isinstance(result.payload, list) else [result.payload]
        rows = [r for r in rows if isinstance(r, dict)]
        if rows:
            self.cursor = max(r["id"] for r in rows)
            emit(dim(f"  caught up to message #{self.cursor} — /history to look back"))

    async def poll(self, *, announce: bool = False) -> None:
        """One turn of the read loop: `get_messages(after_id=<cursor>)`."""
        result = await self.call(
            "get_messages", {"after_id": self.cursor or None, "limit": 200}, quiet=not announce
        )
        if not result.ok:
            emit(red(f"  ✗ poll failed: {result.error}"))
            return

        rows = result.payload if isinstance(result.payload, list) else [result.payload]
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows:
            if announce:
                emit(dim(f"  (nothing new after #{self.cursor})"))
            return

        unknown = {r["from_agent"] for r in rows} - set(self.directory)
        if unknown:
            await self.refresh_directory()

        for row in rows:
            self.cursor = max(self.cursor, row["id"])
            if row["id"] in self.own_sends:
                continue  # already shown at send time; don't echo it twice
            emit(self.render_message(row, incoming=True))


# --- Commands ---------------------------------------------------------------

HELP = f"""
{bold('Talking')}
  <anything>                    send it to your current default recipient
  /to agent:3 | pod:1 | broadcast   set the default recipient
  /send <ref> <text>            one-off send, without changing the default
  /thread <id> | /thread -      label the conversation (or stop labelling)
  /payload {{"k": 1}} | /payload -   attach structured JSON to the NEXT message

{bold('Listening')}   (nothing is pushed — the fund has no websockets)
  /poll                         poll once, right now, and show the call
  /auto <seconds> | /auto off   background polling (default: every 3s)
  /history [n]                  re-read your last n messages (default 20)
  /thread-read <id>             read one whole thread

{bold('The rest of the fund')}
  /who                          the directory — who exists, their role and pod
  /tools                        every MCP tool your key can attempt
  /schema <tool>                the exact JSON schema a model would see
  /call <tool> [json]           call ANY tool, e.g. /call get_clock
  /price <ticker>               /portfolio [pod]      /orders
  /order buy 10 NVDA <why...>   market order (PM only)
  /cost <in> <out> <usd> [label]
  /task start <subject> | /task end <id> [json]
  /events [type]                /metrics [pod]        /leaderboard

{bold('Console')}
  /me       who the app says you are      /trace   show/hide the raw MCP calls
  /quit
"""


async def handle(session: Session, line: str) -> bool:
    """Run one console command. Returns False to quit."""
    line = line.strip()
    if not line:
        return True

    if not line.startswith("/"):
        await do_send(session, session.default_to, line)
        return True

    parts = line.split(maxsplit=1)
    cmd, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else "")

    match cmd:
        case "/quit" | "/exit" | "/q":
            return False

        case "/help" | "/h" | "/?":
            emit(HELP)

        case "/me":
            # Re-asked rather than printed from memory: management can move an
            # agent between pods mid-run, and the app is the one that knows.
            result = await session.identify()
            if not result.ok:
                emit(red(f"  ✗ {result.error}"))
            else:
                pod = f"pod {session.me_pod}" if session.me_pod is not None else "no pod"
                emit(
                    f"  agent {session.me_id}  {bold(session.me_name)}  "
                    f"role {session.me_role}  {pod}\n"
                    f"  address others use to reach you: {bold(f'agent:{session.me_id}')}"
                )

        case "/who":
            result = await session.refresh_directory()
            if not result.ok:
                emit(red(f"  ✗ {result.error}"))
            else:
                emit(bold("  id  name                 role         pod   status"))
                for row in sorted(session.directory.values(), key=lambda r: r["id"]):
                    mine = " ← you" if row["id"] == session.me_id else ""
                    emit(
                        f"  {row['id']:<3} {row['name']:<20} {row['role']:<12} "
                        f"{str(row['pod_id'] or '-'):<5} {row['status']}{mine}"
                    )

        case "/tools":
            emit(bold(f"  {len(session.tools)} tools offered to you:"))
            for name, tool in sorted(session.tools.items()):
                first = (tool.description or "").strip().split("\n")[0]
                emit(f"  {name:<20} {dim(first)}")
            emit(dim("  (the same list goes to every agent; the API returns 403 to whoever is out of bounds)"))

        case "/schema":
            tool = session.tools.get(rest.strip())
            if tool is None:
                emit(red(f"  ✗ no tool named {rest.strip()!r} — try /tools"))
            else:
                emit(bold(f"  {tool.name}"))
                emit(dim((tool.description or "").strip()))
                emit(json.dumps(tool.input_schema, indent=2))

        case "/to":
            session.default_to = rest.strip() or None
            emit(dim(f"  default recipient: {session.default_to or '(none)'}"))

        case "/thread":
            session.thread_id = None if rest.strip() in ("", "-") else rest.strip()
            emit(dim(f"  thread: {session.thread_id or '(none)'}"))

        case "/payload":
            if rest.strip() in ("", "-"):
                session.next_payload = None
                emit(dim("  payload cleared"))
            else:
                try:
                    session.next_payload = json.loads(rest)
                    emit(dim("  payload attached to your next message"))
                except json.JSONDecodeError as exc:
                    emit(red(f"  ✗ not valid JSON: {exc}"))

        case "/send":
            bits = rest.split(maxsplit=1)
            if len(bits) < 2:
                emit(red("  usage: /send agent:3 your message"))
            else:
                await do_send(session, bits[0], bits[1])

        case "/poll":
            await session.poll(announce=True)

        case "/auto":
            arg = rest.strip().lower()
            if arg in ("off", "0", "no"):
                session.polling = False
                emit(dim("  background polling off — use /poll by hand"))
            else:
                if arg:
                    try:
                        session.poll_seconds = max(0.5, float(arg))
                    except ValueError:
                        emit(red("  usage: /auto 3   |   /auto off"))
                        return True
                session.polling = True
                emit(dim(f"  background polling on, every {session.poll_seconds:g}s"))

        case "/history":
            try:
                n = int(rest) if rest.strip() else 20
            except ValueError:
                n = 20
            await show_history(session, n)

        case "/thread-read":
            result = await session.call("get_messages", {"thread": rest.strip(), "limit": 200})
            await show_messages(session, result)

        case "/call":
            bits = rest.split(maxsplit=1)
            if not bits:
                emit(red('  usage: /call get_price {"ticker": "NVDA"}'))
                return True
            args: dict = {}
            if len(bits) > 1 and bits[1].strip():
                try:
                    args = json.loads(bits[1])
                except json.JSONDecodeError as exc:
                    emit(red(f"  ✗ arguments must be JSON: {exc}"))
                    return True
            show(await session.call(bits[0], args))

        case "/price":
            show(await session.call("get_price", {"ticker": rest.strip().upper()}))

        case "/portfolio":
            pod = int(rest) if rest.strip().isdigit() else session.me_pod
            if pod is None:
                emit(red("  ✗ you belong to no pod — /portfolio <pod_id>"))
            else:
                show(await session.call("get_portfolio", {"pod_id": pod}))

        case "/orders":
            show(await session.call("list_orders", {}))

        case "/order":
            await do_order(session, rest)

        case "/cost":
            bits = rest.split(maxsplit=3)
            if len(bits) < 3:
                emit(red("  usage: /cost <tokens_in> <tokens_out> <usd> [label]"))
            else:
                show(await session.call("report_cost", {
                    "tokens_in": int(bits[0]),
                    "tokens_out": int(bits[1]),
                    "usd_cost": float(bits[2]),
                    "task_label": bits[3] if len(bits) > 3 else None,
                }))

        case "/task":
            await do_task(session, rest)

        case "/events":
            show(await session.call("list_events", {"type": rest.strip() or None, "limit": 30}))

        case "/metrics":
            pod = int(rest) if rest.strip().isdigit() else session.me_pod
            if pod is None:
                emit(red("  ✗ /metrics <pod_id>"))
            else:
                show(await session.call("get_pod_metrics", {"pod_id": pod}))

        case "/leaderboard":
            show(await session.call("get_leaderboard", {}))

        case "/trace":
            session.trace = not session.trace
            emit(dim(f"  MCP call tracing {'on' if session.trace else 'off'}"))

        case _:
            emit(red(f"  ✗ unknown command {cmd} — /help"))

    return True


def show(result: ToolResult) -> None:
    if result.ok:
        emit(green("  ✓ ") + json.dumps(result.payload, indent=2, default=str))
    else:
        emit(red(f"  ✗ {result.error}"))


async def show_messages(session: Session, result: ToolResult) -> None:
    if not result.ok:
        emit(red(f"  ✗ {result.error}"))
        return
    rows = result.payload if isinstance(result.payload, list) else [result.payload]
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        emit(dim("  (no messages)"))
        return
    await session.refresh_directory()
    for row in rows:
        emit(session.render_message(row, incoming=row["from_agent"] != session.me_id))
        session.cursor = max(session.cursor, row["id"])
        session.own_sends.add(row["id"])


async def show_history(session: Session, n: int) -> None:
    """The last `n` messages you can see — one call, from the end backwards."""
    result = await session.call(
        "get_messages", {"latest": True, "limit": min(n, 500)}, quiet=True
    )
    if not result.ok:
        emit(red(f"  ✗ {result.error}"))
        return
    rows = result.payload if isinstance(result.payload, list) else [result.payload]
    collected = [r for r in rows if isinstance(r, dict)]

    if not collected:
        emit(dim("  (no messages yet)"))
        return
    await session.refresh_directory()
    emit(dim(f"  your last {len(collected)} message(s):"))
    for row in collected:
        emit(session.render_message(row, incoming=row["from_agent"] != session.me_id))
    session.cursor = max(session.cursor, max(r["id"] for r in collected))
    session.own_sends.update(r["id"] for r in collected)


async def do_send(session: Session, to: str | None, body: str) -> None:
    if not to:
        emit(red("  ✗ no recipient — /to agent:3   (or use /send agent:3 <text>)"))
        return
    result = await session.call("send_message", {
        "to": to,
        "body": body,
        "thread_id": session.thread_id,
        "structured_payload": session.next_payload,
    })
    session.next_payload = None
    if not result.ok:
        emit(red(f"  ✗ refused: {result.error}"))
        return

    msg = result.payload
    session.cursor = max(session.cursor, msg["id"])
    session.own_sends.add(msg["id"])
    emit(session.render_message(msg, incoming=False))
    if msg["to"] != to:
        emit(yellow(
            f"  note: you addressed {to!r} but the bus recorded {msg['to']!r} — "
            "a PM's broadcast is scoped to their own pod (TRD §6)."
        ))


async def do_order(session: Session, rest: str) -> None:
    bits = rest.split(maxsplit=3)
    if len(bits) < 4:
        emit(red("  usage: /order buy 10 NVDA why you are doing this"))
        return
    side, qty, ticker, justification = bits[0].lower(), bits[1], bits[2].upper(), bits[3]
    try:
        quantity = float(qty)
    except ValueError:
        emit(red(f"  ✗ quantity must be a number, got {qty!r}"))
        return
    show(await session.call("place_order", {
        "ticker": ticker,
        "side": side,
        "qty": quantity,
        "price_type": "market",
        "justification": justification,
    }))
    emit(dim("  (if it was rejected, the app has messaged you about it — /poll)"))


async def do_task(session: Session, rest: str) -> None:
    bits = rest.split(maxsplit=2)
    if not bits:
        emit(red("  usage: /task start <subject>   |   /task end <id> [json]"))
        return
    if bits[0] == "start" and len(bits) > 1:
        show(await session.call("start_task", {"subject": " ".join(bits[1:])}))
    elif bits[0] == "end" and len(bits) > 1:
        outcome = {"summary": "done"}
        if len(bits) > 2:
            try:
                outcome = json.loads(bits[2])
            except json.JSONDecodeError:
                outcome = {"summary": bits[2]}
        show(await session.call("end_task", {"task_id": int(bits[1]), "outcome": outcome}))
    else:
        emit(red("  usage: /task start <subject>   |   /task end <id> [json]"))


# --- Startup ----------------------------------------------------------------

def warn_if_playing_someone_else(session: Session, claimed: str | None) -> None:
    """``--as`` is a label for your own terminal, not a way to pick an identity.

    The app decides who you are from the key. If the two disagree, say so once
    rather than letting the header lie for the rest of the session.
    """
    if claimed and claimed.lower() != session.me_name.lower():
        emit(
            yellow(
                f"  ! you passed --as {claimed}, but that key is "
                f"{session.me_name}. Going with the app."
            )
        )


async def poller(session: Session) -> None:
    while True:
        await anyio.sleep(session.poll_seconds)
        if session.polling:
            await session.poll()


async def repl(session: Session, cancel: anyio.CancelScope) -> None:
    while True:
        try:
            line = await anyio.to_thread.run_sync(input, PROMPT, abandon_on_cancel=True)
        except (EOFError, KeyboardInterrupt):
            break
        try:
            if not await handle(session, line):
                break
        except Exception as exc:  # a bad command must not kill the session
            emit(red(f"  ✗ {type(exc).__name__}: {exc}"))
    cancel.cancel()


async def run(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("FUND_MCP__API_KEY") or getpass(
        "API key for the agent you are playing (input hidden): "
    )
    if not api_key.strip():
        print("No API key, no identity. Get one from `uv run fund-env seed-admin` "
              "or from management's register_agent.", file=sys.stderr)
        return 1

    command, *command_args = shlex.split(args.mcp_command)
    params = StdioServerParameters(
        command=command,
        args=command_args,
        cwd=args.cwd,
        env={
            **os.environ,
            # The key is the identity. It goes to the subprocess only.
            "FUND_MCP__API_KEY": api_key.strip(),
            "FUND_MCP__API_BASE_URL": args.api_url,
        },
    )

    # The subprocess logs every HTTP call it makes to stderr. That is genuinely
    # useful — it is the proof that each tool call became a real request — but
    # it would drown the conversation, so it goes to a file you can tail.
    log_path = Path(args.mcp_log or Path(tempfile.gettempdir()) /
                    f"fund-mcp-{args.as_name or 'agent'}-{os.getpid()}.log")

    print(dim(f"launching MCP server: {args.mcp_command}  → {args.api_url}"))
    print(dim(f"its HTTP log: tail -f {log_path}"))
    with log_path.open("w", encoding="utf-8") as errlog:
        return await _session(args, params, errlog)


async def _session(args: argparse.Namespace, params: StdioServerParameters, errlog) -> int:
    try:
        async with Client(stdio_client(params, errlog=errlog)) as client:
            session = Session(client, trace=args.trace)
            listed = await client.list_tools()
            session.tools = {t.name: t for t in listed.tools}

            health = await session.call("get_health", quiet=True)
            if not health.ok:
                print(red(f"The fund API is not answering: {health.error}"))
                print("Start it first:  uv run fund-env serve")
                return 1

            print(green(f"connected — {len(session.tools)} tools, "
                        f"fund clock in {health.payload.get('clock_mode')} mode"))

            # /health needs no key, so this is the first call that actually
            # proves the key is real. Better to stop here than to let every
            # later command fail one at a time.
            identity = await session.identify()
            if not identity.ok:
                print(red(f"\nThe fund would not accept that key: {identity.error}"))
                print("Keys are shown once at registration. Check agents.local.json, "
                      "or have management run register_agent again.")
                return 1

            warn_if_playing_someone_else(session, args.as_name)
            await session.refresh_directory()

            session.poll_seconds = args.poll_seconds
            session.polling = not args.no_poll
            session.default_to = args.to
            session.thread_id = args.thread

            pod = f"pod {session.me_pod}" if session.me_pod is not None else "no pod"
            print(bold(f"\nYou are {session.me_name} — {session.me_role}, {pod}"
                       f"   (agent:{session.me_id})"))
            print(dim(f"default recipient: {session.default_to or 'none — set one with /to'}"
                      f"   polling: {'every %gs' % session.poll_seconds if session.polling else 'off'}"))
            print(dim("/help for commands\n"))

            await session.seek_to_end()

            async with anyio.create_task_group() as tg:
                tg.start_soon(poller, session)
                tg.start_soon(repl, session, tg.cancel_scope)
    except Exception as exc:
        print(red(f"\nMCP session ended: {type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1

    print(dim("\nsession closed — the MCP server subprocess has been shut down"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive one fund agent by hand, over the real MCP server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run one of these per agent, in its own terminal, with its own key.",
    )
    parser.add_argument("--api-key", default=None,
                        help="the agent's key; else $FUND_MCP__API_KEY, else prompted")
    parser.add_argument("--as", dest="as_name", default=None,
                        help="label for this terminal's log file; the key decides who you are")
    parser.add_argument("--to", default=None,
                        help="default recipient, e.g. agent:3 | pod:1 | broadcast")
    parser.add_argument("--thread", default=None, help="start with this thread label")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000",
                        help="where the fund API is listening")
    parser.add_argument("--mcp-command", default="uv run fund-env-mcp",
                        help="how to launch the MCP server subprocess")
    parser.add_argument("--cwd", default=None, help="working directory for that subprocess")
    parser.add_argument("--mcp-log", default=None,
                        help="where the MCP subprocess's stderr/HTTP log goes")
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--no-poll", action="store_true",
                        help="never poll on your own; use /poll by hand")
    parser.add_argument("--trace", action="store_true", default=True,
                        help="show every MCP tool call (default on)")
    parser.add_argument("--no-trace", dest="trace", action="store_false")
    args = parser.parse_args(argv)

    if args.cwd is None:
        args.cwd = str(Path(__file__).resolve().parent.parent)

    try:
        return anyio.run(run, args)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
