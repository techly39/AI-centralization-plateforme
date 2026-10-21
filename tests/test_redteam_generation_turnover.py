"""RED-TEAM (idea: a generation turns over) -- holes in the month's end, the let-go, the hiring
law's new counts and the Runtime's per-step charges.

Each test states the law as it should hold and FAILS on the branch as found. The Builder fixes the
physics; these tests are not to be weakened. Severity is in each test's docstring.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.config import GenerationConfig, HiringConfig, get_settings
from app.db.models import Agent, AgentStatus, CashBalance, Event, Order, OrderStatus, Pod, Position
from app.run_clock import start_backtest


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
def law_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "generation", GenerationConfig(on=True, grace_days=20))


def _advance(client, runtime_key, days: int):
    r = client.post("/clock/advance", headers=h(runtime_key), json={"days": days})
    assert r.status_code == 200, r.text
    return r


def _types(db, type_: str) -> list[dict]:
    return [e.payload_json for e in db.scalars(select(Event).where(Event.type == type_)
                                               .order_by(Event.id))]


# --- the Human's agent cap ----------------------------------------------------------------------

def test_redteam_generation_the_register_route_passes_the_humans_agent_cap(
        client, db, make_pod, agent_factory, tmp_path, monkeypatch):
    """SEVERITY: high (breaks a cap: the Human's firm.max_agents_total).

    The branch moves the Human's agent cap "into physics", but only into the vacancy fill
    (app/capital/hiring.py fill -> over_cap). POST /agents/register (app/api/agents.py:31 ->
    app/registry/service.py register_agent) checks no cap at all. A firm management mind (one a
    registrar made over HTTP, the kind fill() now refuses) registers PMs into existing pods past
    the cap, as many as it likes, and holds every key: the cap binds the Runtime's hire and
    nobody else.
    """
    from app.registry import population

    make_pod(1)
    _, cio = agent_factory("cio", "management")          # a firm mind, not the operator's
    human = tmp_path / "human.yaml"
    monkeypatch.setattr(population, "HUMAN_FILE", human)
    alive = population.alive_agents(db)
    human.write_text(f"firm:\n  max_agents_total: {alive}\n")   # the firm is AT the cap
    codes = [client.post("/agents/register", headers=h(cio), json={
        "name": f"extra-pm-{k}", "role": "pm", "pod_id": 1}).status_code for k in range(3)]
    db.expire_all()
    after = population.alive_agents(db)
    assert after <= alive, (
        f"the firm was at the Human's cap of {alive} alive agents; /agents/register answered "
        f"{codes} and the firm now holds {after}")


# --- escaping the month's end -------------------------------------------------------------------

def test_redteam_generation_a_fresh_colleague_resets_an_old_pms_grace(
        client, db, september, law_on, make_pod, pm_factory, agent_factory, runtime_key):
    """SEVERITY: medium (a real advantage: a PM past its grace is never let go).

    The law (app/capital/generation.py docstring, 2.): "a PM whose pod never earned a seed is let
    go, once it has worked there at least grace_days". The code judges the POD by its newest PM:
    ``tenure = min(... for a in staff)`` (generation.py, _turnover). A management mind (or any
    registrar) registers one throw-away PM into the failing pod on the month's last day: the pod
    reads "too_new", and the PM who worked there all month (30 days, grace 20) stays and keeps
    thinking. Repeat every month and the pod is never judged.
    """
    make_pod(1, "doomed")
    old_id, _ = pm_factory("pm-old", 1)                 # Sep 1: 30 days at the month's end
    _, cio = agent_factory("cio", "management")
    _advance(client, runtime_key, 29)                   # Sep 30
    shield = client.post("/agents/register", headers=h(cio), json={
        "name": "pm-shield", "role": "pm", "pod_id": 1})
    assert shield.status_code == 201, shield.text
    _advance(client, runtime_key, 1)                    # Oct 1: September ends
    [gen] = _types(db, "generation_ended")
    verdict = {p["pod_name"]: p["verdict"] for p in gen["pods"]}["doomed"]
    db.expire_all()
    assert db.get(Agent, old_id).status == AgentStatus.inactive, (
        f"pm-old worked 30 days (grace 20) in an unseeded pod and is still active: a colleague "
        f"registered on the last day made the pod {verdict!r}")


def test_redteam_generation_the_capital_view_names_a_judgement_day_physics_does_not_keep(
        client, db, september, law_on, make_pod, pm_factory, agent_factory, runtime_key):
    """SEVERITY: low (a wrong record an agent reads: its own judgement day).

    ``generation.your_pod.judged_on`` (generation.py _your_pod) is computed from the pod's OLDEST
    active PM (``min(joined)``), while the month's end judges the pod by its NEWEST
    (``min(tenure)``). With two PMs the view tells pm-old "you are judged on 2024-10-01" and
    physics does not judge it then.
    """
    make_pod(1, "doomed")
    old_id, old_key = pm_factory("pm-old", 1)
    _, cio = agent_factory("cio", "management")
    _advance(client, runtime_key, 29)                   # Sep 30
    assert client.post("/agents/register", headers=h(cio), json={
        "name": "pm-shield", "role": "pm", "pod_id": 1}).status_code == 201
    told = client.get("/capital", headers=h(old_key)).json()["generation"]["your_pod"]
    _advance(client, runtime_key, 1)                    # Oct 1
    db.expire_all()
    gone = db.get(Agent, old_id).status == AgentStatus.inactive
    assert (told["judged_on"] == "2024-10-01") == gone, (
        f"the capital view told pm-old it is judged on {told['judged_on']}; at 2024-10-01 "
        f"physics {'let it go' if gone else 'did not judge it'}")


# --- money and orders in a pod the month's end closes ------------------------------------------

def test_redteam_generation_an_unseeded_pod_with_money_closes_with_its_money_and_live_orders(
        client, db, september, law_on, make_pod, fund_pod_cash, pm_factory, runtime_key, prices):
    """SEVERITY: medium (a wrong record and an act after being let go: money stranded in a closed
    pod, and the let-go PM's limit order fills there after it is gone).

    "Seeded" is only ``capital_seeded``. A pod the operator funded (a world recipe's pod
    ``allocation`` -> ``allocation_set``) never has one, so its PM is let go at the month's end
    and ``_let_go`` (generation.py) closes the pod by setting ``pod.status`` -- with no recall,
    no sale and no cancel of pending orders (the ladder's close does all three; hire_failed
    refuses to close a pod with money in it at all). The money and the holding sit in a closed
    pod the next generations skip, and the check of pending limit orders (app/oms/monitor.py)
    does not look at the pod's stage: the let-go PM's limit buy fills in the closed pod.
    """
    make_pod(1, "funded")
    fund_pod_cash(1, 100_000.0)                         # operator money, no seed
    pm_id, key = pm_factory("pm-1", 1)
    prices.set_price("AAPL", 200.0)
    base = {"ticker": "AAPL", "side": "buy", "justification": "thesis"}
    assert client.post("/orders", headers=h(key), json={
        **base, "qty": 100, "price_type": "market"}).status_code == 201
    assert client.post("/orders", headers=h(key), json={
        **base, "qty": 10, "price_type": "limit", "limit_price": 150.0}).status_code == 201
    _advance(client, runtime_key, 30)                   # Oct 1: September ends
    db.expire_all()
    assert db.get(Agent, pm_id).status == AgentStatus.inactive      # the law let it go
    prices.set_price("AAPL", 140.0)                     # the market falls through its limit
    _advance(client, runtime_key, 1)
    db.expire_all()
    pod = db.get(Pod, 1)
    late = [o.id for o in db.scalars(select(Order).where(
        Order.pod_id == 1, Order.status.in_((OrderStatus.pending, OrderStatus.filled)),
        Order.limit_price.is_not(None)))]
    cash = db.scalar(select(CashBalance.balance).where(CashBalance.pod_id == 1)) or 0.0
    held = db.scalar(select(Position.qty).where(Position.pod_id == 1)) or 0.0
    assert pod.status != "closed" or (not late and cash == 0 and held == 0), (
        f"the month's end closed pod 1 with ${cash:,.0f} cash, {held} AAPL and the let-go PM's "
        f"limit order(s) {late} still live (pending or filled after the close)")


# --- the month's table --------------------------------------------------------------------------

def test_redteam_generation_one_advance_over_two_month_ends_makes_one_mislabelled_generation(
        client, db, september, law_on, make_pod, pm_factory, runtime_key):
    """SEVERITY: low (a mislabelled record; a buggy or coarse Runtime step reaches it).

    ``_turnover`` ends at most one generation per advance and spans it from the last one's end
    to the day before today's month. One 61-day advance (MAX_ADVANCE_DAYS is 366) from Sep 1 to
    Nov 1 writes a single ``generation_ended`` with ``month: "2024-09"`` whose window runs to
    2024-10-31: October's month end never happens, its fitness is folded into "September", and a
    PM is judged once for two months. (A failing month's end retried past the next month's turn
    merges the same way.) Expected: each month its own generation, or the advance refused.
    """
    make_pod(1)
    pm_factory("pm-1", 1)
    r = client.post("/clock/advance", headers=h(runtime_key), json={"days": 61})
    if r.status_code != 200:
        return      # refusing an advance over two month turns is a fix too
    for g in _types(db, "generation_ended"):
        first, last = date.fromisoformat(g["from"]), date.fromisoformat(g["to"])
        assert (first.year, first.month) == (last.year, last.month) and \
            g["month"] == first.strftime("%Y-%m"), (
            f"generation {g['generation']} is labelled {g['month']} but spans "
            f"{g['from']} to {g['to']}")


def test_redteam_generation_a_pod_closed_by_a_failed_hire_vanishes_from_the_months_table(
        client, db, SessionFactory, september, law_on, make_pod, admin_key, runtime_key):
    """SEVERITY: low (a wrong record: a pod that lived in the month, and its thinking, are in no
    row).

    The docstring: "generation_ended holds every pod that lived in it". ``_turnover`` skips a
    closed pod unless it was closed by a ``pod_stage_changed`` or a ``pm_let_go`` in the window;
    a hired pod closed by ``hire_failed`` (management deactivates the hired PM, or the Runtime's
    key_over_cap path) is neither, so it is dropped: its month's thinking cost is in nobody's
    fitness.
    """
    from tests.test_redteam_pod_replacement import _close

    make_pod(1, "dead")
    vacancy_id = _close(SessionFactory, 1)
    made = client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key))
    assert made.status_code == 201, made.text
    hired = made.json()["agent"]
    assert client.post("/metering/usage", headers=h(runtime_key), json={
        "agent_id": hired["id"], "key_ref": "k-hire", "usd_micros_total": 3_000_000}
    ).status_code == 200
    _advance(client, runtime_key, 10)
    assert client.post(f"/agents/{hired['id']}/deactivate",
                       headers=h(admin_key)).status_code == 200      # hire_failed: pod closed
    _advance(client, runtime_key, 20)                   # Oct 1
    [gen] = _types(db, "generation_ended")
    rows = {p["pod_id"]: p for p in gen["pods"]}
    assert hired["pod_id"] in rows, (
        f"pod {hired['pod_id']} lived ten days of September and thought $3.00, but September's "
        f"table holds only pods {sorted(rows)}")


# --- the hiring law's new count -----------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="known physics hole (low, red-team cycle 58): an empty pod restaffed by registration passes the live-pod limit")
def test_redteam_generation_an_empty_pod_revived_by_registration_passes_the_live_pod_limit(
        client, db, SessionFactory, make_pod, pm_factory, admin_key, agent_factory, monkeypatch):
    """SEVERITY: low (needs a management agent; a pod over the hiring law's limit can pitch and
    be seeded).

    Empty pods no longer count toward ``max_live_pods`` (hiring.py live_pods), but an empty pod
    is not closed: it can be staffed again by ``POST /agents/register``. With the limit at 2, one
    staffed pod and one empty one, the fill is allowed (1 live < 2), and then a management mind
    registers a PM into the empty pod: 3 live pods under a limit of 2. Before the branch the empty
    pod counted and the fill was refused.
    """
    from app.capital.hiring import live_pods
    from tests.test_redteam_pod_replacement import _close

    monkeypatch.setattr(get_settings(), "hiring", HiringConfig(max_live_pods=2))
    make_pod(1, "dead")
    vacancy_id = _close(SessionFactory, 1)               # the law (limit 2) frozen here
    make_pod(2, "working")
    pm_factory("pm-2", 2)
    make_pod(3, "empty")                                 # made by the operator, no one works there
    assert client.post(f"/vacancies/{vacancy_id}/fill", headers=h(admin_key)).status_code == 201
    _, cio = agent_factory("cio", "management")
    revived = client.post("/agents/register", headers=h(cio), json={
        "name": "pm-3", "role": "pm", "pod_id": 3})
    db.expire_all()
    assert live_pods(db) <= 2, (
        f"the hiring law allows 2 live pods; the fill was allowed and the empty pod was staffed "
        f"again ({revived.status_code}): {live_pods(db)} live pods")


# --- the Runtime's per-step charges -------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="known physics hole (low, red-team cycle 58): a recorded charge is checked for amount, not for its agent")
def test_redteam_generation_a_recorded_charge_cannot_move_a_minds_thinking_to_another_agent():
    """SEVERITY: low (a forged or buggy recording; the replay posts the cost to another pod).

    ``Recording.__init__`` (runtime/replay.py) checks each charge's amount against the spec's
    recorded turns, but not who it is charged to: one spec's charges may name agent 7 under
    key-pm at step 0 and agent 8 (a rival's PM) under key-rival at step 1, and the replay posts
    them as recorded (lockstep: ``due = list(replay.charged(step))``), so its thinking lands on
    another pod's fitness. Expected: one spec's charges name one agent and one key.
    """
    from runtime.replay import Recording, RecordingError
    from tests.test_cassette_replay import _wake_json

    steps = [{"step": 0, "at": "d0", "wakes": [_wake_json("pm")], "advanced_to": "d1",
              "charged": [["pm", 7, "key-pm", 500_000]]},
             {"step": 1, "at": "d1", "wakes": [_wake_json("pm")], "advanced_to": "d2",
              "charged": [["pm", 8, "key-rival", 1_000_000]]}]
    with pytest.raises(RecordingError):
        Recording.from_outcome({"run": {"ended": "completed", "retired": [], "steps": steps}})
