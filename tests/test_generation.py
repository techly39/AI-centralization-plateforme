"""A generation turns over: the month's end, who is let go, the lesson and the library, the law off.
The end-to-end proof is ``acceptance/generation_turnover.py`` (three scripted months on a made-up
market); here a backtest clock is advanced over one month's turn."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.config import GenerationConfig, get_settings
from app.db.models import Agent, AgentStatus, Event, Pod
from app.ledger.rebuild import rebuild_state
from app.run_clock import start_backtest
from mcp_server.client import FundClient
from runtime.native import NAMED_ONLY_TOOLS, published_tools


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
    set_clock(LiveClock())      # the next test starts on the live clock, as every test does


@pytest.fixture
def law_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "generation", GenerationConfig(on=True, grace_days=20))


def _advance(client, runtime_key, days: int) -> None:
    r = client.post("/clock/advance", headers=h(runtime_key), json={"days": days})
    assert r.status_code == 200, r.text


def _types(db, type_: str) -> list[dict]:
    return [e.payload_json for e in db.scalars(select(Event).where(Event.type == type_)
                                               .order_by(Event.id))]


def test_the_month_end_lets_go_the_unseeded_pm_and_spares_the_new_one(
        client, db, september, law_on, make_pod, pm_factory, runtime_key):
    make_pod(1, "old")
    old_id, old_key = pm_factory("pm-old", 1)
    r = client.post("/metering/usage", headers=h(runtime_key), json={
        "agent_id": old_id, "key_ref": "k-old", "usd_micros_total": 5_000_000})
    assert r.status_code == 200, r.text
    _advance(client, runtime_key, 15)
    make_pod(2, "new")
    new_id, new_key = pm_factory("pm-new", 2)          # Sep 16: 15 days at the month's end
    _advance(client, runtime_key, 14)                  # Sep 30: the month has not turned
    assert _types(db, "generation_ended") == []
    _advance(client, runtime_key, 1)                   # Oct 1
    [gen] = _types(db, "generation_ended")
    assert (gen["generation"], gen["month"], gen["from"], gen["to"]) == (
        1, "2024-09", "2024-09-01", "2024-09-30")
    rows = {p["pod_name"]: p for p in gen["pods"]}
    assert rows["old"]["verdict"] == "let_go" and rows["new"]["verdict"] == "too_new"
    # it held nothing all month: no P&L, and its thinking is its fitness
    assert (rows["old"]["pnl_usd"], rows["old"]["thinking_usd"], rows["old"]["fitness_usd"]) == (
        0.0, 5.0, -5.0)
    db.expire_all()
    assert db.get(Agent, old_id).status == AgentStatus.inactive
    assert db.get(Agent, new_id).status == AgentStatus.active
    assert db.get(Pod, 1).status == "closed" and db.get(Pod, 2).status == "active"
    # a let-go PM's key answers 401: the Runtime retires its mind
    assert client.get("/me", headers=h(old_key)).status_code == 401
    # the lesson is in the vacancy and in the library, which every firm agent reads
    [vacancy] = _types(db, "vacancy_opened")
    assert vacancy["pod_id"] == 1 and vacancy["post_mortem"]["reason"] == "no_seed"
    lib = client.get("/library", headers=h(new_key)).json()
    assert [(x["pms"], x["reason"], x["generation"]) for x in lib] == [(["pm-old"], "no_seed", 1)]
    assert lib[0]["lesson"]["thinking_cost_usd"] == 5.0
    # the let-go PM's closed pod stays closed when the books are rebuilt from the ledger
    db.get(Pod, 1).status = "active"
    rebuild_state(db)
    assert db.get(Pod, 1).status == "closed"
    db.rollback()
    # the next month's turn judges the new PM (now 45 days in)
    _advance(client, runtime_key, 31)
    second = _types(db, "generation_ended")[1]
    assert {p["pod_name"]: p["verdict"] for p in second["pods"]}["new"] == "let_go"
    # the generation law is frozen into the first generation: a later edit does not change it
    assert second["law"] == gen["law"]


def test_the_capital_view_states_the_law(client, september, law_on, make_pod, pm_factory):
    make_pod(1)
    _, key = pm_factory("pm-1", 1)
    told = client.get("/capital", headers=h(key)).json()["generation"]
    assert "let go" in told["law"] and told["grace_days"] == 20
    assert told["next_judged_on"] == "2024-10-01"


def test_with_the_law_off_nothing_turns(client, db, september, make_pod, pm_factory, runtime_key):
    make_pod(1)
    pm_id, key = pm_factory("pm-1", 1)
    _advance(client, runtime_key, 45)
    assert _types(db, "generation_ended") == [] and _types(db, "pm_let_go") == []
    db.expire_all()
    assert db.get(Agent, pm_id).status == AgentStatus.active
    assert "generation" not in client.get("/capital", headers=h(key)).json()
    assert client.get("/library", headers=h(key)).json() == []


#: The tools every recorded mind that names no tools was shown (cycle 53). A tool added since is in
#: ``NAMED_ONLY_TOOLS``: shown only to a spec that names it, so no old recording's replay breaks.
SHOWN_TO_SPECS_THAT_NAME_NONE = frozenset({
    "whoami", "register_agent", "list_agents", "deactivate_agent", "send_message", "get_messages",
    "get_price", "get_ohlcv", "run_research_backtest", "list_research_backtests", "submit_pitch",
    "list_pitches", "get_pitch", "get_capital", "get_mandate", "list_vacancies", "get_vacancy",
    "fill_vacancy", "refuse_hire", "place_order", "cancel_order", "list_orders", "get_portfolio",
    "report_cost", "start_task", "end_task", "get_pod_metrics", "get_leaderboard",
    "get_metered_costs", "list_events", "get_clock", "advance_clock", "report_metered_usage",
    "declare_run_minds", "get_halt", "get_health"})


def test_a_new_tool_is_shown_only_to_a_spec_that_names_it():
    async def names() -> set[str]:
        client = FundClient(base_url="http://127.0.0.1:9", api_key="x")
        try:
            return {t.name for t in await published_tools(client)}
        finally:
            await client.aclose()

    published = asyncio.run(names())
    assert "read_library" in NAMED_ONLY_TOOLS <= published
    assert published - NAMED_ONLY_TOOLS == SHOWN_TO_SPECS_THAT_NAME_NONE


# --- a let-go PM's retirement is part of the recording ---------------------------------------------

def _retired_run(retired: list, retired_at: list, *, late_wake: bool = False,
                 reason: str = "no_identity") -> dict:
    from tests.test_cassette_replay import _wake_json

    refused = {"spec_id": "pm-gone", "ended": "refused", "reason": reason, "tool_calls": 0,
               "tool_failures": 0, "transcript": [], "exchanges": []}
    steps = [{"step": 0, "at": "a", "wakes": [_wake_json("pm"), _wake_json("pm-gone")],
              "advanced_to": "b"},
             {"step": 1, "at": "b", "wakes": [_wake_json("pm"), refused], "advanced_to": "c"},
             {"step": 2, "at": "c", "wakes": [_wake_json("pm")]
              + ([_wake_json("pm-gone")] if late_wake else []), "advanced_to": "d"}]
    return {"run": {"ended": "completed", "retired": retired, "retired_at": retired_at,
                    "steps": steps}}


def test_a_recorded_retirement_replays_where_it_happened_and_nowhere_else():
    from runtime.replay import Recording, RecordingError

    rec = Recording.from_outcome(_retired_run(["pm-gone"], [1]))
    assert rec.retired == {"pm-gone": 1} and "pm-gone" in rec.spec_ids
    assert rec.tape(0, "pm-gone").turns and not rec.tape(1, "pm-gone").turns
    for forged in (_retired_run([], []),                        # a refusal the run never retired
                   _retired_run(["pm-gone"], [2]),              # the word, at another step
                   _retired_run(["pm-gone"], [1], late_wake=True),   # it wakes after it
                   _retired_run(["pm-gone"], [1], reason="cap_null"),  # not a dead key
                   _retired_run(["pm-gone"], [])):              # a word with no step
        with pytest.raises(RecordingError):
            Recording.from_outcome(forged)


# --- thinking charged each step is part of the recording -------------------------------------------

def test_a_recorded_charge_must_be_what_the_recorded_turns_stated():
    from runtime.replay import Recording, RecordingError
    from tests.test_cassette_replay import _wake_json

    def run(*charges):
        steps = [{"step": n, "at": f"d{n}", "wakes": [_wake_json("pm")], "advanced_to": f"d{n + 1}",
                  **({"charged": c} if c is not None else {})} for n, c in enumerate(charges)]
        return {"run": {"ended": "completed", "retired": [], "steps": steps}}

    # each wake's one turn stated $0.50: 500000 µ$ after step 0, 1000000 after step 1
    rec = Recording.from_outcome(run([["pm", 7, "key-pm", 500_000]], [["pm", 7, "key-pm", 1_000_000]]))
    assert rec.charged(0) == (("pm", 7, "key-pm", 500_000),) and rec.charged(5) == ()
    assert Recording.from_outcome(run(None, [["pm", 7, "key-pm", 1_000_000]])).charged(1)
    for forged in (run([["pm", 7, "key-pm", 500_001]]),                 # more than was stated
                   run([["pm", 7, "key-pm", 500_000]], [["pm", 7, "key-pm", 500_000]]),  # no growth
                   run([["nobody", 7, "key-pm", 500_000]]),             # a mind not in the run
                   run([["pm", 7, "key-pm", 500_000], ["pm", 7, "key-pm", 500_000]]),  # twice
                   run([["pm", "7", "key-pm", 500_000]])):              # not an agent id
        with pytest.raises(RecordingError):
            Recording.from_outcome(forged)
