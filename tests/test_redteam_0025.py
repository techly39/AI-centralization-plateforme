"""Red-team 0025 (cycle 42, ADR-047) — MEDIUM: a turn whose cost is not stated is synced as $0.

Severity: **medium** — a wrong record: the ledger's ``cost_metered`` for a mind that spent real
money says it spent nothing, so its pod's P&L is not charged for its thinking.

``OpenRouterProvisioner.usage()`` waits for the provider's per-key spend only until it reaches
``billed`` (the sum of the turns' own ``usage.cost``). Two ordinary cases leave ``billed`` at 0
for a turn that cost money:

* the answer carries no ``usage.cost`` (``usd_to_micros_ceil(None) == 0``: some routes, an
  error answer, a field renamed);
* the request timed out client-side (``httpx.ReadTimeout``) after the provider ran and billed it:
  ``billed()`` is never called for it.

With ``billed == 0`` the first read of the key's spend ends the wait, however soon after the turn
it is; the provider's per-key usage updates "a little after a turn" (the module says so), so the
read says 0 and 0 is posted — once, cumulative, for a key that is then disabled: the ledger never
catches up. The sync should wait out the settle time (or report the spend unknown) whenever a turn's
cost was not stated.

Hole tests are ``xfail(strict=True)``: they pass once the Builder fixes the physics.
"""

from __future__ import annotations

import json

import httpx
import pytest

from runtime.metering import Meter
from runtime.openrouter import OpenRouterProvisioner
from runtime.registry import build_provider
from tests.test_runtime_openrouter import Account, chat, request, spec


class LaggingSpend(Account):
    """The provider bills a turn, but the key's ``usage`` shows it only from the second read on."""

    def __init__(self, timeout: bool) -> None:
        super().__init__()
        self.timeout = timeout
        self.pending: dict[str, float] = {}
        self.reads = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/chat/completions":
            digest = self.secrets[request.headers["authorization"].removeprefix("Bearer ")]
            self.chats.append({"key": digest, "body": json.loads(request.content)})
            self.pending[digest] = self.pending.get(digest, 0.0) + 0.25   # what it really cost
            if self.timeout:
                raise httpx.ReadTimeout("the answer did not come back in time", request=request)
            answer = chat("done")
            del answer["usage"]["cost"]                                     # cost not stated
            return httpx.Response(200, json=answer)
        if request.method == "GET" and path.startswith("/keys/"):
            digest = path.removeprefix("/keys/")
            self.reads += 1
            if self.reads >= 2:                                             # the spend settles
                self.keys[digest]["usage"] += self.pending.pop(digest, 0.0)
        return super().handler(request)


@pytest.mark.xfail(strict=True, reason=(
    "MEDIUM red-team 0025: a turn whose cost the answer does not state (or that timed out after "
    "billing) is synced as $0: usage() stops at the first read when billed is 0"))
@pytest.mark.parametrize("timeout", [False, True], ids=["no_cost_in_answer", "client_timeout"])
def test_hole_a_turn_with_no_stated_cost_is_synced_as_zero(timeout) -> None:
    account = LaggingSpend(timeout)
    p = OpenRouterProvisioner("prov-key", 50_000_000, transport=httpx.MockTransport(account.handler),
                              run_tag="t1", settle_s=1.0, sleep=lambda s: None)
    meter = Meter(p, p.create_key(7, 1_000_000, spec_id="pm"))
    mind = build_provider(spec(), meter=meter)
    try:
        mind.complete(request())
    except httpx.TimeoutException:
        pass                                    # native.wake records provider_error and goes on
    [usage] = p.usage()
    assert usage.usd_micros_total == 250_000, (
        f"the key cost $0.25 at the provider; the sync would post {usage.usd_micros_total} µ$")
