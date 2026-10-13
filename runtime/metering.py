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

from dataclasses import dataclass, field
from typing import Protocol

from mcp_server.client import FundAPIError, FundClient

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

    def create_key(self, agent_id: int, limit_usd_micros: int) -> str:
        if type(limit_usd_micros) is not int or limit_usd_micros < 0:
            raise ValueError("a key's limit is a non-negative int of micro-dollars")
        key_ref = f"fake-{len(self._keys) + 1:04d}"
        self._keys[key_ref] = (agent_id, limit_usd_micros)
        self._spent[key_ref] = 0
        return key_ref

    def charge(self, key_ref: str, usd_micros: int) -> None:
        """Spend on a key. Refuses an unknown key, a bad amount, or a charge past the limit."""
        if key_ref not in self._keys:
            raise KeyError(key_ref)
        if type(usd_micros) is not int or usd_micros < 0:
            raise ValueError("a charge is a non-negative int of micro-dollars")
        if self._spent[key_ref] + usd_micros > self._keys[key_ref][1]:
            raise LimitExceeded(key_ref)
        self._spent[key_ref] += usd_micros

    def usage(self) -> list[KeyUsage]:
        return [
            KeyUsage(key_ref, self._keys[key_ref][0], self._spent[key_ref])
            for key_ref in sorted(self._keys)
        ]


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
