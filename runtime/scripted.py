"""The ``scripted`` provider: a deterministic policy in code (ADR-032 (3), R-2).

A scripted mind runs no model and holds no network client. Its reply is a pure
function of the request it is shown — the transcript so far — so the same
transcript always gets the same reply, and a cassette of it (R-4) is exact.

A script is chosen by name from :data:`SCRIPTS`, a closed table in code: a spec
names a script, it cannot supply one. Adding a script is a code change, reviewed
like any other.

This module imports only pure standard-library modules and :mod:`runtime.providers`,
and calls none of the builtins that load code or reach other modules
(``__import__``, ``eval``, ``exec``, ``compile``, ``globals``, ``vars``, ``getattr``,
``open``, ``__builtins__``). ``tests/test_runtime_native.py`` checks both, with
planted counter-examples. That check is a lint on code the Builder writes, not a
seal (ADR-032 (f)). "Pure" and "keeps no state" are rules for script authors,
checked by review and by the month-twice test, not by code.

A scripted mind is not a firm agent (Art. 2.1): it is a script with an API key,
like the cycle-18 probe pod. Runs with scripted minds are labelled so (R-3).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from types import MappingProxyType

from runtime.providers import CompletionRequest, CompletionResponse, ToolCall

#: A script: the whole transcript in, one reply out. It must not keep state.
Script = Callable[[CompletionRequest], CompletionResponse]


class ScriptedProvider:
    """The one class the name ``scripted`` builds (:mod:`runtime.registry`)."""

    name = "scripted"
    spends_money = False

    def __init__(self, script: Script) -> None:
        self._script = script

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        # ``request.model`` is never read: there is no model to give it to.
        return self._script(request)


def _context(request: CompletionRequest) -> dict:
    """The code-assembled context the native adapter puts in the first user message."""
    first_user = next(m for m in request.messages if m.role == "user")
    return json.loads(first_user.content)


def _turn(request: CompletionRequest) -> int:
    return sum(1 for m in request.messages if m.role == "assistant")


def _results(request: CompletionRequest) -> dict[str, object]:
    """Tool results by call id; a failed call maps to ``None``."""
    return {
        m.tool_call_id: None if m.is_error else json.loads(m.content)
        for m in request.messages
        if m.role == "tool" and m.tool_call_id is not None
    }


def moving_average_pm(request: CompletionRequest) -> CompletionResponse:
    """The cycle-18 probe pod as a mind: 5-day vs 20-day average, one sleeve per name.

    Turn 0 reads the book, the bars and the price of every name in the workflow
    input's ``universe``. Turn 1 places the orders the averages call for, keeping
    a running cash figure so a sleeve never spends cash an earlier buy used.
    Turn 2 is done. Any failed read ends the wake without trading.
    """
    context = _context(request)
    pod_id = context["me"]["pod_id"]
    universe = context["input"].get("universe")
    if type(universe) is not list or not universe or pod_id is None:
        return CompletionResponse(content="No pod or no universe in my input; nothing to do.")
    turn = _turn(request)

    if turn == 0:
        calls = [ToolCall(id="book", name="get_portfolio", arguments={"pod_id": pod_id})]
        for ticker in universe:
            calls.append(ToolCall(id=f"bars:{ticker}", name="get_ohlcv",
                                  arguments={"ticker": ticker, "interval": "1d"}))
            calls.append(ToolCall(id=f"price:{ticker}", name="get_price",
                                  arguments={"ticker": ticker}))
        return CompletionResponse(content="Reading the book and the market.", tool_calls=calls)

    if turn == 1:
        results = _results(request)
        failed = sorted(k for k, v in results.items() if v is None)
        if failed:
            return CompletionResponse(content=f"A read failed ({', '.join(failed)}); not trading.")
        book = results["book"]
        held = {p["ticker"]: p["qty"] for p in book["positions"]}
        cash = book["cash"]
        sleeve = book["total_value"] / len(universe)
        orders: list[ToolCall] = []
        for ticker in universe:
            closes = [b["close"] for b in results[f"bars:{ticker}"]["bars"]]
            if len(closes) < 20:
                continue
            fast, slow = sum(closes[-5:]) / 5, sum(closes[-20:]) / 20
            price = results[f"price:{ticker}"]["price"]
            if fast > slow and not held.get(ticker):
                qty = math.floor(min(sleeve, cash) * 0.99 / price)
                if qty:
                    cash -= qty * price
                    orders.append(_order(ticker, "buy", qty, f"5d avg {fast:.2f} > 20d avg {slow:.2f}"))
            elif fast < slow and held.get(ticker):
                orders.append(_order(ticker, "sell", held[ticker],
                                     f"5d avg {fast:.2f} < 20d avg {slow:.2f}"))
        if not orders:
            return CompletionResponse(content="No crossing today; holding.")
        return CompletionResponse(content=f"Placing {len(orders)} order(s).", tool_calls=orders)

    return CompletionResponse(content="Done for today.")


def _order(ticker: str, side: str, qty: float, why: str) -> ToolCall:
    return ToolCall(id=f"order:{ticker}", name="place_order", arguments={
        "ticker": ticker, "side": side, "qty": qty, "price_type": "market",
        "justification": why,
    })


#: The closed table: script name → policy. A spec names one of these keys.
SCRIPTS: Mapping[str, Script] = MappingProxyType({
    "moving-average-pm": moving_average_pm,
})
