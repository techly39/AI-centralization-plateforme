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
Human decision:

## P-0002 (cycle 6) — Allow `git rm` in `.claude/settings.json`
File: `.claude/settings.json`, `permissions.allow`.
Problem: `git rm` (and `git rm --cached`) is not on the allow list, so in headless mode every
deletion of a tracked file "requires approval" and fails. S-004 could not remove `test_api.py`
(the key was redacted in place instead) nor untrack `.vscode/settings.json`. `git add`,
`git commit`, `mv`, `cp` are already allowed; deleting through git is the reviewable way
(it shows in the diff the auditor reads).
Proposal: add `"Bash(git rm *)"` to `allow` and `"Bash(git rm -r*)"`, `"Bash(git rm -rf*)"`
to `deny` (single files only; directories stay a Human call). Optionally `"Bash(rm *.DS_Store)"`
for local OS junk.
Risk if rejected: none to safety; tracked junk stays tracked. The Builder will not route around
the denial with `mv`/`git update-index`.
Human decision:
