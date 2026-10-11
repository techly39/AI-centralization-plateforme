"""Physical limits that clients must agree with physics on.

Pure constants, no imports: the MCP wrapper (``mcp_server``) may import this
module and ``app.config`` and nothing else from ``app`` (dependency law,
ADR-022, ``tests/test_boundaries.py``). A limit lives here when a client
validates the same bound before calling the API.
"""

#: Most tokens one report may claim, per direction. A report is one unit of
#: work; even a full million-token context re-read a hundred times fits. The cap
#: exists because the counts are summed per pod: unbounded, two int64-max
#: reports overflowed the sum and took the leaderboard down (red-team 0001).
MAX_TOKENS_PER_REPORT = 100_000_000

#: Most dollars one cost report may claim. A frontier model at list price
#: would need billions of tokens to reach it; the cap exists because costs are
#: summed per pod, and two 1e308 reports summed to ``inf`` and turned the
#: ranking number into ``null`` (red-team 0001, B-000d).
MAX_USD_PER_REPORT = 1_000_000.0

#: Largest order, in shares. With :data:`MAX_PRICE` it keeps every notional
#: (qty × price ≤ 1e16) finite; no real order comes near either bound.
MAX_ORDER_QTY = 1_000_000_000.0

#: Highest limit price an order may name, in dollars per share.
MAX_PRICE = 10_000_000.0

#: Largest integer every JSON reader holds exactly (JavaScript's
#: ``Number.MAX_SAFE_INTEGER``). The ledger holds no larger int (ADR-024).
MAX_SAFE_INT = 2**53 - 1

#: Largest id an agent may name in a path, query or body. Ids are
#: autoincrement and never get near it; the bound exists because an unbounded id
#: overflowed SQLite (500) or, copied into a ``permission_denied`` event, broke
#: the portable-ledger rule and lost the violation record (red-team 0002/0004,
#: auditor cycle 12).
MAX_ID = MAX_SAFE_INT

#: Deepest nesting a free JSON field (message ``structured_payload``, task
#: ``outcome``) may have. A thesis needs a handful of levels; ~256 levels was
#: stored and then could not be rendered, so every read of it was a 500
#: (red-team 0004).
MAX_JSON_DEPTH = 32

#: Deepest ledger payload: a free JSON field plus the event's own wrapping.
MAX_LEDGER_DEPTH = MAX_JSON_DEPTH + 4

#: Longest single step of a backtest clock (``POST /clock/advance``), in days.
#: A year per step covers any honest schedule; the bound keeps one call from
#: skipping a run past everything the pods were meant to live through (ADR-027).
MAX_ADVANCE_DAYS = 366

#: The same bound in minutes, for a step given in minutes.
MAX_ADVANCE_MINUTES = MAX_ADVANCE_DAYS * 24 * 60
