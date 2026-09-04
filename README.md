# MTG Data

A Claude Code plugin for Magic: The Gathering tournament data, from the scrape through to the meta read.

Playwright scrapers run on your machine and pull round-by-round results from melee.gg and MTGO. Claude reads what they produce. Defaults to Standard, and works for any format you point it at. Set the scrapes on a schedule and the answer is ready before you ask.

## Skills in this plugin

| Skill | What it does |
|---|---|
| `mtg-tournament-analysis` | Reads the format. Meta share, win rates, a colour-coded matchup matrix, what moved week over week, and card-level signal across the field: rogue picks, deviations from an archetype's goto build, adoption trends, and shells nobody has named yet. |
| `deck-check` | Gets every deck under the right archetype name, and pushes that name into the CSVs the win rates and matchups are actually built from. Reads rulings you mark up in Obsidian, and keeps them across scrapes. |
| `vod-review` | Reviews your own games from an untapped.gg match log, a YouTube VOD, or a pasted log. Finds the turn the game was actually lost, and judges the line on what you knew at the time rather than on what you drew. Asks what you were thinking before it grades anything, and keeps a running profile of your habits. |
| `rules-check` | Answers a rules question by quoting the current Comprehensive Rules with the rule number. Priority, the stack, triggers, state-based actions, layers. Never from memory. |

The split between the first two is deliberate. Analysis reports the cards performing in a deck it can't name and stops there; naming it is `deck-check`'s job, and that's the step that turns those cards into an archetype with a win rate.

The other two are what you do with a meta read. Knowing a deck wins 55% doesn't tell you why you went 2-3 with it, and `vod-review` hands every priority and timing question to `rules-check` rather than resolving it from memory.

**Start at [`CLAUDE.md`](CLAUDE.md).** It's the router: which skill answers which question, how the data flows, which consumer reads which file, and the hard rules. Read it before opening a SKILL.md.

**More skills will land here.** The layout is `skills/<name>/SKILL.md`, so adding one doesn't move anything else. One rule holds it together: every skill carries a `## Related skills in this plugin` table naming its siblings and when to hand off, and a test in `tests/test_event_validation.py` fails if you add a skill without updating the others.

---

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
python setup.py        # Windows
python3 setup.py       # macOS / Linux
```

Setup is what makes the skills useful. Without it there's no workspace, no scrape script, and no archetype baseline, so every question comes back "no local data." Details in [Set up local scraping](#set-up-local-scraping) below.

Prefer a file? `python package.py` builds `mtg-data.plugin`, a zip of the plugin layout, for installing from a local checkout.

---

## Local-first: where the clean data comes from

The scrapers run on your own machine. They pull the cleanest, most complete data (full melee round data, MTGO Challenge and 5-0 lists), and Claude reads what they produce.

What a session can fetch live, with no local data:

- **mtgtop8** renders as plain HTML, so it's the reliable live source: archetype meta share, the current decks to beat, and aggregate decklists. `setup.py` seeds a per-format baseline from it.
- **MTGO decklists and magic.gg results are JavaScript-rendered.** A plain fetch gets a loading shell instead of cards, so card-level data comes from the local MTGO scrape.
- **melee.gg** pairings and standings, the data behind the matchup matrix and head-to-head win rates, are JavaScript-rendered and the API is OAuth-gated. They come only from the local scraper, which drives a real browser.

## Requirements

- Python 3.10 or newer.
- One third-party package: Playwright, which drives the browser for melee.gg and MTGO. Everything else is the standard library. `setup.py` offers to install it, or do it yourself:

  ```
  pip install -r requirements.txt
  playwright install chromium
  ```

- `pytest` if you want to run the test suite. It's in `requirements.txt` as a dev dependency.

## Set up local scraping

**Windows**: double-click `setup.bat`, or run `python setup.py`.
**macOS / Linux**: `python3 setup.py`.

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

Re-run `setup.py` any time to add a format. It won't clobber a config you've tuned.

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

To run a fetcher directly, set those yourself, or run it in the repo folder and everything defaults to landing next to the scripts:

```
python mtg_fetch.py --format Modern --since 2026-05-01
python fetch_mtgo.py --format Modern
```

`mtg_fetch.py` flags: `--format`, `--since YYYY-MM-DD`, `--dry-run`, `--fetch-sets`.

---

## The pool has to be right before the numbers mean anything

Three things run automatically after a scrape. Each exists because the alternative failed quietly.

**`validate_events.py`** judges every event by its decklists rather than by its name or its metadata. Verdicts are `off-format`, `pre-era`, `variant`, `seat`, `unverified` or `ok`. Anything that fails is quarantined out of the combined CSVs and renamed out of the per-event glob, with `*.raw.csv` kept alongside.

That guard is not hypothetical. In August 2026, 1,316 of 1,708 pairing rows in a Standard pool didn't belong: a pre-ban paper event, an entirely Modern team-trios event, and an Artisan side event whose every card is Standard-legal. Card legality is necessary and not sufficient. Every script exited 0, and a published note reported a banned deck at 6.8% of a "post-ban" metagame 17 days after the ban.

**`build_card_pool.py`** caches a format's legal cards from Scryfall, which is what the validator judges against.

**`audit_refs.py`** checks `archetype_refs.json` is in-era, in-format, and free of labels that collide with each other. `--strict` exits non-zero. `--apply-aliases` collapses confirmed duplicates and backs up first.

```
python validate_events.py --format Standard
python build_card_pool.py --format Standard
python audit_refs.py --strict
```

`build_baseline.py` refuses to write a snapshot when the quarantine report is missing, was built for a different era, or predates the last scrape. `--skip-validation-check` overrides it, and you should have a reason.

## Format eras, and what happens when cards get banned

The search window opens at the start of the current **era**: the later of the newest set release (`set_releases.json`) and the newest banned and restricted announcement (`bans.json`). A ban and a set release inside 14 days count as one reset, anchored on the earlier date.

```
python mtg_era.py
```

That prints where the window starts and why. A set release is the obvious break. A ban is the sneaky one, because the files keep their names, the archetype labels keep their spelling, and a win rate against a deck that no longer exists still reads like a fact.

When a B&R announcement lands:

```
python archive_era.py --dry-run     # what would move
python archive_era.py               # move it
python mtg_fetch.py                 # scrape the new era from scratch
python build_mtgtop8_baseline.py    # re-seed references for the new era
```

`archive_era.py` moves the scraped CSVs, the MTGO dumps, and the closing era's baseline into `archive/through-YYYY-MM-DD/` with a manifest. That's not tidiness. The analysis scripts glob `melee_*_pairings.csv` out of the data folder and pool everything they find, and the glob doesn't recurse, so moving the files down one level is what takes them out of the live numbers.

Add the announcement to `bans.json` yourself (effective date, format, cards, decks hit, the WotC link). Nothing auto-fetches it, and the whole split depends on that file being right.

## Build a meta baseline

Two ways, answering different questions.

**From mtgtop8, no scrape needed.** `setup.py` runs this, and you can re-run it any time:

```
python build_mtgtop8_baseline.py --format Standard
```

It pulls the current metagame from mtgtop8 (server-rendered, no browser): archetype share into `baselines/meta_baseline_mtgtop8_<format>.json`, and a modal decklist per archetype into `archetype_refs.json` so the classifier has references on a fresh install. It's additive, so it never clobbers a reference you've refined locally. Re-seed after every ban and every set release.

On one run it took the unnamed share of a post-ban field from 42% to 24%.

**From your own scrape:**

```
python build_baseline.py --label "Week 4, post-Spotlight"
```

Reads the standings CSV from `MTG_DATA_DIR` and appends a snapshot to `baselines/meta_baseline_<era_slug>.json`. A ban starts a new baseline file, so a week-over-week delta can't compare live decks against banned ones.

## Your play profile

`vod-review` does two things a one-off review can't. It asks, and it remembers.

**It asks.** Before grading a decision it flagged, it asks what the read was, what you were playing around, and whether a particular card was in the picture. That third question names a real card from the opponent's archetype, either from your own archetype note if you have built one or from `card_signal.py`'s rogue lens for cards the field has started playing that the note hasn't caught up to. It only asks if the deck actually plays the card, the card was live at that moment, and knowing about it changes the line. Otherwise it skips the question, because a manufactured trap teaches you to distrust the review.

The answers move grades, which is why they're collected first. A sound read whose line still lost is graded `correct`, and your answer is what proves it. Naming the right card and then making a play that ignores it is an execution problem rather than a judgement problem, and those need different practice.

**It remembers.** Every finding is appended to `play_log.jsonl`, one object per game, and `play_profile.py` counts it:

```
python play_profile.py                 # roll up, rewrite the profile note
python play_profile.py --validate      # check the ledger, write nothing
python play_profile.py --dry-run       # print the profile, write nothing
python play_profile.py --json          # the counts, for answering a question
```

What the counting buys you:

- **A habit needs 3 occurrences across 2 sessions before it's called a trend.** Two occurrences on one night is one bad night, so sessions are counted separately from games. Two go in a Watching section, named and counted with no conclusion drawn.
- **Every line carries its count and its dates.** "You're impatient with removal" is a vibe. "Spent removal on the first legal target 3 times across 3 sessions, 2 punts and a close, turns 3, 4 and 6" is something you can argue with.
- **Strengths clear the same bar.** A profile listing only leaks is the default failure of automated review and the reason people stop reading them. A habit that stops appearing moves to Faded with the date last seen, so a fixed leak stays visible as fixed.
- **Pace is measured or declared unmeasurable.** A YouTube VOD gives real seconds per turn from its timestamps; an untapped replay gives duration over turn count; a pasted log gives nothing and says so. MTGO and Arena logs carry no usable timing and none gets derived. Beyond that there are six proxy tells (tapped the wrong mana, cast before the land drop, missed trigger, and so on): one is noise, two in a game is a signal. Losing is never evidence about speed.
- **A count that is mostly confirmation says so.** The profile is read at the start of a review and written at the end, which makes it easy to find the habit you expected. Findings are formed from the game first, the profile is checked second, and anything found only on that second pass is flagged. A habit whose count is mostly flagged gets discounted in the note and is never offered as the thing to work on.

`kind` comes from a fixed vocabulary of ten decision types, for the same reason archetype names do: free text splits one habit spelled three ways into three habits. A line using anything else is rejected and reported rather than counted under a name nothing else uses, and the exit code says so (`0` clean, `1` couldn't run, `2` found lines it couldn't use).

**Your ledger and your profile stay on your machine.** They're a record of your own games. `.gitignore` and `package.py` both exclude them, and a test fails if that ever stops being true. The schema and the vocabularies are in [`skills/vod-review/reference/play-profile.md`](skills/vod-review/reference/play-profile.md).

## Rules lookups

`rules-check` quotes the Comprehensive Rules rather than reciting them. `rules_lookup.py` finds the current dated CR text file on the WotC rules page, caches it beside the scripts, and refreshes after 14 days or when a newer one is published.

```
python rules_lookup.py 117.3b            # one rule, verbatim
python rules_lookup.py 704               # a whole section
python rules_lookup.py --search "split second"
python rules_lookup.py --glossary "deathtouch"
python rules_lookup.py --version         # what's cached, and how old
```

Stdlib only, no browser. Every result prints the CR version alongside it, because the rules are revised with every set and an answer you can't date is an answer you can't re-check.

## Archetype names are a fixed vocabulary

`archetype_names.json` carries the canonical names. They *are* the vocabulary every source's deck names resolve onto, through `mtg_stats.ARCHETYPE_ALIASES`.

Point an alias at a name the manifest doesn't carry and you split a deck instead of merging it. A test fails if you try, and another fails if the alias table ever chains A to B to C.

**The archetype notes themselves don't ship.** `skills/mtg-tournament-analysis/reference/archetypes/` arrives empty apart from its README. The notes are one person's reading of a metagame at a moment, they go stale the week the format moves, and you need none of them to run the plugin. `mtg-tournament-analysis` writes your own as you scrape; `deck-check` adds the name to the manifest when it names a new deck.

## Data freshness

Check the newest event date in `melee_<format>_all_pairings.csv` before trusting local data. More than 2 weeks old, run the scrape script. The skills will tell you when they're working from stale data, and that warning is worth reading.

## Tests

```
pytest tests/ -q
```

They pin the parsers against static fixtures (no network), the win-rate counting rules, the event validator, the alias table, and the plugin's own structure.

---

## Feedback

Bug reports and feature requests go to [GitHub Issues](https://github.com/Phillip-Hurst/MTG-Data/issues).

melee.gg and MTGO redesign their frontends periodically. If a script starts returning empty results or errors, that's usually why. Open an issue with the script name, the error, and the date.

## Credits and legal

Card names, costs, and oracle text come from [Scryfall](https://scryfall.com). If you extend the card-lookup code, respect their [API guidelines](https://scryfall.com/docs/api): keep requests modest (roughly 10 per second, with a small delay between calls).

Tournament data is read from melee.gg, MTGO, mtgtop8, and MTGGoldfish for personal, non-commercial analysis. Check each site's terms before redistributing scraped data.

Magic: The Gathering is © Wizards of the Coast. This is unofficial Fan Content permitted under the [Wizards of the Coast Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved or endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast LLC.

Code is released under the MIT License, see [LICENSE](LICENSE).
