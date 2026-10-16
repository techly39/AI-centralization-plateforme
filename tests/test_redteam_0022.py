"""Red-team 0022 (cycle 42, ADR-047) — HIGH: two runs minting at once both pass the monthly check.

Severity: **high** — breaks the Human's monthly cap.

``OpenRouterProvisioner.create_key`` reads the account (``month_committed``), then mints. Nothing
holds the month between the read and the mint: no lock across processes, no reservation, and not
even the keys this object already minted are counted locally (it trusts the provider's listing to
already show them). Two runs started together (two terminals, a retried loop, an acceptance script
beside a backtest) each read "0 committed", each mint $30 under a $50 cap, and the firm's month
holds $60 of spendable limits. ADR-047 names this as a known limit and says "every key's hard
limit at the provider still bounds each one" — true, but nothing bounds their *sum*, which is the
cap. Offline: one fake account, two provisioners, a barrier that makes both list before either mints.

Hole tests are ``xfail(strict=True)``: they pass once the Builder fixes the physics.
"""

from __future__ import annotations

import threading

import httpx
import pytest

from runtime.openrouter import OpenRouterProvisioner, OverCap
from tests.test_runtime_openrouter import Account

CAP = 50_000_000


class RacingAccount(Account):
    """The account; the first two mints wait for each other, so both runs have finished reading
    the month before either key exists (two runs started at the same moment)."""

    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2, timeout=5)
        self.mints = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/keys" and request.method == "POST":
            with self.lock:
                self.mints += 1
                wait = self.mints <= 2
            if wait:
                self.barrier.wait()
        with self.lock:
            return super().handler(request)


def _prov(account: Account, tag: str) -> OpenRouterProvisioner:
    return OpenRouterProvisioner("prov-key", CAP, transport=httpx.MockTransport(account.handler),
                                 run_tag=tag, settle_s=0, sleep=lambda s: None)


@pytest.mark.xfail(strict=True, reason=(
    "HIGH red-team 0022: two runs read the month before either mints; both mint $30 under a "
    "$50 cap (no lock or reservation across runs)"))
def test_hole_two_concurrent_runs_each_mint_past_the_cap_together() -> None:
    account = RacingAccount()
    outcomes: dict[str, str] = {}

    def run(tag: str) -> None:
        try:
            _prov(account, tag).create_key(1, 30_000_000, spec_id="pm")
            outcomes[tag] = "minted"
        except OverCap:
            outcomes[tag] = "over_cap"

    threads = [threading.Thread(target=run, args=(t,)) for t in ("ra", "rb")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    firm_limits = sum(k["limit"] for k in account.keys.values()
                      if k["name"].startswith("firm-") and not k["disabled"])
    # The law (ADR-047 §4): Σ firm limits this month <= cap. Here it is $60 against $50.
    assert firm_limits * 1e6 <= CAP, (outcomes, firm_limits)


class LaggingAccount(Account):
    """The account's key listing lags: a key just minted is not listed yet (eventual consistency)."""

    def __init__(self) -> None:
        super().__init__()
        self.listed = dict(self.keys)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/keys" and request.method == "GET":
            offset = int(request.url.params.get("offset", 0))
            return httpx.Response(200, json={"data": list(self.listed.values())[offset:offset + 2]})
        return super().handler(request)


@pytest.mark.xfail(strict=True, reason=(
    "HIGH red-team 0022: one provisioner does not count the keys it minted itself; a listing "
    "that lags lets one run mint 3 x $20 under a $50 cap"))
def test_hole_one_run_does_not_count_its_own_keys_when_the_listing_lags() -> None:
    account = LaggingAccount()
    p = _prov(account, "rc")
    minted = 0
    for i in range(3):
        try:
            p.create_key(i + 1, 20_000_000, spec_id=f"m{i}")
            minted += 1
        except OverCap:
            break
    assert minted * 20_000_000 <= CAP, f"{minted} keys of $20 minted under a $50 cap"
