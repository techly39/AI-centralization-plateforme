# 08 — OpenClaw: setting up the firm's minds correctly

Living book. The OpenClaw agents are the **subjects of the experiment**. A badly set-up
agent doesn't just misbehave — it silently invalidates every result it touches:

| Misconfiguration | What it breaks |
|---|---|
| Agent can browse / search the web | **Look-ahead leak**: in a 2008 backtest it can google what happened next. Also breaks the seal (Art. 2.1). |
| Agent shares an auth profile / falls back to `main`'s key | Cost attribution is wrong; the leaderboard is fiction. |
| Agent has a shell (`exec`) or write access outside its workspace | It can touch the host, read other agents' memory, or forge files. Incident. |
| Agent's API key written in its workspace files | Another agent (or a prompt leak) steals its identity. |
| Two agents share a workspace or `agentDir` | Memories and sessions bleed into each other. |
| Agent is bound to a channel (Telegram, WhatsApp…) | It can contact real people (Art. 2.3). |
| Prompt says "you are agent 7 in pod 2" | Identity drifts from the App's truth the first time HR moves someone. |

So the standard is: **every firm agent is set up perfectly, verified by a conformance
suite, every time it is created and every time OpenClaw is upgraded.**

## 1. Rule zero — verify, never remember

OpenClaw changes fast. Example: in the Oct 2026 docs the agent roster key is
`agents.entries` (older `agents.list` is migrated by `openclaw doctor`), and the docs
navigation lists `TOOLS.md` and `HEARTBEAT.md` as **retired** workspace files — while the
OCT POC was built with `TOOLS.md`. Anything you "know" about OpenClaw may be stale.

**The docs are not your version** (Survey, cycle 7 — `runtime/openclaw/VERSION_NOTES.md`):
`docs.openclaw.ai` serves the *latest* release (no versioned docs were found). The Mac mini
runs **2026.5.12**, whose roster key is still `agents.list`, while the docs (≥ 2026.9) say
`agents.entries` — and at least one newer default is **looser**: `tools.sessions.visibility`
`tree` → `all`. (The docs also say `tools.agentToAgent.enabled` defaults on; the installed
schema states no default, so that one is unknown, not measured.) An upgrade can silently
widen what an agent sees: render every seal key explicitly, never inherit a default (B-023).

Before writing any OpenClaw integration code:
1. `openclaw --version` and `openclaw config schema` (the installed CLI's own schema is the
   source of truth for keys). **Not** `openclaw doctor` at first: even without `--fix` it
   may apply "safe migrations" to the config. Run it only after a fresh backup (§2), and
   only against the firm's profile (ADR-019).
2. Read the docs (docs.openclaw.ai): multi-agent, agent workspace, configuration /
   per-agent entries, tools & sandbox, MCP, auth profiles, how to run a turn for one agent
   from CLI or gateway — and check every key you take from them against the installed
   schema. Where they disagree, the schema wins; record the difference.
3. Write `runtime/openclaw/VERSION_NOTES.md`: version, every config key and CLI command the
   adapter relies on, with doc links, and anything that surprised you.
4. Pin the version the adapter was verified against. On upgrade: re-read, update the
   notes, re-run conformance before any agent wakes.

Known from docs at Bible writing (re-verify): config `~/.openclaw/openclaw.json`
(`OPENCLAW_CONFIG_PATH`), state dir `~/.openclaw` (`OPENCLAW_STATE_DIR`), per-agent
`workspace` and `agentDir` (default `~/.openclaw/agents/<agentId>/agent`), per-agent auth
store in the agentDir, agents **without** a local auth profile read through to the main
agent's profiles, `openclaw agents add <id> --workspace --model --agent-dir --non-interactive`,
`openclaw agents list --bindings`, `tools.allow` / `tools.deny` (deny wins; each layer
can only restrict), MCP tools named `<server>__<tool>` and filterable with globs,
`sandbox.mode` / `workspaceAccess`.
*Measured on 2026.5.12 (cycles 7–8):* `mcp.servers`, `tools.web`, `tools.sessions` and
`tools.agentToAgent` are **global only** — there is no per-agent MCP key. (`tools.profile`
does have a per-agent override, `agents.list[].tools.profile`.) Hence one named MCP server per firm agent, admitted by that agent's allowlist glob
alone, inside the firm's own profile (§2, ADR-019). Details: VERSION_NOTES.

## 2. Rule one — never break the Human's OpenClaw

The Mac mini already runs OpenClaw for the Human (e.g. `main`, the OCT POC agents,
Telegram bots).
- **Back up first:** before the first change, archive `~/.openclaw` (config, agents,
  workspaces — exclude nothing) to `~/firm-openclaw-backups/<timestamp>.tar.gz`. Back up
  again before every config migration. Never print secrets from it.
  **Born private:** the archive holds credentials, so create it under `umask 077` in a
  `700` directory (`openclaw backup create` exists; the mode of its archives is unverified) — fixing permissions afterwards may not be
  allowed to a headless Builder (cycle 7's tarball came out `644`, Q-0004).
- **Own profile (ADR-019):** because the seal keys are global, firm agents do not live in
  the Human's config at all: they live in a separate OpenClaw profile
  (`openclaw --profile firm` → `~/.openclaw-firm`), so firm seal settings never change the
  Human's agents and vice versa. Unverified until the adapter (B-012) proves it.
- **Namespace:** firm agents are `firm-<podslug>-<role>-<name>` (management:
  `firm-mgmt-<role>-<name>`). The adapter only creates, changes, or retires agents with
  the `firm-` prefix.
- **Hands off** `main` and every non-`firm-` agent, binding, and channel. Migrating
  anything of the Human's goes through `state/PROPOSALS.md`.

## 3. Rule two — configuration is generated, never hand-edited

The source of truth for an agent is its **AgentSpec** in the App (`03_WORLD.md` §3).
The adapter renders everything OpenClaw needs from it, idempotently:

```
AgentSpec ──render──▶ workspace files + openclaw config entry + auth profile + MCP wiring
          ──apply───▶ openclaw agents add / config update (supported CLI/API only)
          ──verify──▶ conformance suite (§5) → only then may the agent wake
```

- Re-rendering an unchanged spec produces zero diff.
- The rendered workspace is hashed; the hash is stored on the AgentSpec and checked at
  every wake (drift = someone or something edited the mind outside the law → finding).
- Agents may write their **own memory** inside their workspace — that is theirs. The
  charter/persona files are physics-owned and re-rendered if changed.

## 4. The per-agent standard

| Aspect | Standard |
|---|---|
| Identity | Unique `agentId` (namespaced). One App API key ↔ one OpenClaw agent ↔ one `fund-env-mcp` process. Identity in prompts = "call `whoami` first and trust it over this text". |
| Workspace | Its own directory, never shared. Persona/charter files rendered from templates in `runtime/openclaw/templates/` using **the bootstrap file names the installed version supports**. |
| agentDir / sessions | Its own, never shared, never reused after an agent dies (archive it). |
| Auth | Its **own local auth profile** holding its own metered key (ADR-007). No read-through to `main`. Verified by probing, not assumed. |
| Model | From the AgentSpec. Model choice is the pod's strategic decision within budget. |
| Tools | **Deny by default.** Allow only the fund MCP tools (`fund__*`, or whatever the server is named) plus the minimal memory/workspace tools the version needs. Deny shell/exec, process, browser, web search/fetch, gateway, and any tool that writes outside the workspace — by whatever names the installed version uses. |
| Sandbox | Strictest mode that still lets the agent work; workspace access no wider than its own workspace. |
| MCP | `fund-env-mcp` with `FUND_MCP__API_KEY=<that agent's key>`, passed through env/secret config — **never** in a workspace file. |
| Channels | **No bindings.** Firm agents talk only through the App's bus. |
| Wake | Through the supported, documented mechanism for the installed version (CLI turn or gateway API), called only by the Runtime scheduler. Record the exact command in VERSION_NOTES. |
| Halt | Runtime checks `governance/HALT` before every wake; the App refuses writes while halted. |

What the agent is told about its world (charter template):
- its role, its pod's mandate, the firm's laws (rendered from the laws table), its duties
  (report tasks; report costs until metering is authoritative), how to use the tools;
- that capital is fictional and the firm is AI-run (honest by default);
- **whether it is told that its market data is historical or synthetic is an
  experimental variable**, recorded per run — never changed silently.

## 5. The conformance suite (definition of "set up perfectly")

`uv run fund-runtime openclaw doctor [--agent <id>] [--live]` plus pytest integration
tests (skipped automatically when OpenClaw is not installed). For every `firm-` agent:

Static checks (free):
1. Agent exists in `openclaw agents list`, with no bindings.
2. Workspace and agentDir exist, are unique, and the workspace hash matches the AgentSpec.
3. Config entry matches the rendered entry exactly (model, tools, sandbox, MCP).
4. A local auth profile exists (no read-through), and no key appears in any workspace file.
5. `openclaw doctor` reports no errors for the firm entries — run against the firm profile
   only, after a fresh backup (it may migrate config even without `--fix`, §1).

Live probes (cheapest model; need a firm budget — skipped with a clear notice while
`monthly_llm_usd_cap` is null):
6. Agent calls `whoami` → returns exactly its own id, role, pod.
7. Agent is asked to fetch a URL, run a shell command, and read another agent's workspace
   → all three refused by the tool layer (not by the model's good manners).
8. Role permissions hold end-to-end (an analyst's `place_order` → the App's 403).
9. The probe's cost appears on **that agent's** metered key and in the App as a
   system-reported cost.
10. With `governance/HALT` present, the Runtime refuses to wake it.

An agent that fails any check **does not wake**. Conformance runs: on spawn, on every
spec change, on OpenClaw upgrade, and at the start of every backtest run. Results are
stored with the run so every experiment can prove its subjects were sound.

## 6. The OCT POC

The earlier OpenClaw Trading POC (Orchestrator, PM, Analyst; Telegram; file-based OMS)
is the ancestor. During the Survey (Era ½): inventory its agents, workspace files,
models, and tools — read-only. In Era I: turn its charters into AgentSpec templates.
The deterministic Runtime replaces the LLM "Orchestrator" role (orchestration is S3, not
an agent). The Human's existing bots stay untouched unless a proposal is accepted.
