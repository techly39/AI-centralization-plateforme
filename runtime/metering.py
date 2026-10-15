"""Metering v1, the Runtime half (R-6a, ADR-041): a fake provisioner and the cost sync.

The provisioner is where money is really spent: it mints a key per agent with a
spending limit and knows what each key has cost. Physics never sees a key; it
sees a ``key_ref`` label and the key's cumulative total, posted here by
:func:`sync_costs` as the Runtime's identity (``POST /metering/usage``). A
provisioner is anything with ``usage()``; the only one built is
:class:`FakeProvisioner`, which holds no secret and touches no network. A real
one (OpenRouter) is R-6b/R-8 work and needs a cap (Q-0001).

Boundary law: this module reaches physics only through :class:`FundClient`.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Protocol

from mcp_server.client import FundAPIError, FundClient
from runtime.providers import CompletionRequest, CompletionResponse, Usage
from runtime.scripted import Script

#: Copies of ``app.limits`` (the Runtime never imports the App); a test pins them equal.
MAX_METERED_USD_MICROS = 10**12
KEY_REF_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"

#: The fake provider's price, micro-dollars a token ($3 in / $15 out per million tokens), on
#: tokens = ceil(characters / 4) of the request's and the reply's canonical JSON (ADR-044).
FAKE_IN_MICROS_PER_TOKEN = 3
FAKE_OUT_MICROS_PER_TOKEN = 15

#: The statuses that mean "this key's post was refused, the others may go on":
#: unknown agent, a key bound to another agent or a total that went down, a body
#: the schema refused or a physics identity as the subject.
_PER_KEY_REFUSALS = frozenset({404, 409, 422})


class LimitExceeded(Exception):
    """A charge would take a key past its spending limit (an OpenRouter credit limit)."""


@dataclass(frozen=True)
class KeyUsage:
    """What one provisioned key has cost so far, in total, in integer micro-dollars."""

    key_ref: str
    agent_id: int
    usd_micros_total: int


class Provisioner(Protocol):
    def usage(self) -> list[KeyUsage]: ...


class FakeProvisioner:
    """Keys and spend, in memory. Deterministic: ``fake-0001``, ``fake-0002``, …"""

    def __init__(self) -> None:
        self._keys: dict[str, tuple[int, int]] = {}    # key_ref -> (agent_id, limit)
        self._spent: dict[str, int] = {}
        self._charges: dict[str, int] = {}

    def create_key(self, agent_id: int, limit_usd_micros: int) -> str:
        if type(limit_usd_micros) is not int or not 0 <= limit_usd_micros <= MAX_METERED_USD_MICROS:
            raise ValueError(
                f"a key's limit is an int of micro-dollars in 0..{MAX_METERED_USD_MICROS}")
        key_ref = f"fake-{len(self._keys) + 1:04d}"
        if not re.fullmatch(KEY_REF_PATTERN, key_ref):
            raise ValueError("the key's label is not one physics accepts")
        self._keys[key_ref] = (agent_id, limit_usd_micros)
        self._spent[key_ref] = 0
        self._charges[key_ref] = 0
        return key_ref

    def limit(self, key_ref: str) -> int:
        return self._keys[key_ref][1]

    def agent_of(self, key_ref: str) -> int:
        return self._keys[key_ref][0]

    def charges(self, key_ref: str) -> int:
        """How many accepted charges the key has had (one per model turn of a fake mind)."""
        return self._charges[key_ref]

    def charge(self, key_ref: str, usd_micros: int) -> None:
        """Spend on a key. Refuses an unknown key, a bad amount, or a charge past the limit."""
        if key_ref not in self._keys:
            raise KeyError(key_ref)
        if type(usd_micros) is not int or usd_micros < 0:
            raise ValueError("a charge is a non-negative int of micro-dollars")
        if self._spent[key_ref] + usd_micros > self._keys[key_ref][1]:
            raise LimitExceeded(key_ref)
        self._spent[key_ref] += usd_micros
        self._charges[key_ref] += 1

    def usage(self) -> list[KeyUsage]:
        return [
            KeyUsage(key_ref, self._keys[key_ref][0], self._spent[key_ref])
            for key_ref in sorted(self._keys)
        ]


def usd_to_micros_floor(usd: float) -> int:
    """Whole micro-dollars in ``usd``, rounded down, exactly (decimal, not binary float)."""
    return int((Decimal(repr(float(usd))) * 1_000_000).to_integral_value(rounding=ROUND_FLOOR))


@dataclass(frozen=True)
class Meter:
    """A mind's own key at the provisioner: the only way a metered mind spends."""

    provisioner: FakeProvisioner
    key_ref: str

    def charge(self, usd_micros: int) -> None:
        self.provisioner.charge(self.key_ref, usd_micros)


def _tokens(value: object) -> int:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)
    return math.ceil(len(text) / 4)


def fake_charge(request: CompletionRequest, response: CompletionResponse) -> tuple[int, int, int]:
    """``(tokens_in, tokens_out, micro-dollars)`` the fake provider bills for one model turn:
    a pure function of the request and the reply."""
    tokens_in = _tokens(request.model_dump(mode="json"))
    tokens_out = _tokens(response.model_dump(mode="json"))
    return (tokens_in, tokens_out,
            FAKE_IN_MICROS_PER_TOKEN * tokens_in + FAKE_OUT_MICROS_PER_TOKEN * tokens_out)


class FakeMeteredProvider:
    """The one class the name ``fake-metered`` builds (:mod:`runtime.registry`): a deterministic
    script that is billed, per model turn, to its own key. No model, no network. A charge past
    the key's limit raises :class:`LimitExceeded` before any reply is returned, so nothing is
    ever spent past a limit and the wake ends ``error/provider_error:LimitExceeded``."""

    name = "fake-metered"
    spends_money = True

    def __init__(self, script: Script, meter: Meter) -> None:
        self._script = script
        self._meter = meter

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = self._script(request)
        tokens_in, tokens_out, micros = fake_charge(request, response)
        self._meter.charge(micros)
        return response.model_copy(update={"usage": Usage(
            input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=micros / 1e6)})


@dataclass(frozen=True)
class SyncReport:
    posted: int = 0
    unchanged: int = 0
    #: ``(key_ref, status, detail)`` for each key physics refused; the rest still went.
    refused: list[tuple[str, int, str]] = field(default_factory=list)
    #: A HALT stopped the sync; the keys after it were not posted (the next sync catches up).
    halted: bool = False


async def sync_costs(provisioner: Provisioner, client: FundClient) -> SyncReport:
    """Post every key's cumulative total to physics, in ``key_ref`` order.

    ``client`` must act as the Runtime's identity. A 423 (HALT) stops the sync
    with ``halted``; a 401/403 (the wrong key) raises, because every later post
    would fail the same way; a 404/409/422 is recorded and the next key goes on,
    so one bad key never hides other agents' dollars.
    """
    posted = unchanged = 0
    refused: list[tuple[str, int, str]] = []
    for usage in provisioner.usage():
        try:
            answer = await client.post(
                "/metering/usage",
                {
                    "agent_id": usage.agent_id,
                    "key_ref": usage.key_ref,
                    "usd_micros_total": usage.usd_micros_total,
                },
            )
        except FundAPIError as exc:
            if exc.status_code == 423:
                return SyncReport(posted, unchanged, refused, halted=True)
            if exc.status_code in _PER_KEY_REFUSALS:
                refused.append((usage.key_ref, exc.status_code, exc.detail))
                continue
            raise
        if answer["recorded"]:
            posted += 1
        else:
            unchanged += 1
    return SyncReport(posted, unchanged, refused)
