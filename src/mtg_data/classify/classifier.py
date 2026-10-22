#!/usr/bin/env python3
"""
classifier.py — the one scoring model. Which archetype is this deck?

Why this replaced the old one
-----------------------------
The old rule was "sum of min(deck_count, ref_count), confident at 45 of 60".
Two things were wrong with it, and together they grew the review queue instead
of draining it. Measured on 2026-09-07 against 795 MTGO decks, 263 of which had
never been classified:

1. **The threshold was in the wrong unit.** References are built from whatever
   decks happen to be cached, so they range from 15 to 63 total slots. A
   reference summing to 36 slots can never score 45, so every deck of that
   archetype went to the queue forever however perfect the match. Eight of the
   twenty-one references were in that state, including Mono Green Landfall,
   the most-played deck in the format.

2. **Selection had no margin.** Izzet, Izzet Elementals and Izzet Spellementals
   shared 94% of their slots and scored within 1-3 of each other on the same
   decks, so the winner was decided by dictionary order.

Both are fixed by scoring in ratios and requiring the winner to actually win.

The three numbers
-----------------
    matched      slots of the reference the deck satisfies (the old score)
    coverage     matched / reference size    "how much of the archetype is here"
    containment  matched / deck size         "how much of the deck this explains"

Coverage is comparable across references of different sizes, which is the fix
for (1). Containment stops a small reference claiming a deck it only explains a
third of. A verdict needs both, plus a `margin` of coverage over the runner-up,
which is the fix for (2).

Defaults, tuned on the 795-deck corpus: coverage 0.65, containment 0.35, margin
0.05. That agrees with 446 of 481 existing labels; all 35 disagreements are
refinements (bare "Jeskai" resolving to Jeskai Control, "Four-Color Control"
splitting into its base) rather than errors.

Two card-level rules
--------------------
Slot overlap can't see a colour or a combo piece, so a reference can carry:

    "requires":  [card, ...]   a deck playing none of these is ineligible
    "signature": [card, ...]   near-unique to this deck; breaks ties

`requires` is a hard gate. Four-Color Control requires Inevitable Defeat, which
is what stops three-colour Jeskai scoring into it. `signature` is a soft nudge
for the case where two references are genuinely close and one card settles it.
Derive signatures with `signature_cards()` rather than guessing at them.
"""
import os
import sys
from collections import namedtuple


from mtg_data.classify import refs_store
from mtg_data.core.paths import ROOT_DIR

# Tuned on the 795-deck MTGO corpus, 2026-09-07. See the module docstring.
MIN_COVERAGE = 0.65
MIN_CONTAINMENT = 0.35
MIN_MARGIN = 0.05
# Below this coverage a deck isn't a near-miss, it's a deck we have no reference
# for. Worth saying differently in the queue, because the fix is different:
# a near-miss wants a ruling, an unmatched deck wants a new reference.
UNCERTAIN_COVERAGE = 0.45

# A signature hit is worth this much coverage when breaking a tie. Small on
# purpose: it should settle a photo finish, never overturn a clear winner.
SIGNATURE_BONUS = 0.04

Candidate = namedtuple(
    "Candidate", "archetype matched coverage containment adjusted signatures")
Verdict = namedtuple(
    "Verdict", "archetype status matched coverage containment margin runner_up "
               "reason candidates")


def deck_size(mainboard):
    return sum(mainboard.values()) or 60


def score_one(deck_main, entry):
    """(matched slots, coverage, containment) of one deck against one reference."""
    mb = (entry or {}).get("mainboard") or {}
    if not mb or not deck_main:
        return 0, 0.0, 0.0
    matched = sum(min(deck_main.get(card, 0), n) for card, n in mb.items())
    return matched, matched / (sum(mb.values()) or 1), matched / deck_size(deck_main)


def rank(deck_main, refs, signature_bonus=SIGNATURE_BONUS):
    """
    Every eligible reference, best first, as Candidate tuples.

    Ordering is by raw coverage, then containment, then matched slots.
    References the deck is ineligible for (see refs_store.eligible) don't
    appear at all.

    Signatures deliberately do NOT enter the ordering. Coverage saturates at
    1.0, so among references the deck fully satisfies a bonus decides the
    winner instead of the better description — a reference explaining 64 slots
    of the deck lost to one explaining 60 that happened to carry a tell.
    Signatures are applied in `classify`, and only to a genuine photo finish.
    `adjusted` is carried for reporting and equals coverage plus the bonus.
    """
    out = []
    for name, entry in (refs or {}).items():
        if not (entry or {}).get("mainboard"):
            continue
        if not refs_store.eligible(deck_main, entry):
            continue
        matched, coverage, containment = score_one(deck_main, entry)
        hits = [c for c in (entry.get("signature") or []) if deck_main.get(c, 0) > 0]
        adjusted = coverage + (signature_bonus if hits else 0.0)
        out.append(Candidate(name, matched, coverage, containment, adjusted, hits))
    out.sort(key=lambda c: (-c.coverage, -c.containment, -c.matched, c.archetype))
    return out


def classify(deck_main, refs, min_coverage=MIN_COVERAGE,
             min_containment=MIN_CONTAINMENT, min_margin=MIN_MARGIN,
             uncertain_coverage=UNCERTAIN_COVERAGE):
    """
    One verdict. status is "confident", "uncertain", "unmatched" or "no_refs".

    `reason` says which condition failed, because a queue entry that doesn't
    say why it's there can't be acted on. The reasons map to different fixes:

        confident   nothing to do
        margin      two references are too close — separate them with a
                    requires/excludes gate, or alias them together
        containment the reference explains too little of the deck — the
                    reference is thin, feed it more decklists
        coverage    no reference is close — this archetype needs one

    A photo finish (margin under `min_margin`) is settled by signature cards
    when exactly one of the tied candidates has any. That's the whole job of a
    signature: it decides between two references the slot maths can't separate,
    and it never overturns a candidate that was already ahead on coverage.
    """
    cands = rank(deck_main, refs)
    if not cands:
        return Verdict(None, "no_refs", 0, 0.0, 0.0, 0.0, None,
                       "no eligible reference", [])

    top = cands[0]
    runner = cands[1] if len(cands) > 1 else None
    margin = top.coverage - (runner.coverage if runner else 0.0)

    if runner is not None and margin < min_margin:
        band = [c for c in cands if top.coverage - c.coverage < min_margin]
        with_tell = [c for c in band if c.signatures]
        if len(with_tell) == 1:
            top = with_tell[0]
            others = [c for c in band if c is not top]
            runner = others[0] if others else runner
            # The tell is the separation, so the photo finish is resolved.
            margin = min_margin

    if top.coverage < uncertain_coverage:
        status, reason = "unmatched", "coverage"
    elif top.coverage < min_coverage:
        status, reason = "uncertain", "coverage"
    elif top.containment < min_containment:
        status, reason = "uncertain", "containment"
    elif margin < min_margin:
        status, reason = "uncertain", "margin"
    else:
        status, reason = "confident", "confident"

    return Verdict(top.archetype, status, top.matched, top.coverage,
                   top.containment, margin,
                   runner.archetype if runner else None, reason, cands)


def signature_cards(labelled_decks, min_share=0.60, max_elsewhere=0.10,
                    min_decks=4):
    """
    Find each archetype's tells from decks that already carry a label.

    A signature is a card in at least `min_share` of one archetype's decks and
    in under `max_elsewhere` of **every other archetype's** decks, measured per
    rival rather than pooled. Those are the cards a person would name if you
    asked them how to spot the deck across the table, and they're derivable
    rather than a matter of opinion.

    Per-rival matters. Pooling dilutes the test by the size of the field: Jeskai
    Revelation is in most Jeskai Control decks and most Four-Color Control
    decks, but those are 30 decks in a 745-deck corpus, so pooled it reads as
    4% "elsewhere" and passes as a signature of both. Per-rival it fails against
    the one archetype that matters, which is the one it's supposed to
    distinguish from.

    `labelled_decks` is an iterable of (archetype, mainboard). Archetypes with
    fewer than `min_decks` examples are skipped, and rivals below that are
    ignored as rivals — a "signature" off two decks is a coincidence either way.

    Returns {archetype: [card, ...]}.
    """
    by_arch = {}
    for arch, main in labelled_decks:
        if not arch or not main:
            continue
        by_arch.setdefault(arch, []).append(set(main))

    total = {a: len(v) for a, v in by_arch.items()}
    plays = {a: {} for a in by_arch}
    for arch, decks in by_arch.items():
        for cards in decks:
            for c in cards:
                plays[arch][c] = plays[arch].get(c, 0) + 1

    rivals = [a for a in by_arch if total[a] >= min_decks]

    out = {}
    for arch in rivals:
        counts = plays[arch]
        sigs = []
        for card, n in counts.items():
            share = n / total[arch]
            if share < min_share:
                continue
            if any(plays[r].get(card, 0) / total[r] > max_elsewhere
                   for r in rivals if r != arch):
                continue
            sigs.append((share, card))
        sigs.sort(reverse=True)
        if sigs:
            out[arch] = [c for _, c in sigs[:8]]
    return out


def explain(verdict, width=3):
    """One line per top candidate, for a review note or a console dump."""
    lines = []
    for c in verdict.candidates[:width]:
        sig = f"  sig:{','.join(c.signatures)}" if c.signatures else ""
        lines.append(f"    {c.archetype:36} {c.matched:2d} slots  "
                     f"cov {c.coverage:.2f}  con {c.containment:.2f}{sig}")
    return "\n".join(lines)
