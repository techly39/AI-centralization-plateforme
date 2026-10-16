# setup/ — installer for the Human-only files (HUMAN-RUN)

The Builder may not write protected files (Constitution §10), so their new versions are staged here
and installed by the Human. Current staging: **Builder v3** (ADR-046), on branch `builder-v3`.

| Path | Installed as |
|---|---|
| `files/bible_dir/00_CONSTITUTION.md`, `01_GENESIS.md` | `bible/` (short rulebook, new decision rule) |
| `files/claude_dir/commands/cycle.md` | `.claude/commands/cycle.md` (the few gates) |
| `files/claude_dir/agents/*.md` | `.claude/agents/` (auditor, red-team, worker; architect and validator removed) |
| `files/claude_dir/hooks/guard.py`, `stop_gate.py` | `.claude/hooks/` (guard blocks only writes to protected paths) |
| `files/claude_dir/settings.json` | `.claude/settings.json` (Bash allowed; deny list kept) |
| `files/loop_dir/run.sh`, `builder.sh`, `preflight.py` | `loop/` (v3 team, `idea/*` branches, subagents not killed) |
| `files/governance_dir/human.yaml` | `governance/human.yaml` (opus leads, cap $50 unchanged, pitches don't wait, OpenRouter reachable for metered runs) |

```bash
bash setup/install.sh          # with no Builder run going, from a clean tree
loop/builder.sh start          # the first session starts the first idea of the book
bash setup/rollback.sh ~/.firm/backups/install-<time>   # undo
bash setup/test_install.sh     # what was tested before this was offered (scratch clone, stub claude)
```
