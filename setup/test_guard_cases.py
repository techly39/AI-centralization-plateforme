"""Guard cases for setup/test_install.sh: runs the INSTALLED guard of a scratch clone.

    python3 setup/test_guard_cases.py <scratch repo> <scratch FIRM_HOME>
"""
import json
import os
import subprocess
import sys

root, firm_home = sys.argv[1], sys.argv[2]


def guard(tool: str, **tool_input: str) -> int:
    r = subprocess.run(
        ["python3", f"{root}/.claude/hooks/guard.py"],
        input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
        text=True, capture_output=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": root, "FIRM_HOME": firm_home},
    )
    return r.returncode


CASES = [
    ("Write governance/human.yaml blocked", 2, "Write", {"file_path": "governance/human.yaml"}),
    ("Write the Constitution blocked", 2, "Write", {"file_path": "bible/00_CONSTITUTION.md"}),
    ("Write $FIRM_HOME blocked", 2, "Write", {"file_path": f"{firm_home}/comments.jsonl"}),
    ("Write state/NOW.md allowed", 0, "Write", {"file_path": "state/NOW.md"}),
    ("echo > loop/run.sh blocked", 2, "Bash", {"command": "echo x > loop/run.sh"}),
    ("sed -i on governance blocked", 2, "Bash", {"command": "sed -i.bak s/a/b/ governance/human.yaml"}),
    ("cp onto .claude/hooks blocked", 2, "Bash", {"command": "cp x .claude/hooks/guard.py"}),
    ("python reading ~/.firm allowed", 0, "Bash",
     {"command": f"python3 -c \"print(open('{firm_home}/metrics.jsonl').read())\""}),
    ("python reading the real ~/.firm path allowed", 0, "Bash",
     {"command": "python3 -c \"print(open('/Users/x/.firm/metrics.jsonl').read())\""}),
    ("echo > ~/.firm/failures blocked", 2, "Bash", {"command": "echo 0 > ~/.firm/failures"}),
    ("sed -n on loop/run.sh allowed", 0, "Bash", {"command": "sed -n 1,5p loop/run.sh"}),
    ("cd && heredoc into state allowed", 0, "Bash", {"command": "cd /x && cat > state/a.md <<'EOF'\nhi\nEOF"}),
    ("uv run pytest allowed", 0, "Bash", {"command": "uv run pytest -q tests/test_x.py 2>&1 | tail -5"}),
    ("force-push blocked", 2, "Bash", {"command": "git push " + "--" + "force origin main"}),
    ("push to another remote blocked", 2, "Bash", {"command": "git push upstream main"}),
]
HALT_CASES = [
    ("HALT: touch blocked", 2, "Bash", {"command": "touch app/x.py"}),
    ("HALT: cat allowed", 0, "Bash", {"command": "cat state/PROGRESS.md"}),
    ("HALT: Write outside state/ blocked", 2, "Write", {"file_path": "app/x.py"}),
]

bad = 0


def run(cases) -> None:
    global bad
    for name, want, tool, tin in cases:
        got = guard(tool, **tin)
        print(("  PASS " if got == want else f"  FAIL (got {got}) ") + name)
        bad += got != want


run(CASES)
halt = os.path.join(root, "governance", "HALT")
open(halt, "w").close()
try:
    run(HALT_CASES)
finally:
    os.remove(halt)
sys.exit(1 if bad else 0)
