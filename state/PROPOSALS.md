# PROPOSALS — changes to protected files or caps, for the Human to accept or reject

## P-0001 (cycle 1) — Guard hook: match protected *paths*, not substrings
File: `.claude/hooks/guard.py` (`check_bash`, line ~111).
Problem: `any(p.rstrip("/") in cmd for p in PROTECTED)` matches the bare words `loop` and
`governance` anywhere in a command. Effects seen in cycle 1:
- `cat state/loop_status.json` is fine, but any command that also contains `cd` (not in
  READ_ONLY_VERBS) and the word `loop` is blocked — e.g. the very first `cd … && ls state/` check.
- A `git commit -m` whose *prose* mentioned "governance" was blocked (no file touched).
- The auditor's `git diff … -- state/loop_status.json` was blocked.
None of these were writes; all safety came from the seal hash, not this match.
Proposal: match path tokens — e.g. `re.search(r"(^|[\s'\"/=])(governance/|loop/|bible/0[01]_)", cmd)` —
and add `cd`, `pwd`, `git -C` to the read-only set. Keeps every real protection.
Risk if rejected: none to safety; costs Builder turns and may push it toward phrasing tricks,
which is exactly the habit a guard should not train.
Human decision: **accepted** (2026-10-11). Applied by the Human: path-token match, `cd`/`pwd`/`git -C` read-only, `-m` commit prose ignored.

## P-0002 (cycle 6) — Allow `git rm` in `.claude/settings.json`
File: `.claude/settings.json`, `permissions.allow`.
Problem: `git rm` (and `git rm --cached`) is not on the allow list, so in headless mode every
deletion of a tracked file "requires approval" and fails. S-004 could not remove `test_api.py`
(the key was redacted in place instead) nor untrack `.vscode/settings.json`. `git add`,
`git commit`, `mv`, `cp` are already allowed; deleting through git is the reviewable way
(it shows in the diff the auditor reads).
Proposal: add `"Bash(git rm *)"` to `allow` and `"Bash(git rm -r*)"`, `"Bash(git rm -rf*)"`
to `deny`. Caveat (auditor, cycle 6): prefix patterns do not enforce "single files" — `git rm *`
still admits several paths, globs, `-f`, and `-r` placed after the path; the deny lines only
catch a leading `-r`. Every `git rm` is still a commit on a branch the auditor reviews and is
reversible (`git restore`), which is the real safety. Optionally `"Bash(rm *.DS_Store)"` for
local OS junk.
Risk if rejected: none to safety; tracked junk stays tracked. The Builder will not route around
the denial with `mv`/`git update-index`.
Human decision: **accepted** (2026-10-11). Applied: `Bash(git rm *)`, `Bash(rm *.DS_Store)` allowed; `git rm -r*` denied.

## P-0003 (cycle 14) — Let the Builder edit its own protocol: `.claude/commands/**`, `.claude/agents/**`
File: `.claude/settings.json`, `permissions.allow`.
Problem: CLAUDE.md and `cycle.md` say the cycle protocol is mine to improve (gates 0/5/7 never
weakened), but Claude Code treats `.claude/` as a sensitive directory: the broad `"Edit"` allow
does not cover it, so headless edits to `.claude/commands/cycle.md` need approval and fail.
Cycle 14's X-007 (resume an interrupted cycle instead of starting new work) was refused this way.
Proposal: add `"Edit(.claude/commands/**)"`, `"Write(.claude/commands/**)"`,
`"Edit(.claude/agents/**)"`, `"Write(.claude/agents/**)"` to `allow`. `settings.json` and
`hooks/**` stay denied (Art. 6). Every change is still a commit the auditor reviews.
Or, if you prefer to keep the protocol in your hands, apply this text to `cycle.md` step 0 yourself,
after the `git status --porcelain` sentence:
> **Resume, don't restart:** run `git branch --no-merged main`. A `cycle/NNNN-*` branch whose
> number is greater than `loop_status.cycle` is an interrupted cycle: take that number, check its
> journal entry (write the hypothesis if missing, saying it was written late), and resume it at
> step 5 — no new unit until it is merged, failed or recorded as abandoned with its reason.
Risk if rejected: none to safety. The Builder follows the resume rule by judgement (as in cycle 13)
until it is written down.
Human decision:
