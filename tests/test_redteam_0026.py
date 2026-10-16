"""Red-team 0026 (cycle 42, ADR-047) — HIGH: a cap lowered mid-run is held against this run alone.

Severity: **high** — the firm keeps spending past the cap the Human just set.

Red-team 0021 made the conductor re-read the cap before every wake (``lockstep._limits_fit``). With
the fake provisioner every key of the month was in the run, so Σ this run's limits was the month.
With OpenRouter it is not (ADR-047 §4): earlier runs this month already spent. ``_limits_fit``
still sums only the run's own key limits, so after the Human lowers the cap from $50 to $47 with
$45 already spent by earlier runs and this run holding two $2.50 keys, the check reads 5 <= 47 and
every mind keeps waking: the month can reach $50 against a $47 cap. The pre-mint check
(``month_committed``) knows the month; the mid-run check never asks it.

Hole tests are ``xfail(strict=True)``: they pass once the Builder fixes the physics.
"""

from __future__ import annotations

import httpx
import pytest

from tests.test_runtime_cli_backtest import _run, _write_specs, keys  # noqa: F401 - fixtures
from tests.test_runtime_lockstep import gov, live_afterwards, world  # noqa: F401 - fixtures
from tests.test_runtime_metered_run import _cap
from tests.test_runtime_openrouter import _or_spec, account, chat, faked  # noqa: F401 - fixtures


@pytest.mark.xfail(strict=True, reason=(
    "HIGH red-team 0026: after the cap is lowered mid-run below the month's commitment, the "
    "next mind still wakes and spends (the conductor sums this run's limits, not the month's)"))
def test_hole_a_lowered_cap_ignores_what_earlier_runs_spent_this_month(
        SessionFactory, keys, tmp_path, gov, faked, capsys) -> None:  # noqa: F811
    _cap(gov, 50)
    faked.add("firm-earlier-pm", limit=45.0, usage=45.0, disabled=True)    # $45 spent this month
    inner = faked.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions") and not faked.chats:
            _cap(gov, 47)                       # the Human lowers the cap during a-pm's first turn
        return inner(request)

    faked.handler = handler
    faked.answers += [chat("done", cost=0.001), chat("done", cost=0.001)]
    specs = _write_specs(tmp_path / "specs", _or_spec("a-pm", "desk-1-pm", 1, 2.5),
                         _or_spec("b-pm", "desk-2-pm", 2, 2.5))
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    woke_after = [c for c in faked.chats if faked.keys[c["key"]]["name"] == "firm-t1-b-pm"]
    # The month holds $45 spent + $5 of limits = $50 > $47: b-pm must not wake.
    assert woke_after == [], (out["ended"], out["reason"], len(faked.chats))


def test_held_a_cap_lowered_below_this_runs_own_limits_stops_the_next_wake(
        SessionFactory, keys, tmp_path, gov, faked, capsys) -> None:  # noqa: F811
    _cap(gov, 50)
    inner = faked.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions") and not faked.chats:
            _cap(gov, 4)
        return inner(request)

    faked.handler = handler
    faked.answers += [chat("done", cost=0.001), chat("done", cost=0.001)]
    specs = _write_specs(tmp_path / "specs", _or_spec("a-pm", "desk-1-pm", 1, 2.5),
                         _or_spec("b-pm", "desk-2-pm", 2, 2.5))
    code, out, err = _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    assert out["reason"] == "metered_over_cap" and len(faked.chats) == 1
    assert all(k["disabled"] for k in faked.keys.values() if k["name"].startswith("firm-t1-"))
