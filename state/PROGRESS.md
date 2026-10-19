Cycle 0048 · merged: capital follows results (the multi-manager machine, first slice) · branch: idea/capital-machine
Done this session:
- The red-team's 8 holes (5 medium, 3 low, none high) are all fixed: the whole clock advance holds
  the order lock and the ladder runs before pending orders fill; the ladder sees the worst fall a
  pod lived; a recall takes only the centre's own stake (money the world gave a pod stays in it);
  a pod funded before its seed starts its record honestly; a halved pod is not raised back; a pod
  no longer reads which pod it moves like.
- The auditor blocked twice on copies earning a second seed (two different orders of pitches).
  The cure: the machine runs the correlation gate again as it pays each seed, against every
  mandate the centre ever funded (closed pods too). No order of pitches, nor two at once, gets
  two seeds for one rule. The third pass found no block. A failed sweep is now in the ledger.
- Merged to main; showcase, book and the rules (ADR-049 amended) updated.
Next: Next up 1b, a dead pod is replaced (a plan session first: hire a new PM, a real mind, for
a closed pod; recorded, $0 replays).
Watch out: the red-team's clone test assumed the copy still passed the gate; with the gate fixed
it fails there, so that step now asserts the refusal (stricter). Two older tests seeded two pods
with one rule as a shortcut and now switch off only the copy check, with the reason written in.
Known small holes left in the book: a pod can work out the size of its highest correlation from
its own score; unpriced holdings are valued at cost.
Demo: passes (2 s, $0).
