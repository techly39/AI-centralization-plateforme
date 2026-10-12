"""The wake gate: may this mind wake, may this tool batch run? (ADR-032 (4), Q-0005)

The gate reads the law literally and fails closed:

* **HALT** → nothing wakes and no further tool batch runs, whatever the provider.
* **Cap** ``null`` → only a provider named in :data:`ZERO_COST_PROVIDERS`,
  through an adapter named in :data:`ZERO_COST_ADAPTERS`, may wake. Every
  other pair is refused, unknown names included.
* **Cap set** → a spending provider is still refused (``no_metered_key``) until
  per-agent metered keys exist (R-6): a cap the Runtime cannot meter is a cap
  it cannot keep.

The gate decides on the provider and adapter **names** taken from the AgentSpec, which the
operator writes and no mind can edit. It never asks a provider object what it
costs: a gate that asks a component whether it is dangerous is not a gate
(cycle-20 audit). Names match exactly — no case folding, no trimming.

Every decision reads governance fresh (:func:`runtime.governance.read_governance`).
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.governance import Governance, read_governance

#: The only providers that may wake while the cap is ``null``: a deterministic
#: script with no model and no network client, and a replay of recorded output
#: that calls nothing. Both cost $0 by construction. Changing this set is a law
#: change: an ADR, and the Human sees it in Q-0005.
ZERO_COST_PROVIDERS = frozenset({"scripted", "cassette"})

#: The only adapter a zero-cost mind may wake through. ``openclaw`` runs its own
#: model on its own key, whatever the spec's provider says, so it is always
#: spending (ADR-032 (4); red-team 0012 H1: ``scripted`` + ``openclaw`` woke).
ZERO_COST_ADAPTERS = frozenset({"native"})


@dataclass(frozen=True)
class Decision:
    allowed: bool
    #: ``zero_cost`` | ``halted`` | ``cap_null`` | ``no_metered_key`` | ``ok``
    reason: str


def decide_wake(provider: str, adapter: str) -> Decision:
    """Before every wake: may a mind with this provider and adapter wake now?"""
    return decide_wake_under(provider, adapter, read_governance())


def decide_batch() -> Decision:
    """Before every tool-call batch inside a wake: may it run now? (03 §3)"""
    if read_governance().halted:
        return Decision(False, "halted")
    return Decision(True, "ok")


def decide_wake_under(provider: object, adapter: object, law: Governance) -> Decision:
    """The same decision against a law already read (one read per report)."""
    if law.halted:
        return Decision(False, "halted")
    # Exactly ``str``: a subclass could answer the membership test with its own
    # ``__eq__``/``__hash__`` (red-team 0012 H4).
    if (
        type(provider) is str and provider in ZERO_COST_PROVIDERS
        and type(adapter) is str and adapter in ZERO_COST_ADAPTERS
    ):
        return Decision(True, "zero_cost")
    if law.monthly_llm_usd_cap is None:
        return Decision(False, "cap_null")
    return Decision(False, "no_metered_key")
