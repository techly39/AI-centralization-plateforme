"""Minds made from their specs: one App agent per spec (ADR-032 (n), R-3b-2b-1).

Until now the caller registered each App agent and handed its key to the
conductor, so nothing bound the spec to the agent beyond role and pod.
:func:`provision` registers the agent **from the spec** over HTTP:

* ``name`` = the spec's ``name`` (the wake and the conductor refuse a key whose
  ``/me`` name is not the spec's), ``role`` and ``pod_id`` = the spec's, and
  ``charter_ref`` = ``spec:<id>``, so the App's own records say which spec an
  agent was made from.
* The registrar is a key the **caller** holds; physics decides whether it may
  register (``REGISTER_AGENTS``). The Runtime's clock identity is not given that
  right: the clock key stays the narrowest key in the world (prime rule, safer
  seal). Every ``agent_registered`` event names the registrar as its actor.
* Every spec is checked **before any is registered**:
  - ids are unique, and names are unique **as a reader sees them**
    (:func:`name_key`, physics' fold);
  - no name is reserved;
  - the wake gate is open under one read of the law (HALT or a cap refusal
    provisions nothing); a metered spec is judged as if its key existed, and the
    budgets of all metered specs, in whole micro-dollars, must fit the cap together
    (ADR-044);
  - ``wake_policy`` is not ``never``;
  - a mind can be built from the spec;
  - no name is already taken in the directory the registrar reads (red-team 0016 H2/H3).

  A spec that could never wake, or that physics would certainly refuse, gets no
  agent. HALT is read again before every registration, so a HALT that appears
  part-way stops the next one (Art. 5.2). Someone may still take a name between
  the directory read and the POST. That fails closed: physics answers 409.
* An answer is accepted only if it is the agent asked for (name, role, pod, an
  int id never seen in this call, a key). Otherwise :class:`ProvisionError`
  names every spec whose App agent **may** exist: those already registered,
  plus the failing one unless physics answered 4xx (only a refusal proves
  nothing was made, red-team 0016 H1). If the caller's ``connect`` fails, the
  error names the same (H1b). Those agents are in the run's database, which is
  spoiled (ADR-027: a run is a database).

A metered spec gets one key at the provisioner, minted right after its agent is registered and
bound to that agent's id, with a spending limit of its budget. A zero-cost mind gets none.

Keys are never written anywhere: each lives only in the client ``connect`` builds
from it. The caller closes the clients of a successful call; a failed call closes
the ones it made.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence

from mcp_server.client import FundAPIError, FundClient
from runtime.gate import METERED_PROVIDERS, decide_batch, decide_wake_under
from runtime.governance import Governance, read_governance
from runtime.lockstep import Mind
from runtime.metering import (
    MAX_METERED_USD_MICROS,
    FakeProvisioner,
    Meter,
    usd_to_micros_floor,
)
from runtime.openrouter import OpenRouterProvisioner, OverCap
from runtime.registry import ProviderRefused, check_spec
from runtime.spec import AgentSpec

#: Physics' reserved names and name fold (``app.registry.service``), copied: the
#: Runtime imports no ``app`` module. ``tests/test_runtime_provision.py`` pins
#: the copy to the original.
RESERVED_NAMES = frozenset({"system", "runtime"})
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cn", "Co", "Cs", "Mn", "Me"})
_BLANK_CHARS = frozenset("ᅟᅠㅤﾠ⠀")


def name_key(name: str) -> str:
    """A name as a reader sees it: NFKC, case-folded, characters that draw
    nothing dropped, surrounding space stripped."""
    folded = unicodedata.normalize("NFKC", name).casefold()
    return "".join(
        c for c in folded
        if unicodedata.category(c) not in _INVISIBLE_CATEGORIES and c not in _BLANK_CHARS
    ).strip()


class ProvisionError(RuntimeError):
    """Provisioning stopped. ``reason`` is a short code; ``registered`` lists the
    spec ids whose App agent exists or may exist (empty: nothing was registered)."""

    def __init__(self, reason: str, registered: Sequence[str] = ()) -> None:
        self.reason = reason
        self.registered = tuple(registered)
        super().__init__(f"{reason} (registered or maybe: {', '.join(self.registered) or 'none'})")


async def provision(
    specs: Sequence[AgentSpec],
    registrar: FundClient,
    connect: Callable[[str], FundClient],
    *,
    provisioner: FakeProvisioner | OpenRouterProvisioner | None = None,
    declare_models: bool = False,
) -> list[Mind]:
    """Register one App agent per spec through ``registrar``; return the minds in id order.
    With ``declare_models`` (a world under the reproduction law), each spec's model is declared
    at registration: a founding PM's design goes on the record.

    ``connect(api_key)`` builds the client a mind will act through. ``provisioner`` is where the
    metered specs' keys are minted; a metered spec without one is refused.
    """
    ordered = sorted(specs, key=lambda s: s.id)
    # one read: every spec is judged under the same law
    if (problem := vet(ordered, read_governance())) is not None:
        raise ProvisionError(problem)
    try:
        directory = await registrar.get("/agents")
    except FundAPIError as exc:
        raise ProvisionError(f"directory_unreadable:{exc.status_code}") from exc
    if not isinstance(directory, list):
        raise ProvisionError("directory_malformed")
    if provisioner is None and any(s.provider in METERED_PROVIDERS for s in ordered):
        raise ProvisionError("no_provisioner")
    # A key is made where its mind spends: the fake's keys answer no model, OpenRouter's no script.
    wanted = {"fake-metered": FakeProvisioner, "openrouter": OpenRouterProvisioner}
    for spec in ordered:
        if spec.provider in METERED_PROVIDERS and not isinstance(provisioner, wanted[spec.provider]):
            raise ProvisionError(f"wrong_provisioner:{spec.id}")
    taken = {name_key(a["name"]) for a in directory
             if isinstance(a, dict) and type(a.get("name")) is str}
    for spec in ordered:
        if name_key(spec.name) in taken:
            raise ProvisionError(f"name_taken:{spec.id}")

    minds: list[Mind] = []
    seen: set[int] = set()
    try:
        for spec in ordered:
            done = [m.spec.id for m in minds]
            if not decide_batch().allowed:  # HALT is re-read before every registration
                raise ProvisionError("halted", done)
            try:
                made = await registrar.post("/agents/register", {
                    "name": spec.name, "role": spec.role, "pod_id": spec.pod,
                    "charter_ref": f"spec:{spec.id}",
                    **({"model": spec.model} if declare_models and spec.model else {})})
            except FundAPIError as exc:
                # Only a refusal (4xx) proves nothing was made; a lost answer may hide one.
                maybe = done if exc.status_code < 500 else [*done, spec.id]
                raise ProvisionError(f"register_failed:{spec.id}:{exc.status_code}",
                                     maybe) from exc
            except Exception as exc:  # noqa: BLE001 - whatever broke, name what may exist
                raise ProvisionError(f"register_failed:{spec.id}:error",
                                     [*done, spec.id]) from exc
            if not _is_the_agent(made, spec) or made["id"] in seen:
                # Registered or not, the answer is not this spec's agent: the run
                # cannot know what exists, so this spec is named as possibly registered.
                raise ProvisionError(f"wrong_agent:{spec.id}", [*done, spec.id])
            seen.add(made["id"])
            try:
                client = connect(made["api_key"])
            except Exception as exc:  # noqa: BLE001 - the caller's connect failed
                raise ProvisionError(f"connect_failed:{spec.id}", [*done, spec.id]) from exc
            meter = None
            if spec.provider in METERED_PROVIDERS:
                try:
                    limit = usd_to_micros_floor(spec.budget_usd)
                    meter = Meter(provisioner, (
                        provisioner.create_key(made["id"], limit, spec_id=spec.id)
                        if isinstance(provisioner, OpenRouterProvisioner)   # names the key
                        else provisioner.create_key(made["id"], limit)))
                except OverCap as exc:  # the firm's month is full (ADR-047 §4): no key, no wake
                    await client.aclose()
                    raise ProvisionError(f"key_over_cap:{spec.id}", [*done, spec.id]) from exc
                except Exception as exc:  # noqa: BLE001 - the agent exists, its key does not
                    await client.aclose()
                    raise ProvisionError(f"key_failed:{spec.id}", [*done, spec.id]) from exc
            minds.append(Mind(spec, client, meter))
    except BaseException:
        for mind in minds:  # no client outlives a failed provisioning
            await mind.client.aclose()
        raise
    return minds


def vet(specs: Sequence[AgentSpec], law: Governance) -> str | None:
    """Why ``specs`` cannot be provisioned under ``law``, or ``None``: every check
    :func:`provision` makes before it reads the directory, with no network call
    (B-053). ``fund-runtime backtest`` asks first, so a run whose minds could never
    wake tells physics nothing: no ``/run/minds`` declaration, no agent. The reason
    is the one :func:`provision` would raise."""
    ordered = sorted(specs, key=lambda s: s.id)
    limits: dict[str, int] = {}   # metered spec id -> its key's limit, micro-dollars
    if len({s.id for s in ordered}) != len(ordered):
        return "duplicate_spec_id"
    if len({name_key(s.name) for s in ordered}) != len(ordered):
        return "duplicate_name"
    for spec in ordered:
        if name_key(spec.name) in RESERVED_NAMES:
            return f"name_reserved:{spec.id}"
        if spec.wake_policy == "never":
            return f"wake_policy_never:{spec.id}"
        # A metered spec is judged as if its key existed: provision mints it.
        decision = decide_wake_under(spec.provider, spec.adapter, law,
                                     metered=spec.provider in METERED_PROVIDERS)
        if not decision.allowed:
            return f"wake_refused:{spec.id}:{decision.reason}"
        try:
            check_spec(spec)
        except ProviderRefused as exc:
            return f"provider_refused:{spec.id}:{exc.reason}"
        if decision.reason == "metered":
            limits[spec.id] = usd_to_micros_floor(spec.budget_usd)
            if limits[spec.id] > MAX_METERED_USD_MICROS:
                return f"budget_too_large:{spec.id}"
    if limits and sum(limits.values()) > usd_to_micros_floor(law.monthly_llm_usd_cap):
        return "budget_over_cap"
    return None


def _is_the_agent(made: object, spec: AgentSpec) -> bool:
    return (
        isinstance(made, dict)
        and type(made.get("id")) is int
        and (made.get("name"), made.get("role"), made.get("pod_id")) == (
            spec.name, spec.role, spec.pod)
        and type(made.get("api_key")) is str and made["api_key"] != ""
    )
