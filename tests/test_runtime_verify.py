"""M-002 (ADR-045): ``fund-runtime replay --cassette F --verify``.

Claims under test: only a tape divergence or an unequal ledger after ``completed`` reads DIVERGED
(everything else that is not IDENTICAL is a SETUP ERROR, HALTED or unreadable); a divergence
names its step and wake; one file is enough (an empty working directory, no ``FUND_RUNTIME__*``,
specs never read off the disk); a tampered reply, a tampered ledger row, a wrong world key, an
unknown tool, a version-1 or world-less file, HALT, a redacted key in the recorded ledger each give
their own verdict and exit code. The pinned limit: the text of a wake's final reply is not hashed.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path

import pytest

from runtime import cassette, cli, governance, spec, verify, world
from runtime.verify import verdict_of
from tests.hosted_month import OTHER_KEY, WORLD_KEY

LOCATE = {"event_id": 9, "step": 2, "actor_agent_id": 5, "type": "message_sent", "genesis": False}
ROWS = [[1, "t", None, "run_started", "{}"], [2, "t", 3, "run_minds_declared", '{"minds":["scripted"]}'],
        [9, "t", 5, "message_sent", "{}"]]
RUN = {"agents": [["a-analyst", 5], ["b-pm", 6]]}


# --- the verdict, pure ------------------------------------------------------------------

EQUAL = {"equal": True, "allowed": 1, "first_difference": None, "locate": None}
UNEQUAL = {"equal": False, "allowed": 1, "first_difference": 9, "locate": LOCATE}


@pytest.mark.parametrize("ended, reason, compare, name, code", [
    ("completed", "completed", EQUAL, "IDENTICAL", 0),
    ("completed", "completed", UNEQUAL, "DIVERGED", 1),
    ("completed", "completed", None, "SETUP ERROR", 3),
    ("completed", "completed", {"allowed": 1}, "SETUP ERROR", 3),
    ("diverged", "diverged:b-pm:3:1:world", None, "DIVERGED", 1),
    ("diverged", "diverged:clock:2:0:calendar_at", None, "DIVERGED", 1),
    ("diverged", "diverged:clock:2:0:calendar_landed", None, "DIVERGED", 1),
    ("diverged", "diverged:garbage", None, "SETUP ERROR", 3),
    ("diverged", "diverged:b-pm:x:1:world", None, "SETUP ERROR", 3),
    ("halted", "halted", None, "HALTED", 4),
    ("refused", "wake_refused:b-pm:unknown_tool", None, "SETUP ERROR", 3),
    ("refused", "identity_mismatch:b-pm", None, "SETUP ERROR", 3),
    ("refused", "provision:contradiction", None, "SETUP ERROR", 3),
    ("refused", "wake_refused:b-pm:contradiction", None, "SETUP ERROR", 3),
    ("refused", "metered_over_cap", None, "SETUP ERROR", 3),
    ("error", "clock_unreadable:500", None, "SETUP ERROR", 3),
    ("error", "advance_failed:500", None, "SETUP ERROR", 3),
    ("something-new", "x", None, "SETUP ERROR", 3),
])
def test_verdict_of_only_diverged_or_unequal_is_diverged(ended, reason, compare, name, code) -> None:
    v = verdict_of({"ended": ended, "reason": reason, "run": RUN}, compare, ROWS, len(ROWS))
    assert (v.name, v.code) == (name, code), v.line
    assert ("DIVERGED" in v.line) == (name == "DIVERGED")  # no other line says it


def test_the_verdict_of_a_clean_replay_says_what_was_allowed() -> None:
    v = verdict_of({"ended": "completed", "reason": "completed", "run": RUN}, EQUAL, ROWS, 3)
    assert v.line == "IDENTICAL: 3 events, 0 differences, $0 (allowed: run_minds_declared scripted -> cassette)"
    v = verdict_of({"ended": "completed", "reason": "completed", "run": RUN},
                   {**EQUAL, "allowed": 0}, ROWS, 3)
    assert v.line == "IDENTICAL: 3 events, 0 differences, $0"


def test_parse_divergence_reasons() -> None:
    v = verdict_of({"ended": "diverged", "reason": "diverged:b-pm:14:2:world"}, None, ROWS, 3)
    assert v.line.startswith("DIVERGED at step 14, wake b-pm, turn 2: world")
    assert v.where == {"kind": "world", "step": 14, "wake": "b-pm", "turn": 2}
    v = verdict_of({"ended": "diverged", "reason": "diverged:clock:0:0:calendar_landed"}, None, ROWS, 3)
    assert v.line.startswith("DIVERGED at step 0, the calendar (calendar_landed)")
    assert v.where["wake"] is None


def test_a_ledger_divergence_names_the_wake_or_physics() -> None:
    out = {"ended": "completed", "reason": "completed", "run": RUN}
    v = verdict_of(out, UNEQUAL, ROWS, 3)
    assert v.line.startswith("DIVERGED at step 2, wake a-analyst, event 9 (message_sent)")
    assert v.where["wake"] == "a-analyst"
    other = {**UNEQUAL, "locate": {**LOCATE, "actor_agent_id": 3}}  # the registrar: not a mind
    assert verdict_of(out, other, ROWS, 3).line.startswith("DIVERGED at step 2, physics, event 9")
    assert verdict_of(out, {**UNEQUAL, "locate": None}, ROWS, 3).where["step"] is None  # null, not 0


def test_a_redacted_key_in_the_recorded_row_reads_as_a_key_difference() -> None:
    rows = [*ROWS[:2], [9, "t", 5, "message_sent", '{"body":"fk_<redacted>"}']]
    v = verdict_of({"ended": "completed", "reason": "completed", "run": RUN}, UNEQUAL, rows, 3)
    assert v.where["kind"] == "key" and "minted key" in v.line


# --- end to end, on the shared hosted recording -----------------------------------------

def _doc(rec) -> dict:
    return json.loads(rec.path.read_text(encoding="ascii"))


def _put(tmp_path: Path, doc: dict, name: str = "t") -> Path:
    path = tmp_path / f"{name}.cassette.json"
    path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="ascii")
    return path


def _verify(path: Path, monkeypatch: pytest.MonkeyPatch, key: str | None = WORLD_KEY,
            cwd: Path | None = None) -> tuple[int, str, str, dict | None]:
    for name in [n for n in os.environ if n.startswith("FUND_RUNTIME__")]:
        monkeypatch.delenv(name)
    if key is None:
        monkeypatch.delenv(world.WORLD_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(world.WORLD_KEY_ENV, key)
    if cwd is not None:
        monkeypatch.chdir(cwd)
    code, out, err = asyncio.run(verify.verify(path))
    first, _, rest = out.partition("\n")
    return code, first, err, (json.loads(rest) if rest.strip() else None)


def test_verify_identical_from_empty_cwd_without_runtime_env_e2e(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    lone = elsewhere / "m.cassette.json"
    lone.write_bytes(hosted_cassette.path.read_bytes())
    rows = len(_doc(hosted_cassette)["ledger"]["rows"])

    def no_disk(*a, **k):
        raise AssertionError("verify read specs off the disk")
    monkeypatch.setattr(spec, "load_specs", no_disk)  # claim: one file is enough
    monkeypatch.setattr(cli, "load_specs", no_disk)
    code, line, err, evidence = _verify(lone, monkeypatch, cwd=elsewhere)
    assert code == 0 and line.startswith(f"IDENTICAL: {rows} events, 0 differences, $0"), (line, err)
    assert evidence["events"] == rows and evidence["replay"]["ended"] == "completed"
    assert evidence["compare"]["equal"] is True and evidence["allowed"] == 1
    assert evidence["replay_usd"] == 0 and evidence["where"] is None
    assert evidence["cassette"]["bytes"] == lone.stat().st_size
    assert os.listdir(elsewhere) == ["m.cassette.json"]


def _first_place_order(doc: dict, from_step: int = 0):
    for st in doc["outcome"]["run"]["steps"]:
        for w in st["wakes"]:
            for m in w["transcript"]:
                for c in m.get("tool_calls") or []:
                    if st["step"] >= from_step and w["spec_id"] == "b-pm" and c["name"] == "place_order":
                        return st["step"], c
    return None


def test_tampered_reply_diverges_at_its_wake_e2e(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _doc(hosted_cassette)
    found = _first_place_order(doc)
    assert found is not None, "the 3-step month has no order to tamper with"
    step, call = found
    call["arguments"]["qty"] = max(1, call["arguments"]["qty"] // 2) \
        if call["arguments"]["qty"] > 1 else 2
    code, line, err, evidence = _verify(_put(tmp_path, doc), monkeypatch)
    assert code == 1 and line.startswith(f"DIVERGED at step {step}, wake b-pm, turn "), (line, err)
    assert evidence["where"]["kind"] == "world" and evidence["compare"] is None


def test_tampered_ledger_row_diverges_at_its_step_with_replay_completed_e2e(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _doc(hosted_cassette)
    rows = doc["ledger"]["rows"]
    advances = [r[0] for r in rows if r[3] == "clock_advanced"]
    victim = next(i for i, r in enumerate(rows) if r[0] > advances[1])  # the first row of step 2
    rows[victim][4] += " "
    code, line, err, evidence = _verify(_put(tmp_path, doc), monkeypatch)
    assert code == 1 and line.startswith("DIVERGED at step 2"), (line, err)
    assert evidence["where"]["event_id"] == rows[victim][0]
    assert evidence["replay"]["ended"] == "completed"  # every tape matched; only the ledger caught it


def test_wrong_world_key_is_setup_error_3(
        hosted_cassette, monkeypatch: pytest.MonkeyPatch) -> None:
    code, line, err, evidence = _verify(hosted_cassette.path, monkeypatch, key=OTHER_KEY)
    assert code == 3 and line.startswith("SETUP ERROR") and "event 1 (run_started)" in line
    assert "DIVERGED" not in line + err + json.dumps(evidence)


def test_unknown_tool_spec_is_setup_error_not_diverged(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _doc(hosted_cassette)
    for entry in doc["specs"]:
        if entry["spec"]["id"] == "b-pm":
            entry["spec"]["tools"] = ["no_such_tool"]
            entry["sha256"] = cassette.spec_sha256(entry["spec"])
    code, line, err, evidence = _verify(_put(tmp_path, doc), monkeypatch)
    assert code == 3 and "unknown_tool" in line and "DIVERGED" not in line + err
    assert evidence["verdict"] == "SETUP ERROR"


def test_missing_key_is_2_and_spawns_nothing(
        hosted_cassette, monkeypatch: pytest.MonkeyPatch) -> None:
    def spawned(*a, **k):
        raise AssertionError("a process was started without a key")
    monkeypatch.setattr(world.subprocess, "run", spawned)
    monkeypatch.setattr(world.subprocess, "Popen", spawned)
    code, line, err, _ = _verify(hosted_cassette.path, monkeypatch, key=None)
    assert code == 2 and line == "" and "world_key_missing" in err


def test_v1_and_worldless_cassettes_exit_2_by_name(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _doc(hosted_cassette)
    v1 = {"cassette_version": 1, "hash_format": doc["hash_format"], "outcome": doc["outcome"],
          "redactions": 0}
    code, _, err, _ = _verify(_put(tmp_path, v1, "v1"), monkeypatch)
    assert code == 2 and "cassette version 1" in err
    code, _, err, _ = _verify(_put(tmp_path, {**doc, "world": None, "ledger": None}, "nw"), monkeypatch)
    assert code == 2 and "no world" in err
    code, _, err, _ = _verify(tmp_path / "missing.cassette.json", monkeypatch)
    assert code == 2 and "cannot open" in err


def test_the_cassettes_own_inconsistencies_exit_2(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _doc(hosted_cassette)
    edited = copy.deepcopy(doc)
    edited["specs"][0]["spec"]["charter"] = "Other."  # without its digest
    code, _, err, _ = _verify(_put(tmp_path, edited, "digest"), monkeypatch)
    assert code == 2 and "digest" in err
    steps = copy.deepcopy(doc)
    steps["parameters"]["steps"] = 2
    code, _, err, _ = _verify(_put(tmp_path, steps, "steps"), monkeypatch)
    assert code == 2 and "steps" in err
    bad_recipe = copy.deepcopy(doc)
    bad_recipe["world"]["recipe"]["admin"] = "-x"
    code, _, err, _ = _verify(_put(tmp_path, bad_recipe, "recipe"), monkeypatch)
    assert code == 2 and "recipe_invalid" in err


def test_halt_is_exit_4(hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    halt = tmp_path / "HALT"
    halt.write_text("")
    monkeypatch.setattr(governance, "HALT_FILE", halt)
    code, line, err, evidence = _verify(hosted_cassette.path, monkeypatch)
    assert code == 4 and line.startswith("HALTED") and evidence["verdict"] == "HALTED"


def test_redacted_key_in_recorded_ledger_reads_diverged_key(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A mind that writes a minted key into the world makes its run unprovable; the verdict says so."""
    doc = _doc(hosted_cassette)
    rows = doc["ledger"]["rows"]
    victim = next(r for r in rows if r[3] == "message_sent")
    # the ledger keeps no message body, so the key rides in a text field the row does carry
    victim[4] = victim[4].replace('"to": "', '"to": "fk_<redacted> ', 1)
    assert "fk_<redacted>" in victim[4]
    code, line, err, evidence = _verify(_put(tmp_path, doc), monkeypatch)
    assert code == 1 and "minted key" in line and evidence["where"]["kind"] == "key", (line, err)


def test_final_reply_text_edit_still_verifies_identical(
        hosted_cassette, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The **pinned limit** (ADR-045), not a fix: the text of a wake's final reply is neither in
    any later request nor in the ledger, so editing it changes nothing a replay can see. IDENTICAL
    proves the acts and the world, not the prose after the last act."""
    doc = _doc(hosted_cassette)
    wake = doc["outcome"]["run"]["steps"][0]["wakes"][0]
    final = wake["transcript"][-1]
    assert final["role"] == "assistant" and not final["tool_calls"]
    final["content"] += " (edited after the fact)"
    code, line, err, _ = _verify(_put(tmp_path, doc), monkeypatch)
    assert code == 0 and line.startswith("IDENTICAL"), (line, err)
