"""RED-TEAM 0016 — attacks on cycle 0026's provisioning and the name binding
(ADR-032 (n), R-3b-2b-1: ``runtime/provision.py``; ``native.wake`` and
``lockstep.run_backtest`` compare ``/me``'s name with ``spec.name``).

Claims under attack:

* every spec is checked **before any is registered**; "a spec that could never
  wake gets no agent";
* ids and names are unique;
* if a registration fails part-way, ``ProvisionError.registered`` names the
  specs whose App agent exists ("a failure part-way names what was already
  registered, and only that exists");
* a key must wear its spec's name; HALT is re-read before every registration;
  keys are never written anywhere.

Attacker: a sloppy operator (specs, registrar, network) and a firm agent.

* Plain ``test_held_*``: the attack was refused; kept as regression guards.
* ``xfail(strict=True)``: a hole. When the Builder fixes it, strict mode fails
  the run and the marker must come off.

Run against 4eaeb29.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from mcp_server import FundClient
from runtime.native import wake
from runtime.provision import ProvisionError
from tests.test_runtime_lockstep import (  # noqa: F401  (fixtures)
    _app,
    conduct,
    gov,
    live_afterwards,
    woke,
    world,
)
from tests.test_runtime_provision import _made, _provision, _spec


class _LateTransport(httpx.AsyncBaseTransport):
    """Delivers the request, then loses the answer (a read timeout after the
    server committed): the network failure every real deployment eventually has."""

    def __init__(self, inner: httpx.AsyncBaseTransport, lose_for: str) -> None:
        self._inner, self._lose_for = inner, lose_for

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if request.url.path == "/agents/register" and self._lose_for.encode() in request.content:
            await response.aread()
            raise httpx.ReadTimeout("answer lost", request=request)
        return response


def _losing_registrar(name: str):
    class Registrar(FundClient):
        def __init__(self, *, transport, **kw) -> None:
            super().__init__(transport=_LateTransport(transport, name), **kw)
    return Registrar


# --- H1: a registration whose answer was lost is not named ------------------------------

# RED-TEAM 0016 H1 (low): when the registrar's POST reaches physics but the answer
# is lost (timeout, reset: FundClient turns it into FundAPIError 503), provision
# raises register_failed:<id>:503 with `registered` = the specs *before* it. The
# spec whose POST landed is not named, yet its App agent exists. The operator
# reads `registered == ()` as "the run database is clean" (ADR-027) and runs in a
# world holding an agent nobody declared. The wrong_agent branch already names
# the failing spec as "possibly registered"; a 5xx / unreachable answer is the
# same uncertainty and is not treated the same.
# Minimal fix: in provision, on FundAPIError with status_code >= 500 (or any
# non-4xx), raise ProvisionError(..., [*done, spec.id]) — only a 4xx answer
# proves nothing was created.
# Fixed in cycle 26 (a 5xx answer names the spec as possibly registered). Guard.
def test_hole_a_lost_registration_answer_hides_an_existing_agent(SessionFactory, world, woke):
    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2")]
    err, _, _ = _provision(SessionFactory, specs, world["admin"],
                           registrar=_losing_registrar("fresh-2"))
    assert isinstance(err, ProvisionError) and err.reason == "register_failed:b-pm:503"
    exists = {_made(SessionFactory)[n][2].removeprefix("spec:") for n in _made(SessionFactory)}
    assert exists == {"a-pm", "b-pm"}  # physics holds both agents
    assert set(err.registered) >= exists  # ...the error must name every one that may exist


# RED-TEAM 0016 H1b (low): an exception that is not a FundAPIError — the caller's
# `connect` failing on the key it was handed — escapes provision raw, so the
# operator is told nothing about the agents already created (here: both).
# Minimal fix: wrap `connect(...)` (and any non-FundAPIError from the POST) and
# raise ProvisionError("connect_failed:<id>", [*done, spec.id]) from it.
# Fixed in cycle 26 (connect_failed:<id> names it). Guard.
def test_hole_a_failing_connect_names_no_registered_agent(SessionFactory, world, woke,
                                                          monkeypatch):
    real_init = FundClient.__init__
    built: list[bool] = []

    def init(self, **kw):
        built.append(True)
        if len(built) == 3:  # registrar, a-pm's client, then b-pm's: the caller's connect fails
            raise OSError("could not open the mind's client")
        real_init(self, **kw)

    monkeypatch.setattr(FundClient, "__init__", init)
    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2")]
    try:
        out, _, _ = _provision(SessionFactory, specs, world["admin"])
    except OSError:
        out = None
    assert set(_made(SessionFactory)) == {"fresh-1", "fresh-2"}
    assert isinstance(out, ProvisionError) and set(out.registered) == {"a-pm", "b-pm"}


# --- H2: names unique only byte for byte ------------------------------------------------

# RED-TEAM 0016 H2 (low; the runtime side of B-042): `duplicate_name` compares the
# exact strings, so two specs whose names a reader cannot tell apart ("desk-pm"
# and "desk-pm" + U+200B, or "Desk-PM") pass the preflight and both are
# registered: two agents in the same pod under one visible name. The run maps
# them correctly (exact names), but every mind reading the directory or a
# message header sees one colleague twice. And once B-042 makes physics' unique
# check fold, this spec set fails *part-way* (409 after the first registration)
# instead of before anything is registered.
# Minimal fix: in provision, compare names under the same fold as physics
# (NFKC + casefold + drop Cc/Cf/Cn/Co/Cs/Mn/Me and blank characters + strip) —
# a runtime copy of `_name_key`, as runtime.governance copies the HALT path.
# Fixed in cycle 26 (names compared under physics' fold). Guard.
@pytest.mark.parametrize("twin", ["desk-pm​", "Desk-PM", "desk-pm ", "ｄｅｓｋ-pm"],
                         ids=["zero-width", "case", "trailing-space", "fullwidth"])
def test_hole_lookalike_spec_names_both_register(SessionFactory, world, woke, twin):
    specs = [_spec("a-pm", "desk-pm"), _spec("b-pm", twin)]
    err, _, _ = _provision(SessionFactory, specs, world["admin"])
    assert isinstance(err, ProvisionError) and (err.reason, err.registered) == (
        "duplicate_name", ())
    assert _made(SessionFactory) == {}


# --- H3: a name physics will refuse is found only after others were registered ----------

# RED-TEAM 0016 H3 (low): "every spec is checked before any is registered" and "a
# spec that could never wake gets no agent" — but a spec whose name physics must
# refuse (reserved: "Runtime", "system"; already held by an agent: "pm-2") passes
# the preflight, so every spec sorted before it is registered and the run
# database is spoiled by a mistake knowable in advance. (tests/test_runtime_
# provision.py pins the part-way 409 as intended; this test asks for the
# stronger law.)
# Minimal fix: in the preflight, refuse a spec whose folded name is reserved
# ({"system", "runtime"}, same fold as H2), and GET /agents through the registrar
# (management holds LIST_AGENTS) and refuse a spec whose folded name is taken —
# `name_taken:<id>` / `name_reserved:<id>` with registered=(). The race window
# that remains still fails closed (409).
# Fixed in cycle 26 (name_reserved / name_taken in the preflight). Guard.
@pytest.mark.parametrize("bad", ["Runtime", "system", "pm-2"], ids=["reserved-case", "reserved",
                                                                      "taken"])
def test_hole_a_name_physics_refuses_is_found_after_registering(SessionFactory, world, woke,
                                                                bad):
    specs = [_spec("a-pm", "fresh-1"), _spec("z-pm", bad)]
    err, _, _ = _provision(SessionFactory, specs, world["admin"])
    assert isinstance(err, ProvisionError) and err.registered == ()
    assert _made(SessionFactory) == {}


# --- held -------------------------------------------------------------------------------

@pytest.mark.parametrize("twin", ["pm-1​", "PM-1", "pm-1 ", "ｐｍ-1", "pm-1\x00"],
                         ids=["zero-width", "case", "trailing-space", "fullwidth", "nul"])
def test_held_a_lookalike_spec_name_cannot_wake_on_the_real_key(SessionFactory, world, woke,
                                                                 twin):
    """The binding is exact: a spec under a name that folds to pm-1's cannot use
    pm-1's key, through the wake or the conductor."""
    app = _app(SessionFactory)

    async def go():
        async with FundClient(base_url="http://fund.test", api_key=world["pm"][1],
                              transport=httpx.ASGITransport(app=app)) as pm_1:
            return await wake(_spec("a-pm", twin), pm_1, workflow_input={})

    with TestClient(app):
        record = asyncio.run(go())
    assert (record.ended, record.reason) == ("refused", "identity_mismatch")
    run = conduct(SessionFactory, [(_spec("a-pm", twin), world["pm"][1])], world["clock"],
                  steps=1)
    assert (run.ended, run.reason) == ("refused", "identity_mismatch:a-pm")
    assert woke == []


def test_held_lookalike_minds_stay_bound_to_their_own_specs(SessionFactory, world, woke):
    """Two lookalike agents registered outside provision (physics does not fold
    names yet, B-042; since the H2 fix provision refuses such a pair): the run
    does not swap them, each mind's /me is the agent its key belongs to.
    (Adapted in cycle 26 from its provision-built form.)"""
    with TestClient(_app(SessionFactory)) as http:  # the server installs the run's clock
        k1, k2 = (http.post("/agents/register", headers={"X-API-Key": world["admin"]},
                            json={"name": n, "role": "pm", "pod_id": 1}).json()["api_key"]
                  for n in ("desk-pm", "desk-pm​"))
    specs = [(_spec("a-pm", "desk-pm"), k1), (_spec("b-pm", "desk-pm​", script="read-b"), k2)]
    run = conduct(SessionFactory, specs, world["clock"], steps=1)
    assert run.ended == "completed", run.reason
    for wake_record in run.steps[0].wakes:
        me = wake_record.transcript[1].content
        spec_name = {"a-pm": "desk-pm", "b-pm": "desk-pm​"}[wake_record.spec_id]
        assert f'"name": {json.dumps(spec_name)}' in me


def test_held_a_race_for_the_name_fails_closed(SessionFactory, world, woke):
    """Someone registers the spec's name between the preflight and the POST: the
    POST is refused (409) and no mind is bound to the squatter."""
    class Squatted(FundClient):
        async def post(self, path, body=None, **params):
            if body and body.get("name") == "fresh-2":
                await super().post(path, {**body, "charter_ref": "squatter"})
            return await super().post(path, body, **params)

    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2")]
    err, _, closed = _provision(SessionFactory, specs, world["admin"], registrar=Squatted)
    assert (err.reason, err.registered) == ("register_failed:b-pm:409", ("a-pm",))
    assert closed == [True]


def test_held_no_key_in_errors_or_reprs(SessionFactory, world, woke):
    """Neither a ProvisionError (any branch) nor a returned Mind's repr carries a key."""
    seen_keys: list[str] = []

    class Spy(FundClient):
        async def post(self, path, body=None, **params):
            made = await super().post(path, body, **params)
            seen_keys.append(made["api_key"])
            return {**made, "pod_id": 3} if body["name"] == "fresh-2" else made

    specs = [_spec("a-pm", "fresh-1"), _spec("b-pm", "fresh-2")]
    err, _, _ = _provision(SessionFactory, specs, world["admin"], registrar=Spy)
    text = " ".join([str(err), repr(err), repr(err.__cause__), repr(err.__context__)])
    assert seen_keys and not any(k in text for k in seen_keys)
    seen_keys.clear()
    minds, _, _ = _provision(SessionFactory, [_spec("c-pm", "fresh-3")], world["admin"],
                             registrar=Spy)
    assert seen_keys and not any(k in repr(minds) for k in seen_keys)


def test_held_halt_during_the_last_registration_wakes_nothing(SessionFactory, world, woke, gov):
    """HALT that lands while the last POST is in flight: provision returns, but the
    run it is handed to wakes no one."""
    class HaltsOnLast(FundClient):
        async def post(self, path, body=None, **params):
            made = await super().post(path, body, **params)
            (gov / "HALT").write_text("")
            return made

    minds, run, _ = _provision(SessionFactory, [_spec("a-pm", "fresh-1")], world["admin"],
                               steps=2, clock_key=world["clock"], registrar=HaltsOnLast)
    assert run.ended != "completed" and woke == []
