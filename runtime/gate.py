"""The wake gate: may this mind wake, may this tool batch run? (ADR-032 (4), Q-0005)

The gate reads the law literally and fails closed:

* **HALT** → nothing wakes and no further tool batch runs, whatever the provider.
* **Cap** ``null`` → only the providers named in :data:`ZERO_COST_PROVIDERS`
  may wake. Every other name is refused, an unknown one included.
* **Cap set** → a spending provider is still refused (``no_metered_key``) until
  per-agent metered keys exist (R-6): a cap the Runtime cannot meter is a cap
  it cannot keep.

The gate decides on a provider **name** taken from the AgentSpec, which the
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


@dataclass(frozen=True)
class Decision:
    allowed: bool
    #: ``zero_cost`` | ``halted`` | ``cap_null`` | ``no_metered_key`` | ``ok``
    reason: str


def decide_wake(provider: str) -> Decision:
    """Before every wake: may a mind backed by ``provider`` wake now?"""
    return decide_wake_under(provider, read_governance())


def decide_batch() -> Decision:
    """Before every tool-call batch inside a wake: may it run now? (03 §3)"""
    if read_governance().halted:
        return Decision(False, "halted")
    return Decision(True, "ok")


def decide_wake_under(provider: object, law: Governance) -> Decision:
    """The same decision against a law already read (one read per report)."""
    if law.halted:
        return Decision(False, "halted")
    if isinstance(provider, str) and provider in ZERO_COST_PROVIDERS:
        return Decision(True, "zero_cost")
    if law.monthly_llm_usd_cap is None:
        return Decision(False, "cap_null")
    return Decision(False, "no_metered_key")
