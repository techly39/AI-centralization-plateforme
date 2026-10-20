"""RED-TEAM (idea: the firm lives a quarter) -- holes in what PMs are told, the laws a world recipe
carries, and what they touch (hiring, the pitch desk).

Each test states the law as it should hold and FAILS on the branch as found. The Builder fixes the
physics; these tests are not to be weakened. Severity and the path to the wrong outcome are in each
test's docstring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from app.config import CapitalConfig
from app.db.models import Agent, Pod
from app.ledger.events import (
    EVENT_CAPITAL_OPENED,
    EVENT_CAPITAL_SEEDED,
    EVENT_PITCH_JUDGED,
    EVENT_PITCH_SUBMITTED,
    EVENT_POD_STAGE_CHANGED,
    append_event,
)
from app.marketdata import SyntheticProvider, set_provider
from app.registry.service import get_or_create_system_agent
from tests.support import world_key
from tests.test_runtime_hiring import _run, _stage_vacancy, _template
from tests.test_runtime_lockstep import gov, live_afterwards, woke, world  # noqa: F401 - fixtures


def h(key: str) -> dict:
    return {"X-API-Key": key}


# --- H1 (high): hires spawn agents past the Human's population cap ---------------------------------

@pytest.fixture
def keys(world, monkeypatch: pytest.MonkeyPatch) -> dict:  # noqa: F811 - the hiring tests' own
    from runtime import cli
    monkeypatch.setenv(cli.REGISTRAR_KEY_ENV, world["admin"])
    monkeypatch.setenv(cli.CLOCK_KEY_ENV, world["clock"])
    return world


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    from tests.test_runtime_cli_backtest import _write_specs
    return _write_specs(tmp_path / "specs", {
        "id": "a-pm", "name": "desk-2-pm", "role": "pm", "pod": 2, "provider": "scripted",
        "script": "read-a", "charter": "Read the clock."})


def test_redteam_a_hire_never_takes_the_firm_past_the_humans_agent_cap(
        SessionFactory, keys, specs, woke, tmp_path, capsys, gov):  # noqa: F811
    """SEVERITY: high (spawns agents past a cap the Human set: ``firm.max_agents_total``).

    Path: nothing in physics or the Runtime reads ``max_agents_total`` (200 in human.yaml); the
    only bound on hires is the hiring law's ``max_live_pods`` (``le=1000``), which a world's recipe
    now sets (``laws.hiring.max_live_pods``), and a closed pod's PM stays an active agent, so each
    death + hire adds one alive agent for good. Here the Human allows 2 alive agents, the world
    already holds more, and Onboarding still hires ``hire-1-pm``.
    """
    (gov / "human.yaml").write_text(
        "firm:\n  monthly_llm_usd_cap: null\n  max_agents_total: 2\n")
    _stage_vacancy(SessionFactory)
    _run(SessionFactory, ["--specs", str(specs), "--steps", "1", "--hire",
                          str(_template(tmp_path))], capsys)
    with SessionFactory() as s:
        hired = s.scalar(select(Agent).where(Agent.name == "hire-1-pm"))
    assert hired is None, (
        "the Runtime hired a new PM although the firm already holds more alive agents than the "
        "Human's max_agents_total (2): the population cap binds nobody")


def test_redteam_a_world_recipe_cannot_set_more_live_pods_than_the_humans_agent_cap():
    """SEVERITY: high (same hole, by the new recipe route: a recipe raises a cap).

    Path: ``laws: {"hiring": {"max_live_pods": 1000}}`` is accepted by ``parse_recipe`` and sent
    to the hosted App as ``FUND_HIRING__MAX_LIVE_PODS=1000``, five times the Human's 200.
    """
    from app.config import REPO_ROOT
    from runtime import world as hosted_world

    human = REPO_ROOT / "governance" / "human.yaml"      # read only: the Human's own cap
    cap = yaml.safe_load(human.read_text())["firm"]["max_agents_total"]
    doc = {"start": "2024-09-01T14:30:00Z", "admin": "mgmt",
           "pods": [{"name": "a", "allocation": 0}],
           "laws": {"hiring": {"max_live_pods": cap + 1}}}
    with pytest.raises(hosted_world.WorldError):
        hosted_world.parse_recipe(doc)


# --- H2 (medium): a dead pod's later pitches still bind every other pod's correlation gate --------

SYMBOLS = {"SYNA": 100.0, "SYNB": 50.0, "SYNC": 20.0, "SYND": 35.0}
MANDATE = {"universe": ["SYNA", "SYNB"], "signal": "low_volatility", "lookback": 20,
           "rebalance_every": 5, "top_n": 1, "side": "long_only"}
LATER = {"universe": ["SYNA", "SYNB", "SYNC", "SYND"], "signal": "momentum", "lookback": 20,
         "rebalance_every": 5, "top_n": 1, "side": "long_short"}
PITCH = {"hypothesis": "Trends persist.", "data_needed": "daily prices", "team": "one analyst",
         "budget_usd": 5.0}


def _stage(SessionFactory, type_: str, payload: dict) -> int:
    s = SessionFactory()
    try:
        event = append_event(s, type=type_, actor_agent_id=get_or_create_system_agent(s).id,
                             payload=payload)
        s.commit()
        return event.id
    finally:
        s.close()


def _close_pod(SessionFactory, pod_id: int, rule: dict) -> None:
    pitch = _stage(SessionFactory, EVENT_PITCH_SUBMITTED, {"pod_id": pod_id, "rule": rule,
                                                           "hypothesis": "h"})
    _stage(SessionFactory, EVENT_CAPITAL_SEEDED, {"pod_id": pod_id, "pitch_id": pitch,
                                                  "seed_usd": 200_000.0, "rule": rule,
                                                  "cost_at_seed_usd": 0.0})
    _stage(SessionFactory, EVENT_POD_STAGE_CHANGED, {"pod_id": pod_id, "from": "active",
                                                     "to": "closed", "drawdown": 0.12,
                                                     "worst_drawdown": 0.12})
    with SessionFactory() as s:
        s.get(Pod, pod_id).status = "closed"
        s.commit()


def test_redteam_a_closed_pods_later_pitch_does_not_bind_another_pods_correlation_gate(
        client, SessionFactory, frozen_clock, make_pod, pm_factory):
    """SEVERITY: medium (a real advantage: an agent with nothing left to lose denies other pods
    capital; the replacement hire is the first target).

    Path: the ladder closes pod 1; its PM stays active and may still pitch (now told only "your
    pod was closed ... gets no capital"). Its later pitch of a rule it never traded becomes pod 1's
    "latest pitch", which ``submit_pitch`` puts into every other pod's correlation gate as
    ``"pod 1"``: any pod (the hire included) that pitches that rule after it fails the gate,
    though a closed pod can never be seeded with it. (The closed pod's *mandate* staying in the
    gate is the intended law; its post-mortem pitches are not.)
    """
    set_provider(SyntheticProvider(world_key(48), SYMBOLS))
    try:
        make_pod(1)
        make_pod(2)
        _, dead_pm = pm_factory("pm-1", 1)
        _, live_pm = pm_factory("pm-2", 2)
        _close_pod(SessionFactory, 1, MANDATE)
        squat = client.post("/pitches", headers=h(dead_pm), json={**PITCH, "rule": LATER})
        assert squat.status_code == 201, squat.text
        mine = client.post("/pitches", headers=h(live_pm), json={**PITCH, "rule": LATER})
        assert mine.status_code == 201, mine.text
        corr = next(g for g in mine.json()["verdict"]["gates"] if g["gate"] == "correlation")
        assert "pod 1" not in corr["against"], (
            "a closed pod's post-close pitch is in pod 2's correlation gate "
            f"(against {corr['against']}, result {corr['result']}): a dead PM blocks live pods")
    finally:
        set_provider(None)


# --- H3 (low): a capital answer dated before the decision it reports -------------------------------

def test_redteam_a_told_answer_is_never_dated_before_the_close_it_reports(
        client, SessionFactory, frozen_clock, make_pod, pm_factory):
    """SEVERITY: low (only mislabels a record a PM reads).

    Path: with ``tell_pms`` on, every pitch of a closed pod (eligible or not) is answered "your
    pod was closed by the risk ladder", and the answer's ``on`` is the pitch's own judging day.
    A pitch judged weeks before the close now reads, in the PM's own list, as answered "closed"
    on a day the pod was alive and trading.
    """
    make_pod(1)
    _, key = pm_factory("pm-1", 1)
    frozen_clock.set(datetime(2026, 6, 1, 15, tzinfo=timezone.utc))
    _stage(SessionFactory, EVENT_CAPITAL_OPENED, {"law": CapitalConfig(tell_pms=True).model_dump(),
                                                  "firm_capital_usd": 1e7})
    early = _stage(SessionFactory, EVENT_PITCH_SUBMITTED, {**PITCH, "pod_id": 1, "agent_id": 1,
                                                           "rule": MANDATE})
    _stage(SessionFactory, EVENT_PITCH_JUDGED, {"pitch_id": early, "pod_id": 1,
                                                "eligible": False, "gates": [], "attempts": 1})
    seeded = _stage(SessionFactory, EVENT_PITCH_SUBMITTED, {**PITCH, "pod_id": 1, "agent_id": 1,
                                                            "rule": MANDATE})
    _stage(SessionFactory, EVENT_PITCH_JUDGED, {"pitch_id": seeded, "pod_id": 1,
                                                "eligible": True, "gates": [], "attempts": 2})
    frozen_clock.set(datetime(2026, 6, 2, 15, tzinfo=timezone.utc))
    _stage(SessionFactory, EVENT_CAPITAL_SEEDED, {"pod_id": 1, "pitch_id": seeded,
                                                  "seed_usd": 200_000.0, "rule": MANDATE,
                                                  "cost_at_seed_usd": 0.0})
    frozen_clock.set(datetime(2026, 7, 1, 15, tzinfo=timezone.utc))
    _stage(SessionFactory, EVENT_POD_STAGE_CHANGED, {"pod_id": 1, "from": "active",
                                                     "to": "closed", "drawdown": 0.11,
                                                     "worst_drawdown": 0.11})
    answer = client.get(f"/pitches/{early}", headers=h(key)).json()["capital"]
    assert answer is None or answer["on"] >= "2026-07-01", (
        f"pitch #{early}, judged 2026-06-01, is answered {answer}: a close dated a month before "
        "it happened")
