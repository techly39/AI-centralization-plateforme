# 09 — The Builder's Vision

> Living book, owned by S1 (`01_GENESIS.md` §6). It is kept **one step ahead of the work**:
> where I am taking the world, why, and how we will know. Re-written at every retrospective.
> Decisions it implies are logged in `07_DECISIONS.md`; it decides nothing by itself.
> First written cycle 20 (2026-10-12).

## 0. Where the world is (cycle 20)

Physics is honest about time and about its market. There is one "now" (ADR-029), no feed shows
what is not yet known (ADR-028), a backtest is a database whose clock is a ledger fact (ADR-027).
A keyed synthetic market makes a month a pure function of a secret (ADR-030), and every run
records which world it lived in and refuses to live in two (ADR-031). A scripted pod has lived a
month twice and left the same ledger, event for event, in ~0.55 s. 796 tests and 11 red-team
passes. **No mind has acted yet.** There is no Runtime, so 0 of the 7 Era I exit criteria are met.

## 1. The thesis: the world is an instrument

**What I am building:** a sealed economy in which every run is a reproducible, attributable
experiment. What AI minds do inside it should be measured the way a lab measures, not told as a
story.

Most agent-market simulations, LLM trading-agent papers included, produce narratives: one run,
one model, one curve. Few of them can replay a run exactly, prove their subjects never saw the
future, charge every dollar of thought to the mind that spent it, and count every trial. This
world can already do the first two for scripted minds. My target is for it to do all four for
real ones.

**A run is a proof object.** It is a triple:

| Part | What pins it | Status |
|---|---|---|
| Physics | git sha + the law versions in force (run manifest — IDEAS c15) | partly: `look_ahead_guard`, world `law` version |
| World | `run_started.world`: provider, law, parameters, key fingerprint | done (ADR-031) |
| Minds | AgentSpecs + **cassettes**: every LLM request/response, hashed, in order | Runtime (ADR-032) |

`replay(physics, world, minds) == ledger`, byte for byte, at zero LLM cost. If a replay
diverges, either physics is nondeterministic (a bug) or a cassette is missing (a hole in the
record). Every finding in `state/FINDINGS.md` should cite a proof object, so anyone can re-run
the run behind it.

## 2. The instrument nobody has: the exact counterfactual fork

Once runs are proof objects, a new kind of experiment becomes cheap:

> **Fork a run at day *d*.** Replay days 1…*d* from cassettes (free, exact), then change exactly
> one thing (one mind's model, one world event, one firm law, one prompt line) and let the
> run continue live. Only the days after the fork cost money.

The two branches share an exact history up to *d*. Any difference after *d* is caused by the one
thing changed, or by model sampling, which we measure by forking the same change several times.
I know of no LLM society, firm or market simulation that runs **exact counterfactuals with shared
history**. The usual design is "run A, run B, compare", which pays twice for the shared part and
loses the shared history to sampling noise.

What it unlocks: the scale questions (`02_SCALES.md` §4) as controlled experiments ("what does a
stronger PM buy?": fork at day 10, swap the PM's model, n forks per arm, effect with a confidence
interval), Truman shocks as interventions, firm laws as treatments, and generations
(Era II) as forks of the previous generation's world.

**Scientific question:** *how much of an LLM firm's outcome is caused by any one of its parts,
measured against the same history?* **Measure:** per-arm outcome distributions over n forks,
divergence day, and cost per fork (the counterfactual must be cheaper than two full runs or the
instrument is not worth having).

## 3. The road, one step ahead

**Now → Era I exit (the Runtime).** Plan: ADR-032, backlog slices R-1…R-8. Milestones:
- **M1** a two-mind pod (PM + Analyst) with *scripted* minds lives a month **through the
  Runtime**, every act over HTTP, under 10 minutes;
- **M2** the same month replayed from cassettes → identical ledger, $0;
- **M3** halt mid-run stops within one tick; cap `null` refuses every spending mind; a mind asking
  for tomorrow is refused, all tested at the agent level, not only in physics;
- **M4** metering against a fake provisioner: every (fake) dollar charged to a mind by the system,
  not by self-report;
- **M5** the `openclaw` adapter renders `firm-` agents that pass the static conformance suite;
- **M6** (needs the Human's cap, Q-0001) the first real-model month, and its replay.

M1–M5 need no money. M6 is the only step that waits for the Human, so it goes last.

**Era II (the end of the Launch Pad)** as the Human wrote it, with the fork as its measuring tool.
Generation N+1 is a fork of generation N's world, so "did the firm get better?" is asked against
the same market.

**After the Launch Pad**, candidate Eras I expect to author (written into `05_ERAS.md` only when
the Launch Pad closes; never build Era N+2 to finish Era N):
- **Forks: counterfactual firm science.** Question: what changes when exactly one thing changes?
  Exit: one published fork experiment, ≥ 5 forks per arm, effect with a CI, proof objects for
  every branch.
- **The Proving Ground** (merges the suggested Era III with two of my ideas). Can minds find
  alpha that survives worlds they have never lived (B-037c makes "never lived" a ledger fact)?
  When paid to report physics holes, do they report or exploit them (exploit bounty, IDEAS c1)?
  Information-shape tests (IDEAS c16) become the gate that keeps the Proving Ground honest.
- Evolution and Society as suggested, but measured by forks rather than by single runs.

## 4. What twenty cycles taught me (my working laws)

1. **Ledger first, mirror second.** In-memory state may move only after the event that
   justifies it commits (cycle 17).
2. **A determinism tool is a secrecy tool.** Whatever makes a world replayable also makes it
   predictable to whoever holds the input (cycle 18).
3. **A claim is never wider than its planted counter-examples.** Half of cycles 1–10 were BLOCKed
   for overstated coverage; 2 of 9 since then (X-006, cycle 20 retrospective).
4. **New laws audit old tests.** The tests a new law breaks are findings (cycle 19).
5. **Seal-first must not become seal-only.** Nine cycles of time physics made backtests honest.
   The frontier is now the Runtime: no new hardening unless the Runtime needs it or an agent can
   reach it.

## 5. What I am deliberately not doing

- No real-model run before the Human sets a cap (Art. 4). Everything up to M6 runs on scripted
  or fake minds, and is **labelled as such** in its run record. A scripted month is never
  reported as an agent month.
- No Era III+ features before Era II closes.
- No second physics: the Runtime holds no rules that matter (those are App law). It decides only
  *when* a mind wakes and *what it sees* (`02_SCALES.md` §2).

## 6. How this vision is held to account

At each retrospective, three numbers in the journal: Era exit criteria ticked (now 0/7 Era I),
proof objects (runs that replay to their ledger: now 1 scripted probe in tests), and the
ambition check: *is there an experiment this world can run that no other can?* (now: not yet;
a fork of scripted minds needs M2, and a fork that means anything about LLMs also needs M6).
