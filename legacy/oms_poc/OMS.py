#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
OMS (Order Management System) — OCT simulated broker.

Behavior:
  - Every 60s, scans "Sended orders (not treated)/" for new *.json order files.
  - Each file is one PM submission and may contain multiple ticker sub-orders.
  - Buys only. Sells/shorts are rejected.
  - For each sub-order:
      * price_to_enter == "current"   -> market order, executed now
      * price_to_enter == <number>    -> limit order, queued in "Pending Orders/"
  - Cost check is done across the whole submission (sum of market + limit
    notionals). If the total exceeds available cash, the WHOLE submission
    is cancelled (POC behavior — PM must rework priorities).
  - At market execution, the price is re-fetched and cash re-checked. If
    cash is no longer sufficient, the whole submission is cancelled.
  - When a fill happens, Portfolio.json is updated atomically (cash + positions).
  - Pending orders live as one JSON file per ticker order under "Pending Orders/"
    so the limit-watcher script can poll them every 10 min.

Prices are obtained by shelling out to:
  ../Skills/price_fetcher.py   (action=price, --ticker=<TICKER>)
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
OMS_DIR        = Path(__file__).resolve().parent
POC_ROOT       = OMS_DIR.parent
INBOX_DIR      = OMS_DIR / "Sended orders (not treated)"
PENDING_DIR    = OMS_DIR / "Pending Orders"
LOGS_DIR       = OMS_DIR / "Logs"
PROCESSED_DIR  = OMS_DIR / "Processed orders"
PORTFOLIO_FILE = OMS_DIR / "Portfolio.json"
PRICE_FETCHER  = POC_ROOT / "Skills" / "price_fetcher.py"

for d in (INBOX_DIR, PENDING_DIR, LOGS_DIR, PROCESSED_DIR):
    d.mkdir(parents=True, exist_ok=True)

POLL_SECONDS = 60

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "oms.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("OMS")


# ---------------------------------------------------------------------------
# JSON I/O (atomic write)
# ---------------------------------------------------------------------------
def _load_json(path: Path, default):
    if not path.exists() or path.stat().st_size == 0:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_portfolio() -> dict:
    p = _load_json(PORTFOLIO_FILE, {"cash": 0.0, "positions": {}})
    p.setdefault("cash", 0.0)
    p.setdefault("positions", {})
    return p


def save_portfolio(p: dict) -> None:
    _save_json(PORTFOLIO_FILE, p)


# ---------------------------------------------------------------------------
# Price fetcher — calls the Skills/price_fetcher.py script
# ---------------------------------------------------------------------------
def get_price(ticker: str) -> float:
    proc = subprocess.run(
        ["uv", "run", str(PRICE_FETCHER), "price", "--ticker", ticker],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"price_fetcher failed for {ticker}: {proc.stderr.strip()}")
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    if "error" in payload:
        raise RuntimeError(f"price_fetcher error for {ticker}: {payload['error']}")
    return float(payload["price"])


# ---------------------------------------------------------------------------
# Order parsing & validation
# ---------------------------------------------------------------------------
def parse_order_file(path: Path) -> list[dict]:
    """A submission file is a JSON list of sub-orders (or a single object)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("order file must be a JSON object or list of objects")
    return data


def validate_suborder(o: dict) -> None:
    required = ("ticker", "quantity", "price_to_enter", "justification")
    for k in required:
        if k not in o:
            raise ValueError(f"missing field '{k}'")
    if "side" in o and str(o["side"]).lower() not in ("buy", "long"):
        raise ValueError(f"only buy orders are accepted, got side={o['side']}")
    qty = int(o["quantity"])
    if qty <= 0:
        raise ValueError(f"quantity must be > 0, got {qty}")
    ptype = o["price_to_enter"]
    if ptype != "current":
        try:
            if float(ptype) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"price_to_enter must be 'current' or a positive number, got {ptype!r}")


# ---------------------------------------------------------------------------
# Portfolio mutation
# ---------------------------------------------------------------------------
def apply_fill(portfolio: dict, ticker: str, qty: int, price: float) -> None:
    cost = qty * price
    portfolio["cash"] = round(portfolio["cash"] - cost, 4)
    positions = portfolio["positions"]
    if ticker in positions:
        old_qty = positions[ticker]["quantity"]
        old_avg = positions[ticker]["avg_price"]
        new_qty = old_qty + qty
        new_avg = ((old_qty * old_avg) + cost) / new_qty
        positions[ticker] = {"quantity": new_qty, "avg_price": round(new_avg, 4)}
    else:
        positions[ticker] = {"quantity": qty, "avg_price": round(price, 4)}


# ---------------------------------------------------------------------------
# Submission processing
# ---------------------------------------------------------------------------
def process_submission(submission_path: Path) -> dict:
    submission_id = str(uuid.uuid4())
    log.info(f"--- submission {submission_path.name} (id={submission_id}) ---")

    try:
        suborders = parse_order_file(submission_path)
        for o in suborders:
            validate_suborder(o)
    except Exception as e:
        log.error(f"invalid submission {submission_path.name}: {e}")
        return _archive(submission_path, submission_id, "rejected",
                        {"reason": "invalid_format", "error": str(e)})

    portfolio = load_portfolio()
    cash_start = portfolio["cash"]

    # 1. Estimate notional across the whole submission.
    priced = []
    total_cost = 0.0
    for o in suborders:
        ticker = o["ticker"]
        qty = int(o["quantity"])
        try:
            ref = get_price(ticker) if o["price_to_enter"] == "current" else float(o["price_to_enter"])
        except Exception as e:
            log.error(f"price lookup failed for {ticker}: {e}")
            return _archive(submission_path, submission_id, "cancelled",
                            {"reason": "price_lookup_failed",
                             "ticker": ticker, "error": str(e)})
        cost = qty * ref
        total_cost += cost
        priced.append({"order": o, "qty": qty, "ref_price": ref, "cost": cost})
        log.info(f"  {ticker}: qty={qty} @ ${ref:.2f} = ${cost:.2f}")

    log.info(f"submission total est. ${total_cost:.2f} | cash available ${cash_start:.2f}")

    # 2. Whole-submission cash gate.
    if total_cost > cash_start:
        log.warning("insufficient cash for whole submission — cancelling.")
        # TODO(POC+1): notify the PM here so they can re-prioritize.
        return _archive(submission_path, submission_id, "cancelled",
                        {"reason": "insufficient_cash",
                         "needed": total_cost, "available": cash_start})

    # 3. Execute market orders, queue limit orders.
    results = []
    queued_paths: list[Path] = []
    for item in priced:
        o = item["order"]
        ticker = o["ticker"]
        qty = item["qty"]

        if o["price_to_enter"] == "current":
            # Re-fetch and re-check cash at the moment of execution.
            try:
                fill_price = get_price(ticker)
            except Exception as e:
                log.error(f"exec price fetch failed for {ticker}: {e} — cancelling submission")
                _rollback_queued(queued_paths)
                return _archive(submission_path, submission_id, "cancelled",
                                {"reason": "exec_price_lookup_failed",
                                 "ticker": ticker, "error": str(e)})
            cost = fill_price * qty
            if cost > portfolio["cash"]:
                log.warning(f"cash drifted below need at exec for {ticker} — cancelling submission")
                _rollback_queued(queued_paths)
                return _archive(submission_path, submission_id, "cancelled",
                                {"reason": "insufficient_cash_at_exec",
                                 "ticker": ticker, "needed": cost,
                                 "available": portfolio["cash"]})
            apply_fill(portfolio, ticker, qty, fill_price)
            save_portfolio(portfolio)  # persist after each fill
            log.info(f"FILLED {ticker} x{qty} @ ${fill_price:.2f} "
                     f"(cost ${cost:.2f}, cash now ${portfolio['cash']:.2f})")
            results.append({"ticker": ticker, "status": "filled",
                            "quantity": qty, "fill_price": fill_price})
        else:
            order_id = str(uuid.uuid4())
            entry = {
                "order_id": order_id,
                "submission_id": submission_id,
                "ticker": ticker,
                "quantity": qty,
                "limit_price": float(o["price_to_enter"]),
                "justification": o.get("justification", ""),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }
            qpath = PENDING_DIR / f"{ticker}_{order_id}.json"
            _save_json(qpath, entry)
            queued_paths.append(qpath)
            log.info(f"QUEUED {ticker} x{qty} @ ${entry['limit_price']:.2f} "
                     f"-> {qpath.name}")
            results.append({"ticker": ticker, "status": "pending",
                            "order_id": order_id, "limit_price": entry["limit_price"]})

    return _archive(submission_path, submission_id, "accepted",
                    {"results": results, "remaining_cash": portfolio["cash"]})


def _rollback_queued(paths: list[Path]) -> None:
    for p in paths:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _archive(src: Path, submission_id: str, status: str, extra: dict) -> dict:
    record = {
        "submission_id": submission_id,
        "source_file": src.name,
        "status": status,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    dest = PROCESSED_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{status}_{src.name}"
    try:
        src.rename(dest)
    except OSError:
        # cross-device or busy — fall back to copy + unlink
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        src.unlink()
    _save_json(dest.with_suffix(".result.json"), record)
    log.info(f"submission {submission_id} -> {status}")
    return record


# ---------------------------------------------------------------------------
# Inbox scan loop
# ---------------------------------------------------------------------------
def scan_inbox_once() -> int:
    files = sorted(p for p in INBOX_DIR.glob("*.json") if p.is_file())
    if not files:
        return 0
    log.info(f"inbox: {len(files)} new submission(s)")
    for f in files:
        try:
            process_submission(f)
        except Exception as e:
            log.exception(f"unhandled error processing {f.name}: {e}")
    return len(files)


def run_forever() -> None:
    log.info(f"OMS started. Watching: {INBOX_DIR}")
    while True:
        try:
            scan_inbox_once()
        except Exception as e:
            log.exception(f"scan loop error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        scan_inbox_once()
    else:
        run_forever()
