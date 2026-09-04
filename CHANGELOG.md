# Changelog

## 1.15.0 - 2026-09-04

Blind mulligans and informed mulligans are two decisions, the profile opens with
one classification table, and four grades changed after an audit against the
review notes.

### A game 1 mulligan is made in the dark

- **`phase` splits into `mulligan-blind` and `mulligan-post-board`.** A game 1 keep can only be judged against the format. A game 2 or 3 keep is judged against a deck already seen, and the same six cards can be a keep in one and a ship in the other. Grading them together averages a blind decision with an informed one and reports the mean as a habit.
- **The 2026-09-01 Izzet Spellementals punt is the case that proves it.** Bottoming Erode off a two-land six was a punt entirely because two games had already shown that their whole battlefield costs two and three. Blind, it is a close call about a one-mana instant against an unknown deck.
- **A phase has to agree with its game number**, and the script checks. A blind mulligan is game 1; boarding happens between games. A phase that disagrees means one of the two is wrong and the finding lands in the other kind's counts.
- **New `## Mulligans` section** in both profile notes, and `rollup["hands"]["by_knowledge"]` splits the kept hands into blind and post-board with their own record, mean lands, sizes and outcomes. `--hands` labels every row.
- **A pattern's own count stays whole**, and its line reports the phase mix instead. Splitting the counts as well would put a two-occurrence habit below the bar twice and report neither.
- What it surfaced on the first run: all 6 graded mulligans split 3 blind and 3 post-board, and **both punts are post-board**. Blind keeps grade 2 close and 1 correct across 25 hands; post-board keeps grade 2 punt and 1 close across 13. The 14-11 against 4-9 record split is confounded, because you only reach game 3 after a split, but the grades are not.

### One table for strengths and weaknesses

- **Both profile notes open with `## At a glance`:** one row per pattern that cleared the bar, with its classification, kind, count, grade split and deck count. Sorted leaks first. The per-bucket sections below still carry the argument and the citations.

### The grade audit

Four grades changed, each read against the five review notes rather than the
one-line ledger note. The test applied: does the note name a better line and
offer no counter-argument? Then it is a punt. Does it argue the other side? It
stays a close. Was no better line available with the cards in the 75? Then it is
correct-and-lost-anyway.

- **UW mirror g2 t10, `casts-flash-threat-on-own-turn`: close to punt.** The note says "There's no version of this turn where main-phasing her is better" and then grades it a close because Erode killed her either way. That second half is outcome reasoning, which is the one thing the skill exists to forbid.
- **UW mirror boarding, `boards-without-an-answer`: close to correct.** The note says the absence of an answer to an indestructible Captain Marvel is "true of the 75, not just the 60". If no configuration of the 75 answers it, the boarding was not the error and the deckbuilding is the finding.
- **Charbelcher g2 and g3, `cuts-the-tutor-for-the-card-brought-in`: close to punt, both.** The note names the better line, argues no other side, and records it as "a 15 you decided on rather than a slip".
- Buckets and the work-on line are unchanged by all four, which is the result you want from an audit: the grades got more honest without the conclusions moving.
- 6 new tests, 163 passing.

## 1.14.0 - 2026-09-04

The play profile counts patterns instead of decision categories. Found by
reviewing what the profile actually said after 41 games: four "trends", every
one of them labelled `removal-timing decisions (16 wordings)` or its
equivalent, with `removal-timing` listed as a trend and a strength in the same
note.

### The habit is now an entity

- **New: `play_patterns.json`**, the pattern registry. Every finding names a `pattern_id` from it, and that is what the rollup counts. 22 patterns seeded from the 46 findings already in the ledger. It ships, because a pattern is a general fact about how Magic decisions go wrong rather than a fact about one player, and `play_profile.py` exits 1 without it.
- **`kind` was never able to do this job.** Every game contains removal-timing decisions, so kind occurrences accumulate with games played rather than with mistakes made: any kind clears a three-occurrence bar within a few sessions no matter how well someone played. Kind stays as the coarse category, and a finding's kind has to match its pattern's.
- **`_label_for` is gone**, along with the two tests that pinned its fallback. A label built by guessing at the most common free-text wording can never find a majority when every finding is worded once, which is why all four headings read "(N wordings)".
- **An unknown `pattern_id` is rejected, not counted.** Same discipline as `mtg_stats.ARCHETYPE_ALIASES`, for the same reason.
- **`polarity` in the registry is checked against the grades.** A pattern declared a leak that keeps grading correct gets a **Registry disagrees with the grades** section naming it, because one of the two is wrong.

### One pattern, one bucket

- **Leak, strength, mixed, watching, below-bar or faded. Exactly one.** The old code computed "trend" and "strength" independently off the same row and could print both, which it did on 2026-09-04.
- **A punt counts double a close in the work-on ranking.** Weighting them equally named a pattern with 6 closes and 0 punts as the thing to work on. Three rankings have failed here now, so the reference note carries all three.
- **Fading is measured against the sessions where that pattern's deck was played.** Measuring against all recent sessions faded every Yawgmoth pattern the moment three UW sessions went by, which reports a habit as cured on no evidence.

### The prose stops at the review note

- **Nothing quotes the ledger any more.** A finding carries `pattern_id`, `grade`, a `review_note` pointer and an optional `note` capped at 300 characters that is never rolled up. Every profile line ends in a **Read it in:** citation instead.
- The cross-deck profile went from 11.2 KB to 6.4 KB. `--json` went from 53.4 KB to 18.5 KB, having been *larger* than the 45.9 KB ledger it summarised, and now drops single-occurrence patterns and the card-for-card hand index. `--json --full` restores them.

### The schema is closed, and it was silently dropping data

- **An unrecognised key is a problem, not a passing value.** The 2026-09-04 review wrote `opening_hand` where the schema says `hand`, for all three games of a match. Those rows validated clean, the run exited 0, and the hand count reported "35 of 41", which reads as six games whose source never showed a hand. Three of them were transcription loss. Recovered: 38 of 41 now.
- **`(match_id, game)` has to be unique.** Appending the same game twice doubled every count it touched and nothing could see it happen.
- **`session_id` is recorded, not derived from `date`.** The trend bar rests on it, and two sittings in one day used to collapse into one while a session past midnight split into two.
- **`turn` belongs to an `in-game` finding only**, with a new `phase` of `mulligan`, `sideboard` or `in-game`. It used to be a required integer with 0 for "before the game started", and the profile printed `Turns: 0, 0, 0, 0, 0, 0, 0, 0`.
- **`--validate` distinguishes a rejected row from a game that lacked the data.** Folding the two together is what made the hand gap look legitimate.
- `package.py` gains `play_patterns.json` in `KEEP_JSON` and in `REQUIRED`. Without the first, the `.json` suffix rule dropped it and the bundle installed cleanly and then refused to run.
- 29 new tests, 157 passing.

## 1.13.0 - 2026-09-04

The replay viewer is gone from `vod-review` as a reading path, and the log is the
only source. Found while reviewing a 22-match, 29-game Historic cluster in one
session, which the old flow could not have afforded.

### The replay viewer was never worth its cost

- **`vod-review` reads the logs and does not step the replay viewer.** The viewer costs one browser round trip per game state and a three-game match runs to several hundred of them. The log is one fetch and holds strictly more. Stepping the viewer to establish a fact the log already carries is now called out as the mistake it is.
- **The viewer opens for two reasons only:** the user asked to see a board, or the log endpoint 404s on an incomplete upload. The skill has to say which one it is.
- `reference/untapped-sources.md` is retitled "the index and the log", and every "default to the log" hedge is now a rule.

### New source: the games index, one call for a whole cluster

- **`api.mtga.untapped.gg/api/v1/games/users/<userId>/players/<playerTag>/?card_set=<CODE>`** enumerates every match with per-game results, `game_duration_seconds`, `active_player_id`, opening-hand counts and the bottomed card's `grpId`, without fetching a single log. A pasted deck-page URL carries the `userId`, `playerTag` and `friendly_deck_id` it needs.
- **`card_set` is required and has to be a real Arena set code.** No "all" value: anything else is a `400 Invalid card set`, a set the account can't see is a `403`. Codes come from `mtgajson.untapped.gg/v1/latest/cards.json`, newest last.
- **Pace no longer comes from parsing `[UnityCrossThreadLogger]` timestamp headers.** `game_duration_seconds` over the log's turn count is the same `untapped-duration` measure for a fraction of the work. A 0-turn game (immediate concede) gets `measure: "none"`, not a divide by zero.
- **Mulligans come from the index too.** `player_opening_hands` length greater than 1 means a mulligan, and `player_mulligan_put_on_bottom` names the card. The log's hand snapshots dedupe to the *second* seven rather than the six, so the six is reconstructed as that seven minus the bottomed card. `players[].mulliganCount` is usually absent and is no longer relied on.

### The active player is not the caster (new trap 2)

- **Labelling a `ZoneTransfer` by `turnInfo.activePlayer` marks every instant the opponent casts on your turn as yours.** A Golgari Yawgmoth digest came back showing the player casting Bitter Triumph and Lightning Axe, neither of which is in the deck. They were the opponent's removal, cast during the player's own turn.
- Label by `ownerSeatId` from `gameObjects[]`, carried across `ObjectIdChanged` alongside `grpId`. Keep the active player as separate information, because "sacrificed on their turn" and "sacrificed on my turn" are different decisions.
- Trap 4 now also warns that `CounterAdded` targets resolved from a stale id map are unreliable, which is how a +1/+1 counter gets reported as landing on a land.

### The two-pass rule, which is where the token cost lives

- **Pass one produces candidates, never findings.** One parse per match into a line-per-event digest: 40 to 250 lines per game, readable in one call, enough to see the shape of all 29 games.
- **Pass two traces only the shortlist.** Annotation stream in order, battlefield with tap state, `ManaPaid`, `TappedUntappedPermanent`, `RevealedCard*`, for the two or three turns in question.
- **A trace killed roughly half the candidates in the first cluster it ran on**, including a confident "he had the uncounterable four-drop and cast a two-drop instead" that the tap trace answered with three mana sources.

### Nonland mana sources have restrictions, and they flip findings

- Added to trap 0: **Delighted Halfling** makes any colour but only for a legendary spell, **Phyrexian Tower** makes `{C}` or `{B}{B}` and can never pay a green activation cost, and **Badgermole Cub** adds its extra `{G}` only when a creature is tapped for mana, which a sacrifice-for-mana land does not do. Each of these decided a line in the first cluster.

### Hand-reveal effects are gradeable

- **`AnnotationType_RevealedCardCreated` gives the opponent's full hand** on a Thoughtseize or a Duress, one annotation per card, followed by their `ZoneType_Hand` with the taken card gone. That is the only way to grade the choice, and it has to be graded on that hand plus their available mana, never on what they drew afterwards. A Thoughtseize that left a Goblin Charbelcher behind graded `correct` on this rule, because their revealed hand held no way to cast it.

### Operational notes that cost a session's time to learn

- **`upload-log` rate limits.** Sustained pulls return 429. Sleep about 3 seconds between logs, back off 7 on a 429, retry up to 5 times. A 429 body has a `detail` key and **no `log` field**, so check `typeof j.log === 'string'` rather than throwing on `undefined.indexOf`.
- **The browser's JavaScript call caps at about 45 seconds**, which a throttled batch outlives. Park the run on `window` with `.then()` and poll it; make the batch skip already-parsed ids so a retry after a timeout is free.
- **Strip query strings from anything echoed back.** The extension refuses a result that looks like cookie or query-string data and returns `[BLOCKED: Cookie/query string data]` instead of the value. Reading `performance.getEntriesByType('resource')` trips it. Return `host + pathname`.
- **Reset per game.** A `gameNumber` change means zeroing the turn counter and dropping the id maps, or game 2's opening hand never gets captured because the snapshot only fires while `turnNumber === 0`.

## 1.12.0 - 2026-09-04

Three defects, all found while reviewing one match, all of which had already put a
wrong line in a shipped note.

### The work-on line named a strength

- **`play_profile.py` ranks "what to work on" on `punt` and `close` occurrences, never on total occurrences.** The profile listed removal-timing as a strength, 10 correct of 12, and named it as the thing to work on, in the same note. A decision type someone keeps getting right is one they keep making, so it accumulates occurrences faster than the leak and wins a ranking built on volume. Habits flagged as a strength are now ineligible, ties break on total occurrences then `kind`, and the line prints the grade split it ranked on so a reader can argue with it.
- **When every trend that cleared the bar is a strength, the line says so and names nothing.** Filling the heading with the least-good strength makes the profile unreadable as a measurement. New `problem_occurrences` field on each habit carries the count.
- Two tests pin both behaviours, and the rule is written out in `reference/play-profile.md` and the SKILL.md decision table.

### Sideboarding was one finding per match, not one per game

- **Games two and three each get their own `sideboarding` finding.** They're boarded off different information, so they're two decisions. One row per match loses the second one, and it loses the more interesting case entirely: a player who cuts a card for game 2 and puts it back for game 3 has already found the mistake. That happened this match with a Spell Snare, and the single row missed it.
- **Build the in and out lists by diffing the decklists in the log, and check the counts balance.** An in-list shorter than its out-list means a card got missed, which is how "he cut that and never brought it back" gets written about a player who brought it back the next game. That also happened this match.
- The review template now carries a graded block per post-board game.

### Lands in play is not usable mana

- **New trap 0 in `reference/untapped-sources.md`.** A **stun counter** (`AnnotationType_CounterAdded`, `counter_type: 172`) means the land's next untap step is spent removing the counter, so it sits tapped through a turn it looks entitled to (CR 122.1d). Magmatic Hellkite and the rest of the "basic land tapped with a stun counter" family do this. A turn-11 finding in the Boros Dragons review was written as though six lands meant six mana when the real number was five.
- The note also covers colourless-only lands against coloured costs, and lands that entered tapped this turn. **The settling check is `ManaPaid` summed against the untap-step `TappedUntappedPermanent` count**, and it runs before any "he could have held X up" line.

### Reading a card is not the same as reading its text

The same turn-11 finding then went wrong a second time, in the other direction, and the
mana count wasn't the reason. Beza, the Bounding Spring has four conditional clauses and
they were graded as a block, so the review concluded the player's plan was impossible
when it was available one play later in the sequence. The player caught it.

- **New section in `SKILL.md` Step 2, four checks in order.** Split a conditional ability into one clause per condition and evaluate each against the state at the moment it's read. Work out *when* it's read: an "if" immediately after the trigger condition is an intervening-if, checked on trigger and again on resolution (CR 603.4); an "if" anywhere else is ordinary English, read once as the ability resolves in written order (CR 608.2c). Ask what the player could still do afterwards, because CR 305.1 allows the land drop any time they have priority in a main phase with the stack empty, and a trigger that counts lands or cards in hand is decided by that order. Then count mana from `ManaPaid`.
- **`rules-check` is now a required handoff, not an option.** The sibling table says to go get the rule whenever a finding rests on when a condition is evaluated, and the review cites the number it got back. A grade built on a remembered rule is the one error the player has no way to check.

## 1.11.0 - 2026-09-02

An untapped match URL is two sources, and `vod-review` now knows which one to read.

### The log, not the replay

- **New `skills/vod-review/reference/untapped-sources.md`.** The replay at `mtga.untapped.gg/replay/<shortId>` is a board viewer that steps one game state at a time; the log at `api.mtga.untapped.gg/api/v1/upload-log/<shortId>` is the raw MTGA client log the viewer is built from. A three-game match is hundreds of game states or one fetch, and the log holds strictly more: mana payments, priority order, counters added, mulligans, both decklists, and every sideboard swap without asking the player to remember it. The note carries the fetch recipe, the brace-matching extraction, the `grpId` to card-name lookup, and the field map for everything a finding needs.
- **`SKILL.md` Step 1 now names both sources and says which one findings come from.** Default is the log. The replay is for looking at a board, taking a screenshot, or checking one moment the log left ambiguous.
- **Scryfall is still the authority on cards.** Untapped's `cards.json` resolves names and nothing else. Costs, types and oracle text get verified, because that's what a finding turns on.

### Three traps, one of which already shipped a wrong finding

- **`isTapped` is omitted, not set to false.** Merging game objects across messages with `Object.assign` leaves a stale `isTapped: true` on every land that ever tapped, so every board reads as fully tapped and "he was tapped out" becomes a finding that never happened. That is exactly what happened in the 2026-09-02 UW mirror review: a turn-23 attack was graded a punt for stranding the player with no mana, when he had ended that turn with four lands untapped. Replace the object, don't merge it, and cross-check against `TappedUntappedPermanent` and `ManaPaid`.
- **The annotation stream is resolution order, not casting order.** A spell cast in response resolves before the ability already on the stack, so reading the stream top-down gets the causality backwards. When a finding turns on priority, walk the window message by message and print the annotations alongside the untapped list.
- **Object ids get reused.** A name resolved from a stale id map produces lines like "sacrificed Get Lost" for a Map token. Don't write a finding on a single strange event.

### A new rule

- **No mana claim without the tap trace.** "He was tapped out", "she had the counter up", "he could have paid the {3}" are the sentences reviews turn on, and each one is a specific set of lands in a specific message. Print them, count them, then write.

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
