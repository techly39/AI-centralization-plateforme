# scripts/ — driving the fund by hand

Two operator tools for exercising the system the way a real agent would, without
a language model in the loop. They are **clients**, not part of the app: they
import `mcp`, never `app`, and everything they do goes through the MCP server →
REST API → bus, hitting every permission check on the way.

| Script | What it is |
|---|---|
| `setup_demo_firm.py` | Registers an analyst and a PM, through MCP, as management. Writes their keys to `agents.local.json` (gitignored, mode 600). |
| `agent_console.py` | One interactive agent. Launches `fund-env-mcp` as a subprocess over stdio, does the MCP handshake, and lets you make the tool calls a model would make. |
| `smoke_run.py` | Run check outside pytest: builds a database in a temp dir with the real CLI, starts `fund-env serve` on a free port, connects `fund-env-mcp` with the seeded key and calls read tools. Never touches `fund.db`. Exit 0 = everything starts. |

## First run

```bash
uv run fund-env init-db
uv run fund-env seed-admin --name mgmt                        # prints a key, once
uv run fund-env create-pod --name demo-pod --allocation 1000000
uv run fund-env serve                                         # leave running

# in another terminal
uv run python scripts/setup_demo_firm.py --management-key fk_... --pod-id 1
```

That last command prints a ready-to-paste launch line per agent. Run each in its
own terminal — one process, one API key, one identity, which is the same rule
`mcp_server/server.py` documents.

## What the console is for

It makes the invisible parts of the bus visible:

- **Nothing is pushed.** Incoming messages appear only when the console polls
  (`/poll`, or the background loop). Turn it off with `/auto off` and watch a
  message sit unseen until you ask for it.
- **Visibility is computed per reader.** Two consoles side by side see different
  subsets of the same `messages` table.
- **Permissions are the app's, not the client's.** All 20 tools are offered to
  every agent; an analyst calling `/send broadcast` gets the real 403.
- **The app is on the bus too.** Reject an order and the `system` agent messages
  you about it, in the same feed as your colleagues.

`/help` lists the commands. `/call <tool> {json}` reaches any endpoint the
shortcuts don't cover.

## Notes

- `agents.local.json` holds live credentials. Keys are unrecoverable if lost —
  register new agents rather than hunting for them.
- The MCP subprocess logs every HTTP request it makes to a file printed at
  startup; `tail -f` it to watch tool calls become requests.
- These scripts write real rows to `fund.db`. Point them at a scratch database
  (`FUND_DATABASE_URL=sqlite:///scratch.db`) if you don't want the history.
