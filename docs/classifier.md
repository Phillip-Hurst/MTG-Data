# The deck classifier

A win rate is only as good as the label on each deck. If half of one archetype is
filed under another name, both numbers are wrong and neither looks it. The
classifier's job is to put one canonical archetype name on every decklist, and to
say so when it can't.

## What it is

A scoring rule, with no trained model behind it. It compares a decklist against a
set of **reference lists**, one per archetype, each holding the modal copy count of
every card most decks of that archetype play. References are built from decklists
that already carry a label, through one writer (`classify/refs_store.py`).

Three numbers come out of each comparison:

| Number | Meaning |
|---|---|
| matched | slots of the reference the deck fills |
| coverage | matched ÷ reference size: how much of the archetype is in this deck |
| containment | matched ÷ deck size: how much of this deck the archetype explains |

A deck gets a **confident** label only if the best reference clears all three bars:

| Bar | Value | What it stops |
|---|---:|---|
| coverage | 0.65 | a deck being filed under an archetype it only half resembles |
| containment | 0.35 | a small reference claiming a deck it explains a third of |
| margin over the runner-up | 0.05 | a near-tie being settled by dictionary order |

Two card-level rules sit on top, because slot overlap can't see a colour or a
combo piece. A reference can **require** cards (a deck with none of them is
ineligible) or **exclude** them. Four-Color Control requires Inevitable Defeat,
which is what keeps three-colour Jeskai lists out of it. A reference can also
carry **signature** cards that settle a photo finish, worth 0.04 of coverage:
enough to break a tie, never enough to overturn a clear winner.

Code: `src/mtg_data/classify/classifier.py`. The bars are constants at the top.

## When it isn't sure, it says so

Every deck that doesn't get a confident label gets a reason, and each reason
points at a different fix:

| Status | Reason | The fix |
|---|---|---|
| uncertain | margin | two references are too close: gate them apart, or alias them as one deck |
| uncertain | containment | the reference is thin: feed it more decklists |
| uncertain | coverage | near-miss: a person should rule on it |
| unmatched | coverage (under 0.45) | no reference exists for this deck yet |

Uncertain decks go to a **review queue**: a markdown note a person reads and
rules on, deck by deck. Rulings go back in through `classify-decks
--apply-reviews` for MTGO decks and `apply-corrections` for melee.gg decks.
Unmatched decks go to `cluster-shells`, which groups them by shared core cards into
candidate archetypes and suggests names from the published vocabulary; a person
picks the name.

`apply-corrections` keeps each melee.gg ruling in `archetype_overrides.json`, which
lives apart from the scraped data. A re-scrape refetches decklists and would
otherwise overwrite every correction with whatever the classifier says, which is
exactly what happened before the overrides file existed.

When a pairing is turned into a matchup, the label comes from the first of these
that has one: a human ruling, a confident classifier verdict, the organizer's
text, or nothing (and the seat is counted as unnamed).

## How well it works

Measured on 2026-09-07 against 795 MTGO decks:

- With the current bars it agreed with **446 of 481** existing labels (93%).
  The 35 disagreements were refinements: a bare "Jeskai" resolving to Jeskai
  Control, or "Four-Color Control" splitting into its two bases.
- The rule it replaced required a raw score of 45 of 60 slots. Eight of 21
  references could never reach 45 because they were smaller than that, including
  the most-played deck in the format, so every deck of those archetypes went to
  the queue forever.
- Three Izzet references shared 94% of their slots and scored within 1 to 3 of
  each other on the same decks. The margin bar exists because of them.

**Read the 93% with care.** The bars were tuned on the same 795 decks the
agreement was measured on, and the 481 "existing labels" were the pipeline's own
earlier output. There's no held-out set of independently labelled
decks. So the number shows the new rule reproduces the old labels with fewer
coin-flips; it doesn't show the labels are right.

## Where it goes wrong

- **Thin references over-match.** A reference under 8 cards matches anything in
  its colours. `audit-refs` flags them; four were on file at the last audit.
- **New decks have no reference.** After a ban or a set release, a large share of
  the field is unmatched until someone names it. One post-ban run started with 42%
  of decks unnamed; seeding references from mtgtop8 brought that to 24%.
- **Two names for one deck.** Different sites use different house styles. Aliases
  fold them together, and an alias can only point at a name in
  `config/archetype_names.json`, so a typo splits a deck instead of merging it and
  a test fails.
- **Organizer text is a fallback, and a weak one.** Players type their own deck
  names into melee.gg. When the classifier abstains and there's no ruling, that
  text is what gets counted, and it's counted separately so it can be discounted.

## What it would take to trust it further

If this fed a decision that mattered more than which deck to register on Saturday,
these are the next steps:

1. A held-out set of decklists labelled by someone other than the person who tuned
   the bars, never used for tuning.
2. Per-archetype precision and recall on that set, and a confusion matrix, so the
   pairs it mixes up are named.
3. The abstention rate reported beside accuracy. A classifier that abstains on half
   the field can be 100% accurate on the half it labels.
4. The human rulings tracked as their own measure: how often a person overturns a
   confident verdict is the best signal available that the bars have drifted.
