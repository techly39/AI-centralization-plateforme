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

0. the law is read once: under HALT the run ends ``halted``; a spec that could
   never wake under it (:func:`runtime.provision.vet`, no network) ends the run
   ``refused`` before physics is told anything (B-053). A HALT met at any later
   stage also ends it ``halted``, never ``refused`` (B-054);
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

    fund-runtime replay --cassette PATH [--server URL]

replays the run ``PATH`` recorded (ADR-040) into the fresh backtest database the App at ``URL``
serves, set up exactly as the recorded run's was: the specs' minds (as the cassette carries them,
as ``cassette`` minds) answering from the tape. The cassette (v2, ADR-045) holds everything the
replay needs: the step count, days per step, tool-call budget and workflow input of the recorded
run, and its specs; no other flag exists. Same keys, same order, same output as ``backtest``. Exit 0
only if the run ``completed``; 1 if it was refused or ended early (``halted``, ``diverged``,
``error``); 2 if the command is wrong (the cassette is unreadable, is version 1 or not a completed
run, a spec carries a model, and every ``backtest`` usage error). **Exit 0 is not proof of an
identical ledger**: compare the new database with the recorded one, ``fund-env compare-ledgers
RECORDED REPLAYED``.

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

from mcp_server.client import FundAPIError, FundClient
from runtime import cassette, packages, world
from runtime.cassette import CassetteError, redact  # noqa: F401 - ``cli.redact`` is public
from runtime.gate import METERED_PROVIDERS, decide_wake_under
from runtime.governance import Governance, read_governance
from runtime.lockstep import (
    MAX_DAYS_PER_STEP,
    MAX_STEPS,
    Mind,
    check_clock,
    declare_minds,
    record_json,
    run_backtest,
)
from runtime.metering import FakeProvisioner, sync_costs, usd_to_micros_floor
from runtime.native import DEFAULT_MAX_TOOL_CALLS
from runtime.openrouter import OpenRouterError, OpenRouterProvisioner
from runtime.onboarding import HIRE_PREFIX, HireTemplate, Onboarding, load_template, probe_spec, vet_template
from runtime.provision import ProvisionError, provision, vet
from runtime.registry import ProviderRefused, check_spec
from runtime.replay import Recording, RecordingError, as_cassette
from runtime.spec import AgentSpec, SpecError, load_specs, specs_from_cassette

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
    bt.add_argument("--package", default=None, metavar="NAME",
                    help="hand every wake its day's data package (known: "
                         f"{', '.join(sorted(packages.PACKAGES))}); needs a `universe` in --input")
    bt.add_argument("--charge-each-step", action="store_true",
                    help="post each metered mind's thinking cost to physics at every step's end "
                         "(the capital machine and the month's end then see it as the run lives)")
    bt.add_argument("--server", default=None,
                    help=f"the App's URL, on this machine (default ${SERVER_ENV} or {DEFAULT_SERVER})")
    bt.add_argument("--world", type=Path, metavar="FILE",
                    help="host the run in a fresh world built from this recipe (start, admin, pods) "
                         "instead of an App the operator built; needs --cassette and the world key "
                         f"in ${world.WORLD_KEY_ENV}; the cassette then proves the run (ADR-045)")
    bt.add_argument("--cassette", type=Path, metavar="PATH",
                    help=f"write the run's record to a new PATH{cassette.SUFFIX} (never overwritten)")
    bt.add_argument("--hire", type=Path, metavar="FILE",
                    help="hire into every vacancy the risk ladder opens, with this template (YAML: "
                         "provider, adapter, script, tools); the hiring law names the rest")
    rp = sub.add_parser("replay", help="replay a recorded run's minds from its cassette (no model, $0)")
    rp.add_argument("--cassette", type=Path, required=True, metavar="PATH",
                    help=f"the recorded run's {cassette.SUFFIX} (a completed run of scripted minds)")
    rp.add_argument("--verify", action="store_true",
                    help="rebuild the recorded world from the cassette's recipe, replay at $0 and "
                         "say IDENTICAL or DIVERGED at <step, wake> (needs the cassette to carry a "
                         f"world, and ${world.WORLD_KEY_ENV}); excludes --server")
    rp.add_argument("--server", default=None,
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
        # As ``vet`` asks: a metered spec is judged as if provisioning had given it its key.
        d = decide_wake_under(spec.provider, spec.adapter, law,
                              metered=spec.provider in METERED_PROVIDERS)
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
    workflow_input = _check_run_flags(args, steps)
    return (workflow_input, *_keys(args))


def _check_run_flags(args: argparse.Namespace, steps: int | None) -> dict[str, Any]:
    """The run flags' ranges and the workflow input (the part of :func:`_shared` that needs no key)."""
    # --steps 0 would make the run's agents and live nothing (audit c27 NOTE 3).
    for flag, value, low, top in (("--steps", steps, 1, MAX_STEPS),
                                  ("--days-per-step", args.days_per_step, 1, MAX_DAYS_PER_STEP),
                                  ("--max-tool-calls", args.max_tool_calls, 0, MAX_TOOL_CALLS)):
        if value is not None and not low <= value <= top:
            raise _Usage(f"{flag} is in [{low}, {top}]")
    return _read_input(args.input)


def _keys(args: argparse.Namespace) -> tuple[str, str, str]:
    """``(registrar_key, clock_key, server)``: from the environment, never the command line."""
    registrar_key, clock_key = (_key(REGISTRAR_KEY_ENV), _key(CLOCK_KEY_ENV))
    if registrar_key == clock_key:
        raise _Usage("the registrar key and the clock key are one key: the clock "
                     "identity registers nobody")
    return registrar_key, clock_key, _loopback(args.server or os.environ.get(SERVER_ENV) or DEFAULT_SERVER)


def _replay(args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None) -> int:
    """``fund-runtime replay`` (ADR-040, ADR-045): the recorded run's minds, as cassette minds, in a
    fresh database; the specs and the run's parameters come from the cassette alone. Exit 0 only
    for ``completed``: **that is not proof of an identical ledger** (``--verify`` is)."""
    if args.verify:
        if args.server is not None:
            print("fund-runtime: --verify and --server are exclusive: the verified replay is "
                  "hosted in a world of its own", file=sys.stderr)
            return 2
        from runtime import verify  # imports this module's conductor, so not at the top
        return verify.main(args.cassette)
    try:
        try:
            cas = cassette.read(args.cassette)
            rec = Recording.from_outcome(cas.outcome)
            specs = specs_from_cassette(cas.specs)
        except (CassetteError, RecordingError) as exc:
            raise _Usage(f"{args.cassette}: {exc}") from exc
        if {s.id for s in specs} != rec.spec_ids - rec.hired_ids:
            raise _Usage("the cassette's specs are not the recording's minds: their ids differ")
        if cas.parameters["steps"] != rec.steps:
            raise _Usage("the cassette's parameters disagree with its recording (steps)")
        if (package := cas.parameters.get("package")) is not None:
            try:
                packages.check(package, cas.parameters["workflow_input"])
            except packages.PackageError as exc:
                raise _Usage(f"{args.cassette}: {exc}") from exc
        hiring = recorded_hiring(cas.parameters, rec)
        try:
            for spec in specs:  # the recorded spec itself must be one a mind is built from
                check_spec(spec)
            specs = [as_cassette(s) for s in specs]
            for spec in specs:
                check_spec(spec)
        except (ProviderRefused, ValueError) as exc:
            raise _Usage(f"the specs cannot replay as cassette minds: {exc}") from exc
        registrar_key, clock_key, server = _keys(args)
    except (SpecError, _Usage) as exc:
        print(f"fund-runtime: {exc}", file=sys.stderr)
        return 2
    out = asyncio.run(_conduct(specs, server, registrar_key, clock_key, transport,
                               steps=rec.steps, days_per_step=cas.parameters["days_per_step"],
                               workflow_input=cas.parameters["workflow_input"],
                               max_tool_calls=cas.parameters["max_tool_calls"], replay=rec,
                               package=cas.parameters.get("package"), hiring=hiring))
    print(redact(json.dumps(out, indent=2, sort_keys=True)))
    return 0 if out["ended"] == "completed" else 1


def recorded_hiring(parameters: dict[str, Any], rec: Recording) -> HireTemplate | None:
    """The hiring template a recorded run hired with (``None``: it hired nobody), checked as a
    mind can be built from it; else :class:`_Usage`."""
    doc = parameters.get("hiring")
    if doc is None:
        if rec.hires:
            raise _Usage("the recording hired, but the cassette holds no hiring template")
        return None
    try:
        template = HireTemplate.model_validate(doc)
        check_spec(probe_spec(template))
        check_spec(as_cassette(probe_spec(template)))
    except (ValueError, ProviderRefused) as exc:
        raise _Usage(f"the cassette's hiring template cannot replay: {exc}") from exc
    return template


def _backtest(args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None) -> int:
    hosting = args.world is not None
    try:
        specs = load_specs(args.specs)
        if not specs:
            raise _Usage(f"no specs in {args.specs}: a run needs minds")
        if hosting:
            if args.server is not None:
                raise _Usage("--world and --server are exclusive: the run is hosted in its own "
                             "world, or in an App the operator built")
            if args.cassette is None:
                raise _Usage("--world needs --cassette: a hosted world exists to be recorded")
            workflow_input = _check_run_flags(args, args.steps)
            try:
                recipe, key = world.load_world(args.world), world.world_key()
            except world.WorldError as exc:
                raise _Usage(f"--world: {exc.reason}") from exc
            registrar_key = clock_key = server = ""
        else:
            workflow_input, registrar_key, clock_key, server = _shared(args, args.steps)
        if args.package is not None:
            try:
                packages.check(args.package, workflow_input)
            except packages.PackageError as exc:
                raise _Usage(str(exc)) from exc
        if args.cassette is not None:
            try:
                cassette.check_path(args.cassette)
            except CassetteError as exc:
                raise _Usage(str(exc)) from exc
        hiring = load_template(args.hire) if args.hire is not None else None
    except (SpecError, _Usage) as exc:
        print(f"fund-runtime: {exc}", file=sys.stderr)
        return 2
    run = dict(steps=args.steps, days_per_step=args.days_per_step, workflow_input=workflow_input,
               max_tool_calls=args.max_tool_calls, package=args.package, hiring=hiring,
               charge_each_step=args.charge_each_step)
    ledger = None
    if hosting:
        try:
            out, ledger = asyncio.run(_hosted(specs, recipe, key, **run))
        except world.WorldError as exc:  # no run began: there is nothing to record
            print(f"fund-runtime: world: {exc.reason}" + (f"\n{exc.detail}" if exc.detail else ""),
                  file=sys.stderr)
            return 1
    else:
        out = asyncio.run(_conduct(specs, server, registrar_key, clock_key, transport, **run))
    print(redact(json.dumps(out, indent=2, sort_keys=True)))
    code = 0 if out["ended"] == "completed" else 1
    if (lost := _unattributed(out.get("metering"))):
        # Spent, and not posted to the ledger: the run is not clean (ADR-044 §5).
        print(f"fund-runtime: {lost} metered micro-dollars not attributed: "
              f"{json.dumps(out['metering']['sync'], sort_keys=True)}", file=sys.stderr)
        code = 1
    if args.cassette is not None:  # every run that began is written, refused ones too (Art. 9)
        try:
            redactions = cassette.write(
                args.cassette, out,
                parameters={**{k: run[k] for k in ("steps", "days_per_step", "max_tool_calls",
                                                   "workflow_input", "package", "charge_each_step")
                               if k not in ("package", "charge_each_step") or run[k]},
                            **({"hiring": hiring.model_dump(mode="json")} if hiring else {})},
                specs=[spec.model_dump(mode="json") for spec in specs],
                world={"recipe": recipe} if ledger is not None else None, ledger=ledger)
        except CassetteError as exc:
            print(f"fund-runtime: {exc}", file=sys.stderr)
            return 1
        print(f"fund-runtime: cassette {args.cassette} ({redactions} redactions)",
              file=sys.stderr)
    return code


async def _hosted(specs: list[AgentSpec], recipe: dict[str, Any], key: str,
                  **run: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The run in a world of its own (:mod:`runtime.world`): ``(outcome, ledger)``. The ledger is
    physics' own export of the world's database after the server stopped; ``None`` if physics
    could not write it down (the outcome is still returned: a trial is never hidden)."""
    async with world.hosted(recipe, key) as hosted_world:
        url = await hosted_world.serve()
        try:
            out = await _conduct(specs, url, hosted_world.registrar_key, hosted_world.clock_key,
                                 None, declare_models=world.declares_models(recipe), **run)
        finally:
            hosted_world.stop()
        try:
            return out, hosted_world.export_ledger()
        except world.WorldError:
            return out, None


async def _conduct(specs: list[AgentSpec], server: str, registrar_key: str, clock_key: str,
                   transport: httpx.AsyncBaseTransport | None, *,
                   hiring: HireTemplate | None = None, declare_models: bool = False,
                   **run: Any) -> dict[str, Any]:
    def connect(key: str) -> FundClient:
        return FundClient(base_url=server, api_key=key, transport=transport)

    def refused(reason: str, registered: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
        return {"ended": "refused", "reason": reason, "registered": list(registered), "run": None}

    def halted(registered: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
        return {"ended": "halted", "reason": "halted", "registered": list(registered), "run": None}

    # B-053: specs that could never wake tell physics nothing (no declaration, no
    # agent); one read of the law decides. B-054: a HALT at any stage reads ``halted``.
    law = read_governance()
    if law.halted:
        return halted()
    if (problem := vet(specs, law)) is not None:
        return refused(f"provision:{problem}")
    replaying = run.get("replay") is not None
    if hiring is not None:
        # A hire is a mind the run will make: judged before physics hears of the run.
        for spec in sorted(specs, key=lambda s: s.id):
            if spec.id.startswith(HIRE_PREFIX):
                return refused(f"provision:hire_prefix:{spec.id}")
        if not replaying and (problem := vet_template(hiring, law)) is not None:
            return refused(f"provision:{problem}")
    hire_kind = (None if hiring is None
                 else as_cassette(probe_spec(hiring)) if replaying else probe_spec(hiring))
    if run.get("replay") is None:
        # Red-team 0020: outside a replay a cassette mind has no tape and could never wake.
        for spec in sorted(specs, key=lambda s: s.id):
            if spec.provider == "cassette":
                return refused(f"provision:cassette_without_recording:{spec.id}")
    registrar, clock = connect(registrar_key), connect(clock_key)
    minds: list[Mind] = []
    try:
        # Both before anything is registered: physics takes the declaration only
        # while no firm agent has acted (ADR-032 (p)).
        problem = await check_clock(clock) or await declare_minds(
            clock, [*specs, *([hire_kind] if hire_kind is not None else [])])
        if problem == "minds_refused:423":
            return halted()
        if problem is not None:
            return refused(problem)
        # Where the metered minds' keys live: the fake provisioner, in this process (ADR-044),
        # or the OpenRouter account (ADR-047). One kind per run.
        metered = {s.provider for s in [*specs, *([hire_kind] if hire_kind is not None else [])]
                   if s.provider in METERED_PROVIDERS}
        provisioner: FakeProvisioner | OpenRouterProvisioner | None = None
        if len(metered) > 1:
            return refused("provision:mixed_metered_providers")
        if metered == {"fake-metered"}:
            provisioner = FakeProvisioner()
        elif metered == {"openrouter"}:
            try:
                provisioner = OpenRouterProvisioner.from_env(
                    usd_to_micros_floor(law.monthly_llm_usd_cap))
            except OpenRouterError as exc:
                return refused(f"provision:openrouter_unavailable:{exc.status}")
        try:
            minds = await provision(specs, registrar, connect, provisioner=provisioner,
                                    declare_models=declare_models)
        except ProvisionError as exc:
            # Nothing has woken, so no key has spent anything: there is nothing to sync. Keys
            # already minted are disabled all the same.
            if isinstance(provisioner, OpenRouterProvisioner):
                provisioner.close()
            if _is_halt(exc.reason):
                return halted(exc.registered)
            return refused(f"provision:{exc.reason}", exc.registered)
        except BaseException:
            # Any other end mid-provisioning (a crash, Ctrl-C): the keys made so far still spend
            # no more.
            if isinstance(provisioner, OpenRouterProvisioner):
                provisioner.close()
            raise
        metering = None
        onboarding = None if hiring is None else Onboarding(
            hiring, registrar, connect, provisioner=provisioner,
            recorded=run["replay"].hires if replaying else None)
        try:
            record = await run_backtest(minds, clock, hiring=onboarding, **run)
        finally:
            if onboarding is not None:
                minds = [*minds, *onboarding.minds]   # the hired minds are metered and closed too
            if provisioner is not None:
                # Once, after the run ends, whatever the end — a crash or SystemExit too
                # (red-team 0021): the meter's totals reach the ledger.
                try:
                    metering = await _sync_metering(provisioner, minds, clock, law)
                finally:
                    if isinstance(provisioner, OpenRouterProvisioner):
                        # Then every key the run made is disabled (ADR-047 §3), even if the
                        # sync itself crashed (red-team 0027): it spends no more.
                        left = provisioner.close()
                        if metering is not None:
                            metering["keys_left_enabled"] = left
        out = {"ended": record.ended, "reason": record.reason,
               "registered": [m.spec.id for m in minds], "run": record_json(record)}
        if metering is not None:
            out["metering"] = metering
        return out
    finally:
        for c in [registrar, clock, *(m.client for m in minds)]:
            await c.aclose()


async def _sync_metering(provisioner: FakeProvisioner | OpenRouterProvisioner, minds: list[Mind],
                         clock: FundClient, law: Governance) -> dict[str, Any]:
    """Post every key's total to physics as the Runtime's identity (ADR-041) and report what the
    keys cost: who, how much, and whether each dollar reached the ledger. A sync that fails
    is data in the outcome, not an exception: the caller exits non-zero on it. The meter is
    read **once**: what is posted and what is reported are the same numbers (a real provider's
    usage can move between two reads)."""
    cap = None if law.monthly_llm_usd_cap is None else usd_to_micros_floor(law.monthly_llm_usd_cap)
    try:
        snapshot = provisioner.usage()
    except (OpenRouterError, httpx.HTTPError) as exc:
        # The provider could not say what was spent: nothing is posted, every key is unknown.
        error = f"meter_unreadable:{getattr(exc, 'status', 0)}"
        keys = [{"spec_id": m.spec.id, "agent_id": provisioner.agent_of(m.meter.key_ref),
                 "key_ref": m.meter.key_ref, "limit_usd_micros": provisioner.limit(m.meter.key_ref),
                 "spent_usd_micros": None, "charges": provisioner.charges(m.meter.key_ref)}
                for m in minds if m.meter is not None]
        return {"cap_usd_micros": cap, "keys": keys,
                "total_usd_micros": sum(k["limit_usd_micros"] for k in keys),
                "sync": {"posted": 0, "unchanged": 0, "halted": False, "refused": [], "error": error}}
    try:
        report = await sync_costs(_Snapshot(snapshot), clock)
        sync = {"posted": report.posted, "unchanged": report.unchanged, "halted": report.halted,
                "refused": [list(r) for r in report.refused], "error": None}
    except FundAPIError as exc:  # 401/403: the wrong key; every post would fail the same way
        sync = {"posted": 0, "unchanged": 0, "halted": False, "refused": [],
                "error": f"sync_failed:{exc.status_code}"}
    usage = {u.key_ref: u for u in snapshot}
    keys = [{"spec_id": m.spec.id, "agent_id": usage[m.meter.key_ref].agent_id,
             "key_ref": m.meter.key_ref,
             "limit_usd_micros": provisioner.limit(m.meter.key_ref),
             "spent_usd_micros": usage[m.meter.key_ref].usd_micros_total,
             "charges": provisioner.charges(m.meter.key_ref)}
            for m in minds if m.meter is not None]
    return {"cap_usd_micros": cap,
            "keys": keys,
            "total_usd_micros": sum(k["spent_usd_micros"] for k in keys),
            "sync": sync}


class _Snapshot:
    """One read of the meter, handed to :func:`sync_costs` as its provisioner."""

    def __init__(self, usage: list[Any]) -> None:
        self._usage = usage

    def usage(self) -> list[Any]:
        return list(self._usage)


def _unattributed(metering: dict[str, Any] | None) -> int:
    """Micro-dollars spent that physics did not take: all of them if the sync was stopped
    (HALT) or failed, otherwise those of the keys it refused."""
    if metering is None:
        return 0
    sync = metering["sync"]
    if sync["halted"] or sync["error"] is not None:
        return metering["total_usd_micros"]
    refused = {r[0] for r in sync["refused"]}
    return sum(k["spent_usd_micros"] for k in metering["keys"] if k["key_ref"] in refused)


def _is_halt(reason: str) -> bool:
    """True only for the reasons :func:`provision` gives when HALT stopped it: its own
    re-read, the gate's ``halted`` under its own read, or physics' 423 (only
    ``app.registry.halt`` answers 423). Spec ids hold no ``:`` (``runtime.spec``)."""
    parts = reason.split(":")
    return (reason == "halted"
            or (len(parts) == 3 and parts[0] == "wake_refused" and parts[2] == "halted")
            or (len(parts) == 3 and parts[0] == "register_failed" and parts[2] == "423"))


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
