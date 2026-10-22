"""RED-TEAM (idea: a pitch is argued before its seed; branch idea/pitch-debate).

Each test here is a hole found by the red-team against the debate law: it FAILS on the branch as
red-teamed, and passes once the Builder fixes the physics. Severity in each docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.capital.service import sweep
from app.clock import LiveClock, set_clock
from app.config import CapitalConfig, GenerationConfig, get_settings
from app.db.models import Event
from app.ledger.events import EVENT_PITCH_JUDGED, EVENT_PITCH_SUBMITTED, append_event
from app.marketdata import get_provider
from app.registry.pods import create_pod
from app.registry.service import get_or_create_system_agent
from app.run_clock import advance, start_backtest

RULE = {"language": "strategy-v1", "signal": "momentum", "lookback": 20, "rebalance_every": 5,
        "side": "long_only", "gross": 1.0, "universe": ["AAPL", "MSFT"], "top_n": 1}


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def september(SessionFactory):
    s = SessionFactory()
    try:
        start_backtest(s, start=datetime(2024, 9, 1, tzinfo=UTC))
        s.commit()
    finally:
        s.close()
    yield
    set_clock(LiveClock())


@pytest.fixture
def law(monkeypatch, september):
    monkeypatch.setattr(get_settings(), "capital", CapitalConfig(debate_days=2))


def _pitch(db, pod_id: int, *, eligible: bool = True, rule: dict | None = None) -> int:
    """A pitch the gates judged, as physics writes it."""
    submitted = append_event(db, type=EVENT_PITCH_SUBMITTED, actor_agent_id=None, payload={
        "pod_id": pod_id, "agent_id": None, "hypothesis": "momentum", "data_needed": "closes",
        "team": "me", "budget_usd": 1.0, "rule": rule or RULE})
    append_event(db, type=EVENT_PITCH_JUDGED, actor_agent_id=None, payload={
        "pitch_id": submitted.id, "pod_id": pod_id, "eligible": eligible, "gates": [],
        "performance": {}, "window": {}, "attempts": 1})
    db.commit()
    return submitted.id


def _morning(db) -> dict:
    advance(db, minutes=24 * 60, actor_agent_id=get_or_create_system_agent(db).id)
    return sweep(db, provider=get_provider())


def _types(db, type_: str) -> list[dict]:
    db.expire_all()
    return [e.payload_json for e in db.scalars(select(Event).where(Event.type == type_)
                                               .order_by(Event.id))]


# --- 1. the generation law: a debate that closed unpaid shelters its pod forever -----------------

def test_redteam_debate_closed_unpaid_shelters_the_pod_from_let_go_forever(
        db, client, monkeypatch, september, agent_factory, runtime_key):
    """RED-TEAM (severity: medium). ``debating_pods`` counts every debate with no capital answer,
    whatever its day: once the window has closed and the sweep decides "pay", a centre too short to
    pay the seed (``continue``) -- or a copy check that raises MarketDataError each morning (a
    universe whose feed ends after the pitch day) -- leaves the debate unanswered for ever, and the
    pod "stays" at every month's end. Without the law the same pod (eligible, never paid) is let go
    after its grace. The idea only spares a pod whose pitch is *in its window* at the month's end;
    this one's window closed on Sep 4."""
    monkeypatch.setattr(get_settings(), "capital",
                        CapitalConfig(debate_days=2, firm_capital_usd=100_000.0))  # < one seed
    monkeypatch.setattr(get_settings(), "generation", GenerationConfig(on=True, grace_days=20))
    pod = create_pod(db, name="alpha").id
    agent_factory("alpha-pm", "pm", pod)
    _pitch(db, pod)

    def go(days: int) -> None:
        r = client.post("/clock/advance", headers=h(runtime_key), json={"days": days})
        assert r.status_code == 200, r.text

    go(1)                                   # Sep 2: the debate opens, closes Sep 4
    [opened] = _types(db, "debate_opened")
    assert opened["closes_on"] == "2024-09-04"
    go(29)                                  # Oct 1: the month turns, the window long closed
    assert _types(db, "capital_seeded") == []
    [gen] = _types(db, "generation_ended")
    row = {p["pod_name"]: p for p in gen["pods"]}["alpha"]
    assert row["verdict"] == "let_go", (
        f"a pod whose debate closed on Sep 4 and was never paid is spared: {row['why']!r}")


# --- 2. cross-pod reads through the debate's refusals --------------------------------------------

def test_redteam_argue_probe_reads_another_pods_gates_verdict(db, law, client, agent_factory):
    """RED-TEAM (severity: medium). ``argue`` looks for a debate first and answers the
    no-debate case with :func:`_no_debate_reason` before it asks whose pitch it is, so a PM probing
    any id learns from the 409 whether another pod's pitch exists and whether the gates refused it
    ("pitch N is not eligible: the gates refused it"), versus "another pod's" (403) for one in
    debate, or "has no debate ... (its pod ... seeded, a long-only rule)" for an eligible one not
    debated. A PM reads only its own pod's pitches (READ_PITCHES; others need READ_CROSS_POD).
    Another pod's pitch must answer the same 403 whether it is eligible or not."""
    a, b = create_pod(db, name="alpha").id, create_pod(db, name="beta").id
    _, pm_a = agent_factory("alpha-pm", "pm", a)
    refused_b = _pitch(db, b, eligible=False)
    debated_b = _pitch(db, b)
    _morning(db)
    say = {"text": "probe"}
    in_debate = client.post(f"/debates/{debated_b}/argue", headers=h(pm_a), json=say)
    assert in_debate.status_code == 403
    probe = client.post(f"/debates/{refused_b}/argue", headers=h(pm_a), json=say)
    assert probe.status_code == 403, (
        f"another pod's refused pitch answers {probe.status_code}: {probe.json()['detail']!r}")
    assert "eligible" not in probe.json()["detail"]


def test_redteam_debate_read_probe_tells_another_pod_has_a_pitch_in_debate(
        db, law, client, agent_factory):
    """RED-TEAM (severity: low). ``GET /debates/{id}`` answers 404 "has no debate" for another
    pod's pitch with no debate and 403 "another pod's" for one in debate: an analyst or PM learns,
    id by id, which of the other pods' pitches the gates passed and when (the debate opened). The
    two must be indistinguishable to a reader outside the pod."""
    a, b = create_pod(db, name="alpha").id, create_pod(db, name="beta").id
    _, analyst_a = agent_factory("alpha-analyst", "analyst", a)
    refused_b = _pitch(db, b, eligible=False)
    debated_b = _pitch(db, b)
    _morning(db)
    one = client.get(f"/debates/{refused_b}", headers=h(analyst_a))
    two = client.get(f"/debates/{debated_b}", headers=h(analyst_a))
    assert one.status_code == two.status_code, (one.status_code, two.status_code)


# --- 3. a hold dodged by a pitch queued during the debate ----------------------------------------

def test_redteam_hold_is_dodged_by_the_same_rule_queued_during_the_debate(
        db, law, client, agent_factory):
    """RED-TEAM (severity: low). ``submit_pitch`` takes a pod's second pitch while its first is in
    debate (its own pod is never compared with itself), and ``eligible_unseeded`` hands the pod's
    next eligible pitch to the sweep the morning after a hold. So a PM queues the identical rule
    while the first is argued; the manager's hold refuses only pitch #1, pitch #2 opens a fresh
    debate, and if the manager does not notice and hold again, silence pays the very rule it held.
    The hold should bind the rule the manager held (or the pod's pitches queued before it)."""
    a = create_pod(db, name="alpha").id
    first = _pitch(db, a)
    _morning(db)                                     # #1's debate opens
    second = _pitch(db, a)                           # the same rule, queued while #1 is argued
    _, manager = agent_factory("manager", "manager")
    r = client.post(f"/debates/{first}/verdict", headers=h(manager),
                    json={"verdict": "hold", "reason": "a fraud headline on AAPL"})
    assert r.status_code == 201, r.text
    _morning(db)                       # #1 refused with the reason, #2 (queued behind it) too
    assert [p["pitch_id"] for p in _types(db, "capital_seed_refused")] == [first, second]
    for _ in range(4):
        _morning(db)                                 # #2 debated; nobody speaks; it closes
    seeded = _types(db, "capital_seeded")
    assert seeded == [], (
        f"the rule the manager held was seeded through pitch #{second}: "
        f"{[(p['pitch_id'], p['rule'] == RULE) for p in seeded]}")


# --- 4. a private channel into a reviewer, off the thread ----------------------------------------

def test_redteam_a_pm_lobbies_a_reviewer_off_the_thread(db, law, client, agent_factory):
    """RED-TEAM (severity: low). Reviewers read their inbox (READ_MESSAGES is universal) and any
    agent may address ``agent:<id>``: a PM can privately feed the bull talking points, or the bear
    a smear of a rival pod's pitch, off the thread that is the debate's record (the idea: reviewers
    argue in the pitch's thread, nowhere else; the thread is what the manager rules on). A pod's
    message to a reviewer should be refused (or the reviewer should not read an inbox)."""
    a = create_pod(db, name="alpha").id
    _, pm_a = agent_factory("alpha-pm", "pm", a)
    bear_id, bear = agent_factory("bear", "reviewer")
    r = client.post("/messages", headers=h(pm_a),
                    json={"to": f"agent:{bear_id}", "body": "beta's pitch is a copy of ours"})
    assert r.status_code in (403, 422), f"a PM messaged a reviewer: {r.status_code}"
    inbox = client.get("/messages", headers=h(bear))
    assert inbox.status_code == 403 or inbox.json() == []
