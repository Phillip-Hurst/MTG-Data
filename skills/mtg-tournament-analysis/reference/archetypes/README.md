# Archetype reference notes

One note per Standard archetype: game plan, key cards with verified text, play patterns, and matchup data where it exists.

## What these are for

**These filenames are the canonical archetype vocabulary.** Every source names decks differently — melee lets players type whatever they want, mtgtop8 has its own house style, MTGO publishes nothing at all. Pick any one of them and the same deck ends up under three labels, which splits its win rate three ways and makes the matchup matrix meaningless.

So one name wins, and it's the one with a note here.

`mtg_stats.ARCHETYPE_ALIASES` maps every other spelling onto these names. `audit_refs.py --apply-aliases` collapses duplicate references onto them. A test fails if an alias ever points at a name that has no note in this folder — that's how "Izzet" briefly got mapped to "Izzet Elementals", which had no note, while "Izzet Spellementals" did.

## Adding one

A new archetype earns a note when it's a real deck rather than a spread of brews. `card_signal.py --lens unnamed` finds the candidates: a group sharing a core, with a pilot count and a finishing record.

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

**Card text comes from Scryfall, always.** A note full of cards described from memory is worse than a short one — it reads as authoritative and isn't. Where a card hasn't been verified, say so in the note rather than guessing.

Once the note exists, add the alias in `mtg_stats.py` so every source's spelling resolves to it.

## Two kinds of section, and the precedence between them

`mtg-tournament-analysis` owns `## Matchup data` and `## Weekend update`. Both come
from a counted pool of matches, and both are rebuilt from CSVs rather than edited by
hand.

`vod-review` may add two things after reviewing one of the user's own matches:

- **Cards and interactions**, into `## Key cards` and `## Key tricks and
  interactions`, with text verified on Scryfall. These are facts about the format.
- **`## Personal experience (small sample, not tournament data)`**, a short record of
  the user's own games with the sample size in the header.

**The precedence rule is absolute: the matchup table wins.** Personal experience never
moves a number in it, never gets merged into it, and never gets quoted as a win rate.
A 1-2 in a single match is one data point about one match. It earns a place here for
the texture the numbers don't carry — which card actually beat you, which sideboard
card was blank — and nothing more.

## Provenance

These are the working notes from the vault they were built in, shipped as-is. They carry their own dates and sources. Some are thorough, some are stubs with the card table filled in and the game plan still open — the front matter and the "Open" sections say which.
