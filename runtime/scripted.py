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
        views: dict[str, tuple[str, str]] = {}
        for ticker in universe:
            view = _crossing([b["close"] for b in results[f"bars:{ticker}"]["bars"]])
            if view is not None:
                views[ticker] = view
        orders = _rebalance(universe, views, results, book)
        if not orders:
            return CompletionResponse(content="No crossing today; holding.")
        return CompletionResponse(content=f"Placing {len(orders)} order(s).", tool_calls=orders)

    return CompletionResponse(content="Done for today.")


def ma_signal_analyst(request: CompletionRequest) -> CompletionResponse:
    """An analyst: the same 5-day vs 20-day crossing, sent to its pod as a dated signal.

    Turn 0 reads the clock and the bars of every name in the input's ``universe``.
    Turn 1 sends one message to ``pod:<own pod>`` whose structured payload is
    ``{"kind": "signal", "as_of": <the clock's now>, "signals": {ticker: "long" |
    "flat"}}`` — a name with under 20 bars, or no crossing, is left out. Turn 2 is
    done. Any failed read ends the wake without a signal: no signal is not "flat".
    """
    context = _context(request)
    pod_id = context["me"]["pod_id"]
    universe = context["input"].get("universe")
    if type(universe) is not list or not universe or pod_id is None:
        return CompletionResponse(content="No pod or no universe in my input; nothing to do.")
    turn = _turn(request)

    if turn == 0:
        calls = [ToolCall(id="clock", name="get_clock")]
        calls += [ToolCall(id=f"bars:{t}", name="get_ohlcv", arguments={"ticker": t, "interval": "1d"})
                  for t in universe]
        return CompletionResponse(content="Reading the clock and the bars.", tool_calls=calls)

    if turn == 1:
        results = _results(request)
        failed = sorted(k for k, v in results.items() if v is None)
        if failed:
            return CompletionResponse(content=f"A read failed ({', '.join(failed)}); no signal today.")
        signals: dict[str, str] = {}
        reasons: list[str] = []
        for ticker in universe:
            view = _crossing([b["close"] for b in results[f"bars:{ticker}"]["bars"]])
            if view is not None:
                signals[ticker], why = view
                reasons.append(f"{ticker} {signals[ticker]} ({why})")
        payload = {"kind": "signal", "as_of": results["clock"]["now"], "signals": signals}
        body = "Signal: " + ("; ".join(reasons) if reasons else "no crossing in any name")
        return CompletionResponse(content="Sending today's signal to my pod.", tool_calls=[
            ToolCall(id="signal", name="send_message", arguments={
                "to": f"pod:{pod_id}", "body": body, "structured_payload": payload})])

    return CompletionResponse(content="Done for today.")


def signal_pm(request: CompletionRequest) -> CompletionResponse:
    """A PM that trades only on its own analyst's signal for today.

    Turn 0 reads the clock, the book, the directory, the newest 50 messages it
    can see and the price of every name in the input's ``universe``. Turn 1 takes
    the newest of those that is addressed to its pod, comes from an active analyst
    of its pod (by the directory, not by what the message says), was stamped by
    physics with the clock's now (``ts``), and carries a ``signal`` payload whose
    ``as_of`` says the same. A signal pushed out of the 50 by later messages is
    not seen. With no such message it holds. Otherwise
    it buys a sleeve of each ``long`` name it does not hold and sells each ``flat``
    name it holds, citing the message id. Turn 2 is done. Any failed read ends the
    wake without trading.
    """
    context = _context(request)
    pod_id = context["me"]["pod_id"]
    universe = context["input"].get("universe")
    if type(universe) is not list or not universe or pod_id is None:
        return CompletionResponse(content="No pod or no universe in my input; nothing to do.")
    turn = _turn(request)

    if turn == 0:
        calls = [ToolCall(id="clock", name="get_clock"),
                 ToolCall(id="book", name="get_portfolio", arguments={"pod_id": pod_id}),
                 ToolCall(id="directory", name="list_agents"),
                 ToolCall(id="inbox", name="get_messages", arguments={"latest": True, "limit": 50})]
        calls += [ToolCall(id=f"price:{t}", name="get_price", arguments={"ticker": t})
                  for t in universe]
        return CompletionResponse(content="Reading the book, the inbox and the market.",
                                  tool_calls=calls)

    if turn == 1:
        results = _results(request)
        failed = sorted(k for k, v in results.items() if v is None)
        if failed:
            return CompletionResponse(content=f"A read failed ({', '.join(failed)}); not trading.")
        now = results["clock"]["now"]
        analysts = {a["id"] for a in results["directory"]
                    if a["role"] == "analyst" and a["pod_id"] == pod_id and a["status"] == "active"}
        today = [m for m in results["inbox"]
                 if m["from_agent"] in analysts and m["to"] == f"pod:{pod_id}"
                 and m["ts"] == now and _is_signal(m["structured_payload"], now)]
        if not today:
            return CompletionResponse(content="No signal from my analyst for today; holding.")
        signal = max(today, key=lambda m: m["id"])
        views = {t: (side, f"analyst signal #{signal['id']}: {side}")
                 for t, side in signal["structured_payload"]["signals"].items()}
        orders = _rebalance(universe, views, results, results["book"])
        if not orders:
            return CompletionResponse(content=f"Signal #{signal['id']} asks for no trade; holding.")
        return CompletionResponse(content=f"Placing {len(orders)} order(s) on signal #{signal['id']}.",
                                  tool_calls=orders)

    return CompletionResponse(content="Done for today.")


def _crossing(closes: list[float]) -> tuple[str, str] | None:
    """``("long" | "flat", why)`` from the 5-day vs 20-day averages; ``None`` with
    under 20 closes or no crossing."""
    if len(closes) < 20:
        return None
    fast, slow = sum(closes[-5:]) / 5, sum(closes[-20:]) / 20
    if fast > slow:
        return "long", f"5d avg {fast:.2f} > 20d avg {slow:.2f}"
    if fast < slow:
        return "flat", f"5d avg {fast:.2f} < 20d avg {slow:.2f}"
    return None


def _is_signal(payload: object, now: str) -> bool:
    """A ``signal`` payload stamped ``now`` whose every view is ``long`` or ``flat``."""
    if not isinstance(payload, dict) or payload.get("kind") != "signal" or payload.get("as_of") != now:
        return False
    signals = payload.get("signals")
    return isinstance(signals, dict) and all(
        type(t) is str and v in {"long", "flat"} for t, v in signals.items())


def _rebalance(universe: list, views: Mapping[str, tuple[str, str]], results: Mapping[str, object],
               book: dict) -> list[ToolCall]:
    """Orders for ``views`` (ticker → (long | flat, why)), one sleeve per name of the
    universe, keeping a running cash figure so a buy never spends cash an earlier
    buy used. A name outside the universe is never traded."""
    held = {p["ticker"]: p["qty"] for p in book["positions"]}
    cash = book["cash"]
    sleeve = book["total_value"] / len(universe)
    orders: list[ToolCall] = []
    for ticker in universe:
        if ticker not in views:
            continue
        side, why = views[ticker]
        price = results[f"price:{ticker}"]["price"]
        if side == "long" and not held.get(ticker):
            qty = math.floor(min(sleeve, cash) * 0.99 / price)
            if qty:
                cash -= qty * price
                orders.append(_order(ticker, "buy", qty, why))
        elif side == "flat" and held.get(ticker):
            orders.append(_order(ticker, "sell", held[ticker], why))
    return orders


def _order(ticker: str, side: str, qty: float, why: str) -> ToolCall:
    return ToolCall(id=f"order:{ticker}", name="place_order", arguments={
        "ticker": ticker, "side": side, "qty": qty, "price_type": "market",
        "justification": why,
    })


def self_reporting(script: Script, usd_per_wake: float) -> Script:
    """``script``, then one ``report_cost`` call of ``usd_per_wake`` when it has nothing left
    to do: a mind that tells the fund what it cost, in a number the meter neither needs nor
    believes (M-001, ADR-044). The inner script's own calls are passed through untouched."""
    def run(request: CompletionRequest) -> CompletionResponse:
        if any(c.id == "self-report" for m in request.messages for c in m.tool_calls):
            return CompletionResponse(content="Done for today.")
        reply = script(request)
        if reply.tool_calls:
            return reply
        return CompletionResponse(content="Reporting what today cost.", tool_calls=[
            ToolCall(id="self-report", name="report_cost", arguments={
                "tokens_in": 1000, "tokens_out": 100, "usd_cost": usd_per_wake,
                "task_label": "wake"})])
    return run


def pitch_pm(request: CompletionRequest) -> CompletionResponse:
    """A PM that pitches once, then trades its mandate (idea: a dead pod is replaced).

    Its rule is the workflow input's ``pitch_rules[<my name>]`` (none: it only trades). Turn 0
    reads its pod's pitches and its mandate. Turn 1: no pitch yet → it pitches the rule (naming
    the dead pod its ``post_mortem`` describes, if it was hired into one); else, once seeded, it
    places the mandate's orders. Turn 2 is done.
    """
    context = _context(request)
    me = context["me"]
    rules = context["input"].get("pitch_rules")
    rule = rules.get(me.get("name")) if isinstance(rules, dict) else None
    turn = _turn(request)
    if turn == 0:
        return CompletionResponse(content="Reading my pitches and my mandate.", tool_calls=[
            ToolCall(id="pitches", name="list_pitches", arguments={}),
            ToolCall(id="mandate", name="get_mandate", arguments={})])
    if turn == 1:
        results = _results(request)
        pitches = results.get("pitches")
        if type(pitches) is not list:
            return CompletionResponse(content="I could not read my pitches; nothing today.")
        if not pitches and isinstance(rule, dict):
            dead = context["input"].get("post_mortem")
            why = "Slow diffusion of information: recent winners keep winning."
            if isinstance(dead, dict):
                why += (f" The pod before me ({dead.get('pod_name')}) was closed after "
                        f"{dead.get('forward_days')} forward days; I trade other names.")
            return CompletionResponse(content="Pitching my rule.", tool_calls=[
                ToolCall(id="pitch", name="submit_pitch", arguments={
                    "hypothesis": why, "data_needed": "daily prices", "team": "the PM alone",
                    "budget_usd": 0.0, "rule": rule})])
        mandate = results.get("mandate")
        orders = mandate.get("orders") if isinstance(mandate, dict) else None
        if not orders:
            return CompletionResponse(content="Nothing to trade today.")
        return CompletionResponse(content=f"Placing {len(orders)} order(s).", tool_calls=[
            ToolCall(id=f"order:{i}:{o['ticker']}", name="place_order", arguments={
                "ticker": o["ticker"], "side": o["side"], "qty": o["qty"],
                "price_type": "market", "justification": "my funded rule's rebalance"})
            for i, o in enumerate(orders)])
    return CompletionResponse(content="Done for today.")


def team_pm(request: CompletionRequest) -> CompletionResponse:
    """A PM that builds a team, then pitches and trades as :func:`pitch_pm` (idea: a PM builds
    its team).

    Its ask is the input's ``team_asks[<my name>]`` (charter, model, budget_usd); with one, it
    pitches only once its pod's research holds a backtest (its analyst's). From the input's
    ``let_go_on[<my name>]`` (a date) on, it lets every working analyst go. Turn 0 reads its
    team, pitches, research, mandate and the clock; turn 1 acts; turn 2 is done.
    """
    context = _context(request)
    me, given = context["me"], context["input"]
    name = me.get("name")
    pick = lambda key: (given.get(key) or {}).get(name) if isinstance(given.get(key), dict) else None  # noqa: E731
    rule, ask, let_go_on = pick("pitch_rules"), pick("team_asks"), pick("let_go_on")
    turn = _turn(request)
    if turn == 0:
        return CompletionResponse(content="Reading my team, pitches, research and mandate.",
                                  tool_calls=[
            ToolCall(id="team", name="get_team", arguments={}),
            ToolCall(id="pitches", name="list_pitches", arguments={}),
            ToolCall(id="research", name="list_research_backtests", arguments={}),
            ToolCall(id="mandate", name="get_mandate", arguments={}),
            ToolCall(id="clock", name="get_clock", arguments={})])
    if turn > 1:
        return CompletionResponse(content="Done for today.")
    results = _results(request)
    team, pitches, research = results.get("team"), results.get("pitches"), results.get("research")
    clock = results.get("clock")
    if not (isinstance(team, dict) and type(pitches) is list and type(research) is list
            and isinstance(clock, dict)):
        return CompletionResponse(content="A read failed; nothing today.")
    calls: list[ToolCall] = []
    places = team.get("places") or []
    if isinstance(ask, dict) and not places:
        calls.append(ToolCall(id="ask", name="request_analyst", arguments={
            "charter": ask.get("charter"), "model": ask.get("model"),
            "budget_usd": ask.get("budget_usd")}))
    if type(let_go_on) is str and str(clock.get("now", ""))[:10] >= let_go_on:
        calls += [ToolCall(id=f"let-go:{p['id']}", name="let_go_analyst",
                           arguments={"place_id": p["id"]})
                  for p in places if p.get("status") == "working"]
    if not pitches and isinstance(rule, dict) and (ask is None or research):
        calls.append(ToolCall(id="pitch", name="submit_pitch", arguments={
            "hypothesis": "Slow diffusion of information: recent winners keep winning.",
            "data_needed": "daily prices", "team": "my analyst",
            "budget_usd": float((ask or {}).get("budget_usd") or 0.0), "rule": rule}))
    mandate = results.get("mandate")
    orders = mandate.get("orders") if isinstance(mandate, dict) else None
    calls += [ToolCall(id=f"order:{i}:{o['ticker']}", name="place_order", arguments={
        "ticker": o["ticker"], "side": o["side"], "qty": o["qty"], "price_type": "market",
        "justification": "my funded rule's rebalance"}) for i, o in enumerate(orders or [])]
    if not calls:
        return CompletionResponse(content="Nothing to do today.")
    return CompletionResponse(content=f"Acting: {len(calls)} call(s).", tool_calls=calls)


def research_analyst(request: CompletionRequest) -> CompletionResponse:
    """An analyst a PM hired (idea: a PM builds its team): each wake it backtests the next of
    the input's ``research_rules[<its PM's name>]`` it has not yet run, and tells its PM. Turn 0
    reads its pod's research; turn 1 backtests and messages; turn 2 is done."""
    context = _context(request)
    me, given = context["me"], context["input"]
    pm, pm_id = given.get("hired_by"), given.get("hired_by_id")
    rules = (given.get("research_rules") or {}).get(pm) if isinstance(
        given.get("research_rules"), dict) else None
    turn = _turn(request)
    if turn == 0:
        return CompletionResponse(content="Reading my pod's research.", tool_calls=[
            ToolCall(id="research", name="list_research_backtests", arguments={})])
    if turn > 1:
        return CompletionResponse(content="Done for today.")
    research = _results(request).get("research")
    if type(research) is not list or type(rules) is not list or type(pm_id) is not int:
        return CompletionResponse(content="Nothing I can do today.")
    mine = sum(1 for r in research if isinstance(r, dict) and r.get("agent_id") == me.get("id"))
    if mine >= len(rules):
        return CompletionResponse(content="Every rule I was given is tested.")
    return CompletionResponse(content="Testing the next rule.", tool_calls=[
        ToolCall(id="backtest", name="run_research_backtest", arguments={"rule": rules[mine]}),
        ToolCall(id="tell", name="send_message", arguments={
            "to": f"agent:{pm_id}", "body": f"Backtest {mine + 1} of {len(rules)} is in our "
                                            f"pod's research."})])


def firm_manager(request: CompletionRequest) -> CompletionResponse:
    """The firm's manager (idea: a manager chooses the hires): it reads the board, writes the
    input's ``manager.direction`` once, and picks for every open place still waiting for it:
    ``manager.pick`` is a candidate id, ``"other_child"`` (the first child of a pod other than
    the default's parent) or absent (silent: the law's default stands), with ``manager.brief``.
    Turn 0 reads the board; turn 1 acts; turn 2 is done."""
    context = _context(request)
    given = context["input"].get("manager")
    given = given if isinstance(given, dict) else {}
    turn = _turn(request)
    if turn == 0:
        return CompletionResponse(content="Reading the firm's board.", tool_calls=[
            ToolCall(id="board", name="read_board", arguments={})])
    if turn > 1:
        return CompletionResponse(content="Done for today.")
    board = _results(request).get("board")
    if not isinstance(board, dict):
        return CompletionResponse(content="I could not read the board; nothing today.")
    calls: list[ToolCall] = []
    if board.get("direction") is None and type(given.get("direction")) is str:
        calls.append(ToolCall(id="direction", name="set_direction",
                              arguments={"text": given["direction"]}))
    want = given.get("pick")
    for v in board.get("open_vacancies") or []:
        listed = v.get("candidates") or []
        if not listed or v.get("picked") is not None or want is None:
            continue
        if want == "other_child":
            choice = next((c["id"] for c in listed if not c.get("default")
                           and str(c.get("what", "")).startswith("a child of")), None)
        else:
            choice = want
        if choice is not None:
            calls.append(ToolCall(id=f"pick:{v['id']}", name="pick_hire", arguments={
                "vacancy_id": v["id"], "candidate": choice,
                "brief": str(given.get("brief") or "")}))
    if not calls:
        return CompletionResponse(content="Nothing to decide today.")
    return CompletionResponse(content=f"Deciding: {len(calls)} call(s).", tool_calls=calls)


#: The closed table: script name → policy. A spec names one of these keys.
def headline_analyst(request: CompletionRequest) -> CompletionResponse:
    """An analyst given headlines (idea: data packages): each wake it reads the clock and the last
    31 days of headlines, then sends its pod a ``signal`` (as :func:`ma_signal_analyst` does):
    ``flat`` for each name of the input's ``universe`` a headline ties to fraud, ``long`` for the
    rest. A refused or failed read ends the wake without a signal.
    """
    context = _context(request)
    pod_id = context["me"]["pod_id"]
    universe = context["input"].get("universe")
    if type(universe) is not list or not universe or pod_id is None:
        return CompletionResponse(content="No pod or no universe in my input; nothing to do.")
    turn = _turn(request)

    if turn == 0:
        return CompletionResponse(content="Reading the clock and the headlines.", tool_calls=[
            ToolCall(id="clock", name="get_clock"),
            ToolCall(id="news", name="read_headlines", arguments={"days": 31})])

    if turn == 1:
        results = _results(request)
        if any(v is None for v in results.values()):
            return CompletionResponse(content="A read failed; no signal today.")
        flagged = sorted({x["ticker"] for x in results["news"]["headlines"]
                          if x["ticker"] in universe and "fraud" in x["title"].lower()})
        signals = {t: "flat" if t in flagged else "long" for t in universe}
        payload = {"kind": "signal", "as_of": results["clock"]["now"], "signals": signals}
        body = ("Signal: flat " + ", ".join(flagged) + " (a fraud headline); long the rest"
                if flagged else "Signal: no fraud headline on our names; long them all")
        return CompletionResponse(content="Sending today's signal to my pod.", tool_calls=[
            ToolCall(id="signal", name="send_message", arguments={
                "to": f"pod:{pod_id}", "body": body, "structured_payload": payload})])

    return CompletionResponse(content="Done for today.")


SCRIPTS: Mapping[str, Script] = MappingProxyType({
    "moving-average-pm": moving_average_pm,
    "ma-signal-analyst": ma_signal_analyst,
    "signal-pm": signal_pm,
    "ma-signal-analyst-underreports": self_reporting(ma_signal_analyst, 0.01),
    "pitch-pm": pitch_pm,
    "team-pm": team_pm,
    "research-analyst": research_analyst,
    "firm-manager": firm_manager,
    "headline-analyst": headline_analyst,
})
