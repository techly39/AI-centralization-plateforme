# protocol/ — the Builder's own process (Builder-owned)

Claude Code protects the `.claude/` folder, so in unattended mode the Builder cannot edit files
there. Everything about *how the Builder works* that it should be able to improve lives here instead:

| File | What |
|---|---|
| `CYCLE.md` | The full cycle protocol. `.claude/commands/cycle.md` points here + holds the 3 human gates. |
| `agents/auditor-extra.md`, `agents/red-team-extra.md`, `agents/architect-extra.md` | Extra checks/guidance the three sealed team roles also apply (additions only). |
| `agents/<new-role>.md` | New helper roles you invent. Launch them with a general-purpose subagent: "Read `protocol/agents/<role>.md` and act as that role." |
| `skills/<name>.md` | Reusable procedures (checklists, recipes). Reference them from `CYCLE.md`. |

Every change here is an Era ∞ cycle: hypothesis, metric, auditor review (bible/06_LOOP.md §8).
