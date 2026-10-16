"""The cassette file: what a run leaves behind, and how it is read back (R-4a/R-4b, ADR-037, ADR-038,
M-002/ADR-045).

One JSON file per run, ``*.cassette.json``. Version 2 (M-002) is a **proof object**: one file is
enough to re-live the run and to prove its ledger identical. It carries

* the run's record (``outcome``: the outcome ``fund-runtime backtest`` prints, with every wake's
  exchanges: ``request_sha256`` and usage; see :class:`runtime.native.Exchange`);
* the run's ``parameters`` (steps, days per step, tool-call budget, workflow input);
* the ``specs`` the run's minds were built from, each with its digest;
* the ``world`` recipe the run was hosted in, and the ``ledger`` it left (both ``null`` for a
  run on an App the operator built: it cannot be verified, only replayed).

* **Deterministic.** The text is a pure function of its parts: sorted keys, compact
  separators, ASCII, no clock, no randomness. Equal runs give equal bytes **unless a mind was
  handed a minted key**: the exchange hash is of the unredacted request (below), and a key is
  fresh randomness, so the hashes after it differ run to run while the redacted text does not.
* **Redacted.** Every key in the form physics mints is replaced before the file is
  written, and the number replaced is stored (``redactions``). The hash in an exchange
  is of the *unredacted* request, so a replay that meets a minted key diverges instead of
  matching by luck (B-047). A key a mind re-encodes is in-world data this cannot see (Art. 8).
  The world key is never in the file: it comes from the environment (red-team 0010).
* **Bounded.** A file larger than :data:`MAX_CASSETTE_BYTES` is neither written nor read.
* **Careful with the disk.** The file is created exclusively (never overwritten), with mode
  0600, and the file itself is never a symlink (``O_NOFOLLOW`` looks at the last component
  only: a symlinked *directory* is the operator's choice). A refusal leaves no file behind.
  It is gitignored (B-000i). It holds the world's generating law (in the ledger's
  ``run_started`` row): an operator file, never to be handed to a mind.
* **One version.** Version 1 (outcome only) is refused by name: it holds nothing that proves
  anything (ADR-045).

Standard library only: this module imports nothing from physics or the conductor.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.providers import CompletionRequest

#: How :func:`request_sha256` serialises. Any change to it, to the request models in
#: :mod:`runtime.providers`, or to the tool list a request carries is a new format: bump this
#: and ``CASSETTE_VERSION`` together. (It lives here, not in ``providers``, because that
#: module is a script's only non-stdlib import and is pinned to pydantic + typing.)
HASH_FORMAT = "sha256/json-sorted-compact-ascii/1"
#: Bump with ``HASH_FORMAT`` and with any change to the shape of the document.
CASSETTE_VERSION = 2
SUFFIX = ".cassette.json"
#: A cassette bigger than this is neither written nor read (64 MiB).
MAX_CASSETTE_BYTES = 64 * 2**20
#: The ledger block's format: ``rows`` are ``app.ledger.compare.Row`` as JSON arrays.
LEDGER_FORMAT = "fund-ledger-rows/1"
#: Bounds on the run parameters: the conductor's own limits, pinned to these by a test (this
#: module imports nothing from it).
STEPS_RANGE = (1, 3660)
DAYS_PER_STEP_RANGE = (1, 366)
MAX_TOOL_CALLS_RANGE = (0, 1024)
#: ``app.registry.security``: ``API_KEY_PREFIX`` + ``secrets.token_urlsafe(32)``.
_MINTED_KEY = re.compile(r"fk_[A-Za-z0-9_-]+")
_REDACTED = "fk_<redacted>"
_SHA = re.compile(r"[0-9a-f]{64}")
_KEYS = frozenset({"cassette_version", "hash_format", "ledger", "outcome", "parameters",
                   "redactions", "specs", "world"})


class CassetteError(Exception):
    """The cassette cannot be written (nothing was left behind) or cannot be read (R-4b)."""


@dataclass(frozen=True)
class Cassette:
    """A validated cassette: the six parts of a version-2 document."""
    outcome: dict[str, Any]
    redactions: int
    parameters: dict[str, Any]
    #: ``[{"sha256": ..., "spec": {...}}, ...]``; see :func:`runtime.spec.specs_from_cassette`.
    specs: list[dict[str, Any]]
    #: ``{"recipe": {...}}``, or ``None`` for a run on an operator-hosted App.
    world: dict[str, Any] | None
    #: ``{"ledger_format": LEDGER_FORMAT, "rows": [...]}``, or ``None`` as ``world``.
    ledger: dict[str, Any] | None


def _canonical(doc: Any) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def request_sha256(request: CompletionRequest) -> str:
    """The digest that names a request: sha256 of its sorted, compact, ASCII JSON."""
    return hashlib.sha256(_canonical(request.model_dump(mode="json")).encode("ascii")).hexdigest()


def spec_sha256(spec: Mapping[str, Any]) -> str:
    """The digest that names a spec: sha256 of its sorted, compact, ASCII JSON."""
    return hashlib.sha256(_canonical(spec).encode("ascii")).hexdigest()


def tools_sha256(tools: Sequence[Any]) -> str:
    """The digest that names the tools a wake's requests carried (pydantic ``ToolSpec``s, in
    the order the request holds them): so a changed tool surface reads as a surface change."""
    return hashlib.sha256(_canonical([t.model_dump(mode="json") for t in tools]).encode("ascii")
                          ).hexdigest()


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


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise CassetteError("a key is used twice in one object")
    return dict(pairs)


def _refuse_constant(name: str) -> Any:
    raise CassetteError(f"{name} is not JSON")


#: A data package's name (``runtime.packages``); the cassette records it, the conductor checks it.
_PACKAGE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


def _in_range(value: Any, bounds: tuple[int, int]) -> bool:
    return type(value) is int and bounds[0] <= value <= bounds[1]


def _validate(doc: Any) -> Cassette:
    """The parts of a parsed version-2 document, else :class:`CassetteError`."""
    if type(doc) is not dict or set(doc) != _KEYS:
        raise CassetteError(f"a cassette has exactly these top-level keys: {sorted(_KEYS)}")
    if doc["hash_format"] != HASH_FORMAT:
        raise CassetteError("a different hash format")
    redactions, outcome = doc["redactions"], doc["outcome"]
    if type(redactions) is not int or redactions < 0 or type(outcome) is not dict:
        raise CassetteError("redactions is a non-negative int and the outcome an object")
    params = doc["parameters"]
    if (type(params) is not dict
            or set(params) - {"package"} != {"steps", "days_per_step", "max_tool_calls",
                                              "workflow_input"}
            or ("package" in params and not (type(params["package"]) is str
                                             and _PACKAGE.fullmatch(params["package"])))
            or not _in_range(params["steps"], STEPS_RANGE)
            or not _in_range(params["days_per_step"], DAYS_PER_STEP_RANGE)
            or not _in_range(params["max_tool_calls"], MAX_TOOL_CALLS_RANGE)
            or type(params["workflow_input"]) is not dict):
        raise CassetteError("parameters are steps, days_per_step and max_tool_calls (ints in "
                            "range) and a workflow_input object")
    specs = doc["specs"]
    if type(specs) is not list or not all(
            type(e) is dict and set(e) == {"sha256", "spec"} and type(e["spec"]) is dict
            and type(e["sha256"]) is str and _SHA.fullmatch(e["sha256"]) for e in specs):
        raise CassetteError("specs is a list of {sha256, spec} entries")
    world, ledger = doc["world"], doc["ledger"]
    if world is not None and not (type(world) is dict and set(world) == {"recipe"}
                                  and type(world["recipe"]) is dict):
        raise CassetteError("world is null or {recipe: object}")
    if ledger is not None and not (
            type(ledger) is dict and set(ledger) == {"ledger_format", "rows"}
            and ledger["ledger_format"] == LEDGER_FORMAT and type(ledger["rows"]) is list
            and all(type(r) is list for r in ledger["rows"])):
        raise CassetteError(f"ledger is null or {{ledger_format: {LEDGER_FORMAT}, rows: [[...]]}}")
    return Cassette(outcome, redactions, params, specs, world, ledger)


def dumps(outcome: Mapping[str, Any], *, parameters: Mapping[str, Any],
          specs: Sequence[Mapping[str, Any]], world: Mapping[str, Any] | None = None,
          ledger: Mapping[str, Any] | None = None) -> tuple[str, int]:
    """``(text, redactions)``: the cassette document for a run.

    ``specs`` are the run's spec bodies (``AgentSpec.model_dump(mode="json")``); the entries are
    sorted by id and digested here. Raises ``TypeError``/``ValueError`` if a part is not plain
    JSON (NaN included), :class:`CassetteError` if the parts are not a cassette or if redaction
    would make two keys of one object equal.
    """
    entries = sorted(({"sha256": spec_sha256(s), "spec": dict(s)} for s in specs),
                     key=lambda e: str(e["spec"].get("id")))
    body, redactions = redact_count(_canonical({
        "cassette_version": CASSETTE_VERSION, "hash_format": HASH_FORMAT, "ledger": ledger,
        "outcome": outcome, "parameters": parameters, "specs": entries, "world": world,
        "redactions": 0}))
    try:
        doc = json.loads(body, object_pairs_hook=_unique_pairs, parse_constant=_refuse_constant)
    except RecursionError as exc:
        raise CassetteError("the cassette is nested too deep") from exc
    doc["redactions"] = redactions
    _validate(doc)
    return _canonical(doc), redactions


def read(path: Path) -> Cassette:
    """The :class:`Cassette` in a file written by :func:`write`, else :class:`CassetteError`
    (R-4b). The file is untrusted input, so only the canonical v2 document is accepted: the file
    itself is not a symlink, is a regular file of at most :data:`MAX_CASSETTE_BYTES`, is ASCII,
    repeats no key, holds no NaN/Infinity, carries exactly the eight top-level keys with this
    version and hash format and well-formed parts, and its text equals what :func:`dumps` would
    have produced for its own parts. Anything else (pretty-printed, reordered, version 1) is
    refused. Every input gives a :class:`Cassette` or a :class:`CassetteError`, nothing else.
    """
    try:
        # O_NONBLOCK: opening a FIFO would otherwise wait for a writer, forever (audit c32 WARN 1);
        # the regular-file check below refuses it. It does not change how a regular file reads.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise CassetteError(f"cannot open {path}: {exc.strerror}") from exc
    try:
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise CassetteError(f"{path} is not a regular file")
            if info.st_size > MAX_CASSETTE_BYTES:
                raise CassetteError(f"{path} is over {MAX_CASSETTE_BYTES} bytes")
            raw = f.read(MAX_CASSETTE_BYTES + 1)  # a file that grows while we read is bounded too
    except OSError as exc:
        raise CassetteError(f"cannot read {path}: {exc.strerror}") from exc
    if len(raw) > MAX_CASSETTE_BYTES:
        raise CassetteError(f"{path} is over {MAX_CASSETTE_BYTES} bytes")
    try:
        text = raw.decode("ascii")
        doc = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_refuse_constant)
    except CassetteError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise CassetteError(f"{path} is not a cassette ({type(exc).__name__})") from exc
    version = doc.get("cassette_version") if type(doc) is dict else None
    if type(version) is int and version == 1:
        raise CassetteError(
            "cassette version 1 is not read since M-002 (ADR-045): it carries no run parameters, "
            "specs, world or ledger, so it proves nothing; re-record the run")
    if type(version) is not int or version != CASSETTE_VERSION:
        raise CassetteError(f"this reader reads cassette version {CASSETTE_VERSION} only")
    parts = _validate(doc)
    try:
        canonical = _canonical(doc)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CassetteError("the cassette is not plain JSON") from exc
    if text != canonical:
        raise CassetteError("the file is not in the canonical form write() produces")
    return parts


def check_path(path: Path) -> Path:
    """``path`` if a cassette could be written there now, else :class:`CassetteError`."""
    if not path.name.endswith(SUFFIX) or path.name == SUFFIX:
        raise CassetteError(f"a cassette path ends in {SUFFIX}")
    if not path.parent.is_dir():
        raise CassetteError(f"{path.parent} is not a directory")
    if os.path.lexists(path):  # a dangling symlink exists
        raise CassetteError(f"{path} exists: a cassette is never overwritten")
    return path


def write(path: Path, outcome: Mapping[str, Any], *, parameters: Mapping[str, Any],
          specs: Sequence[Mapping[str, Any]], world: Mapping[str, Any] | None = None,
          ledger: Mapping[str, Any] | None = None) -> int:
    """Write the cassette for a run to ``path``; return how many keys were redacted."""
    check_path(path)
    # Serialise first: a bad or oversize document creates no file.
    text, redactions = dumps(outcome, parameters=parameters, specs=specs, world=world,
                             ledger=ledger)
    if len(text) > MAX_CASSETTE_BYTES:  # ASCII: characters are bytes
        raise CassetteError(f"the cassette would be {len(text)} bytes: over {MAX_CASSETTE_BYTES}")
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
