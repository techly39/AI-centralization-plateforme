"""RED-TEAM 0010 — attacks on cycle 0018's seeded synthetic market (B-004c, ADR-030).

Claim under attack: :class:`~app.marketdata.SyntheticProvider` is a sealed
``MarketDataProvider`` whose day ``D`` is a pure function of (world, symbol, D);
it serves a close only once its day has ended, never shows a second market on
another route, and — because the world's key is secret — an agent cannot know
tomorrow.

The hole found here (a small integer seed brute-forced from served volumes) was
fixed in the same cycle by keying the walk with ≥ 128 random bits through
HMAC-SHA256 and drawing wicks/volumes from a separate domain (ADR-030
amendment). The hole test now attacks the fixed law the same way: the attacker
knows the formula and searches every guessable key.

The attacker is a firm PM with an API key, reaching the market only through
HTTP (``/price``, ``/ohlcv``, ``POST /orders``). It is assumed to know the
algorithm (Kerckhoffs: the code is the law, and laws are published, Art. 10).

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

import pytest

from app.clock import LiveClock, set_clock
from app.db.models import AgentRole
from app.marketdata import SyntheticProvider, set_provider
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import start_backtest
from tests.support import world_key

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


def _open_world(SessionFactory, *, key: bytes, start: datetime) -> dict[str, object]:
    set_provider(SyntheticProvider(key, SYMBOLS))
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

def _attacker_volume(key: bytes, symbol: str, day: date) -> int:
    """Volume as the published formula derives it: bits of the day's noise HMAC."""
    digest = hmac.new(key, f"noise:{symbol}:{day.isoformat()}".encode(),
                      hashlib.sha256).digest()
    u4 = ((int.from_bytes(digest[8:16], "big") >> 11) + 0.5) / float(1 << 53)
    return int(1e5 + 9e5 * u4)


def _guessable_keys(search: int):
    """Every key an attacker can enumerate: small ints in the usual encodings,
    their hashes, and the public test keys."""
    for n in range(search):
        yield n.to_bytes(16, "big")
        yield n.to_bytes(32, "big")
        yield hashlib.sha256(str(n).encode()).digest()
        yield world_key(n)


def _brute_force_key(observed: list[tuple[date, int]], symbol: str,
                     search: int = 1 << 12) -> bytes | None:
    """The key whose noise reproduces every served volume, if a guessable one does."""
    first_day, first_volume = observed[0]
    for key in _guessable_keys(search):
        if _attacker_volume(key, symbol, first_day) != first_volume:
            continue
        if all(_attacker_volume(key, symbol, d) == v for d, v in observed[1:]):
            return key
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
# FIXED (cycle 18, ADR-030 amendment): a world is a >= 128-bit secret key
# (`SyntheticProvider` refuses less; config has no default and reads it from the
# environment only); returns and noise are separate HMAC domains.
def test_hole_a_pm_cannot_recover_the_seed_and_compute_tomorrow(
        SessionFactory, client, live_afterwards):
    world = _open_world(SessionFactory, key=secrets.token_bytes(32), start=PROBE_START)
    pm = world["pm"]
    bars = _get(client, pm, "/ohlcv/SYNA", interval="1d")["bars"]
    observed = [(datetime.fromisoformat(b["ts"]).date(), int(b["volume"])) for b in bars[-3:]]

    recovered = _brute_force_key(observed, "SYNA")
    prediction = None
    if recovered is not None:
        # The attacker's own replica of the world, a week ahead of the clock.
        replica = SyntheticProvider(recovered, SYMBOLS)
        prediction = replica.get_price("SYNA", as_of=PROBE_START + timedelta(days=7)).price

    _advance(client, world["admin"], days=7)
    actual = _get(client, pm, "/price/SYNA")["price"]
    assert prediction != actual, (
        f"key {recovered!r} recovered from 3 served volumes; next week's close "
        f"{actual} was known a week early"
    )


def test_the_attack_is_real_on_a_guessable_key():
    """Not vacuous: the same search recovers a public test key from its volumes —
    which is why a real world's key never comes from tests/support.py."""
    provider = SyntheticProvider(world_key(7), SYMBOLS)
    bars = provider.get_ohlcv("SYNA", start=date(2023, 12, 1), end=date(2024, 1, 2),
                              interval="1d", as_of=PROBE_START)
    observed = [(b.ts.date(), int(b.volume)) for b in bars[-3:]]
    assert _brute_force_key(observed, "SYNA") == world_key(7)


# =============================================================================
# HELD (regression guards)
# =============================================================================

def test_held_no_close_or_week_before_its_end_at_the_midnight_edge(
        SessionFactory, client, live_afterwards):
    """Sunday 23:59: Sunday's close and the week Mon 4 – Sun 10 are unknown; at
    Monday 00:00 both appear, and /price, /ohlcv 1d, 1wk and the fill agree."""
    world = _open_world(SessionFactory, key=world_key(5), start=SUNDAY_2359)
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
    world = _open_world(SessionFactory, key=world_key(9), start=datetime(2024, 4, 3, 12, tzinfo=UTC))
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
    same in two worlds that share nothing (different keys) — no oracle."""
    pm = _open_world(SessionFactory, key=world_key(1), start=PROBE_START)["pm"]
    answers = []
    for n in (1, 2):
        set_provider(SyntheticProvider(world_key(n), SYMBOLS))
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
    """Guard for B-037: when run_started records the world, the key must not
    become readable — management agents read /events."""
    secret = secrets.token_bytes(32)
    world = _open_world(SessionFactory, key=secret, start=PROBE_START)
    seen = []
    for key in (world["pm"], world["admin"]):
        for path, params in [("/clock", {}), ("/price/SYNA", {}),
                             ("/ohlcv/SYNA", {"interval": "1d"}),
                             (f"/portfolio/{world['pod_id']}", {}),
                             ("/events", {"limit": 1000})]:
            r = client.get(path, headers=H(key), params=params)
            seen.append(r.text)
    for spelling in (secret.hex(), secret.hex().upper(), json.dumps(secret.hex())):
        assert not any(spelling in text for text in seen)


def test_held_the_widest_window_is_bounded_work(SessionFactory, client, live_afterwards):
    """start=0001-01-01 on every interval: clamped at ORIGIN, ~10^5 cheap steps."""
    world = _open_world(SessionFactory, key=world_key(3), start=PROBE_START)
    pm = world["pm"]
    for interval in ("1d", "1wk", "1mo"):
        began = time.perf_counter()
        resp = client.get("/ohlcv/SYNA", headers=H(pm),
                          params={"interval": interval, "start": "0001-01-01"})
        assert resp.status_code == 200, resp.text
        assert time.perf_counter() - began < 5.0, interval
