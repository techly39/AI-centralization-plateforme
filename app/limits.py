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
