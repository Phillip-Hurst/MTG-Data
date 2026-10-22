# User guide

How to install mtg-data, pull data, and run each part of the pipeline. For how it
works and why, start at the [README](../README.md) and the
[architecture](architecture.md).

## Install

Two steps. Step 1 gives Claude the skills. Step 2 builds the place the data lives, and you can't skip it, because the scrapers run on your machine rather than inside a Claude session.

### 1. Add the plugin

```
/plugin marketplace add Phillip-Hurst/MTG-Data
/plugin install mtg-data@mtg-data
```

### 2. Run setup (required)

Clone the repo, or use the copy the plugin installed, and run:

```
python scripts/setup_workspace.py       # Windows, or double-click scripts\setup.bat
python3 scripts/setup_workspace.py      # macOS / Linux
```

Setup is what makes the skills useful. Without it there's no workspace, no scrape script, and no archetype baseline, so every question comes back "no local data." Details in [Set up local scraping](#set-up-local-scraping) below.

Prefer a file? `python scripts/build_plugin.py` builds `mtg-data.plugin`, a zip of the plugin layout, for installing from a local checkout.

---

## Local-first: where the clean data comes from

The scrapers run on your own machine. They pull the cleanest, most complete data (full melee round data, MTGO Challenge and 5-0 lists), and Claude reads what they produce.

What a session can fetch live, with no local data:

- **mtgtop8** renders as plain HTML, so it's the reliable live source: archetype meta share, the current decks to beat, and aggregate decklists. `scripts/setup_workspace.py` seeds a per-format baseline from it.
- **MTGO decklists and magic.gg results are JavaScript-rendered.** A plain fetch gets a loading shell instead of cards, so card-level data comes from the local MTGO scrape.
- **melee.gg** pairings and standings, the data behind the matchup matrix and head-to-head win rates, are JavaScript-rendered and the API is OAuth-gated. They come only from the local scraper, which drives a real browser.

## Requirements

- Python 3.10 or newer.
- One third-party package: Playwright, which drives the browser for melee.gg and MTGO. Everything else is the standard library. `scripts/setup_workspace.py` offers to install it, or do it yourself:

  ```
  pip install -e .
  playwright install chromium
  ```

- `pip install -e ".[dev]"` adds pytest and ruff, for the test suite and the lint check.

## Set up local scraping

**Windows**: double-click `scripts\setup.bat`, or run `python scripts/setup_workspace.py`.
**macOS / Linux**: `python3 scripts/setup_workspace.py`.

Setup will:

1. Check your Python version.
2. Offer to install Playwright and Chromium (melee.gg needs it, MTGO doesn't).
3. Let you pick which formats to track. Type numbers or names, comma-separated (`1,2` or `Standard, Modern`).
4. Build a folder tree, one branch per format:

   ```
   <workspace>/
     Standard/
       scrapes/        melee + MTGO data lands here
         baselines/
       insights/       analysis output ([C] *.md, win-rate tracker, matrix)
         Archetypes/
         Snapshots/
         transcripts/
       scrape.bat / scrape.sh    one-click fetch for this format
     Modern/
       ...
   ```

5. Write an `mtg_workspace.json` manifest at the root so Claude knows where each format's data lives.
6. Seed each format's archetype baseline from mtgtop8 (optional, asks first) so the classifier has references before your first scrape.

Re-run `scripts/setup_workspace.py` any time to add a format. It won't clobber a config you've tuned.

## Pull data

Open a format's folder and run its scrape script:

```
scrape.bat          (Windows)
./scrape.sh         (macOS / Linux)
```

It scrapes melee.gg, then MTGO, then validates what it got (below) and audits the archetype references. Data accumulates, so you don't re-scrape what you already have.

Under the hood the script sets three environment variables and calls the fetchers:

- `MTG_DATA_DIR` where scraped data is read and written
- `MTG_OUTPUT_DIR` where analysis notes are written
- `MTG_FORMAT` the format name melee.gg and MTGO expect (`Standard`, `Modern`, ...)

To run a fetcher directly, set those yourself. With none of them set, data and notes land in the checkout root, which `.gitignore` keeps out of the repo:

```
python mtg.py fetch-melee --format Modern --since 2026-05-01
python mtg.py fetch-mtgo --format Modern
```

`fetch-melee` flags: `--format`, `--since YYYY-MM-DD`, `--dry-run`, `--fetch-sets`.

---

## The pool has to be right before the numbers mean anything

Three things run automatically after a scrape. Each exists because the alternative failed quietly.

**`validate-events`** judges every event by its decklists rather than by its name or its metadata. Verdicts are `off-format`, `pre-era`, `variant`, `seat`, `unverified` or `ok`. Anything that fails is quarantined out of the combined CSVs and renamed out of the per-event glob, with `*.raw.csv` kept alongside.

That guard is not hypothetical. In August 2026, 1,316 of 1,708 pairing rows in a Standard pool didn't belong: a pre-ban paper event, an entirely Modern team-trios event, and an Artisan side event whose every card is Standard-legal. Card legality is necessary and not sufficient. Every script exited 0, and a published note reported a banned deck at 6.8% of a "post-ban" metagame 17 days after the ban.

**`build-card-pool`** caches a format's legal cards from Scryfall, which is what the validator judges against.

**`audit-refs`** checks `archetype_refs.json` is in-era, in-format, and free of labels that collide with each other. `--strict` exits non-zero. `--apply-aliases` collapses confirmed duplicates and backs up first.

```
python mtg.py validate-events --format Standard
python mtg.py build-card-pool --format Standard
python mtg.py audit-refs --strict
```

`build-baseline` refuses to write a snapshot when the quarantine report is missing, was built for a different era, or predates the last scrape. `--skip-validation-check` overrides it, and you should have a reason.

## Format eras, and what happens when cards get banned

The search window opens at the start of the current **era**: the later of the newest set release (`config/set_releases.json`) and the newest banned and restricted announcement (`config/bans.json`). A ban and a set release inside 14 days count as one reset, anchored on the earlier date.

```
python mtg.py era
```

That prints where the window starts and why. A set release is the obvious break. A ban is the sneaky one, because the files keep their names, the archetype labels keep their spelling, and a win rate against a deck that no longer exists still reads like a fact.

When a B&R announcement lands:

```
python mtg.py archive-era --dry-run     # what would move
python mtg.py archive-era               # move it
python mtg.py fetch-melee                 # scrape the new era from scratch
python mtg.py build-mtgtop8-baseline    # re-seed references for the new era
```

`archive-era` moves the scraped CSVs, the MTGO dumps, and the closing era's baseline into `archive/through-YYYY-MM-DD/` with a manifest. That's not tidiness. The analysis scripts glob `melee_*_pairings.csv` out of the data folder and pool everything they find, and the glob doesn't recurse, so moving the files down one level is what takes them out of the live numbers.

Add the announcement to `config/bans.json` yourself (effective date, format, cards, decks hit, the WotC link). Nothing auto-fetches it, and the whole split depends on that file being right.

## Build a meta baseline

Two ways, answering different questions.

**From mtgtop8, no scrape needed.** `scripts/setup_workspace.py` runs this, and you can re-run it any time:

```
python mtg.py build-mtgtop8-baseline --format Standard
```

It pulls the current metagame from mtgtop8 (server-rendered, no browser): archetype share into `baselines/meta_baseline_mtgtop8_<format>.json`, and a modal decklist per archetype into `archetype_refs.json` so the classifier has references on a fresh install. It's additive, so it never clobbers a reference you've refined locally. Re-seed after every ban and every set release.

On one run it took the unnamed share of a post-ban field from 42% to 24%.

**From your own scrape:**

```
python mtg.py build-baseline --label "Week 4, post-Spotlight"
```

Reads the standings CSV from `MTG_DATA_DIR` and appends a snapshot to `baselines/meta_baseline_<era_slug>.json`. A ban starts a new baseline file, so a week-over-week delta can't compare live decks against banned ones.

## Your play profile

`vod-review` does two things a one-off review can't. It asks, and it remembers.

**It asks.** Before grading a decision it flagged, it asks what the read was, what you were playing around, and whether a particular card was in the picture. That third question names a real card from the opponent's archetype, either from your own archetype note if you have built one or from `card-signal`'s rogue lens for cards the field has started playing that the note hasn't caught up to. It only asks if the deck actually plays the card, the card was live at that moment, and knowing about it changes the line. Otherwise it skips the question, because a manufactured trap teaches you to distrust the review.

The answers move grades, which is why they're collected first. A sound read whose line still lost is graded `correct`, and your answer is what proves it. Naming the right card and then making a play that ignores it is an execution problem rather than a judgement problem, and those need different practice.

**It remembers.** Every finding is appended to `play_log.jsonl`, one object per game, and `play-profile` counts it:

```
python mtg.py play-profile                 # roll up, rewrite the profile note
python mtg.py play-profile --validate      # check the ledger, write nothing
python mtg.py play-profile --dry-run       # print the profile, write nothing
python mtg.py play-profile --json          # the counts, for answering a question
```

What the counting buys you:

- **A habit needs 3 occurrences across 2 sessions before it's called a trend.** Two occurrences on one night is one bad night, so sessions are counted separately from games. Two go in a Watching section, named and counted with no conclusion drawn.
- **Every line carries its count and its dates.** "You're impatient with removal" is a vibe. "Spent removal on the first legal target 3 times across 3 sessions, 2 punts and a close, turns 3, 4 and 6" is something you can argue with.
- **Strengths clear the same bar.** A profile listing only leaks is the default failure of automated review and the reason people stop reading them. A habit that stops appearing moves to Faded with the date last seen, so a fixed leak stays visible as fixed.
- **Pace is measured or declared unmeasurable.** A YouTube VOD gives real seconds per turn from its timestamps; an untapped replay gives duration over turn count; a pasted log gives nothing and says so. MTGO and Arena logs carry no usable timing and none gets derived. Beyond that there are six proxy tells (tapped the wrong mana, cast before the land drop, missed trigger, and so on): one is noise, two in a game is a signal. Losing is never evidence about speed.
- **A count that is mostly confirmation says so.** The profile is read at the start of a review and written at the end, which makes it easy to find the habit you expected. Findings are formed from the game first, the profile is checked second, and anything found only on that second pass is flagged. A habit whose count is mostly flagged gets discounted in the note and is never offered as the thing to work on.

`kind` comes from a fixed vocabulary of ten decision types, for the same reason archetype names do: free text splits one habit spelled three ways into three habits. A line using anything else is rejected and reported rather than counted under a name nothing else uses, and the exit code says so (`0` clean, `1` couldn't run, `2` found lines it couldn't use).

**Your ledger and your profile stay on your machine.** They're a record of your own games. `.gitignore` and `scripts/build_plugin.py` both exclude them, and a test fails if that ever stops being true. The schema and the vocabularies are in [`skills/vod-review/reference/play-profile.md`](skills/vod-review/reference/play-profile.md).

## Rules lookups

`rules-check` quotes the Comprehensive Rules rather than reciting them. `rules-lookup` finds the current dated CR text file on the WotC rules page, caches it in the checkout root, and refreshes after 14 days or when a newer one is published.

```
python mtg.py rules-lookup 117.3b            # one rule, verbatim
python mtg.py rules-lookup 704               # a whole section
python mtg.py rules-lookup --search "split second"
python mtg.py rules-lookup --glossary "deathtouch"
python mtg.py rules-lookup --version         # what's cached, and how old
```

Stdlib only, no browser. Every result prints the CR version alongside it, because the rules are revised with every set and an answer you can't date is an answer you can't re-check.

## Archetype names are a fixed vocabulary

`config/archetype_names.json` carries the canonical names. They *are* the vocabulary every source's deck names resolve onto, through `mtg_data.core.stats.ARCHETYPE_ALIASES`.

Point an alias at a name the manifest doesn't carry and you split a deck instead of merging it. A test fails if you try, and another fails if the alias table ever chains A to B to C.

**The archetype notes themselves don't ship.** `skills/mtg-tournament-analysis/reference/archetypes/` arrives empty apart from its README. The notes are one person's reading of a metagame at a moment, they go stale the week the format moves, and you need none of them to run the plugin. `mtg-tournament-analysis` writes your own as you scrape; `deck-check` adds the name to the manifest when it names a new deck.

## Data freshness

Check the newest event date in `melee_<format>_all_pairings.csv` before trusting local data. More than 2 weeks old, run the scrape script. The skills will tell you when they're working from stale data, and that warning is worth reading.
