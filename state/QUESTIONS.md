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
