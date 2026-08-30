---
author: claude
type: note
project: MTG Tournament Analysis Skill
date: 2026-08-27
archetype: Four-Color Control
aliases: [W-U-B-R Control]
colors: WUBR
sources: melee_415628_pairings.csv (PT SOS), melee_410903_pairings.csv (Champions Cup Final S4R3), mtgtop8.com/event?e=84341&d=840752, magic.gg PT SOS metagame article, 1UfUmY93K_k (OptimusTomTV — Champions Cup JP/KR + Spotlight Secrets London recap, 2026-05-12)
tags: [mtg, standard, archetype, control, four-color]
---

# Four-Color Control (W-U-B-R Control)

**Two notable performances since Secrets of Strixhaven release:**
- **Keiichiro Matsumoto won Champions Cup Final S4R3 (Japan, 2026-05-08)** on a W-U-B-R Control list — 13-2-1, 352-player event. Tournament organizers tagged this list as "W-U-B-R Control" on melee.gg; the deck is mechanically the same as Four-Color Control and is tracked under this file.
- **Nick Deriu's Resonating Lute build at PT Secrets of Strixhaven** — 8-2 in Standard (24 pts, 32nd overall). Three other PT pilots ran different 4C Control 75s and all went 1-4.

The archetype is not monolithic — each pilot registers a different 75. Two distinct lists worth analyzing: Deriu's Resonating Lute engine (PT) and Matsumoto's W-U-B-R build (Japan Champions Cup).

---

## The Matsumoto list — Champions Cup S4R3 winner (2026-05-08)

Decklist URL: melee.gg/Decklist/View/23148164-c890-43e0-b178-b44300cf2aca

Final standings record: 13-2-1 in swiss + Top 8 run. Full decklist content needs to be pulled and analyzed; the deck is registered as "W-U-B-R Control" on melee but mechanically belongs in the Four-Color Control family.

**Why it might be the better control build than Jeskai.** The Jeskai vs Four-Color comparison in the matchup data showed Four-Color outperforming Jeskai by ~2 points overall, with a 24-point gap into Selesnya Landfall. Matsumoto's win is one tournament's worth of evidence that this gap holds at the highest competitive level — but with only 70 games from this list specifically, no individual matchup hits the 10-game minimum. The combined Four-Color sample (245 games) is where the real signal lives.

_TBD — extract Matsumoto's 75 and compare to Deriu's list. Likely candidates for the red splash beyond a Jeskai shell: Slagstorm, Anger of the Gods, Wrenn and Six, Vraska's Fall (if printed). Update this section once the decklist is pulled._

---

## The Deriu list (the one that matters)

Jeskai base (Steam Vents, Hallowed Fountain, Shattered Sanctum, Meticulous Archive) splashing black via Gloomlake Verge and Godless Shrine. The nameplate card is **Resonating Lute** — 3 copies main.

### Game plan

Stall the early game with cheap interaction, land Resonating Lute to double mana for instants and sorceries, then close with Jeskai Revelation at a much lower effective cost than Jeskai Control achieves. The Lute essentially lets you fire Revelation two to three turns ahead of schedule.

### Key cards

| Card | Copies | Role |
|---|---|---|
| Resonating Lute | 3 | Mana doubler for instants/sorceries — the engine |
| Jeskai Revelation | 4 | Finisher; Lute gets this online faster |
| Consult the Star Charts | 4 | Draw and land selection |
| Stock Up | 3 | Draw and filtering |
| No More Lies | 3 | Soft counterspell |
| Inevitable Defeat | 3 | Black removal — exiles; the reason for the splash |
| Lightning Helix | 2 | Cheap interaction + life gain |
| Get Lost | 2 | Flexible removal; hits enchantments |
| Flashback | 2 | Draw (instant, gets back from graveyard) |
| Great Hall of the Biblioplex | 4 | Land that functions as a latent threat for multicolor decks |
| Meticulous Archive | 4 | Surveil / draw filter |
| Day of Judgment | 1 | Sweeper (1 main, 1 side) |
| Spell Snare | 1 | Early counter for 2-drops |

**Sideboard key cards:**
- High Noon ×2 — Prowess hate
- Stoic Sphinx ×2 — threat against aggro
- Wan Shi Tong, Librarian ×1 — flash threat, library lock
- Strategic Betrayal ×2 — graveyard exile + bounce
- Flashfreeze ×2 — blue/green counter
- Outrageous Robbery ×1 — steal opponent's gameplan

---

## Play patterns

- **Resonating Lute timing**: ideally lands on turn 3 or 4, giving you a 7-mana Revelation on turn 5 or 6 — two to three turns ahead of Jeskai Control's typical curve
- **Inevitable Defeat as the black reason**: a 3-mana instant that exiles the creature and is harder to interact with than Get Lost; targets Eddymurk Crab and Slickshot Show-Off cleanly
- **Lightning Helix in the value shell**: not just reach — stabilizes the life total while drawing through Consult and Stock Up
- **High Noon from the board**: comes in against Prowess and slows the explosive single-turn spell dumps that make Izzet dangerous

---

## PT Secrets of Strixhaven — pilot comparison

| Pilot | List URL | Standard Day 1 | Made Day 2? |
|---|---|---|---|
| **Nick Deriu** | 290f186c | **4-1** | **Yes** |
| Brandon Kohrs | 4674e77c | 1-4 | No |
| Gabriel Bostic | b5e50ad1 | 1-4 | No |
| Yang He | 6b552faa | 1-4 | No |

Deriu's 8-2 final Standard record is the only data worth building from. The other three lists don't share his URL and likely differ in meaningful ways.

---

## Weekend update — Champions Cup JP/KR + Spotlight Secrets London (2026-05-12)

Source: OptimusTomTV (1UfUmY93K_k). 32 pilots, 3.3% combined metagame share. **53.3% combined win rate — 54.2% non-mirror.** Won Champions Cup (Matsumoto). One of the two best decks of the weekend behind Selesnya Ouroboroid.

**The new build pattern** (visible in Champions Cup top lists):
- **Tablet of Discovery** — ramp/filter artifact that gets the deck a turn ahead of Jeskai's seven-mana Revelation timing. Both Four-Color Control and Jeskai Control are running it now, but Four-Color leverages it harder because of the heavier finisher curve.
- **Great Hall of the Biblioplex** — gives creatureless control builds a creature to win with AND fixes mana for Jeskai Revelation + Inevitable Defeat in a four-color shell.
- **Inevitable Defeat** stays the splash justification — exile-based removal that handles Selesnya Landfall's enchantment-based threats.

**Weekend matchup spread**:
- vs Izzet Prowess: 42.9% (still a losing matchup; Prowess is too fast)
- vs Selesnya Landfall: 53.1% (board wipes plus Inevitable Defeat on the enchantments)
- vs Izzet Spellementals: 81% (counter magic destroys the Sunderflock plan; sideboard High Noon/Rest in Peace finish the job)
- vs Izzet Lessons: 50/50
- vs Azorius Flash, Selesnya Ouroboroid, Bant Rhythm: all favored
- vs Mono-Green Landfall: bad (n=3, small sample) — Inevitable Defeat doesn't hit Bossing Say
- vs Dimir Excruciator: bad (n=3, small sample) — Cavern of Souls makes counters dead, the deceit/excruciator combo mills the answer pieces

The Japanese metagame skewed toward control this weekend, which inflated Four-Color's wins — but the matchup spread holds independent of region.

---

## Deriu's round-by-round Standard record

| Round | Opponent | Opponent's deck | Result |
|---|---|---|---|
| 4 | Jason Qiu | Izzet Maestro | Won 2-0 |
| 5 | Edgar Baumler | Izzet Prowess | **Lost 0-2** |
| 6 | Kazuya Takuwa | Simic Omniscience | Won 2-1 |
| 7 | Julian Riedener | Mono-Green Landfall | Won 2-1 |
| 8 | Andrew Elenbogen | Azorius Momo | Won 2-1 |
| 12 | Yuuki Ichikawa | Izzet Spellementals | Won 2-1 |
| 13 | Hiroki Kageyama | Izzet Prowess | Won 2-1 |
| 14 | Adam Edelson | Izzet Prowess | Won 2-1 |
| 15 | Marcus Wosner | Mono-Green Landfall | **Lost 0-2** |
| 16 | Thirawat Chaovarindr | Izzet Prowess | Won 2-0 |

---

## Matchup data

*Updated: 2026-08-27 · 19 melee.gg tournaments · 1,232 Standard matches with deck names on both sides*

**Overall: 99 games · 47W-51L-1D · Win rate 48.0% over decided games (match-win % incl. draws as 0.5: 48.0%)**

| Opponent | Win% | N | Notes |
|---|---:|---:|---|
| Izzet Prowess | 36.4% | 11 | small sample |
