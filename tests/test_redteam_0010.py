"""RED-TEAM 0010 — attacks on cycle 0018's seeded synthetic market (B-004c, ADR-030).

Claim under attack: :class:`~app.marketdata.SyntheticProvider` is a sealed
``MarketDataProvider`` whose day ``D`` is a pure function of
``sha256("{seed}:{symbol}:{D}")``; it serves a close only once its day has
ended, never shows a second market on another route, and — because the seed is
config, not agent-visible — an agent cannot know tomorrow.

The attacker is a firm PM with an API key, reaching the market only through
HTTP (``/price``, ``/ohlcv``, ``POST /orders``). It is assumed to know the
algorithm (Kerckhoffs: the code is the law, and laws are published, Art. 10).

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

import pytest

from app.clock import LiveClock, set_clock
from app.config import MarketDataConfig
from app.db.models import AgentRole
from app.marketdata import SyntheticProvider, set_provider
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import start_backtest

UTC = timezone.utc
SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0, "SYNC": 20.0}
#: The probe's start (tests/test_phase3_probe.py).
PROBE_START = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
#: Sunday 10 March 2024, one minute before midnight: day *and* week edge.
SUNDAY_2359 = datetime(2024, 3, 10, 23, 59, tzinfo=UTC)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


def _open_world(SessionFactory, *, seed: int, start: datetime) -> dict[str, object]:
    set_provider(SyntheticProvider(seed, SYMBOLS))
    session = SessionFactory()
    try:
        start_backtest(session, start=start)
        _, admin_key = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="desk")
        fund_pod(session, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(session), reason="red-team 0010")
        _, pm_key = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
        session.commit()
        return {"admin": admin_key, "pm": pm_key, "pod_id": pod.id}
    finally:
        session.close()


def _get(client, key: str, path: str, **params) -> dict:
    resp = client.get(path, headers=H(key), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _advance(client, admin: str, **step) -> None:
    resp = client.post("/clock/advance", headers=H(admin), json=step)
    assert resp.status_code == 200, resp.text


# --- The attacker's offline replica of the published law --------------------

def _attacker_volume(seed: int, symbol: str, day: date) -> int:
    """Volume as the published formula derives it: raw bits of the day's hash."""
    digest = hashlib.sha256(f"{seed}:{symbol}:{day.isoformat()}".encode()).digest()
    u4 = ((int.from_bytes(digest[24:32], "big") >> 11) + 0.5) / float(1 << 53)
    return int(1e5 + 9e5 * u4)


def _brute_force_seed(observed: list[tuple[date, int]], symbol: str,
                      search: int = 1 << 16) -> int | None:
    """The seed whose hash reproduces every served volume, if a small one does."""
    first_day, first_volume = observed[0]
    for seed in range(search):
        if _attacker_volume(seed, symbol, first_day) != first_volume:
            continue
        if all(_attacker_volume(seed, symbol, d) == v for d, v in observed[1:]):
            return seed
    return None


# =============================================================================
# HOLES
# =============================================================================

# HOLE (high): the seed is low-entropy and the served bars carry raw bits of the
# keyed hash, so a PM recovers the seed from /ohlcv and knows every future close.
#
# `synthetic_seed` is a plain int (config default 0; the probe uses 11 and 12;
# nothing asks for entropy, and the field caps it at 53 bits anyway). Every
# served daily bar's `volume` is `int(1e5 + 9e5 * u4)` — ~20 bits taken straight
# from `sha256(f"{seed}:{symbol}:{day}")` — and its wick hands over ~50 more
# (`high = max(o, c) * (1 + vol*u3/2)`, vol a known constant). Three bars pin the
# seed; a 2^16 search takes a fraction of a second, 2^32 an afternoon on a laptop.
# With the seed, the walk is a pure function: the attacker computes tomorrow's
# close before the clock gets there, and passes any backtest gate it likes.
#
# Fix: key the walk with a high-entropy secret the agents never see — e.g.
# `HMAC-SHA256(secret_256bit, f"{symbol}:{day}")`, the secret drawn per world
# and kept out of every agent-visible surface (including B-037's run_started,
# which management can read via /events); refuse short seeds. Separately
# derive wick/volume from a different key than the return, so served noise is
# not a window onto the return generator. Obscurity of the formula is not a fix.
@pytest.mark.xfail(strict=True, reason="RED-TEAM 0010: synthetic seed recoverable from "
                   "served volumes; future closes then computable")
@pytest.mark.parametrize("seed", [MarketDataConfig().synthetic_seed, 11],
                         ids=["config-default", "probe-seed"])
def test_hole_a_pm_cannot_recover_the_seed_and_compute_tomorrow(
        seed, SessionFactory, client, live_afterwards):
    world = _open_world(SessionFactory, seed=seed, start=PROBE_START)
    pm = world["pm"]
    bars = _get(client, pm, "/ohlcv/SYNA", interval="1d")["bars"]
    observed = [(datetime.fromisoformat(b["ts"]).date(), int(b["volume"])) for b in bars[-3:]]

    recovered = _brute_force_seed(observed, "SYNA")
    prediction = None
    if recovered is not None:
        # The attacker's own replica of the world, a week ahead of the clock.
        replica = SyntheticProvider(recovered, SYMBOLS)
        prediction = replica.get_price("SYNA", as_of=PROBE_START + timedelta(days=7)).price

    _advance(client, world["admin"], days=7)
    actual = _get(client, pm, "/price/SYNA")["price"]
    assert prediction != actual, (
        f"seed {recovered} recovered from 3 served volumes; next week's close "
        f"{actual} was known a week early"
    )


# =============================================================================
# HELD (regression guards)
# =============================================================================

def test_held_no_close_or_week_before_its_end_at_the_midnight_edge(
        SessionFactory, client, live_afterwards):
    """Sunday 23:59: Sunday's close and the week Mon 4 – Sun 10 are unknown; at
    Monday 00:00 both appear, and /price, /ohlcv 1d, 1wk and the fill agree."""
    world = _open_world(SessionFactory, seed=5, start=SUNDAY_2359)
    pm = world["pm"]
    sunday, monday_wk = "2024-03-10", "2024-03-04"

    daily = _get(client, pm, "/ohlcv/SYNA", interval="1d")["bars"]
    assert daily[-1]["ts"].startswith("2024-03-09")
    weekly = _get(client, pm, "/ohlcv/SYNA", interval="1wk",
                  start="2024-01-01")["bars"]
    assert not any(b["ts"].startswith(monday_wk) for b in weekly)
    monthly = _get(client, pm, "/ohlcv/SYNA", interval="1mo",
                   start="2023-01-01")["bars"]
    assert monthly[-1]["ts"].startswith("2024-02-01")
    quote = _get(client, pm, "/price/SYNA")
    assert quote["price"] == daily[-1]["close"]
    assert datetime.fromisoformat(quote["as_of"]) <= SUNDAY_2359

    _advance(client, world["admin"], minutes=1)
    daily = _get(client, pm, "/ohlcv/SYNA", interval="1d")["bars"]
    assert daily[-1]["ts"].startswith(sunday)
    weekly = _get(client, pm, "/ohlcv/SYNA", interval="1wk", start="2024-01-01")["bars"]
    assert weekly[-1]["ts"].startswith(monday_wk)
    assert weekly[-1]["close"] == daily[-1]["close"]
    price = _get(client, pm, "/price/SYNA")["price"]
    assert price == daily[-1]["close"]
    resp = client.post("/orders", headers=H(pm), json={
        "ticker": "SYNA", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "red-team 0010"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "filled"
    assert resp.json()["fill_price"] == price


def test_held_one_market_on_every_route(SessionFactory, client, live_afterwards):
    """1wk/1mo bars are exact aggregates of the 1d bars served on the same call
    window — no second market to arbitrage between routes."""
    world = _open_world(SessionFactory, seed=9, start=datetime(2024, 4, 3, 12, tzinfo=UTC))
    pm = world["pm"]
    daily = _get(client, pm, "/ohlcv/SYNB", interval="1d", start="2024-01-01")["bars"]
    by_day = {b["ts"][:10]: b for b in daily}
    for b in _get(client, pm, "/ohlcv/SYNB", interval="1wk", start="2024-01-01")["bars"]:
        first = datetime.fromisoformat(b["ts"]).date()
        days = [by_day[(first + timedelta(days=k)).isoformat()] for k in range(7)]
        assert b["open"] == days[0]["open"] and b["close"] == days[-1]["close"]
        assert b["high"] == max(d["high"] for d in days)
        assert b["low"] == min(d["low"] for d in days)


def test_held_errors_do_not_depend_on_the_future(SessionFactory, client, live_afterwards):
    """Unknown symbol, pre-origin window and today-only window: each answer is the
    same in two worlds that share nothing (different seeds) — no oracle."""
    pm = _open_world(SessionFactory, seed=1, start=PROBE_START)["pm"]
    answers = []
    for seed in (1, 2):
        set_provider(SyntheticProvider(seed, SYMBOLS))
        row = []
        for path, params in [
            ("/price/NOPE", {}),
            ("/ohlcv/NOPE", {"interval": "1d"}),
            ("/ohlcv/SYNA", {"interval": "1d", "start": "1990-01-01", "end": "1999-06-01"}),
            ("/ohlcv/SYNA", {"interval": "1d", "start": "2024-01-02", "end": "2024-01-03"}),
            ("/ohlcv/SYNA", {"interval": "1h"}),
            ("/ohlcv/SYNA", {"interval": "1d", "start": "2024-01-03"}),
        ]:
            r = client.get(path, headers=H(pm), params=params)
            row.append((r.status_code, r.json()))
        answers.append(row)
    assert answers[0] == answers[1]


def test_held_no_agent_visible_surface_carries_the_seed(SessionFactory, client, live_afterwards):
    """Guard for B-037: when run_started records the world, the seed must not
    become readable — management agents read /events."""
    seed = 987_654_321_987
    world = _open_world(SessionFactory, seed=seed, start=PROBE_START)
    seen = []
    for key in (world["pm"], world["admin"]):
        for path, params in [("/clock", {}), ("/price/SYNA", {}),
                             ("/ohlcv/SYNA", {"interval": "1d"}),
                             (f"/portfolio/{world['pod_id']}", {}),
                             ("/events", {"limit": 1000})]:
            r = client.get(path, headers=H(key), params=params)
            seen.append(r.text)
    assert not any(str(seed) in text for text in seen)
    assert not any(json.dumps(seed) in text for text in seen)


def test_held_the_widest_window_is_bounded_work(SessionFactory, client, live_afterwards):
    """start=0001-01-01 on every interval: clamped at ORIGIN, ~10^5 cheap steps."""
    world = _open_world(SessionFactory, seed=3, start=PROBE_START)
    pm = world["pm"]
    for interval in ("1d", "1wk", "1mo"):
        began = time.perf_counter()
        resp = client.get("/ohlcv/SYNA", headers=H(pm),
                          params={"interval": interval, "start": "0001-01-01"})
        assert resp.status_code == 200, resp.text
        assert time.perf_counter() - began < 5.0, interval
