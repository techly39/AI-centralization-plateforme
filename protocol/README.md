# protocol/ — the Builder's own process (Builder-owned)

Claude Code protects `.claude/`, so the parts of the process the Builder must be able to improve live here.

| File | What |
|---|---|
| `CYCLE.md` | A build session: orient, start an idea, build, finish, record. `.claude/commands/cycle.md` points here and holds the gates. |
| `PLAN.md` | A planning session: look back, update the ideas book, queue the next idea, one process improvement. |
| `agents/auditor-extra.md`, `agents/red-team-extra.md` | Extra checks the sealed review roles also apply (additions only). |
| `agents/<new-role>.md` | New helper roles. Launch with a general-purpose subagent: "Read `protocol/agents/<role>.md` and act as that role." |
| `skills/<name>.md` | Reusable procedures, referenced from `CYCLE.md` or `PLAN.md`. |

The goal source is `bible/IDEAS_BOOK.md`. Change this folder when the numbers in
`$FIRM_HOME/metrics.jsonl` say the process is slow or wrong; say what you expect to improve.
