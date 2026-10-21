"""Every kept recording of a completed run still replays IDENTICAL under today's physics.

A recording is the proof of a finished idea; a change to physics that makes one diverge breaks
that proof (auditor, the firm lives a quarter: a gate rule applied to every run made the cycle-51
hire diverge, and no suite test replayed it). Trials that are kept for what they found and are
known not to replay (their README says why) are listed apart. Each replay is offline and $0.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evidence"

#: recording → the world key it was made with (ADR-045: never in the file; each demo names it)
KEYS = {
    "pitch-gates/session.cassette.json": b"fund-pitch-gates/1",
    "pod-replacement/hire.cassette.json": b"fund-pod-replacement/1",
    "real-agents-backtest/month.cassette.json": b"fund-real-agents-backtest/1",
    "firm-quarter/quarter.cassette.json": b"fund-firm-quarter/1",
    "generation-turnover/generations.cassette.json": b"fund-generation-turnover/1",
    "designs-reproduce/reproduce.cassette.json": b"fund-generation-turnover/1",
    "pm-builds-team/team.cassette.json": b"fund-generation-turnover/1",
}
#: kept trials that do not replay against today's code, and why (each has its README line)
TRIALS = {
    "pod-replacement/trial-1-refusal-unseen.cassette.json": "pitches now carry the capital answer",
    "firm-quarter/trial-1-meter-timeout.cassette.json": "stopped at step 26: only a completed "
                                                        "run replays",
}


def test_every_recording_is_named_here() -> None:
    found = {str(p.relative_to(EVIDENCE)) for p in EVIDENCE.rglob("*.cassette.json")}
    assert found <= set(KEYS) | set(TRIALS), f"a recording no test replays: {found - set(KEYS)}"


@pytest.mark.parametrize("name", sorted(KEYS))
def test_a_kept_recording_replays_identical(name: str, tmp_path: Path) -> None:
    tape = EVIDENCE / name
    assert tape.is_file(), f"{name} is gone: a finished idea's proof is never deleted"
    lone = tmp_path / "run.cassette.json"
    lone.write_bytes(tape.read_bytes())
    (tmp_path / "vtmp").mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("FUND_", "OPENROUTER", "VIRTUAL_ENV"))
           and k.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    env.update({"FUND_MARKETDATA__SYNTHETIC_KEY": hashlib.sha256(KEYS[name]).hexdigest(),
                "TMPDIR": str(tmp_path / "vtmp"),
                "FUND_DATABASE_URL": f"sqlite:///{tmp_path / 'sentinel.db'}",
                "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"})
    r = subprocess.run(["uv", "run", "--project", str(REPO), "fund-runtime", "replay",
                        "--cassette", lone.name, "--verify"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=900)
    line, _, rest = r.stdout.partition("\n")
    assert r.returncode == 0 and line.startswith("IDENTICAL:"), (
        f"{name}: exit {r.returncode}: {line or r.stderr.strip()[-400:]}")
    assert json.loads(rest).get("replay_usd") == 0
