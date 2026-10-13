# setup/ — Builder v2 installer (HUMAN-RUN, ADR-042)

The Builder may not write protected files (Constitution Art. 6), so changes to them are staged here and
installed by the Human.

| Path | Installed as |
|---|---|
| `files/claude_dir/commands/cycle.md` | `.claude/commands/cycle.md` (the gates) |
| `files/claude_dir/agents/*.md` | `.claude/agents/` (architect, auditor, red-team, **validator**, **worker**) |
| `files/claude_dir/hooks/guard.py`, `stop_gate.py` | `.claude/hooks/` (guard fix + the Stop hook) |
| `files/claude_dir/settings.json` | `.claude/settings.json` (+ Stop hook) |
| `files/loop_dir/run.sh`, `builder.sh`, `preflight.py` | `loop/` (session modes, referee, metrics, usage-limit wait) |
| `files/governance_dir/human.yaml` | `governance/human.yaml` (new team roles, no USD caps, sandbox) |

```bash
bash setup/install.sh          # from branch builder-v2, with no Builder run going
loop/builder.sh start          # first session = planning (the re-foundation)
bash setup/rollback.sh ~/.firm/backups/install-<time>   # undo
```

Tested in a scratch clone with a stub `claude` (install, plan → build, referee, false-done, usage limit)
before it was offered to the Human.
