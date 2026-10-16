"""Red-team 0023 (cycle 42, ADR-047) — MEDIUM: a spend the provider does not state counts as $0.

Severity: **medium** — the monthly accounting fails open on an absent field: a real advantage
over the cap when the provider's answer changes shape, without breaking it while the API keeps
today's fields.

``usd_to_micros_ceil(None) == 0`` by design (an absent turn cost). ``month_committed`` reuses it
for a disabled firm key's ``usage_monthly``: a listing row that does not carry the field (an API
version that renames it, a partial row, ``null``) makes a key that spent $45 this month count
**$0**, and a new run mints $45 more under a $50 cap. Every other unreadable spend in the module
refuses (``OpenRouterError``) — this one is silently zero. A disabled key whose month spend is
unknown should count what it could have spent (its limit) or refuse the mint.

Hole tests are ``xfail(strict=True)``: they pass once the Builder fixes the physics.
"""

from __future__ import annotations

import httpx
import pytest

from runtime.openrouter import OpenRouterError, OpenRouterProvisioner, OverCap
from tests.test_runtime_openrouter import Account

CAP = 50_000_000


def _prov(account: Account) -> OpenRouterProvisioner:
    return OpenRouterProvisioner("prov-key", CAP, transport=httpx.MockTransport(account.handler),
                                 run_tag="t1", settle_s=0, sleep=lambda s: None)


@pytest.mark.xfail(strict=True, reason=(
    "MEDIUM red-team 0023: a disabled firm key whose usage_monthly is absent/null counts $0; "
    "a key that spent $45 lets a new run mint $45 more under a $50 cap"))
@pytest.mark.parametrize("shape", ["absent", "null"])
def test_hole_a_disabled_key_with_no_stated_month_spend_counts_zero(shape) -> None:
    account = Account()
    digest = account.add("firm-earlier-run-pm", limit=45.0, usage=45.0, disabled=True)
    if shape == "absent":
        del account.keys[digest]["usage_monthly"]
    else:
        account.keys[digest]["usage_monthly"] = None
    p = _prov(account)
    try:
        p.create_key(1, 45_000_000, spec_id="pm")
    except (OverCap, OpenRouterError):
        return  # fails closed: the law holds
    pytest.fail(f"minted $45 beside a key that spent $45 (counted {p.month_committed() - 45_000_000} µ$)")
