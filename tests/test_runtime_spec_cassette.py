"""M-002: the specs a cassette carries (``runtime.spec.specs_from_cassette``).

One file is enough: the specs come out of the cassette, never off the disk, and a spec edited
inside the file without its digest is refused, not run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from runtime.cassette import spec_sha256
from runtime.spec import AgentSpec, SpecError, load_specs, specs_from_cassette

DESK = Path(__file__).resolve().parent.parent / "specs" / "desk-month"


def _entries() -> list[dict]:
    return [{"sha256": spec_sha256(s.model_dump(mode="json")), "spec": s.model_dump(mode="json")}
            for s in load_specs(DESK)]


def test_specs_round_trip_through_the_cassette() -> None:
    assert specs_from_cassette(_entries()) == load_specs(DESK)


def test_specs_from_cassette_refuses_a_digest_mismatch_and_duplicate_ids() -> None:
    entries = _entries()
    edited = [dict(e) for e in entries]
    edited[0] = {"sha256": entries[0]["sha256"], "spec": dict(entries[0]["spec"], charter="Other.")}
    with pytest.raises(SpecError, match="digest"):
        specs_from_cassette(edited)
    with pytest.raises(SpecError, match="unique and sorted"):
        specs_from_cassette([entries[0], entries[0]])
    with pytest.raises(SpecError, match="unique and sorted"):
        specs_from_cassette(list(reversed(entries)))
    with pytest.raises(SpecError, match="no specs"):
        specs_from_cassette([])


def test_a_digest_right_but_invalid_spec_is_refused() -> None:
    body = dict(_entries()[0]["spec"], role="king")
    with pytest.raises(SpecError, match="not a spec"):
        specs_from_cassette([{"sha256": spec_sha256(body), "spec": body}])
    extra = dict(_entries()[0]["spec"], tools_extra=1)  # extra="forbid"
    with pytest.raises(SpecError, match="not a spec"):
        specs_from_cassette([{"sha256": spec_sha256(extra), "spec": extra}])


def test_a_dumped_spec_validates_again() -> None:
    raw = yaml.safe_load((DESK / "b-pm.yaml").read_text())
    spec = AgentSpec.model_validate(raw)
    assert AgentSpec.model_validate(spec.model_dump(mode="json")) == spec
