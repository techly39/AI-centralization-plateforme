"""Red-team 0028 (cycle 42, ADR-047) — LOW: ``close()`` disables whatever key the mint answer named.

Severity: **low** — needs the provider to answer a mint with a hash that is not the key it made (a
provider bug, a proxy that mixes answers); but the harm is a hard limit of the Human's: ADR-047 §4
"keys whose name does not start with ``firm-`` are never changed".

``create_key`` checks that the answer holds a secret and a hex ``hash``, not that the hash names a
``firm-`` key, nor the name it asked for (``data.name`` is never read). ``close()`` then PATCHes
``/keys/<that hash>`` ``{"disabled": true}`` and ``usage()`` reads it as the agent's spend: the
Human's own key is disabled (and its lifetime spend is posted as a firm agent's cost). A check of
``data.name == name`` at mint, and of the key's name before every PATCH, closes it.

Fixed in cycle 43; the tests now guard the fix.
"""

from __future__ import annotations

import json

import httpx

from runtime.openrouter import OpenRouterError, OpenRouterProvisioner
from tests.test_runtime_openrouter import Account


class CrossedAccount(Account):
    """The mint answer names the Human's key (hash and row) instead of the key it made."""

    def __init__(self) -> None:
        super().__init__()
        self.human = next(iter(self.keys))
        self.patched_humans: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/keys" and request.method == "POST":
            made = json.loads(super().handler(request).content)
            return httpx.Response(201, json={"data": self.keys[self.human], "key": made["key"]})
        if request.method == "PATCH" and path.removeprefix("/keys/") == self.human:
            self.patched_humans.append(self.human)
            self.keys[self.human]["disabled"] = True
            return httpx.Response(200, json={"data": self.keys[self.human]})
        return super().handler(request)


def test_hole_a_crossed_mint_answer_gets_the_humans_key_disabled() -> None:
    account = CrossedAccount()
    p = OpenRouterProvisioner("prov-key", 50_000_000, transport=httpx.MockTransport(account.handler),
                              run_tag="t1", settle_s=0, sleep=lambda s: None)
    try:
        p.create_key(1, 1_000_000, spec_id="pm")
    except OpenRouterError:
        return  # refused at mint: the law holds
    spend = p.usage()[0].usd_micros_total
    p.close()
    assert account.patched_humans == [], f"the Human's key was disabled; its {spend} µ$ read as the agent's"
