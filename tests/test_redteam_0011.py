"""RED-TEAM 0011 — attacks on cycle 0019's "a run records its world" (B-037, ADR-031).

Claim under attack: ``run_started`` carries the provider's ``world()`` record —
for the synthetic market law, origin, drift, volatility, symbols and
``key_fingerprint`` = first 128 bits of ``HMAC-SHA256(key, "fingerprint:v1")`` —
and :func:`~app.run_clock.install_run_clock` refuses a process whose provider
describes another world. Management reads the record through ``/events``.

The attacker is a firm agent (PM, analyst or management) with an API key,
reaching the world only through HTTP; it knows the published law (Art. 10). The
questions: does the record or the fingerprint help recover the key or predict a
bar; can an agent get a run served in another world, or make the check pass
wrongly (float round-trips, symbol case, dict order); can an agent turn the
check into a denial of service (a restart that fails); does anything new leak
through ``/events``, errors or 403s?

* Plain tests: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.db.models import AgentRole, Event
from app.ledger.events import EVENT_RUN_STARTED
from app.marketdata import StaticProvider, SyntheticProvider, set_provider
from app.registry.pods import create_pod, fund_pod
from app.registry.service import get_or_create_system_agent, register_agent
from app.run_clock import RunClockError, install_run_clock, start_backtest
from tests.support import world_key

UTC = timezone.utc
SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0, "SYNC": 20.0}
START = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def live_afterwards() -> Iterator[None]:
    yield
    set_clock(LiveClock())


def _open_world(SessionFactory, provider, *, start: datetime = START) -> dict[str, object]:
    """Open a backtest in ``provider``'s world with management, a PM and an analyst."""
    set_provider(provider)
    session = SessionFactory()
    try:
        start_backtest(session, start=start)
        _, admin = register_agent(session, name="management", role=AgentRole.management)
        pod = create_pod(session, name="desk")
        fund_pod(session, pod_id=pod.id, delta=100_000.0,
                 actor=get_or_create_system_agent(session), reason="red-team 0011")
        _, pm = register_agent(session, name="pm", role=AgentRole.pm, pod_id=pod.id)
        _, analyst = register_agent(session, name="analyst", role=AgentRole.analyst,
                                    pod_id=pod.id)
        session.commit()
        return {"admin": admin, "pm": pm, "analyst": analyst, "pod_id": pod.id}
    finally:
        session.close()


def _restart(db, provider):
    """A fresh process on the same database: live clock, the given provider."""
    set_clock(LiveClock())
    set_provider(provider)
    db.expire_all()
    return install_run_clock(db)


def _run_started_world(db) -> dict:
    db.expire_all()
    first = db.scalar(select(Event).order_by(Event.id).limit(1))
    assert first.type == EVENT_RUN_STARTED
    return first.payload_json["world"]


def _fingerprint(key: bytes) -> str:
    return hmac.new(key, b"fingerprint:v1", hashlib.sha256).hexdigest()[:32]


# =============================================================================
# HOLES
# =============================================================================

# HOLE (low): "one run, one world" holds only for the synthetic market. Every
# other provider records the default `{provider, reproducible: False}`, so a
# backtest opened on the config-selectable static table (`provider: "static"`,
# `static_prices`) restarts without complaint on a *different* table — the
# exact splice ADR-031 says the check exists to prevent ("a server restarted
# with ... other symbols ... would splice two markets into one ledger, and
# nothing in it would say where"). The static table *is* a function of its
# record; calling it non-reproducible lets two markets share one ledger.
# Not agent-reachable (only the operator chooses the provider and its prices),
# hence low. Fix: StaticProvider.world() records its normalised price table
# (reproducible: True), or start_backtest refuses a non-reproducible provider.
@pytest.mark.xfail(strict=True, reason="red-team 0011: a static run restarts on another table")
def test_hole_a_static_run_does_not_restart_on_another_table(SessionFactory, db):
    _open_world(SessionFactory, StaticProvider({"SYNA": 100.0}))
    with pytest.raises(RunClockError):
        _restart(db, StaticProvider({"SYNA": 1_000.0, "EVIL": 1.0}))


# =============================================================================
# HELD (regression guards)
# =============================================================================

def test_held_only_management_reads_the_world(SessionFactory, client):
    """PM and analyst get a bare 403 on /events (every filter), so the world
    record, its symbols and fingerprint are management's alone."""
    secret = secrets.token_bytes(32)
    world = _open_world(SessionFactory, SyntheticProvider(secret, SYMBOLS))
    fp = _fingerprint(secret)
    for role in ("pm", "analyst"):
        for params in ({}, {"type": "run_started"}, {"limit": 1000}):
            r = client.get("/events", headers=H(world[role]), params=params)
            assert r.status_code == 403, (role, params, r.text)
            assert fp not in r.text and "key_fingerprint" not in r.text
    r = client.get("/events", headers=H(world["admin"]), params={"type": "run_started"})
    assert r.status_code == 200
    assert r.json()[0]["payload_json"]["world"]["key_fingerprint"] == fp


def test_held_management_sees_a_name_not_the_key(SessionFactory, client):
    """Everything management can read in a fresh random world carries no
    spelling of the key, and the fingerprint is not any value the walk uses:
    no ``return:``/``noise:`` HMAC of any served day starts with it."""
    secret = secrets.token_bytes(32)
    world = _open_world(SessionFactory, SyntheticProvider(secret, SYMBOLS))
    texts = [client.get(p, headers=H(world["admin"]), params=q).text for p, q in [
        ("/events", {"limit": 1000}), ("/clock", {}), ("/agents", {}),
        ("/ohlcv/SYNA", {"interval": "1d", "start": "2023-12-01"})]]
    blob = "\n".join(texts)
    for spelling in (secret.hex(), secret.hex().upper(), secret.hex()[:32],
                     secret.hex()[32:], json.dumps(list(secret))[1:-1]):
        assert spelling not in blob
    fp = _fingerprint(secret)
    day = date(2023, 12, 1)
    while day < START.date():
        for domain in ("return", "noise"):
            for sym in SYMBOLS:
                digest = hmac.new(secret, f"{domain}:{sym}:{day}".encode(),
                                  hashlib.sha256).hexdigest()
                assert not digest.startswith(fp[:8])
        day += timedelta(days=1)


def test_held_the_fingerprint_is_no_brute_force_target_for_a_real_key():
    """Every guessable key (small ints in three encodings, their hashes, the
    public test keys) misses a random key's fingerprint. Companion: the same
    search *hits* a public test key — the fingerprint is an exact offline oracle,
    but no better than the served volumes red-team 0010 already showed are, and
    only a guessable key falls to it."""
    def guesses():
        for n in range(1 << 12):
            yield n.to_bytes(16, "big")
            yield n.to_bytes(32, "big")
            yield hashlib.sha256(str(n).encode()).digest()
            yield world_key(n)

    real = SyntheticProvider(secrets.token_bytes(32), SYMBOLS).world()["key_fingerprint"]
    assert not any(_fingerprint(k) == real for k in guesses())
    public = SyntheticProvider(world_key(11), SYMBOLS).world()["key_fingerprint"]
    assert next(k for k in guesses() if _fingerprint(k) == public) == world_key(11)


def test_held_equal_records_mean_equal_markets_even_for_aliased_keys():
    """HMAC zero-pads keys shorter than its block: ``K`` and ``K + b"\\0"`` are
    different bytes but the same world. The fingerprint names them as one, and
    the bars agree — so the check can neither split one market in two nor merge
    two markets under one name."""
    k = secrets.token_bytes(16)
    a, b = SyntheticProvider(k, SYMBOLS), SyntheticProvider(k + b"\0", SYMBOLS)
    assert a.world() == b.world()
    as_of = START + timedelta(days=40)
    assert (a.get_ohlcv("SYNA", start=date(2023, 1, 1), end=as_of.date(), interval="1d",
                        as_of=as_of)
            == b.get_ohlcv("SYNA", start=date(2023, 1, 1), end=as_of.date(), interval="1d",
                           as_of=as_of))
    c = SyntheticProvider(k + b"\1", SYMBOLS)
    assert c.world()["key_fingerprint"] != a.world()["key_fingerprint"]


@pytest.mark.parametrize("price", [5e-324, 0.1 + 0.2, 1e300, 123456789.123456789, 7])
def test_held_the_record_survives_the_ledger_bit_for_bit(SessionFactory, db, price):
    """Awkward floats (subnormal, 0.30000000000000004, huge, int) round-trip
    through the SQLite JSON payload exactly, and the same world restarts."""
    provider = SyntheticProvider(world_key(3), {"SYNA": price, "SYNB": 50.0})
    _open_world(SessionFactory, provider)
    recorded = _run_started_world(db)
    assert recorded == provider.world()
    assert all(type(v) is float for v in recorded["symbols"].values())
    assert _restart(db, SyntheticProvider(world_key(3), {"SYNA": price, "SYNB": 50.0}))


def test_held_normalisation_cannot_split_or_merge_worlds(SessionFactory, db):
    """Case, whitespace, dict order and int-vs-float spellings of the same world
    restart; one ulp on a start price, or a drift of -0.0 vs a real change, is
    judged by the market it serves."""
    _open_world(SessionFactory, SyntheticProvider(world_key(4), SYMBOLS))
    same = {" sync": 20, "synb ": 50.0, "SYNA": 100}
    assert _restart(db, SyntheticProvider(world_key(4), same)).now() == START
    assert _restart(db, SyntheticProvider(world_key(4), SYMBOLS, drift=0.0003,
                                          volatility=0.015)).now() == START
    nudged = dict(SYMBOLS, SYNA=math.nextafter(100.0, math.inf))
    with pytest.raises(RunClockError, match="symbols"):
        _restart(db, SyntheticProvider(world_key(4), nudged))
    with pytest.raises(RunClockError, match="drift"):
        _restart(db, SyntheticProvider(world_key(4), SYMBOLS, drift=0.00030000000000000003))
    with pytest.raises(RunClockError, match="volatility"):
        _restart(db, SyntheticProvider(world_key(4), SYMBOLS, volatility=0.0))


def test_held_the_refusal_names_fields_not_values(SessionFactory, db):
    """The error an operator (and any log) sees names what differs, never the
    recorded or installed fingerprint, prices or parameters."""
    k1, k2 = secrets.token_bytes(32), secrets.token_bytes(32)
    _open_world(SessionFactory, SyntheticProvider(k1, SYMBOLS))
    with pytest.raises(RunClockError) as exc:
        _restart(db, SyntheticProvider(k2, {"SYNA": 101.5}, drift=0.001, volatility=0.02))
    text = str(exc.value)
    for leak in (_fingerprint(k1), _fingerprint(k2), k1.hex(), k2.hex(),
                 "101.5", "0.001", "0.02", "100.0", "0.0003"):
        assert leak not in text
    assert all(f in text for f in ("key_fingerprint", "symbols", "drift", "volatility"))


def test_held_no_agent_action_breaks_the_next_restart(SessionFactory, client, db):
    """Denial of service through the check: after every write a PM, analyst and
    management can make (orders, messages, task reports, clock steps, bad
    tickers, 403s), the same world still restarts, at the advanced now — the
    world record lives in the first event, which no agent can write."""
    world = _open_world(SessionFactory, SyntheticProvider(world_key(6), SYMBOLS))
    pm, analyst, admin = world["pm"], world["analyst"], world["admin"]
    client.post("/orders", headers=H(pm), json={
        "ticker": "SYNA", "side": "buy", "qty": 3, "price_type": "market",
        "justification": "red-team 0011"})
    client.post("/orders", headers=H(pm), json={
        "ticker": "syna ", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "case"})
    client.post("/orders", headers=H(pm), json={
        "ticker": "NOTINWORLD", "side": "buy", "qty": 1, "price_type": "market",
        "justification": "unknown symbol"})
    client.post("/messages", headers=H(analyst), json={
        "to": "pm", "type": "run_started", "body": "world: {}",
        "structured_payload": {"world": {"provider": "evil"}}})
    client.post("/clock/advance", headers=H(pm), json={"days": 1})          # 403
    client.get("/events", headers=H(analyst))                               # 403
    r = client.post("/clock/advance", headers=H(admin), json={"days": 2})
    assert r.status_code == 200, r.text
    clock = _restart(db, SyntheticProvider(world_key(6), dict(reversed(SYMBOLS.items()))))
    assert clock.now() == START + timedelta(days=2)
    db.expire_all()
    starts = db.scalars(select(Event).where(Event.type == EVENT_RUN_STARTED)).all()
    assert len(starts) == 1
