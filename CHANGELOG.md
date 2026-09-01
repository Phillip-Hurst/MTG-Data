# Changelog

## 1.10.0 - 2026-09-01

The repo carries the plugin, not one person's metagame reading.

### The archetype notes left the repo

- **All 25 archetype notes are out of the repo and out of the bundle.** They were a reading of one metagame at one moment, written from one person's scrape. They go stale the week the format moves, and nobody needs them to run the plugin. `.gitignore` now covers `[C] *.md` inside `skills/mtg-tournament-analysis/reference/archetypes/`, and `package.py` excludes the same path while still shipping the folder's README. They stay on the author's disk, untracked.
- **New `archetype_names.json`**, and it does ship. The canonical names were carried by the note *filenames*, so deleting the notes would have deleted the vocabulary every source's deck label resolves onto through `mtg_stats.ARCHETYPE_ALIASES`. The manifest carries the names and nothing else. An end user needs the names; they do not need somebody else's notes.
- **The alias guard now checks the manifest** rather than the folder, so it holds on a fresh clone where the folder is empty. It fails loudly if the manifest is missing: nothing else defines the vocabulary, and an unverifiable alias table is how "Izzet" once resolved to an archetype that did not exist.
- **`package.py`'s REQUIRED gained the manifest and lost the notes**, so a bundle without the vocabulary fails the build instead of installing and silently merging nothing. The dry run reports canonical names in place of note count. Bundle is 43 files.
- **Naming a deck is three steps now, not two**: add the name to the manifest, write the note, add the alias. `deck-check` says so, and `CLAUDE.md`'s hard-rules list says so.
- **`vod-review` treats a missing archetype note as the normal case**, not an error. It builds the card list from what the match revealed, says which cards it had to learn from the game itself, and writes the note afterwards so the next review starts ahead.
- The folder README was rewritten from "here are the notes" to "here is what belongs here and why it arrives empty", including the precedence rule between tournament data and personal experience.
- **137 tests.** The three that pinned shipped notes now pin the opposite: the manifest exists and is populated, working notes are excluded from the bundle, and the folder README still ships.

## 1.9.0 - 2026-09-01

One profile per deck, a cross-deck layer above them, and a place to put matchup experience without pretending it's data.

### A profile per deck, and a player above the decks

- **`play_profile.py` now writes `[C] Play Profile - {deck}.md` for every deck in the ledger**, alongside the cross-deck `[C] Play Profile.md`. Deck names are sanitised into the filename, so a name with a slash in it can't write outside the insights folder.
- **A habit seen with one deck is the deck's habit, not the player's.** It could be the archetype, the matchup, or a week of practice. It stays in that deck's note, counted and named, and the cross-deck note lists it under "single-deck so far" rather than claiming it. A second deck showing the same `kind` promotes it: `MIN_DECKS_FOR_PLAYER_HABIT` is 2, on top of the ordinary trend bar. The Trends, Watching and Faded tables in the cross-deck note now hold cross-deck habits only, and every habit row carries the decks it was seen on.
- **The deck note carries what is specific to that deck**: its habits with the bias-discount and intent-mismatch lines, its matchup record, its boarding, and its kept hands.
- The confirmation-bias discount and the execution-versus-judgement line moved down to whichever note reports the habit, so a single-deck habit can't lose its caveat on the way.

### Matchup experience, filed as experience

- **New `## Matchups played (personal experience)` in each deck note.** Games reviewed, record, and the sample verdict. **Under 20 games (`MEANINGFUL_MATCHUP_GAMES`) it prints as "anecdote", in that word.** It never prints a win rate: three games cannot support a percentage.
- **The precedence rule is written into three places** so nothing can quietly forget it: the deck note's own header, `vod-review`'s Step 2, and the archetypes README. **Large-sample tournament data beats personal experience at every sample size.** Where the two disagree, the archetype note's `## Matchup data` table stands and the disagreement is worth a sentence, not an edit.
- **`vod-review` may append `## Personal experience (small sample, not tournament data)`** to an archetype note, under the matchup table and never inside it, with the sample size in the header and opponent handles left out. Cards and interactions still go in Key cards and Key tricks, because those are facts about the format rather than facts about one night.
- **`mtg-tournament-analysis` now knows those sections exist and that they are not data.** Its Related-skills section says never to fold them into `## Matchup data`, never to let them move a number, and never to quote them as field evidence.

### Sideboarding is now countable

- **New `sideboard` field on the ledger row**: what came in, what went out, per game. It rolls up per opponent archetype in the deck note, so "this card comes in every matchup and has never mattered" becomes a claim with a count behind it.
- **Boarding is counted per game, not per copy.** Four copies of one card in one game is one decision, and counting copies would report a four-of as four times the habit of a one-of.

### Honesty fixes

- **A habit whose wordings don't agree is labelled by its kind.** Seven findings written seven different ways, headlined by whichever came first, reads as a much narrower claim than the ledger supports. A single wording only earns the headline when it covers at least half the occurrences.
- **136 tests, up from 124.** New ones pin the one-deck-versus-two-decks rule, per-deck rollups, the deck-name path guard, the anecdote threshold and its wording, boarding counted per game, and the habit-label rule in both directions.

## 1.8.1 - 2026-09-01

`vod-review` writes down the hand, and looks up the opponent's cards before it grades.

### The kept hand is now evidence

- **Every reviewed game records the hand that was kept, card for card**, in a new `hand` object on the ledger row: `kept_at`, `lands`, `cards`, `shape`, `outcome`, and an optional one-line `note`. A mulligan finding without the hand behind it can't be argued with, and the hand is the one part of a game that isn't recoverable later: the replay shows it for four seconds and then it's gone.
- **`shape` is judged on what was knowable at the keep, `outcome` on what the draw did afterwards**, and they're separate fields on purpose. `lands-and-spells` that came out `screwed` is variance. `land-light` that came out `neither` is still a bad keep that got bailed out. Collapsing the two is how outcome bias gets into a mulligan grade.
- **Both vocabularies are fixed** (seven shapes, four outcomes), same rule as `kind`, with a test asserting they match the reference note.
- **The script rejects a hand whose card list disagrees with `kept_at`.** A hand transcribed wrong still gets counted, and the count is the whole point.
- **New `python play_profile.py --hands`**: the index of kept hands, newest last, card for card, with deck, result, and what the draw did. "What am I actually keeping against this deck" is now a count rather than an impression.
- **The profile gained an Opening hands section**: games by kept size with record and mean lands, the shapes kept, the screwed/flooded split, and the most-kept cards.
- `hand` is optional in the schema so ledger lines written before this stay usable, and not optional in a review: a game whose source showed the hand and got logged without one has thrown the evidence away.

### The archetype notes are the review's working memory

- **New Step 2 sub-step: build the card list before grading anything.** The archetype note's Key cards and Key tricks tables get read for both decks and held open, because a grade written without them is a grade written against a deck nobody looked up.
- **Write down the interaction, not the name.** The review's new **Cards that mattered** section carries one line per card: what it does that the line had to respect, verified on Scryfall. "Hydro-Man" is a name. "Becomes a land at his end step until his next turn, so sorcery-speed removal on your turn can never target him" is what decided the game.
- **A card that decided a game and isn't in the archetype note gets added to it**, with its verified text and the date, and the review says so. The next review of that matchup starts knowing what this one learned the hard way.
- The review template gained **Cards that mattered** and **Opening hands** sections, and the Rules list gained the two matching rules.
- **`[C] Izzet Spellementals.md` gained Hydro-Man, Fluid Felon and Colorstorm Stallion**, both Scryfall-verified, plus a Key tricks section on why Hydro-Man is structurally unanswerable by a control deck's sorcery-speed removal. Found the hard way in a 2026-09-01 ladder match.
- **124 tests, up from 114.** Ten cover the hand: storage card-for-card, counting by kept size, the card-count-versus-`kept_at` guard, the two vocabularies and their bounds, an older line with no hand staying usable, and both profile branches.

## 1.8.0 - 2026-08-31

`vod-review` asks before it grades, and remembers between sessions.

### It asks what you were thinking

- **New Step 4: the interview.** The review now asks the player about the decisions it flagged before grading any of them, because a review that skips this is guessing at the reasoning and then grading its own guess. Three questions, capped at three per match, batched into one round: what was the read, what were you playing around, and was this card in the picture.
- **The third question is the one that teaches.** It names a real card from the opponent's archetype (the note's key-cards table, or `card_signal.py`'s rogue and deviation lenses for cards the field has started playing that the note hasn't caught up to) and asks whether it factored in. Three conditions before it can be asked: the archetype actually plays it, it was live at that moment, and knowing about it changes the line. If no card clears all three, the question gets skipped. A manufactured trap teaches the player to distrust the review.
- **The interview moves grades, which is the point of doing it first.** A sound read whose line still lost is `correct`, and the interview is what proves it. A player who named the right card to play around and then made a play that didn't account for it has an execution problem rather than a judgement problem, and those need different practice.
- **"I don't remember" is recorded as an answer.** A decision that left no memory of the reasoning behind it is usually a fast one.
- **Testimony is not evidence.** What the player says goes in the note as their account, and where the account and the line disagree the review says so.

### It builds a play profile

- **New `play_profile.py`.** Reads the ledger, applies the trend bar, and rewrites the profile note. Stdlib only, like `mtg_era.py` and `rules_lookup.py`. `--validate` checks the ledger and writes nothing, `--dry-run` prints the profile it would write, `--json` gives the counts for answering a question straight, and `--min-occurrences` / `--min-sessions` move the bar without touching the counting. Exit codes carry meaning: `0` clean, `1` couldn't run, `2` ran and found ledger lines it couldn't use. **The skill no longer counts by hand**, because counting from memory across a dozen review notes is how a habit list turns back into a vibe.
- **New `play_log.jsonl` and `[C] Play Profile.md`**, both in the insights folder. The ledger is append-only, one object per game. The profile is generated, never hand-edited: an edit to it is gone on the next run, so corrections go in the ledger line.
- **`kind` comes from a fixed vocabulary** of ten decision types. This is the whole reason the ledger works: free text can't be counted, and a habit spelled three ways splits into three habits. Same failure the archetype alias table exists to prevent.
- **The bar for a trend is 3 occurrences across 2 or more sessions.** Two occurrences on one night is one bad night. Two go in a Watching section, named and counted with no conclusion drawn. Every profile line carries its count and its date range, and a line without one gets deleted rather than softened.
- **Strengths are tracked to the same bar**, and a habit that stops appearing moves to Faded with the date last seen. A profile listing only leaks is the default failure of automated review and the reason players stop reading them.
- **Pace is measured, not guessed.** A VOD gives real seconds per turn from its timestamps, untapped gives duration over turn count, a pasted log gives nothing and says so. MTGO and Arena logs carry no usable timing and none gets derived. Beyond that there are six proxy tells (tapped the wrong mana, cast before the land drop, missed trigger, and so on): one is noise, two in a game is a signal. **Losing is not evidence about speed.**
- **The confirmation-bias guard.** The profile is read at the start of a review and written at the end, which makes it easy to find the habit you expected. So findings are formed from the game first, the profile is checked second, and anything found only at that second pass is flagged `prompted_by_profile` in the ledger so its count can be discounted. Where the profile predicts a habit this game doesn't show, the review says that out loud. A profile nothing can contradict has stopped being a measurement.
- **Asking for the profile with no game attached** ("what are my bad habits", "am I playing too fast") answers straight from the ledger, reports the sample size in the first sentence, and says the sample is thin instead of inventing a profile from four games.
- Both files stay out of the repo and out of the bundle. They're the user's game history and the repo is public.

### Housekeeping

- **New `skills/vod-review/reference/play-profile.md`**: the ledger schema, the `kind` vocabulary, the pace measures and tells, the trend bar, and the profile note template. Ships under `skills/`, so `package.py` already carries it.
- **114 tests, up from 77.** `tests/test_play_profile.py` covers one test per rule the profile's credibility rests on, plus the guardrails: a clean game with no findings is valid, an unknown `kind` is rejected rather than counted, one malformed line doesn't take the ledger down and doesn't vanish either, an unreadable ledger is not an empty one (OneDrive raises `OSError` on a cloud-only placeholder that lists fine), the second run is a no-op that leaves no spurious backup, a rewrite backs up the previous note first, a missing ledger exits 1 instead of writing an empty profile, and the module is pure ASCII so a cp1252 Windows console can't die on the reporting step after the work is done. One test asserts the script's vocabularies and the reference note haven't drifted apart, because a comment is not a guard.
- `package.py` `REQUIRED` gained `play_profile.py`, so a bundle missing it fails the build rather than installing a skill whose Step 7 calls a script that isn't there.
- `vod-review` now asks which deck you were on and what you were up against before reading the source, rather than inferring both off the log. Step 2 still reads it off the reveals when the player doesn't know.
- The router table in `CLAUDE.md` gained a row for the habit question.
- **`package.py` and `.gitignore` now exclude `play_log*.jsonl`, with a test pinning it.** Caught before the ledger existed: `.jsonl` fell through every exclusion rule to `return True`, and in the flat no-setup workflow `mtg_paths.resolve_output_dir` resolves the insights folder to the script's own folder, which is the repo root. So a ledger written by the default install would have been committed to a public repo and shipped in the next bundle. Same shape as the 2026-08-29 archetype-notes bug, opposite direction.

## 1.7.0 - 2026-08-30

Two new skills, and a router note so a reader knows which of the four to open.

### Reviewing games, not just fields

- **New skill: `vod-review`.** Reviews your own play from an untapped.gg match replay, a YouTube gameplay VOD, or a pasted MTGA/MTGO log. The rule it enforces is judging a decision on the information available when it was made, rather than on what the top of the library turned out to be. Grades land in three buckets: punt, close, and correct-but-lost, and the last one is the most useful and the most under-used.
- **New skill: `rules-check`.** Answers rules questions by quoting the current Comprehensive Rules with the rule number, never from memory. `vod-review` hands priority and timing questions here rather than guessing, because a review's whole finding often rests on whether a response was possible.
- **New `rules_lookup.py`.** Scrapes the WotC rules page for the current dated CR text file, caches it beside the scripts, and refreshes after 14 days or when WotC publishes a newer one. Lookup by rule number (`117.3b`), by section (`704`), by keyword, or in the Glossary. Stdlib only, like `mtg_era.py`. It prints the CR version with every result, so an answer can be traced to a document and re-checked after the next set.
- **New `skills/rules-check/reference/rules-and-the-stack.md`.** The working summary: priority, the stack, triggered abilities, state-based actions, layers, combat, replacement effects. Verified against CR 20260819. It also draws the line the CR doesn't cover, because deck registration, missed triggers and slow play live in the tournament documents, and answering those with a CR number is a confident way to be wrong at an event.

### A router for the plugin

- **New `CLAUDE.md` at the repo root.** A routing table sending a question to the right skill, the data stack drawn as a flow, a table of which consumer reads which file, and the eight hard rules. It ships with the plugin and `package.py` fails the build without it.
- The "which consumer reads which file" table is the one worth reading. Fixing data means fixing the file the consumer reads, not the one that looks canonical, and that has caused four separate bugs here.

### The era now applies to every file an analysis reads

- **`validate_events.py` cleans the source caches, not just the CSVs.** The era mechanism shipped in 1.5.0 and was only ever enforced against melee CSVs. Three weeks later `mtgo_classifications.json` still held rows dated 2026-06-03, both MTGO dumps still held events from before the window opened, and `melee_deck_cache.json` still held 71 decks running Badgermole Cub. Every script exited 0 the whole time. `build_refs_from_melee.py` worked around the dirty cache with a read-time filter, which is exactly why the references came out clean and nothing looked wrong.
- **Two tests, because the files carry different evidence.** The MTGO files have an event date, so date decides. `melee_deck_cache.json` has no event date at all, so cards decide, using the same `judge_deck` predicate the event validator already trusts. It drops the same 188 decks the reference builder rejects at read time, which is the corroboration that the two agree.
- **The case that needed both: publication date is not play date.** An MTGO dump is stamped with the day it was published, so the league dump published on the morning of a ban is a record of games played the week before it. Three of its six lists run Badgermole Cub. A date-only filter admits all of them. Cards now override an in-era date, at the same 10% threshold the event validator uses.
- **Nothing is deleted.** Removed entries are archived to `archive/through-YYYY-MM-DD/*.pre-era.json` and a one-time `.bak` is kept beside each file. Pre-era data stays readable for cross-era questions.
- `--skip-caches` validates events only. The report gains a `caches` section, so `build_baseline.py` inherits the guarantee.
- Live result on the maintainer's data: 2,421 pre-era entries archived, **0 decks running a banned card left in any of the four files**, and a second run is a no-op.

### Housekeeping

- `package.py` `REQUIRED` gained the router, both new skills, the rules reference and `rules_lookup.py`, so a bundle missing any of them fails the build instead of installing quietly.
- **55 → 77 tests.** `tests/test_cache_cleaning.py` covers one test per defect above plus the safety properties: dry-run writes nothing, the backup is never overwritten by already-cleaned data, a deck that can't be judged is kept rather than dropped blind, and a file dropping off the covered list fails the suite.
- Both existing SKILL.md files name the two new siblings, per the standing rule. The sibling tests discover skills from the folder, so they caught this rather than a human remembering.

## 1.6.0 — 2026-08-30

Two things: the repo is a plugin with more than one skill now, and the event pool gets validated against cards instead of trusting what melee says about itself.

### Now a plugin, and built to take more skills

- **The plugin is `mtg-data`** (was `mtg-tournament-analysis`, which collided with the name of a skill inside it). Existing installs need a reinstall under the new id.
- `SKILL.md` moved from the repo root to `skills/mtg-tournament-analysis/SKILL.md`. A root `SKILL.md` alongside a `skills/` folder risked double-registering on install.
- **New skill: `deck-check`.** It assigns archetype names and pushes them into the pairing and standings CSVs the win rates are built from. `mtg-tournament-analysis` no longer categorizes anything; for a deck it can't name it reports the cards performing in it and hands off.
- **New `.claude-plugin/marketplace.json`**, so the repo installs directly: `/plugin marketplace add Phillip-Hurst/MTG-Data`. `setup.py` is still required after install, because the scrapers run on your machine rather than in a Claude session.
- **Standing rule, enforced by a test:** every skill in a multi-skill plugin carries a `## Related skills in this plugin` table naming its siblings and when to hand off. Adding a skill means updating the others, and `test_every_skill_in_this_plugin_names_its_siblings` fails if you don't.
- The 25 archetype notes ship at `skills/mtg-tournament-analysis/reference/archetypes/`. Those filenames are the canonical vocabulary that every source's deck names resolve onto.
- **`package.py` rewritten.** It builds `mtg-data.plugin` in the plugin directory layout, including `.claude-plugin/plugin.json` and everything under `skills/`. The old version decided exclusions on the bare filename, so every `.md` not literally called `SKILL.md` was dropped: all 25 archetype notes, silently. It now decides on the relative path and fails closed if the manifest, either skill, or the archetype notes come out missing.

### The event pool

- **New `validate_events.py`.** Judges events by their decklists, not their names or their metadata. Verdicts: `off-format`, `pre-era`, `variant`, `seat`, `unverified`, `ok`. Failures are quarantined out of the combined CSVs and renamed out of the per-event glob, with `*.raw.csv` preserved. Runs automatically after every scrape.
- **Two bugs in `mtg_fetch.py`, both now fail closed.** Every date filter sat behind `if date_val:`, so an undated row skipped the window check and was admitted. And the format filter matched `"magic"`, which appears in `GameDescription` on every event of every format, which is how a Modern team-trios event entered a Standard pool. Undated events are now skipped and reported with a copy-pasteable command.
- What that missed: 1,316 of 1,708 pairing rows didn't belong. A pre-ban paper event, the Modern team event, and an Artisan side event whose every card is Standard-legal. **Card legality is necessary and not sufficient.** Nothing errored, and a published note carried a banned deck at 6.8% of a "post-ban" metagame for 17 days.
- Per-event CSVs that fail validation are renamed `*.quarantined.csv`. `matchup_matrix.py` and `winrate_analysis.py` glob the per-event files and skip the combined one, so cleaning only the combined file left bad events invisible to the snapshot and fully visible to the matrix.
- Validation discovery unions the combined and per-event sources, so a second run sees what the first run saw. Reading only its own cleaned output made it non-idempotent.
- **New `build_card_pool.py`**: caches a format's legal card names from Scryfall (5,365 for Standard) into `card_pool_<format>.json`.
- **`build_baseline.py`** refuses to snapshot when the quarantine report is missing, built for a different era, or older than the last scrape. `--skip-validation-check` overrides.

### Archetype references

- **New `audit_refs.py`.** Checks `archetype_refs.json` for banned and off-format references, labels colliding on 60%+ of their slots, thin references that over-match, and coverage against the live field. `--strict` exits non-zero. `--apply-aliases` collapses confirmed duplicates, backing up to `archetype_refs.pre-alias.json` first. Runs after every scrape.
- **`build_refs_from_melee.py`** filters off-era decks out of the deck cache before building. Without it a rebuild produced 45 references, 6 of them Modern, which would then have been matched against live Standard decks. The quarantine had cleaned the CSVs and never touched the cache. It also survives an unreadable CSV instead of aborting the whole rebuild.
- **`build_mtgtop8_baseline.py`** gained the same era guard. Its "last 2 weeks" window isn't era-aware, so running it the morning after a B&R pulls in decks built around a card that's no longer legal.
- Seeding references from mtgtop8 took the unnamed share of a post-ban field from 42% to 24% in one command. `_write_refs` is additive and never clobbers a locally refined reference.
- **`mtg_stats.ARCHETYPE_ALIASES`** went from 1 entry to 13, every canonical name taken from a shipped archetype note. Two new tests: one fails if an alias points at a name with no note, another if the table ever chains A to B to C.

### Cards, corrections, eras

- **New `card_signal.py`**: tracks individual cards across the whole field through four lenses. `rogue` (under 8% of the field, pilots beating the field average), `deviation` (cards outside an archetype's goto build, ranked by how much better those pilots finished), `trend` (adoption moving across the window), `unnamed` (shells grouped by co-occurrence, handed to `deck-check`). Rows resting on fewer than 4 pilots are marked.
- **New `apply_corrections.py`**: reads `Decision:` lines from the Obsidian mislabel notes into `archetype_overrides.json`, then applies them to the deck cache, the MTGO classifications, and every pairing and standings CSV. `--dry-run`, `--list`, `--reapply`, `--backfill`. Exits non-zero when it finds nothing rather than reporting success on an empty run.
- **`mtg_era.py`** gained `MERGE_ANCHOR_DAYS = 14`: a ban and a set release inside a fortnight are one reset, anchored on the earlier date so no results are lost.
- **`set_releases.json`**: added The Hobbit (2026-08-14). It was missing, and the era window had landed on the right date by accident.

### Tests and packaging hygiene

- 26 new tests in `tests/test_event_validation.py` covering the validator, plus the alias, sibling and ASCII rules.
- `test_shipped_shell_scripts_are_strictly_ascii` fails on any `.bat`, `.ps1` or `.cmd` carrying a byte above 127, and names the character. Windows PowerShell 5.1 reads a BOM-less file as ANSI, so a UTF-8 em dash breaks string termination. That killed every scheduled scrape for two days in June and a new script in August. The rule had been a comment both times.
- `test_mtg_stats.py` fixtures switched from `"Izzet"` to `Placeholder Deck A/B`. "Izzet" stopped being a placeholder when it became an alias, which would have broken three counting tests on a naming change. `test_placeholders_are_not_aliased` now guards the fixture.
- `test_live_data_invariants` skips with a clear message when every pairing file is unreadable, instead of crashing on a OneDrive cloud-only placeholder.
- **Two `.gitignore` bugs, found by testing it rather than reading it.** `[C] *.md` read `[C]` as a character class, so it matched files starting `C ` and never ignored the review notes. Unanchored, it also matched at every level, which would have silently excluded the 25 shipped archetype notes. Now `/\[C\] *.md`, verified with `git check-ignore`.
- `.gitignore` also covers `card_pool_*.json`, `event_quarantine_*.json`, `archetype_overrides.json`, `*.quarantined.csv` and `*.raw.csv`.

## 1.5.0 — 2026-08-15

Bans end an era. The data now knows that.

### Format eras
- New `bans.json`: B&R announcements with effective date, format, cards, and the decks each one hit. Seeded with the 2026-08-10 Standard bans (Badgermole Cub, Stormchaser's Talent, Gran-Gran) plus the Legacy and Vintage changes from the same announcement.
- New `mtg_era.py`: resolves the current era for a format as the later of the newest set release and the newest ban. Exposes `resolve_era()` and `previous_era()`, and runs standalone (`python mtg_era.py`, `--json`) to print the window start, the anchor, the slug, and why. Standard library only.
- `mtg_fetch.py`'s `get_window_start()` now anchors on the era instead of reading `set_releases.json` directly, so a ban moves the search window the same way a rotation does. It prints the reason and, after a ban, points at `archive_era.py`.
- `build_baseline.py` writes to `meta_baseline_<era_slug>.json` and stamps each snapshot with its era and start date. A set-only era slugs identically to the old set slug, so baselines written before this change keep their filename and keep meaning the stretch they actually cover. The practical effect: the run-over-run delta in the weekly note can never straddle a ban and report a banned deck as "down 12 points."

### Archiving
- New `archive_era.py`: moves every scraped CSV, the MTGO dumps, the deck cache, and the closing era's baseline into `archive/through-YYYY-MM-DD/`, and writes a `manifest.json` with the era labels, the closing ban, the file list, and row counts. `--dry-run` first.
- This is the part that actually matters: `winrate_analysis.py`, `matchup_matrix.py` and `update_archetypes.py` glob `melee_*_pairings.csv` out of the data folder non-recursively and treat every hit as one pool. Correct inside an era, silently wrong across one. Moving the files down a level is the fix.
- `package.py` excludes `archive/` and now ships `bans.json`. `.gitignore` covers `archive/`.

### Docs
- SKILL.md gains a "Format eras" section: what ends an era, the four-step routine when a ban lands, how to read archived data without laundering it into live numbers, and how to talk about a metagame that's four days old. Step 0 now checks the live ban list against `bans.json` before anything else. Intra-set/cross-set framing is now intra-era/cross-era throughout, and the cross-era layer asks for the mechanism: a deck that cratered because its 4-of got banned isn't a metagame trend.

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
