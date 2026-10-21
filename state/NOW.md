# A PM builds its own team: it hires an analyst it describes, paid from its pod's thinking budget, and the analyst's research and cost count as the pod's

## How I understand it
Today every mind in the firm is a PM, and every decision about people is a law: who is hired,
with what model, with what charter. The Human's pod is a PM *with a small team it builds and pays
for*. This first slice lets a PM create one kind of teammate, an analyst:
- **The request.** A PM asks for an analyst: what it should do (a charter in the PM's words), a
  model from the firm's pool, and a thinking budget.
- **Physics decides.** The pod's team limit, the Human's agent cap and the pod's team budget
  (its analysts' keys together; the PM's own key stays the hiring law's, and every dollar of both
  is the pod's fitness) grant it or refuse it by name.
- **The hire.** A granted request opens a place in the PM's living pod; the Runtime fills it the
  next morning (the same Onboarding as a PM hire), with a key carved from the pod's budget.
- **The analyst works.** It researches rules (its backtests are the pod's attempts, so the gates'
  deflated Sharpe counts them at the PM's next pitch), reads the library and messages its PM. It
  cannot pitch, trade or hire.
- **It costs the pod.** Its thinking lowers the pod's fitness and capital score. The PM can let it
  go; when the PM is let go or the pod closes, the analyst stops too.
Whether real PMs choose to hire, and whether a team pays for itself, is the finding.

## What done looks like
`uv run python acceptance/pm_builds_team.py` ($0, offline):
- A (scripted): a PM's first request is granted and its analyst wakes the next morning; requests
  past the team limit, the pod's budget or the agent cap are refused by name; the analyst is
  refused when it pitches or trades; its backtests raise the pod's count of attempts; its thinking
  lowers the pod's fitness; let go, it stops waking; a flood of messages cannot drain the PM's key;
  law off → nothing changes; rebuild from the ledger gives the same books.
- B0: the same through the Runtime, replay IDENTICAL.
- B (recorded, real Haiku PMs offered a team): physics' answers to whatever they chose are
  checked; IDENTICAL for $0; the report shows each pod's team and what it cost.

## Plan
1. A `team:` law (off by default, so every older recording replays as it was): analysts per pod,
   the pod's thinking budget, the models allowed.
2. The request: a PM-only endpoint + MCP tool; physics names the hire in a vacancy of role analyst
   into the PM's living pod; refusals logged.
3. Onboarding reused for the analyst; its key carved from the pod's budget, under the cap.
4. Permissions: an analyst researches, reads, messages; never pitches, orders or hires.
5. Attempts and cost: check the pod (not the agent) is what both are counted on.
6. Letting go: by its PM; with its PM; with its pod.
7. Holes fixed inside: a message flood draining a metered key; a registration restaffing an empty
   pod past the live-pod limit.
8. Demo A, B0 rehearsal with the real run's very command, the real run, red-team, auditor, merge.
Left out: engineers, a PM choosing its analyst's tools, a manager mind, the team as an inherited gene.

## Risk
Agents created by an agent, keys and budgets, the cap, permissions: red-team + auditor before merge.

## Progress
- cycle 63: planned.
- cycle 64: physics built (the law, request, fill, letting go, the team following its PM
  and its pod out, the two holes fixed); demo part A passes in full; next: the Runtime hires
  team places each morning (B0), then the real run (B).
