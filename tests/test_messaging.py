"""The bus: who may say what to whom, and who gets to read it (TRD §6, §7).

The rules under test are the ones an agent will run into on its first day:
address a colleague, address a pod, try to broadcast, poll for replies. If any
of these is wrong the whole multi-agent premise breaks quietly — an agent that
believes it sent a message and did not will just look stupid.
"""

from __future__ import annotations

from sqlalchemy import select

from app.bus.refs import parse_ref
from app.db.models import Event, Message
from app.ledger.events import EVENT_MESSAGE_SENT, EVENT_PERMISSION_DENIED


def send(client, key, **body):
    return client.post("/messages", headers={"X-API-Key": key}, json=body)


def inbox(client, key, **params):
    resp = client.get("/messages", headers={"X-API-Key": key}, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Addressing -------------------------------------------------------------

def test_agent_to_agent_message_is_delivered_and_logged(client, desk, agent_factory, db):
    pod_id, pm_id, pm_key = desk
    analyst_id, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    resp = send(
        client,
        analyst_key,
        to=f"agent:{pm_id}",
        body="JPM screens cheapest in the group.",
        thread_id="jpm-thesis",
        structured_payload={"ticker": "JPM", "conviction": 0.8},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["to"] == f"agent:{pm_id}"
    assert body["from_agent"] == analyst_id
    assert body["structured_payload"] == {"ticker": "JPM", "conviction": 0.8}

    # The PM sees it; the sender sees their own copy.
    assert [m["id"] for m in inbox(client, pm_key)] == [body["id"]]
    assert body["id"] in [m["id"] for m in inbox(client, analyst_key)]

    # And it is on the ledger, not only in the messages table (principle 2).
    event = db.scalar(
        select(Event).where(Event.type == EVENT_MESSAGE_SENT).order_by(Event.id.desc())
    )
    assert event.payload_json["message_id"] == body["id"]
    assert event.actor_agent_id == analyst_id


def test_any_role_may_address_a_pod(client, desk, agent_factory):
    pod_id, _, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    resp = send(client, analyst_key, to=f"pod:{pod_id}", body="Screen attached.")
    assert resp.status_code == 201, resp.text
    assert resp.json()["to"] == f"pod:{pod_id}"

    # Every member of that pod can read it, including the PM who did not send it.
    assert [m["body"] for m in inbox(client, pm_key)] == ["Screen attached."]


def test_unknown_recipient_is_a_404_not_a_silent_success(client, desk):
    _, _, pm_key = desk
    assert send(client, pm_key, to="agent:9999", body="hello").status_code == 404
    assert send(client, pm_key, to="pod:9999", body="hello").status_code == 404


def test_malformed_recipient_is_refused_with_the_grammar(client, desk):
    _, _, pm_key = desk
    resp = send(client, pm_key, to="pm-alpha", body="hello")
    assert resp.status_code == 422
    # The error has to teach the format, because the caller is an LLM that will
    # retry: it must be able to fix itself from the message alone.
    detail = resp.json()["detail"]
    assert "agent:<id>" in detail and "pod:<id>" in detail and "broadcast" in detail


# --- Broadcast scoping (TRD §6) ---------------------------------------------

def test_management_broadcast_reaches_the_whole_firm(
    client, admin_key, desk, agent_factory, make_pod, fund_pod_cash
):
    _, _, pm_key = desk
    make_pod(2)
    _, other_pm_key = agent_factory("pm-2", "pm", 2)

    resp = send(client, admin_key, to="broadcast", body="All-hands Friday.")
    assert resp.status_code == 201
    assert resp.json()["to"] == "broadcast"

    for key in (pm_key, other_pm_key):
        assert "All-hands Friday." in [m["body"] for m in inbox(client, key)]


def test_pm_broadcast_is_scoped_to_its_own_pod(
    client, desk, agent_factory, make_pod
):
    pod_id, _, pm_key = desk
    _, mate_key = agent_factory("analyst-1", "analyst", pod_id)
    make_pod(2)
    _, outsider_key = agent_factory("pm-2", "pm", 2)

    resp = send(client, pm_key, to="broadcast", body="Cut the JPM position.")
    assert resp.status_code == 201
    # The effective audience is the PM's pod, not the firm — and the response
    # says so rather than echoing back what was asked for.
    assert resp.json()["to"] == f"pod:{pod_id}"

    assert "Cut the JPM position." in [m["body"] for m in inbox(client, mate_key)]
    assert inbox(client, outsider_key) == []


def test_analyst_may_not_broadcast_and_the_refusal_is_logged(
    client, desk, agent_factory, db
):
    pod_id, _, _ = desk
    analyst_id, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    resp = send(client, analyst_key, to="broadcast", body="everyone listen to me")
    assert resp.status_code == 403

    denial = db.scalar(
        select(Event)
        .where(Event.type == EVENT_PERMISSION_DENIED)
        .order_by(Event.id.desc())
    )
    assert denial.actor_agent_id == analyst_id
    assert denial.payload_json["code"] == "broadcast_not_permitted"
    # Nothing was written to the bus.
    assert db.scalar(select(Message)) is None


def test_pm_without_a_pod_cannot_broadcast(client, agent_factory):
    _, homeless_key = agent_factory("pm-nowhere", "pm", None)
    resp = send(client, homeless_key, to="broadcast", body="hello?")
    assert resp.status_code == 403
    assert "no pod" in resp.json()["detail"]


# --- Visibility -------------------------------------------------------------

def test_you_cannot_read_a_message_addressed_to_someone_else(
    client, desk, agent_factory, make_pod
):
    pod_id, pm_id, _ = desk
    _, insider_key = agent_factory("analyst-1", "analyst", pod_id)
    make_pod(2)
    _, outsider_key = agent_factory("pm-2", "pm", 2)

    send(client, insider_key, to=f"agent:{pm_id}", body="private note")

    assert inbox(client, outsider_key) == []
    assert [m["body"] for m in inbox(client, insider_key)] == ["private note"]


def test_management_can_read_the_whole_bus_but_others_cannot(
    client, admin_key, desk, agent_factory
):
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    send(client, analyst_key, to=f"agent:{pm_id}", body="between us")

    # Management sees it without being addressed.
    everything = inbox(client, admin_key, mine=False)
    assert [m["body"] for m in everything] == ["between us"]
    # ...and sees nothing when it plays by the normal rules.
    assert inbox(client, admin_key) == []

    resp = client.get(
        "/messages", headers={"X-API-Key": pm_key}, params={"mine": False}
    )
    assert resp.status_code == 403


# --- Polling ----------------------------------------------------------------

def test_after_id_is_a_reliable_cursor(client, desk, agent_factory):
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    for i in range(3):
        assert send(client, analyst_key, to=f"agent:{pm_id}", body=f"note {i}").status_code == 201

    first_page = inbox(client, pm_key)
    assert [m["body"] for m in first_page] == ["note 0", "note 1", "note 2"]
    # Oldest first, so a poller can append in order.
    assert first_page == sorted(first_page, key=lambda m: m["id"])

    # Nothing new since the last id.
    assert inbox(client, pm_key, after_id=first_page[-1]["id"]) == []

    send(client, analyst_key, to=f"agent:{pm_id}", body="note 3")
    fresh = inbox(client, pm_key, after_id=first_page[-1]["id"])
    assert [m["body"] for m in fresh] == ["note 3"]


def test_frozen_clock_ties_do_not_break_polling(
    client, desk, agent_factory, frozen_clock
):
    """Backtest mode (Phase 3) stops the clock — many messages, one timestamp.

    ``after_id`` must still separate them, which is the reason it exists.
    """
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    for i in range(3):
        send(client, analyst_key, to=f"agent:{pm_id}", body=f"tick {i}")

    page = inbox(client, pm_key)
    assert len({m["ts"] for m in page}) == 1  # all stamped identically
    assert inbox(client, pm_key, after_id=page[0]["id"]) == page[1:]


# --- Reading backwards ------------------------------------------------------
#
# `after_id` alone can only walk forward from message 1, so finding the end of a
# long-running fund's history costs a page per 500 messages. `latest` and
# `before_id` are the other direction: start at the end, walk back as far as you
# actually need.

def test_latest_returns_the_end_of_the_ledger_in_one_call(
    client, desk, agent_factory
):
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    for i in range(5):
        send(client, analyst_key, to=f"agent:{pm_id}", body=f"note {i}")

    tail = inbox(client, pm_key, latest=True, limit=2)
    # The newest two — but still oldest-first, like every other page.
    assert [m["body"] for m in tail] == ["note 3", "note 4"]


def test_before_id_walks_back_through_history(client, desk, agent_factory):
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    for i in range(5):
        send(client, analyst_key, to=f"agent:{pm_id}", body=f"note {i}")

    page = inbox(client, pm_key, latest=True, limit=2)
    older = inbox(client, pm_key, before_id=page[0]["id"], limit=2)
    assert [m["body"] for m in older] == ["note 1", "note 2"]

    oldest = inbox(client, pm_key, before_id=older[0]["id"], limit=2)
    assert [m["body"] for m in oldest] == ["note 0"]
    # And there is nothing before the first message.
    assert inbox(client, pm_key, before_id=oldest[0]["id"]) == []


def test_paging_backwards_sees_exactly_what_paging_forwards_sees(
    client, desk, agent_factory
):
    """The two directions must not disagree about what history *is*."""
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    for i in range(7):
        send(client, analyst_key, to=f"agent:{pm_id}", body=f"note {i}")

    forwards = inbox(client, pm_key)

    backwards: list[dict] = []
    cursor = None
    while True:
        page = inbox(
            client, pm_key, limit=3,
            **({"before_id": cursor} if cursor else {"latest": True}),
        )
        if not page:
            break
        backwards = page + backwards
        cursor = page[0]["id"]

    assert backwards == forwards


def test_backwards_paging_still_only_shows_what_you_may_read(
    client, desk, agent_factory, make_pod
):
    """Reading from the end must not become a way around the visibility filter."""
    pod_id, pm_id, _ = desk
    _, insider_key = agent_factory("analyst-1", "analyst", pod_id)
    make_pod(2)
    _, outsider_key = agent_factory("pm-2", "pm", 2)

    send(client, insider_key, to=f"agent:{pm_id}", body="private note")

    assert inbox(client, outsider_key, latest=True) == []
    assert [m["body"] for m in inbox(client, insider_key, latest=True)] == ["private note"]


def test_frozen_clock_ties_do_not_break_backwards_paging(
    client, desk, agent_factory, frozen_clock
):
    """Same tie-break problem as forward polling, same fix: order by id too."""
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    for i in range(4):
        send(client, analyst_key, to=f"agent:{pm_id}", body=f"tick {i}")

    tail = inbox(client, pm_key, latest=True, limit=2)
    assert [m["body"] for m in tail] == ["tick 2", "tick 3"]
    assert [m["body"] for m in inbox(client, pm_key, before_id=tail[0]["id"])] == [
        "tick 0",
        "tick 1",
    ]


def test_reading_both_directions_at_once_is_refused(client, desk, agent_factory):
    """A caller that thinks it is reading history while tailing loses messages.

    Better to fail loudly than to silently honour one cursor and drop the other.
    """
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)
    send(client, analyst_key, to=f"agent:{pm_id}", body="note")

    for params in ({"after_id": 1, "before_id": 9}, {"after_id": 1, "latest": True}):
        resp = client.get("/messages", headers={"X-API-Key": pm_key}, params=params)
        assert resp.status_code == 422, params
        # The message has to name both cursors, because the caller is an LLM
        # that must be able to fix the call from the error alone.
        detail = resp.json()["detail"]
        assert "after_id" in detail and "before_id" in detail


def test_thread_filter_groups_a_conversation(client, desk, agent_factory):
    pod_id, pm_id, pm_key = desk
    _, analyst_key = agent_factory("analyst-1", "analyst", pod_id)

    send(client, analyst_key, to=f"agent:{pm_id}", body="on JPM", thread_id="jpm")
    send(client, analyst_key, to=f"agent:{pm_id}", body="on WMT", thread_id="wmt")
    send(client, analyst_key, to=f"agent:{pm_id}", body="more on JPM", thread_id="jpm")

    assert [m["body"] for m in inbox(client, pm_key, thread="jpm")] == [
        "on JPM",
        "more on JPM",
    ]


def test_limit_is_capped_so_one_call_cannot_return_a_whole_run(client, desk):
    _, _, pm_key = desk
    resp = client.get("/messages", headers={"X-API-Key": pm_key}, params={"limit": 10_000})
    assert resp.status_code == 422


# --- The system's own messages ----------------------------------------------

def test_order_rejection_notice_arrives_on_the_same_bus(client, desk):
    """TRD §8.2's rejection message is a real message, not a side channel."""
    _, _, pm_key = desk
    resp = client.post(
        "/orders",
        headers={"X-API-Key": pm_key},
        json={
            "ticker": "AAPL",
            "side": "buy",
            "qty": 10_000,
            "price_type": "market",
            "justification": "too big to afford",
        },
    )
    assert resp.json()["status"] == "rejected"

    notice = inbox(client, pm_key)[-1]
    assert notice["structured_payload"]["kind"] == "order_rejected"
    assert notice["structured_payload"]["reason"] == "insufficient_cash"
    assert notice["thread_id"] == f"order-{resp.json()['id']}"


# --- The address format itself ----------------------------------------------

def test_ref_parsing_round_trips():
    for raw in ("agent:7", "pod:2", "broadcast"):
        assert parse_ref(raw).ref == raw
