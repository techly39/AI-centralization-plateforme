# OpenClaw — version notes (`bible/08_OPENCLAW.md` §1, rule zero)

**Installed:** `OpenClaw 2026.5.12 (f066dd2)` — measured cycle 7 (2026-10-11).
**Adapter verified against:** none yet (no adapter exists; B-012). Pin the version here when it does.
**Evidence:** `uv run python scripts/survey_probe_openclaw.py` (read-only, never prints a secret).
**Backup before any change:** `~/firm-openclaw-backups/20261011T0129Z-cycle0007.tar.gz`
(whole `~/.openclaw`, 35.8 MB, 4 107 entries = 4 107 on disk; excludes nothing).

## The first rule of this file: the docs are not this version

`docs.openclaw.ai` serves the **latest** docs (pages mention upgrading "through 2026.9.5"), not
2026.5.12's. The two disagree on things that matter to the seal:

| Thing | Live docs (≥ 2026.9) | Installed 2026.5.12 (`openclaw config schema`) |
|---|---|---|
| Agent roster key | `agents.entries` | `agents.list` (`agents.*` = `defaults`, `list`) |
| `tools.sessions.visibility` default | `all` — every session on the Gateway, incl. other agents' | `tree` (current session + its spawned subagents) |
| `tools.agentToAgent.enabled` default | `true` ("cross-agent access is on by default") | not stated; description says "keep off" |

So an upgrade can silently **widen** what an agent can read. Consequence for the adapter:
never rely on a default — render every seal-relevant key explicitly, and treat the installed
CLI's own schema (`openclaw config schema`) as the source of truth, docs second.

## Config keys the adapter will rely on (2026.5.12 schema)

- Per agent, `agents.list[]` (31 keys): `id`, `name`, `workspace`, `agentDir`, `model`, `models`,
  `identity`, `tools`, `sandbox`, `subagents`, `skills`, `heartbeat`, `systemPromptOverride`, …
- `agents.list[].tools`: `allow`, `alsoAllow`, `deny`, `profile`, `byProvider`, `exec`, `fs`,
  `elevated`, `message`, `sandbox`, `toolsBySender`, `loopDetection`.
  Docs (precedence page): profile → global allow/deny → agent allow/deny → sandbox → subagent;
  each layer only restricts, **deny wins**, a later layer can't grant back.
  <https://docs.openclaw.ai/tools/multi-agent-sandbox-tools>
- `agents.list[].sandbox`: `mode` ∈ {`off`, `non-main`, `all`}; `workspaceAccess` ∈ {`none`,
  `ro`, `rw`}; `scope` ∈ {`session`, `agent`, `shared`}; `docker.*` (network, readOnlyRoot, …).
  Docs warn `workspaceAccess: ro/none` does **not** stop `exec` from writing — deny `exec` too.
- `agents.list[].subagents.allowAgents` — spawn targets; default "same agent only".
- **MCP is global only:** `mcp.servers.<name>` = {`command`, `args`, `env`, `cwd`, `url`,
  `transport`, `headers`}. There is **no per-agent `mcp` key.** Tools are named
  `<server>__<tool>` and filterable by glob (`fund_x__*`). So "one `fund-env-mcp` per agent key"
  = one *named server per agent* in the global list, and each agent's allowlist admits only its
  own server's glob. The key goes in that server's `env` (config, not workspace) — prefer a
  SecretRef (`openclaw secrets`, `config set … --ref-source env`) over a literal.
- Global-only seal keys (not per agent): `tools.sessions.visibility` ∈ {`self`,`tree`,`agent`,`all`},
  `tools.agentToAgent` {`enabled`, `allow`}, `tools.web.*`, `tools.profile`
  ∈ {`minimal`,`coding`,`messaging`,`full`}.

## CLI commands the adapter will rely on

| Need | Command (2026.5.12) | Notes |
|---|---|---|
| version | `openclaw --version` | |
| roster | `openclaw agents list --bindings` | read-only; works headless |
| validate | `openclaw config validate` | read-only; "Config valid" |
| schema | `openclaw config schema` | 2.4 MB JSON; source of truth for keys |
| add agent | `openclaw agents add` | not run yet |
| write config | `openclaw config patch --file … --dry-run` / `config set --batch-file … --dry-run` | dry-run first, always |
| wake one turn | `openclaw agent --agent <id> --message … --json` (via Gateway) or `--local` (embedded, needs provider keys in env) | `--deliver` must never be passed |
| isolation | `openclaw --profile <name>` → state + config under `~/.openclaw-<name>` | see ADR-019 |
| doctor | `openclaw doctor` | **not run**: even without `--fix` it may apply "safe migrations"; run only after a fresh backup, in Era I |

## The Human's OpenClaw as found (cycle 7) — hands off

- 4 agents, all `openrouter/deepseek/deepseek-v4-flash`: `main` (Telegram `chatbot`),
  `rachel` = OCT Orchestrator (Telegram `default`), `pm`, `analyst`. No `firm-` agent exists.
- No agent has a `tools` or `sandbox` entry; global `tools.profile = "coding"`,
  `tools.web.search` (provider grok) and `tools.web.fetch` **enabled for every agent**. 0 MCP servers.
- The three OCT workspaces live **inside `main`'s workspace** (`~/.openclaw/workspace/OCT/…`), so
  `main` can read and write their memory. Not shared, but nested.
- Auth: `main` and `rachel` have local profiles (openrouter + xai api_key); `pm` and `analyst`
  have an **empty** `auth-profiles.json` → they read through to `main`'s keys (the exact case
  08 §4 forbids for firm agents).
- 118 workspace text files scanned: **0** credential patterns.
- Workspace bootstrap files in use: `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`,
  `HEARTBEAT.md` (+ `MEMORY.md`, custom `PRICE_FETCHER_DIRECTIVE.md`). Which ones 2026.5.12
  still loads is **unverified** (docs list `TOOLS.md`/`HEARTBEAT.md` as retired in the newer
  version) → check before rendering templates (B-012).

## Surprises

1. **"Chat restricted to the central pod" — likely cause found (config, not yet a live test).**
   The Orchestrator's own memory (`…/Orchestrator/memory/2026-05-16-0004.md`) records
   `sessions_spawn` with `agentId` being forbidden, and that spawning with a `cwd` loads the
   *spawner's* workspace files, not the target's. In 2026.5.12 nothing sets
   `subagents.allowAgents`, whose default is "same agent only". → B-014.
2. **Prompts vs tools — a hint, not a measurement.** In May a test "Analyst" used `web_search`
   for prices every time (2 runs, 0 `exec` calls) despite the Analyst's `TOOLS.md`; but the same
   memory file says the test subagent loaded the *Orchestrator's* workspace (a `cwd` does not
   switch the bootstrap files), so it never saw those instructions. Confounded. What stands:
   `web_search` is reachable by every agent and nothing denies it — the look-ahead leak of
   08 §4 is one prompt away. Only the tool layer can enforce the seal (live probe 7).
