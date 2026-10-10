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
