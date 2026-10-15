"""A short month recorded in a world of the Runtime's own (M-002), shared by the e2e tests.

``record`` runs ``fund-runtime backtest --world`` in this process (the Runtime starts the real
``fund-env`` processes, as it does for an operator), with a planted ``FUND_DATABASE_URL`` that no
command may create. The session fixture ``hosted_cassette`` in ``conftest`` calls it once.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from runtime import cli, world

REPO = Path(__file__).resolve().parent.parent
DESK = REPO / "specs" / "desk-month"
WORLD_KEY = hashlib.sha256(b"fund-tests-M-002/1").hexdigest()
OTHER_KEY = hashlib.sha256(b"fund-tests-M-002/other").hexdigest()
STEPS = 3


@dataclass(frozen=True)
class Recorded:
    path: Path
    sentinel: Path
    stdout: str
    stderr: str
    outcome: dict


def record(directory: Path, steps: int = STEPS, key: str = WORLD_KEY) -> Recorded:
    path, sentinel = directory / "m.cassette.json", directory / "sentinel.db"
    out, err = io.StringIO(), io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(world.WORLD_KEY_ENV, key)
        mp.setenv("FUND_DATABASE_URL", f"sqlite:///{sentinel}")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["backtest", "--world", str(DESK / "world.json"), "--specs", str(DESK),
                             "--input", str(DESK / "input.json"), "--steps", str(steps),
                             "--cassette", str(path)])
    assert code == 0, err.getvalue()[-2000:]
    return Recorded(path, sentinel, out.getvalue(), err.getvalue(), json.loads(out.getvalue()))
