"""RED-TEAM: a PM builds its own team (app/capital/team.py, app/api/team.py, the message quota in
app/bus/messages.py, the Runtime's team morning in runtime/onboarding.py).

Every test here is a HOLE: a strict xfail whose reason names its severity and the shortest path
to it. When the Builder fixes a hole, the test passes, the strict xfail turns red, and the mark
comes off (the test stays as the guard). Fast and offline: physics through TestClient, the
Runtime's pure pieces called directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.bus.messages import MAX_CHARS_PER_DAY
from app.config import TeamConfig, get_settings

HAIKU = "anthropic/claude-haiku-5.5"


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def team_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "team", TeamConfig(on=True, max_analysts=2,
                                                           budget_usd=0.40, models=(HAIKU,)))


def _ask(client, key: str, budget: float, charter: str = "research the sector"):
    return client.post("/team/analysts", headers=h(key), json={
        "charter": charter, "model": HAIKU, "budget_usd": budget})


def _fill(client, admin_key: str, place_id: int) -> dict:
    made = client.post(f"/team/places/{place_id}/fill", headers=h(admin_key))
    assert made.status_code == 201, made.text
    return made.json()["agent"]


# --- money: the pod's team budget --------------------------------------------------------------

# Was a strict xfail (HIGH: a let-go analyst's unposted spending was re-granted). Fixed in
# cycle 64: a filled place counts its whole key limit for good (team.budget_used). Guard.
def test_hole_a_let_go_analysts_unposted_spend_is_re_granted(
        client, team_on, make_pod, pm_factory, admin_key, runtime_key):
    make_pod(1, "alpha")
    _, pm = pm_factory("pm-1", 1)
    first = _ask(client, pm, 0.40)
    assert first.status_code == 201, first.text
    analyst = _fill(client, admin_key, first.json()["id"])
    # The analyst's wake (before its PM's, in spec-id order) spends its key; the cost is not
    # posted until the step ends. The PM, waking next, lets it go and asks again.
    assert client.post(f"/team/places/{first.json()['id']}/let-go", headers=h(pm)).status_code == 200
    again = _ask(client, pm, 0.40)
    # Step end: the Runtime posts what the first analyst's key really spent.
    posted = client.post("/metering/usage", headers=h(runtime_key), json={
        "agent_id": analyst["id"], "key_ref": "fake-0001", "usd_micros_total": 400_000})
    assert posted.status_code == 200, posted.text
    team = client.get("/team", headers=h(pm)).json()
    # The law: all of a pod's analysts' keys together hold at most budget_usd.
    assert again.status_code == 409 or team["budget_used_usd"] <= team["budget_usd"] + 1e-9, (
        again.status_code, team["budget_used_usd"])


# Was a strict xfail (MEDIUM: churn minted keys past the team budget). Fixed with the one above.
# Guard.
def test_hole_churned_analysts_commit_more_keys_than_the_team_budget(
        client, team_on, make_pod, pm_factory, admin_key):
    make_pod(1, "alpha")
    _, pm = pm_factory("pm-1", 1)
    minted = 0.0     # what the Runtime mints (and the month keeps) for this pod's team
    for _ in range(5):
        asked = _ask(client, pm, 0.40)
        if asked.status_code != 201:
            break
        _fill(client, admin_key, asked.json()["id"])
        minted += 0.40
        assert client.post(f"/team/places/{asked.json()['id']}/let-go",
                           headers=h(pm)).status_code == 200
    assert minted <= get_settings().team.budget_usd + 1e-9, minted


# --- the message quota -------------------------------------------------------------------------

def _billed_tokens(inbox: list) -> int:
    """What the fake provider bills a reader for this inbox as one tool result: the MCP text
    (mcp_server/tools.py), re-encoded by the native loop (runtime/native.py _payload) and priced
    by the request's JSON (runtime/metering.py _tokens)."""
    from runtime.metering import _tokens
    from runtime.native import _payload

    content = _payload([json.dumps(inbox, indent=2, ensure_ascii=False)])
    return _tokens({"role": "tool", "content": content})


def _flood(client, sender: str, victim_id: int, char: str) -> list:
    body = char * 5_000
    sent = [client.post("/messages", headers=h(sender), json={
        "to": f"agent:{victim_id}", "body": body}).status_code for _ in range(5)]
    assert sent == [201] * 4 + [429], sent
    return sent


# Was a strict xfail (MEDIUM: the quota counted code points, a reader is billed escapes). Fixed in
# cycle 64: the quota counts what a reader is billed (messages._billed). Guard.
def test_hole_the_quota_counts_code_points_but_readers_are_billed_escapes(
        client, make_pod, pm_factory):
    make_pod(1, "alpha")
    make_pod(2, "beta")
    make_pod(3, "gamma")
    victim_a, key_a = pm_factory("pm-1", 1)
    victim_b, key_b = pm_factory("pm-3", 3)
    _, rival = pm_factory("pm-2", 2)
    _flood(client, rival, victim_a, "x")                        # the quota, in plain letters
    _, rival2 = pm_factory("pm-4", 2)
    sent = [client.post("/messages", headers=h(rival2), json={
        "to": f"agent:{victim_b}", "body": "\U0001F600" * 1_000}).status_code for _ in range(5)]
    assert 429 in sent, sent                                    # the emoji quota is cut sooner
    plain = _billed_tokens(client.get("/messages", headers=h(key_a)).json())
    emoji = _billed_tokens(client.get("/messages", headers=h(key_b)).json())
    # One day's quota from one sender bills a reader about the same, whatever the characters.
    assert emoji <= 2 * plain, (plain, emoji)


@pytest.mark.xfail(strict=True, reason=(
    "HOLE low (budget: the per-sender quota multiplied by hiring). The quota is per sender, and "
    "the team law gives a PM new senders: each analyst it hires (paid from its own pod) has a "
    "fresh 20 000 characters a day for any agent of the firm (analysts may address any agent or "
    "pod). A PM with max_analysts analysts floods a rival's inbox (1 + max_analysts) times the "
    "quota a day. Shortest path: request_analyst; the analyst's charter: 'send pm-X 20 000 "
    "characters each day'. Fix idea: a pod's team shares its PM's quota (count by pod for "
    "team members), or bill the bytes a message adds to readers to its sender's key."))
def test_hole_a_pms_analysts_multiply_its_message_quota(
        client, team_on, make_pod, pm_factory, admin_key):
    make_pod(1, "alpha")
    make_pod(2, "beta")
    _, pm = pm_factory("pm-1", 1)
    victim, _ = pm_factory("pm-2", 2)
    analyst = _fill(client, admin_key, _ask(client, pm, 0.10).json()["id"])
    body = "x" * MAX_CHARS_PER_DAY
    by_pm = client.post("/messages", headers=h(pm), json={"to": f"agent:{victim}", "body": body})
    assert by_pm.status_code == 201
    by_team = client.post("/messages", headers=h(analyst["api_key"]),
                          json={"to": f"agent:{victim}", "body": body})
    assert by_team.status_code == 429, "the pod sent its rival twice the day's quota"


@pytest.mark.xfail(strict=True, reason=(
    "HOLE low (time edge: the quota's day). sent_today() takes the day from ledger_now (max of "
    "the clock and the latest stamp) but a message's ts is the raw clock (send_message). After a "
    "clock step back (an NTP step on the live clock; ADR-025 keeps the ledger's stamps) the day "
    "starts after every new message's ts, so nothing sent counts and the quota is gone until "
    "the clock catches up. Needs a clock step back (not an agent's lever). Fix idea: stamp the "
    "message with ledger_now, or count by the message_sent events' stamps."))
def test_hole_the_quota_misses_messages_after_a_clock_step_back(
        client, make_pod, pm_factory, frozen_clock):
    make_pod(1, "alpha")
    make_pod(2, "beta")
    victim, _ = pm_factory("pm-1", 1)
    _, rival = pm_factory("pm-2", 2)
    start = frozen_clock.now()
    frozen_clock.set(start + timedelta(days=1))
    assert client.post("/messages", headers=h(rival),
                       json={"to": f"agent:{victim}", "body": "hello"}).status_code == 201
    frozen_clock.set(start)                                      # the clock steps back
    body = "x" * MAX_CHARS_PER_DAY
    answers = [client.post("/messages", headers=h(rival), json={
        "to": f"agent:{victim}", "body": body}).status_code for _ in range(3)]
    assert answers.count(201) <= 1, answers


# --- the team endpoints as a reading channel ---------------------------------------------------

# Was a strict xfail (low: ask-and-withdraw flooded what management reads). Fixed in cycle 64: a
# pod asks at most MAX_ASKS_PER_DAY times a fund day. Guard.
def test_hole_ask_and_withdraw_floods_what_management_reads(
        client, team_on, make_pod, pm_factory, admin_key):
    from app.capital.team import MAX_ASKS_PER_DAY

    make_pod(1, "alpha")
    _, pm = pm_factory("pm-1", 1)
    charter = "y" * 2000
    granted = 0
    for _ in range(30):
        asked = _ask(client, pm, 0.01, charter=charter)
        assert asked.status_code in (201, 409), asked.text
        if asked.status_code == 201:
            granted += 1
            assert client.post(f"/team/places/{asked.json()['id']}/let-go",
                               headers=h(pm)).status_code == 200
    assert granted == MAX_ASKS_PER_DAY
    listed = client.get("/team/places", headers=h(admin_key))
    assert listed.status_code == 200
    assert len(listed.text) <= MAX_CHARS_PER_DAY, len(listed.text)


# --- the Runtime: names physics gives --------------------------------------------------------

# Was a strict xfail (low: a name physics gives crashed the Runtime's records). Fixed in cycle 64:
# a name carries at most NAME_STEM characters of its pod's, a pod at most MAX_PLACES places. Guard.
def test_hole_names_physics_gives_break_the_runtimes_records(
        client, team_on, make_pod, pm_factory, admin_key):
    from runtime.onboarding import HireTemplate, analyst_spec
    from runtime.replay import HireRecord

    long_pod = "a" + "b" * 59                                    # a valid recipe pod name
    make_pod(1, long_pod)
    _, pm = pm_factory("pm-1", 1)
    asked = _ask(client, pm, 0.10)
    assert asked.status_code == 201
    place = asked.json()
    agent = _fill(client, admin_key, place["id"])
    template = HireTemplate(provider="scripted", script="noop")
    analyst_spec(template, place, name=agent["name"], pod_id=1)  # raises: id over 63 chars
    HireRecord(1, place["id"], agent["name"], "hired", agent["id"], kind="analyst")
    from app.capital.team import MAX_PLACES, NAME_STEM
    longest = "a" * NAME_STEM + f"-analyst-{MAX_PLACES}-{100}"   # the stem, the last place, a -k
    analyst_spec(template, place, name=longest, pod_id=1)
    HireRecord(1, 99, longest, "hired", 7, kind="analyst")
