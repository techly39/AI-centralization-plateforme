"""Red-team 0029 (cycle 42, ADR-047 §8) — MEDIUM: ``replay --verify`` says IDENTICAL for a metered
month whose cost rows were rewritten.

Severity: **medium** — a wrong record passes the proof: the ledger a cassette carries differs from
the one the run wrote, and the verifier prints IDENTICAL with the forged cost "reported apart".

The trailing block of ``cost_metered`` rows is cut from the comparison (nothing replays it) and is
judged only against the cassette's own ``outcome.metering`` — the same file. ``metered_block``
compares three fields of each row's body and the actor's *count*, so each of these edits verifies
IDENTICAL (exit 0):

* ``pod_id`` of a cost row moved to another pod (the body field ``metered_by_agent`` charges the
  cost to; the outcome does not carry it, so nothing else needs editing);
* the actor of the cost rows set to the management agent (physics only lets the ``runtime``
  identity post ``/metering/usage``; the check is only "one actor that is not a mind");
* every key's total set to $0 in both the rows and ``outcome.metering`` — although the cassette's
  own tapes record what each turn cost (``exchanges[].usage.cost_usd``), which the verifier never
  sums against the block;
* the whole block and ``outcome.metering`` removed from a run whose recorded specs are metered:
  the month verifies as one that cost nothing (``metered_block: null``).

Fixed in cycle 43; the tests now guard the fix.
"""

from __future__ import annotations

import json

import pytest

from runtime import verify
from tests.test_runtime_metered_cassette import _tampered, _verify, recorded  # noqa: F401 - fixture


def _body_edit(field, value):
    def edit(doc) -> None:
        body = json.loads(doc["ledger"]["rows"][-1][4])
        body[field] = value(body[field]) if callable(value) else value
        doc["ledger"]["rows"][-1][4] = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return edit


def _actor_to_management(doc) -> None:
    rows = doc["ledger"]["rows"]
    mgmt = next(json.loads(r[4])["agent_id"] for r in rows
                if r[3] == "agent_registered" and json.loads(r[4])["role"] == "management")
    for row in rows[-len(doc["outcome"]["metering"]["keys"]):]:
        row[2] = mgmt


def _zero_cost(doc) -> None:
    m = doc["outcome"]["metering"]
    for key in m["keys"]:
        key["spent_usd_micros"] = 0
    m["total_usd_micros"] = 0
    for row in doc["ledger"]["rows"][-len(m["keys"]):]:
        body = json.loads(row[4])
        body["usd_micros_total"] = 0
        row[4] = json.dumps(body, sort_keys=True, separators=(",", ":"))


def _no_cost_at_all(doc) -> None:
    n = len(doc["outcome"]["metering"]["keys"])
    del doc["ledger"]["rows"][-n:]
    del doc["outcome"]["metering"]


@pytest.mark.parametrize("edit", [
    _body_edit("pod_id", lambda p: (p or 0) + 1),
    _actor_to_management,
    _zero_cost,
    _no_cost_at_all,
], ids=["pod_moved", "actor_management", "zeroed", "removed"])
def test_hole_a_rewritten_cost_block_verifies_identical(recorded, tmp_path, edit) -> None:  # noqa: F811
    doc = json.loads(recorded.read_text(encoding="ascii"))
    assert any(s["spec"]["provider"] == "fake-metered" for s in doc["specs"])   # a metered month
    tapes = sum(e["usage"]["cost_usd"] for s in doc["outcome"]["run"]["steps"]
                for w in s.get("wakes") or [] for e in w.get("exchanges") or [])
    assert tapes > 0                                                         # its tapes record cost
    code, line, ev = _verify(_tampered(recorded, tmp_path, edit))
    assert code == verify.EXIT_DIVERGED, (line, ev.get("metered_block"))
