"""S3 — the Runtime (bible/03_WORLD.md §3, ADR-032).

A separate client process that decides *when* a mind wakes and *what it sees*,
never what is allowed: every rule that matters lives in physics (``app/``),
which the Runtime reaches only over HTTP with each agent's own key.

R-1 (cycle 21) ships the skeleton and its gates only — nothing wakes yet:

* :mod:`runtime.governance` reads the Human's HALT file and cap, fresh, from fixed paths;
* :mod:`runtime.gate` decides whether a provider may wake, failing closed;
* :mod:`runtime.spec` is the AgentSpec (the genome), file-backed for now;
* :mod:`runtime.providers` is the ``LLMProvider`` seam every mind plugs into;
* :mod:`runtime.cli` is ``uv run fund-runtime``.
"""
