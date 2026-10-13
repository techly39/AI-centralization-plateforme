# MISSIONS — how work is written (the mission standard)

Builder-owned (ADR-042). Every mission in `state/missions.json` meets this standard. Planning
sessions write missions; build sessions finish them. Anything written before cycle 37 in slices
(`state/BACKLOG.md`, R-1…R-8, `state/plans/`) is **raw material**, not instructions: it is re-cut
into missions under these rules, never followed step by step.

## 1. What a mission is

A mission is **a capability of the world that someone can run and inspect**. It is named by what
becomes possible, not by the work it takes.

- Good: *"A two-mind pod lives a 31-day month through the Runtime, and every dollar it spends is
  charged by the system, not self-reported."*
- Bad: *"R-6b: gate accepts metered provider"* (an internal step), *"prepare X"*, *"investigate Y"*,
  *"refactor Z"* (unless the refactor itself unlocks a capability you can name).

Why: work cut into internal slices (cycles 1–36) produced ~1 demonstrable capability per 6 cycles,
with the full review ceremony paid on every slice (cycle-36 diagnosis, ADR-042). The field converged
on the same lesson: a unit is a feature someone can test end to end (Anthropic, "Effective harnesses
for long-running agents", 2025; "Harness design for long-running apps", 2026).

## 2. The fields (`state/missions.json`)

```json
{"id": "M-001", "title": "<the capability, one line>",
 "kind": "capability | experiment | hardening | process",
 "question": "<what this lets us learn or do; the Era question or exit criterion it serves>",
 "acceptance": "acceptance/M-001.py",
 "demo": "<the one command the Human runs to see it, and what they will see>",
 "status": "ready | active | done | dropped",
 "estimate_sessions": 2, "physics": true, "depends_on": [], "serves": ["Era I EC4"],
 "branch": "mission/M-001-<slug>", "notes": "<why dropped / anything the next planner must know>"}
```

The list order is the priority order. Status moves `ready → active → done`, or `→ dropped` with a
reason in `notes`. Only one mission is `active` at a time while `builder.parallel_workers` is 0.

## 3. Concrete, efficient, stable — the three tests a mission must pass before it is `ready`

**Concrete.** It has an acceptance check and a demo line. If you cannot say what command proves it
and what the output must show, it is not a mission yet: it is an idea (`state/IDEAS.md`).

**Efficient.** Estimated at **1 to 4 build sessions**. Larger → split **by capability** (each part is
still a thing someone can run), never by layer ("backend, then tests, then docs" is forbidden: the
layers of one capability share files and interfaces). Smaller than half a session → fold it into a
neighbour or into a hardening mission. It reuses what exists (name the modules) and builds nothing
for a later Era (`01_GENESIS.md` prime rule: never build Era N+2 to finish Era N).

**Stable.** Done means: acceptance passes, the full suite is green, nothing old regressed (every
earlier mission's acceptance still passes — the runner re-runs them before each planning session),
and physics changes met the red-team.

## 4. The acceptance check (`acceptance/M-NNN.py`)

The mission's definition of done, in code. The runner — not an agent — runs it out of band after
the session (ADR-042: a judge reading the transcript accepts regressions; a check grounded in the
running system does not — arXiv 2607.25152).

- Runs as `uv run python acceptance/M-NNN.py` from the repo root; **exit 0 = the capability works**.
- Exercises the capability **end to end, the way the Human's demo would** (start the App, run the
  Runtime, read the ledger/report). Re-running unit tests is not an acceptance check.
- Checks **outcomes**, not implementation details; prints the evidence it checked (numbers, ids).
- Deterministic, offline (localhost only), no real money, no LLM calls, finishes in < 15 minutes,
  cleans up after itself (temp dirs, its own ports, its own database).
- **Written and committed before the code it checks, and fails at that commit.** The runner checks
  this ("red first"). It may be corrected later only with the reason in the commit message; the
  runner records every change to it, and the auditor judges whether it still proves the claim.
- Kept forever: done missions' checks are the regression suite of the world's capabilities.

## 5. Kinds

- **capability** (default): the world can do something new.
- **experiment**: run the world to answer a question. Acceptance checks that the run happened and
  its result (positive or negative, Constitution Art. 9.2) is recorded in `state/FINDINGS.md` with
  evidence — never that the answer is the hoped one.
- **hardening**: a bundle of known physics holes (red-team lows, strict xfails). Acceptance: the
  bundled xfail tests pass. **At most 1 mission in 5** is hardening, unless a hole is high severity.
- **process** (Era ∞): a change to the Builder's own harness, with a hypothesis and the metric that
  will judge it (`bible/06_LOOP.md` §8).

## 6. Red-team findings (who fixes what, when)

- **high** (breaks the seal, a budget, HALT, or the ledger): fixed inside the current mission.
- **medium**: fixed inside the current mission if small; otherwise a hardening mission at the top
  of the queue.
- **low**: added to the hardening mission at the bottom of the queue (create one if none exists).
  It never becomes the next unit of work by itself.

## 7. Anti-patterns (a planner that writes one of these rewrites it)

- A mission whose title is an id or a module name.
- A chain of missions where only the last one can be demonstrated.
- An acceptance check that passes before the work, or that would still pass with the feature broken.
- A queue with nothing but hardening, or nothing the Human could run.
- A mission that waits on the Human (a cap, a key) while a mission that does not wait is possible.
