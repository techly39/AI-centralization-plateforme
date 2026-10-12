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
    provisions nothing);
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

Keys are never written anywhere: each lives only in the client ``connect`` builds
from it. The caller closes the clients of a successful call; a failed call closes
the ones it made.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence

from mcp_server.client import FundAPIError, FundClient
from runtime.gate import decide_batch, decide_wake_under
from runtime.governance import read_governance
from runtime.lockstep import Mind
from runtime.registry import ProviderRefused, build_provider
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
) -> list[Mind]:
    """Register one App agent per spec through ``registrar``; return the minds in id order.

    ``connect(api_key)`` builds the client a mind will act through.
    """
    ordered = sorted(specs, key=lambda s: s.id)
    if len({s.id for s in ordered}) != len(ordered):
        raise ProvisionError("duplicate_spec_id")
    if len({name_key(s.name) for s in ordered}) != len(ordered):
        raise ProvisionError("duplicate_name")
    law = read_governance()  # one read: every spec is judged under the same law
    for spec in ordered:
        if name_key(spec.name) in RESERVED_NAMES:
            raise ProvisionError(f"name_reserved:{spec.id}")
        if spec.wake_policy == "never":
            raise ProvisionError(f"wake_policy_never:{spec.id}")
        decision = decide_wake_under(spec.provider, spec.adapter, law)
        if not decision.allowed:
            raise ProvisionError(f"wake_refused:{spec.id}:{decision.reason}")
        try:
            build_provider(spec)
        except ProviderRefused as exc:
            raise ProvisionError(f"provider_refused:{spec.id}:{exc.reason}") from exc
    try:
        directory = await registrar.get("/agents")
    except FundAPIError as exc:
        raise ProvisionError(f"directory_unreadable:{exc.status_code}") from exc
    if not isinstance(directory, list):
        raise ProvisionError("directory_malformed")
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
                    "charter_ref": f"spec:{spec.id}"})
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
            minds.append(Mind(spec, client))
    except BaseException:
        for mind in minds:  # no client outlives a failed provisioning
            await mind.client.aclose()
        raise
    return minds


def _is_the_agent(made: object, spec: AgentSpec) -> bool:
    return (
        isinstance(made, dict)
        and type(made.get("id")) is int
        and (made.get("name"), made.get("role"), made.get("pod_id")) == (
            spec.name, spec.role, spec.pod)
        and type(made.get("api_key")) is str and made["api_key"] != ""
    )
