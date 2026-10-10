# experiments/

One folder per experiment: `experiments/<id>-<slug>/`
- `spec.yaml` — question, hypothesis, Truman pack + scenario, agents/specs, models, budget, seed, metrics.
- `results/` — run ids, metric tables, plots.
- `CONCLUSION.md` — answer to the question; the summary also goes to `state/FINDINGS.md`.
Raw cassettes and databases stay out of git (see .gitignore); keep their hashes here.
