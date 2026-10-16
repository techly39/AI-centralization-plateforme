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

``cassette`` builds :class:`runtime.replay.CassetteProvider` from a **tape**: data (exactly
:class:`runtime.replay.Tape`, checked with ``type(...) is``), never a provider. Without a tape
it is refused with ``unavailable``; a tape handed to any other name is a ``contradiction``
(R-4b, ADR-038). :func:`check_spec` is the part of that which needs no tape: provisioning
uses it, and still refuses every contradiction.
"""

from __future__ import annotations

from types import MappingProxyType

from runtime import metering, openrouter, replay, scripted
from runtime.gate import METERED_PROVIDERS, ZERO_COST_PROVIDERS
from runtime.providers import LLMProvider
from runtime.spec import AgentSpec

#: provider name → the one class it builds. Changing this is a law change (ADR).
PROVIDER_CLASSES = MappingProxyType({
    "scripted": scripted.ScriptedProvider,
    "cassette": replay.CassetteProvider,
    "fake-metered": metering.FakeMeteredProvider,
    "openrouter": openrouter.OpenRouterProvider,
})


class ProviderRefused(ValueError):
    """No mind is built from this spec. ``reason`` is a short code for records."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def check_spec(spec: AgentSpec) -> None:
    """Raise :class:`ProviderRefused` if ``spec`` contradicts its provider or names no known
    one. Builds nothing (a ``cassette`` spec needs a tape to be built)."""
    name = spec.provider
    if name in ZERO_COST_PROVIDERS:
        # A cassette mind may carry the model it was recorded with (ADR-047 §6): the request
        # hash names it, and the mind still calls nothing.
        if spec.model is not None and name != "cassette":
            raise ProviderRefused("contradiction", f"provider {name!r} runs no model; `model` is set")
        if spec.budget_usd != 0:
            raise ProviderRefused("contradiction", f"provider {name!r} spends nothing; `budget_usd` is set")
    if name not in ("scripted", "fake-metered") and spec.script is not None:
        raise ProviderRefused(
            "contradiction", f"`script` is for provider 'scripted' or 'fake-metered', not {name!r}")
    if name in METERED_PROVIDERS:
        if metering.usd_to_micros_floor(spec.budget_usd) <= 0:
            raise ProviderRefused("no_budget", f"provider {name!r} spends: `budget_usd` must buy "
                                  "at least one micro-dollar")
    if name == "fake-metered" and spec.model is not None:
        raise ProviderRefused("contradiction", f"provider {name!r} runs no model; `model` is set")
    if name == "openrouter" and (type(spec.model) is not str or not spec.model.strip()):
        raise ProviderRefused("no_model", "provider 'openrouter' needs the spec's `model`")
    if name in ("scripted", "fake-metered"):
        if type(spec.script) is not str or spec.script not in scripted.SCRIPTS:
            raise ProviderRefused("unknown_script", f"no script named {spec.script!r}")
    elif name not in PROVIDER_CLASSES:
        raise ProviderRefused("unknown_provider", f"no provider named {name!r}")


def build_provider(spec: AgentSpec, tape: replay.Tape | None = None,
                   meter: metering.Meter | None = None) -> LLMProvider:
    """The mind for ``spec``, or :class:`ProviderRefused`. ``tape`` is for ``cassette`` only,
    ``meter`` (the mind's own key) for a metered provider only."""
    check_spec(spec)
    name = spec.provider
    if meter is not None and name not in METERED_PROVIDERS:
        raise ProviderRefused("contradiction", f"a meter is for a metered provider, not {name!r}")
    if name in METERED_PROVIDERS:
        if tape is not None:
            raise ProviderRefused("contradiction", "a tape is for provider 'cassette'")
        if type(meter) is not metering.Meter:  # a key is a Meter, not whatever claims to be one
            raise ProviderRefused("unavailable", "a metered provider needs its mind's own key")
        if name == "openrouter":
            # The key must live at the real provisioner: a fake key would answer nothing.
            if type(meter.provisioner) is not openrouter.OpenRouterProvisioner:
                raise ProviderRefused("unavailable", "an openrouter mind's key is an OpenRouter key")
            return PROVIDER_CLASSES[name](spec.model, meter)
        if type(meter.provisioner) is not metering.FakeProvisioner:
            raise ProviderRefused("unavailable", "a fake metered mind's key is a fake key")
        return PROVIDER_CLASSES[name](scripted.SCRIPTS[spec.script], meter)
    if name == "scripted":
        if tape is not None:
            raise ProviderRefused("contradiction", "a tape is for provider 'cassette'")
        return PROVIDER_CLASSES["scripted"](scripted.SCRIPTS[spec.script])
    if name != "cassette":  # a provider added to the table later needs its own branch here
        raise ProviderRefused("unavailable", f"provider {name!r} has no builder")
    if type(tape) is not replay.Tape:  # a subclass, a dict or a provider is not a recording
        raise ProviderRefused("unavailable", "the cassette provider needs a recording of this wake")
    return PROVIDER_CLASSES["cassette"](tape)
