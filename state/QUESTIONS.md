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
Update (cycle 6): **redacted, not removed.** `git rm` needs approval in headless mode (P-0002),
so the key line was replaced in place: `test_api.py` now reads `FUND_API_KEY` from the
environment (unset → it sends an empty key and gets 401). The key is gone from `main`'s tree,
still in history (commit before 897be4b), and **still live** in `fund.db` — B/C remain yours.
Human answer:

## Q-0004 (cycle 7) — An xAI key in a plain file in your OpenClaw workspace
Context: `~/.openclaw/workspace/OPENCLAW_XAI_KEY.txt` holds a string shaped like an xAI API key
(found by name + pattern; the Builder never printed it). It sits in `main`'s workspace, which
also contains the three OCT workspaces, so any of your agents with `read`/`exec` can read it —
and `main` has web tools and a Telegram binding. Your `auth-profiles.json` already holds an xAI
key for `main`/`rachel`, so the file may be a leftover.
Options: A leave it / B delete or move it outside `~/.openclaw/workspace` (and rotate the key if
it was ever exposed).
Chosen: nothing — it is your OpenClaw (08 §2, hands off). Recommended: B. A copy is also in
the backup `~/firm-openclaw-backups/20261011T0129Z-cycle0007.tar.gz`.
**Also yours, one command:** that backup holds all of `~/.openclaw` (config, auth profiles,
credentials) and was created mode 644 in a 755 dir; your home is 750, so only your group
(`staff`) can reach it. The Builder's `chmod 600` needs approval headless — please run
`chmod 700 ~/firm-openclaw-backups && chmod 600 ~/firm-openclaw-backups/*.tar.gz`.
Future backups: created under `umask 077` (B-012 backup step).
Reversible: yes.
Human answer:
