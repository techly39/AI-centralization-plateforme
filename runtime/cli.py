"""``uv run fund-runtime`` — the Runtime's entry point.

    fund-runtime status [--specs DIR]

prints the law as the Runtime reads it (HALT, cap, any cap problem) and, for
every spec in ``DIR``, what the wake gate would decide right now. It wakes
nothing. Exit 1 if a spec file is refused.

    fund-runtime backtest --specs DIR --steps N [--days-per-step D] [--input FILE]
                          [--max-tool-calls K] [--server URL] [--cassette PATH]

lives ``N`` steps of a backtest run with the minds ``DIR``'s specs describe
(R-3b-2c-1). The run's database is the one the App at ``URL`` serves; the
operator opened it (``fund-env start-backtest``), seeded the Runtime's clock
identity and made the pods. In order:

1. the specs, the workflow input (a JSON object, default ``{}``) and the two keys
   are read. Keys come **from the environment only**, never argv (``ps`` shows
   argv to every user): ``FUND_RUNTIME__REGISTRAR_KEY`` registers the minds'
   agents (physics decides whether it may), ``FUND_RUNTIME__CLOCK_KEY`` is the
   Runtime's clock identity;
2. the clock key is checked **before anything is registered**: it must be the
   ``runtime`` role on a ``backtest`` run, so a live database never gains a
   run's agents;
3. the clock key declares what drives the run's minds (``POST /run/minds``, the
   specs' kinds: ADR-032 (p)). Physics takes it once, and only before any firm
   agent acts, so it comes before registration too;
4. :func:`runtime.provision.provision` makes one App agent per spec, then
   :func:`runtime.lockstep.run_backtest` conducts the run.

One JSON object goes to stdout: ``{ended, reason, registered, run}``.
``registered`` lists the spec ids whose agent exists or may exist (after a
refusal part-way, the run's database is spoiled: ADR-027). ``run`` is the
:class:`~runtime.lockstep.RunRecord`, or ``null`` if the run never began. No
key in the form physics mints is printed (:func:`redact`). Exit 0 only if the run ``completed``; 1 if it was refused
or ended early; 2 if the command itself is wrong (no specs, an unreadable
input, a missing key, a server that is not on this machine, a ``--cassette`` path that
cannot be written). With ``--cassette PATH`` the same outcome is also written, redacted, to a
new ``*.cassette.json`` file (:mod:`runtime.cassette`) whatever the run's end; a write that
fails exits 1 after the outcome was printed.

    fund-runtime replay --cassette PATH --specs DIR [--days-per-step D] [--input FILE]
                        [--max-tool-calls K] [--server URL]

replays the run ``PATH`` recorded (ADR-040) into the fresh backtest database the App at ``URL``
serves, set up exactly as the recorded run's was: the same specs' minds, as ``cassette`` minds,
answering from the tape. No ``--steps``: the recording holds the step count. ``--input`` and
``--days-per-step`` must be the recorded run's (cassette v1 does not store them; a mismatch ends
the run ``diverged``). Same keys, same order, same output as ``backtest``. Exit 0 only if the run
``completed``; 1 if it was refused or ended early (``halted``, ``diverged``, ``error``); 2 if the command is wrong (the
cassette is not a completed run, the specs are not its minds, a spec carries a model, and every
``backtest`` usage error). **Exit 0 is not proof of an identical ledger**: compare the new
database with the recorded one, ``fund-env compare-ledgers RECORDED REPLAYED``.

The server must be on this machine (``127.0.0.1`` or ``::1``), and no proxy from
the environment is used (``FundClient``): agent keys never leave it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from mcp_server.client import FundClient
from runtime import cassette
from runtime.cassette import CassetteError, redact  # noqa: F401 - ``cli.redact`` is public
from runtime.gate import decide_wake_under
from runtime.governance import read_governance
from runtime.lockstep import (
    MAX_DAYS_PER_STEP,
    MAX_STEPS,
    Mind,
    check_clock,
    declare_minds,
    record_json,
    run_backtest,
)
from runtime.native import DEFAULT_MAX_TOOL_CALLS
from runtime.provision import ProvisionError, provision
from runtime.registry import ProviderRefused, check_spec
from runtime.replay import Recording, RecordingError, as_cassette
from runtime.spec import AgentSpec, SpecError, load_specs

REGISTRAR_KEY_ENV = "FUND_RUNTIME__REGISTRAR_KEY"
CLOCK_KEY_ENV = "FUND_RUNTIME__CLOCK_KEY"
SERVER_ENV = "FUND_RUNTIME__SERVER_URL"
DEFAULT_SERVER = "http://127.0.0.1:8000"
#: Addresses, not names: ``localhost`` is whatever ``/etc/hosts`` says (audit c27 NOTE 1).
_LOOPBACK = frozenset({"127.0.0.1", "::1"})
#: A wake's tool-call budget, at most (audit c27 WARN 2); the default is 64.
MAX_TOOL_CALLS = 1024


class _Usage(Exception):
    """The command is wrong: exit 2, nothing contacted."""


def main(argv: list[str] | None = None, *,
         transport: httpx.AsyncBaseTransport | None = None) -> int:
    """``transport`` lets tests serve the App in-process; the CLI never sets it."""
    parser = argparse.ArgumentParser(prog="fund-runtime", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="show the law and what the gate would wake (wakes nothing)")
    status.add_argument("--specs", type=Path, help="directory of AgentSpec YAML files")
    bt = sub.add_parser("backtest", help="provision the specs' minds and live a backtest run")
    bt.add_argument("--specs", type=Path, required=True, help="directory of AgentSpec YAML files")
    bt.add_argument("--steps", type=int, required=True, help="how many steps the run lives")
    bt.add_argument("--days-per-step", type=int, default=1)
    bt.add_argument("--input", type=Path, help="workflow input: a JSON object every wake sees")
    bt.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS,
                    help="tool-call budget per wake")
    bt.add_argument("--server", default=os.environ.get(SERVER_ENV) or DEFAULT_SERVER,
                    help=f"the App's URL, on this machine (default ${SERVER_ENV} or {DEFAULT_SERVER})")
    bt.add_argument("--cassette", type=Path, metavar="PATH",
                    help=f"write the run's record to a new PATH{cassette.SUFFIX} (never overwritten)")
    rp = sub.add_parser("replay", help="replay a recorded run's minds from its cassette (no model, $0)")
    rp.add_argument("--cassette", type=Path, required=True, metavar="PATH",
                    help=f"the recorded run's {cassette.SUFFIX} (a completed run of scripted minds)")
    rp.add_argument("--specs", type=Path, required=True,
                    help="the same specs the run was recorded with (their ids must match)")
    rp.add_argument("--days-per-step", type=int, default=1)
    rp.add_argument("--input", type=Path, help="workflow input: the one the run was recorded with")
    rp.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS,
                    help="tool-call budget per wake")
    rp.add_argument("--server", default=os.environ.get(SERVER_ENV) or DEFAULT_SERVER,
                    help=f"the App's URL, on this machine (default ${SERVER_ENV} or {DEFAULT_SERVER})")
    args = parser.parse_args(argv)
    if args.command == "backtest":
        return _backtest(args, transport)
    if args.command == "replay":
        return _replay(args, transport)

    try:
        specs = load_specs(args.specs) if args.specs else []
    except SpecError as exc:
        print(f"fund-runtime: {exc}", file=sys.stderr)
        return 1
    law = read_governance()  # one read for one report
    wakes = []
    for spec in specs:
        d = decide_wake_under(spec.provider, spec.adapter, law)
        wakes.append({"id": spec.id, "provider": spec.provider, "adapter": spec.adapter,
                      "allowed": d.allowed, "reason": d.reason})
    print(json.dumps({
        "halted": law.halted,
        "monthly_llm_usd_cap": law.monthly_llm_usd_cap,
        "cap_problem": law.cap_problem,
        "wakes": wakes,
        "woke": 0,
    }, indent=2))
    return 0


def _shared(args: argparse.Namespace, steps: int | None = None) -> tuple[dict[str, Any], str, str, str]:
    """What ``backtest`` and ``replay`` check alike, before anything is contacted:
    ``(workflow_input, registrar_key, clock_key, server)``."""
    # --steps 0 would make the run's agents and live nothing (audit c27 NOTE 3).
    for flag, value, low, top in (("--steps", steps, 1, MAX_STEPS),
                                  ("--days-per-step", args.days_per_step, 1, MAX_DAYS_PER_STEP),
                                  ("--max-tool-calls", args.max_tool_calls, 0, MAX_TOOL_CALLS)):
        if value is not None and not low <= value <= top:
            raise _Usage(f"{flag} is in [{low}, {top}]")
    workflow_input = _read_input(args.input)
    registrar_key, clock_key = (_key(REGISTRAR_KEY_ENV), _key(CLOCK_KEY_ENV))
    if registrar_key == clock_key:
        raise _Usage("the registrar key and the clock key are one key: the clock "
                     "identity registers nobody")
    return workflow_input, registrar_key, clock_key, _loopback(args.server)


def _replay(args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None) -> int:
    """``fund-runtime replay`` (ADR-040): the recorded run's minds, as cassette minds, in a fresh
    database. Exit 0 only for ``completed``: **that is not proof of an identical ledger**."""
    try:
        specs = load_specs(args.specs)
        if not specs:
            raise _Usage(f"no specs in {args.specs}: a run needs minds")
        try:
            rec = Recording.load(args.cassette)
        except (CassetteError, RecordingError) as exc:
            raise _Usage(f"{args.cassette}: {exc}") from exc
        if len({s.id for s in specs}) != len(specs) or {s.id for s in specs} != rec.spec_ids:
            raise _Usage("the specs are not the recording's minds: their ids differ")
        try:
            specs = [as_cassette(s) for s in specs]
            for spec in specs:
                check_spec(spec)
        except (ProviderRefused, ValueError) as exc:  # a cassette v1 cannot replay a model-bearing run
            raise _Usage(f"the specs cannot replay as cassette minds: {exc}") from exc
        workflow_input, registrar_key, clock_key, server = _shared(args)
    except (SpecError, _Usage) as exc:
        print(f"fund-runtime: {exc}", file=sys.stderr)
        return 2
    out = asyncio.run(_conduct(specs, server, registrar_key, clock_key, transport,
                               steps=rec.steps, days_per_step=args.days_per_step,
                               workflow_input=workflow_input,
                               max_tool_calls=args.max_tool_calls, replay=rec))
    print(redact(json.dumps(out, indent=2, sort_keys=True)))
    return 0 if out["ended"] == "completed" else 1


def _backtest(args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None) -> int:
    try:
        specs = load_specs(args.specs)
        if not specs:
            raise _Usage(f"no specs in {args.specs}: a run needs minds")
        workflow_input, registrar_key, clock_key, server = _shared(args, args.steps)
        if args.cassette is not None:
            try:
                cassette.check_path(args.cassette)
            except CassetteError as exc:
                raise _Usage(str(exc)) from exc
    except (SpecError, _Usage) as exc:
        print(f"fund-runtime: {exc}", file=sys.stderr)
        return 2
    out = asyncio.run(_conduct(specs, server, registrar_key, clock_key, transport,
                               steps=args.steps, days_per_step=args.days_per_step,
                               workflow_input=workflow_input,
                               max_tool_calls=args.max_tool_calls))
    print(redact(json.dumps(out, indent=2, sort_keys=True)))
    code = 0 if out["ended"] == "completed" else 1
    if args.cassette is not None:  # every run that began is written, refused ones too (Art. 9)
        try:
            redactions = cassette.write(args.cassette, out)
        except CassetteError as exc:
            print(f"fund-runtime: {exc}", file=sys.stderr)
            return 1
        print(f"fund-runtime: cassette {args.cassette} ({redactions} redactions)",
              file=sys.stderr)
    return code


async def _conduct(specs: list[AgentSpec], server: str, registrar_key: str, clock_key: str,
                   transport: httpx.AsyncBaseTransport | None, **run: Any) -> dict[str, Any]:
    def connect(key: str) -> FundClient:
        return FundClient(base_url=server, api_key=key, transport=transport)

    def refused(reason: str, registered: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
        return {"ended": "refused", "reason": reason, "registered": list(registered), "run": None}

    registrar, clock = connect(registrar_key), connect(clock_key)
    minds: list[Mind] = []
    try:
        # Both before anything is registered: physics takes the declaration only
        # while no firm agent has acted (ADR-032 (p)).
        problem = await check_clock(clock) or await declare_minds(clock, specs)
        if problem is not None:
            return refused(problem)
        try:
            minds = await provision(specs, registrar, connect)
        except ProvisionError as exc:
            return refused(f"provision:{exc.reason}", exc.registered)
        record = await run_backtest(minds, clock, **run)
        return {"ended": record.ended, "reason": record.reason,
                "registered": [m.spec.id for m in minds], "run": record_json(record)}
    finally:
        for c in [registrar, clock, *(m.client for m in minds)]:
            await c.aclose()


def _key(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise _Usage(f"{name} is not set: keys come from the environment, never the command line")
    return value


def _read_input(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Usage(f"{path}: unreadable workflow input ({exc.__class__.__name__})") from exc
    if not isinstance(doc, dict):
        raise _Usage(f"{path}: the workflow input is a JSON object")
    return doc


def _loopback(url: str) -> str:
    try:
        parts = urlsplit(url)
        ok = (parts.scheme in {"http", "https"} and parts.hostname in _LOOPBACK
              and parts.username is None and (parts.port or 0) >= 0)  # .port raises if malformed
    except ValueError:
        ok = False
    if not ok:
        raise _Usage(f"{url}: the App must be on this machine (http://127.0.0.1:PORT); "
                     "agent keys never leave it")
    return url


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
