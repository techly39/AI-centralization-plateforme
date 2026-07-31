# OMS migration — from the file-based POC to the app

The old OMS was a standalone script that watched a folder. The new one is a
module inside the app, reached only through the API. This document is the
point-by-point record of what moved where, why, and what changed beyond the
minimum — read it before touching `app/oms/`.

The old code is preserved, unused, in [`legacy/oms_poc/`](../legacy/oms_poc/).

---

## 1. The eight required changes

These are the discrepancies listed in the original migration analysis, and how
each is resolved.

| # | Old behaviour | New behaviour | Where |
|---|---|---|---|
| 1 | **Order ingestion** — scanned `Sended orders (not treated)/` for JSON files every 60s | `POST /orders`, authenticated, one order per request, validated by a Pydantic schema | [`app/api/orders.py`](../app/api/orders.py) |
| 2 | **State** — read and rewrote `Portfolio.json` | Immutable `order_filled` events in SQLite; `positions` and `cash_balances` are *derived* by folding those events | [`app/ledger/apply.py`](../app/ledger/apply.py), [`app/ledger/reducers.py`](../app/ledger/reducers.py) |
| 3 | **Time** — `datetime.now(timezone.utc)` scattered through the file | Every timestamp comes from `get_clock().now()`; the OMS never reads the system clock | [`app/clock.py`](../app/clock.py) |
| 4 | **Prices** — shelled out to `../Skills/price_fetcher.py` per ticker (a subprocess per quote) | `MarketDataProvider` interface with a yfinance implementation, injectable and cached | [`app/marketdata/`](../app/marketdata/) |
| 5 | **Sells** — rejected outright ("buys only") | Buys and sells, partial sells allowed, realised P&L booked on the fill event | [`app/oms/service.py`](../app/oms/service.py) |
| 6 | **Costs** — `qty × price`, no fee | `qty × price` **+ a configurable fee** (default 0.1%), charged on both sides | [`app/oms/money.py`](../app/oms/money.py) |
| 7 | **Security** — none; any file in the folder was an order | API key → agent → role check (`place_order`) → pod-scope check (own pod only) | [`app/registry/auth.py`](../app/registry/auth.py), `_validate_request` |
| 8 | **Pending orders** — one JSON file per order, polled by a separate script | Rows in `orders` with `status='pending'`, swept by an APScheduler job | [`app/oms/monitor.py`](../app/oms/monitor.py), [`app/scheduler.py`](../app/scheduler.py) |

## 2. What changed beyond that list

The eight items above make the OMS *fit*. These make it *correct*. Each one is
a bug the old design either had or would have grown.

**Whole-submission cancellation is gone.** The POC treated a file of sub-orders
as one atomic submission: if the total exceeded cash, *every* order in it was
cancelled. The TRD models one order per request, so each order now succeeds or
fails on its own. A PM whose third idea is unaffordable keeps the first two.

**Rejections are recorded, not discarded.** The POC moved the file to
`Processed orders/` and wrote a `.result.json` next to it. Now a rejected order
is a real row with `status='rejected'` and a `status_reason`, an
`order_rejected` event, **and** a message to the PM carrying the actual numbers
(required, needed, available, shortfall) as structured JSON — TRD §8.2. See
[`app/bus/notify.py`](../app/bus/notify.py).

**Cash is re-validated at fill time, not just at submission.** A limit order
placed yesterday cannot overdraw a pod that spent its cash this morning. The
monitor re-runs the full affordability check before every fill and rejects the
order if it no longer holds. Covered by
`test_pending_buy_is_rejected_if_cash_ran_out_meanwhile`.

**Concurrent orders cannot double-spend.** The POC was single-threaded, so it
never had to think about this; a web server does. Two simultaneous requests would
both read the same balance and both spend it. `OMS_LOCK` serialises the
read-check-write-commit sequence. `tests/test_oms_concurrency.py` is the proof —
if someone removes the lock, that test breaks.

**Live state and replayed state are provably identical.** The derived tables are
updated incrementally on each fill (fast), but `rebuild_state()` recomputes them
from the whole ledger (authoritative). Both call the *same* reducer functions —
there is exactly one implementation of the money arithmetic — and
`tests/test_oms_replay_consistency.py` trades a full sequence and asserts the two
agree to the cent. This is the TRD's Definition of Done, made mechanical.

**One price lookup per ticker per sweep.** The POC ran a subprocess per quote.
The monitor now prices each distinct ticker once per sweep, and the provider
caches quotes for a configurable window.

**A feed outage no longer decides anything.** The POC cancelled the submission
when a price lookup failed. Now an unpriceable pending order simply stays
pending, and an unpriceable position in a portfolio comes back with `null`
valuation fields plus `fully_priced: false` — the rest of the book is still
readable.

**Tickers are normalised once.** `normalise_ticker` upper-cases and trims at
every entry point, so `aapl` and `AAPL` can never become two positions in the
same pod.

**No look-ahead, from day one.** `validate_window` rejects any request for data
past the clock's "now", and the yfinance provider drops bars stamped after it.
Live mode never notices; Phase 3's backtests depend on it entirely.

## 3. Who checks permissions, and why it looks duplicated

Three different questions get asked, and they cannot all live in one place.

| Question | Asked by | Why there |
|---|---|---|
| Who are you? (API key → an active agent) | **API only** — `app/registry/auth.py` | Only the API sees HTTP headers. |
| May this role *ever* place an order? | **API**, then **the OMS again** | TRD §6 puts the matrix in the API layer; TRD §8.1 lists "authenticate + permission check" as step 1 of the OMS's own flow. Both are satisfied by checking twice. |
| Is this the agent's **own** pod? | **OMS only** — `_validate_request` | The matrix is a `role → action` table. It cannot express the "(own pod)" qualifier in the TRD §6 row for orders; that needs the agent-to-pod relationship. |

The middle row is deliberate defence in depth: `place_order()` must be safe when
called from something that is not an HTTP route — a maintenance script, Phase
3's backtest driver, a test.

**The rule that makes the duplication safe:** the OMS does not keep its own list
of roles. It calls `has_permission(actor.role, Action.PLACE_ORDER)` — the same
function, reading the same `_MATRIX`, that the API's dependency uses. Add a role
to `app/registry/permissions.py` and both layers start allowing it, with no
edit anywhere else.

If someone ever replaces that call with a hardcoded role tuple, the layers can
silently disagree — the API lets a request through and the OMS rejects it with a
baffling 403. [`tests/test_oms_permissions.py`](../tests/test_oms_permissions.py)
prevents it: `test_the_oms_follows_the_matrix_it_does_not_hardcode_roles` widens
the matrix at runtime and fails unless the OMS follows.

## 4. Behaviour worth knowing

**Limit orders never fill at placement.** Per TRD §8.4 a limit order is queued as
`pending` and the monitor fills it on its next sweep — even one that is already
marketable. So a buy limit at \$400 with the market at \$331 comes back
`pending` and fills seconds later, at \$331 (the market price, not the limit:
if the market gaps through your limit, you get the better price).

**Cash is not reserved while an order waits.** A pending limit order does not
ring-fence the money. The check happens at submission and again at fill. This
matches the TRD; if you later want reservations, that is a deliberate change to
`assert_affordable`, and the tests will tell you what it breaks.

**Fees are expensed, not capitalised.** `avg_cost` is the clean average
execution price; fees hit cash directly and never enter the cost basis. Realised
P&L is `qty × (price − avg_cost) − exit fee`. This is inherited from the Phase 0
reducer — changing it would rewrite the meaning of every historical event.

**`POST /orders` answers 201 even for a rejection.** The order resource was
created; its state happens to be `rejected`. Clients must read `status`, not
just the HTTP code. Malformed requests (bad qty, missing limit price) are a
different thing and answer 422 with nothing stored.

## 5. Things deliberately left out

- **`POST /allocations`** is a Phase 3 endpoint (TRD §11), so funding a pod is
  an operator command for now: `fund-env create-pod` / `fund-env fund-pod`. Both
  call `app/registry/pods.py:fund_pod`, which the Phase 3 endpoint will reuse
  unchanged.
- **`run_id` scoping** (TRD §9, separating live and backtest runs) belongs to
  Phase 3. It will be an alembic migration adding a column, not a redesign.
- **The messaging API** (`GET /messages`) is Phase 2. Rejection notices are
  already written into the `messages` table in the right shape, so that endpoint
  will surface them with no backfill.
- **Short selling** is not supported: a sell is validated against the position
  held. Nothing in the TRD asks for shorts.
