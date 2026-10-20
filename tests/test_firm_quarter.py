"""The firm lives a quarter: what a PM is told (``tell_pms``), the laws a world recipe carries, and the
quarter report. The end-to-end proof is ``acceptance/firm_quarter.py`` (a scripted quarter on a
made-up market); here the ledger is staged directly."""

from __future__ import annotations

import pytest

from app.capital.report import quarter_report, render
from app.config import CapitalConfig
from app.ledger.events import (
    EVENT_CAPITAL_OPENED,
    EVENT_CAPITAL_SEEDED,
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_SUBMITTED,
    EVENT_POD_STAGE_CHANGED,
    append_event,
)
from app.registry.service import get_or_create_system_agent
from runtime import world

RULE = {"language": "strategy-v1", "signal": "momentum", "universe": ["AAA", "BBB"],
        "lookback": 20, "rebalance_every": 5, "top_n": 1, "side": "long_only", "gross": 1.0}


def h(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture
def stage(SessionFactory):
    """Write events as physics would: ``stage(type, payload)`` → the event id."""

    def _stage(type_: str, payload: dict) -> int:
        s = SessionFactory()
        try:
            event = append_event(s, type=type_, actor_agent_id=get_or_create_system_agent(s).id,
                                 payload=payload)
            s.commit()
            return event.id
        finally:
            s.close()

    return _stage


def _pitch(stage, pod_id: int, eligible: bool = True) -> int:
    pitch = stage(EVENT_PITCH_SUBMITTED, {"pod_id": pod_id, "agent_id": 1,
                                          "hypothesis": "winners keep winning",
                                          "data_needed": "prices", "team": "me",
                                          "budget_usd": 0.0, "rule": RULE})
    stage(EVENT_PITCH_JUDGED, {"pitch_id": pitch, "pod_id": pod_id, "eligible": eligible,
                               "gates": [], "attempts": 1})
    return pitch


def _seeded_pod(stage, *, tell: bool) -> tuple[int, int]:
    law = CapitalConfig(tell_pms=tell)
    stage(EVENT_CAPITAL_OPENED, {"law": law.model_dump(), "firm_capital_usd": 1e7})
    first = _pitch(stage, 1)
    stage(EVENT_CAPITAL_SEEDED, {"pod_id": 1, "pitch_id": first, "seed_usd": 200_000.0,
                                 "rule": RULE, "cost_at_seed_usd": 0.0})
    return first, _pitch(stage, 1)


def test_the_switch_is_left_out_of_the_frozen_law_while_off():
    # A run recorded before the switch existed opened with a law without it: its replay must
    # write the same law, so the switch off is not in the dump; on, it is.
    assert "tell_pms" not in CapitalConfig().model_dump()
    assert CapitalConfig(tell_pms=True).model_dump()["tell_pms"] is True
    assert CapitalConfig.model_validate(CapitalConfig().model_dump()).tell_pms is False


def test_told_a_seeded_pods_later_pitch_is_answered(client, make_pod, pm_factory, stage):
    make_pod(1)
    _, key = pm_factory("pm-1", 1)
    first, later = _seeded_pod(stage, tell=True)
    pitches = {p["id"]: p for p in client.get("/pitches", headers=h(key)).json()}
    assert pitches[first]["capital"]["outcome"] == "seeded"
    answer = pitches[later]["capital"]
    assert answer["outcome"] == "not_seeded" and f"pitch #{first}" in answer["reason"]
    # a pitch that is not eligible is answered by its verdict alone
    loser = _pitch(stage, 1, eligible=False)
    assert "capital" not in client.get(f"/pitches/{loser}", headers=h(key)).json()
    # once the pod is closed, the answer says so
    stage(EVENT_POD_STAGE_CHANGED, {"pod_id": 1, "from": "active", "to": "closed",
                                    "drawdown": 0.11, "worst_drawdown": 0.11})
    late = _pitch(stage, 1)
    assert "closed" in client.get(f"/pitches/{late}", headers=h(key)).json()["capital"]["reason"]
    # ... for every pitch the closed pod's PM sends, eligible or not: no capital ever comes
    lost = _pitch(stage, 1, eligible=False)
    assert "closed" in client.get(f"/pitches/{lost}", headers=h(key)).json()["capital"]["reason"]


def test_told_the_capital_view_carries_the_hiring_law(client, make_pod, pm_factory, stage):
    make_pod(1)
    _, key = pm_factory("pm-1", 1)
    _seeded_pod(stage, tell=True)
    view = client.get("/capital", headers=h(key)).json()
    assert "new PM is hired" in view["hiring"]["law"] and view["hiring"]["max_live_pods"] >= 1


def test_not_told_nothing_changes(client, make_pod, pm_factory, stage):
    # The law of every run recorded before the switch: the same words as then.
    make_pod(1)
    _, key = pm_factory("pm-1", 1)
    _, later = _seeded_pod(stage, tell=False)
    assert "capital" not in client.get(f"/pitches/{later}", headers=h(key)).json()
    assert "hiring" not in client.get("/capital", headers=h(key)).json()


def test_a_recipe_carries_its_laws_to_the_world(tmp_path):
    doc = {"start": "2024-09-01T14:30:00Z", "admin": "mgmt", "pods": [{"name": "a",
                                                                        "allocation": 0}],
           "laws": {"capital": {"tell_pms": True}, "hiring": {"max_live_pods": 4,
                                                               "charter": "Be brief."}}}
    recipe = world.parse_recipe(doc)
    env = world.child_env(tmp_path / "w.db", "k", laws=recipe.laws)
    assert env["FUND_CAPITAL__TELL_PMS"] == "true"
    assert env["FUND_HIRING__MAX_LIVE_PODS"] == "4"
    assert env["FUND_HIRING__CHARTER"] == "Be brief."
    for bad in ({"oms": {"fee_rate": 0}}, {"capital": {"Seed-USD": 1}}):
        with pytest.raises(world.WorldError):
            world.parse_recipe({**doc, "laws": bad})
    # a recipe without laws runs under the file's, as every older recording did
    plain = world.parse_recipe({k: v for k, v in doc.items() if k != "laws"})
    assert not any(k.startswith(("FUND_CAPITAL__", "FUND_HIRING__"))
                   for k in world.child_env(tmp_path / "w.db", "k", laws=plain.laws))


def test_the_report_before_the_centre_opens_says_so(db, prices):
    report = quarter_report(db, provider=prices)
    assert report["opened_on"] is None and report["pods"] == []
    assert "never opened" in render(report)


def test_the_operator_prints_the_report(capsys):
    from app.cli import main as fund_env

    assert fund_env(["quarter-report"]) == 0
    assert "never opened" in capsys.readouterr().out
