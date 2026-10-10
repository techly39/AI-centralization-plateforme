# METRICS — one row per cycle (append-only)

| cycle | date | era | unit | result | turns | tests | duration_min | notes |
|---|---|---|---|---|---|---|---|---|
| 0 | 2026-10-11 | 0→I | Bible installed | merged | – | 218 | – | by Human |
| 1 | 2026-10-11 | ½ | S-002 git hygiene | merged | ~60 | 250+10xf | ~25 | auditor BLOCK (flaky test) → fixed → PASS; red-team 10 holes |
| 2 | 2026-10-11 | ½ | B-000c token-overflow DoS | merged | ~45 | 267+9xf | ~20 | auditor PASS (4 notes fixed); red-team 12 held, 1 new low hole |
| 3 | 2026-10-11 | ½ | S-001 toolchain + run check | merged | ~40 | 267+9xf | ~15 | smoke 12/12; auditor PASS (5 notes fixed); no red-team (no physics change) |
| 4 | 2026-10-11 | ½ | S-003a repo survey, physics | merged | ~75 | 267+9xf | ~35 | 9 findings, probe P1–P9; auditor PASS (10 of 11 notes fixed, 1 at record); no red-team (no physics change) |
