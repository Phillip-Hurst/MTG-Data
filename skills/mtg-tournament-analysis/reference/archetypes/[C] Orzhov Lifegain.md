---
author: claude
type: note
project: MTG Tournament Analysis Skill
date: 2026-08-29
archetype: Orzhov Lifegain (Amalia; mtgtop8 files it as Orzhov Aggro)
colors: WB
sources: MTGO Challenge + 5-0 data 2026-08-11 to 08-27, 31 lists. Card text verified on Scryfall 2026-08-29.
tags: [mtg, standard, archetype, lifegain, orzhov, combo]
---

# Orzhov Lifegain

Named by Phill on 2026-08-29. mtgtop8 files it under its colours as "Orzhov Aggro", which describes the mana and not the deck. What it does is gain life, over and over, until that becomes damage.

---

## Game plan

Gain life repeatedly. Every trigger drains the opponent and grows Amalia, and either clock gets there.

Two axes running off the same engine:

- **Drain.** Starscape Cleric and Lunar Convocation both turn "you gained life" into "each opponent loses 1 life". The life total moves without attacking.
- **Amalia.** Every life-gain event explores; enough of them and she's a threat that has to be answered, with the kill-everything-else clause at exactly 20 power sitting behind it.

---

## The 11-card spine

Every one of the 31 post-ban lists runs all of these. That's unusually rigid — most archetypes this session had a spine of 8 or 9.

| Card | Copies | Role |
|---|---:|---|
| Case of the Uneaten Feast | 4.0 | — |
| Hinterland Sanctifier | 4.0 | — |
| Amalia Benavides Aguirre | 3.9 | Payoff. Explores on every life gain; destroys all other creatures if her power is exactly 20 |
| Lunar Convocation | 3.8 | Drain. End step: if you gained life, each opponent loses 1. Gained *and* lost life, make a 1/1 flying Bat |
| Haliya, Guided by Light | 3.1 | — |
| Moseo, Vein's New Dean | 2.9 | — |
| Starscape Cleric | 2.4 | Drain. {1}{B} 2/1 flier that can't block; whenever you gain life, each opponent loses 1. Offspring {2}{B} |
| Voice of Victory | 2.4 | — |

Plus the manabase: Godless Shrine, Concealed Courtyard, Plains.

Cards marked "—" are unverified as of 2026-08-29 and want a Scryfall pass before anyone writes about their role.

---

## Flex slots

| Card | Lists | Copies |
|---|---:|---:|
| Bleachbone Verge | 28/31 | 2.0 |
| Erode | 27/31 | 2.7 |
| Shattered Sanctum | 27/31 | 3.0 |
| Emptiness | 24/31 | 2.0 |
| Deep-Cavern Bat | 24/31 | 2.8 |
| Zoraline, Cosmos Caller | 23/31 | 1.0 |
| Strategic Betrayal | 21/31 | 1.0 |
| Zora, Spider Fancier | 15/31 | 1.0 |
| Aunt May | 11/31 | 1.2 |
| Clarion Conqueror | 10/31 | 1.0 |

The singleton cluster — Zoraline, Strategic Betrayal, Zora, Clarion Conqueror — is where the deck is still being figured out. Worth watching in `card_signal.py --archetype "Orzhov Lifegain"`.

---

## Record

31 decks post-ban, 24 of them in Challenges. **Average finish 17.8 against a field average of 16.5**, 4 top 8s, one win.

So: a real deck with a real spine that is currently finishing slightly below average. It converts when it converts, but nobody should read the 27-pilot count as evidence it's good. It was also the second-biggest faller inside the window, 7.4% of the field in week 1 down to 3.8% in week 2.

---

## Open

- Seven of the spine cards have no verified text here. A Scryfall pass would make this note actually useful for deckbuilding rather than just for classification.
- No matchup data. The melee pool is too thin post-ban and MTGO publishes standings without pairings.
- Whether the deck wants to be the drain deck or the Amalia deck is unresolved in the lists themselves — the flex slots don't commit either way.
