---
name: vod-review
description: Review Magic gameplay and find the decisions that decided the game. Works from an untapped.gg match replay, a YouTube gameplay VOD, a pasted MTGA or MTGO game log, or screenshots. Use when the user wants their own play reviewed, wants to know why they lost a match, wants a line second-guessed, or wants a pro's VOD broken down for what they did differently. Trigger on phrasings like "review this match", "why did I lose that game", "was that the right line", "go through my untapped replay", "review my games from last night", "what should I have done on turn 4", "break down this VOD", "did I punt", "review my mulligan decisions", or any request pairing a game, a replay link, or a game log with a question about how it was played.
---

# vod-review

One job: find the decisions that actually decided the game, and say what the better
line was and why. Everything else in a game is noise.

## Related skills in this plugin

| Skill | What it's for | Hand off when |
|---|---|---|
| `rules-check` | What the Comprehensive Rules say. Priority, the stack, layers, state-based actions, timing | A line's legality or timing is the question. Never guess at whether a response was possible; go get the rule |
| `mtg-tournament-analysis` | Meta share, win rates, matchup matrices, card-level signal across the field | The review turns into "is this deck even good" or "what's the field like", or you need the matchup's real win rate to judge how a game *should* have gone |
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

Three sources. They give different things, so ask which one the user has rather than
assuming.

### Untapped.gg replay (best for your own Arena games)

Untapped records full turn-by-turn state: both players' plays, mana available, cards
drawn, and what was revealed. That's more information than a VOD gives you, because
you get the actual sequencing rather than a camera pointed at it.

The pages are JavaScript-rendered, so a plain fetch returns a shell. Use the browser
tools that render JavaScript.

1. Ask the user for the match or profile URL. Their match history lives under their
   untapped profile; individual matches have their own URL.
2. Navigate with the browser tools, then read the page as text rather than
   screenshotting it. The turn log is text, and text is what you need.
3. **The session has to be signed in.** If the page shows a login wall, say so and
   ask the user to sign in rather than trying to work around it. Some breakdowns are
   Premium-gated; if a panel is paywalled, note which one and work from what's
   visible.
4. Read the whole match, both games, before commenting on any of it. A turn-3
   decision often only looks wrong once you know what was in the deck.

**What untapped gives you that nothing else does:** the opponent's revealed cards
across all games of the match, and your own draws in order. That's enough to
reconstruct what you knew at each decision point, which is the whole basis of the
review.

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

1. Name the user's deck. If they haven't said, read it off the game.
2. Name the opponent's deck from what they revealed. If the cards don't resolve to a
   known archetype, hand it to `deck-check` rather than inventing a name.
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

---

## Step 3: Find the decision points

Most turns have no decision worth reviewing. Look for these.

| Decision point | The question to ask |
|---|---|
| **Mulligan** | What did the hand need to function, and how many of the deck's cards provided it? Count them. |
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

---

## Step 4: Grade honestly

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

---

## Step 5: Write it up

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

## Game 1

**Turn {N} — {Punt | Close | Correct}**

You knew: {what was visible and known}
You didn't know: {what was hidden}
You played: {the line}
The alternative: {the other line}
Why it matters: {the count, or the mechanical reason}

## Game 2
...

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

## When the review turns into something else

- **"Is this deck actually good?"** goes to `mtg-tournament-analysis`. A review can
  tell you the line was right; only the field data tells you the deck was.
- **"Could they have responded to that?"** goes to `rules-check`. Never answer a
  priority or timing question from memory in a review. The whole finding rests on it.
- **"What is my opponent even playing?"** goes to `deck-check` if the cards don't
  resolve to a known archetype.

---

## Rules

- **No outcome bias.** Judge on information available at the time. This is the rule
  the whole skill exists to enforce.
- **Don't manufacture mistakes.** Some games are unwinnable and some lines are just
  right. Say so.
- **Cite the turn.** Every finding names a turn number, and a timestamp too when the
  source is a VOD.
- **Verify cards on Scryfall.** A review that misstates a card's cost is wrong in the
  one way a review cannot afford.
- **Ask before inferring.** A screenshot with no context, an unreadable card, a
  paywalled panel: ask rather than filling the gap.
- **The user plays the game.** Present the count and the alternative. Where two lines
  are genuinely close, say which you'd take and let them disagree.
