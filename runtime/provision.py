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
* Every spec is checked **before any is registered**: ids and names unique, the
  wake gate open under one read of the law (HALT or a cap refusal provisions
  nothing), ``wake_policy`` not ``never``, and a mind buildable from the spec.
  A spec that could never wake gets no agent.
* An answer is accepted only if it is the agent asked for (name, role, pod, an
  int id never seen in this call, a key). If a registration fails or is wrong,
  :class:`ProvisionError` names the specs already registered: those agents exist
  in the run's database, which is spoiled (ADR-027: a run is a database).

Keys are never written anywhere: each lives only in the client ``connect`` builds
from it. The caller closes the clients.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from mcp_server.client import FundAPIError, FundClient
from runtime.gate import decide_wake_under
from runtime.governance import read_governance
from runtime.lockstep import Mind
from runtime.registry import ProviderRefused, build_provider
from runtime.spec import AgentSpec


class ProvisionError(RuntimeError):
    """Provisioning stopped. ``reason`` is a short code; ``registered`` lists the
    spec ids whose App agent already exists (empty if nothing was registered)."""

    def __init__(self, reason: str, registered: Sequence[str] = ()) -> None:
        self.reason = reason
        self.registered = tuple(registered)
        super().__init__(f"{reason} (already registered: {', '.join(self.registered) or 'none'})")


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
    if len({s.name for s in ordered}) != len(ordered):
        raise ProvisionError("duplicate_name")
    law = read_governance()  # one read: every spec is judged under the same law
    for spec in ordered:
        if spec.wake_policy == "never":
            raise ProvisionError(f"wake_policy_never:{spec.id}")
        decision = decide_wake_under(spec.provider, spec.adapter, law)
        if not decision.allowed:
            raise ProvisionError(f"wake_refused:{spec.id}:{decision.reason}")
        try:
            build_provider(spec)
        except ProviderRefused as exc:
            raise ProvisionError(f"provider_refused:{spec.id}:{exc.reason}") from exc

    minds: list[Mind] = []
    seen: set[int] = set()
    try:
        for spec in ordered:
            done = [m.spec.id for m in minds]
            try:
                made = await registrar.post("/agents/register", {
                    "name": spec.name, "role": spec.role, "pod_id": spec.pod,
                    "charter_ref": f"spec:{spec.id}"})
            except FundAPIError as exc:
                raise ProvisionError(f"register_failed:{spec.id}:{exc.status_code}",
                                     done) from exc
            if not _is_the_agent(made, spec) or made["id"] in seen:
                # Registered or not, the answer is not this spec's agent: the run
                # cannot know what exists, so this spec is named as possibly registered.
                raise ProvisionError(f"wrong_agent:{spec.id}", [*done, spec.id])
            seen.add(made["id"])
            minds.append(Mind(spec, connect(made["api_key"])))
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
