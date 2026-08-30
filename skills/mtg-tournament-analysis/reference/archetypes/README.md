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

## Provenance

These are the working notes from the vault they were built in, shipped as-is. They carry their own dates and sources. Some are thorough, some are stubs with the card table filled in and the game plan still open — the front matter and the "Open" sections say which.
