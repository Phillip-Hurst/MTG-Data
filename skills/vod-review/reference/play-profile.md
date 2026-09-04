# The play profile

How a single review turns into a picture of how someone plays. Three layers,
and one rule about where prose is allowed to live.

| Layer | Holds | Read back by the tool |
|---|---|---|
| `[C] VOD Review - ...md` | All the prose. Play-by-play, the interview, cards that mattered, the hands card for card | Never. It is the archive, and the thing every profile line cites |
| `play_log.jsonl` | Facts only. Ids, enums, counts, and a pointer at the review note | Every run |
| `[C] Play Profile.md` + `[C] Play Profile - {deck}.md` | Aggregates. One line per pattern, with its count and its citation | On demand. Generated, never hand-edited |

**Prose stops at layer 1.** A ledger finding carries a `pattern_id`, a grade and
a pointer, and the profile cites the note rather than quoting it. Copying the
account of a decision into the ledger and then into two profile notes on top of
that is what turned an 11 KB profile into 59% quoted play-by-play, and made
`--json` bigger than the ledger it summarised.

**Two profile layers, and the split is the point.** A pattern that only ever
shows up with one deck is the deck's, not the player's: it could be the
archetype, the matchup, or one week of practice. It stays in that deck's note,
named and counted, and the cross-deck note says where it lives rather than
claiming it. The moment a second deck shows the same pattern it gets promoted.
The bar is `MIN_DECKS_FOR_PLAYER_HABIT`, currently 2, on top of the trend bar.

**`play_profile.py` at the repo root does the counting.** Exit codes: `0` clean,
`1` couldn't run, `2` ran and found lines it couldn't use. A hand edit to a
profile note is gone on the next run, so corrections belong in the ledger line.

```bash
python play_profile.py                 # roll up, write the profiles
python play_profile.py --validate      # check the ledger, write nothing
python play_profile.py --dry-run       # print the profile, write nothing
python play_profile.py --json          # the counts, for answering a question
python play_profile.py --json --full   # the counts plus the card-for-card hands
python play_profile.py --hands         # the index of kept hands, card by card
python play_profile.py --min-occurrences 4 --min-sessions 3   # a stricter bar
```

**Neither the ledger nor the profile notes ship, and neither belongs in the
repo.** They are the user's own play data. `package.py` drops them from a bundle
and `.gitignore` covers both, with a test pinning it. `play_patterns.json` is
different: it is a vocabulary of how Magic decisions go wrong, true regardless of
who was holding the cards, and it ships.

---

## The pattern registry is the thing that makes a habit countable

`play_patterns.json` at the repo root. Every finding names one `pattern_id` from
it, and that is what the profile counts.

**`kind` cannot do this job, and trying was the original defect.** Kind is a
decision category and there are ten of them. Every game contains removal-timing
decisions, so kind occurrences accumulate with games played rather than with
mistakes made: any kind clears a three-occurrence bar within a few sessions no
matter how well someone played. Counting kinds measures how much Magic you have
been playing.

It failed visibly. On 2026-09-04 the profile carried four "trends", every one of
them labelled `removal-timing decisions (16 wordings)` or its equivalent, and
listed `removal-timing` as a trend and a strength in the same note off 14 correct
grades out of 16.

A pattern names the behaviour instead:

```json
"removal-spent-on-present-target": {
  "kind": "removal-timing",
  "label": "Spends removal on the target in front of him",
  "description": "Uses the answer on the only legal target available rather than holding it for the threat he already knows is coming.",
  "polarity": "leak"
}
```

Three rules, all hard:

- **An unknown `pattern_id` is rejected, not counted.** Same discipline as
  `mtg_stats.ARCHETYPE_ALIASES`. A habit spelled two ways counts as two habits
  and the number stops meaning anything.
- **Adding a pattern means editing the registry, and nowhere else.** Never
  inline. `test_play_profile.py` fails if the registry and this note drift.
- **A finding's `kind` has to match its pattern's `kind`.** The script checks.
- **Every kind carries at least one pattern.** A kind with none is a category a
  reviewer can name and cannot file anything under, because the pattern_id it
  would need does not exist and an invented one is rejected. `play-draw`,
  `combat-math` and `rules-error` sat empty from 1.14.0 until 2026-09-04, so a
  combat-math error had nowhere to go and either got dropped or landed under a
  pattern that did not describe it. A test now fails on an empty kind.

`kind` is the coarse category every pattern belongs to, and it is a fixed list:

```
mulligan · play-draw · land-sequencing · mana-holding · trading ·
removal-timing · combat-math · sideboarding · lost-turn · rules-error
```

`polarity` is one of:

```
leak · strength · neutral
```

`phase` says where in the game the decision happened:

```
mulligan-blind · mulligan-post-board · sideboard · in-game
```

**`polarity` is documentation, not a verdict.** The registry declares what shape
a pattern is; the ledger measures what it actually graded. Where the two
disagree, the profile prints a **Registry disagrees with the grades** section and
names the pattern, because either the label is wrong or the grades are and
somebody should look.

---

## Why a ledger and not just notes

A habit claim needs a count behind it. "You're impatient with removal" is a vibe.
"You spent removal on the first legal target in 5 of the last 7 games, and in 3
of them the real threat landed two turns later" is a finding someone can act on,
and can argue with.

Reading six review notes and remembering what they said produces the first
sentence. Counting a ledger produces the second.

---

## The ledger row

One object per game, not per match. A three-game match appends three lines.

```json
{
  "date": "2026-08-31",
  "session_id": "2026-08-31.1",
  "match_id": "2f9c81a4",
  "source": "untapped:2f9c81a4",
  "era": "secrets-of-strixhaven",
  "your_deck": "Izzet Prowess",
  "their_deck": "Dimir Midrange",
  "game": 2,
  "result": "L",
  "on_the_play": false,
  "review_note": "[C] VOD Review - Dimir Midrange 2026-08-31.md",
  "findings": [
    {
      "phase": "in-game",
      "turn": 4,
      "kind": "removal-timing",
      "pattern_id": "removal-spent-on-present-target",
      "grade": "punt",
      "note": "Torch on the two-drop with Sheoldred known in hand",
      "stated_reason": "wanted to stop the clock before it grew",
      "intent_matched_line": true,
      "prompted_by_profile": false
    },
    {
      "phase": "sideboard",
      "kind": "sideboarding",
      "pattern_id": "boards-without-an-answer",
      "grade": "close"
    }
  ],
  "hand": {
    "kept_at": 6,
    "lands": 2,
    "cards": ["Island", "Hallowed Fountain", "Three Steps Ahead",
              "No More Lies", "Stock Up", "Day of Judgment"],
    "shape": "interaction-heavy",
    "outcome": "screwed",
    "note": "never found a fifth land"
  },
  "sideboard": {
    "in": ["Rest in Peace", "Flashfreeze"],
    "out": ["Seam Rip", "Wan Shi Tong, Librarian"]
  },
  "pace": {
    "measure": "untapped-duration",
    "seconds_per_turn": 34,
    "tells": []
  },
  "interview": { "asked": 3, "answered": 2, "dont_remember": 1 }
}
```

### The schema is closed

**An unrecognised key is a problem, not a passing value.** The 2026-09-04 review
wrote `opening_hand` where the schema says `hand`, for all three games. Those
rows validated clean, the run exited 0, and the hand count reported "35 of 41",
which reads as six games whose source never showed a hand. Half of it was
transcription loss and nothing said so.

The row's keys are exactly: `date`, `session_id`, `match_id`, `source`, `era`,
`your_deck`, `their_deck`, `game`, `result`, `on_the_play`, `review_note`,
`findings`, `hand`, `sideboard`, `pace`, `interview`. Anything else is reported.

### Identity, and the two dimensions that used to be guesses

**`session_id`** is recorded, not derived. It used to be `distinct date`, which
means two Arena sessions in one day collapsed into one and suppressed a trend,
while a session running past midnight split into two and promoted one. The trend
bar rests on this, so it gets written down. Format is the date plus an ordinal:
`2026-08-31.1`, then `.2` for a second sitting the same day.

**`match_id`** is the match's identity, and `(match_id, game)` has to be unique
across the ledger. Appending the same game twice doubles every count it touches,
and nothing in the old schema could see it happen. For untapped it is the
shortId. For a VOD, `yt:<videoId>`. For a pasted log, anything stable.

**`review_note`** is the filename of the note holding the prose. It is what every
profile line cites, and it is how a count stays checkable without the prose
being copied.

**The pointer has to resolve, and every run checks it.** Write the filename with
a plain hyphen, never an em dash: `[C] VOD Review - Boros Dragons 2026-09-04.md`.
It used to be checked for being a non-empty string and nothing else, and on
2026-09-04 all 41 rows cited a hyphenated name while the notes on disk carried an
em dash. 46 findings, 7 citation strings, none of them resolving, and a run that
reported no problems at all. A citation that lands on nothing is decoration, so
an unresolvable `review_note` is now a reported problem and the run exits 2. The
row still counts; it is the pointer that is broken.

### The fields that carry weight

**`phase`** is `mulligan-blind`, `mulligan-post-board`, `sideboard` or
`in-game`. `turn` is a positive integer when the phase is `in-game`, and must be
absent otherwise. It used to be a required integer with 0 standing in for
"before the game started", and the profile printed `Turns: 0, 0, 0, 0, 0, 0, 0, 0`.

**A phase has to agree with the game number**, and the script checks:
`mulligan-blind` is game 1, `mulligan-post-board` and `sideboard` are games 2 and
up. A phase that disagrees with its game number means one of the two is wrong,
and the finding would land in the other kind's counts.

### The two mulligans are two different decisions

**A game 1 keep is made in the dark.** No idea what deck is across the table, so
the hand can only be judged against the format: does it cast its spells, does it
have lands, is there an early play. **A game 2 or 3 keep is made knowing the
matchup**, and the same six cards can be a keep in one and a ship in the other.

The 2026-09-01 Izzet Spellementals mulligan is the case that proves it. Bottoming
Erode off a two-land six was graded a punt, and the whole argument rests on
information: two games had already shown that their entire battlefield presence
costs two and three, so Erode was one of two live cards in the hand and
Disdainful Stroke was blank. Blind, that is a close call about a one-mana instant
against an unknown deck. Informed, it is the wrong card going under.

Grading them together averages a blind decision with an informed one and reports
the mean as a habit.

So the profile counts them apart:

- **`rollup["mulligans"]`** carries the graded findings per phase, with the grade
  split and the patterns behind each.
- **`rollup["hands"]["by_knowledge"]`** splits the kept hands into `blind` and
  `post-board`: how many, the record, mean lands, sizes kept and outcomes. This
  is derived from the game number rather than stored, because a stored copy could
  disagree with `game` and there is only one right answer.
- **A pattern's own count stays whole.** A mulligan pattern's line reports its
  phase mix ("Split 1 blind, game 1, 1 post-board, knowing the matchup") rather
  than being split into two patterns. Splitting the counts as well would put a
  two-occurrence habit below the bar twice and report neither.
- **`--hands` labels every row** `blind` or `post-board`.

**`grade`** is `punt`, `close`, or `correct` (the third meaning correct and lost
anyway). Same three buckets the review uses.

**`note`** is optional, capped at 300 characters, and never rolled up. It is a
label for scanning the ledger. The account of the decision is in the review note.

**`stated_reason`** is what the player said in the interview, quoted or close to
it. Null when they weren't asked or didn't remember.

**`intent_matched_line`** is the interesting one. True when the stated plan and
the actual play agree. False when they don't, which is its own problem: a player
who knows the right card to play around and then makes a play that doesn't
account for it needs different practice from one who never considered the card.

**`prompted_by_profile`** is true when the finding was checked because the
profile predicted it. That flag is the confirmation-bias audit. If most findings
for a pattern carry it, the pattern is being found because it's expected, and
the count is worth less than it looks.

---

## The kept hand

**Every reviewed game logs the hand that was kept, card for card.** A mulligan
finding without the hand behind it can't be argued with, and the hand is the one
piece of a game that is never recoverable later: the replay shows it for about
four seconds and then it's gone into the rest of the game.

| Field | What it is |
|---|---|
| `kept_at` | Cards kept: 7 for a no-mulligan keep, 6 after one, and so on. `cards` has to be this long |
| `lands` | Lands in the kept hand. Required. Count MDFC land backs and say so in `note` |
| `cards` | The hand, card for card, in Scryfall spelling |
| `shape` | What kind of hand it was, from the fixed list below |
| `outcome` | What the draw did afterwards, from the fixed list below |
| `note` | Optional. One line: what the hand needed, and whether it got it |

**`shape` is judged on what was knowable at the keep.** From this list:

```
lands-and-spells · interaction-heavy · threat-heavy · land-light ·
land-heavy · no-early-play · unknown
```

**`outcome` is what happened afterwards**, kept separate on purpose:

```
screwed · flooded · neither · unknown
```

Splitting the two is what stops outcome bias getting into the mulligan grade. A
hand can be `lands-and-spells` and still come out `screwed`, and that combination
is a variance note, not a punt. `land-light` that came out `neither` is a keep
that got bailed out, and it stays a bad keep.

**On the play or on the draw already lives on the row**, so it isn't repeated
here. The rollup pairs them.

`hand` is optional in the schema so that ledger lines written before it existed
stay usable. It is not optional in a review: a game reviewed from a source that
showed the opening hand and logged without one has thrown the evidence away.
Count the lands off the card list and verify every card's type, because a hand
whose card count or land count is wrong still gets counted.

---

## Sideboarding and matchup experience

**`sideboard` records what came in and what went out**, per game, for games two
and three. It rolls up per opponent archetype in the deck note: which cards you
bring in against what, how often, and with what record behind it. That's the raw
material for noticing a card that comes in every time and never does anything.

**Build the lists by diffing the decklists in the log, not from memory.** The two
lists are the same length by arithmetic: a deck keeps its size. **Every run
checks it now**, in both directions, because this rule sat here from 1.12.0
enforced by nothing and a test actually pinned the opposite, asserting that 2 in
against 1 out validated clean. A live ledger row then carried 9 in against 7 out
on both post-board games of one match, which no 60-card deck can do.

**An unbalanced list costs the boarding data for that game and nothing else.**
The row stays, its findings still count, and only the in/out lists are set aside
so the matchup rollup never carries a list already known to be wrong. Rejecting
the whole row was the first attempt at this and it was worse than the defect: on
the row that found it, the findings were a post-board mulligan punt and a
boarding call, and that mulligan punt is the case the blind/post-board split was
written for.

A list that comes up short is how "he cut that and never brought it back" gets
written about a player who brought it back the very next game.

**A `sideboarding` finding belongs to one post-board game, and both post-board
games get looked at.** Game 2 and game 3 are boarded off different information,
so they are two decisions and they take two rows. Collapsing them loses the
second decision, and it loses the more interesting case: a player who cut a card
for game 2 and put it back for game 3 has already found the mistake.

Where that happens, put the finding on the game 2 row and say in the `note` that
the correction landed in game 3. One decision stays one occurrence that way.

**The matchup record in a deck note is personal experience and is labelled as
such.** Under `MEANINGFUL_MATCHUP_GAMES` (currently 20) games it is called an
anecdote, in that word, and above it the phrasing softens to "worth reading". It
never becomes data.

**Tournament data outranks it at every sample size.** The matchup tables in
`skills/mtg-tournament-analysis/reference/archetypes/` are built on hundreds of
matches from melee and MTGO. A 1-2 in one match is not evidence that a matchup is
bad; it is evidence about one match. Where the two disagree, the archetype note
wins, the deck note says so, and neither the review nor the profile ever quotes a
personal win rate as though it were a field number.

What personal experience is genuinely good for, and what the field numbers can't
give you: which card of theirs actually beat you, which of your sideboard cards
was blank in practice, and which of their draws you had no answer to.

---

## Pace, and what can actually be measured

Think time is mostly invisible, so this section says what each source supports
and stops there. A rushing claim with no measurement behind it is a guess dressed
as an observation.

| `measure` | Source | What it gives |
|---|---|---|
| `vod-timestamps` | YouTube VOD | Real seconds per turn, per turn. The only direct measurement available |
| `untapped-duration` | untapped.gg | `game_duration_seconds` from the index, over the log's turn count. Both clocks combined, one coarse average per game |
| `self-report` | The interview | "I snap-kept", "I don't remember", "I was on a timer" |
| `none` | Pasted log, screenshots | Nothing. Say so and leave `seconds_per_turn` null |

**MTGO and Arena logs carry no usable timing.** Don't derive one.

### The proxy tells

Some mistakes are the fingerprint of a fast click rather than a wrong read. They
go in `pace.tells`, from this list:

```
tapped-wrong-mana · cast-before-land-drop · missed-trigger ·
attacked-before-pump · same-15-every-matchup · sequenced-into-own-counterspell
```

**One tell is noise.** Two or more in the same game, or the same tell across
games, is a pace signal worth writing down.

**Never infer rushing from losing.** A loss is not evidence about speed. The
evidence is a timestamp, a duration, something the player said, or two tells in
one game. The review names which of those it used.

---

## Rolling the ledger into the profile

`play_profile.py` applies everything in this section. The rules are written out
here because they're the ones a reader needs in order to argue with a number, and
a test fails if the two drift apart.

### One pattern, one bucket

A pattern lands in exactly one of these. The old code computed "trend" and
"strength" independently and could put the same row in both, which it did on
2026-09-04.

| Bucket | Condition |
|---|---|
| **Leak** | Cleared the bar, and punt-and-close outnumber correct |
| **Strength** | Cleared the bar, and correct outnumbers punt-and-close |
| **Mixed** | Cleared the bar, and the two tie. Right about as often as not |
| **Watching** | Two or more occurrences that did not clear the bar. Named, counted, not concluded |
| **Below the bar** | One occurrence. Stays in the review note, never reaches the profile |
| **Faded** | Cleared the bar once and has since gone quiet. Kept, with the date |

The bar is 3 or more occurrences across 2 or more sessions. Two occurrences on
one night is one bad night, which is why sessions are counted separately from
games.

**Strengths count, and they clear the same bar.** A profile that lists only leaks
is a worse tool than one that also says what someone does well, and it's the
default failure mode of every automated review. A `correct` grade on a game that
was lost is the raw material.

### Fading is measured against sessions where that deck was played

**A deck sitting in its box does not fade its habits.** Fade looks at the last
`FADE_AFTER_SESSIONS` (currently 2) sessions in which one of the pattern's own
decks was on the table. Measuring against all recent sessions faded every
Yawgmoth pattern the moment three UW sessions went by, which reports a habit as
cured on no evidence at all.

Don't delete a pattern that stops showing up. Someone who fixed a leak should get
to see that they fixed it, and if it comes back the history is right there.

### What to work on is ranked on weighted problem grades

**The heading names the leak with the highest problem score, where a punt counts
double a close and a correct counts nothing.** Ties break on total occurrences,
then on `pattern_id` so the output is stable. A strength is never eligible, and
neither is a pattern flagged for confirmation bias. Mixed patterns are the
fallback when no leak has cleared the bar.

Two rankings failed here before this one. Raw occurrences promoted the best habit
to the top of the list of things to fix, because a decision type someone keeps
getting right accumulates occurrences fastest. Unweighted punt-and-close then
named a pattern with six closes and zero punts, because a close counted the same
as a punt.

**When no leak has cleared the bar, the line says so** and names nothing. A clean
profile is a legitimate result, and filling the heading with the least-good
strength would make it unreadable as a measurement.

**Every line in the profile carries its count, its date range, and a citation.**
A line without one is an opinion that snuck in, and it gets deleted rather than
softened.

---

## Reading the profile without letting it write the review

The profile is read at the start of a review and written at the end, which
creates an obvious trap: read "spends removal on the first target" first and
every removal spell starts looking early.

The order that avoids it:

1. Work the game and write the findings from what the game shows.
2. Then open the profile and check its pattern list against the game.
3. Anything found only at step 2 gets `prompted_by_profile: true`.
4. A pattern the profile predicted and the game doesn't support gets said out
   loud: *"Your profile says you tap out into open mana, and this game doesn't
   show it."*

That last one matters more than it sounds. A profile nothing can contradict has
stopped being a measurement.
