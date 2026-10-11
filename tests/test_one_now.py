"""One "now" for the whole world (B-004b, ADR-029).

``GET /clock`` tells an agent the ledger's now (ADR-026): ``max(clock, latest
stamp)``. Every other reader of "now" in physics — the quote route, the OHLCV
defaults, the portfolio valuation, pod metrics, the leaderboard, the price an
order fills at, the pending-order sweep — must answer at that same moment.
Otherwise, after the clock steps back behind the ledger (ADR-025), an agent is
told one time, shown prices from another and stamped with a third.

The scenario: the ledger holds a stamp on 10 June; the clock then steps back to
5 June. Every answer must be the 10 June world (the close of 9 June), never the
5 June one.
"""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.marketdata import set_provider
from tests.support import HistoricalProvider

APP = Path(__file__).resolve().parent.parent / "app"

LEDGER_DAY = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)
STEPPED_BACK = datetime(2026, 6, 5, 15, 0, tzinfo=timezone.utc)
#: AAPL closes 100 + day of month: 9 June closes at 109, 4 June at 104.
SERIES = {"AAPL": {date(2026, 6, d): 100.0 + d for d in range(1, 13)}}
KNOWN_CLOSE = 109.0
STALE_CLOSE = 104.0


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture
def stepped_back(frozen_clock, client, desk, admin_key):
    """A desk whose ledger reached 10 June, then a clock stepped back to 5 June."""
    set_provider(HistoricalProvider(SERIES))
    _, _, pm_key = desk
    frozen_clock.set(LEDGER_DAY)
    first = client.post("/orders", headers=H(pm_key), json={
        "ticker": "AAPL", "side": "buy", "qty": 10.0,
        "price_type": "market", "justification": "stamp the ledger on 10 June",
    })
    assert first.status_code == 201, first.text
    assert first.json()["fill_price"] == KNOWN_CLOSE
    frozen_clock.set(STEPPED_BACK)
    now = datetime.fromisoformat(client.get("/clock", headers=H(pm_key)).json()["now"])
    assert now == LEDGER_DAY
    return pm_key, admin_key


def test_the_quote_is_at_the_ledgers_now(client, stepped_back) -> None:
    pm_key, _ = stepped_back
    resp = client.get("/price/AAPL", headers=H(pm_key))
    assert resp.status_code == 200, resp.text
    assert resp.json()["price"] == KNOWN_CLOSE
    assert datetime.fromisoformat(resp.json()["as_of"]) == datetime(
        2026, 6, 10, tzinfo=timezone.utc
    )


def test_ohlcv_defaults_end_at_the_ledgers_today(client, stepped_back) -> None:
    pm_key, _ = stepped_back
    resp = client.get("/ohlcv/AAPL", headers=H(pm_key))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert date.fromisoformat(body["end"]) == LEDGER_DAY.date() + timedelta(days=1)
    assert body["bars"][-1]["close"] == KNOWN_CLOSE


def test_the_portfolio_is_valued_at_the_ledgers_now(client, stepped_back) -> None:
    pm_key, _ = stepped_back
    resp = client.get("/portfolio/1", headers=H(pm_key))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert datetime.fromisoformat(body["as_of"]) == LEDGER_DAY
    assert body["positions"][0]["last_price"] == KNOWN_CLOSE


def test_pod_metrics_are_as_of_the_ledgers_now(client, stepped_back) -> None:
    _, admin_key = stepped_back
    resp = client.get("/metrics/pod/1", headers=H(admin_key))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert datetime.fromisoformat(body["as_of"]) == LEDGER_DAY
    assert body["capital"]["positions_value"] == pytest.approx(10 * KNOWN_CLOSE)


def test_the_leaderboard_is_as_of_the_ledgers_now(client, stepped_back) -> None:
    _, admin_key = stepped_back
    resp = client.get("/metrics/leaderboard", headers=H(admin_key))
    assert resp.status_code == 200, resp.text
    assert datetime.fromisoformat(resp.json()["as_of"]) == LEDGER_DAY


def test_an_order_fills_at_the_price_of_the_moment_it_is_stamped(client, stepped_back) -> None:
    pm_key, _ = stepped_back
    resp = client.post("/orders", headers=H(pm_key), json={
        "ticker": "AAPL", "side": "buy", "qty": 1.0,
        "price_type": "market", "justification": "priced where stamped",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert datetime.fromisoformat(body["created_at"]) == LEDGER_DAY
    assert body["fill_price"] == KNOWN_CLOSE
    assert body["fill_price"] != STALE_CLOSE


def test_the_sweep_prices_at_the_ledgers_now(client, stepped_back, db) -> None:
    """A limit between the two closes: the stale 104 would fill it, 109 must not."""
    from app.oms.monitor import check_pending_orders

    pm_key, _ = stepped_back
    resp = client.post("/orders", headers=H(pm_key), json={
        "ticker": "AAPL", "side": "buy", "qty": 1.0, "price_type": "limit",
        "limit_price": 106.0, "justification": "only below 106",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"
    check_pending_orders(db)
    db.expire_all()
    orders = client.get("/orders", headers=H(pm_key)).json()
    limit = next(o for o in orders if o["id"] == resp.json()["id"])
    assert limit["status"] == "pending", limit


# --- The static law ----------------------------------------------------------

#: Every raw read of time in ``app/``, counted per file, and why. A new reader of
#: time must use ``ledger_now(session)``; one that cannot must change a count
#: here with its reason, in review. Counted per read, not per file: a listed
#: file gaining one more read is as red as an unlisted one (auditor, cycle 17).
ALLOWED_TIME_READS: dict[str, tuple[int, str]] = {
    "clock.py": (2, "the clocks themselves"),
    "ledger/events.py": (2, "append_event and ledger_now: the floor is applied in SQL"),
    "run_clock.py": (3, "the backtest controller: raw clock vs ledger_now, wall_now bound"),
    "marketdata/yfinance_provider.py": (1, "wall_now: the live quote's 60 s window (ADR-028)"),
    "cli.py": (1, "prints the start of a run it has just created"),
    "main.py": (3, "request log line and its elapsed ms: diagnostics, not physics"),
    # B-028: these rows should copy their event's held stamp, not read a clock.
    "metrics/reporting.py": (3, "B-028 (Cost.ts, Task.started_at/ended_at)"),
    "bus/messages.py": (1, "B-028 (Message.ts)"),
    "registry/service.py": (2, "B-028 (Agent.created_at)"),
    "registry/pods.py": (1, "B-028 (Allocation.ts)"),
}

#: Attribute names that read a clock, called or not (``f = clock.now`` counts).
_CLOCK_ATTRS = {"now", "utcnow", "today"}


def _is_time_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        # x.now / datetime.utcnow / date.today, and anything off the time module.
        return node.attr in _CLOCK_ATTRS or (
            isinstance(node.value, ast.Name) and node.value.id == "time"
        )
    if isinstance(node, ast.Name):
        return node.id == "wall_now" and isinstance(node.ctx, ast.Load)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        # getattr(clock, "now") spells the attribute as a string.
        return node.func.id == "getattr" and any(
            isinstance(a, ast.Constant) and a.value in _CLOCK_ATTRS for a in node.args
        )
    return False


def _time_reads() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        n = sum(1 for node in ast.walk(tree) if _is_time_read(node))
        if n:
            found[path.relative_to(APP).as_posix()] = n
    return found


def test_no_physics_reader_of_now_bypasses_the_ledger() -> None:
    allowed = {f: n for f, (n, _) in ALLOWED_TIME_READS.items()}
    found = _time_reads()
    over = {f: n for f, n in found.items() if n > allowed.get(f, 0)}
    assert not over, f"read time with ledger_now(session), not the clock: {over}"


def test_the_allowlist_is_exact() -> None:
    allowed = {f: n for f, (n, _) in ALLOWED_TIME_READS.items()}
    under = {f: n for f, n in allowed.items() if _time_reads().get(f, 0) < n}
    assert not under, f"fewer raw reads than listed — lower the count: {under}"


@pytest.mark.parametrize("source", [
    "get_clock().now()",
    "f = clock.now",
    "getattr(clock, 'now')()",
    "datetime.utcnow()",
    "date.today()",
    "time.time()",
    "time.monotonic()",
    "wall_now()",
])
def test_the_detector_sees_every_spelling(source: str) -> None:
    assert any(_is_time_read(n) for n in ast.walk(ast.parse(source))), source
