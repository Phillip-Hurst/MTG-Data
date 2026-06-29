# MTG Tournament Analysis — Cowork Skill

A Cowork skill that analyzes Magic: The Gathering tournament results. Playwright scrapers run on your machine to pull round-by-round data from melee.gg and MTGO — Cowork reads what they produce. Defaults to Standard; configurable for any format.

Ask it anything about the current meta and it gives you:

- What's winning right now (top 8 counts, meta share)
- How the meta changed week over week (intra-set drift)
- What changed from the previous set (cross-set shift)
- A matchup matrix, color-coded by win rate
- Cards worth watching, with the mechanical reason, not just the name

---

## Local-first: where the clean data comes from

This tool runs its scrapers on your own machine. The local scripts pull the cleanest, most complete data (full melee round data, MTGO Challenge and 5-0 lists), and Cowork reads what they produce. Run setup once, scrape when you want fresh results, then ask Cowork about the meta.

What a Cowork session can fetch live, with no local data:

- **mtgtop8** renders as plain HTML, so it's the reliable live source: archetype meta share, the current "decks to beat," and aggregate decklists. `setup.py` seeds a per-format baseline from it (see below).
- **MTGO decklists and magic.gg results are JavaScript-rendered.** A plain fetch gets a loading shell, not the cards, so the card-level data comes from the local MTGO scrape (or a browser), not a live fetch.
- **melee.gg** round-by-round pairings and standings, the data behind the matchup matrix and head-to-head win rates, are JavaScript-rendered and the API is OAuth-gated. They come only from the local scraper, which drives a real browser on your machine.

That's what `setup.py` is for: it builds a clean place to scrape into, wires the scripts to use it, and seeds each format's archetype baseline from mtgtop8 so you're not starting from nothing.

---

## Install the skill

Download `mtg-tournament-analysis.skill` from [Releases](https://github.com/Phillip-Hurst/MTG-Data/releases) and drop it into Cowork.

Or build the `.skill` yourself:

```
git clone https://github.com/Phillip-Hurst/MTG-Data
cd MTG-Data
python package.py
```

Then drop the produced `mtg-tournament-analysis.skill` into Cowork.

---

## Requirements

- Python 3.10 or newer.
- One third-party package: Playwright, which drives the browser for melee.gg and MTGO. Everything else is the Python standard library. `setup.py` offers to install it, or do it yourself:

  ```
  pip install -r requirements.txt
  playwright install chromium
  ```

---

## Set up local scraping (run this first)

The scrapers run on your own machine, not in Cowork. `setup.py` walks you through it.

**Windows** — double-click `setup.bat`, or in Command Prompt:

```
python setup.py
```

**macOS / Linux:**

```
python3 setup.py
```

(On macOS and Linux the command is usually `python3`, not `python`.) Python 3.10 or newer is required.

Setup will:

1. Check your Python version.
2. Offer to install Playwright + Chromium (needed for melee.gg; MTGO doesn't need it).
3. Let you pick which formats to track — type numbers or names, comma-separated (`1,2` or `Standard, Modern`).
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

5. Write a `mtg_workspace.json` manifest at the root so Cowork knows where each format's data lives.
6. Seed each format's archetype baseline from mtgtop8 (optional, asks first) so the classifier and the meta read have a starting point before your first scrape.

Re-run `setup.py` any time to add another format. It won't clobber a config you've already tuned.

---

## Pull data

Open a format's folder and run its scrape script:

```
scrape.bat          (Windows)
./scrape.sh         (macOS / Linux)
```

It scrapes melee.gg, then MTGO, for that format and drops everything in that format's `scrapes/` folder. Run it whenever you want fresh results — data accumulates over time, so you don't re-scrape what you already have.

Under the hood the script just sets three environment variables and calls the fetchers:

- `MTG_DATA_DIR` — where scraped data is read and written (the format's `scrapes/` folder)
- `MTG_OUTPUT_DIR` — where analysis notes are written (the format's `insights/` folder)
- `MTG_FORMAT` — the format name melee.gg and MTGO expect (`Standard`, `Modern`, ...)

If you'd rather run a fetcher directly, set those yourself, or just run it in the skill folder and everything defaults to landing next to the scripts:

```
python mtg_fetch.py --format Modern --since 2026-05-01
python fetch_mtgo.py --format Modern
```

`mtg_fetch.py` flags: `--format` (override for one run), `--since YYYY-MM-DD` (tighter window), `--dry-run` (see what it found without scraping), `--fetch-sets` (refresh `set_releases.json` from WotC).

---

## Build a meta baseline

Two ways, and they answer different questions.

**From mtgtop8, no scrape needed.** `setup.py` runs this in step 6, and you can re-run it any time to refresh:

```
python build_mtgtop8_baseline.py --format Standard
```

It pulls the current metagame from mtgtop8 (server-rendered, no browser): archetype share into `baselines/meta_baseline_mtgtop8_<format>.json`, and a modal decklist per archetype into `archetype_refs.json` so the classifier has references on a fresh install. Set `MTG_DATA_DIR` first (the scrape script does) so it writes to the right format. Flags: `--max-archetypes`, `--decks-per-archetype`, `--dry-run`, `--verbose`.

**From your own scrape.** Once you've scraped melee:

```
python build_baseline.py --label "Week 4 — post-Spotlight"
```

Reads the standings CSV from `MTG_DATA_DIR` and appends a meta snapshot to `baselines/meta_baseline_<set_slug>.json`. Run it after any significant scrape — the baseline is what makes week-over-week comparison work.

---

## Data freshness

Check the newest event date in the combined pairings file (`melee_<format>_all_pairings.csv`, e.g. `melee_standard_all_pairings.csv`) before trusting local data. If it's more than 2 weeks old, run the scrape script to catch up. The skill will tell you when it's working from stale data — don't skip that warning.

---

## Feedback

Bug reports and feature requests go to [GitHub Issues](https://github.com/Phillip-Hurst/MTG-Data/issues).

melee.gg and MTGO redesign their frontends periodically. If a script starts returning empty results or errors, that's usually why. Open an issue with the script name, the error, and the date — it helps narrow down what changed.

---

## Credits and legal

Card names, costs, and oracle text come from [Scryfall](https://scryfall.com). If you extend the card-lookup code, respect their [API guidelines](https://scryfall.com/docs/api): keep requests modest (roughly 10 per second, with a small delay between calls).

Tournament data is read from melee.gg, MTGO, and MTGGoldfish for personal, non-commercial analysis. Check each site's terms before redistributing scraped data.

Magic: The Gathering is © Wizards of the Coast. This is unofficial Fan Content permitted under the [Wizards of the Coast Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved or endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast LLC.

Code is released under the MIT License — see [LICENSE](LICENSE).
