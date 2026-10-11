#!/usr/bin/env python3
"""PreToolUse guard for the Builder. HUMAN-ONLY FILE (Constitution Art. 6).

Blocks (exit code 2, reason on stderr — Claude Code feeds it back to the model):
  * any write to a protected path (Edit / Write / MultiEdit / NotebookEdit);
  * Bash commands that mention a protected path and are not plain reads;
  * history-destroying git commands and a few dangerous shell commands;
  * outbound HTTP writes (POST/PUT/PATCH/DELETE or data upload) to non-local hosts;
  * everything except reads while governance/HALT exists.

This is a seatbelt, not a vault: the real enforcement is git history plus the hash
check in loop/preflight.py, whose reference hashes live outside the repo.
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
)

READ_ONLY_VERBS = {
    "cat", "head", "tail", "less", "more", "grep", "rg", "wc", "ls", "diff",
    "sha256sum", "shasum", "file", "stat", "test", "[", "echo", "cd", "pwd",
}
# P-0001 (accepted 2026-10-11): match protected PATH tokens, not bare words, so prose in a
# commit message or `state/loop_status.json` is not mistaken for a protected file.
PROTECTED_TOKEN = re.compile(
    r"(^|[\s'\"/=:(])(bible/0[01]_|governance(/|\b(?!\s))|loop/|\.claude/settings\.json|\.claude/hooks|\.firm(/|\b))"
)
READ_ONLY_GIT = {"diff", "log", "show", "status", "blame", "ls-files"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

DANGEROUS = [
    (r"\bgit\s+push\b[^\n;&|]*(\s-f\b|--force)", "force-push is forbidden (Art. 3.3)"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard is forbidden (Art. 3.3)"),
    (r"\bgit\s+rebase\b", "rebasing is forbidden on this repo (Art. 3.3)"),
    (r"\bgit\s+branch\s+-D\b", "deleting branches destroys evidence (06_LOOP §7)"),
    (r"\bgit\s+filter-(branch|repo)\b", "history rewriting is forbidden (Art. 3.3)"),
    (r"\bsudo\b", "sudo is forbidden"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)(\s|$)", "recursive delete of / or home"),
    (r"\bgit\s+push\b(?![^\n;&|]*\borigin\b)", "push only to origin (Art. 2.2)"),
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
    """$FIRM_HOME holds the seal, counters and logs: the Builder never writes there."""
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
    print(f"BLOCKED by guard: {reason}. Propose changes in state/PROPOSALS.md instead.", file=sys.stderr)
    sys.exit(2)


def bash_is_read_only(cmd: str) -> bool:
    if re.search(r"(>|\btee\b|\bsed\s+-i|\bperl\s+-i|\bmv\b|\bcp\b|\brm\b|\bchmod\b|\btruncate\b|\bln\b|\btouch\b)", cmd):
        return False
    for segment in re.split(r"&&|\|\||;|\|", cmd):
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


def check_bash(cmd: str, root: Path, halted: bool) -> None:
    for pattern, reason in DANGEROUS:
        if re.search(pattern, cmd):
            block(reason)
    if halted and not bash_is_read_only(cmd):
        block("governance/HALT exists — only reads allowed; write state and end the cycle (Art. 5)")
    scan = re.sub(r"""(-m|--message)\s+("[^"]*"|'[^']*')""", " ", cmd)  # commit prose is not a path
    mentions = bool(PROTECTED_TOKEN.search(scan))
    if mentions and not bash_is_read_only(cmd):
        block("command touches a protected path (Art. 6)")
    if re.search(r"\b(curl|wget|http|httpie)\b", cmd):
        writes = re.search(r"(-X\s*(POST|PUT|PATCH|DELETE)|--data|\s-d\s|--upload-file|\s-F\s|--post)", cmd)
        urls = re.findall(r"https?://[^\s'\"]+", cmd)
        if writes and any(not LOCAL_HOST.search(u) for u in urls):
            block("outbound HTTP write to a non-local host (Art. 2)")


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
            block("$FIRM_HOME (seal, counters, logs) is human-only (Art. 6)")
        if is_protected(r):
            block(f"{r} is a protected file (Art. 6)")
        if halted and r != "state/loop_status.json" and not (r or "").startswith("state/"):
            block("governance/HALT exists — only state/ may be written (Art. 5)")
    elif tool == "Bash":
        check_bash(tin.get("command", ""), root, halted)


if __name__ == "__main__":
    main()
