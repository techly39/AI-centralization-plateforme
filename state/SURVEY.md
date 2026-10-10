# SURVEY — Era ½ (written section by section; complete when every section is filled)

Sections: 1 Toolchain · 2 What exists · 3 What works · 4 What's broken · 5 What's dead ·
6 Risks · 7 Surprises · 8 What this changes in the backlog.

## 1. Toolchain (cycle 3, 2026-10-11)

| Tool | Version | Notes |
|---|---|---|
| macOS | 26.5.2 (25F84), arm64 | Mac mini |
| uv | 0.11.14 (Homebrew) | |
| Python (project venv) | 3.12.13 (uv-managed) | `.python-version` pins 3.12 — matches the TRD |
| Python (system `python3`) | 3.14.4 | only the guard hook uses it (stdlib only) |
| SQLite | 3.50.4 in the venv's `sqlite3`; CLI 3.51.0 | `TOTAL()` (ADR-018) available in both |
| Node / npm | v22.22.2 / 10.9.7 | needed by OpenClaw |
| OpenClaw | 2026.5.12 (f066dd2), `/opt/homebrew/bin/openclaw` | details → S-005 / `runtime/openclaw/VERSION_NOTES.md` |
| Claude Code | 2.1.296 (inferred from the install path, not `--version`) | `claude --version` needs a permission prompt in loop mode |
| git | not captured | `git --version` needs a permission prompt in loop mode |
| origin | github.com/techly39/AI-centralization-plateforme | `main` = origin/main at cycle start |

Key Python deps (locked): fastapi 0.139.2 · pydantic 2.13.4 · sqlalchemy 2.0.51 · alembic 1.18.5 ·
apscheduler 3.11.3 · **mcp 2.0.0** · yfinance 1.5.2 · pytest 9.1.1 · uvicorn 0.51.0 · httpx 0.28.1.
All match the TRD stack.

### Run check — evidence

`uv run python scripts/smoke_run.py` (new this cycle; temp dir, never touches `fund.db`):

```
[PASS] fund-env init-db — Database schema is up to date (alembic head).
[PASS] fund-env seed-admin
[PASS] fund-env create-pod — Pod created: id=1 name=smoke-pod allocation=$1,000,000.00
[PASS] fund-env serve answers /health — http://127.0.0.1:59846
[PASS] GET /docs
[PASS] MCP handshake + list_tools — 20 tools
[PASS] MCP call get_health / get_clock / list_agents / get_leaderboard / list_events
[PASS] server stopped cleanly on SIGINT — rc=0
```

So: the CLI builds a schema from zero through all alembic migrations, the API serves, and an
MCP client (the same path OpenClaw will use) authenticates with a seeded key and reads through
every layer. The physics runs outside pytest.

### Findings from the run check
- **mcp 2.0 renamed result fields** (`CallToolResult.isError` → `is_error`). Any client code or
  doc written against mcp 1.x idioms will break silently-ish; `agent_console.py` only reads
  `.content`, so it is unaffected. Watch for this in the OpenClaw adapter (B-012).
- `scripts/README.md` said "19 tools"; there are 20 (fixed).
- Stopping `uv run fund-env serve`: SIGTERM → rc=143 (128+15; which process reports it — `uv` or
  uvicorn — is unverified), SIGINT → rc=0 (measured). The script and the Runtime (B-009) stop
  the server with SIGINT.
- The live clock reports UTC (`2026-10-10T23:33Z` while local time was 01:33 CEST) — correct.
- `fund.db` at the repo root holds the Human's August history (167 kB, last write 2026-08-02).
  The Builder must never run the CLI against it by default — use `FUND_DATABASE_URL` or the smoke script.
- Loop-mode permission prompts block `VAR=x cmd`, `git --version`, `claude --version` and
  multi-op shell lines; plus the guard's `loop` substring rule (P-0001). Survey tooling should be
  scripts run as one `uv run python …` command.

## 2–8
To be filled by S-003 (repo survey), S-004 (cleanup), S-005 (OpenClaw), S-006, S-007.
