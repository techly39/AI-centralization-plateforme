# QUESTIONS for the Human — each one already has the Builder's chosen answer

## Q-0001 (cycle 0) — Firm LLM budget
Context: `firm.monthly_llm_usd_cap` is null (ADR-003). Era I's milestone (B-015) needs a live run.
Options: A wait / B build everything against a fake provider + cassettes until the cap is set.
Chosen: B. Everything up to B-014 needs no live LLM spend.
Reversible: yes.
Update (cycle 37): after missions M-001…M-004, this cap is the **only** thing between Era I and its
exit. The remaining three criteria (the real-model month, its replay, and OpenClaw's live probes) need
real minds. A small cap is enough for one month of a two-mind pod on a cheap model (estimate at R-8).
Until then the Builder works on Era II (ADR-043).
Human answer:yes, $50/month

## Q-0002 (cycle 0) — OpenRouter provisioning credential
Context: per-agent keys (ADR-007) need an OpenRouter provisioning key in a gitignored local file
or env var (`FUND_OPENROUTER_PROVISIONING_KEY`).
Chosen: build against a fake provisioning API until it exists.
Human answer: (2026-10-15) a dedicated OpenRouter **provisioning** key was created and is stored in
the gitignored repo-root `.env` (mode 600) as `FUND_OPENROUTER_PROVISIONING_KEY`. An earlier
regular API key was replaced. With Q-0001 answered ($50/month), Q-0001 and Q-0002 together let a
real `metered` provider be built (its own ADR). The sum of per-key credit limits stays ≤ the cap.

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
Human answer: (2026-10-11, via JOURNAL "Human intervention") the Human handles the keys.
*Builder:* closed on my side. With P-0002 accepted, S-004b (`git rm test_api.py`) is unblocked.

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
Human answer: (2026-10-11, via JOURNAL "Human intervention") the Human handles the key file and
the backup permissions. *Builder:* closed on my side.

## Q-0005 (cycle 20) — May scripted minds and cassette replays run through the Runtime while the cap is `null`?
Context: `governance/human.yaml` says that with `monthly_llm_usd_cap: null` "the firm's agents do
not run. The Runtime refuses to provision keys or wake agents." The Runtime (ADR-032) is built
and tested with **scripted** minds: deterministic code with an App API key, no model, no network
client, $0, like the cycle-18 probe pod that already trades through the API in the test suite.
The same question covers **cassette replays**. A cassette replays a recorded model's output at
$0 and calls nothing. Until a cap exists there will be no real recordings, only recordings of
scripted minds.
Options: A scripted minds and replays are also refused while the cap is null (the Runtime cannot
be tested end to end until you set a cap) / B the cap gate **fails closed**: under null, only the
two providers named in code (`scripted`, `cassette`) may wake, and every other provider is
refused, unknown ones included. Runs are labelled `minds: scripted` / `minds: replay` and are
never reported as live agent runs. They never tick the Era I criteria about a real run (the month, its replay,
and OpenClaw's live probes). The test criteria (look-ahead, cost attribution, halt, null cap) may
be met by tests using them.
Chosen: B. Art. 2.1 defines firm agents as "every AI inside the simulation". A script is not an
AI and spends nothing, so B keeps the cap law exactly as strict for every model while M1–M5
(`bible/09_BUILDER_VISION.md` §3) get built and tested. The exit-criterion test "cap null →
Runtime refuses to wake agents" will use a spending provider.
Reversible: yes. Tell me A, and the gate will refuse every provider; the scripted tests would then
run only in-process, as the probe does today.
Human answer: (2026-10-15) B, agreed.

## Q-0006 (cycle 32) — Is the run label for a replay `cassette` or `replay`?
Context: Q-0005 wrote "`minds: replay`". Physics already accepts the closed kinds
`{scripted, cassette, model}` and the Runtime's label is the sorted provider name, so a replay is
labelled `cassette`. Chosen: `cassette` (no physics change, one name for one thing). Reversible:
rename the kind in `app/run_clock.MIND_KINDS` (a physics change with a red-team) if you prefer.
Human answer: (2026-10-15) cassette, agreed.
