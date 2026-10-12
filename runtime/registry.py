"""Which name builds which mind (ADR-032 amendment (b), second half; R-2).

The wake gate lets a spec through on its ``provider`` name. That is only safe if
the name decides the class: ``scripted`` must build a scripted mind and nothing
else, whatever else the spec says. So the Runtime never accepts a provider
object from a caller — :func:`build_provider` builds it from the spec, through
:data:`PROVIDER_CLASSES`, a closed table in code.

The registry also refuses a spec whose fields contradict its provider (decided
in R-2, prime rule: safer budget, more honest measurement): a zero-cost provider
with a ``model`` or a ``budget_usd``, a ``scripted`` spec without a known
``script``, or a ``script`` on any other provider. A spec loads anyway — the
contradiction is refused where a mind would be built from it.

``cassette`` is on the gate's list but has no class until R-4: it is refused here
with ``unavailable``, never built from something else.
"""

from __future__ import annotations

from types import MappingProxyType

from runtime import scripted
from runtime.gate import ZERO_COST_PROVIDERS
from runtime.providers import LLMProvider
from runtime.spec import AgentSpec

#: provider name → the one class it builds. Changing this is a law change (ADR).
PROVIDER_CLASSES = MappingProxyType({
    "scripted": scripted.ScriptedProvider,
})


class ProviderRefused(ValueError):
    """No mind is built from this spec. ``reason`` is a short code for records."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def build_provider(spec: AgentSpec) -> LLMProvider:
    """The mind for ``spec``, or :class:`ProviderRefused`."""
    name = spec.provider
    if name in ZERO_COST_PROVIDERS:
        if spec.model is not None:
            raise ProviderRefused("contradiction", f"provider {name!r} runs no model; `model` is set")
        if spec.budget_usd != 0:
            raise ProviderRefused("contradiction", f"provider {name!r} spends nothing; `budget_usd` is set")
    if name != "scripted" and spec.script is not None:
        raise ProviderRefused("contradiction", f"`script` is for provider 'scripted', not {name!r}")
    if name == "scripted":
        script = scripted.SCRIPTS.get(spec.script) if type(spec.script) is str else None
        if script is None:
            raise ProviderRefused("unknown_script", f"no script named {spec.script!r}")
        return PROVIDER_CLASSES["scripted"](script)
    if name == "cassette":
        raise ProviderRefused("unavailable", "the cassette provider arrives in R-4")
    raise ProviderRefused("unknown_provider", f"no provider named {name!r}")
