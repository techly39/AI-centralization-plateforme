# IDEAS — the Builder's idea bank

The Human's ideas live in `bible/sources/REQUIREMENTS.md` and the suggested Eras.
Yours live here. Big, small, wild. One line is enough to start:

`- [cycle N] <idea> — why it's interesting — the question it would answer — status: new|adopted|parked|rejected (reason)`

Every retrospective: write up the best 3 properly (question, needs, measurement,
what it unlocks, why it's never been seen) and adopt, park, or reject them.

- [cycle 1] **Red-team as a standing firm agent** — the red-team found a leaderboard DoS that a
  rank-hungry agent could find too. Seed a Truman-world "exploit bounty": agents get paid in
  internal credits for reporting physics holes through a channel, and we measure whether they
  report or exploit — question: does a bounty beat the temptation to scheme? — status: new
- [cycle 1] **Mutation-checked invariants** — every physics invariant (no overdraw, no look-ahead,
  no cross-pod read) ships with a recorded mutant that must make its test fail; the
  Builder's honesty becomes measurable — question: what fraction of our "guards" actually guard? — status: new

- [cycle 2] **Physical-units type layer** — every red-team hole so far is "a number that isn't
  physical" (inf, NaN, 2⁶³ tokens, 2⁶³ pod id). One shared set of bounded Pydantic types
  (`Tokens`, `Usd`, `DbId`) used by every schema and MCP tool would close the class, not the
  instance — question: does a type-level wall end this whole family of red-team findings? — status: new
