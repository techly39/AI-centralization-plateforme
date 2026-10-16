# Real minds v1: a pod of real models lives a backtest month (ADR-047)

What shipped (cycles 42-43; hardened by red-team 0022-0030):

- `openrouter` is a metered provider (`runtime/openrouter.py`). A spec names a `model` and a
  `budget_usd`; the Runtime mints one OpenRouter key per agent with that hard limit, named
  `firm-<run>-<spec id>`, and disables it after the run (never deletes it).
- Monthly accounting across runs: before each key is minted, every `firm-` key on the account counts
  against `firm.monthly_llm_usd_cap` (enabled = its whole limit, disabled = its spend this month).
  The Human's own keys (any other name) are never counted or changed.
- Each morning each mind gets its data package (`--package prices-v1`, `runtime/packages.py`).
- A metered run records a cassette like any other; `replay --verify` judges its trailing cost rows
  apart (`runtime.verify.metered_block`) and replays at $0.

## Run a real month

```bash
set -a; . ./.env; set +a          # FUND_OPENROUTER_PROVISIONING_KEY
export FUND_MARKETDATA__SYNTHETIC_KEY=<64 hex>   # the world's seed; keep it to verify later
uv run fund-runtime backtest --world specs/real-desk/world.json --specs specs/real-desk \
  --input specs/real-desk/input.json --steps 31 --package prices-v1 --cassette PATH.cassette.json
uv run fund-runtime replay --cassette PATH.cassette.json --verify    # $0, offline
```

The pod in `specs/real-desk/` (trend analyst, risk analyst, PM; `anthropic/claude-haiku-5.5`,
$0.40 key each) cost about $0.007 a day in the 1-day trial. The account had about $1.86 of credit
on 2026-10-16: check `GET https://openrouter.ai/api/v1/credits` before a big run.

## Not done

- Company data and headlines packages (the next data-package idea).
- Memory across days: each wake starts from the charter, `/me`, the input and the package; a mind
  remembers yesterday only through the bus (`get_messages`) and its book.
- One lock per repo copy: two clones minting at the same moment do not share it (ADR-047 known limits).
- The demo replays the recorded month, so it proves the record, not the live path; the live
  OpenRouter path is covered by tests against a fake account (`tests/test_runtime_openrouter.py`).
- OpenClaw as a host: still an adapter to certify later (ADR-047 §1).
