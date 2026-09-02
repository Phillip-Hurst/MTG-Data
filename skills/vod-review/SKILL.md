---
name: vod-review
description: Review Magic gameplay and find the decisions that decided the game, interviewing the player about their reasoning rather than guessing at it, and building a play profile of their habits over time. Works from an untapped.gg match replay, a YouTube gameplay VOD, a pasted MTGA or MTGO game log, or screenshots. Use when the user wants their own play reviewed, wants to know why they lost a match, wants a line second-guessed, wants a pro's VOD broken down, or wants to know what their recurring habits and leaks are. Trigger on phrasings like "review this match", "why did I lose that game", "was that the right line", "go through my untapped replay", "review my games from last night", "what should I have done on turn 4", "break down this VOD", "did I punt", "review my mulligan decisions", "what are my bad habits", "what do I keep getting wrong", "am I playing too fast", "what should I work on", "show me my play profile", or any request pairing a game, a replay link, or a game log with a question about how it was played.
---

# vod-review

One job: find the decisions that actually decided the game, and say what the better
line was and why. Everything else in a game is noise.

Two things make this a review rather than a lecture. The player gets asked what they
were thinking before anything gets graded, and every finding gets logged so the
habits show up across sessions instead of dying in one note.

## Related skills in this plugin

| Skill | What it's for | Hand off when |
|---|---|---|
| `rules-check` | What the Comprehensive Rules say. Priority, the stack, layers, state-based actions, timing | A line's legality or timing is the question. Never guess at whether a response was possible; go get the rule |
| `mtg-tournament-analysis` | Meta share, win rates, matchup matrices, card-level signal across the field | The review turns into "is this deck even good" or "what's the field like", or you need the matchup's real win rate to judge how a game *should* have gone. Also where the archetype notes and `card_signal.py` live, which is where the "was this card in the picture?" question in Step 4 gets its card |
| `deck-check` | Assigns the right archetype name and pushes it into the win-rate data | The opponent's deck needs a name before you can look up the matchup |

`mtg-price-check` prices a Moxfield binder against Face to Face Games. It is a
separate skill and does not ship in this plugin, so point the user at it by name
rather than assuming it is installed.

---

## The rule that makes a review worth reading

**Judge the decision on the information available when it was made.** Not on what the
top of the library turned out to be.

A play that loses to the one card that beats it is often correct. A play that wins
because the opponent had nothing is often a punt. Reviewing on outcome teaches the
wrong lesson, and it's the default failure of every review that starts with "well,
you lost."

So every note follows the same shape:

> At this point you knew X. You didn't know Y. Given that, line A wins against
> N of the opponent's likely hands and line B wins against M. You took the smaller
> number.

If you can't fill in the count, you don't have a finding. Say the decision looked
close and move on.

**Say when a game was unwinnable.** Some are. A review that manufactures a mistake in
every game is worse than one that says "you got run over on the play by a hand you
beat 70% of the time, nothing here."

---

## Step 1: Get the game

Before touching a source, ask two questions: what deck are you on, and what are you
up against. Don't infer either from the game log by default; the user's answer is
faster and more reliable, and it's needed before Step 2 can pull the right archetype
notes. If the user genuinely doesn't know the opponent's deck yet (game still in
progress, or they forgot), fall back to reading it off the reveals in Step 2.

**Load the play profile now, and don't read the habit list yet.** `[C] Play Profile.md`
in the insights folder holds the running picture of how this player plays. It gets
checked in Step 5, after the findings are formed from the game, for the reason spelled
out in `reference/play-profile.md`. If there's no profile yet, this is the first
review and Step 7 creates one.

Three sources. They give different things, so ask which one the user has rather than
assuming.

### Untapped.gg (best for your own Arena games)

An untapped match URL is two sources, and they are not interchangeable. **Read
`reference/untapped-sources.md` before touching either one.** It carries the fetch
recipe, the field map, and the three traps, one of which has already put a wrong
finding into a shipped review.

| Source | What it is | Use it for |
|---|---|---|
| **The log** | `api.mtga.untapped.gg/api/v1/upload-log/<shortId>`. The raw MTGA client log. | Every finding in the review |
| **The replay** | `mtga.untapped.gg/replay/<shortId>`. The JavaScript board viewer. | Seeing a board, screenshots, checking one moment |

**Default to the log.** The replay steps one game state at a time and a three-game
match runs to hundreds of them. The log is one fetch and holds strictly more: mana
payments, priority order, counters added, mulligans, both decklists, and every
sideboard swap without asking the user to remember it.

1. Ask the user for the match or profile URL. Their match history lives under their
   untapped profile; individual matches have their own URL.
2. Open the replay page with the JavaScript-rendering browser tools, then fetch the
   log from the page context. The sandbox can't reach the endpoint; the page's origin
   can.
3. **The session has to be signed in.** If the page shows a login wall, say so and
   ask the user to sign in rather than trying to work around it. Some breakdowns are
   Premium-gated; if a panel is paywalled, note which one and work from what's
   visible.
4. Read the whole match, every game, before commenting on any of it. A turn-3
   decision often only looks wrong once you know what was in the deck.

**What the log gives you that nothing else does:** the opponent's revealed cards
across all games, your own draws in order, and the exact set of lands untapped at
every point of every turn. That's enough to reconstruct what you knew and what you
could afford at each decision, which is the whole basis of the review.

**Verify the mana before writing the finding.** "He was tapped out" and "she could
have paid the {3}" are the sentences reviews turn on, and each one is a specific set
of lands in a specific message. `isTapped` is omitted rather than set false, so a
merged object map reports every land as tapped forever. Print the lands, count them,
cross-check against the `TappedUntappedPermanent` and `ManaPaid` annotations, then
write.

### YouTube gameplay VOD

Same transcript path `mtg-tournament-analysis` uses for caster recaps, pointed at
gameplay instead. The difference is that timestamps matter here, because the user
wants to jump back to the turn.

```bash
pip install yt-dlp --break-system-packages -q
yt-dlp --write-auto-sub --sub-lang en --skip-download --sub-format vtt -o "%(id)s.%(ext)s" "<URL>"
yt-dlp --print "title,uploader,upload_date,duration_string" --skip-download "<URL>"
```

**Keep the timestamps.** The cleaning routine in `mtg-tournament-analysis` strips
them, which is right for a recap and wrong here. Keep the `-->` cue lines and map
each block of text to its start time, so every finding can cite `14:32` and the user
can go look.

Save the `.vtt` and the timestamped text to `transcripts/`, same as the analysis
skill does.

**A VOD transcript is a weak source for board state.** Auto-captions mangle card names
constantly, and a camera on a playmat is not a game log. Treat the transcript as the
commentary track and say plainly when a claim rests on it. If the player narrates
their reasoning out loud, that's the good part: you get to review the thinking, not
just the play.

### Pasted log or screenshots

MTGO writes a game log the user can copy out. Arena's log is harder to get at, so
screenshots are common. Both work.

- **A pasted log** is the cleanest input after untapped. Parse it turn by turn.
- **Screenshots** are a snapshot, not a game. Ask what happened before and after, and
  don't infer a sequence from one image. If the user drops several, ask for the order.

Do not guess at a card from a blurry image. Ask, or say which card you couldn't read.

---

## Step 2: Establish what each player was playing

Before any judgement, name both decks. A line that's wrong against Dimir Midrange is
often right against Mono-Green Landfall, and the review is worthless without knowing
which one you were facing.

1. Use the deck names the user gave you in Step 1. If they didn't say, read the
   user's deck off the game and ask them to confirm.
2. Name the opponent's deck from what they revealed, unless the user already told
   you. If the cards don't resolve to a known archetype, hand it to `deck-check`
   rather than inventing a name.
3. Pull the archetype note from
   `skills/mtg-tournament-analysis/reference/archetypes/` for both. That's where the
   game plan, the key cards, and the known matchup numbers live.
4. **Check the era.** Run `python mtg_era.py`. A review of a game from a dead format
   is a history lesson, which is fine, and it should say so. A matchup number quoted
   from before a ban is not fine.

**Verify every card on Scryfall before writing about it.** Same hard rule as the rest
of the plugin. This matters more in a review than anywhere else, because a review
turns on exact costs and exact text: whether the counterspell could have been held
up, whether the removal spell answered the threat, whether the trigger was optional.

### Build the card list before you grade anything

The archetype note's **Key cards** and **Key tricks and interactions** tables are the
review's working memory. Read them and hold them open: they say which of the
opponent's cards the line had to respect, and a grade written without them is a grade
written against a deck you didn't look up.

1. **List the cards that were actually in the picture.** Everything the opponent
   revealed across the match, plus anything the archetype note flags that they had
   mana for and hadn't shown yet. Verify each on Scryfall.
2. **Write down the interaction, not the name.** "Hydro-Man" is a name. "Becomes a
   land at his end step until his next turn, so it isn't a creature during your turn
   and sorcery-speed removal can never target it" is the thing that decided the game.
   The review's **Cards that mattered** section carries these, one line each.
3. **A card that decided a game and isn't in the archetype note goes into the note.**
   Append it to Key cards with its verified text and the date, and say in the review
   that you did. This is the whole reason the notes exist: the next review of that
   matchup starts knowing what this one had to learn the hard way.
   The same goes for an interaction the note doesn't spell out: it earns a line in
   **Key tricks and interactions**. Card text and interactions are general facts about
   the format, so they belong in the shipped note.
4. **If no archetype note exists for the opponent's deck**, say so plainly and build
   the card list from the reveals alone. Don't fabricate an archetype's contents from
   the name. **This is the normal state on a fresh install**: the notes are local
   working notes and the plugin ships none of them, only the canonical names in
   `archetype_names.json`. A review with no note behind it is still a review; it just
   says which cards it had to learn from the game itself, and writes the note
   afterwards so the next one starts ahead.

The card that decided the game is the same card the interview's third question is
about, so this step feeds Step 4 directly.

### Writing matchup experience back, without pretending it's data

A reviewed match is one data point about a matchup and a real observation about how it
plays. Both of those are worth keeping, and they go to different places.

**Card text, interactions, and play patterns go in the archetype note.** They're facts
about the format and they're true regardless of who was holding the cards.

**Your record in the matchup goes in the deck profile**, where `play_profile.py`
counts it and labels it. Under 20 games it prints as an anecdote, in that word.

**A short personal-experience section in the archetype note is fine, and it is never
data.** Append it under the existing matchup table, never inside it, in this shape:

```markdown
## Personal experience (small sample, not tournament data)

**Sample: 3 games, 1 match, 2026-09-01. On UW Control.** The matchup table above is
built on a much larger pool and overrides anything here.

- Hydro-Man went the distance in game 3. Sorcery-speed removal never had a legal
  window and Day of Judgment can't kill him at all.
- Disdainful Stroke was blank: their board comes down at two and three mana.
```

Three rules, all of them hard:

- **Never touch the `## Matchup data` table with personal results.** That table is the
  field's number. `mtg-tournament-analysis` owns it and rebuilds it from CSVs.
- **Never state a personal win rate.** "1-2 in one match" is a record. "33%" is a
  claim, and three games can't support one.
- **Where personal experience and the matchup table disagree, the table wins**, and
  the note says so in the section header. Large-sample tournament data beats how it
  felt every time.

Leave opponent handles out. The observation is about the deck, not the person.

---

## Step 3: Find the decision points

Most turns have no decision worth reviewing. Look for these.

| Decision point | The question to ask |
|---|---|
| **Mulligan** | What did the hand need to function, and how many of the deck's cards provided it? Count them. Write the hand down card for card first (see below). |
| **Play or draw** | Did the choice match the matchup, or the default? |
| **Sequencing lands** | Which land was held back, and did it cost a colour or a untapped mana later? |
| **Holding up mana vs deploying** | What were you representing, and could the opponent see through it? |
| **Trading vs going wide** | Did the trade progress your plan or just clear a board you were winning? |
| **Removal timing** | Was the spell spent on the first target or saved for the real one? Name the real one. |
| **Combat math** | The attack that was and wasn't made. Show the numbers. |
| **Sideboarding** | Which cards came out, and did the plan match what the opponent actually showed? |
| **The turn the game was lost** | Usually two or three turns before the game ended. Find it. |

**The turn the game was lost is rarely the last turn.** By the time the lethal attack
comes, the decision was made a while ago. Work backwards from the loss until you find
the turn where a different choice changes the outcome, then review that one.

### Write the kept hand down first

**Before anything else in the game, record the hand that was kept, card for card.**
Untapped shows it at the mulligan state and then it's gone; a pasted log has it at the
top; from screenshots, ask. Record the count kept (7, 6, 5), the lands in it, the
cards in Scryfall spelling, and whether the player was on the play.

Do this for every game, win or loss, not only the games with a mulligan finding. Two
reasons:

- **A mulligan grade needs the hand to be arguable.** "That was a keep" is an opinion.
  "You kept a 6 with two lands and four spells at three or more, on 27 lands" is a
  review, and it's a review the player can disagree with using the same numbers.
- **The hands accumulate into an index.** Across a dozen reviews the ledger answers
  "what am I actually keeping against this deck" with a count instead of an
  impression. `python play_profile.py --hands` prints it.

Classify the hand on what was knowable at the keep (`shape`), and record what the draw
did afterwards (`outcome`) as a separate field. Keeping those apart is what stops a
hand being graded by how it turned out: `lands-and-spells` that came out `screwed` is
variance, `land-light` that came out `neither` is still a bad keep that got bailed
out. Both vocabularies are fixed and live in `reference/play-profile.md`.

**Note the pace tells as you read, and measure pace if the source lets you.** A VOD
gives real seconds per turn from the timestamps. Untapped gives game duration over
turn count. A pasted log gives nothing, and that's a fine answer. The tells worth
recording (tapped the wrong mana, cast a spell before the land drop that would have
enabled a better one, missed a trigger, attacked before the pump was available) are
listed in `reference/play-profile.md`. One tell is noise.

---

## Step 4: Ask what he was thinking

A review that skips this is guessing at the reasoning and grading the guess. The
player knows something the log doesn't: what they saw, what they feared, and what they
had already decided two turns earlier.

**Interview before grading.** The answers move grades, and a grade published before
the question was asked is one you'll have to walk back.

### The three questions

Ask about the decisions Step 3 flagged. Nothing else.

**1. What was the read?**

> Turn 4 you had Torch and Opt up, and you cast Opt. What were you seeing there?

Open question, no leading. If the reasoning was sound and the line still lost, that's
a `correct` grade and the interview is what proved it.

**2. What were you playing around?**

> You held two mana through their whole turn. What was that for?

Then check the answer against the line. If they name a card and the mana they held
doesn't actually beat that card, the finding isn't the read, it's the execution. Those
are different problems and they need different practice, so say which one it was.

**3. Was this card in the picture?**

Pick one card from the opponent's archetype and ask whether it factored in. This is
the question that teaches, because it surfaces cards the deck plays that the player
didn't know to fear.

Where the card comes from:

- The **Notable cards** and **Key tricks and interactions** tables in the archetype
  note at `skills/mtg-tournament-analysis/reference/archetypes/`.
- The rogue and deviation lenses of `card_signal.py`, for cards showing up in that
  archetype's current lists without being in the note yet. That's the good version of
  this question: a card the field has started playing and the note hasn't caught up
  to.

Three conditions before asking, all of them:

- **The archetype actually plays it.** From the note or from current data, verified on
  Scryfall. Never a card invented to make an interesting question.
- **It was live at that moment.** Right mana available, not already seen, not already
  answered. A card that couldn't have been there is trivia.
- **It changes the line.** If knowing about the card doesn't change what the right play
  was, there's no question to ask.

If no card clears all three, skip the question. A manufactured trap teaches the player
to distrust the review.

### How to run it

- **Batch the questions into one round.** Ask all of them at once, then grade. A
  turn-by-turn interrogation across ten messages gets abandoned halfway.
- **Cap it at three questions per match.** More than that and the review stops being
  worth the time it costs.
- **Use the multiple-choice tool where the options are enumerable** (which card were
  you playing around, was this in the picture yes or no) and plain text where the
  answer is a read.
- **"I don't remember" is an answer, and an informative one.** Record it. A decision
  that left no memory of the reasoning behind it is usually a fast one, and that's a
  pace signal, not a character flaw.
- **Testimony is not evidence.** What the player says they were thinking goes in the
  note as their account. Where the account and the line disagree, say so plainly.
  Softening that is the one thing that makes the whole exercise pointless.

---

## Step 5: Grade honestly

Three buckets. Use them sparingly; most plays are fine.

- **Punt.** A clearly better line existed with the information available at the time.
  Say what it was and why, in that order.
- **Close.** Two lines were defensible. Say which you'd take and what would tip it.
  Most "mistakes" live here, and calling them punts is how a review loses credibility.
- **Correct, lost anyway.** The line was right and the deck or the draw let it down.
  Say it plainly. This is the most useful category and the most under-used one.

Never bucket a play by whether it worked.

**On mulligans specifically:** count. "That was a keep" is an opinion. "That hand had
two lands and four four-drops, and you're on 24 lands, so you're keeping a hand that
needs to hit two of the next three draws" is a review. Do the counting.

### What the interview does to a grade

| The answer | Effect |
|---|---|
| Sound read, line matched it, lost anyway | `correct`. The interview is the proof |
| Sound read, line didn't account for the card they named | Stays a punt, and the finding is execution rather than judgement. Say which |
| Hadn't considered a card that was live and changes the line | A real punt, and the most teachable one. Name the card |
| "I don't remember" | Grade the line on its merits. Log the non-answer as a pace signal, not as a mistake |

### Now check the profile

Findings are formed. Open `[C] Play Profile.md` and check its habit list against this
match. Anything the profile predicted and this game supports gets flagged as such in
the ledger, so the count can be discounted later for confirmation bias.

**Say it when the profile is wrong about this game.** "Your profile says removal
timing, and this game doesn't show it" is a useful sentence, and a profile nothing can
contradict has stopped being a measurement.

---

## Step 6: Write it up

Save to the insights folder as `[C] VOD Review — {opponent deck or event} {YYYY-MM-DD}.md`.

```markdown
---
author: claude
type: solution
project: MTG Tournament Analysis Skill
date: YYYY-MM-DD
tags: [mtg, vod-review, {your-deck-slug}]
source: {untapped match URL | YouTube video ID | pasted log}
era: {output of mtg_era.py}
---

# {Your deck} vs {Their deck} — {date}

**Result:** {2-1, 0-2, etc.} · **Source:** {where this came from}

## The short version

{Two or three sentences. The one decision that mattered most, and the pattern if
there is one across games. If the games were fine, say that.}

## Cards that mattered

{One line per card, from the archetype notes plus what the match revealed, verified
on Scryfall. The interaction, not the name: what it does that the line had to
respect. Mark any card that wasn't in the archetype note and has now been added to
it.}

## Opening hands

| Game | Kept at | Lands | On the | Hand | Outcome |
|---|---|---|---|---|---|
| 1 | 6 | 2 | play | {card, card, card, ...} | screwed |

{One line under the table per hand worth arguing about: what it needed, how many
cards in the deck provided it, and whether the keep was right on what was knowable.}

## Game 1

**Turn {N} — {Punt | Close | Correct}**

You knew: {what was visible and known}
You didn't know: {what was hidden}
You played: {the line}
You said: {their stated reasoning, or "not asked" / "didn't remember"}
Playing around: {the card they named, and whether the line actually beat it}
The alternative: {the other line}
Why it matters: {the count, or the mechanical reason}

## Game 2
...

## Pace

{The measurement and its source, or "not measurable from a pasted log". Any tells,
with the turn they happened on. Nothing here if there's nothing to say.}

## Sideboarding

{What came in and out, against what the opponent actually showed. Reference the
archetype note's sideboard section if there is one.}

## The pattern

{Optional. Only if the same mistake shows up more than once. One repeated habit is
worth more than six one-off notes.}

## What to practise

{One thing. Not a list.}
```

**One thing to practise, not a list.** A review that ends in nine action items gets
read once and changes nothing.

---

## Step 7: Update the play profile

The review is written. Now make it count toward the next one.

**Append to the ledger, then run the script. Don't count by hand.** `play_profile.py`
does the arithmetic, applies the trend bar, and rewrites the profile note. Counting
from memory across a dozen review notes is how a habit list turns into a vibe.

1. **Append one line per game to `play_log.jsonl`** in the insights folder. One object
   per game, not per match. The schema and the fixed `kind` vocabulary are in
   `reference/play-profile.md`. Never invent a `kind` inline; a habit spelled three
   ways splits into three habits, and the script rejects the line rather than counting
   it under a name nothing else uses.
   **Every line carries its `hand`** — the cards kept, the land count, the shape, and
   the outcome. The script rejects a hand whose card list disagrees with `kept_at`,
   because a hand transcribed wrong still gets counted, and the count is the point. A
   game whose source genuinely never showed the opening hand is the only line that
   ships without one, and the review says which game that was.
   **Games two and three carry `sideboard`** — what came in, what went out. That's how
   "this card comes in every time and has never mattered" becomes a countable claim
   instead of a feeling.
2. **Run the rollup.** It reads the ledger and rewrites `[C] Play Profile.md` plus one
   `[C] Play Profile - {deck}.md` per deck in the ledger.

   **Two layers, on purpose.** The deck note holds that deck's habits, its matchup
   record, its boarding, and its kept hands. The cross-deck note holds only what has
   shown up with two or more decks, because a habit seen on one deck might be the
   archetype rather than the player. When the cross-deck note is thin and the deck
   notes aren't, that's the system working, not a bug. Say which layer a finding came
   from when you report it.

   ```bash
   python play_profile.py                 # roll up, write the profile
   python play_profile.py --validate      # check the ledger, write nothing
   python play_profile.py --dry-run       # print the profile, write nothing
   python play_profile.py --json          # the counts, for answering a question
   python play_profile.py --hands         # the kept-hand index, card by card
   ```

3. **Read the exit code and repeat what it said.** `0` clean, `1` couldn't run,
   `2` ran and found ledger lines it couldn't use. On `2`, fix the lines it named and
   run it again, and say in the review that the counts understate until then.
4. **Report what moved.** How many games the ledger holds now, and which habits changed
   bucket. A silent update looks exactly like one that didn't happen.

**Never hand-edit the profile note.** It's a view of the ledger, regenerated on every
run, and an edit to it is gone the next time the script runs. Corrections go into the
ledger line.

### What the script decides, so the review doesn't have to

| Rule | Value |
|---|---|
| Deck habit | Clears the trend bar with one deck. Lives in that deck's note only |
| Player habit | Clears the trend bar **and** appears with 2 or more decks |
| Personal matchup record | An anecdote under 20 games. Never a win rate, never beats the archetype note's table |
| Trend | 3 or more occurrences across 2 or more sessions |
| Watching | Exactly 2 occurrences, counted with no conclusion drawn |
| Below the bar | 1 occurrence. Stays in the review note, never reaches the profile |
| Faded | Cleared the bar once, absent from the last 2 sessions. Kept, with the date |
| Strength | 3 or more `correct` grades across 2 or more sessions, outnumbering the rest |
| Discount flag | More than half a habit's findings were `prompted_by_profile` |

Two occurrences on one night is one bad night, which is why sessions are counted
separately from games. A flagged habit is never offered as the thing to work on.

**Neither the ledger nor the profile ships, and neither goes in the repo.** They're the
user's play history, and the repo is public. `package.py` and `.gitignore` both exclude
them, with a test pinning it.

---

## When the review turns into something else

- **"Is this deck actually good?"** goes to `mtg-tournament-analysis`. A review can
  tell you the line was right; only the field data tells you the deck was.
- **"Could they have responded to that?"** goes to `rules-check`. Never answer a
  priority or timing question from memory in a review. The whole finding rests on it.
- **"What is my opponent even playing?"** goes to `deck-check` if the cards don't
  resolve to a known archetype.

---

## Asked for the profile with no game attached

"What are my bad habits", "what should I work on", "am I playing too fast" are all
answerable straight from the ledger. Skip Steps 1 through 6 and run the rollup:

```bash
python play_profile.py --json
```

"What do I keep", "am I keeping too many two-landers", "what did I keep against that
deck" are the same move against the hand index:

```bash
python play_profile.py --hands
```

Answer from those counts rather than from the profile note's prose, and rather than
from memory of previous sessions.

Two things to hold to. Report the sample size in the first sentence, because a habit
list off 4 games and one off 40 are different objects. And if the ledger is empty or
thin, say that instead of producing a profile from nothing: the honest answer to "what
are my leaks" after two reviewed games is that there isn't enough here yet, and here's
what's being watched. The script says `Sample is thin` under 5 games, and that line is
meant to be passed on rather than smoothed over.

---

## Rules

- **No outcome bias.** Judge on information available at the time. This is the rule
  the whole skill exists to enforce.
- **Interview before grading.** Ask what the player was thinking, then grade. A grade
  published before the question was asked is one you'll walk back.
- **Testimony is not evidence.** Record what they said as their account. Where the
  account and the line disagree, say so.
- **No pace claim without a measurement.** A timestamp, a duration, something they
  said, or two tells in one game. Losing is not evidence about speed.
- **No trend without a count.** Three occurrences across two sessions, or it isn't a
  trend yet.
- **Don't manufacture mistakes.** Some games are unwinnable and some lines are just
  right. Say so. The same goes for habits: a clean profile is a legitimate result.
- **Cite the turn.** Every finding names a turn number, and a timestamp too when the
  source is a VOD.
- **Record the hand.** Every game, card for card, before grading the mulligan. A
  mulligan finding without the hand behind it is unarguable, and the hand is the one
  part of a game that can't be recovered later.
- **Name the interaction, not the card.** A card that decided a game gets its actual
  text in the review, and gets added to the archetype note if it wasn't there.
- **Verify cards on Scryfall.** A review that misstates a card's cost is wrong in the
  one way a review cannot afford.
- **No mana claim without the tap trace.** Whether someone was tapped out, held a
  counter up, or could have paid a tax is a specific set of lands in a specific
  message. Print them and count them. `reference/untapped-sources.md` has the trap
  that makes every land look tapped, and the annotations that overrule it.
- **Ask before inferring.** A screenshot with no context, an unreadable card, a
  paywalled panel: ask rather than filling the gap.
- **The user plays the game.** Present the count and the alternative. Where two lines
  are genuinely close, say which you'd take and let them disagree.
