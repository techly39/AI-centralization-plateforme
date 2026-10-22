"""RED-TEAM (idea: headlines and company data, handed by role). Each test here is a physics hole
found by the red-team on the branch: it FAILS until the Builder fixes the hole. Severity is in each
test's docstring. Do not weaken these tests to make them pass: fix the physics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.clock import LiveClock, set_clock
from app.marketdata import BarsProvider, set_provider
from app.marketdata.made_up import MadeUpMarket, bars, items
from app.run_clock import start_backtest

FRAUD = date(2024, 9, 10)
MISS = date(2024, 9, 12)
#: The world of tests/test_data_packages.py: K01 and K02 both report on 2024-08-26 by schedule.
BASE = {"seed": 7, "origin": "2024-06-01", "pivot": "2024-08-01", "days": 140,
        "families": [{"prefix": "K", "width": 6, "fate": "edge"}]}
NEWS = {"per_day": 3, "causes": [
    {"kind": "fraud", "ticker": "K01", "on": FRAUD.isoformat(), "shock": -0.08, "drift": -0.01,
     "days": 5},
    {"kind": "earnings_miss", "ticker": "K02", "on": MISS.isoformat(), "shock": -0.05,
     "drift": -0.005, "days": 4}]}
#: The acceptance demo's world (acceptance/data_packages.py), copied: M05's miss is on 2024-09-07.
DEMO = {
    "seed": 23, "origin": "2024-01-01", "pivot": "2024-08-01", "days": 300,
    "families": [{"prefix": "K", "width": 10, "fate": "edge"},
                 {"prefix": "M", "width": 10, "fate": "noise"}],
    "news": {"per_day": 3, "reports": True, "causes": [
        {"kind": "fraud", "ticker": "K03", "on": "2024-09-05",
         "shock": -0.09, "drift": -0.012, "days": 6},
        {"kind": "earnings_miss", "ticker": "M05", "on": "2024-09-07",
         "shock": -0.06, "drift": -0.006, "days": 4}]}}


def h(key: str) -> dict:
    return {"X-API-Key": key}


def _market(recipe: dict, news: dict | None) -> MadeUpMarket:
    body = {k: v for k, v in recipe.items() if k != "news"}
    return MadeUpMarket.model_validate({**body, **({"news": news} if news is not None else {})})


def _without_causes(recipe: dict, news: dict) -> MadeUpMarket:
    return _market(recipe, {**news, "causes": []})


def _midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), UTC)


# --- HOLE 1: a future earnings miss is visible before its day (the missing report) ----------------

@pytest.mark.parametrize("recipe,news", [(BASE, NEWS), (DEMO, DEMO["news"])],
                         ids=["test-world", "demo-world"])
def test_redteam_data_packages_a_future_miss_changes_nothing_served_before_its_day(
        recipe: dict, news: dict) -> None:
    """RED-TEAM, severity HIGH (look-ahead / the seal: the recipe's future causes leak).

    An ``earnings_miss`` cause *replaces* the name's scheduled quarterly report when the schedule
    falls within 45 days of the miss. When the scheduled day is BEFORE the miss, the scheduled
    report simply vanishes: from that day until the miss, the cause's name is the only one whose
    quarterly report is overdue. A mind with the company right (`/reports?days=400`) sees the hole
    up to 45 days early and knows a planted miss is coming on that name. In the demo world M05's
    2024-07-25 report is gone: the 2024-09-07 miss is foretold for 44 days, the whole of the demo's
    run. Law: what is served before a cause's day must be identical with and without that cause.

    Fix: never drop or move a scheduled report for a cause; publish the miss as that name's
    report on the scheduled day only (refuse a miss not on a scheduled day), or add it as an extra
    item while keeping the scheduled one on its day."""
    caused, plain = _market(recipe, news), _without_causes(recipe, news)
    first = min(date.fromisoformat(c["on"]) for c in news["causes"])
    before = lambda m: [x for x in items(m) if x.published < first]  # noqa: E731
    lost = [(x.published.isoformat(), x.ticker) for x in before(plain) if x not in before(caused)]
    assert before(caused) == before(plain), (
        f"items served before the first cause's day differ with the causes: {lost} vanish")


@pytest.fixture
def newsroom(SessionFactory):
    m = _market(BASE, NEWS)
    set_provider(BarsProvider(bars(m), news=items(m)))
    s = SessionFactory()
    try:
        start_backtest(s, start=_midnight(FRAUD))       # 2024-09-10: two days before K02's miss
        s.commit()
    finally:
        s.close()
    yield
    set_clock(LiveClock())


def test_redteam_data_packages_a_company_reader_sees_the_coming_miss_through_the_api(
        newsroom, client, admin_key, make_pod) -> None:
    """RED-TEAM, severity HIGH (the same hole, reached by a mind through its own tool).

    On 2024-09-10 an analyst holding only the company right reads the last 91 days of reports:
    K01 (scheduled with K02 on 2024-08-26) reported; K02 did not. Every other name has its
    quarter; K02's is missing because of a cause dated 2024-09-12, two days in the future.

    Fix: as in test_redteam_data_packages_a_future_miss_changes_nothing_served_before_its_day."""
    pod = make_pod(1)
    reader = client.post("/agents/register", headers=h(admin_key), json={
        "name": "a-co", "role": "analyst", "pod_id": pod, "data": ["company"]}).json()["api_key"]
    got = client.get("/reports", headers=h(reader), params={"days": 91})
    assert got.status_code == 200, got.text
    who = {x["ticker"] for x in got.json()["reports"]}
    plain = _without_causes(BASE, NEWS)
    should = {x.ticker for x in items(plain) if x.kind == "report"
              and FRAUD - timedelta(days=90) <= x.published <= FRAUD}
    assert who == should, (
        f"a company reader on {FRAUD} sees {sorted(who)} reporting; the world without the "
        f"future miss shows {sorted(should)}: {sorted(should - who)} is foretold")


# --- HOLE 2: a cause is read before its price has moved ------------------------------------------

@pytest.mark.parametrize("recipe,news", [(BASE, NEWS), (DEMO, DEMO["news"])],
                         ids=["test-world", "demo-world"])
def test_redteam_data_packages_a_cause_is_never_served_before_its_shock_is_in_the_price(
        recipe: dict, news: dict) -> None:
    """RED-TEAM, severity HIGH (look-ahead in effect: trading on a bar that has not ended).

    An item published on day D exists from D 00:00 UTC, but its cause's ``shock`` is added to the
    log-return of D's own bar, which ends (and is served) only at D+1 00:00. All day D, the quote
    (what a market order fills at, ``app/oms/service._fetch_price``) is D-1's close: the price
    without the shock. A mind that reads the fraud headline (or the miss report) at any moment of
    D sells at the pre-shock price and escapes the whole shock with certainty: it knows a close
    that has not happened. In the demo, an analyst reads K03's fraud at 2024-09-05 00:00 and its
    PM may sell at 2024-09-04's close, 9 % above the next price. That is not information priced
    at publication, it is the recipe's effect read before the world shows it, and the B run's
    finding ('did the PM cut?') would measure this artefact.

    Law: at every moment a cause's item is served, the quote of its ticker already carries the
    cause (it differs from the world without the cause).

    Fix: an item published on D exists from D's bar end (D+1 00:00 UTC, when D's bar is served),
    or apply the shock to the bar before the item's day; only the drift is then left to trade."""
    caused, plain = _market(recipe, news), _without_causes(recipe, news)
    with_news = BarsProvider(bars(caused), news=items(caused))
    without = BarsProvider(bars(plain))
    for c in news["causes"]:
        day, ticker = date.fromisoformat(c["on"]), c["ticker"]
        kind = "headline" if c["kind"] == "fraud" else "report"
        for at in (_midnight(day), _midnight(day) + timedelta(hours=14, minutes=30),
                   _midnight(day + timedelta(days=1)) - timedelta(seconds=1)):
            served = with_news.get_news(kind=kind, as_of=at, since=day, ticker=ticker)
            if not any(x.published == day for x in served):
                continue                       # not served yet: nothing to trade on
            now_price = with_news.get_price(ticker, as_of=at).price
            no_cause = without.get_price(ticker, as_of=at).price
            assert now_price != no_cause, (
                f"{ticker}'s {c['kind']} is served at {at.isoformat()} while its quote "
                f"{now_price:.4f} is the price of a world without it: the shock "
                f"{c['shock']:+.2%} is still ahead and certain")


# --- HOLE 3: report ids tell a company-only reader how many headlines a day had -------------------

def test_redteam_data_packages_reports_say_nothing_about_headlines() -> None:
    """RED-TEAM, severity LOW (a right read around: headlines' count reaches a reader without it).

    Item ids number a day's items in one sequence, headlines first then reports
    (``made_up.items``: sort by day, kind, ...). So a report's id is ``count(headlines that day) +
    its rank``: a mind with only the company right reads the day's headline count from the first
    report id. Noise is exactly ``per_day`` headlines a day, so a report day whose first id is
    ``per_day + 2`` says a fraud headline (a cause) was published that day, to a mind refused the
    headlines. Needs a report on the fraud day (frequent in a wide world); gives existence only.

    Law: the reports served are the same whether or not a headline is published that day.

    Fix: number each kind on its own (``20240826-r-001``), or derive the id from the item's own
    fields (a hash of kind, day, ticker, title)."""
    on_report_day = {**NEWS, "causes": [
        {"kind": "fraud", "ticker": "K03", "on": "2024-08-26"}]}     # K01 and K02 report that day
    with_fraud = [x for x in items(_market(BASE, on_report_day)) if x.kind == "report"]
    without = [x for x in items(_market(BASE, {**NEWS, "causes": []})) if x.kind == "report"]
    changed = [(a.ticker, b.id, a.id) for a, b in zip(with_fraud, without) if a != b]
    assert with_fraud == without, (
        f"a fraud headline changes the reports a company-only reader gets: {changed}")


# --- HOLE 4: two misses on one name: a cause moves the price with no item --------------------------

def test_redteam_data_packages_every_cause_is_published_on_its_day() -> None:
    """RED-TEAM, severity LOW (a wrong record: the world moves a price with no news).

    ``items`` keeps earnings misses in a dict keyed by ticker, so a second miss on the same name
    overwrites the first. If the kept one is consumed by a scheduled quarter, the other miss gets
    no report at all, while ``returns`` still adds its shock and drift: a planted cause no reader
    can ever read, and the recipe's 'each cause is an item' is false. The recipe validator
    accepts it (only one cause per name *and day* is refused). Operator-made, no agent gain.

    Fix: key the misses by (ticker, day) and publish each, or refuse a second miss per name in the
    validator."""
    two = {"per_day": 3, "causes": [
        {"kind": "earnings_miss", "ticker": "K02", "on": "2024-07-01"},
        {"kind": "earnings_miss", "ticker": "K02", "on": "2024-09-12"}]}
    made = items(_market(BASE, two))
    for c in two["causes"]:
        day = date.fromisoformat(c["on"])
        assert any(x.kind == "report" and x.ticker == "K02" and x.published == day
                   for x in made), f"K02's miss on {day} moves its price but is never published"
