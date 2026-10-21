"""The first real metered provider: OpenRouter (ADR-047).

Two parts, both over HTTPS to one fixed host (:data:`BASE_URL`), both with an injectable
``httpx`` transport so tests never touch the network:

* :class:`OpenRouterProvisioner` — holds the account's **provisioning key** (from the
  environment, :data:`PROVISIONING_KEY_ENV`) and mints **one key per agent**, named
  ``firm-<run>-<spec id>``, with a hard spending limit. Before any key is minted it does the
  **monthly accounting across runs** (ADR-047 §4): every ``firm-`` key on the account counts
  against the Human's cap — an enabled key its whole limit, a disabled key what it spent this
  month — and the new limit must fit beside them. Keys whose name does not start with ``firm-``
  (the Human's own) are never changed and never counted. After the run :meth:`close` disables
  every key it made; nothing is ever deleted, so the provider keeps the history.
  ``usage()`` is the meter :func:`runtime.metering.sync_costs` posts: what the provider says
  each key cost.
* :class:`OpenRouterProvider` — what the name ``openrouter`` builds (:mod:`runtime.registry`):
  one chat completion per model turn, with the mind's tools, the spec's model and the mind's
  own key. No retries (a retry spends twice). A wall-clock timeout bounds every call. The
  turn's cost is the provider's own ``usage.cost``; it is reported, never trusted as the meter.

A minted key lives only in this module's objects. It is never returned to a caller, printed or
written: records hold the ``key_ref`` (``or-`` + 16 hex digits of the key's public hash).

Boundary law: this module imports no ``app`` module.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import httpx

from runtime.governance import REPO_ROOT
from runtime.metering import MAX_METERED_USD_MICROS, KeyUsage, Meter
from runtime.providers import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ToolCall,
    Usage,
)

BASE_URL = "https://openrouter.ai/api/v1"
PROVISIONING_KEY_ENV = "FUND_OPENROUTER_PROVISIONING_KEY"
#: Every key the firm makes starts with this; nothing else on the account is the firm's.
FIRM_PREFIX = "firm-"
#: Seconds one model turn may take, end to end.
TURN_TIMEOUT_S = 120.0
#: How long ``usage()`` waits for the provider's per-key spend to catch up with the turns it billed.
SETTLE_S = 30.0
#: Most a model may write in one turn: a turn admitted under a key's limit stays a small turn.
MAX_TURN_TOKENS = 4096
#: A key's limit is hard (cycle 59): the provider finishes the turn that crosses a limit (a
#: real hire's key spent $0.200068 of $0.20), so no turn is sent whose worst case could cross
#: what the key has left. The worst case is priced from the provider's own model list; the
#: prompt is bounded by its bytes (a token is at least one byte), plus these tokens for each
#: message's framing and for the provider's own tool instructions.
MESSAGE_TOKENS = 16
TOOLS_TOKENS = 1024
#: Price fields (USD per token, or per request) that can raise a turn's cost: the most of each
#: group is taken, across every price tier the prompt could reach.
_PROMPT_PRICES = ("prompt", "input_cache_write", "input_cache_write_1h")
_WRITING_PRICES = ("completion", "internal_reasoning")
_REQUEST_PRICES = ("request",)
#: Fields a turn of this firm never buys (it sends no image, audio or web search) or that only
#: lower a cost. Any other field fails closed: a price the guard does not know is not bounded.
_UNBOUGHT_PRICES = frozenset({"input_cache_read", "web_search", "image", "input_image", "audio",
                              "input_audio", "input_audio_cache", "discount"})
#: Held from the month's count to the mint, so two runs never both fit in the same room under
#: the cap (red-team 0022). One per repo: every run of this firm passes through it.
MINT_LOCK = REPO_ROOT / ".openrouter-mint.lock"
#: How long a run waits for another run's mint before it gives up.
MINT_LOCK_WAIT_S = 60.0
#: An account read is asked this many times in all before it counts as unreadable; the
#: answers worth asking again (a timeout, too many requests, the provider's own failure).
ATTEMPTS = 3
PASSING = frozenset({408, 429, 500, 502, 503, 504})
#: The secret's shape, for the secret scan (:func:`holds_secret`).
SECRET_PATTERN = re.compile(r"sk-or-[A-Za-z0-9_-]{8,}")


class OpenRouterError(RuntimeError):
    """The provider refused or could not answer. ``status`` is the HTTP status (0: no answer)."""

    def __init__(self, what: str, status: int = 0) -> None:
        super().__init__(f"{what} (HTTP {status})" if status else what)
        self.status = status


class OverCap(RuntimeError):
    """Minting this key would take the firm's month past the Human's cap (ADR-047 §4)."""


def holds_secret(text: str) -> bool:
    """True if ``text`` holds anything shaped like an OpenRouter key (ADR-047 §5)."""
    return SECRET_PATTERN.search(text) is not None


def usd_to_micros_ceil(usd: object) -> int:
    """Whole micro-dollars in ``usd``, rounded **up** (spend is never under-counted). Digits
    below a nano-dollar are float noise (``0.0045000000000000001``), dropped first."""
    if usd is None:
        return 0
    if type(usd) not in (int, float) or not math.isfinite(usd) or usd < 0:
        raise OpenRouterError(f"the provider reported a spend that is not a dollar amount: {usd!r}")
    nanos = (Decimal(repr(float(usd))) * 1_000_000_000).to_integral_value(rounding=ROUND_HALF_EVEN)
    return int((nanos / 1000).to_integral_value(rounding=ROUND_CEILING))


def _price(value: object, what: str) -> Decimal:
    """One price from the provider's list: a non-negative decimal (the list writes strings)."""
    try:
        price = Decimal(str(value)) if type(value) in (str, int, float) else None
    except ArithmeticError:
        price = None
    if price is None or not price.is_finite() or price < 0:
        raise OpenRouterError(f"{what}: the price list holds {value!r}, not a price")
    return price


def _tier(row: Mapping[str, Any], what: str) -> tuple[Decimal, Decimal, Decimal]:
    """(per prompt token, per written token, per request) of one price tier, the most of each."""
    groups: dict[str, list[Decimal]] = {"prompt": [], "writing": [], "request": []}
    for field, value in row.items():
        if field in ("overrides", "min_prompt_tokens") or field in _UNBOUGHT_PRICES:
            continue
        group = ("prompt" if field in _PROMPT_PRICES else "writing" if field in _WRITING_PRICES
                 else "request" if field in _REQUEST_PRICES else None)
        if group is None:
            raise OpenRouterError(f"{what}: the price list names {field!r}, which no turn is bounded by")
        groups[group].append(_price(value, what))
    if not groups["prompt"] or not groups["writing"]:
        raise OpenRouterError(f"{what}: the price list gives no prompt or completion price")
    return (max(groups["prompt"]), max(groups["writing"]),
            max(groups["request"], default=Decimal(0)))


class Prices:
    """A model's prices, as the provider's model list states them: a base tier and the tiers a
    long prompt reaches (``overrides`` with ``min_prompt_tokens``)."""

    def __init__(self, model: str, pricing: object) -> None:
        what = f"pricing {model}"
        if not isinstance(pricing, Mapping):
            raise OpenRouterError(f"{what}: the model list holds no prices for it")
        overrides = pricing.get("overrides") or []
        if not isinstance(overrides, list) or not all(isinstance(o, Mapping) for o in overrides):
            raise OpenRouterError(f"{what}: its price overrides are not a list of tiers")
        self._tiers = [(0, _tier(pricing, what))]
        for o in overrides:
            start = o.get("min_prompt_tokens")
            if type(start) is not int or start < 0:
                raise OpenRouterError(f"{what}: a price tier names no min_prompt_tokens")
            # A tier states only what it changes: the rest is the base tier's.
            self._tiers.append((start, _tier({**pricing, **o}, what)))

    def worst_case(self, prompt_tokens: int) -> int:
        """Micro-dollars, rounded up, a turn of at most ``prompt_tokens`` in and
        :data:`MAX_TURN_TOKENS` out can cost, at every tier that prompt could reach."""
        reached = [t for start, t in self._tiers if start <= prompt_tokens]
        usd = max(fixed + prompt_tokens * per_in + MAX_TURN_TOKENS * per_out
                  for per_in, per_out, fixed in reached)
        return int((usd * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def _wire_bytes(value: object) -> int:
    return len(json.dumps(value, sort_keys=True).encode())


def _client(key: str, transport: httpx.BaseTransport | None, timeout: float) -> httpx.Client:
    # trust_env: the operator's network may need its proxy to reach the provider. The host is
    # fixed here; no spec, mind or flag can point a key elsewhere.
    return httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {key}"},
                        timeout=timeout, transport=transport, trust_env=transport is None)


def _json(response: httpx.Response, what: str) -> Any:
    if response.status_code >= 400:
        raise OpenRouterError(what, response.status_code)
    try:
        return response.json()
    except ValueError as exc:
        raise OpenRouterError(f"{what}: the answer is not JSON", response.status_code) from exc


class OpenRouterProvisioner:
    """One key per agent at OpenRouter, under the Human's monthly cap, counted across runs."""

    def __init__(self, provisioning_key: str, cap_usd_micros: int, *,
                 transport: httpx.BaseTransport | None = None,
                 run_tag: str | None = None, settle_s: float = SETTLE_S,
                 sleep: Callable[[float], None] = time.sleep,
                 lock_path: Path = MINT_LOCK) -> None:
        if type(cap_usd_micros) is not int or cap_usd_micros < 0:
            raise ValueError("the cap is an int of micro-dollars")
        if not provisioning_key.strip():
            raise ValueError("no provisioning key")
        self._http = _client(provisioning_key, transport, 30.0)
        self._transport = transport
        self._cap = cap_usd_micros
        self.run_tag = run_tag or secrets.token_hex(4)
        if not re.fullmatch(r"[a-z0-9]{1,16}", self.run_tag):
            raise ValueError("a run tag is 1-16 lowercase letters or digits")
        self._settle_s = settle_s
        self._sleep = sleep
        self._lock_path = lock_path
        #: key_ref -> (agent_id, limit µ$, provider hash, secret, name)
        self._keys: dict[str, tuple[int, int, str, str, str]] = {}
        #: key_ref -> µ$ the provider's own turn answers said this key cost (a floor for usage)
        self._billed: dict[str, int] = {}
        self._turns: dict[str, int] = {}
        #: key_ref -> turns the provider may have billed without saying what (red-team 0025)
        self._unstated: dict[str, int] = {}
        #: key_ref -> µ$ those unstated turns could have cost at most (their worst cases)
        self._reserved: dict[str, int] = {}
        #: keys a turn billed more than its worst case: the price list is not to be trusted
        self._unbounded: set[str] = set()
        self._prices: dict[str, Prices] = {}

    def _ask(self, method: str, path: str, what: str, **kwargs: Any) -> Any:
        """One account request, asked again (up to :data:`ATTEMPTS` times in all) when the answer
        is a passing failure: a dropped connection, a timeout, 408, 429 or 5xx. Still nothing
        after that is an :class:`OpenRouterError`, so every caller fails closed as before (cycle
        54: one 408 listing the keys stopped a real quarter at step 26 and lost its cost record).
        Only reads and the idempotent disable come through here, never a mint."""
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt == ATTEMPTS:
                    raise OpenRouterError(f"{what}: {type(exc).__name__}") from exc
            else:
                if response.status_code not in PASSING or attempt == ATTEMPTS:
                    return _json(response, what)
            self._sleep(2.0 * attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    @classmethod
    def from_env(cls, cap_usd_micros: int, **kwargs: Any) -> OpenRouterProvisioner:
        key = os.environ.get(PROVISIONING_KEY_ENV, "")
        if not key.strip():
            raise OpenRouterError(f"{PROVISIONING_KEY_ENV} is not set")
        return cls(key, cap_usd_micros, **kwargs)

    # -- the account -------------------------------------------------------------------------

    def firm_keys(self) -> list[dict[str, Any]]:
        """Every key on the account whose name starts with ``firm-`` (all pages)."""
        found: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._ask("GET", "/keys", "listing the account's keys",
                             params={"offset": offset, "include_disabled": "true"})
            rows = page.get("data") if isinstance(page, dict) else None
            if not isinstance(rows, list):
                raise OpenRouterError("listing the account's keys: no `data` list")
            found += [r for r in rows if isinstance(r, dict)
                      and str(r.get("name", "")).startswith(FIRM_PREFIX)]
            if not rows or offset > 100_000:
                return found
            offset += len(rows)

    def month_committed(self) -> int:
        """Micro-dollars the firm's keys hold this month (ADR-047 §4): an enabled key's whole
        limit (it may still spend it), a disabled key's spend this month. An enabled key with
        no limit is unbounded, so nothing more may be minted. The keys this run made count
        their whole limit from here, listed yet or not (red-team 0022)."""
        mine = {k[2] for k in self._keys.values()}
        total = sum(k[1] for k in self._keys.values())
        for row in self.firm_keys():
            if row.get("hash") in mine:
                continue
            if row.get("disabled") is True and row.get("usage_monthly") is not None:
                total += usd_to_micros_ceil(row.get("usage_monthly"))
            elif row.get("limit") is None:
                # Red-team 0023: a disabled key that does not say what it spent counts its limit.
                raise OverCap(f"the firm key {row.get('name')!r} has no limit: the month is unbounded")
            else:
                total += usd_to_micros_ceil(row.get("limit"))
        return total

    @contextmanager
    def _mint_lock(self) -> Iterator[None]:
        """One run at a time between reading the month and minting into it (red-team 0022)."""
        with open(self._lock_path, "a") as handle:
            deadline = time.monotonic() + MINT_LOCK_WAIT_S
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise OverCap("another run is minting keys: the month cannot be counted") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    # -- the Provisioner the Runtime uses (runtime.provision / lockstep / sync_costs) ---------

    def create_key(self, agent_id: int, limit_usd_micros: int, *, spec_id: str = "agent") -> str:
        if type(limit_usd_micros) is not int or not 0 < limit_usd_micros <= MAX_METERED_USD_MICROS:
            raise ValueError(f"a key's limit is an int of micro-dollars in 1..{MAX_METERED_USD_MICROS}")
        name = f"{FIRM_PREFIX}{self.run_tag}-{spec_id}"
        with self._mint_lock():
            committed = self.month_committed()
            if committed + limit_usd_micros > self._cap:
                raise OverCap(f"the firm's keys hold {committed} µ$ this month; {limit_usd_micros} "
                              f"more would pass the cap of {self._cap} µ$")
            made = _json(self._http.post("/keys", json={"name": name, "limit": limit_usd_micros / 1e6}),
                         "minting a key")
            data = made.get("data") if isinstance(made, dict) else None
            secret = made.get("key") if isinstance(made, dict) else None
            digest = data.get("hash") if isinstance(data, dict) else None
            if type(secret) is not str or not secret or type(digest) is not str \
                    or not re.fullmatch(r"[0-9a-f]{16,128}", digest):
                raise OpenRouterError("minting a key: the answer holds no key and hash")
            if data.get("name") != name:
                # Red-team 0028: an answer naming another key (maybe the Human's) is never held,
                # so nothing of this run ever reads or disables it.
                raise OpenRouterError("minting a key: the answer names another key")
            key_ref = f"or-{digest[:16]}"
            if key_ref in self._keys:
                raise OpenRouterError("minting a key: the provider answered a key already held")
            self._keys[key_ref] = (agent_id, limit_usd_micros, digest, secret, name)
            self._billed[key_ref] = 0
            self._turns[key_ref] = 0
            self._unstated[key_ref] = 0
            self._reserved[key_ref] = 0
        limit = data.get("limit")
        if type(limit) not in (int, float) or usd_to_micros_ceil(limit) != limit_usd_micros \
                or data.get("limit_reset") is not None:   # a limit that resets is no hard limit
            # Red-team 0024: a key the provider does not bound as asked is ours, so it is
            # disabled at once (close() would only report it), and the run is refused.
            if self._disable(digest):
                del self._keys[key_ref]
            raise OpenRouterError(f"minting a key: the provider set its limit to {limit!r}, "
                                  f"not {limit_usd_micros / 1e6}")
        return key_ref

    def limit(self, key_ref: str) -> int:
        return self._keys[key_ref][1]

    def agent_of(self, key_ref: str) -> int:
        return self._keys[key_ref][0]

    def charges(self, key_ref: str) -> int:
        """Model turns the key answered (for the run's report)."""
        return self._turns[key_ref]

    def billed(self, key_ref: str, usd_micros: int | None, worst_case: int | None = None) -> None:
        """A turn on ``key_ref`` cost this, by the provider's own answer (``None``: the turn
        reached the provider but its answer did not say what it cost). ``worst_case`` is the
        most the turn could cost, as priced before it was sent (``None``: not priced, so the
        key is spent out)."""
        if usd_micros is None:
            self._unstated[key_ref] += 1
            self._reserved[key_ref] += (self._keys[key_ref][1] if worst_case is None
                                        else worst_case)
        else:
            self._billed[key_ref] += usd_micros
            if worst_case is not None and usd_micros > worst_case:
                self._unbounded.add(key_ref)
        self._turns[key_ref] += 1

    def spent_out(self, key_ref: str) -> bool:
        """Have the key's turns, by their own answers, used its whole limit? (red-team 0024)"""
        return self._billed[key_ref] >= self._keys[key_ref][1]

    def left(self, key_ref: str) -> int:
        """Micro-dollars the key may still spend: its limit less what its turns billed and the
        worst cases of the turns that did not say. 0 once a turn billed past its own worst
        case (the prices the guard read are not the prices charged)."""
        if key_ref in self._unbounded:
            return 0
        return max(0, self._keys[key_ref][1] - self._billed[key_ref] - self._reserved[key_ref])

    def prices(self, model: str) -> Prices:
        """The model's prices, from the provider's model list (read once per run)."""
        if model not in self._prices:
            listing = self._ask("GET", "/models", "reading the model list")
            rows = listing.get("data") if isinstance(listing, dict) else None
            if not isinstance(rows, list):
                raise OpenRouterError("reading the model list: no `data` list")
            found = [r for r in rows if isinstance(r, dict) and r.get("id") == model]
            if len(found) != 1:
                raise OpenRouterError(f"reading the model list: {len(found)} models named {model!r}")
            self._prices[model] = Prices(model, found[0].get("pricing"))
        return self._prices[model]

    def chat_client(self, key_ref: str) -> httpx.Client:
        """The HTTP client one mind's turns go through: its own key, nothing else."""
        return _client(self._keys[key_ref][3], self._transport, TURN_TIMEOUT_S)

    def usage(self) -> list[KeyUsage]:
        """What each key has cost, by the provider's per-key usage, rounded up. The provider
        updates usage a little after a turn: this waits up to ``settle_s`` for it to reach what
        the turns' own answers billed, and never reports less than that."""
        deadline = time.monotonic() + self._settle_s
        out = []
        for key_ref in sorted(self._keys):
            agent_id, _, digest, _, _ = self._keys[key_ref]
            floor, unstated = self._billed[key_ref], self._unstated[key_ref]
            while True:
                row = self._ask("GET", f"/keys/{digest}", "reading a key's spend")
                data = row.get("data") if isinstance(row, dict) else None
                if not isinstance(data, dict):
                    raise OpenRouterError("reading a key's spend: no `data`")
                spent = usd_to_micros_ceil(data.get("usage"))
                # A turn whose cost went unstated settles only when the spend passes what the
                # stated turns billed (red-team 0025).
                settled = spent > floor if unstated else spent >= floor
                if settled or time.monotonic() >= deadline:
                    break
                self._sleep(2.0)
            out.append(KeyUsage(key_ref, agent_id, max(spent, self._billed[key_ref])))
        return out

    def close(self) -> list[str]:
        """Disable every key this run made (never delete: the account keeps the history).
        Returns the key_refs that could not be disabled; they still count their whole limit."""
        failed = [key_ref for key_ref in sorted(self._keys) if not self._disable(self._keys[key_ref][2])]
        self._http.close()
        return failed

    def _disable(self, digest: str) -> bool:
        try:
            self._ask("PATCH", f"/keys/{digest}", "disabling a key", json={"disabled": True})
        except (OpenRouterError, httpx.HTTPError):
            return False
        return True


# -- the mind's side -----------------------------------------------------------------------

def _wire_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name,
                                  "arguments": json.dumps(c.arguments, sort_keys=True)}}
                    for c in m.tool_calls]
            out.append(msg)
        elif m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id,
                        "content": ("ERROR: " if m.is_error else "") + m.content})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _arguments(raw: object) -> dict[str, Any]:
    """A model's arguments, as the adapter takes them. Arguments that are not a JSON object are
    passed on under one key, so the tool refuses them and the mind hears why."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"_unparsed_arguments": raw}
        return parsed if isinstance(parsed, dict) else {"_unparsed_arguments": raw}
    return {"_unparsed_arguments": json.dumps(raw)}


class OpenRouterProvider:
    """The one class the name ``openrouter`` builds. One HTTPS call per model turn, on the mind's
    own key; the turn's cost is booked to that key's floor at the provisioner."""

    name = "openrouter"
    spends_money = True

    def __init__(self, model: str, meter: Meter) -> None:
        if type(model) is not str or not model:
            raise ValueError("an openrouter mind names its model")
        self._model = model
        self._meter = meter
        self._http = meter.provisioner.chat_client(meter.key_ref)
        #: The last answered turn: (its messages, its tools, the prompt tokens the provider counted)
        self._last: tuple[list[dict[str, Any]], object, int] | None = None

    def _prompt_bound(self, body: Mapping[str, Any]) -> int:
        """Most prompt tokens this turn can hold. A wake's transcript only grows: when this turn
        extends the last answered one, the bound is what the provider counted then plus the bytes
        added since; otherwise every byte of the messages and tools."""
        messages, tools = body["messages"], body.get("tools")
        start, base = 0, (_wire_bytes(tools) + TOOLS_TOKENS) if tools else 0
        if self._last is not None:
            before, before_tools, counted = self._last
            if before_tools == tools and messages[:len(before)] == before:
                start, base = len(before), counted
        return base + sum(_wire_bytes(m) + MESSAGE_TOKENS for m in messages[start:])

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        provisioner, key_ref = self._meter.provisioner, self._meter.key_ref
        if provisioner.spent_out(key_ref):
            raise OpenRouterError("a model turn: the key's turns have used its whole limit")
        body: dict[str, Any] = {
            "model": self._model,
            "messages": _wire_messages(request.messages),
            "max_tokens": MAX_TURN_TOKENS,
            "usage": {"include": True},
        }
        if request.tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t.name, "description": t.description,
                                           "parameters": t.input_schema or {"type": "object"}}}
                             for t in request.tools]
        # The hard limit: a turn is sent only if its worst case fits what the key has left.
        worst = provisioner.prices(self._model).worst_case(self._prompt_bound(body))
        left = provisioner.left(key_ref)
        if worst > left:
            raise OpenRouterError(f"a model turn: it could cost up to {worst} µ$ and the key "
                                  f"has {left} µ$ left of its limit")
        try:
            answer = _json(self._http.post("/chat/completions", json=body), "a model turn")
        except (OpenRouterError, httpx.HTTPError) as exc:
            # Sent and maybe billed (a timeout after the model ran): the spend is unstated.
            # A refusal the provider names (4xx) billed nothing.
            if not (isinstance(exc, OpenRouterError) and 400 <= exc.status < 500):
                provisioner.billed(key_ref, None, worst)
            raise
        usage = answer.get("usage") if isinstance(answer, dict) else None
        usage = usage if isinstance(usage, Mapping) else {}
        stated = usage.get("cost")
        try:
            micros = usd_to_micros_ceil(stated)
        except OpenRouterError:
            provisioner.billed(key_ref, None, worst)   # billed, but not said how much
            raise
        provisioner.billed(key_ref, None if stated is None else micros, worst)
        if isinstance(answer, dict) and answer.get("error"):
            raise OpenRouterError(f"a model turn: {str(answer['error'])[:200]}")
        choices = answer.get("choices") if isinstance(answer, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise OpenRouterError("a model turn: no choice in the answer")
        message = choices[0].get("message") or {}
        # Call ids are the Runtime's, not the model's: unique in the wake by construction
        # (models reuse ids like "call_0"), and recorded, so a replay asks the same thing.
        turn = sum(1 for m in request.messages if m.role == "assistant")
        calls = [ToolCall(id=f"t{turn}c{i}", name=str((c.get("function") or {}).get("name", "")),
                          arguments=_arguments((c.get("function") or {}).get("arguments")))
                 for i, c in enumerate(message.get("tool_calls") or []) if isinstance(c, dict)]
        tokens_in, tokens_out = usage.get("prompt_tokens"), usage.get("completion_tokens")
        self._last = ((body["messages"], body.get("tools"), tokens_in)
                      if type(tokens_in) is int and tokens_in >= 0 else None)
        return CompletionResponse(
            content=message.get("content") if isinstance(message.get("content"), str) else "",
            tool_calls=calls,
            usage=Usage(input_tokens=tokens_in if type(tokens_in) is int and tokens_in >= 0 else 0,
                        output_tokens=tokens_out if type(tokens_out) is int and tokens_out >= 0 else 0,
                        cost_usd=micros / 1e6))
