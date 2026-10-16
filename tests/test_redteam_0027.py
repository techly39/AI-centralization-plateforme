"""Red-team 0027 (cycle 42, ADR-047) — LOW: a sync that crashes leaves the run's real keys enabled.

Severity: **low** — no cap is passed (an enabled key still counts its whole limit in the month, and
its secret dies with the process), but ADR-047 §3 "every key the run made is disabled" fails and
the month stays blocked by limits nobody can spend until the Human disables them by hand.

In ``cli._conduct`` the keys are disabled on the line *after* ``_sync_metering`` in the same
``finally``. ``_sync_metering`` catches ``OpenRouterError``/``httpx.HTTPError`` from the meter read
and ``FundAPIError`` from the post, but not a transport failure of the post itself: the App dying
at the end of a run (``httpx.ConnectError`` from ``sync_costs``), a ``KeyboardInterrupt`` during the
up-to-30-second settle wait, or any bug in the report. Then ``provisioner.close()`` never runs and
the outcome never says ``keys_left_enabled``. ``close()`` belongs in its own ``finally``.

Hole tests are ``xfail(strict=True)``: they pass once the Builder fixes the physics.
"""

from __future__ import annotations

import httpx
import pytest

from runtime import cli
from tests.test_runtime_cli_backtest import _run, _write_specs, keys  # noqa: F401 - fixtures
from tests.test_runtime_lockstep import gov, live_afterwards, world  # noqa: F401 - fixtures
from tests.test_runtime_metered_run import _cap
from tests.test_runtime_openrouter import _or_spec, account, chat, faked  # noqa: F401 - fixtures


@pytest.mark.xfail(strict=True, reason=(
    "LOW red-team 0027: when the cost sync raises (the App's connection drops), the run's "
    "OpenRouter keys are never disabled"))
def test_hole_a_crashing_sync_leaves_the_keys_enabled(
        SessionFactory, keys, tmp_path, gov, faked, capsys, monkeypatch) -> None:  # noqa: F811
    _cap(gov, 50)

    async def drops(*args, **kwargs):
        raise httpx.ConnectError("the App went away")

    monkeypatch.setattr(cli, "sync_costs", drops)
    faked.answers += [chat("done", cost=0.001)]
    specs = _write_specs(tmp_path / "specs", _or_spec("a-pm", "desk-1-pm", 1, 1.0))
    try:
        _run(SessionFactory, ["--specs", str(specs), "--steps", "1"], capsys)
    except BaseException:  # noqa: BLE001 - a crash is the careless run under test
        pass
    made = [k for k in faked.keys.values() if k["name"].startswith("firm-t1-")]
    assert made and all(k["disabled"] for k in made), [(k["name"], k["disabled"]) for k in made]
