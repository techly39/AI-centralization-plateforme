"""Red-team 0024 (cycle 42, ADR-047) — MEDIUM: a key's hard limit is the provider's word, never checked.

Severity: **medium** — the Runtime keeps no limit of its own on a real key; the cap holds only
while the provider applies a field the Runtime never reads back.

1. ``create_key`` posts ``{"limit": L}`` and accepts the answer without looking at the limit the
   provider says the key has. An answer whose key has ``limit: null`` (the field ignored, renamed,
   or the key made unlimited) or a larger limit is taken as a key of limit ``L``: the run's
   ``_limits_fit`` and the report use the requested ``L`` while the real key is unbounded.
2. ``OpenRouterProvider.complete`` never compares what the key's own turns already billed
   (``billed``, the provider's per-turn ``usage.cost``) with the key's limit. ``FakeMeteredProvider``
   refuses a charge past the limit (``LimitExceeded``); the real one sends the next request anyway,
   so a key the provider fails to stop keeps spending real money past its budget.

Fixed in cycle 43; the tests now guard the fix.
"""

from __future__ import annotations

import json

import httpx
import pytest

from runtime.metering import Meter
from runtime.openrouter import OpenRouterError, OpenRouterProvisioner, OverCap
from runtime.registry import build_provider
from tests.test_runtime_openrouter import Account, chat, request, spec

CAP = 50_000_000


class IgnoringAccount(Account):
    """An account whose key endpoint ignores the requested limit: every minted key is unlimited."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        response = super().handler(request)
        path = request.url.path.removeprefix("/api/v1")
        if path == "/keys" and request.method == "POST":
            body = json.loads(response.content)
            self.keys[body["data"]["hash"]]["limit"] = None
            body["data"]["limit"] = None
            return httpx.Response(201, json=body)
        return response


def _prov(account: Account) -> OpenRouterProvisioner:
    return OpenRouterProvisioner("prov-key", CAP, transport=httpx.MockTransport(account.handler),
                                 run_tag="t1", settle_s=0, sleep=lambda s: None)


def test_hole_a_key_minted_without_its_limit_is_accepted() -> None:
    account = IgnoringAccount()
    p = _prov(account)
    try:
        key_ref = p.create_key(1, 1_000_000, spec_id="pm")
    except (OpenRouterError, OverCap):
        return  # refused: the law holds
    pytest.fail(f"accepted {key_ref} as a $1 key; the provider says its limit is "
                f"{next(k for k in account.keys.values() if k['name'] == 'firm-t1-pm')['limit']}")


def test_hole_a_mind_keeps_calling_after_its_turns_billed_past_its_limit() -> None:
    account = Account()   # like the test account, it does not stop a key at its limit
    p = _prov(account)
    meter = Meter(p, p.create_key(7, 1_000, spec_id="pm"))        # a $0.001 key
    mind = build_provider(spec(), meter=meter)
    account.answers += [chat("one", cost=0.002), chat("two", cost=0.002)]
    mind.complete(request())                                      # billed $0.002 > $0.001 limit
    try:
        mind.complete(request())
    except Exception:  # noqa: BLE001 - any refusal before the request is the law holding
        if len(account.chats) == 1:
            return
    pytest.fail(f"{len(account.chats)} requests sent; the key billed "
                f"{p.usage()[0].usd_micros_total} µ$ against a limit of {p.limit(meter.key_ref)}")
