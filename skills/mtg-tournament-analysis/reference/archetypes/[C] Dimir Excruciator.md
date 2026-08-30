---
author: claude
type: note
project: MTG Tournament Analysis Skill
date: 2026-08-27
archetype: Dimir Excruciator
colors: UB
sources: melee.gg decklist cache (10 lists) + melee_all_pairings.csv (1,919 decided games). Card text verified on Scryfall 2026-06-23 (DSK, SPM, SOS, ECL, TDM, TLA, DFT, LCI, MKM, OTJ).
tags: [mtg, standard, archetype, control, dimir, graveyard]
---

# Dimir Excruciator

**The fifth most-played deck in the field, and it loses more than it wins. 1,919 games, 46.7%. People are bringing it in numbers the results don't back up.**

It's a blue-black control deck that treats the graveyard as a second hand. Removal and discard hold the early game, the yard fills up, and the late game is won by recurring threats and card advantage the opponent can't match one-for-one. Doomsday Excruciator is the namesake top-end.

---

## Game plan

Trade resources until the opponent runs dry, then bury them under recursion. Cheap removal answers the early board, surveil and card draw stock the graveyard, and the back half of the deck turns that graveyard into threats and extra cards. Day of Black Sun and Deadly Cover-Up reset against decks that go wider than the spot removal can handle.

The mana is built black-heavy on purpose: Doomsday Excruciator costs six black pips, so nearly every land makes black.

---

## Play patterns

- **Superior Spider-Man** ({2}{U}{B}, 4/4) enters as a copy of any creature in a graveyard and exiles it. Point it at the best thing that died, yours or theirs, and take the ETB with it. It's reanimation stapled to removal of a graveyard target.
- **Emeritus of Ideation** ({3}{U}{U}, 5/5 flying, ward 2) is a card-advantage engine on an evasive body. It buys Ancestral Recall (draw 3), and each attack lets you exile 8 cards from the graveyard to re-arm it. The graveyard the rest of the deck fills is the fuel.
- **Winternight Stories** ({2}{U}) draws 3, discards 2 unless you pitch a creature, and can be cast again from the graveyard with Harmonize. Card advantage that also feeds the yard and refuses to stay dead.
- **Deceit** ({4}{U/B}{U/B}, 5/5) flexes on how you pay. Evoke it cheap for a bounce or a targeted discard, or hardcast the body. Spend {U}{U} to bounce a permanent, {B}{B} to strip a card.
- **Doomsday Excruciator** ({B}{B}{B}{B}{B}{B}, 6/6 flying) lands late and draws you a card every upkeep while clipping both libraries down to six cards. In a deck already grinding on card quality, it's the haymaker that ends mirrors.
- **Restless Reef** is a manland that becomes a 4/4 deathtoucher and mills on attack. It closes games through sweepers that catch the rest of the board.

---

## Notable cards

| Card | Role |
|---|---|
| Doomsday Excruciator | Top-end finisher; upkeep card draw, resets both libraries to six |
| Superior Spider-Man | Copy-a-dead-creature threat; graveyard removal attached |
| Emeritus of Ideation | 5/5 flyer that buys and recurs Ancestral Recall |
| Deceit | Modal: evoke for bounce/discard, or a 5/5 body |
| Winternight Stories | Draw 3, fills the yard, recastable via Harmonize |
| Stock Up | Card selection, dig 5 take 2 |
| Requiting Hex | Cheap removal for creatures MV2 or less; the aggro answer |
| Shoot the Sheriff | {1}{B} instant kill (misses outlaws) |
| Bitter Triumph | {1}{B} kill a creature or planeswalker |
| Strategic Betrayal | Removal + graveyard exile in one; answers recursion |
| Day of Black Sun | Scalable sweeper; set X to dodge your own threats |
| Deadly Cover-Up | Board wipe plus surgical name-exile from the opponent |

**Manabase (~26):** Swamp x9, Watery Grave x4, Gloomlake Verge x4, Restless Reef x4, Undercity Sewers x2, Cavern of Souls x2, Multiversal Passage x1. Undercity Sewers and Restless Reef quietly feed the graveyard plan while making mana.

---

## Key interactions

- **Surveil and mill into the graveyard payoffs.** Undercity Sewers, Restless Reef, and the discard from Winternight Stories aren't downside, they're setup. Every card in the yard is a target for Superior Spider-Man, fuel for Emeritus, or a Harmonize recast.
- **Strategic Betrayal is a two-for-one against the field's graveyard decks.** It exiles a creature and the whole graveyard for {1}{B}. Against reanimator or anything leaning on recursion, that's a blowout, and it overlaps with this deck's own plan as a mirror tool.
- **Day of Black Sun scales around your own board.** Set X low to sweep a creature deck's early drops while your Restless Reef (only a creature when you animate it) and a just-cast Doomsday Excruciator survive.
- **Cavern of Souls protects the key creature from counters.** In the control mirrors and against the blue tempo decks, naming the right type pushes a threat through.

---

## Weaknesses

The matchup data tells the real story, and it's not kind. The deck is built to win grindy games on card quality, and it does: it beats the other midrange and control decks. It loses to speed.

Against the fast, redundant starts it can't answer every threat in time. One-for-one removal is too slow when the opponent plays three things a turn, and the card-advantage engines come online a turn or two after the game's already been decided.

The headline problem is Izzet Prowess. It's the most-played deck in the format, Dimir Excruciator plays it more than anything else (390 games), and it loses that matchup at 42%. You can't run the most popular grind deck into the most popular aggro-tempo deck, lose that pairing, and post a winning record overall. That, plus a 37% mark against Mono-Green Landfall, is most of why the deck sits at 46.7%.

---

## Sideboard notes

Averaged across the 10 lists: Flashfreeze (counters artifact or red spells, anti-Prowess/anti-ramp), Disdainful Stroke (counter MV4+), and Ghost Vacuum (graveyard hate) are the most consistent inclusions, alongside extra Duress and a second Deadly Cover-Up. Qarsi Revenant ({1}{B}{B} 3/3 flying deathtouch lifelink, recurs from the yard with Renew) comes in as a resilient lifegain threat against aggro. Oildeep Gearhulk and Quantum Riddler round out the top end for grindy matchups.

---

## Matchup data

*Updated: 2026-08-27 · 19 melee.gg tournaments · 1,232 Standard matches with deck names on both sides*

**Overall: 80 games · 37W-41L-2D · Win rate 47.4% over decided games (match-win % incl. draws as 0.5: 47.5%)**

| Opponent | Win% | N | Notes |
|---|---:|---:|---|
| Izzet Prowess | 30.0% | 10 | small sample |
