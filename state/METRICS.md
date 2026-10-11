# METRICS — one row per cycle (append-only)

| cycle | date | era | unit | result | turns | tests | duration_min | notes |
|---|---|---|---|---|---|---|---|---|
| 0 | 2026-10-11 | 0→I | Bible installed | merged | – | 218 | – | by Human |
| 1 | 2026-10-11 | ½ | S-002 git hygiene | merged | ~60 | 250+10xf | ~25 | auditor BLOCK (flaky test) → fixed → PASS; red-team 10 holes |
| 2 | 2026-10-11 | ½ | B-000c token-overflow DoS | merged | ~45 | 267+9xf | ~20 | auditor PASS (4 notes fixed); red-team 12 held, 1 new low hole |
| 3 | 2026-10-11 | ½ | S-001 toolchain + run check | merged | ~40 | 267+9xf | ~15 | smoke 12/12; auditor PASS (5 notes fixed); no red-team (no physics change) |
| 4 | 2026-10-11 | ½ | S-003a repo survey, physics | merged | ~75 | 267+9xf | ~35 | 9 findings, probe P1–P9; auditor PASS (10 of 11 notes fixed, 1 at record); no red-team (no physics change) |
| 5 | 2026-10-11 | ½ | S-003b repo survey, the rest | merged | ~40 | 267+9xf | ~15 | resumed interrupted run; live key found (Q-0003); probe R1–R4; auditor PASS (3 notes fixed, 1 → next) ; no red-team (no physics change) |
| 6 | 2026-10-11 | ½ | S-004a cleanup edits | merged | ~45 | 267+9xf | ~15 | key redacted (git rm denied headless → P-0002, S-004b); auditor PASS (5 notes: 2 fixed, 3 at record); no red-team (no physics change) |
| 7 | 2026-10-11 | ½ | S-005 OpenClaw survey | merged | ~50 | 267+9xf | ~20 | backup + probe O1–O6; auditor BLOCK ×2 (missed xAI key file, double count) → fixed → PASS (5 notes → backlog); chmod denied headless → Q-0004; no red-team (no physics change) |
| 8 | 2026-10-11 | ½ | S-006 Bible corrections | merged | ~30 | 267+9xf | ~10 | ADR-020; 00/01 no proposal; auditor BLOCK ×2 (tools.profile not global-only — cycle-7 error; docs default counted as measured) → fixed → PASS (3 notes); no red-team (docs only) |
| 9 | 2026-10-11 | ½→I | S-007 close Era ½ | merged | ~30 | 267+9xf | ~12 | 5/5 exit criteria ticked (SURVEY §10), ADR-021; auditor BLOCK ×1 (physics bugs silently demoted) → fixed → PASS; no red-team (docs only) |
| 10 | 2026-10-11 | I | B-002 dependency-law test + retro | merged | ~40 | 283+9xf | ~20 | ADR-022, app/limits.py; red first on mcp_server only; auditor BLOCK ×1 (literal dynamic imports missed, ADR overstated) → fixed → PASS; smoke 12/12; no red-team (no registry/OMS/marketdata/metering change); retro: 10/10 merged, 5/10 BLOCKed → X-006 |
| 11 | 2026-10-11 | I | B-003 halt in physics | merged | ~90 | 334+9xf | ~45 | step 0 committed Human intervention; ADR-023; mutation 11/11 red; auditor BLOCK ×2 (halt path configurable; per-role overstatement) → fixed → PASS; red-team 0003: 2 holes (covert ledger channel, monitor TOCTOU) fixed same cycle, 13 held; smoke 12/12 |
