# Headlines and company data, handed by role: the made-up world writes dated headlines and quarterly reports (a few planted causes among the noise), physics serves them only on their day and only to a mind given the right, so an analyst can know what its PM does not

## How I understand it
Until now every mind sees the same thing: prices. So a PM offered analysts works alone, and a
manager finds no pod that knows something another does not. This slice gives the world news:
- **The world writes it.** The made-up market's recipe gains a news block: each day a few noise
  headlines (from templates, by the seed), a quarterly report per company (revenue, earnings
  against what was expected, guidance), and a few *planted causes*: a fraud headline on one
  ticker, an earnings miss on another. Each cause moves its ticker's prices from its day on, as
  the recipe says; noise moves nothing. No LLM writes any of it: it is physics.
- **Never early.** An item dated tomorrow does not exist today (the same look-ahead law as
  prices). No endpoint ever says which item is a cause or what it will do: the recipe is the
  world and stays with the operator.
- **Handed by role.** Everyone reads prices. Headlines and company reports are rights: the
  operator grants them when it registers a mind, or a PM asks for an analyst with a package the
  team law lists (one the PM itself may lack). A mind without the right is refused by name
  (403, logged), through its tool and in its morning package.
- **Versioned packages.** Beside `prices-v1`: `headlines-v1`, `company-v1`, `everything-v1`.
  Each is built through the mind's own key, so what a mind gets is what physics lets it read.
Whether a PM acts on what only its analyst read is the finding (the first behaviour test).

## What done looks like
`uv run python acceptance/data_packages.py` ($0, offline):
- A (scripted, through the API): a made-up world with noise headlines and reports and two
  planted causes; an entitled analyst reads the fraud headline on its day and not the day before
  (the 'yes' and 'no' of the look-ahead law); its PM, without the right, is refused by name both
  through the tool and in its morning package; a PM asks for an analyst with headlines and gets
  it, a package outside the law's list is refused; the causes move their tickers' later prices
  as the recipe says and a noise headline moves nothing (from the bars alone); everything-v1 is
  exactly the union; no answer carries an effect; rebuild gives the same rights.
- B0: the same hosted through the Runtime with the real run's very command, replay IDENTICAL.
- B (recorded): real Haiku minds, a PM holding the fraud ticker (prices only) and its analyst
  (headlines); physics' answers checked; replay for $0; whether the PM cut is the finding.

## Plan
1. `app/marketdata/made_up.py`: an optional `news` block (noise per day, reports, causes); a
   recipe without it gives byte-identical bars, so every older world is unchanged.
2. `app/marketdata/news.py`: the news desk (items from the recipe, served at the world's now).
3. Rights in `app/registry/permissions.py`: `data_rights_granted` events, folded from the
   ledger; granted by the operator's registrar at registration, or by a team place's fill.
4. Team law gains `data` (the packages a PM may ask for); the request names an optional package.
5. API `app/api/data.py` (headlines, company reports, my rights) + MCP tools, named-only.
6. `runtime/packages.py`: the three new packages; the spec's `data` passed at registration.
7. Demo A, then B0, red-team, auditor, the real run B, merge.
Left out: data that costs money, the manager reading news, real-history news, LLM-written text.

## Risk
Market data, permissions and the seal: red-team + auditor before the paid real run and merge.

## Progress
- cycle 68: physics (news in the recipe, served under the look-ahead guard, rights by role,
  the team's data, the endpoints, tools and three packages), demo parts A and B0; red-team 4
  holes fixed (news now out at its day's close, with its bar; a miss never hides an earlier
  report); real run B recorded ($0.078: the PM cut K03 a day after its analyst's warning);
  auditor: one block (the recording not in the replay suite) fixed, then PASS. Merged.
