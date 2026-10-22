# Data quality rules

Every number this project prints comes out of a pool of scraped tournament
results, and scraped results are dirty. Events get tagged with the wrong
format. Pre-ban results sit next to post-ban ones under the same file names. The
same deck turns up under five names. A win rate computed on that pool still
prints to one decimal place, and it still reads like a fact.

So the pool has rules. Each one below has an ID, the code that enforces it, the
tests that pin it, and the failure that made it necessary. A rule with no test is
marked as a gap.

## The failure that started this

On 2026-08-27 the melee.gg fetcher logged "Window start: 2026-08-10, post-ban"
and then scraped events that didn't belong. Among them were a pre-ban Standard
event (660 matches), a Modern team event (184 matches) and an Artisan side event
whose every card is Standard-legal. All of it landed in the combined Standard
files. The weekly snapshot reported Izzet Prowess at 6.8% of a "post-ban"
metagame, 17 days after Stormchaser's Talent, one of its cards, was banned.

Every script exited 0. In that pool, 1,316 of 1,708 pairing rows didn't belong.

## Rules

| ID | Rule | Enforced in | Pinned by |
|---|---|---|---|
| DQ-01 | Results are only compared within one **era**. An era starts at the later of the newest set release and the newest ban for the format; a ban and a release within 14 days count as one reset, on the earlier date. Formats with no set list on file use a rolling window. The shipped set and ban lists always count, even when a data folder carries its own copy. | `core/era.py` `resolve_era` | `test_ban_and_set_release_within_a_fortnight_merge_to_the_earlier_date`, `test_reality_fracture_is_the_current_standard_era`, `test_banned_as_of_respects_the_window_start` |
| DQ-02 | Discovery admits an event only if it has a parseable date inside the window and a matching format. Undated, unparseable and future events are skipped, never admitted by default. | `ingest/fetch_melee.py` | `test_undated_event_is_skipped_not_admitted`, `test_unparseable_date_is_treated_as_undated`, `test_event_before_window_start_is_dropped`, `test_future_event_is_dropped`, `test_game_description_no_longer_passes_every_format` |
| DQ-03 | An event is **off-format** if fewer than 50% of its cached decks are legal, where a deck is legal when at least 95% of its cards are in the format's card pool. The cards decide whether an event passes; an event's name can only add a reason to quarantine it (DQ-05, and melee.gg's own demo events). | `quality/validate_events.py` `judge_deck`, `validate_event` | `test_off_format_event_is_quarantined`, `test_clean_standard_event_passes`, `test_melee_demo_events_are_dropped` |
| DQ-04 | An event is **pre-era** if 10% or more of its decks run a card banned as of the window start. One stale list is a player error; a tenth of the field is the wrong tournament. The ban test runs even when no card pool is cached. | `quality/validate_events.py` | `test_pre_ban_event_is_quarantined`, `test_one_stale_list_does_not_condemn_an_event`, `test_with_no_card_pool_a_pre_ban_event_is_still_caught` |
| DQ-05 | A **variant** event (Artisan, Pauper, Brawl, prerelease) is quarantined even though its cards pass, because its metagame is a different one. | `quality/validate_events.py` `VARIANT_EVENT_RE` | `test_a_variant_event_is_quarantined_even_when_every_card_is_legal` |
| DQ-06 | A mixed-format team event keeps its in-format **seat** when per-player results exist, and is dropped whole when they don't. | `quality/validate_events.py`, `quality/combine_events.py` | `test_mixed_format_team_event_salvages_the_standard_seat`, `test_team_event_without_individual_results_is_dropped_entirely`, `test_the_seat_filter_drops_a_cross_format_pairing` |
| DQ-07 | Fewer than 5 cached decklists is too little evidence. The event is kept and flagged **unverified**, never silently confirmed. | `quality/validate_events.py` `MIN_DECKS_TO_JUDGE` | `test_thin_event_is_flagged_not_dropped` |
| DQ-08 | The combined pool is **derived**. One writer rebuilds it from the per-event files with the verdicts applied; nothing edits it in place, and a rebuild of unchanged input is byte-identical. | `quality/combine_events.py` `rebuild` | `test_rebuild_reads_the_per_event_files_not_the_previous_output`, `test_a_second_run_produces_an_identical_file`, `test_a_second_validation_run_does_not_shrink_the_pool` |
| DQ-09 | Quarantine is **reversible and sticky**. Files are renamed, never deleted; a re-scrape can't bring a quarantined event back; reversing a verdict restores it. | `quality/validate_events.py` `quarantine_event_files`, `quality/combine_events.py` | `test_a_scrape_cannot_reinstate_a_quarantined_event`, `test_a_reversed_verdict_puts_the_live_file_back_in`, `test_quarantined_event_files_leave_the_matchup_glob` |
| DQ-10 | An **unreadable** input fails the step. The combined pool refuses to write; validation exits 1 and names the files, even when it also quarantined something. A missing file is absent, which is different. | `quality/combine_events.py`, `quality/validate_events.py` `read_csv` | `test_an_unreadable_file_refuses_the_write`, `test_an_unreadable_file_means_the_pool_was_not_judged`, `test_unjudged_beats_quarantined` |
| DQ-11 | Source caches are cleaned to the era: entries dated before the window are archived, decks with banned or off-format cards are dropped, undated entries are kept and left undated. | `quality/validate_events.py` `clean_source_caches` | `test_mapping_cache_drops_entries_dated_before_the_window`, `test_deck_cache_drops_decks_running_a_banned_card`, `test_an_undated_entry_is_kept_not_guessed_at`, `test_removed_entries_are_archived_not_deleted`, `test_clean_source_caches_covers_every_file_a_consumer_reads` |
| DQ-12 | **Counting rules.** Byes and rows missing a deck are dropped. Win rate is wins over decided games; draws are excluded. A row whose winner matches neither player is dropped, never counted as a draw. | `core/stats.py` `classify_row`, `win_pct` | `test_bye_is_dropped`, `test_draw_is_a_draw`, `test_unparseable_winner_is_dropped_not_a_draw`, `test_win_pct_excludes_draws` |
| DQ-13 | **One alias table.** Every source's spellings fold together through one table, an alias may only point at a name in `config/archetype_names.json`, and no alias points at another alias. A name with no alias passes through as written. | `core/stats.py` `ARCHETYPE_ALIASES` | `test_aliases_resolve_to_names_the_vault_actually_uses`, `test_no_alias_target_is_itself_aliased`, `test_aliases_are_applied_to_every_source` |
| DQ-14 | **Label precedence:** a human ruling, then a confident classifier verdict, then the organizer's text, then dropped. Every drop is counted and reported. | `classify/deck_labels.py` | `test_override_beats_the_classifier`, `test_classifier_beats_organizer_text`, `test_unconfident_deck_falls_back_to_organizer_text_and_says_so`, `test_drops_are_reported_not_silent` |
| DQ-15 | A human correction reaches the columns the numbers are computed from, and survives the next scrape. | `classify/apply_corrections.py` | `test_corrections_reach_the_columns_the_matchup_matrix_reads` |
| DQ-16 | Archetype references have **one writer**. Malformed entries are rejected, pinned entries are never overwritten, and a full replace has to be asked for and backs up first. | `classify/refs_store.py` `save` | `test_no_script_writes_the_refs_file_directly`, `test_malformed_entries_are_rejected_not_written`, `test_pinned_references_are_never_overwritten`, `test_save_replace_needs_asking_for_and_backs_up` |
| DQ-17 | A week-over-week change is only reported when the two snapshots are comparable: enough players, and event pools that overlap. | `classify/deck_labels.py` `delta_is_honest` | `test_delta_refused_when_the_event_pools_barely_overlap`, `test_delta_refused_on_a_thin_sample` |
| DQ-18 | No snapshot is written from a pool that was never validated, was validated under another era, or was rescraped since. | `analyze/build_baseline.py` `validation_status` | `test_a_snapshot_is_refused_when_the_pool_was_never_validated`, `test_a_snapshot_is_refused_for_a_pool_validated_under_another_era`, `test_a_snapshot_is_refused_after_a_rescrape` |
| DQ-19 | Win rates carry their **uncertainty**: a 95% Wilson interval in the win-rate tracker, the archetype notes and the tier list. Matchup cells under 10 decided games aren't printed. | `core/stats.py` `wilson_interval` | `test_wilson_interval_matches_the_textbook_values`, `test_wilson_interval_at_the_matchup_floor_is_wide` |
| DQ-20 | **Same input, same output.** Ties break on a stable key, never on dictionary or set order. | `classify/cluster_shells.py`, `analyze/winrate_analysis.py`, `analyze/card_signal.py` | `test_a_shells_core_cards_break_ties_on_the_name`, `test_a_second_run_produces_an_identical_file`, and `scripts/check_determinism.py` against real data |

Paths are under `src/mtg_data/`. Tests are in `tests/`; `pytest -k <name>` runs one.

## What a run leaves behind

Each validation writes a report, and each rebuild writes a sidecar describing the
pool it produced. Between them you can answer "what's in this number" without
rerunning anything.

**`event_quarantine_<format>.json`** records when the run happened, the window it
judged against, the banned list at the window start, the thresholds it used, and a
verdict with a reason for every event.

**`melee_<format>_all_coverage.json`** records how many rows were available, how
many were kept, which events were dropped and why, and any files that couldn't be
read.

**Every archetype reference** carries how many decklists it was built from, where
they came from (melee.gg cache, MTGO classifications, mtgtop8 or a manual entry)
and the date it was last updated. That is what lets a merge decide which version
of a reference to keep.

Here is the coverage sidecar from a real run on 2026-10-12:

| | Pairings | Standings |
|---|---:|---:|
| Events in the folder | 53 | 41 |
| Events kept | 36 | 30 |
| Rows available | 2,877 | 2,976 |
| Rows kept | 1,795 | 585 |
| Dropped as off-format | 15 events | 9 events |
| Dropped as variant | 2 events | 2 events |

38% of the pairing rows that run scraped never reached a win rate.

## Gaps

These are the places the rules above don't reach yet.

- **Melee results carry no event date.** The per-event CSVs have a tournament ID
  and no date. The era split is enforced at discovery and by the validator's
  card checks; a date column every reader could filter on would be stronger.
  This is the oldest open defect.
- **No raw snapshots.** The scrapers parse as they go. If melee.gg changes what a
  page returns, there is no stored copy of the original response to diff against
  or re-parse.
- **1,094 pairing seats had no deck URL** in the pool as of 2026-10-12, so the
  scraper captured nothing to name them by. They're counted and reported as unnamed, and
  they shrink every sample.
- **The card pool fallback is permissive.** With no card pool cached, validation
  runs the ban test alone and says so, but off-format events get through. Setup
  builds the pool, so this only bites a hand-made data folder.
- **The determinism check needs real data.** `scripts/check_determinism.py` found
  the tie-breaking defects, and it runs against scraped data that isn't in the
  repo, so it isn't in CI.
