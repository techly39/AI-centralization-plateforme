"""Headlines and company data, handed by role (idea: data packages): the paths the acceptance demo
does not walk. A recipe's news never moves a price but its causes; an item does not exist before
its day; data is read only with the right, which only the operator's registrar or a team place's
fill grants; a package's sections are physics' answers through the mind's own key."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.clock import LiveClock, set_clock
from app.config import TeamConfig, get_settings
from app.db.models import Event
from app.marketdata import BarsProvider, set_provider
from app.marketdata.made_up import MadeUpMarket, bars, items, returns
from app.run_clock import start_backtest
from mcp_server.client import FundAPIError
from runtime import packages

HAIKU = "anthropic/claude-haiku-5.5"
FRAUD = date(2024, 9, 10)
MISS = date(2024, 9, 12)
BASE = {"seed": 7, "origin": "2024-06-01", "pivot": "2024-08-01", "days": 140,
        "families": [{"prefix": "K", "width": 6, "fate": "edge"}]}
NEWS = {"per_day": 3, "causes": [
    {"kind": "fraud", "ticker": "K01", "on": FRAUD.isoformat(), "shock": -0.08, "drift": -0.01,
     "days": 5},
    {"kind": "earnings_miss", "ticker": "K02", "on": MISS.isoformat(), "shock": -0.05,
     "drift": -0.005, "days": 4}]}


def h(key: str) -> dict:
    return {"X-API-Key": key}


def market(news: dict | None = NEWS) -> MadeUpMarket:
    return MadeUpMarket.model_validate({**BASE, **({"news": news} if news is not None else {})})


# --- the world writes it ------------------------------------------------------------------------

def test_noise_moves_nothing_and_each_cause_moves_only_its_name_as_the_recipe_says() -> None:
    plain, noisy, caused = returns(market(None)), returns(market({"per_day": 5})), returns(market())
    assert plain == noisy and bars(market(None)) == bars(market({"per_day": 5}))
    origin = date.fromisoformat(BASE["origin"])
    for name, path in caused.items():
        added = [round(a - b, 12) for a, b in zip(path, plain[name])]
        if name == "K01":
            d = (FRAUD - origin).days
            assert added[d] == -0.08 and added[d + 1:d + 6] == [-0.01] * 5
            assert not any(added[:d]) and not any(added[d + 6:])
        elif name == "K02":
            d = (MISS - origin).days
            assert added[d] == -0.05 and added[d + 1:d + 5] == [-0.005] * 4
            assert not any(added[:d]) and not any(added[d + 5:])
        else:
            assert not any(added)


def test_the_items_are_the_seeds_and_carry_no_effect() -> None:
    first, again = items(market()), items(market())
    assert first == again and len(first) > 140 * 3
    fraud = [x for x in first if x.ticker == "K01" and "fraud" in x.title]
    assert [x.published for x in fraud] == [FRAUD]
    miss = [x for x in first if x.kind == "report" and x.published == MISS]
    assert [x.ticker for x in miss] == ["K02"]
    assert miss[0].figures["eps"] < 0.8 * miss[0].figures["expected_eps"]
    assert miss[0].figures["guidance"] == "lowered"
    # K02's miss takes the place of its next scheduled report; every report before it is as in
    # the world without the miss (a report gone missing would foretell it).
    plain = items(market({**NEWS, "causes": []}))
    k02 = lambda xs: sorted(x.published for x in xs if x.kind == "report" and x.ticker == "K02")  # noqa: E731
    assert [d for d in k02(first) if d < MISS] == [d for d in k02(plain) if d < MISS]
    after = [d for d in k02(plain) if d >= MISS]
    replaced = bool(after) and (after[0] - MISS).days <= 45
    assert k02(first) == sorted([d for d in k02(plain) if d < MISS] + [MISS]
                                + (after[1:] if replaced else after))
    for x in first:
        assert set(vars(x) if hasattr(x, "__dict__") else {s: 0 for s in x.__slots__}) == {
            "id", "kind", "published", "ticker", "title", "body", "figures"}
    assert len({x.id for x in first}) == len(first)


def test_a_cause_names_a_name_of_the_world_on_a_day_of_the_world() -> None:
    for bad in ({"kind": "fraud", "ticker": "Z01", "on": "2024-09-10"},
                {"kind": "fraud", "ticker": "K01", "on": "2024-06-01"},
                {"kind": "fraud", "ticker": "K01", "on": "2025-06-01"}):
        with pytest.raises(ValueError):
            market({"causes": [bad]})


def test_a_days_news_is_out_at_its_close_with_its_bar_never_before() -> None:
    m = market()
    provider = BarsProvider(bars(m), news=items(m))
    quiet = BarsProvider(bars(market({**NEWS, "causes": []})))
    at = lambda d: datetime.combine(d, datetime.min.time(), UTC)  # noqa: E731
    since = FRAUD - timedelta(days=5)
    close = at(FRAUD + timedelta(days=1))
    for early in (at(FRAUD), at(FRAUD) + timedelta(hours=14), close - timedelta(seconds=1)):
        before = provider.get_news(kind="headline", as_of=early, since=since, ticker="K01")
        assert not any("fraud" in x.title for x in before)
    out = provider.get_news(kind="headline", as_of=close, since=since, ticker="K01")
    assert any("fraud" in x.title for x in out)
    assert all(x.published <= FRAUD for x in out)
    # When it is out, the price already holds its shock: only the drift is left to trade.
    assert provider.get_price("K01", as_of=close).price < quiet.get_price("K01", as_of=close).price
    assert "news_fingerprint" in provider.world()
    assert "news_fingerprint" not in BarsProvider(bars(m)).world()


# --- handed by role -----------------------------------------------------------------------------

@pytest.fixture
def newsroom(SessionFactory):
    m = market()
    set_provider(BarsProvider(bars(m), news=items(m)))
    s = SessionFactory()
    try:
        # The morning after the fraud's day: its news is out (at the day's close).
        start_backtest(s, start=datetime.combine(FRAUD + timedelta(days=1), datetime.min.time(), UTC))
        s.commit()
    finally:
        s.close()
    yield
    set_clock(LiveClock())


def _register(client, key, name, role, pod=None, data=None):
    return client.post("/agents/register", headers=h(key), json={
        "name": name, "role": role, "pod_id": pod, **({"data": data} if data else {})})


def _denials(db) -> list[dict]:
    db.expire_all()
    return [e.payload_json for e in db.scalars(select(Event).where(
        Event.type == "permission_denied").order_by(Event.id))]


def test_only_a_mind_given_the_right_reads_it_and_a_refusal_is_logged(
        newsroom, client, admin_key, make_pod, db) -> None:
    pod = make_pod(1)
    analyst = _register(client, admin_key, "a-1", "analyst", pod, ["headlines"]).json()["api_key"]
    pm = _register(client, admin_key, "pm-1", "pm", pod).json()["api_key"]
    read = client.get("/headlines", headers=h(analyst), params={"days": 1, "ticker": "K01"})
    assert read.status_code == 200
    assert any("fraud" in x["title"] for x in read.json()["headlines"])
    assert all(set(x) == {"id", "day", "ticker", "title", "body"} for x in read.json()["headlines"])
    assert client.get("/reports", headers=h(analyst)).status_code == 403
    refused = client.get("/headlines", headers=h(pm))
    assert refused.status_code == 403 and "no right to headlines" in refused.json()["detail"]
    assert [d["right"] for d in _denials(db)] == ["company", "headlines"]
    assert client.get("/data/rights", headers=h(pm)).json() == {
        "prices": True, "headlines": False, "company": False}
    assert client.get("/data/rights", headers=h(analyst)).json() == {
        "prices": True, "headlines": True, "company": False}


def test_only_the_operators_registrar_grants_data_and_only_to_a_pm_or_an_analyst(
        newsroom, client, admin_key, make_pod, db) -> None:
    pod = make_pod(1)
    other = _register(client, admin_key, "registrar-2", "management").json()["api_key"]
    by_firm = _register(client, other, "a-2", "analyst", pod, ["headlines"])
    assert by_firm.status_code == 403 and "operator's registrar" in by_firm.json()["detail"]
    to_manager = _register(client, admin_key, "boss", "manager", None, ["headlines"])
    assert to_manager.status_code == 403
    assert _register(client, admin_key, "a-3", "analyst", pod, ["gossip"]).status_code == 422
    db.expire_all()
    assert not db.scalars(select(Event).where(Event.type == "data_rights_granted")).all()
    manager = _register(client, admin_key, "boss", "manager").json()["api_key"]
    assert client.get("/headlines", headers=h(manager)).status_code == 403   # by role


def test_a_pm_asks_for_an_analyst_with_data_the_law_lists_and_its_fill_grants_it(
        newsroom, client, admin_key, make_pod, monkeypatch, db) -> None:
    monkeypatch.setattr(get_settings(), "team", TeamConfig(
        on=True, max_analysts=2, budget_usd=0.40, models=(HAIKU,), data=("headlines",)))
    pod = make_pod(1)
    pm = _register(client, admin_key, "pm-1", "pm", pod).json()["api_key"]
    ask = lambda data: client.post("/team/analysts", headers=h(pm), json={  # noqa: E731
        "charter": "read the news", "model": HAIKU, "budget_usd": 0.1, "data": data})
    outside = ask(["company"])
    assert outside.status_code == 409 and "not in the team law's list" in outside.json()["detail"]
    granted = ask(["headlines"])
    assert granted.status_code == 201 and granted.json()["data"] == ["headlines"]
    assert "request_analyst_with_data" in client.get("/team", headers=h(pm)).json()["law"]
    made = client.post(f"/team/places/{granted.json()['id']}/fill", headers=h(admin_key))
    assert made.status_code == 201, made.text
    key = made.json()["agent"]["api_key"]
    assert client.get("/data/rights", headers=h(key)).json()["headlines"] is True
    assert client.get("/headlines", headers=h(pm)).status_code == 403     # the PM still lacks it


def test_a_team_law_without_data_lists_none_and_its_views_say_nothing_new(
        newsroom, client, admin_key, make_pod, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "team", TeamConfig(on=True, models=(HAIKU,)))
    pod = make_pod(1)
    pm = _register(client, admin_key, "pm-1", "pm", pod).json()["api_key"]
    plain = client.post("/team/analysts", headers=h(pm), json={
        "charter": "research", "model": HAIKU, "budget_usd": 0.1})
    assert plain.status_code == 201 and "data" not in plain.json()
    law = client.get("/team", headers=h(pm)).json()["law"]
    assert "data" not in law and "request_analyst_with_data" not in law
    asked = client.post("/team/analysts", headers=h(pm), json={
        "charter": "research", "model": HAIKU, "budget_usd": 0.1, "data": ["headlines"]})
    assert asked.status_code == 409


# --- the packages -------------------------------------------------------------------------------

class _Through:
    """A FundClient stand-in that reaches the app through the test client, as one agent."""

    def __init__(self, client, key: str) -> None:
        self.client, self.key = client, key

    async def get(self, path: str, **params):
        r = self.client.get(path, headers=h(self.key),
                            params={k: v for k, v in params.items() if v is not None})
        if r.status_code >= 400:
            raise FundAPIError(r.status_code, r.json().get("detail", ""), path=path)
        return r.json()


def test_everything_is_exactly_prices_and_headlines_and_reports_each_by_right(
        newsroom, client, admin_key, make_pod) -> None:
    pod = make_pod(1)
    both = _register(client, admin_key, "a-1", "analyst", pod,
                     ["headlines", "company"]).json()["api_key"]
    pm = _register(client, admin_key, "pm-1", "pm", pod).json()["api_key"]
    at, universe = f"{FRAUD + timedelta(days=1)}T00:00:00+00:00", ["K01", "K02", "K03"]
    build = lambda name, key: asyncio.run(  # noqa: E731
        packages.build(name, _Through(client, key), at, universe))
    every, prices = build("everything-v1", both), build("prices-v1", both)
    head, comp = build("headlines-v1", both), build("company-v1", both)
    assert {k: v for k, v in every.items() if k not in ("name", "headlines", "reports")} == {
        k: v for k, v in prices.items() if k != "name"}
    assert every["headlines"] == head["headlines"] and every["reports"] == comp["reports"]
    assert "reports" not in head and "headlines" not in comp
    assert any("fraud" in x["title"] for x in every["headlines"])
    assert all(x["ticker"] in universe for x in every["reports"])
    assert len({x["ticker"] for x in every["reports"]}) == len(every["reports"])
    refused = build("everything-v1", pm)
    assert "headlines" not in refused and "reports" not in refused
    assert set(refused["refused"]) == {"headlines", "reports"}
    assert "no right to headlines" in refused["refused"]["headlines"]
    assert refused["bars"] == prices["bars"]
    assert math.isfinite(refused["bars"]["K01"][-1][4])


def test_a_miss_just_before_a_scheduled_report_takes_its_place_and_two_misses_are_two_reports(
        ) -> None:
    plain = items(market({"per_day": 1}))
    k02 = lambda xs: sorted(x.published for x in xs if x.kind == "report" and x.ticker == "K02")  # noqa: E731
    origin = date.fromisoformat(BASE["origin"])
    due = next(d for d in k02(plain) if d > origin + timedelta(days=10))  # a scheduled report
    early, late = due - timedelta(days=6), due + timedelta(days=15)
    made = items(market({"per_day": 1, "causes": [
        {"kind": "earnings_miss", "ticker": "K02", "on": early.isoformat()},
        {"kind": "earnings_miss", "ticker": "K02", "on": late.isoformat()}]}))
    assert k02(made) == sorted([d for d in k02(plain) if d != due] + [early, late])
    assert [x for x in made if x.published < early] == [x for x in plain if x.published < early]


def test_a_ticker_filter_is_a_ticker(newsroom, client, admin_key, make_pod) -> None:
    pod = make_pod(1)
    key = _register(client, admin_key, "a-1", "analyst", pod, ["headlines"]).json()["api_key"]
    assert client.get("/headlines", headers=h(key), params={"ticker": "K" * 17}).status_code == 422
    assert client.get("/headlines", headers=h(key), params={"ticker": "K01"}).status_code == 200
