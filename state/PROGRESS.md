Cycle: 0038 · Mission: none active (M-001 merged) · Branch: main
Done so far: M-001 (metered pod month) merged: gate opens `fake-metered` with a key; keys under the
budget/cap law; one sync after the run; `GET /metering/agents`; ADR-044; EC4 ticked. Red-team: high+low
fixed, 2 medium + 1 low routed to M-004 (`tests/test_redteam_0021.py`, 3 strict xfails).
Next: build session → start M-002 (`protocol/CYCLE.md` §2): set it active, branch
`mission/M-002-proof-object`, architect plans it (Gate 2), write `acceptance/M-002.py`, see it fail.
Watch out:
- The Human's cap edit (`monthly_llm_usd_cap: 50`) and their `state/QUESTIONS.md` answers may be
  uncommitted in the working tree. NEVER `git add -A`: stage by path (it swept their edit into a
  commit once). The suite then fails locally in exactly 1 test (`test_the_real_human_yaml_reads_as_
  cap_null`, pins the committed null). Once the Human commits the cap, change that test to 50.0.
- The guard blocks Bash heredocs, `sed -i`, `python -c`, and any command naming the law directory
  (use Read). Write files with Write/Edit. The sandbox denied cloning into $TMPDIR (validator too).
- A metered month's bill grows with the published tool list (each new MCP tool moves it); acceptance
  asserts relations, not dollar constants.
- M-002 owns the compare-ledgers law for a trailing `cost_metered` block IF its cassette carries a
  metered run (ADR-044 §6); M-001 refuses `--cassette` on a metered run.
Acceptance: acceptance/M-001.py passes (ACCEPTED, Σ = exact); suite 1974 passed / 12 xfailed
(1 local failure while the Human's cap edit is uncommitted).
