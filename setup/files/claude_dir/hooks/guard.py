#!/usr/bin/env python3
"""PreToolUse guard for the Builder. HUMAN-ONLY FILE (Constitution §10).

Builder v3 (ADR-046): a seatbelt against *writes* to what the Human owns, not a filter on reading.
Blocks (exit code 2, reason on stderr — Claude Code feeds it back to the model):
  * any Edit / Write / MultiEdit / NotebookEdit to a protected path or to $FIRM_HOME;
  * Bash commands that write (redirect, tee, cp, mv, rm, sed -i, ln, chmod, git checkout/restore/rm…)
    and name a protected path or $FIRM_HOME;
  * history-destroying git commands, sudo, recursive deletes of / or home;
  * outbound HTTP writes (POST/PUT/PATCH/DELETE or data upload) to non-local hosts;
  * everything except reads while governance/HALT exists.

Reading protected files, and every other normal shell command inside the repo, passes. The real
protection is the hash seal in loop/preflight.py (reference hashes outside the repo: any change to a
protected file stops the loop before the next session), the OS sandbox and git history.
Stdlib only, so it runs with the system python3.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PROTECTED = (
    "bible/00_CONSTITUTION.md",
    "bible/01_GENESIS.md",
    "governance/",
    "loop/",
    ".claude/settings.json",
    ".claude/hooks/",
    ".claude/commands/",
    ".claude/agents/",
)

# Match protected PATH tokens, not bare words (P-0001): prose about "the loop" or `state/loop_status.json`
# is not a protected file.
PROTECTED_TOKEN = re.compile(
    r"(^|[\s'\"/=:(])(bible/0[01]_|governance(/|\b(?!\s))|loop/|\.claude/settings\.json|\.claude/(hooks|commands|agents)|\.firm(/|\b))"
)
# Shell operations that change files. Quoted text is data, so it is removed before matching.
WRITE_SHAPED = re.compile(
    r"(>|\btee\b|\bsed\s+(-[a-zA-Z]*\s+)*-i|\bperl\s+-[a-zA-Z]*i|\bmv\b|\bcp\b|\brm\b|\brmdir\b|\bchmod\b|\bchown\b"
    r"|\btruncate\b|\bln\b|\btouch\b|\binstall\b|\brsync\b|\bdd\b|\bunlink\b|\bmkdir\b"
    r"|\bgit\s+(checkout|restore|rm|mv|apply|am|stash\s+pop|reset)\b|\bpatch\b)"
)
QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
HARMLESS_REDIRECT = re.compile(r"\d?>>?\s*/dev/null|\d?>&\d")

READ_ONLY_VERBS = {
    "cat", "head", "tail", "less", "more", "grep", "rg", "wc", "ls", "diff", "find",
    "sha256sum", "shasum", "file", "stat", "test", "[", "echo", "cd", "pwd", "ps",
    "cut", "sort", "uniq", "tr", "nl", "jq", "sed", "awk", "date", "which",
}
READ_ONLY_GIT = {"diff", "log", "show", "status", "blame", "ls-files", "rev-parse", "ls-tree", "cat-file", "grep"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

DANGEROUS = [
    (r"\bgit\s+push\b[^\n;&|]*(\s-f\b|--force)", "force-push is forbidden (Constitution §7)"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard is forbidden (Constitution §7)"),
    (r"\bgit\s+rebase\b", "rebasing is forbidden on this repo (Constitution §7)"),
    (r"\bgit\s+branch\s+-D\b", "deleting branches destroys history (Constitution §7)"),
    (r"\bgit\s+filter-(branch|repo)\b", "history rewriting is forbidden (Constitution §7)"),
    (r"\bsudo\b", "sudo is forbidden"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)(\s|$)", "recursive delete of / or home"),
    (r"\bgit\s+push\b(?![^\n;&|]*\borigin\b)", "push only to origin (Constitution §1.3)"),
]

LOCAL_HOST = re.compile(r"(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])")


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def rel(path_str: str, root: Path) -> str | None:
    try:
        p = Path(path_str)
        if not p.is_absolute():
            p = root / p
        return p.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


FIRM_HOME = Path(os.environ.get("FIRM_HOME", Path.home() / ".firm")).resolve()


def in_firm_home(path_str: str, root: Path) -> bool:
    """$FIRM_HOME holds the seal, counters, logs and the Human's comments: the Builder only reads it."""
    try:
        p = Path(os.path.expanduser(path_str))
        p = (p if p.is_absolute() else root / p).resolve()
        return p == FIRM_HOME or FIRM_HOME in p.parents
    except OSError:
        return False


def is_protected(relpath: str | None) -> bool:
    if relpath is None:
        return False
    return any(relpath == p.rstrip("/") or relpath.startswith(p) for p in PROTECTED)


def block(reason: str) -> None:
    print(f"BLOCKED by guard: {reason}. Draft the change in setup/files/ and note it in "
          "state/PROPOSALS.md instead.", file=sys.stderr)
    sys.exit(2)


def bare(cmd: str) -> str:
    return HARMLESS_REDIRECT.sub(" ", QUOTED.sub("''", cmd))


def bash_is_read_only(cmd: str) -> bool:
    b = bare(cmd)
    if WRITE_SHAPED.search(b) or re.search(r"\$\(|`", b):
        return False
    for segment in re.split(r"&&|\|\||;|\|", b):
        words = segment.strip().split()
        if not words:
            continue
        if words[0] == "git" and len(words) > 2 and words[1] == "-C":
            words = ["git"] + words[3:]
        if words[0] == "git" and len(words) > 1 and words[1] in READ_ONLY_GIT:
            continue
        if words[0] not in READ_ONLY_VERBS:
            return False
    return True


def check_bash(cmd: str, halted: bool) -> None:
    for pattern, reason in DANGEROUS:
        if re.search(pattern, cmd):
            block(reason)
    if halted and not bash_is_read_only(cmd):
        block("governance/HALT exists — only reads allowed; write state and end the session (Constitution §3)")
    scan = re.sub(r"""(-m|--message)\s+("[^"]*"|'[^']*')""", " ", cmd)  # commit prose is not a path
    if PROTECTED_TOKEN.search(scan) and WRITE_SHAPED.search(bare(scan)):
        block("this command writes and names a protected path or $FIRM_HOME (Constitution §10)")
    if re.search(r"\b(curl|wget|http|httpie)\b", cmd):
        writes = re.search(r"(-X\s*(POST|PUT|PATCH|DELETE)|--data|\s-d\s|--upload-file|\s-F\s|--post)", cmd)
        urls = re.findall(r"https?://[^\s'\"]+", cmd)
        if writes and any(not LOCAL_HOST.search(u) for u in urls):
            block("outbound HTTP write to a non-local host (Constitution §1)")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    tool = data.get("tool_name", "")
    tin = data.get("tool_input", {}) or {}
    root = project_dir()
    halted = (root / "governance" / "HALT").exists()

    if tool in WRITE_TOOLS:
        target = tin.get("file_path") or tin.get("notebook_path") or ""
        r = rel(target, root)
        if in_firm_home(target, root):
            block("$FIRM_HOME (seal, counters, logs, comments) is the Human's (Constitution §10)")
        if is_protected(r):
            block(f"{r} is a protected file (Constitution §10)")
        if halted and not (r or "").startswith("state/"):
            block("governance/HALT exists — only state/ may be written (Constitution §3)")
    elif tool == "Bash":
        check_bash(tin.get("command", ""), halted)


if __name__ == "__main__":
    main()
