"""Every number that enters the world is finite (B-000d, ADR-024).

Python's ``json`` reads the non-standard literals ``NaN``, ``Infinity`` and
``-Infinity``, and an overflowing literal such as ``1e309`` becomes ``inf``.
None of them is a quantity of shares or dollars, and none of them is standard
JSON, so a ledger holding one cannot be read back by another tool. Three layers
keep them out:

* request schemas: every float field is bounded and finite, every free JSON
  field is walked — a clean 422 that names the field, nothing written;
* the validation-error handler answers 422 even when the offending input is
  itself ``NaN`` (it used to crash rendering it: 500);
* ``append_event`` refuses a non-finite payload, so no in-process caller can
  write one either.

The OpenAPI walk at the bottom makes the first layer hard to forget: a new float
field without an upper bound, or a new free JSON field this file does not
attack, turns the suite red.
"""

from __future__ import annotations

import json
import math

import pytest
from sqlalchemy import func, select

from app.db.models import Cost, Event, Message, Order, Task
from app.ledger.events import append_event
from app.limits import (
    MAX_ID,
    MAX_JSON_DEPTH,
    MAX_LEDGER_DEPTH,
    MAX_ORDER_QTY,
    MAX_PRICE,
    MAX_SAFE_INT,
    MAX_USD_PER_REPORT,
)


def H(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture
def desk(client, make_pod, fund_pod_cash, pm_factory, agent_factory):
    make_pod(1)
    fund_pod_cash(1, 100_000.0)
    return {"pm": pm_factory("pm-1", 1), "an": agent_factory("analyst-1", "analyst", 1)}


#: Raw JSON tokens, sent as text so the client cannot normalise them first.
NON_FINITE = ["NaN", "Infinity", "-Infinity", "1e309", "-1e309"]


def _raw(client, key, method, path, body: str):
    return client.request(method, path, content=body,
                          headers={**H(key), "Content-Type": "application/json"})


def _counts(db) -> tuple[int, ...]:
    db.expire_all()
    return tuple(db.scalar(select(func.count()).select_from(t)) for t in (Event, Cost, Order, Message, Task))


def _assert_clean_422(resp, field: str) -> None:
    assert resp.status_code == 422, resp.text
    json.loads(resp.text)  # standard JSON: no NaN/Infinity in the error itself
    assert any(field in [str(p) for p in err["loc"]] for err in resp.json()["detail"]), resp.text


# --- Float fields -----------------------------------------------------------

def _order_body(qty: str = "1", limit_price: str = "100") -> str:
    return ('{"ticker": "AAPL", "side": "buy", "price_type": "limit", "justification": "t", '
            f'"qty": {qty}, "limit_price": {limit_price}}}')


def _cost_body(usd: str) -> str:
    return f'{{"tokens_in": 1, "tokens_out": 1, "usd_cost": {usd}}}'


FLOAT_CASES = [
    ("pm", "/orders", "qty", lambda v: _order_body(qty=v)),
    ("pm", "/orders", "limit_price", lambda v: _order_body(limit_price=v)),
    ("an", "/costs", "usd_cost", _cost_body),
]


@pytest.mark.parametrize("token", NON_FINITE)
@pytest.mark.parametrize(("who", "path", "field", "make"), FLOAT_CASES,
                         ids=[c[2] for c in FLOAT_CASES])
def test_non_finite_float_is_a_clean_422_and_writes_nothing(client, desk, db, who, path, field,
                                                            make, token):
    before = _counts(db)
    _assert_clean_422(_raw(client, desk[who][1], "POST", path, make(token)), field)
    assert _counts(db) == before


@pytest.mark.parametrize(("who", "path", "field", "make", "cap"), [
    ("pm", "/orders", "qty", lambda v: _order_body(qty=v), MAX_ORDER_QTY),
    ("pm", "/orders", "limit_price", lambda v: _order_body(limit_price=v), MAX_PRICE),
    ("an", "/costs", "usd_cost", _cost_body, MAX_USD_PER_REPORT),
], ids=["qty", "limit_price", "usd_cost"])
def test_float_fields_are_bounded_at_their_cap(client, desk, db, who, path, field, make, cap):
    """Finite is not enough: two 1e308 costs sum to inf (red-team 0001). The cap
    itself is accepted, the next representable float above it is not."""
    before = _counts(db)
    _assert_clean_422(_raw(client, desk[who][1], "POST", path, make(repr(math.nextafter(cap, math.inf)))),
                      field)
    _assert_clean_422(_raw(client, desk[who][1], "POST", path, make("1e308")), field)
    assert _counts(db) == before
    assert _raw(client, desk[who][1], "POST", path, make(repr(cap))).status_code == 201


# --- Free JSON fields -------------------------------------------------------

def _message_body(payload: str) -> str:
    return f'{{"to": "pod:1", "body": "hi", "structured_payload": {payload}}}'


def _task_end(client, key, payload: str):
    task_id = client.post("/tasks/start", headers=H(key), json={"subject": "s"}).json()["id"]
    return _raw(client, key, "POST", "/tasks/end",
                f'{{"task_id": {task_id}, "outcome": {payload}}}')


@pytest.mark.parametrize("token", NON_FINITE)
@pytest.mark.parametrize("shape", ['{{"x": {t}}}', '{{"a": [1, {{"b": [{t}]}}]}}'],
                         ids=["flat", "nested"])
def test_non_finite_inside_structured_payload_is_refused(client, desk, db, token, shape):
    before = _counts(db)
    resp = _raw(client, desk["an"][1], "POST", "/messages", _message_body(shape.format(t=token)))
    _assert_clean_422(resp, "structured_payload")
    assert _counts(db) == before


@pytest.mark.parametrize("token", NON_FINITE)
@pytest.mark.parametrize("shape", ['{{"x": {t}}}', '{{"a": [1, {{"b": [{t}]}}]}}'],
                         ids=["flat", "nested"])
def test_non_finite_inside_task_outcome_is_refused(client, desk, db, token, shape):
    key = desk["an"][1]
    task_id = client.post("/tasks/start", headers=H(key), json={"subject": "s"}).json()["id"]
    before = _counts(db)
    resp = _raw(client, key, "POST", "/tasks/end",
                f'{{"task_id": {task_id}, "outcome": {shape.format(t=token)}}}')
    _assert_clean_422(resp, "outcome")
    assert _counts(db) == before
    assert db.scalar(select(func.count()).select_from(Task).where(Task.ended_at.is_not(None))) == 0


def test_finite_free_json_still_works(client, desk):
    """The walk refuses only non-finite numbers, not numbers."""
    key = desk["an"][1]
    payload = '{"conviction": 0.7, "big": 1e300, "neg": -2, "nested": [{"x": 1.5}], "s": "NaN"}'
    assert _raw(client, key, "POST", "/messages", _message_body(payload)).status_code == 201
    assert _task_end(client, key, payload).status_code == 200


# --- The ledger itself ------------------------------------------------------

@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("shape", ["flat", "nested", "tuple"])
def test_append_event_refuses_non_finite_payloads(db, bad, shape):
    payload = {"flat": {"x": bad},
               "nested": {"a": [1, {"b": [bad]}]},
               "tuple": {"a": (1.0, bad)}}[shape]
    before = _counts(db)
    with pytest.raises(ValueError, match="non-finite"):
        append_event(db, type="probe", actor_agent_id=None, payload=payload)
    db.rollback()
    assert _counts(db) == before


def _nested(depth: int) -> dict:
    """``depth`` nested dicts: ``_nested(1) == {"a": 1}``."""
    value: object = 1
    for _ in range(depth):
        value = {"a": value}
    return value  # type: ignore[return-value]


def test_free_json_depth_is_capped_exactly(client, desk, db):
    """MAX_JSON_DEPTH levels pass, one more is a 422 that writes nothing
    (red-team 0004: ~256 levels were stored and then unrenderable)."""
    key = desk["an"][1]
    ok = {"to": "pod:1", "body": "x", "structured_payload": _nested(MAX_JSON_DEPTH)}
    assert client.post("/messages", headers=H(key), json=ok).status_code == 201
    before = _counts(db)
    deep = {**ok, "structured_payload": _nested(MAX_JSON_DEPTH + 1)}
    _assert_clean_422(client.post("/messages", headers=H(key), json=deep), "structured_payload")
    assert _counts(db) == before


@pytest.mark.parametrize(("value", "ok"), [(MAX_SAFE_INT, True), (-MAX_SAFE_INT, True),
                                           (MAX_SAFE_INT + 1, False), (10**400, False)])
def test_free_json_integers_must_fit_a_float64_reader(client, desk, value, ok):
    body = {"to": "pod:1", "body": "x", "structured_payload": {"n": value, "flag": True}}
    resp = client.post("/messages", headers=H(desk["an"][1]), json=body)
    assert resp.status_code == (201 if ok else 422), resp.text


def test_append_event_refuses_deep_and_huge_int_payloads(db):
    before = _counts(db)
    for payload, why in (({"n": 2**60}, "2\\*\\*53"),
                         (_nested(MAX_LEDGER_DEPTH + 1), "deeper"),
                         (_nested(5000), "deeper")):
        with pytest.raises(ValueError, match=why):
            append_event(db, type="probe", actor_agent_id=None, payload=payload)
        db.rollback()
    append_event(db, type="probe", actor_agent_id=None, payload=_nested(MAX_LEDGER_DEPTH))
    db.rollback()
    assert _counts(db) == before


@pytest.mark.parametrize("path", ["/orders?pod={}", "/portfolio/{}"])
def test_cross_pod_probe_with_a_huge_id_is_refused_not_a_500(client, desk, db, path):
    """Auditor BLOCK, cycle 12: once the ledger refused ints beyond 2**53, a
    cross-pod read naming one made ``deny()`` raise — 500, and the
    ``permission_denied`` record was lost. Ids are now bounded at the door."""
    key = desk["an"][1]
    before = _counts(db)
    for big in (MAX_ID + 1, 2**60, 2**63):
        assert client.get(path.format(big), headers=H(key)).status_code == 422
    assert _counts(db) == before
    resp = client.get(path.format(MAX_ID), headers=H(key))
    assert resp.status_code == 403
    db.expire_all()
    denied = db.scalars(select(Event).where(Event.type == "permission_denied")).all()
    assert [e.payload_json["pod_id"] for e in denied] == [MAX_ID]


@pytest.mark.parametrize("ref", [f"agent:{MAX_ID + 1}", f"pod:{2**63}", "agent:" + "9" * 27])
def test_huge_recipient_ids_are_a_clean_422(client, desk, db, ref):
    before = _counts(db)
    resp = client.post("/messages", headers=H(desk["an"][1]), json={"to": ref, "body": "x"})
    assert resp.status_code == 422, resp.text
    assert _counts(db) == before


def test_every_integer_parameter_and_body_id_has_an_upper_bound(client):
    """No int an agent sends can reach SQLite or the ledger unbounded."""
    spec = client.get("/openapi.json").json()
    unbounded = [
        (path, param["name"])
        for path, item in spec["paths"].items()
        for op in item.values()
        for param in op.get("parameters", [])
        for v in param.get("schema", {}).get("anyOf", [param.get("schema", {})])
        if v.get("type") == "integer" and "maximum" not in v
    ]
    unbounded += [
        (name, field)
        for name, schema in _request_body_schemas(client).items()
        for field, prop in schema.get("properties", {}).items()
        for v in prop.get("anyOf", [prop])
        if v.get("type") == "integer" and "maximum" not in v
    ]
    assert unbounded == []


def test_report_cost_refuses_non_finite_in_process(db, desk):
    """The schema refuses first (422); this guards in-process callers (Runtime)."""
    from app.db.models import Agent
    from app.metrics.reporting import report_cost

    an = db.get(Agent, desk["an"][0])
    for bad in (math.nan, math.inf, -1.0, MAX_USD_PER_REPORT * 2):
        with pytest.raises(ValueError, match="usd_cost"):
            report_cost(db, reporter=an, tokens_in=1, tokens_out=1, usd_cost=bad)
        db.rollback()


# --- Coverage guard: the schema surface cannot grow past these tests -------

#: Free JSON (``dict``) request fields and the test above that attacks each one.
FREE_JSON_FIELDS = {
    ("MessageSendRequest", "structured_payload"): test_non_finite_inside_structured_payload_is_refused,
    ("TaskEndRequest", "outcome"): test_non_finite_inside_task_outcome_is_refused,
}
#: Bounded float request fields: (lower bound, cap). Attacked by the two float tests.
FLOAT_FIELDS = {
    ("OrderCreateRequest", "qty"): (0, MAX_ORDER_QTY),
    ("OrderCreateRequest", "limit_price"): (0, MAX_PRICE),
    ("CostReportRequest", "usd_cost"): (0, MAX_USD_PER_REPORT),
    # Attacked in tests/test_pitches.py (it has the market the rule needs).
    ("PitchIn", "budget_usd"): (0, MAX_USD_PER_REPORT),
    ("PitchIn.rule", "gross"): (0.01, 2.0),
    ("ResearchBacktestIn.rule", "gross"): (0.01, 2.0),
}

#: Leaf types that cannot carry a float: nothing to bound, nothing to walk.
PLAIN = {"string", "integer", "boolean", "null"}


def _classify(prop: dict, components: dict | None = None) -> tuple[str, object]:
    """One field's schema -> ("plain", None) | ("float", (low, high)) | ("json", None)
    | ("unclassified", schema). Plain covers strings, ints, bools, enums (also
    behind a ``$ref``) and arrays of those. Anything else this walk cannot see
    into — arrays of numbers or objects, nested models, untyped (``Any``) — is
    unclassified and fails the guard: a new shape must arrive with its own
    attack, not slip past."""
    components = components or {}
    kinds = set()
    for v in prop.get("anyOf", [prop]):
        if "$ref" in v:
            v = components.get(v["$ref"].rsplit("/", 1)[-1], {})
            if "enum" in v and v.get("type") in PLAIN:
                continue
            return ("unclassified", v)
        t = v.get("type")
        if t in PLAIN:
            continue
        if t == "array" and _classify(v.get("items", {}), components)[0] == "plain":
            continue
        if t == "number":
            low = v.get("minimum", v.get("exclusiveMinimum"))
            high = v.get("maximum", v.get("exclusiveMaximum"))
            kinds.add(("float", (low, high)))
        elif t == "object" and not v.get("properties"):
            kinds.add(("json", None))
        else:
            return ("unclassified", v)
    if len(kinds) > 1:
        return ("unclassified", prop)
    return kinds.pop() if kinds else ("plain", None)


def _request_body_schemas(client) -> dict[str, dict]:
    spec = client.get("/openapi.json").json()
    names = set()
    for item in spec["paths"].values():
        for op in item.values():
            ref = (op.get("requestBody", {}).get("content", {})
                   .get("application/json", {}).get("schema", {}).get("$ref"))
            if ref:
                names.add(ref.rsplit("/", 1)[-1])
    return {n: spec["components"]["schemas"][n] for n in names}


def _fields(name: str, schema: dict, components: dict):
    """(model, field), prop for every field, nested models walked: ``PitchIn.rule`` names the
    fields of the rule inside a pitch, so a float or int inside a nested model is seen too."""
    for field, prop in schema.get("properties", {}).items():
        ref = prop.get("$ref")
        sub = components.get(ref.rsplit("/", 1)[-1], {}) if ref else {}
        if sub.get("properties"):
            yield from _fields(f"{name}.{field}", sub, components)
        else:
            yield (name, field), prop


def test_every_nested_request_integer_has_an_upper_bound(client):
    """The integer walk above sees top-level fields; this one sees inside nested models."""
    spec = client.get("/openapi.json").json()
    components = spec["components"]["schemas"]
    unbounded = [key for name, schema in _request_body_schemas(client).items()
                 for key, prop in _fields(name, schema, components)
                 for v in prop.get("anyOf", [prop])
                 if v.get("type") == "integer" and "maximum" not in v]
    assert unbounded == []


def test_every_request_float_is_bounded_and_every_free_json_field_is_attacked(client):
    schemas = _request_body_schemas(client)
    assert schemas, "no request bodies found — the walk is broken, not the API safe"
    components = client.get("/openapi.json").json()["components"]["schemas"]
    found = {key: _classify(prop, components)
             for name, schema in schemas.items()
             for key, prop in _fields(name, schema, components)}
    assert [k for k, (kind, _) in found.items() if kind == "unclassified"] == []
    assert {k: b for k, (kind, b) in found.items() if kind == "float"} == FLOAT_FIELDS, \
        "a request float without both bounds, or one these tests do not attack"
    assert {k for k, (kind, _) in found.items() if kind == "json"} == set(FREE_JSON_FIELDS), \
        "a free JSON request field this file does not attack"


@pytest.mark.parametrize("prop", [
    {"type": "array", "items": {"type": "number"}},
    {"type": "array", "items": {"type": "object"}},
    {"anyOf": [{"$ref": "#/components/schemas/Sub"}, {"type": "null"}]},
    {},
    {"type": "number"},
], ids=["list-float", "list-dict", "nested-model", "any", "unbounded-float"])
def test_the_guard_sees_shapes_it_cannot_walk(prop):
    """Planted counter-examples (auditor, cycle 12): the first four are
    unclassified; an unbounded float is classified with ``None`` bounds, which
    can never equal ``FLOAT_FIELDS``."""
    kind, bounds = _classify(prop)
    assert kind == "unclassified" or bounds == (None, None)


def test_no_query_or_path_parameter_can_carry_a_float(client):
    """The walk above covers request bodies only. Today every parameter is plain;
    the first one that is not must arrive with its own bound and attack here."""
    spec = client.get("/openapi.json").json()
    offenders = [
        (method, path, param["name"])
        for path, item in spec["paths"].items()
        for method, op in item.items()
        for param in op.get("parameters", [])
        if _classify(param.get("schema", {}), spec["components"]["schemas"])[0] != "plain"
    ]
    assert spec["paths"] and offenders == []
