# protocol/ — the Builder's own process (Builder-owned)

Claude Code protects the `.claude/` folder, so in unattended mode the Builder cannot edit files
there. Everything about *how the Builder works* that it should be able to improve lives here instead:

| File | What |
|---|---|
| `MISSIONS.md` | The mission standard: how work is written (ADR-042). Read by planners and the architect. |
| `CYCLE.md` | A build session (and what every session shares). `.claude/commands/cycle.md` points here + holds the gates. |
| `PLAN.md` | A planning session: measure, look outward, ideate, write the mission queue, improve the factory. |
| `agents/auditor-extra.md`, `agents/red-team-extra.md`, `agents/architect-extra.md` | Extra checks/guidance the sealed team roles also apply (additions only). |
| `agents/<new-role>.md` | New helper roles you invent. Launch them with a general-purpose subagent: "Read `protocol/agents/<role>.md` and act as that role." |
| `skills/<name>.md` | Reusable procedures (checklists, recipes). Reference them from `CYCLE.md` or `PLAN.md`. |

Every change here is an Era ∞ change made in a planning session: hypothesis, metric (the runner's,
`$FIRM_HOME/metrics.jsonl`), auditor review (`bible/06_LOOP.md` §8).
