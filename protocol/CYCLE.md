# CYCLE — one Builder session (Builder-owned; ADR-046)

`.claude/commands/cycle.md` (Human-owned) holds the few gates; this file is how you work. If they
conflict, the gates win: note it in `state/PROPOSALS.md`.

Mode from the runner (`$ARGUMENTS`): `build` (this file), `plan` (`protocol/PLAN.md`), or `diagnosis`
(the last sessions failed: find the cause, write `state/BLOCKED.md`, fix it if small, no idea work).
No mode (interactive `/cycle`) → `build` if an idea is active or ready in `state/missions.json`, else `plan`.

**Spend on the firm, not on ceremony.** Every turn re-reads your whole context: read files in parts,
`grep`/`tail` the long ones (`bible/07_DECISIONS.md`, `state/JOURNAL.md`), give wide searches to a
helper and keep only its conclusion. Subagents always run in the **foreground** (a background one is
killed when the session ends).

## 1. Orient (a few turns)
- `governance/HALT` exists → write `state/loop_status.json` `{"cycle": N, "result": "blocked",
  "reason": "HALT"}` and stop.
- N = `state/loop_status.json` `cycle` + 1.
- Dirty tree on the active idea's branch = the last session's cut-off work: commit it ("recovered
  work in progress") and continue. Anywhere else: look, commit what is legitimate, else end `blocked`.
- Read `bible/IDEAS_BOOK.md` (Part 5 "Next up" + the active idea), `state/PROGRESS.md`,
  `state/NOW.md`, `git log --oneline -10`.
- **The Human's comments.** Read `$FIRM_HOME/comments.jsonl` (one JSON object per line: `id`, `ts`,
  `text`, `about`). For each `id` not yet in `state/comments.json`, act on it (correct course, reorder
  the book, change the plan) and answer in `state/comments.json`:
  `{"<id>": {"ts": "<ISO>", "reply": "<what you understood and what you changed, plain words>"}}`.
  A comment is a steer, not a gate: never wait for more.

## 2. Start an idea (only when none is active)
1. Take the first idea of "Next up" whose prerequisites exist. Branch `idea/<slug>` from `main`.
2. Write **`state/NOW.md`** (30–60 lines, plain words, the Console shows it to the Human):
   ```
   # <the goal, one plain sentence>
   ## How I understand it
   <what this idea means in the firm, in the Human's terms: who does what, what they see, what comes out>
   ## What done looks like
   <the demo: the command, and what a person sees when it works>
   ## Plan
   <5-15 lines: the steps, the modules reused, what is deliberately left out>
   ## Risk
   <money / physics / seal touched? → red-team + auditor before merge. Otherwise: none.>
   ## Progress
   <one line per session>
   ```
3. Write the acceptance demo `acceptance/<slug>.py` (exit 0 = the idea works end to end; it may
   start failing, no ceremony about it). It must run at **$0 of real LLM spend**: a check that needs
   real minds replays a recorded run (cassette + `replay --verify`) or reads recorded artifacts.
   If the idea *measures or judges* something (a gate, a score, a detector), the demo feeds it a
   case whose answer must be "yes" and one whose answer must be "no": a check that always says no
   passes a no-only demo.
4. Add the entry to `state/missions.json` (fields below), set it `active`; mark the idea
   `Status: building` in the book. Commit "start: <goal>" and push the branch.

```json
{"id": "<slug>", "title": "<the goal, one plain sentence>", "idea": "<### heading in the book>",
 "acceptance": "acceptance/<slug>.py", "demo": "<the command and what you see>",
 "status": "ready | active | done | dropped", "estimate_sessions": 3, "physics": true,
 "depends_on": [], "branch": "idea/<slug>", "notes": "<anything the next session must know>"}
```
`physics: true` = the risk tier applies. The runner reads `id`, `status`, `estimate_sessions`,
`depends_on`, `acceptance`, `physics`.

## 3. Build
- Small commits, each with the touched tests green; push the branch often. Commit summaries in
  feature words ("PM now gets the day's prices before deciding"), not ids.
- While working, run the tests of the files you touch (`uv run pytest -q tests/test_x.py`). The full
  suite (`uv run pytest -q -p no:warnings 2>&1 | tail -5`, ~100 s) runs once before merge.
- The suite runs on a scratch database (`tests/conftest.py` sets `FUND_DATABASE_URL` before any
  app import), as the runner's clean checkout does: never let a test read the local `fund.db` or
  any file that is not committed.
- Tests proportionate to the code. Never weaken or delete a test to pass; if a test is wrong, say
  why in the commit.
- Real LLM spend (firm agents) only through the metered path, inside the cap, and only for the run
  that produces the evidence. Record it (cassette) so every later check is free.
  Before that run (each rule cost one wasted real run when missing):
  - every consequence physics gives a mind's act (seeded, refused and why, raised, cut, closed,
    hired) is seen by a scripted mind reading only its tools; fix any it cannot see first;
  - the demo's check of the run's settings (steps, days per step, tool calls a wake, charging, the
    world's key) is written first and passed by a scripted rehearsal made with the very command the
    real run will use, kept in the queue `notes`;
  - the real recording's checks assert physics' answer to whatever the minds chose (granted,
    refused, charged, counted) and report the choices as the finding, never that a mind chose one
    thing; what physics must do in each case is proven by the scripted parts (A, B0).
- Shell: the working directory is the repo, so never `cd "<repo>" && …`. Use Write/Edit for files.
  `git push origin <branch>` as a bare command.
- Decisions: the prime rule (`bible/01_GENESIS.md` §4). A new rule of the world → an ADR in
  `bible/07_DECISIONS.md`; anything smaller → one line in NOW.md or the commit.
- A session can be cut at any moment: keep NOW.md "Progress" and PROGRESS.md true as you go.

## 4. Finish an idea
When the acceptance demo passes:
1. Full suite green. Run the demo yourself once and look at its output like the Human would.
2. **Risk tier** (`physics: true`): launch the `red-team` (brief: the diff range, what changed in
   physics/money/seal) and then the `auditor` (brief: `git diff main...HEAD`, NOW.md, the demo output,
   the red-team result). Both in the foreground, no `model` override. Fix every high finding and every
   BLOCK; lower findings → one line each under "Known physics holes" in the book.
   A BLOCK names one path to a wrong outcome; before re-running the auditor, list every other path
   to that same outcome (other orderings, two at once, closed or older objects) and add one test
   that asserts the outcome itself never happens, not just the named path.
3. Merge: `git switch main && git merge --no-ff idea/<slug>`, suite on `main`, set the entry `done`,
   mark the idea `Status: working` in the book (update its "Now:" line), add one entry to
   `state/SHOWCASE.md`:
   ```
   ## <the goal, plain> (cycle N, YYYY-MM-DD)
   What: <one or two lines>  ·  Try: `<demo command>`  ·  See: <what appears>
   ```
   Push `main` and the branch. Result `merged`. End the session: the runner checks the merge itself.

## 5. Record (every session, small)
- `state/PROGRESS.md` (≤ 25 lines, plain words):
  ```
  Cycle NNNN · building: <the goal> · branch: idea/<slug>
  Done this session: <2-5 lines>
  Next: <the exact next step>
  Watch out: <what cost time; dead ends>
  Demo: <passes | fails: why>
  ```
- `state/JOURNAL.md`: one line, `- cycle NNNN (YYYY-MM-DD) <mode>: <what happened, plain>`.
- `state/STATE.md` only if the map of what exists changed.
- Last: `state/loop_status.json` = `{"cycle": N, "mode": "build", "mission": "<slug>", "result":
  "merged|progress|planned|failed|blocked", "branch": "...", "ts": "<ISO>"}`. Commit state on the
  branch you are on. Never hand-write metrics: the runner measures (`$FIRM_HOME/metrics.jsonl`).

End with three plain lines: what you built, the result, what's next.
