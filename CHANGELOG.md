# Changelog

## 1.4.0 — 2026-06-29

Local-first framing, and a baseline so a fresh install starts with something.

### Archetype baseline from mtgtop8
- New `build_mtgtop8_baseline.py`: fetches a format's current metagame from mtgtop8 (server-rendered, standard-library `urllib`, no browser) and writes two things into `MTG_DATA_DIR` — `archetype_refs.json` (a modal mainboard per deck label, so `classify_decks.py` has references on a fresh install) and `baselines/meta_baseline_mtgtop8_<format>.json` (the archetype share snapshot). Keyed by the deck-level label, not the umbrella, since that's the granularity that matches the archetype files.
- The modal-mainboard aggregation is reused from `classify_decks.build_ref_from_decks`, so card-name normalization stays identical across every reference builder (no third variant).
- `setup.py` gains step 6: after building the folders it offers to seed each selected format's baseline from mtgtop8. Skippable and offline-tolerant; a failed fetch degrades gracefully and never blocks setup.
- New `tests/test_mtgtop8_baseline.py` pins the parsers (decklist export, metagame share pairing, archetype deck rows) against static fixtures, no network.

### Docs
- README and SKILL.md reframed local-first and corrected: mtgtop8 is the live source that actually renders to a plain fetch; MTGO decklists and magic.gg results are JavaScript-rendered and return a loading shell, so their card-level data comes from the local scrape (or a JS-rendering browser), not a live fetch. The earlier "works live, no setup" wording oversold sources that don't render server-side.

## 1.3.0 — 2026-06-29

Audit follow-up: clears the pre-share blockers and the major/minor issues from the v1.2.0 review.

### Data correctness
- Win rate now counts a draw as neither a win nor a loss (excluded from the denominator), ignores byes, and only counts a decided game when the winner matches one of the two players. An unparseable winner is skipped, not silently logged as a draw. Applied consistently across `winrate_analysis.py`, `matchup_matrix.py` and `update_archetypes.py` through a new shared `mtg_stats.py`. (M2, M3)
- Matchup-matrix cells and the per-archetype tables now share one decided-games denominator, so the numbers agree inside a report. (M2)
- `fetch_mtgo.py`'s MTGGoldfish fallback URLs and filters are built from the chosen format, so a non-Standard run can no longer write Standard data. MTGO.com stays the primary source. (B3)

### Multi-format separation
- Every melee output file is tagged with the format slug (per-event and combined) and the rebuild glob is format-specific, so two formats can't cross-contaminate even in one folder. (B2)
- New `mtg_paths.py` resolves each format's data/output folder from the `mtg_workspace.json` manifest, so a fetch run by hand sorts into the right format folder, not only the generated runner. `setup.py`'s default workspace is now `MTG Skill`. (B2)

### Robustness
- `melee_scraper.py` forces UTF-8 on stdout, so an accented deck or player name no longer crashes a scrape on a default Windows console (it runs as a subprocess, so the crash was previously opaque). Same guard added to the four analysis scripts. (B1)
- `update_archetypes.py` creates its `Archetypes/` folder before scanning, so a fresh install no longer reports every deck as undocumented. (M1)
- `parse_date` matches the literal date patterns instead of mangling the format string; the DOM player-count parse strips the date column so a 4-digit year can't be read as a player count; `load_config` / `merge_event_store` log when they fall back instead of swallowing the error. (minors)

### Cleanup
- Removed the dead `--dump` block in `mtg_fetch.py` and the no-op `--headed` flag; fixed the `--weeks 8` hint to `--since`. (M4, minors)
- Generated `scrape.bat` / `scrape.sh` forward extra flags (`--since`, `--dry-run`) to BOTH fetchers, not just melee. (M5)
- `classify_decks.py` review parser no longer caps card names at 60 chars, and its ref builder normalizes double-faced names to match `build_refs_from_melee.py`. (minors)
- `mtgdecks_fetch.py` (a Cloudflare-blocked experiment) is excluded from the package and gitignored. (M6)

### Project hygiene
- Added `LICENSE` (MIT), `requirements.txt` (pins Playwright, notes Python 3.10+), and Scryfall + Wizards Fan Content Policy credits in the README and SKILL.md.
- `.gitignore` now excludes personal vault notes (`[C] *.md`), the deck-log and win-rate notes, the standings-only registry, and the workspace manifest, so they can't be committed to a public repo.
- Added a `tests/` pytest suite covering the win-rate counting rules (excluded from the installed skill).

## 1.2.0 — 2026-06-24

### Guided setup + per-format workspace

- New `setup.py` (and `setup.bat` for Windows): checks Python, offers to install Playwright + Chromium, lets you pick which formats to track, and builds a per-format folder tree (`<format>/scrapes` and `<format>/insights`) with a ready-to-run `scrape.bat`/`scrape.sh` in each. Writes a `mtg_workspace.json` manifest so Cowork knows where each format's data lives.
- New `MTG_DATA_DIR` environment variable: all scripts now read and write scraped data here, defaulting to the script folder so the existing flat workflow is unchanged. The generated scrape scripts set it per format, so formats no longer cross-contaminate a shared folder (fixes the combined-CSV mixing bug).
- `build_baseline.py`, `fetch_mtgo.py`, `mtg_fetch.py` now resolve `set_releases.json` / `mtg_config.json` from the data folder first, then the shipped copy — each format can carry its own.

### Fixes

- `update_archetypes.py` no longer hardcodes the set name. The meta snapshot title and filename come from `set_releases.json` (and `MTG_FORMAT`), so a set rotation no longer mislabels output.
- Analysis scripts (`winrate_analysis.py`, `matchup_matrix.py`, `update_archetypes.py`) now print a clear "no data — run the scraper first" message instead of writing empty or degenerate output, and create their output directory before writing.
- `build_refs_from_melee.py` imports Playwright lazily, so `--rebuild-only` and `--help` work without it installed.
- `package.py` rewritten to exclude logs, scraped data, and all loose `.md` notes (keeps only `SKILL.md`), and to print a leak check. Stops personal vault notes and run logs from shipping in the public `.skill`. `mtgdecks_fetch.py` (Cloudflare-blocked orphan) and the scraped-event registry are no longer packaged.

---

## 1.1.0 — 2026-06-13

### Format config

- New `mtg_config.json` — set `format` (default `Standard`) and `weeks_window` (default `8`) once; both `mtg_fetch.py` and `fetch_mtgo.py` read it automatically
- `--format` flag added to both scripts; overrides config for a single run
- `mtg_fetch.py`: `find_tournaments`, `get_window_start`, and `_try_ui_filters` all accept the format parameter; non-Standard formats use `weeks_window` instead of `set_releases.json` for the search window
- `mtg_fetch.py`: passes `MTG_FORMAT` env var to the `melee_scraper.py` subprocess
- `fetch_mtgo.py`: builds `MTGO_DECKLISTS_URL` dynamically from the resolved format; non-Standard output files use a `mtgo_{format}_` prefix so multiple formats can coexist in the same folder
- `melee_scraper.py`: reads `MTG_FORMAT` env var; writes `melee_{format}_all_pairings.csv` / `_standings.csv` for non-Standard (Standard keeps original filenames)

---

## 1.0.0 — 2026-06-13

First public release.

### Skill
- Full Standard meta analysis: melee.gg, MTGO Challenges, 5-0 dumps, magic.gg, MTGGoldfish
- Two-layer shift analysis: intra-set drift (recent vs earlier this set) and cross-set shift (current set vs prior baseline)
- Interactive matchup matrix widget (PapaParse, client-side CSV)
- Coverage-style card commentary: role, replacement, synergy, why now, fail case
- Scryfall card verification hard rule — every card check before it's mentioned
- Set-release anchoring via `set_releases.json`

### Scripts
- `mtg_fetch.py` — finds and scrapes Standard tournaments on melee.gg since latest set release
- `melee_scraper.py` — scrapes round pairings and standings for specific tournament IDs
- `fetch_mtgo.py` — pulls MTGO Standard results (Challenges + 5-0 dumps) from mtgo.com
- `build_baseline.py` — appends a meta snapshot to the current set baseline JSON
- `matchup_matrix.py` — builds matchup win-rate tables from pairings CSV
- `winrate_analysis.py` — per-archetype win rates and head-to-head across all scraped data
- `update_archetypes.py` — writes archetype markdown files with matchup sections
- `classify_decks.py` — classifies MTGO decklists against archetype references
- `build_refs_from_melee.py` — builds archetype reference card lists from melee deck URLs
- `analyze_weekend.py` — weekend-focused trend summary

### Portability
- All vault-specific paths removed from scripts
- Output directory defaults to script folder; override with `MTG_OUTPUT_DIR` env var
