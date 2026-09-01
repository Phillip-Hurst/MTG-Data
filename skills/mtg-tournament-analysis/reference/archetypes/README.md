# Archetype reference notes

**This folder ships empty.** One note per Standard archetype lands here as you build
them: game plan, key cards with verified text, play patterns, and matchup data from
your own scrapes.

## Why it's empty

The notes are a reading of a metagame at a moment, written from one person's scrape of
melee and MTGO. Shipping someone else's are worse than useless once the format moves,
and an end user needs none of them to run the plugin. So the plugin carries the
vocabulary and none of the content.

**`archetype_names.json` at the repo root is the canonical vocabulary.** Every source
names decks differently: melee lets players type whatever they want, mtgtop8 has its
own house style, MTGO publishes nothing at all. Pick any one of them and the same deck
lands under three labels, which splits its win rate three ways and makes the matchup
matrix meaningless. So one name wins, and it's the one in that file.

`mtg_stats.ARCHETYPE_ALIASES` maps every other spelling onto those names. A test fails
if an alias ever points at a name the manifest doesn't carry — that's how "Izzet"
briefly got mapped to "Izzet Elementals", which nothing recognised, while "Izzet
Spellementals" was the real name.

## Filling it

`mtg-tournament-analysis` Step 5 writes a note here after any session that produces
matchup data. `deck-check` writes one when it names a new archetype, and adds the name
to `archetype_names.json` in the same move. `vod-review` adds cards and interactions it
verified while reviewing a game, and may add a clearly-labelled personal-experience
section that never counts as data.

```markdown
---
author: claude
type: note
project: MTG Tournament Analysis Skill
date: YYYY-MM-DD
archetype: Name (any aliases worth recording)
colors: WUBRG subset
sources: where the data came from, and when card text was verified
tags: [mtg, standard, archetype, ...]
---
```

Then the game plan, a key-cards table, and the record.

**Card text comes from Scryfall, always.** A note full of cards described from memory
is worse than a short one: it reads as authoritative and isn't. Where a card hasn't
been verified, say so in the note rather than guessing.

A new archetype earns a note when it's a real deck rather than a spread of brews.
`card_signal.py --lens unnamed` finds the candidates: a group sharing a core, with a
pilot count and a finishing record.

## Two kinds of section, and the precedence between them

`mtg-tournament-analysis` owns `## Matchup data` and `## Weekend update`. Both come
from a counted pool of matches, and both are rebuilt from CSVs rather than edited by
hand.

`vod-review` may add two things after reviewing one of your own matches:

- **Cards and interactions**, into `## Key cards` and `## Key tricks and
  interactions`, with text verified on Scryfall. These are facts about the format.
- **`## Personal experience (small sample, not tournament data)`**, a short record of
  your own games with the sample size in the header.

**The precedence rule is absolute: the matchup table wins.** Personal experience never
moves a number in it, never gets merged into it, and never gets quoted as a win rate.
A 1-2 in a single match is one data point about one match. It earns a place here for
the texture the numbers don't carry — which card actually beat you, which sideboard
card was blank — and nothing more.

## These notes stay local

`.gitignore` keeps `[C] *.md` in this folder out of the repo, and `package.py` keeps
them out of the bundle. They're your working notes about your metagame. Nothing here
needs to travel.
