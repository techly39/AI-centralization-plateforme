Cycle: 0038 · Mission: none active (M-001 merged) · Branch: main
Done so far: M-001 (metered pod month) merged: gate opens `fake-metered` with a key; keys under the
budget/cap law; one sync after the run; `GET /metering/agents`; ADR-044; EC4 ticked. Red-team: high+low
fixed, 2 medium + 1 low routed to M-004 (`tests/test_redteam_0021.py`, 3 strict xfails).
Next: build session → start M-002 (`protocol/CYCLE.md` §2): set it active, branch
`mission/M-002-proof-object`, architect plans it (Gate 2), write `acceptance/M-002.py`, see it fail.
Watch out:
- The Human committed the cap (`monthly_llm_usd_cap: 50`, 5ae0942, 2026-10-16); the real-law
  tripwire now pins it (`test_the_real_human_yaml_reads_as_cap_50`). Still NEVER `git add -A`: stage
  by path (it swept a Human edit into a commit once).
- The guard blocks Bash heredocs, `sed -i`, `python -c`, and any command naming the law directory
  (use Read). Write files with Write/Edit. The sandbox denied cloning into $TMPDIR (validator too).
- A metered month's bill grows with the published tool list (each new MCP tool moves it); acceptance
  asserts relations, not dollar constants.
- M-002 owns the compare-ledgers law for a trailing `cost_metered` block IF its cassette carries a
  metered run (ADR-044 §6); M-001 refuses `--cassette` on a metered run.
Acceptance: acceptance/M-001.py passes (ACCEPTED, Σ = exact); suite 1974 passed / 12 xfailed.
