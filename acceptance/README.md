# acceptance/ — one executable demo per idea

`<slug>.py` proves that one idea of `bible/IDEAS_BOOK.md` works end to end (`protocol/CYCLE.md` §2,
ADR-046). `M-NNN.py` are the checks of the first two missions (ADR-042), kept as regression checks.

- Run from the repo root: `uv run python acceptance/<slug>.py`. Exit 0 = the idea works.
- End to end, deterministic, offline (localhost only), **$0 of real LLM spend** (a check about real
  minds replays their recorded run), < 15 minutes, cleans up after itself.
- The runner (`loop/`, outside the Builder's reach) runs it after every session that claims a merge,
  records any change to the file, and re-runs every finished idea's check before each planning
  session: these files are the regression suite of what the world can do.
