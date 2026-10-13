# acceptance/ — one executable definition of done per mission

`M-NNN.py` is mission M-NNN's acceptance check (standard: `protocol/MISSIONS.md` §4, ADR-042).

- Run from the repo root: `uv run python acceptance/M-NNN.py`. Exit 0 = the capability works.
- End to end, deterministic, offline (localhost only), no LLM calls, < 15 minutes, cleans up.
- Committed before the code it checks, and failing at that commit ("red first").
- The runner (`loop/`, outside the Builder's reach) runs it after every session that claims a merge,
  records any change to the file, and re-runs every done mission's check before each planning
  session: these files are the regression suite of the world's capabilities.
