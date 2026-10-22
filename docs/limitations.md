# Scope and limitations

What the numbers are good for, how to read them, and where they stop.

## What it's for

A player reading a Magic format's tournament metagame: what's winning, what the
matchups look like, which cards the field is adopting. And the same player
reviewing their own games: which decisions decided them, and which habits keep
turning up. Personal, non-commercial use. Nothing here should drive a
decision bigger than which deck to register on Saturday.

## The conditions the numbers hold for

| | In scope | Out of scope |
|---|---|---|
| Format | Standard, built and tested on it. Other constructed formats run through the same code with far less data behind them. | Limited (draft, sealed) |
| Sources | melee.gg events with published decklists; MTGO Challenge and 5-0 league lists; mtgtop8 meta share; Scryfall for card legality | Arena ladder win rates, except the player's own games in `vod-review` |
| Time | One format era: from the latest set release or ban to now | Comparisons across a ban or a rotation |

Outside those conditions the commands still run. The numbers stop meaning what the
docs say they mean.

## How to read a win rate

**Win rate is wins over decided games.** Draws are excluded from it; byes and
rows missing a deck name are dropped before counting. Match-win %, printed beside
it, counts a draw as half a win.

**Every win rate carries a 95% range** (a Wilson score interval). If the range
straddles 50%, this sample can't tell the deck from a coin flip. Ten decided games
at 60% runs from 31% to 83%, and that's what most single-matchup cells look like
inside one era.

**Cells under 10 decided games aren't printed**, and the archetype notes mark
anything under 20 as a small sample.

The range is optimistic, for three reasons worth knowing:

- **Matches aren't independent.** One player plays several rounds, so a strong
  pilot lifts their deck's number for every round they play. Swiss pairing then
  matches records against similar records.
- **Mirror matches count.** When both players are on the same deck, that deck gets
  one win and one loss, which pulls every popular deck's overall rate toward 50%.
  The head-to-head tables leave the mirror out; the overall rate doesn't yet.
- **Only published lists are in the sample.** Events without decklists can't be
  labelled, and 1,094 pairing seats in the pool as of 2026-10-12 had no deck URL
  at all.

**MTGO data never feeds a win rate.** League dumps publish 5-0 decks only and
Challenges publish the top finishers, so those lists say what's being played and
adopted. They can't say what loses. Win rates and matchups come from melee.gg
pairings, where both sides of every match are recorded.

## Known limits

**Scrapers break when sites change.** melee.gg and MTGO render with JavaScript and
redesign their pages from time to time. When that happens the scrapers return
fewer rows or none. The validator's report and the coverage sidecar show the drop,
but nothing alerts on it.

**The win-rate reports trust the pool they're given.** `winrate-analysis` and
`matchup-matrix` warn when an event has no verdict, but they don't check that the
pool was validated for the current era. `build-baseline` does, and refuses. Until
the reports do the same, the era check is the skill's job.

**Melee results carry no event date.** The era split is enforced at discovery and
by the validator's card checks. See [data quality](data-quality.md#gaps).

**The classifier hasn't been tested on held-out data.** Its 93% agreement figure
was measured on the same decks its thresholds were tuned on. See
[the classifier](classifier.md#how-well-it-works).

**The agent layer is held to its rules by instructions.** The skills tell Claude
which command answers which question and forbid quoting a number without checking
the era and the pool first. Nothing in code stops a model from writing a number it
didn't get from a command, and there are no automated evaluations of the skills'
behaviour yet. The tests check the skill files' structure only.

**Scraping etiquette stops at pacing.** The browser scrapers pause between
page actions and the Scryfall client backs off on a 429, but nothing reads
robots.txt or caps requests per minute. Scraped data stays on the machine that
scraped it: `.gitignore` keeps it out of the repo and the plugin bundle is built
from an allow-list.

**The play profile is one player's evidence.** A habit needs 3 occurrences across
2 sessions. That bar keeps one bad night from becoming a habit; it's a rule of
thumb with no statistical test behind it. Findings
come from a model's reading of the game and the player's own answers, so the
profile measures what the reviews found. It can't see what they missed.

**Some of the code is older than its standards.** `review/play_profile.py` is
2,200 lines in one module. Most functions have no type hints and there's no type
checker in CI. Several modules resolve their data folder at import time, which is why
the tests patch module attributes. Config lookups differ between modules: some
check the working directory first, some the data folder, some only `config/`.

**One maintainer.** Built by one person, with Claude as a pair programmer
throughout.
