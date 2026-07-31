# legacy/

Nothing in here is used by the app. It is the previous, file-based OMS proof of
concept, kept only so the migration is reversible and so the old numbers are not
lost.

## oms_poc/

The directory-scanning OMS that ran before Phase 1. It read JSON order files from
an inbox folder, priced them by shelling out to a `price_fetcher.py` script,
wrote fills into `Portfolio.json`, and queued limit orders as one file per order.

Its replacement lives in `app/oms/` and is reached through the API
(`POST /orders`), not the filesystem. See `docs/oms_migration.md` for the
point-by-point mapping.

`Portfolio.json` holds the POC's closing state (cash plus four positions). If you
want to continue from it, create a pod and replay those holdings as orders —
do not copy the file anywhere; the app's portfolio is derived from the event
ledger, not from a file.

Safe to delete once you are confident in the new system.
