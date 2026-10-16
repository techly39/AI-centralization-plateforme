"""Red-team 0030 (cycle 42, ADR-047) — LOW: one turn's cost is not bounded by the Runtime.

Severity: **low** — passes a key's limit (and, when the limits fill the cap, the cap) by at most
one turn per key, and only if the provider admits a request while some limit remains and bills it
in full afterwards (the usual way per-key credit limits work).

``OpenRouterProvider.complete`` sends no ``max_tokens``: the model may write up to its own maximum
output in one turn. A key with $0.0001 left is still let through by a limit checked *before* the
request, and the turn costs whatever the model wrote. ADR-047 counts an enabled key at "its whole
limit" as if that were the most it can spend; it is the limit plus one unbounded turn. The fix is a
``max_tokens`` derived from what is left on the key (or a fixed, small bound per turn), so the
overshoot is bounded and the spec's budget is the most a mind can spend.

Hole tests are ``xfail(strict=True)``: they pass once the Builder fixes the physics.
"""

from __future__ import annotations

import httpx
import pytest

from runtime.metering import Meter
from runtime.openrouter import OpenRouterProvisioner
from runtime.registry import build_provider
from tests.test_runtime_openrouter import Account, chat, request, spec


@pytest.mark.xfail(strict=True, reason=(
    "LOW red-team 0030: a model turn's request carries no max_tokens, so one turn past a key's "
    "remaining limit costs whatever the model writes"))
def test_hole_a_turn_request_does_not_bound_its_own_output() -> None:
    account = Account()
    p = OpenRouterProvisioner("prov-key", 50_000_000, transport=httpx.MockTransport(account.handler),
                              run_tag="t1", settle_s=0, sleep=lambda s: None)
    mind = build_provider(spec(), meter=Meter(p, p.create_key(7, 1_000_000, spec_id="pm")))
    account.answers.append(chat("done"))
    mind.complete(request())
    body = account.chats[0]["body"]
    bound = body.get("max_tokens") or body.get("max_completion_tokens")
    assert type(bound) is int and bound > 0, sorted(body)
