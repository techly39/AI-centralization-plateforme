"""The addressing vocabulary of the bus: how a message says who it is for.

``messages.to_ref`` holds a union — one agent, one pod, or everyone (TRD §5).
Bare ids would be ambiguous (``"7"`` could be agent 7 or pod 7), so the *kind* is
written into the string:

    ``agent:7``      one named agent
    ``pod:2``        every member of pod 2
    ``broadcast``    the whole firm

That format is a wire contract: agents type it into ``POST /messages`` and read
it back out of ``GET /messages``, the UI will render it in Phase 4, and it is
stored in the database. Parsing and formatting therefore live in exactly one
module, here, so the format can never drift between producer and consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.bus.errors import InvalidRecipientError
from app.limits import MAX_ID

#: The literal ``to_ref`` value meaning "everyone in the firm".
BROADCAST = "broadcast"

_AGENT_PREFIX = "agent:"
_POD_PREFIX = "pod:"

RecipientKind = Literal["agent", "pod", "broadcast"]


def agent_ref(agent_id: int) -> str:
    return f"{_AGENT_PREFIX}{agent_id}"


def pod_ref(pod_id: int) -> str:
    return f"{_POD_PREFIX}{pod_id}"


@dataclass(frozen=True, slots=True)
class Recipient:
    """A parsed ``to_ref``: what kind of audience, and which one."""

    kind: RecipientKind
    #: The agent id or pod id. ``None`` for a broadcast, which names no target.
    id: int | None = None

    @property
    def ref(self) -> str:
        """Back to the stored string form."""
        if self.kind == "agent":
            return agent_ref(int(self.id))  # type: ignore[arg-type]
        if self.kind == "pod":
            return pod_ref(int(self.id))  # type: ignore[arg-type]
        return BROADCAST

    def __str__(self) -> str:  # pragma: no cover - convenience for logs
        return self.ref


def parse_ref(raw: str) -> Recipient:
    """Parse an address written by an agent.

    Raises:
        InvalidRecipientError: the string is not one of the three legal forms.
            The message names all three, because the caller is usually an LLM
            that will retry and deserves to be told the grammar rather than
            guess it.
    """
    value = (raw or "").strip()
    if not value:
        raise InvalidRecipientError(
            "recipient must not be empty — use 'agent:<id>', 'pod:<id>', "
            "or 'broadcast'"
        )

    if value.lower() == BROADCAST:
        return Recipient(kind="broadcast")

    for prefix, kind in ((_AGENT_PREFIX, "agent"), (_POD_PREFIX, "pod")):
        if value.lower().startswith(prefix):
            suffix = value[len(prefix):]
            try:
                target_id = int(suffix)
            except ValueError:
                raise InvalidRecipientError(
                    f"{prefix}<id> needs a whole number, got {suffix!r}"
                ) from None
            if not 0 < target_id <= MAX_ID:
                raise InvalidRecipientError(
                    f"{prefix}<id> must be 1..{MAX_ID}, got {target_id}"
                )
            return Recipient(kind=kind, id=target_id)  # type: ignore[arg-type]

    raise InvalidRecipientError(
        f"unrecognised recipient {value!r} — use 'agent:<id>', 'pod:<id>', "
        "or 'broadcast'"
    )
