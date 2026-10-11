# QUESTIONS for the Human — each one already has the Builder's chosen answer

## Q-0001 (cycle 0) — Firm LLM budget
Context: `firm.monthly_llm_usd_cap` is null (ADR-003). Era I's milestone (B-015) needs a live run.
Options: A wait / B build everything against a fake provider + cassettes until the cap is set.
Chosen: B. Everything up to B-014 needs no live LLM spend.
Reversible: yes.
Human answer:

## Q-0002 (cycle 0) — OpenRouter provisioning credential
Context: per-agent keys (ADR-007) need an OpenRouter provisioning key in a gitignored local file
or env var (`FUND_OPENROUTER_PROVISIONING_KEY`).
Chosen: build against a fake provisioning API until it exists.
Human answer:

## Q-0003 (cycle 5) — The management key committed in `test_api.py`
Context: `test_api.py:10` holds the live API key of agent `id=1 'management'` in your local
`fund.db` (SHA-256 match, SURVEY §4b.1); it is pushed to origin. Fake money, local DB,
127.0.0.1 server — small blast radius, but the key stays in git history (no force-push).
Options: A remove the file from `main` (S-004) and leave the key live / B also revoke it —
needs a write to `fund.db`, which the Builder never does on its own / C rotate the key via
`fund-env` yourself.
Chosen: A now (S-004). B/C are yours: the Builder does not write your August database.
Also worth checking yourself: whether origin is public (`gh repo view`).
Reversible: yes.
Human answer:
