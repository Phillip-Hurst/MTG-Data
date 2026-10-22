# mtg-data — plugin guide

Read this before opening a SKILL.md. It's deliberately small. Detail lives in the
skills and their reference folders, not here.

**What this plugin is:** Magic: The Gathering tournament data, from the scrape through
to the meta read, plus the two things you do with a meta read: check your own play,
and check what the rules actually say. Playwright scrapers run on your machine.
Claude reads what they produce.

---

## Which skill answers this?

| You want to know | Skill | Because |
|---|---|---|
| What's winning, what moved, what's the matchup matrix | `mtg-tournament-analysis` | It reads the field. It never names a deck. |
| Which cards are quietly performing | `mtg-tournament-analysis` | `card_signal.py`, five lenses: rogue, deviation, trend, adoption, unnamed |
| What the field is boarding, week by week | `mtg-tournament-analysis` | `card_signal.py --lens adoption`. Reads sideboards, which nothing did before 2026-09-08 |
| This deck is under the wrong name | `deck-check` | It's the only thing that writes a label into the files the numbers read |
| Name this unnamed shell | `deck-check` | Analysis hands it over on purpose |
| Clear the mislabel queue | `deck-check` | `apply_corrections.py` reads your `Decision:` lines |
| Why did I lose that game | `vod-review` | Untapped.gg replay, YouTube VOD, or a pasted log |
| Was that the right line on turn 4 | `vod-review` | It grades decisions against the information you had at the time, after asking you what you were thinking |
| What are my recurring habits, am I rushing | `vod-review` | `play_log.jsonl` and `[C] Play Profile.md` in the insights folder, counted rather than remembered |
| Does this trigger go on the stack before or after | `rules-check` | The Comprehensive Rules, quoted with the rule number |
| Can my opponent respond to that | `rules-check` | Priority and the stack, `reference/rules-and-the-stack.md` |
| What does this card cost, what does it do | any skill, but verify on Scryfall | Hard rule below |
| What's a card worth | `mtg-price-check` | Separate skill. Not in this plugin. Point at it by name. |

**When two skills could answer, order matters.** A matchup matrix built on wrong
labels is worse than no matrix, so `deck-check` runs before analysis. A VOD review
that hangs on a rules question stops and asks `rules-check` rather than guessing at
priority.

---

## The data stack

Data flows one direction, and every stage writes a file the next stage reads. That
sounds obvious and it's the source of most of this project's bugs, so it's written
down.

```
melee.gg ──> fetch_melee.py ──> melee_<fmt>_<id>_pairings.csv   <- source of truth
                                melee_<fmt>_<id>_standings.csv
                                melee_deck_cache.json
MTGO     ──> fetch_mtgo.py ──> mtgo_challenge_latest.json
                                mtgo_5-0_latest.json
mtgtop8  ──> build_mtgtop8_baseline.py ──> archetype_refs.json
                                            baselines/meta_baseline_mtgtop8_<fmt>.json
                                   |
                        validate_events.py   judges each event, renames the losers
                        audit_refs.py        checks the references are in-era and distinct
                                   |
                        combine_events.py    THE ONE WRITER of melee_<fmt>_all_*.csv
                                             rebuilds from the per-event files,
                                             verdicts applied, never in place
                                   |
    build_baseline.py ──> baselines/meta_baseline_<era_slug>.json
    matchup_matrix.py ─┐
    winrate_analysis.py├─> combine_events.load_pool(..., resolve_names=True)
    update_archetypes.py┘   one pool, one vocabulary
    card_signal.py    ───> the MTGO dumps, main and side
```

**The combined CSVs are derived. Rebuild them; never edit them.**
`combine_events.py` is the only thing that writes `melee_<fmt>_all_*.csv`. It
reads the per-event files, applies the quarantine's verdicts and the seat
filter, and writes `melee_<fmt>_all_coverage.json` beside them saying which
events made it in. Before 2026-09-08 three scripts wrote that file with three
different definitions, and `validate_events` filtered it in place so each run
filtered the previous run's output: the standings file went 553 rows to 312 to
241 while 27 per-event files sat on disk.

**Every pairing consumer speaks the classifier's vocabulary.**
`deck_labels.py` is the one place a tournament result becomes an archetype name:
override > classifier > organizer text > dropped. `resolve_pairing_decks` puts
the matchup layer on it too, which took distinct labels from 122 to 104 and
matchup cells at the 10-match floor from 8 to 14. For standings, a result whose
decklist isn't in the cache leaves the sample; for pairings, organizer text is
kept and counted separately, because a row records who beat whom.

**A pairing seat with no name and no deck URL cannot be recovered.** 775 of the
783 unnamed seats have neither, so the scraper captured nothing to look them up
by. That is a `melee_scraper.py` gap, not a naming one.

### Which file does a given consumer actually read?

| Consumer | Reads |
|---|---|
| `matchup_matrix.py`, `winrate_analysis.py`, `update_archetypes.py` | the pool via `combine_events.load_pool(..., resolve_names=True)` |
| `build_baseline.py` | `melee_<fmt>_all_standings.csv`, plus `deck_labels.py` for every deck name |
| `combine_events.py` | the per-event `melee_<fmt>_<id>_*.csv`, live and `.quarantined.csv` |
| `deck_labels.py` | `melee_deck_cache.json`, `archetype_refs.json`, `archetype_overrides.json` |
| `build_refs_from_melee.py` | `melee_deck_cache.json` |
| MTGO shares | `mtgo_classifications.json` |
| `card_signal.py` | `mtgo_*_latest.json` mainboards **and** sideboards, plus `card_pool_<fmt>.json` for colour and type |
| `play_profile.py` | `play_log.jsonl`, split on `format`, and it rewrites `[C] Play Profile.md` |

**This table is the whole point.** Fixing data means fixing the file the consumer
reads, not the one that looks canonical. On 2026-08-29 a correction that reached only
the deck cache would have left the matchup matrix reporting the old label forever,
because `mtg_stats.classify_row` reads deck names straight off the CSV row.

---

## Hard rules

**1. Verify every card on Scryfall before writing about it.** Every card, not just
unfamiliar ones. The cards you "know" from coverage or from a vault note are the
dangerous ones. Confident and wrong is worse than asking.

**2. Check the era before quoting a number.** Run `python mtg.py era`. An era is the
stretch over which results are comparable, and it ends on a set release or a ban. A
ban is the dangerous one: filenames don't change, archetype names don't change, and a
62% win rate against a deck that can't be registered still reads like a fact.

**3. Check the pool before quoting a number.** `event_quarantine_<fmt>.json` must
exist, match the current era, and postdate the last scrape. If it doesn't, say so and
point at `validate_events.py` instead of reporting the number.

**4. Card legality is necessary and not sufficient.** An Artisan side event passes
every card test and is not the format you're analyzing. So does a Modern team-trios
event on the seat records. Judge events by what they are.

**5. `config/archetype_names.json` is the vocabulary.** Those are the canonical names every
source resolves onto, through `mtg_stats.ARCHETYPE_ALIASES`. Point an alias at a name
the manifest doesn't carry and you split a deck instead of merging it. A test fails if
you try. The archetype notes in
`skills/mtg-tournament-analysis/reference/archetypes/` are local working notes: they
stay out of the repo and out of the bundle, and a fresh install has none.

**6. Naming a deck is three steps.** Add the name to the manifest, write the note,
then add the alias. Never fewer.

**7. Shell scripts are strictly ASCII.** Windows PowerShell 5.1 reads a BOM-less file
as ANSI, and one em dash kills string termination. This has broken the pipeline twice.
A test now fails on any byte above 127 in a `.bat`, `.ps1` or `.cmd`.

**8. A script that does nothing looks exactly like one that worked.** Every data
defect in this project's history exited 0. Fail closed, and report the count of what
you processed.

---

## Adding a skill

The layout is `skills/<name>/SKILL.md`, so adding one moves nothing else. Two things
are required and both are enforced by tests:

1. **Every SKILL.md carries a `## Related skills in this plugin` table** naming every
   sibling and when to hand off. Adding a skill means updating all the others.
2. **The table names only actual siblings.** A skill that ships separately gets
   mentioned in prose, outside the table. `mtg-price-check` is the standing example.

Then add it to `REQUIRED` in `package.py` so a bundle missing it fails the build
rather than installing quietly, and to the table at the top of this file.

Run `pytest tests/ -q` before committing. `tests/test_plugin_structure.py` and the
sibling test in `tests/test_event_validation.py` discover skills from the folder, so
they'll tell you what you forgot.

---

## Where detail lives

| Topic | File |
|---|---|
| Install, setup, scraping, the full pipeline | `README.md` |
| Reading the format | `skills/mtg-tournament-analysis/SKILL.md` |
| Fixing labels | `skills/deck-check/SKILL.md` |
| Reviewing your own games | `skills/vod-review/SKILL.md` |
| The play ledger, the trend bar, what pace can be measured | `skills/vod-review/reference/play-profile.md` |
| Rules and the stack | `skills/rules-check/SKILL.md` and its `reference/` |
| The canonical archetype names | `config/archetype_names.json` |
| Version history | `CHANGELOG.md` |

**Keep this file under 2,000 tokens.** If an edit pushes past that, move something
into a skill instead. A router that grew into a manual stops routing.
