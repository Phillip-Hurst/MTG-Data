---
name: deck-check
description: Assign the right archetype to Magic tournament decks that were mislabeled or left uncategorized, and push that label into the data the win-rate and matchup numbers are built from. Use when the user wants to fix deck labels, name an unnamed shell, apply corrections they marked up in Obsidian, or clear the mislabel review queue. Trigger on phrasings like "fix the mislabeled decks", "apply my label corrections", "I marked up the mislabel note", "name these uncategorized decks", "what's in the review queue", "this deck is labelled wrong", "clear the deck-check backlog", or any request pairing deck archetype names with a correction.
---

# deck-check

One job: get every deck under the right archetype name, and make that name the one the win-rate and matchup numbers use.

## Related skills in this plugin

| Skill | What it's for | Hand off when |
|---|---|---|
| `mtg-tournament-analysis` | Meta reads: shares, win rates, matchup matrices, what changed, and card-level signal across the field (`python mtg.py card-signal`) | The user wants to know about the format rather than fix a label. Send them there **after** clearing the queue — a matchup matrix built on wrong labels is worse than none |
| `vod-review` | Reviews the user's own games and finds the decisions that decided them | An opponent's deck has been named and the question becomes how the match was played |
| `rules-check` | Quotes the Comprehensive Rules. Priority, the stack, triggers, state-based actions, layers | A ruling is needed. Naming a deck is a judgement call about what a deck *is*; this is the skill for what the rules *say* |

`mtg-price-check` prices a Moxfield binder against Face to Face Games. It is a separate skill and does not ship in this plugin, so point the user at it by name rather than assuming it is installed.

`mtg-tournament-analysis` does **not** categorize decks. It reports which cards are performing in uncategorized decks and stops there. Naming them is this skill's job, and it's the only thing that turns those cards into an archetype with a win rate.

---

## The loop

```
build-refs-from-melee     →  [C] Mislabeled Decks YYYY-MM-DD.md
                                      ↓
                            you edit Decision: lines in Obsidian
                                      ↓
apply-corrections         →  archetype_overrides.json  (the durable ruling)
                                      ↓
              melee_*_pairings.csv · melee_*_standings.csv     ← win rates, matchups
              melee_deck_cache.json · mtgo_classifications.json ← shares, references
```

## The other loop: draining the MTGO queue

The one above fixes labels that are wrong. This one fixes decks that have no
label at all, which is what actually makes a queue grow.

```
classify-decks --rerun      →  [C] MTGO Review Queue.md   (one rolling file)
                                      ↓  reason: coverage
cluster-shells              →  [C] Unnamed Shells YYYY-MM-DD.md
                                      ↓  you fill in Name: lines
cluster-shells --apply      →  new references
refine-refs --signatures --gates --write
classify-decks --rerun      →  a shorter queue

(each line is `python mtg.py <command>`)
```

**Read the reason split before working through the queue deck by deck.** Each
reason has a different lever, and only one of them is a per-deck judgement:

| reason | what it means | what to do |
|---|---|---|
| `coverage` | no reference is close | `cluster-shells`. These are usually a handful of unnamed decks, not hundreds of brews |
| `containment` | the reference explains too little of the deck | it's thin — feed it more decklists |
| `margin` | two references are too close | `refine-refs --gates`, or alias them together |
| `no eligible reference` | every reference is gated out | check the `requires` / `excludes` lists |

A queue of 200 `coverage` entries is about 20 missing categories. Naming them is
20 decisions; triaging the decks is 200. On the first run of this loop, 27 shells
covered 83% of the queue.

**Naming a shell is still yours.** `cluster-shells` proposes and never decides.
What it guarantees is that once a shell is named, its decks stop coming back.

Suggestions come from two lookups, in order:

1. **`config/archetype_vocabulary.json`** — the format's published names, from
   MTGGoldfish's metagame table: archetype, meta share, and the three cards that
   define it. Two of three defining cards in a shell's core is a match worth
   prefilling; one is shown but flagged weak, because Deceit defines two
   archetypes and Stock Up defines four.
2. **the melee cache** — what organizers typed for lists with a similar core.
   Useful for decks too new or too fringe to be catalogued yet.

Refresh the vocabulary with `python mtg.py fetch-vocabulary` after any set release or
B&R announcement. **It's also the cheapest check on whether a deck actually
died.** On 2026-09-07 that table showed Izzet Prowess alive at 1.0% and 13 decks
after Stormchaser's Talent was banned — a ban deletes a card, and whether the
deck folds or rebuilds is a question for the data.

## Reading the note

Each flagged deck carries a `Decision:` line, pre-filled with the card match:

```markdown
### RobinVahland — Brussels Destination Qualifier
URL: https://melee.gg/Decklist/View/65772f10-...
Melee label : **Bant Combo**  (21/60 slots, 38%)
Card match  : **W-U-R-G Combo**  (58/60 slots, 97%)

Top mainboard: 4x Badgermole Cub, 4x Bloom Tender, 4x Brightglass Gearhulk

Decision: W-U-R-G Combo
```

| What you want | What to do |
|---|---|
| Card match is right | Leave it |
| Melee label was right | Type the melee label |
| Neither | Type the archetype you want |
| Not sure | Blank it, or write `skip` |

A skipped deck comes back next run. Nothing is lost by deferring.

## Running it

```bash
python mtg.py apply-corrections             # read notes, apply everywhere
python mtg.py apply-corrections --dry-run   # see what would change
python mtg.py apply-corrections --list      # what's already been ruled on
python mtg.py apply-corrections --reapply   # after a scrape, restore the rulings
python mtg.py build-refs-from-melee --rebuild-only   # feed rulings into future matching
```

Reads every note it finds, skips entries already recorded, safe to re-run. It prints each folder it searched with a count and **exits non-zero when it finds nothing**, rather than reporting success on an empty run.

Notes written before 2026-08-29 have no `Decision:` line. Add them, pre-filled:

```bash
python mtg.py apply-corrections --backfill --dry-run
python mtg.py apply-corrections --backfill
```

## Where a correction lands, and why that matters

| Written to | Read by |
|---|---|
| `archetype_overrides.json` | This script, on every `--reapply` |
| **`melee_*_pairings.csv` / `*_standings.csv`** | **`matchup-matrix`, `winrate-analysis`, `build-baseline`** |
| `melee_deck_cache.json` | `build-refs-from-melee`, archetype references |
| `mtgo_classifications.json` | MTGO archetype shares |

The bolded row is the point of this skill. `mtg_stats.classify_row` reads `player1_deck` / `player2_deck` straight off the CSV row and never touches the decklist cache, so a correction that only reaches the cache leaves the matchup matrix reporting the old label forever.

Because it writes all four, the next win-rate or matchup check uses the corrected labels with no rescrape.

## Where references come from

Three sources, in order of how much work they cost:

| Source | Command | Gives you |
|---|---|---|
| **mtgtop8** | `python mtg.py build-mtgtop8-baseline --format Standard` | Meta share plus real decklists for the top archetypes, server-rendered HTML, stdlib fetch, no browser. **Start here.** |
| local melee cache | `python mtg.py build-refs-from-melee --rebuild-only` | References for whatever your own scrapes have covered. Better lists, far narrower coverage. |
| MTGGoldfish | — | Fetchable for meta share, but duplicates what mtgtop8 gives and its decklists sit behind more layers. Cross-check only. |

mtgdecks.net returns HTTP 403 behind Cloudflare. Don't build on it.

**Every write to `archetype_refs.json` goes through `classify/refs_store.py`, and merging is the default.** A run only builds references for archetypes it has enough cached decks for, so replacing the whole set meant everything below the bar vanished, silently, exit 0. Now a label absent from a run's output is kept, and a label present is only overwritten when this run has at least as many decklists behind it. Refs from another era or another format are still rejected before they land.

The write reports added / updated / kept / untouched, plus the total decklists behind the references. **That total should climb scrape over scrape.** If it falls, something replaced instead of merging.

Two controls matter:

- `--replace-refs` on `build-refs-from-melee` or `classify-decks --build-refs` discards everything and keeps only this run's output. That's a reset, not a rebuild. It backs up to `archetype_refs.pre-replace.json` first, and nothing should reach for it on a schedule.
- `"pinned": true` on an entry means no automated rebuild touches it. Use it when a reference is anchored on a list no scrape will ever produce. `Four-Color Control (Black Base)` is anchored on Deriu's MTGGoldfish 75, so it's pinned until enough of the field is cached.

**A reference can require a card.** `"requires": ["Inevitable Defeat"]` makes a deck ineligible for that reference unless it plays one of the named cards, whatever its slot overlap says. Slot overlap can't see a colour: three-colour Jeskai Control shares Jeskai Revelation, Tablet of Discovery, Consult the Star Charts, Stock Up and most of a manabase with four-colour Jeskai Tablet, so it scored 30-40 against the wrong reference and came back through the queue on every run. Reach for this when two archetypes keep tying and one card genuinely separates them.

**Re-seed after every ban and every set release.** That's what keeps the unnamed share down. On 2026-08-29, seeding from mtgtop8 took it from 42% to 24% in one command.

## Auditing the references

```bash
python mtg.py audit-refs                      # full report
python mtg.py audit-refs --strict             # exit 1 on any error
python mtg.py audit-refs --apply-aliases --dry-run
python mtg.py audit-refs --apply-aliases      # collapse duplicates
```

`fetch-melee` runs the report after every scrape. What it catches:

- **banned / off-format references.** A reference built from the wrong era renames live decks to something that can't be registered.
- **collisions.** Two references sharing 60%+ of their slots produce near-tied match scores, and `classify_decks` picks on raw slot overlap with no margin — so a tie resolves by dictionary order. This is the documented root cause of the review-queue flood. When one card genuinely separates the pair, `"requires"` settles it; when nothing does, they're one archetype and want an alias.
- **the evidence total.** `Decklists behind them` is the number that should grow. A drop means a writer replaced instead of merging.
- **thin references.** Under 8 cards will over-match anything in its colours.
- **coverage.** How much of the live field has no archetype at all.

`--apply-aliases` collapses labels that `mtg_stats.ARCHETYPE_ALIASES` says are one deck, keeping whichever reference was built from more lists, and backs up to `archetype_refs.pre-alias.json`. Re-run `classify-decks --rerun` afterwards so live decks pick up the merged names.

**The canonical name is always one carried by `config/archetype_names.json`.** That file is the vocabulary the matchup tables, snapshots and win-rate numbers are written in. Adding an alias for a name it doesn't carry splits a deck instead of merging it, and a test fails if you try.

The archetype notes in `skills/mtg-tournament-analysis/reference/archetypes/` are local working notes rather than shipped content, so a fresh install has the names and none of the notes. Never treat a missing note as a missing archetype.

So naming a new deck is two steps, not one: write the note, then add the alias.

A collision the aliases don't resolve is a real question about what a deck *is*, and that's the user's call. Report it; don't invent an answer.

## Naming an unnamed shell

`card-signal --lens unnamed`, run by `mtg-tournament-analysis`, reports shells it can't name — a group of decks sharing a core, with a pilot count and a finishing record:

```
37 decks / 30 pilots  avg finish 16.0, 9 top 8s
  core: wan shi tong librarian, tishana's tidebinder, dream beavers,
        spyglass siren, kaito bane of nightmares, floodpits drowner
```

That's one archetype with no name, not 37 brews. To bring it in:

1. **Name it** by what the deck does, not by its colours. mtgtop8 filed the Amalia deck as "Orzhov Aggro"; it gains life, so it's Orzhov Lifegain.
2. **Add the name to `config/archetype_names.json`**, then **write the note** in `reference/archetypes/`. The manifest is what ships and what the alias test checks; the note is the local detail. Card text from Scryfall — a note describing cards from memory reads as authoritative and isn't. Say which cards are unverified rather than guessing.
3. **Add the alias** in `core/stats.py` so every source's spelling resolves to the new name.
4. `python mtg.py build-refs-from-melee --rebuild-only` picks it up once enough decks carry the label. Anything it keeps mismatching comes back through the review note.

A shell finishing better than the field with 10+ pilots is worth naming this week. One with 4 pilots and a worse-than-field record can wait.

## Retiring resolved notes

When every deck in a note has been ruled on, the note moves to `Mislabel Review Resolved/`. One `skip` keeps the whole note in the queue.

The folder is the to-do list. What's left in it is what still needs a decision, instead of a note per scrape piling up forever. `--delete-resolved` removes them instead of archiving; archiving is the default because these are vault notes and a wrong call should cost a move, not a recovery.

## Rules

- **Never hand-edit `melee_deck_cache.json`.** A rescrape refetches the deck and overwrites the archetype with no record a human ruled on it. That was the old instruction, and it's why the same decks kept reappearing in the queue.
- **Don't rule on a deck unless asked.** What a deck *is* is the user's call; they play the format. Surface the disagreement — melee label, card match, top of the mainboard — and let them decide.
- **Do point out consistency.** If 8 flagged decks share one mainboard, say so; they want one answer, not eight.
- **A "new" archetype name is often an old one.** Check whether the 75 already exists under a different label before adding a reference.
