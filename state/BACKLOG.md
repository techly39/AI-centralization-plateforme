# BACKLOG — ordered. Each item serves an exit criterion of the current Era.

## The Runtime — Era I exit (ADR-032; cycle-20 retrospective: this is the frontier)
One slice per cycle, in order. Each names the exit criterion (EC1–EC7, `05_ERAS.md` Era I, in
order) and the vision milestone (M1–M6, `09_BUILDER_VISION.md` §3) it serves. Folded-in items
keep their ids for history.
- [x] **R-1** **Done cycle 21** (merged 8d6e2fe; `runtime/`, `tests/test_runtime_gates.py`,
      red-team 0012: 10 holes, all fixed; ADR-032 amendment (a)–(f)). The gate decides on
      provider **+ adapter**, so `openclaw` always spends. Original: Runtime skeleton (was B-009, first half): `runtime/` package +
      `fund-runtime` script in `pyproject.toml`; `AgentSpec` (pydantic; `03_WORLD.md` §3 fields,
      file-backed for now); governance reader (fixed paths, read-only): HALT → nothing wakes, cap
      `null` → fail closed, only the coded list `{scripted, cassette}` wakes, nothing is
      provisioned (ADR-032 (4), Q-0005); `LLMProvider` protocol. Tests: an unknown provider, and a
      provider claiming `spends_money=False`, are refused under null. Boundary: extend the
      dynamic probe to `runtime` (transitive physics load ⊆ `app.config` + `app.limits`); an
      allowlist for runtime is a law change → ADR-032 amendment + planted counter-example. Serves
      EC5/EC6 (gates exist).
- [x] **R-2** **Done cycle 22** (merged db3e7ee; `runtime/registry.py`, `runtime/scripted.py`,
      `runtime/native.py`, `tests/test_runtime_native.py`, red-team 0013: 8 holes, all fixed;
      ADR-032 amendment (g)(h)(i)). Carry-overs → R-3: the spec's *name* is not bound to the App
      agent (only role + pod) until R-3 provisions agents from specs; tool-function exceptions
      surface only as tool errors (count them in the wake record, re-audit NOTE 1); a real-App
      test of exotic tickers (`^GSPC`, `BRK.B`, `EURUSD=X`) through `_segment` once the synthetic
      world can carry them (re-audit NOTE 5); wall-clock timeout (R-6). Original:
      Carry-overs from R-1 (ADR-032 amendment (b), audit c21 NOTEs 5–6):
      - a name→class registry in which `scripted` and `cassette` each build exactly one class,
        with no model and no network client, plus a test that a `scripted` spec carrying a
        `model` cannot reach a model;
      - decide whether a zero-cost spec with `model` or `budget_usd > 0` is refused;
      - `Usage.cost_usd` is self-reported and is never the meter (R-6).

      Scripted mind + `native` adapter over the published MCP tool list (`build_server`
      → LLM tool schema → calls through `FundClient`); per-wake tool-call budget; HALT re-checked
      before every tool-call batch (03 §3); context =
      charter + `/me` + workflow input, assembled by code and logged. The probe's `ScriptedPM`
      becomes the first scripted mind. Serves M1.
- [ ] **R-3** Split cycle 23 (X-008):
  - [x] **R-3a** **Done cycle 23** (merged 5397ad2; ADR-033 + amendment (a),
        `tests/test_runtime_identity.py`, red-team 0014: 1 low hole, fixed). B-032 + B-000f:
        `runtime` role = READ_HALT/READ_CLOCK/CONTROL_CLOCK; management lost CONTROL_CLOCK;
        `fund-env seed-runtime`; `system` found by role; reserved names.
  - [ ] **R-3b** Split cycle 24 (X-008):
    - [x] **R-3b-1** **Done cycle 24** (merged c3cbfd4; ADR-032 (j) + red-team 0015 amendment,
          ADR-033 (b), `tests/test_runtime_lockstep.py`, red-team 0015: 4 holes, all fixed).
          `runtime.lockstep.run_backtest`, B-041. A mind deactivated in-world is *retired*,
          not a world stop; one App agent = one mind; a failed advance records physics' now.
    - [ ] **R-3b-2** Split cycle 25 (X-008):
      - [x] **R-3b-2a** **Done cycle 25** (merged b0c83a1; ADR-032 (k)(l)(m),
            `tests/test_runtime_pod.py`). `ma-signal-analyst` + `signal-pm`; a two-pod month
            through the conductor, twice; MCP list answers are one array block; `tool_failures`,
            `retired_at`; c24 NOTE 3/4 pinned.
      - [x] **R-3b-2b-1** **Done cycle 26** (merged ca17717; ADR-032 (n) + red-team 0016
            amendment, `tests/test_runtime_provision.py`, `tests/test_redteam_0016.py`: 4 low
            holes, all fixed). `runtime.provision` makes minds from specs with a caller-held
            registrar key (the runtime key gains nothing). Names are folded, reserved and taken
            names are refused before any registration, and the name is bound at wake and
            conductor.
      - [ ] **R-3b-2c** Split cycle 27 (X-008):
        - [x] **R-3b-2c-1** **Done cycle 27** (merged 6d8e08d; ADR-032 (o) + audit amendment,
              `tests/test_runtime_cli_backtest.py`, smoke backtest phase). `fund-runtime
              backtest`; clock checked before any registration; keys from env, redacted
              output, no proxy, loopback only; `specs/desk-month/`.
        - [x] **R-3b-2c-2** **Done cycle 28** (merged 2cd2cb2; ADR-032 (p) + red-team 0017
              amendment, `tests/test_run_minds.py`, red-team 0017: 4 holes, all fixed).
              `POST /run/minds` under CONTROL_CLOCK: once, before any firm act or advance.
              The reader trusts ledger order and covers only agents registered after the
              declaration. **M1 closed** (scripted). Serves EC1, does not tick it (R-8).
      - [x] **B-049** **Done cycle 29** (merged d908dbe; ADR-034,
            `tests/test_world_withheld.py`). `EventOut` reads `run_started.world` and
            `run_minds_declared.minds` as `"withheld"` for every agent; the ledger keeps them.
      - [ ] **B-052** (cycle 29, low, with Truman) The ticker universe is still discoverable:
            an agent can probe `/price/<guess>` and tell 200 from 404 (audit c29 NOTE 5).
            Truman decides what a mind is told about its world; until then charters name it.
      - [ ] **B-050** (cycle 28, low, Era II) A declaration exempts an older agent's
            *registrations* (the registrar making the run's minds). An older management mind
            driven by a model could register agents after the declaration, and they would
            count as covered. Today the registrar is the operator's key. Decide this with
            B-045 (provisioning's own identity).
      - [ ] **B-051** (cycle 28, low) The smoke run checks the minds label with raw SQL (it
            imports no `app`), not with `run_minds()`, so the H4 rule is not exercised over
            the real 5-day run. Add an operator read (`fund-env run-minds`) and have the
            smoke call it.
      - [ ] **B-047** (cycle 27, low) A transcript keeps tool results as they came, so it can
            hold a minted key (`register_agent`). The CLI redacts its output. R-4's cassette
            must redact too, and replay must treat a redacted key as a divergence. Also decide
            whether `native` should redact at the source.
      - [ ] **B-048** (cycle 27, low) `FundClient` turns a non-JSON 2xx answer into a raw
            `ValueError` (`response.json()`), not a `FundAPIError`. A wrong process on the
            port would crash the command with a traceback instead of a refusal.
      - [ ] **B-045** (cycle 26, low, Era II) Management keeps `REGISTER_AGENTS`. A management
            mind could take a future spec's name first and so block that spec (it fails
            closed, `name_taken`). Decide with the `spawn_worker` / `generation_turnover`
            workflows: reserve spec names, or give provisioning its own identity.
      - [ ] **B-046** (cycle 26, low) The runtime's copy of physics' name fold is pinned on 16
            samples (audit c26 NOTE 3). Make it a property test over generated strings
            (hypothesis is not a dependency yet: a seeded random corpus is enough).
      - [ ] **B-043** (cycle 25, low) `get_messages`' description should say `ts` is physics'
            stamp and a payload's dates are the sender's claim (journal c25 Learned 2). Era II
            LLM agents will trust whichever one the tool tells them about.
      - [ ] **B-044** (cycle 25, low) `tool_failures` takes a `ValidationError` raised *inside*
            a tool body for the mind's bad arguments (audit c25 NOTE 4). No tool body builds a
            pydantic model today. If one ever does, classify by where the error was raised.
  - [ ] **R-3c** `daily_cycle` workflow.
- [ ] **R-4** **R-4b-1 done cycle 32** (ADR-038 + amendment (a), `runtime/replay.py`, `cassette.read`,
      `tests/test_cassette_replay.py`, red-team 0018). **R-4b-2a done cycle 33** (merged 016d53d,
      ADR-040: `fund-runtime replay`, the refusal law, `fund-env compare-ledgers`, smoke 21 → 32;
      closes c32 NOTE 4). **R-4b-2b next (not built):** cassette v2 (run parameters, spec digests,
      each wake's model, optional `tools_sha256`), c32 NOTE 5 (`key` can mislabel a surface change),
      a size cap on the reader, `replay --cassette OUT`. Old text for R-4b-2 follows (the CLI and
      comparison halves are done): `fund-runtime replay --cassette
      PATH --specs DIR` (CLI, ledger comparison end to end; only allowed ledger difference: the
      `run_minds_declared` payload scripted -> cassette); cassette v2 records run parameters
      (steps, days_per_step, max_tool_calls, workflow_input), each spec's digest and each wake's
      `model`; a cassette step in the smoke run; a replay setup error (contradiction,
      `unknown_tool`, `identity_mismatch`) should not read as `diverged:...:ended` (audit c32 NOTE 4);
      `key` can mislabel a surface change (NOTE 5); no size cap on the reader. Split cycle 31. **R-4a done cycle 31** **R-4a done cycle 31** (merged fba3b1c, ADR-037: `runtime/cassette.py`,
      `--cassette`, `WakeRecord.exchanges`; B-000i closed; B-047 decided: redact on the way out,
      hash the unredacted request). **R-4b next**, with these carry-overs from R-4a:
      the reader rejects duplicate JSON keys (`object_pairs_hook`); a changed tool surface is a
      "surface changed" divergence, a minted key a "key divergence"; add a cassette step to the
      smoke run; link hashes from events only as a separate physics slice with a red-team;
      optional `tools_sha256` per wake; no size cap on a cassette yet.
      Original text: Cassettes + replay (was B-010) + B-000i (gitignore first): record every exchange,
      replay into a fresh DB in the same world → identical ledger, $0; a miss is a recorded
      divergence. Reuses the ADR-030 comparison. **M2**. It
      serves EC2 but does not tick it (R-8). Run label `minds: replay`.
      **R-4a seed** (from the cycle-30 architect; not built yet):
      - The request hash is sha256 of the sorted, compact JSON of `request.model_dump(mode="json")`.
        Compute it in `native.wake` *before* `provider.complete`, because a mind could change
        its argument dicts.
      - Hash the unredacted request. A minted key then always diverges on replay (B-047).
      - Redact at write time, per string value and per object key, and count the redactions.
      - Each wake record gets `exchanges: (seq, request_sha256, usage)`.
      - The code goes in `runtime/cassette.py` with `CASSETTE_VERSION = 1`. Files are written
        with `open(path, "x")` and mode 0o600, and paths end `.cassette.json`.
      - `.gitignore` gets `*.cassette.json` and `experiments/*/runs/`.
- [ ] **R-5** Agent-level gates. **EC3, EC5, EC6 / M3.** Split cycle 30 (cycle-30 retrospective:
      tick-blindness).
  - [x] **R-5a** **Done cycle 30** (ADR-036, `tests/test_runtime_lockstep.py` "Era I exit
        criteria"): 8 end-to-end tests, no production change; **EC3, EC5, EC6 ticked**.
  - [ ] **B-054** (cycle 33 audit WARN, low-medium) A HALT landing between two minds' wakes ends
        the run `refused`/`wake_refused:<id>:halted`, and a HALT before `declare_minds` ends
        `refused:minds_refused:<code>`; both should read `halted` (Art. 5 holds either way: nothing
        wakes, the clock does not move). Touches the halted branch → needs a red-team. Do it with B-053.
  - [ ] **B-053** (cycle 30, medium for honest records) `fund-runtime backtest` provisions agents
        and declares `/run/minds` *before* any wake gate refuses. Under a null cap, a spending
        spec therefore leaves registered agents and a `model` label on a run in which nothing
        woke. Fix: a pre-gate in `runtime/cli.py::_conduct` using `decide_wake_under` (one law
        read) before provisioning. This is Runtime gate code, so it needs a red-team. B-023 (halt
        observability) if cheap.
- [ ] **R-6** Metering v1 on a fake provisioner (was B-013) + B-000k (firm-level costs) +
      B-000n (cost-report rate law) + B-022 (secret scan, before any key exists): per-agent keys,
      cost-sync posts system-reported costs; system cost overrides self-report. **EC4 / M4.** Split c34:
  - [x] **R-6a** **Done cycle 34** (merged 240b607, ADR-041, red-team 0019: 1 low hole, fixed): physics
        ledger + endpoint + MCP tool + metrics override + `FakeProvisioner`/`sync_costs`. Ticks nothing.
  - [ ] **R-6b** (after B-053/B-054): the gate lets a `metered` provider wake under a numeric cap; `provision`
        mints one key per agent (limit ≤ `MAX_METERED_USD_MICROS`, total ≤ cap); `FakeMeteredProvider`
        charges the `FakeProvisioner`; sync after the last step only; `compare-ledgers` handles the
        trailing `cost_metered` block by type (own ADR; never widen the law); fail loudly on a 422 label;
        EC4 end-to-end test + tick. Red-team (gate). Plus: expose reader `conflicts`/`malformed` (c34
        WARN 3); `record_metered_usage` scans all events per post (O(n²), c34 NOTE) — filter by key.
        B-000k, B-000n, B-022 stay parked (B-022 before any real key).
- [ ] **R-7** `openclaw` adapter + static conformance (was B-012, B-012a, B-012b, B-023s seal
      keys, B-000l): `firm` profile only, backup first, live probes skipped while cap is null.
      **EC7 (static half) / M5.** Before it: re-read `08_OPENCLAW.md` §1 (rule zero).
- [ ] **R-8** The first real-model month + its replay (was B-015). **Needs Q-0001 (cap)** and the
      physics-hole gate below closed or accepted. **EC1 + EC2 with real minds, EC7 live / M6.**
- Parked until a Runtime slice needs it: B-037b (re-run driver; R-4 replay may subsume it),
  B-037c (lived worlds; Era III out-of-sample), B-006 meetings/allocations (Era II), B-007 world
  events (with R-5 if halt events need it), B-008 Truman v1 pack, B-014 two-pod chat (with R-7).

## Physics bugs (Art. 8 — Builder's bugs; priority 2, same tier as B-002/B-003 — ADR-021)
**Gate:** every open hole below is fixed, or accepted by an ADR with its reason, before any
**spending** mind wakes (ADR-032 (8): before R-7's live probes and before R-8; scripted minds in
R-1…R-6 may run with holes open — they are code, not subjects). Order inside the
tier: B-002 + B-003 first, B-000d with or before B-016 (both touch `append_event`), B-000e with
B-018, the rest when cheap or blocking.
Each red-team hole has a strict-xfail test in `tests/test_redteam_000N.py`; fix = remove the marker.
Open strict xfails: 8 (0001: payload size ×2, message content, system squat, MCP path; 0004: fee;
0009: cross-process OMS_LOCK ×2 = B-036).
- [ ] **B-025** (low, not agent-reachable) **Feed half fixed cycle 16** (quotes: the base refuses
      non-finite / non-positive → `price_unavailable`). Left: non-finite *bar* values, `config.yaml`
      bounds, sweep per-order isolation. Original: Non-finite or absurd prices from the world: a
      NaN/inf provider price (yfinance can) or `config.yaml` value (`fee_rate`, `static_prices`)
      → `append_event` raises → POST /orders 500; in the background sweep one such fill rolls back
      **every pod's fills that tick**, every tick (`app/oms/monitor.py`). Fix: providers refuse
      non-finite prices (→ clean `price_unavailable` rejection); settings `allow_inf_nan=False` +
      upper bounds; sweep isolates per-order failures. Red-team 0004 xfail
      `test_hole_non_finite_feed_price_is_a_500`. With B-005/B-008.
- [ ] **B-040** (low, human-only path, cycle 21 claim check + red-team 0012 H3) Physics' halt
      check `app/registry/halt.py: HALT_FILE.exists()` answers "not halted" in three cases that
      the Runtime's reader treats as halted:
      - a dangling symlink at HALT;
      - `governance` is a file (ENOTDIR);
      - `governance/` is missing (a moved `REPO_ROOT`).

      A permission error there raises, which becomes a 500 and is closed in effect. Fix: port
      `runtime.governance._halted`'s rule ("the directory is there and the file is not" → running).
      Each case gets a test in `tests/test_halt.py`.
- [ ] **B-039** (gate item, cycle-20 retrospective, IDEAS c16) Information-shape test: every
      agent-reachable route answers identically in two worlds that agree up to `now` and differ
      after it (needs a synthetic world with a branch day). Before any spending mind wakes.
- [ ] **B-026** (low) Fee rounds to cents per order → any order under $5 notional pays $0.00;
      splitting a trade dodges fees; 5e-324-share orders fill. Fix: round fee up (min $0.01/fill)
      and/or a minimum order notional — an honest-measurement law (cost-adjusted ranking). Red-team
      0004 xfail `test_hole_small_orders_pay_no_fee`.
- [ ] **B-027** (low) MCP tool int args (`order_id`, `task_id`, ids, cursors) carry no `ge`/`le`;
      mirror `MAX_ID` from `app/limits.py` so client and physics agree (re-audit note, cycle 12).
      Also `fund-pod --pod-id` / `--delta` unbounded in the CLI (operator-only; ledger refuses
      non-finite).
- [ ] **B-000e** Message `body` + `structured_payload` on the `message_sent` ledger event, so the
      messages table is rebuildable (CLAUDE.md: every state change is an event). With B-018.
- [ ] **B-019** (low) `POST /agents/register` with a missing `pod_id` → 500 (FK error unhandled);
      PM without pod accepted (can never trade). → 404/422. SURVEY §4a.6, probe P5/P6.
- [ ] **B-000n** (low) Cost-report rate is unbounded per agent (spam inflates rows; token totals
      lose exactness past ~9e7 max-size reports). Decide on a per-agent rate law. With B-013.
- [x] **B-000f** 'system' identity looked up by role/reserved name — **done cycle 23** (ADR-033;
      the 0001 xfail is a guard).
- [x] **B-041** Runtime key rotation + startup squat check — **done cycle 24** (`fund-env
      rotate-runtime-key`, `reserved_identity_problems` at server/CLI start, ADR-033 (b)).
- [ ] **B-042** (low, in-sim, red-team 0014 + re-audit NOTE 3) Directory honesty for firm names:
      uniqueness is on the exact string, so `pm-alpha` + an invisible character passes for a
      colleague, and a name that is only blanks (U+3164…) is accepted. Make uniqueness and
      non-emptiness use `_name_key`. A one-off check of existing names is needed first.
- [ ] **B-000g** Byte-size caps on `structured_payload` and task `outcome` (depth is capped since
      cycle 12, size is not — 2 xfails in red-team 0001).
- [x] **B-000h** MCP client: URL-escape path params — **done cycle 22** (`mcp_server.tools._segment`,
      red-team 0013 H1; the 0001 xfail is a guard).
- [ ] **B-000b** A test that proves `OMS_LOCK` is load-bearing (F-0001), e.g. race injected between
      cash read and write, or run against a row-locking backend; or document the lock as defence-in-depth.
- [ ] **B-000j** Decide whether `state/loop_status.json` is tracked (runner state) — auditor note.
- [x] **B-000c** (high) Token-sum overflow DoS — cycle 2: per-report cap 1e8 + `TOTAL` sum (ADR-018).
- [x] **B-000d** Portable JSON — cycle 12 (ADR-024): bounded floats, walked free JSON (finite,
      ints ≤ 2**53−1, depth ≤ 32), NaN-safe 422, `append_event` refuses; red-team 0004: 4 holes fixed.
- [x] **B-000m** Int ids ≥ 2⁶³ → 500 — cycle 12: every agent-supplied id is 1..2**53−1 (ADR-024).

## Era I — The Desk (current; order per ADR-021: seal → time → clock → the rest)
- [x] **B-002** Dependency-law test — cycle 10 (ADR-022; `app/limits.py`; 2 detectors).
- [x] **B-003** Halt in physics — cycle 11 (ADR-023; 423 + `halt_refused`, route-template path;
      monitor checks under `OMS_LOCK`; `GET /halt` + `get_halt`; red-team 0003: 2 holes fixed).
- [ ] **B-023** (low) Halt observability: halt start/end are not ledger events, so the ledger
      cannot explain why fills paused. Option: the App appends `halt_observed` / `halt_lifted`
      the first time a request/sweep sees the file change state. With B-007 (world events).
- [ ] **B-024** (low) `test_held_monitor_sweep_queued_on_lock_does_not_fill_after_halt` waits a
      fixed 1 s; give the monitor a test hook (or a lock-acquired event) so it needn't.
- [x] **B-016** Replay order = live order — cycle 13 (ADR-025): monotonic ts held in the INSERT,
      every replay folds by id, sell beyond/without position raises; red-team 0005: 2 holes fixed.
- [ ] **B-028** (low) `Message.ts`, `Cost.ts`, `Task.started_at/ended_at` take the raw clock,
      not their event's held stamp (red-team 0005; orders fixed cycle 13). Copy `event.ts` like
      `fund_pod`/OMS do. With B-000e (message event carries body).
- [ ] **B-029** (low, operator-only) A forward clock step is permanent under ADR-025 (f): guard
      (refuse or log) a clock far ahead of the ledger floor. Live runs only since ADR-027 (a
      backtest's steps are bounded and recorded).
- [ ] **B-030** (low) `GET /events` pages only by `since` (ts ≥) with cap 1000: a long held
      stretch gives >1000 events on one stamp and management cannot page past them → add an
      id cursor (`after_id`). Also: market price + `now` read before `OMS_LOCK`, so an order
      queued behind a sweep fills at a quote one sweep stale (red-team 0005 notes) — fixed for
      non-live clocks in cycle 15 (re-price under the lock); live keeps the gap. With B-005.
- [x] **B-020** Clock vs agents — cycle 14 (ADR-026): every agent reads `/clock`; `now` is the
      ledger's now (`ledger_now`); control stays closed. Red-team 0006: 1 low hole fixed.
- [x] **B-004a** Backtest clock — cycle 15 (ADR-027): a run is a database (`start-backtest`,
      `run_started`), `POST /clock/advance` (`CONTROL_CLOCK`), sweep on advance, restart resume,
      `append_event` refuses a wrong-run clock. Red-team 0007: 3 medium holes fixed.
- [x] **B-005** Look-ahead guard — cycle 16 (ADR-028 + amendment): sealed base entries, bars by
      end, future/non-finite quotes refused, past quote = latest ended 1d/1h bar, window clipped,
      uniform 404, strict 60 s margin; `LOOK_AHEAD_GUARD = True`. Red-team 0008: 5 holes fixed.
- [x] **B-004b** One now — cycle 17 (ADR-029 + amendment): quotes, OHLCV defaults, portfolio,
      metrics, leaderboard, order pricing and the sweep read `ledger_now`; one read per report;
      advance commits before the clock moves; AST law counts every raw time read per file.
      Red-team 0009: 4 holes + 8 detector dodges fixed, 1 → B-036.
- [x] **B-004c** Phase 3 probe — cycle 18 (ADR-030 + amendment): keyed `SyntheticProvider`
      (HMAC, ≥128-bit env-only key, no default; config.yaml carrying it refuses to load); scripted
      pod, 31 days through HTTP in ~0.55 s, twice to the same ledger/curve/book/metrics, another
      world differs. Red-team 0010: 1 high hole (seed from volumes) fixed, 6 held.
- [x] **B-037a** A run records its world — cycle 19 (ADR-031 + amendment): `run_started.world`
      (synthetic: law, origin, drift, vol, symbols, 128-bit HMAC fingerprint; static: its table);
      `install_run_clock` refuses another world. Red-team 0011: 1 low hole fixed, 8 held.
- [ ] **B-037b** (parked — see Runtime section) `fund-env backtest` driver: re-run a ledger's world from the
      operator's key file (fingerprint must match before anything runs) and diff the two ledgers —
      the probe as an operator tool. Keep red-team 0010/0011 held tests green.
- [ ] **B-037c** Which agents have lived which worlds (re-running a lived world is not
      out-of-sample): a per-agent world history readable by management / experiments.
- [ ] **B-038** (low, operator-only, red-team 0011 + re-audit notes) A format-valid zero-entropy
      `synthetic_key` (`"00"*16`) is accepted — refuse keys with obviously low entropy (all-same
      byte, short period); a malformed `synthetic_symbols` ticker raises `InvalidRequestError`
      through the CLI as a traceback (exits non-zero, writes nothing) — validate in config.
- [ ] **B-036** (low) `OMS_LOCK` is per-process: a second process (operator `check-orders`, a
      second server) that commits an advance between the in-lock read of now and the fill INSERT
      prices a fill at the old now and stamps it at the new; `build_portfolio`'s positions+cash
      read has the same cross-process gap. 2 strict xfails in `tests/test_redteam_0009.py`. Fix:
      after the flush compare `event.ts` with the priced now and roll back on mismatch, or
      `BEGIN IMMEDIATE` before the read. With B-000b. Also (re-audit): `/portfolio` and metrics now
      wait for `OMS_LOCK` behind a sweep's network pricing — watch latency once live sweeps run.
- [ ] **B-035** (low) Market-data follow-ups (re-audit notes, cycle 16): (a) a non-empty error on
      the 1h leg of a past quote fails the whole quote (502) even when the daily bar exists. Kept
      fail-safe on purpose (falling back would reopen the stale-quote arbitrage while 1h is flaky);
      revisit if Yahoo raises on >730-day hourly requests (would silently stop old backtests);
      (b) two history fetches per past quote and an exact-`as_of` cache → Yahoo request volume at
      minute-step backtests: a per-run bar cache keyed by (symbol, interval, day) once B-004b's
      probe measures it; (c) `bar_end` adds 24 h in UTC, so on DST fall-back a NY daily bar ends
      23:00 local (still after the close: under-conservative by 1 h, not a leak); (d) clip uses
      `as_of.date()` in `as_of`'s tz (UTC today); (e) live quote stamp hides the feed's delay;
      (f) `DailyCloseCache` dates Asian closes by UTC day (mis-dated metric, not a leak — red-team).
- [x] **B-032** **Done cycle 23** (R-3a, ADR-033). Clock control belongs to the Runtime, not to a
      firm agent: `CONTROL_CLOCK` moved from `management` to the `runtime` identity.
- [ ] **B-033** (low, operator-only) ~~`advance` moves the clock before its commit~~ fixed cycle 17
      (ledger first, clock second — red-team 0009). Left: two concurrent `start-backtest` on one empty file, or a
      stale live write between its emptiness check and `run_started` (run check and insert are two
      statements). Fix: one statement, or a file lock for `start-backtest`. Mode check is a string
      (`!= "backtest"`) — an explicit allowed set if a third clock type appears.
- [ ] **B-034** (low) Operator CLI commands ignore `governance/HALT` (pre-existing; `start-backtest`
      copies it). Decide: the Human's own hands (ADR-023 says not gated) vs a Runtime script
      calling the CLI — if the Runtime ever does, gate it.
- [ ] **B-031** (low) `mode` on `/clock` lets agents tell live from backtest (ADR-026 accepts it).
      If an experiment needs agents blind to the mode, withhold it by role in one place, with the
      Runtime/Truman controlling what an agent perceives (auditor note, cycle 14).
- [ ] **B-021** `GET /tasks` + `GET /costs` (own; cross-pod for management) + MCP tools —
      `list_tasks`/`list_costs` exist unused; a restarted agent cannot find its open task ids.
- [ ] **B-017** Sharpe annualisation: equity curve is per calendar day, `annualise` uses √252 →
      reported annual Sharpe ×0.845 ≈ √(5/7) of the true value (P8, synthetic series). Prefer
      trading-day points (√365 on calendar points is still ≈1.017× off); `sharpe_daily` must say
      which day it means. Honest-measurement bug (Art. 9).
- [ ] **B-018** Decide rebuild scope: pod creation + `system` agent write no event (P2);
      `pods.current_allocation`, `allocations`, `orders`, `messages`, `costs`, `tasks`, `agents`
      are not rebuilt. ADR: which tables are derived, which are records; before Era II generations.
      `conftest.make_pod` inserts pods directly with the system clock — update it with the ADR.
- [ ] **B-006** TRD Phase 3c: `POST /allocations`, meeting schedule + package endpoints.
      `fund_pod` (to be reused) validates nothing: add finite `delta`, no withdrawal beyond cash.
- [ ] **B-007** World events table + `system` announcements (law changes, Truman events).
- [ ] **B-008** Truman v1: local cache of real daily history, prices-only pack, one scripted
      scenario, served via `MarketDataProvider`; pack hashing. Must not reuse yfinance's
      `_fetch_price` path (SURVEY §4a.3).
- [x] **B-000i** **Done cycle 31** (ADR-037): `*.cassette.json` and `experiments/*/runs/` ignored.
- [ ] **B-009** → R-1 + R-2. Runtime skeleton (`runtime/`, `uv run fund-runtime`): AgentSpec,
      scheduler on the App clock, halt + cap checks, fake LLM provider for tests.
- [ ] **B-010** → R-4. Runtime: cassette recording + replay mode.
- [ ] **B-011** → R-3. Runtime: `daily_cycle` and `backtest` workflows.
- [ ] **B-022** Secret-scan test: no tracked file contains an `fk_…` key, an OpenRouter
      `sk-or-…` key or another credential pattern (SURVEY §4b.1). Before any firm agent holds a key
      (i.e. before B-012/B-013). Reuse `survey_probe_openclaw.SECRET_VALUE` + filename check
      (cycle 7: a pattern list without `xai-` missed a real key file). Auditor notes (cycle 7):
      the filename heuristic flags `keynote.md`-style names (refine before reusing); URL
      redaction misses `user:pass@`; `relative_to(state)` crashes for a workspace outside the
      state dir.
- [ ] **B-012** → R-7. `openclaw` adapter to the `08_OPENCLAW.md` standard: render config + workspace
      (bootstrap files the installed version supports) from AgentSpec, own agentDir + local auth
      profile + metered key, `fund-env-mcp` per agent key via env, deny-by-default tools, no
      bindings, `firm-` namespace; OCT POC charters → AgentSpec templates.
      Cycle 7 (VERSION_NOTES): target the `firm` profile (ADR-019); MCP servers are global only
      → one named server per agent + allowlist glob of its own server; key via SecretRef, not
      a literal; check which bootstrap files 2026.5.12 loads (`TOOLS.md`/`HEARTBEAT.md`?).
      Backup step: `openclaw backup` (exists in 2026.5.12) or tar under `umask 077` — the
      cycle-7 tarball came out 644 (Q-0004). Plan `doctor` (conformance check 5): firm profile only.
- [ ] **B-023s** → R-7. *(id collision found cycle 20: two items were both B-023; this one,
      the seal keys, is B-023s from now on.)* Render every seal key explicitly, never rely on a default (newer OpenClaw
      loosens them): `tools.web.*` off, `tools.sessions.visibility: self`,
      `tools.agentToAgent.enabled: false`, `tools.profile: minimal`, per-agent deny list,
      `subagents.allowAgents: []`. Conformance check reads `openclaw config schema` of the
      installed version and fails on any seal key missing from the rendered config.
- [ ] **B-012a** Adapter written against mcp 2.x (`is_error`, not `isError`); Runtime stops
      `fund-env serve` with SIGINT (rc 0) — SURVEY §1 findings.
- [ ] **B-012b** Conformance suite: `fund-runtime openclaw doctor` static checks + live probes
      (skipped while firm cap is null); integration tests skip when OpenClaw is absent.
- [ ] **B-000l** MCP API base URL must be loopback (conformance check for Era I).
- [ ] **B-013** → R-6. Metering v1: provisioned per-agent keys (fake provider in tests), cost-sync job →
      system-reported costs; system cost overrides self-report in metrics.
- [ ] **B-000k** Costs from pod-less agents (management) appear on no leaderboard → firm-level spend.
      Before B-015 (every LLM dollar attributed — Era I exit criterion).
- [ ] **B-014** Verify "chat restricted to central pod" with a two-pod test. Cycle 7 lead:
      cross-agent `sessions_spawn` needs `subagents.allowAgents` (default same-agent only).
- [ ] **B-015** → R-8. Era I milestone run: 1 pod, 1-month backtest < 10 min, replay identical.
      Needs a firm cap → ask in QUESTIONS when reached.

## Residue of Era ½ (closed cycle 9, ADR-021)
- [ ] **S-004b** Cleanup, the deletions — **blocked on P-0002** (headless `git rm` needs
      approval): `git rm test_api.py`; `git rm --cached .vscode/settings.json` + ignore `.vscode/`;
      local empty `ui/` and `.DS_Store` ×3 (untracked, ignored — harmless). Do not route around
      the denial. Run it the cycle P-0002 is answered.
- [ ] **S-001r** `git --version`, `claude --version`, origin visibility — need loop-mode
      permission prompts; capture in an interactive session or when allowed.
- Done: S-001 (c3), S-002 (c1; .gitignore gap → B-000i), S-003a (c4), S-003b (c5),
  S-004a (c6; keep `legacy/`), S-005 (c7; `doctor` deliberately not run), S-006 (c8),
  S-007 (c9: SURVEY §10, exit criteria ticked, this reorder). Details: JOURNAL + git.

## Era ∞ (≤ 1 cycle in 5 during the Launch Pad)
- [x] **X-006** (retrospective c10) Counter-example check before the auditor. Measured at the
      cycle-20 retrospective: BLOCK rate cycles 11–19 = 2/9 (c11, c12) vs 5/10 in cycles 1–10.
      Written into `protocol/CYCLE.md` step 5 (cycle 20) with its three questions (claims, what an
      unprotected file/env var can change, checks inside their lock) + "new laws audit old tests".
      Keep the metric: BLOCK rate over cycles 21–30; revert if it rises above 50% (06 §8).
- [x] **X-004** Run `scripts/smoke_run.py` in the verify gate — written into `protocol/CYCLE.md`
      step 5 (cycle 20; P-0003 made the protocol Builder-owned). Metric: smoke failures caught
      that the suite missed, cycles 21–30 (expected 0 — it is a tripwire).
- [ ] **X-008** (retrospective c20) Size check at step 2: cycles 11–19 averaged ~45 min and 3 of 9
      were interrupted (13, 16, 18 resumed via X-007). If a slice needs code + red-team + ADR, plan
      the red-team fix budget up front or split before building. Metric: interrupted cycles 21–30.
- [ ] **X-005** Capability probe for the Builder's own permissions (IDEAS cycle 6) — plan units
      against the headless allow list instead of hitting it.
- [ ] **X-001** `state/METRICS.md` summariser script (success rate, turns, durations).
- [ ] **X-002** Skill: `.claude/skills/new-endpoint/` — checklist for schema + permission +
      MCP tool + tests + docs, from the repo's existing patterns.
- [ ] **X-003** Suite-stability + mutation check: run the suite N× and flag flaky tests; for each
      invariant-guarding test, a recorded mutant that must make it fail (F-0001).
