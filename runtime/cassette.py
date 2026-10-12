"""The cassette file: what a run leaves behind (R-4a, ADR-032 (7) + amendment).

One JSON file per run, ``*.cassette.json``: the run's record (the outcome ``fund-runtime
backtest`` prints), with every wake's exchanges (``request_sha256`` and usage; see
:class:`runtime.native.Exchange`). R-4b reads it back to replay the run at $0.

* **Deterministic.** The text is a pure function of the outcome: sorted keys, compact
  separators, ASCII, no clock, no randomness. Equal runs give equal bytes **unless a mind was
  handed a minted key**: the exchange hash is of the unredacted request (below), and a key is
  fresh randomness, so the hashes after it differ run to run while the redacted text does not.
* **Redacted.** Every key in the form physics mints is replaced before the file is
  written, and the number replaced is stored (``redactions``). The hash in an exchange
  is of the *unredacted* request, so a replay that meets a minted key diverges instead of
  matching by luck (B-047). A key a mind re-encodes is in-world data this cannot see (Art. 8).
* **Careful with the disk.** The file is created exclusively (never overwritten), with mode
  0600, and the file itself is never a symlink (``O_NOFOLLOW`` looks at the last component
  only: a symlinked *directory* is the operator's choice). A refusal leaves no file behind.
  It is gitignored (B-000i).

Standard library only: this module imports nothing from physics or the conductor.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.providers import CompletionRequest

#: How :func:`request_sha256` serialises. Any change to it, to the request models in
#: :mod:`runtime.providers`, or to the tool list a request carries is a new format: bump this
#: and ``CASSETTE_VERSION`` together. (It lives here, not in ``providers``, because that
#: module is a script's only non-stdlib import and is pinned to pydantic + typing.)
HASH_FORMAT = "sha256/json-sorted-compact-ascii/1"
#: Bump with ``HASH_FORMAT`` and with any change to the shape of the outcome.
CASSETTE_VERSION = 1
SUFFIX = ".cassette.json"
#: ``app.registry.security``: ``API_KEY_PREFIX`` + ``secrets.token_urlsafe(32)``.
_MINTED_KEY = re.compile(r"fk_[A-Za-z0-9_-]+")
_REDACTED = "fk_<redacted>"


class CassetteError(Exception):
    """The cassette cannot be written; nothing was left behind."""


def request_sha256(request: CompletionRequest) -> str:
    """The digest that names a request: sha256 of its sorted, compact, ASCII JSON."""
    text = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def redact_count(text: str) -> tuple[str, int]:
    """``text`` with every minted key replaced, and how many were.

    A record can hold one: a management mind's ``register_agent`` result carries the new
    agent's key, and the transcript keeps tool results as they came (audit c27 BLOCK 1).
    JSON escapes none of a key's characters, so the serialized text is searched whole: one
    pass covers object keys, values and JSON nested inside a string, and valid JSON stays
    valid JSON.
    """
    return _MINTED_KEY.subn(_REDACTED, text)


def redact(text: str) -> str:
    """:func:`redact_count` without the count."""
    return redact_count(text)[0]


def dumps(outcome: Mapping[str, Any]) -> tuple[str, int]:
    """``(text, redactions)``: the cassette document for ``outcome``.

    Raises ``TypeError``/``ValueError`` if ``outcome`` is not plain JSON (NaN included).
    """
    body, redactions = redact_count(json.dumps(
        outcome, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
    # Assembled as text so the count describes exactly the text that was redacted.
    return (f'{{"cassette_version":{CASSETTE_VERSION},"hash_format":{json.dumps(HASH_FORMAT)},'
            f'"outcome":{body},"redactions":{redactions}}}'), redactions


def check_path(path: Path) -> Path:
    """``path`` if a cassette could be written there now, else :class:`CassetteError`."""
    if not path.name.endswith(SUFFIX) or path.name == SUFFIX:
        raise CassetteError(f"a cassette path ends in {SUFFIX}")
    if not path.parent.is_dir():
        raise CassetteError(f"{path.parent} is not a directory")
    if os.path.lexists(path):  # a dangling symlink exists
        raise CassetteError(f"{path} exists: a cassette is never overwritten")
    return path


def write(path: Path, outcome: Mapping[str, Any]) -> int:
    """Write the cassette for ``outcome`` to ``path``; return how many keys were redacted."""
    check_path(path)
    text, redactions = dumps(outcome)  # serialise first: a bad outcome creates no file
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise CassetteError(f"cannot create {path}: {exc.strerror}") from exc
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(text)
    except BaseException as exc:  # an interrupt too: no partial file is left either way
        path.unlink(missing_ok=True)  # we created it exclusively just now (by path, not inode)
        if isinstance(exc, OSError):
            raise CassetteError(f"cannot write {path}: {exc.strerror}") from exc
        raise
    return redactions
