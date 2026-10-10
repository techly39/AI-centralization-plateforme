# Phase 2 — Bus, costs, and MCP

What Phase 2 added, and the decisions behind the parts of it that were not
spelled out in the TRD. Read this before changing anything in `app/bus/`,
`app/metrics/`, or `mcp_server/`.

## What shipped

| TRD requirement | Where it lives |
|---|---|
| `POST /messages`, `GET /messages` | `app/bus/`, `app/api/messages.py` |
| Directory | `GET /agents` (Phase 0) — now also reports `status` |
| Self-identification | `GET /me` — the caller's own directory row |
| `POST /costs`, `/tasks/start`, `/tasks/end` | `app/metrics/reporting.py`, `app/api/reporting.py` |
| `GET /metrics/pod/{id}`, `/metrics/leaderboard` | `app/metrics/`, `app/api/metrics.py` |
| MCP server over every endpoint | `mcp_server/` |
| Milestone: the OpenClaw POC, through the app only | `tests/test_poc_milestone.py` |

## Decisions

### Addressing: `agent:3`, `pod:1`, `broadcast`

`messages.to_ref` is a union of three things, so the kind is written into the
string — `7` alone could mean agent 7 or pod 7. The format and its parser live in
one module (`app/bus/refs.py`) because it is a wire contract: agents type it,
read it back, and the UI will render it in Phase 4.

### Why a PM's `broadcast` comes back as `pod:<their pod>`

TRD §6 has two rows that look contradictory: "send message (any agent/pod)" is
allowed for everyone, while "broadcast to a pod" is management, or a PM **on its
own pod**. The reading implemented here:

* addressing a named agent or a named pod is ordinary messaging — any role;
* `broadcast` is the restricted verb. Management reaches the firm; a PM reaches
  its own pod, so the app rewrites the address to `pod:<their pod>`; an analyst
  is refused with a logged 403.

The response returns the *effective* audience rather than echoing the request, so
a PM can see what actually happened. If you ever want a PM to be genuinely unable
to broadcast, remove `Action.BROADCAST` from the pm row in
`app/registry/permissions.py` — nothing else needs to change.

### Polling: use `after_id`, not `since`

`GET /messages?since=` is in the TRD and works. It is not sufficient on its own:
in backtest mode (Phase 3) the clock stands still, so a whole simulated
conversation shares one timestamp and a time cursor either repeats or skips it.
`after_id` is monotonic in insertion order and always separates messages.
`tests/test_messaging.py::test_frozen_clock_ties_do_not_break_polling` pins this.

### Catching up: `latest`, then `before_id`

`after_id` only walks forward from message 1, which makes "where does the history
end" a page-per-500-messages question. An agent restarting into a fund that has
been running for a month would pay that cost on every start, and the Phase 4 feed
would pay it on every render.

So `GET /messages` reads in two directions:

| You want | Call |
|---|---|
| what arrived since I last looked | `after_id=<highest id I hold>` |
| the newest page, from cold | `latest=true&limit=n` |
| the page before that | `before_id=<lowest id I hold>` |

Backwards reads order by `(ts, id)` descending, take `limit`, and reverse in
Python, so **every** page is oldest-first no matter how it was gathered — callers
never branch on ordering. The visibility predicate is the same `visible_to()`
either way, so reading from the end is not a way around it.

The two directions are refused together (422, `conflicting_cursors`) rather than
resolved by precedence: a caller that believes it is reading history while it is
actually tailing new traffic loses messages and never finds out.

### `GET /me` is authentication-only, on purpose

It is the one endpoint with no entry in the permission matrix. The TRD's §6 table
is about what an agent may *do to the firm*; reading the row that describes you is
not one of those things, and gating it would defeat the point of having it.

The point is that identity has exactly one source. Without `/me`, an agent's
`agent_id`, `pod_id`, and `role` have to be written into its prompt — a second
copy of the `agents` table, maintained by hand, in another repository, that starts
drifting the moment management moves someone between pods. Worse, a fresh agent
could only discover its own boundaries by attempting things and reading the 403s.
`GET /portfolio/{pod_id}` needs a pod id the agent had no way to ask for.

`whoami` is the MCP tool, and the server's instructions tell agents to call it
first and to believe it over their own prompt.

### Cost and task attribution is not a parameter

`POST /costs` has no `agent_id` and no `pod_id`; `/tasks/end` refuses a task the
caller does not own. The app cannot verify what an agent spent — it runs outside
the agent — so the one thing it can guarantee is that a report is about its
sender. Without that, a pod could charge its token bill to a rival and the
leaderboard would be worthless.

Zero cost reports show up as `cost.reports == 0` rather than as `$0`, so an
unmeasured pod is visibly unmeasured instead of looking free.

### Performance is time-weighted

Management adding capital is not a return. Each day's return is
`(equity − that day's net flow) / yesterday's equity − 1`, compounded. Without
this the leaderboard would rank pods by how much money they were handed.

Two consequences worth knowing:

* **Total return is not `pnl / net_contributed`.** Time-weighted return measures
  growth from the first daily close, so costs paid on day one — before there was
  a prior equity to measure against — fall outside the series. Both numbers are
  reported; `pnl` is the economic one (`total_value − net_contributed`).
* **Statistics with too little history are `null`, not `0`.** A one-day-old pod
  has no Sharpe ratio. Reporting zero would make it look flat rather than new.

Max drawdown is computed on the compounded return index, not on raw equity, so a
withdrawal is not reported as a loss.

### The equity curve is rebuilt, not stored

`app/metrics/equity.py` replays the pod's ledger day by day through the **same
reducers** the live portfolio uses (`app/ledger/reducers.py`), then prices each
day from one daily-close series per ticker. The final point prefers a live quote,
so `GET /metrics/pod/{id}` and `GET /portfolio/{id}` always agree on what a pod
is worth today.

Cost: one OHLCV fetch per distinct ticker the pod ever held. The leaderboard
shares a `DailyCloseCache` across pods so a name held by five desks is downloaded
once. Curves are capped at `MAX_CURVE_DAYS` (5 years).

A ticker that cannot be priced is carried at its average cost and named in
`pricing_errors` — the same degrade-don't-fail rule the portfolio endpoint
already followed.

### The MCP server is a client, not a second implementation

`mcp_server/` makes ordinary HTTP calls with an ordinary API key. It imports
nothing from `app` except the settings object. That is why the tool list is
identical for an analyst and for management: **permissions are the API's job**,
and an analyst calling `place_order` gets the API's own 403 text back. Filtering
the tool list per role would create a second permission model to keep in sync.

One MCP server process = one agent identity. Run one per agent, each with its own
`FUND_MCP__API_KEY`, and the ledger attributes everything correctly for free.

`tests/test_mcp_server.py::test_every_endpoint_has_a_tool` reads the app's own
OpenAPI schema, so adding a route without a tool fails the suite.

## One fix that was not in the phase's scope

Timestamps were being written to SQLite as timezone-aware UTC and read back
*naive*, because SQLite has no time zone type and silently drops the offset.
Nothing had subtracted two timestamps before, so it had not surfaced; the first
thing that did (task durations) crashed. `app/db/types.py` now converts at the
column boundary, so every datetime that comes out of the database is aware UTC
and directly comparable with `clock.now()`.

Storage format is unchanged, so no data migration was needed — existing rows load
correctly. This mattered enough to fix now because Phase 3 is entirely about
time.

## What Phase 2 deliberately did not do

* No websockets — polling only (TRD §12).
* No `GET /costs` or `GET /tasks` endpoints. The TRD lists three reporting
  endpoints and the metrics views that consume them; adding query endpoints is a
  Phase 4 (UI) question.
* No allocation endpoint, no clock control, no meetings — those are Phase 3.
* Metrics stay management-only, exactly as the TRD says, even though a PM would
  reasonably want its own pod's numbers. If that changes, it is a one-line change
  in `app/api/metrics.py`, not a redesign.
