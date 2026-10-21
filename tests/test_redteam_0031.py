"""Red-team 0031 (cycle 59) — the hard limit on a key: holes in the turn's worst case.

The guard (``OpenRouterProvider.complete``) sends a turn only if its worst case fits what the key
has left: the prompt bounded by its JSON bytes ("a token is at least one byte"), or by what the
provider counted for the turn before plus the bytes added since, plus MAX_TURN_TOKENS written, at
the dearest tier of the provider's model list. Each test below is a hole: it fails until fixed.

1. MEDIUM  ``test_hole_a_token_is_not_always_at_least_one_byte`` and
           ``test_hole_a_mind_writing_ligatures_spends_its_key_past_its_limit``.
   "A token is at least one byte" holds for the bytes the guard counts only if the tokenizer
   sees those same characters. Tokenizers that NFKC-normalize first (SentencePiece's default
   ``nmt_nfkc`` rule; Anthropic's published tokenizer normalizes NFKC before counting) see U+FDFA
   ARABIC LIGATURE SALLALLAHOU ALAYHE WASALLAM as 18 characters, 33 UTF-8 bytes, where
   ``json.dumps`` (ensure_ascii) counted 6 bytes: up to 5.5 tokens per counted byte under a
   byte-level BPE. A mind controls this: its own reply's ``content`` (and a tool call's ``name``)
   go back on the wire raw, and the next turn's bound adds only their escaped bytes. Near a price
   tier the under-count also hides the tier jump (5x in the test's price list): in the end-to-end
   test a $0.02 key spends about $0.06 in two turns. The key is stopped only *after* the crossing
   turn (billed past its worst case), so the overshoot is one turn, but that is exactly what this
   commit claims can no longer happen. (Tool results are safe: ``_payload`` re-encodes them with
   ensure_ascii, so the provider sees ASCII escapes.)
2. LOW     ``test_hole_a_prompt_count_the_provider_understates_is_trusted_as_a_bound``.
   The provider's ``prompt_tokens`` of the turn before is taken as an upper bound with no check
   against the bytes or the cost it billed. An answer that under-counts its prompt (billing it in
   full) makes the next turn's bound tiny; the key spends past its limit.
3. MEDIUM  ``test_hole_the_model_list_price_is_not_the_price_of_the_upstream_that_serves``.
   ``/models`` states one price per model; OpenRouter serves many models through several upstream
   providers at different prices and by default balances load across them (not only the
   cheapest). The request pins neither ``provider.max_price`` nor one upstream, and the guard never
   reads the per-endpoint prices, so a turn served by a dearer upstream can cost past its bound.
   (The recorded run's Haiku is priced the same everywhere; an open-weight model is not.)
4. LOW     ``test_hole_a_408_timeout_holds_back_no_worst_case``.
   A 408 is a timeout, which the code's own comment says may have been billed after the model ran,
   but every 4xx is taken as "billed nothing": the key's ``left`` stays whole.
5. LOW     ``test_hole_an_answer_that_overflows_the_json_parser_holds_back_nothing``.
   A 200 answer nested deeper than the parser's recursion limit raises ``RecursionError``, which
   ``complete`` does not catch: the turn was sent (and maybe billed) but neither its cost nor its
   worst case is booked, and the next wake's turns see the key whole.
6. LOW     ``test_hole_prices_the_guard_skips_are_not_read``.
   ``_UNBOUGHT_PRICES`` are skipped unread on the claim they are never bought or only lower a
   cost. Cache reads are bought without asking (implicit caching); a list whose ``input_cache_read``
   is dearer than ``prompt`` (or whose ``discount`` is negative) is not bounded and not refused.
"""

from __future__ import annotations

import json
import unicodedata
from decimal import Decimal

import httpx
import pytest

from runtime.metering import Meter
from runtime.openrouter import MAX_TURN_TOKENS, OpenRouterError, OpenRouterProvisioner
from runtime.providers import CompletionRequest, Message, ToolSpec
from runtime.registry import build_provider
from tests.test_runtime_openrouter import Account, chat, spec

CAP = 50_000_000
LIGATURE = "ﷺ"   # NFKC: 18 characters, 33 UTF-8 bytes; json.dumps (ensure_ascii): 6 bytes


def _prov(account: Account) -> OpenRouterProvisioner:
    return OpenRouterProvisioner("prov-key", CAP, transport=httpx.MockTransport(account.handler),
                                 run_tag="t1", settle_s=0, sleep=lambda s: None)


def _mind(account: Account, limit: int):
    p = _prov(account)
    meter = Meter(p, p.create_key(7, limit, spec_id="pm"))
    return p, meter, build_provider(spec(), meter=meter)


def _request(*messages: Message) -> CompletionRequest:
    return CompletionRequest(
        messages=list(messages),
        tools=[ToolSpec(name="get_price", description="d", input_schema={"type": "object"})],
        model="vendor/cheap")


def _spent(account: Account, meter: Meter) -> int:
    digest = next(d for d, k in account.keys.items() if k["name"] == "firm-t1-pm")
    return round(account.keys[digest]["usage"] * 1_000_000)


class HonestAccount(Account):
    """An account that bills every turn honestly, by its own tokenizer: a byte-level BPE with no
    merges over the NFKC-normalized text (one token per byte of what the model is shown), at the
    tier of the price list the prompt really reaches. ``understate`` makes it report a prompt
    count lower than the one it billed."""

    def __init__(self, understate: bool = False) -> None:
        super().__init__()
        self.understate = understate
        self.replies: list[tuple[str, int]] = []   # (content, completion tokens) per turn

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.removeprefix("/api/v1") != "/chat/completions":
            return super().handler(request)
        body = json.loads(request.content)
        shown = json.dumps(body["messages"], ensure_ascii=False, separators=(",", ":")) \
            + json.dumps(body.get("tools"), separators=(",", ":"))
        tokens_in = len(unicodedata.normalize("NFKC", shown).encode())
        content, tokens_out = self.replies.pop(0)
        pricing = self.models[0]["pricing"]
        tier = dict(pricing)
        for o in pricing.get("overrides", []):
            if tokens_in >= o["min_prompt_tokens"]:
                tier.update(o)
        cost = float(tokens_in * Decimal(tier["prompt"]) + tokens_out * Decimal(tier["completion"]))
        reported = 1 if self.understate else tokens_in
        self.answers.append({"choices": [{"message": {"content": content}}],
                             "usage": {"prompt_tokens": reported, "completion_tokens": tokens_out,
                                       "cost": cost}})
        return super().handler(request)


# -- 1. NFKC: a mind's own text is more tokens than the bytes the guard counted (MEDIUM) ---------

def test_hole_a_token_is_not_always_at_least_one_byte() -> None:
    """MEDIUM. The bound of a message must be at least what a byte-level tokenizer can make of it
    once normalized NFKC; for a reply of ligatures it is about a fifth of that."""
    account = Account()
    _, _, mind = _mind(account, 1_000_000)
    reply = {"role": "assistant", "content": LIGATURE * 1_000}
    bound = mind._prompt_bound({"messages": [reply]})
    seen = len(unicodedata.normalize("NFKC", reply["content"]).encode())
    assert bound >= seen, f"bound {bound} tokens, the tokenizer may see {seen}"


def test_hole_a_mind_writing_ligatures_spends_its_key_past_its_limit() -> None:
    """MEDIUM. Turn 1: a long charter; the mind writes 1,365 ligatures (3 bytes, so at most 3
    tokens each). Turn 2 adds that reply: the guard bounds it at ~8.2k tokens below the 100k tier;
    the provider sees ~45k more and bills the whole prompt at the dearer tier."""
    account = HonestAccount()
    p, meter, mind = _mind(account, 20_000)                     # a $0.02 key
    charter = Message(role="system", content="x" * 60_000)
    today = Message(role="user", content="u")
    reply = LIGATURE * 1_365
    account.replies += [(reply, 3 * 1_365), ("ok", 1)]
    mind.complete(_request(charter, today))
    assert _spent(account, meter) <= 20_000                    # turn 1 was within its bound
    try:
        mind.complete(_request(charter, today, Message(role="assistant", content=reply),
                               Message(role="user", content="go on")))
    except OpenRouterError:
        pass                                                   # refused unsent: the fix
    assert _spent(account, meter) <= 20_000, \
        f"the key spent {_spent(account, meter)} µ$ of its 20000 µ$ limit"


# -- 2. the provider's prompt count is trusted (LOW) ----------------------------------------------

@pytest.mark.xfail(strict=True, reason="known hole (low, cycle 59): the provider's own prompt count "
                   "is trusted; a turn it bills past that turn's worst case stops the key after it")
def test_hole_a_prompt_count_the_provider_understates_is_trusted_as_a_bound() -> None:
    """LOW. The provider bills a 30k-token prompt in full but says it counted 1 token; the next
    turn, the same prompt plus a few bytes, is bounded at ~100 tokens and sent."""
    account = HonestAccount(understate=True)
    p, meter, mind = _mind(account, 5_200)
    charter = Message(role="system", content="x" * 30_000)
    today = Message(role="user", content="u")
    account.replies += [("ok", 20), ("ok", 20)]
    mind.complete(_request(charter, today))
    try:
        mind.complete(_request(charter, today, Message(role="assistant", content="ok"),
                               Message(role="user", content="go on")))
    except OpenRouterError:
        pass
    assert _spent(account, meter) <= 5_200, \
        f"the key spent {_spent(account, meter)} µ$ of its 5200 µ$ limit"


# -- 3. one price per model, many upstreams (MEDIUM) ----------------------------------------------

def test_hole_the_model_list_price_is_not_the_price_of_the_upstream_that_serves() -> None:
    """MEDIUM. The account serves the model through two upstreams, one 10x dearer than the model
    list says (``/models/{id}/endpoints``). Either the request pins the price the guard used
    (``provider.max_price``) or the guard's worst case covers the dearest upstream."""
    class TwoUpstreams(Account):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.removeprefix("/api/v1") == "/models/vendor/cheap/endpoints":
                base = self.models[0]["pricing"]
                return httpx.Response(200, json={"data": {"id": "vendor/cheap", "endpoints": [
                    {"provider_name": "cheap-host", "pricing": base},
                    {"provider_name": "dear-host", "pricing": {"prompt": "0.000001",
                                                               "completion": "0.000005"}}]}})
            return super().handler(request)

    account = TwoUpstreams()
    p, meter, mind = _mind(account, 1_000_000)
    answer = chat("ok")
    del answer["usage"]["cost"]                     # unstated: the guard holds back its worst case
    account.answers.append(answer)
    mind.complete(_request(Message(role="system", content="c"), Message(role="user", content="u")))
    held = 1_000_000 - p.left(meter.key_ref)
    dear_writing = MAX_TURN_TOKENS * 5             # 5 µ$ a written token at the dear upstream
    pinned = (account.chats[0]["body"].get("provider") or {}).get("max_price")
    assert pinned is not None or held >= dear_writing, \
        f"held back {held} µ$; the dear upstream's writing alone can cost {dear_writing} µ$"


# -- 4. a 408 is a timeout, not a refusal (LOW) ---------------------------------------------------

def test_hole_a_408_timeout_holds_back_no_worst_case() -> None:
    """LOW. The model may have run before the provider timed the request out."""
    class Timeout(Account):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.removeprefix("/api/v1") == "/chat/completions":
                return httpx.Response(408, json={"error": {"code": 408, "message": "timed out"}})
            return super().handler(request)

    account = Timeout()
    p, meter, mind = _mind(account, 1_000_000)
    with pytest.raises(OpenRouterError):
        mind.complete(_request(Message(role="system", content="c"), Message(role="user", content="u")))
    assert p.left(meter.key_ref) < 1_000_000, "a timed-out turn left the key whole"


# -- 5. an answer the parser cannot read escapes the booking (LOW) --------------------------------

def test_hole_an_answer_that_overflows_the_json_parser_holds_back_nothing() -> None:
    """LOW. 200, billed, and nested past the recursion limit: RecursionError is not caught."""
    class Deep(Account):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.removeprefix("/api/v1") == "/chat/completions":
                return httpx.Response(200, content=b"[" * 100_000 + b"]" * 100_000,
                                      headers={"content-type": "application/json"})
            return super().handler(request)

    account = Deep()
    p, meter, mind = _mind(account, 1_000_000)
    with pytest.raises(Exception):
        mind.complete(_request(Message(role="system", content="c"), Message(role="user", content="u")))
    assert p.left(meter.key_ref) < 1_000_000, "a sent turn's worst case was not held back"


# -- 6. prices skipped unread (LOW) ---------------------------------------------------------------

@pytest.mark.parametrize("field,value", [("input_cache_read", "0.00001"),   # 100x the prompt price
                                         ("discount", "-4")])                # a surcharge
def test_hole_prices_the_guard_skips_are_not_read(field, value) -> None:
    """LOW. Either the price list is refused, or the worst case covers the dearer price."""
    account = Account()
    account.models[0]["pricing"] = {"prompt": "0.0000001", "completion": "0.0000005", field: value}
    p, _, _ = _mind(account, 1_000_000)
    try:
        worst = p.prices("vendor/cheap").worst_case(1_000)
    except OpenRouterError:
        return                                                  # refused: the fix
    honest = 1_000 * 10 + MAX_TURN_TOKENS * 0.5 if field == "input_cache_read" \
        else (1_000 * 0.1 + MAX_TURN_TOKENS * 0.5) * 5
    assert worst >= honest, f"worst case {worst} µ$, a turn may cost {honest} µ$"
