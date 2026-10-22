#!/usr/bin/env python3
"""
refine_refs.py — keep the references sharp as the data grows.

audit_refs.py tells you the references are colliding. This fixes the two things
that make them collide, from the labelled decks rather than from opinion:

  --signatures   derive each archetype's tells and write them onto its
                 reference. A signature is a card in most of one archetype's
                 decks and almost none of any rival's. classifier uses them to
                 settle a photo finish.

  --gates        for every colliding pair, work out what one plays that the
                 other never does. **Reports only — it never writes.** A gate is
                 a statement about what a deck is, and that is the user's call.

Why gates are reported and not applied
--------------------------------------
A good gate is worth a lot. Mono Green Landfall against Selesnya Landfall was
108 of the 109 margin ties in one run: not 108 judgements, one — does the white
half make it a different deck. Encoded once, the queue loses 108 entries.

Writing them in bulk is a different thing, and it was measured and rejected on
2026-09-07. Auto-deriving a `requires` for all 26 colliding pairs took confident
classifications from **743 down to 592**. The reason is structural: a `requires`
says a deck must play one of these cards to be this archetype, and across 42
narrow references that gates plenty of decks out of their own archetype. Tightening
the derivation from 9 cards at 55% to 3 at 70% made it worse, not better.

So this reports the discriminators and stops. Apply the ones you agree with by
hand, where you know the distinction is real.

Run after any run that adds references, which is what makes the loop close:

    python mtg.py cluster-shells --apply
    python mtg.py refine-refs --signatures --gates --write
    python mtg.py classify-decks --rerun
"""
import argparse
import itertools
import json
import os
import sys

from mtg_data.classify import classifier, refs_store
from mtg_data.classify import classify_decks as cd
from mtg_data.core.paths import ROOT_DIR
from mtg_data.core.stats import normalize

DATA_DIR = os.environ.get("MTG_DATA_DIR", ROOT_DIR)
REFS_FILE = os.path.join(DATA_DIR, "archetype_refs.json")
CACHE_FILE = os.path.join(DATA_DIR, "melee_deck_cache.json")


def _alias(name):
    return normalize(name)


def labelled_pools():
    """{archetype: [mainboard, ...]} from every deck that already carries a label."""
    pools = {}
    try:
        cls = cd.load_classifications()
        for event in cd.load_events(cd.CHALL_JSON, cd.DUMP_JSON):
            for deck in event.get("decks", []):
                uid = cd.deck_uid(event, deck)
                main = cd.normalize_deck(deck.get("mainboard") or {})
                arch = (cls.get(uid) or {}).get("archetype")
                if main and arch:
                    pools.setdefault(_alias(arch), []).append(main)
    except Exception as e:
        print(f"  (no MTGO data read: {e})")
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as fh:
                cache = json.load(fh)
            for data in cache.values():
                if data.get("mainboard") and not data.get("failed"):
                    pools.setdefault(_alias(data["archetype"]), []).append(
                        data["mainboard"])
        except (OSError, ValueError):
            pass
    return pools


def do_signatures(refs, pools, write):
    flat = [(a, m) for a, ms in pools.items() for m in ms]
    sigs = classifier.signature_cards(flat)
    changed = 0
    print(f"\nSignatures from {len(flat)} labelled deck(s):\n")
    for name in sorted(refs):
        cards = sigs.get(name)
        shown = ", ".join(cards[:5]) if cards else "(nothing unique to it — it "
        if not cards:
            shown += "leans on requires/excludes instead)"
        print(f"  {name:36} {shown}")
        if write:
            if cards:
                refs[name]["signature"] = cards
                changed += 1
            else:
                refs[name].pop("signature", None)
    return changed


def collisions(refs, threshold=0.60):
    out = []
    for a, b in itertools.combinations(sorted(refs), 2):
        ma = refs[a].get("mainboard") or {}
        mb = refs[b].get("mainboard") or {}
        if not ma or not mb:
            continue
        shared = sum(min(ma.get(c, 0), mb.get(c, 0)) for c in set(ma) | set(mb))
        smaller = min(sum(ma.values()), sum(mb.values())) or 1
        if shared / smaller >= threshold:
            out.append((shared / smaller, a, b))
    out.sort(reverse=True)
    return out


def do_gates(refs, pools, write, threshold=0.60):
    pairs = collisions(refs, threshold)
    if not pairs:
        print("\nNo colliding pairs. Nothing to gate.")
        return 0
    print(f"\n{len(pairs)} colliding pair(s). What separates them, from the decks:\n")
    changed = 0
    for overlap, a, b in pairs:
        da, db = pools.get(a, []), pools.get(b, [])
        print(f"  {a}  vs  {b}   ({overlap:.0%} shared, {len(da)}/{len(db)} decks)")
        if len(da) < 3 or len(db) < 3:
            print("    not enough labelled decks on one side to derive a gate\n")
            continue
        # A gate must be a tell, not a list. Nine cards each present in 55% of
        # one side is a loose net: it gates decks out of their own archetype and
        # turns a margin tie into a coverage failure. Three cards at 70% is a
        # card a person would actually name.
        only_a, only_b = refs_store.discriminators(
            da, db, min_share=0.70, max_other=0.05, limit=3)
        if not only_a and not only_b:
            print("    nothing separates them. This is one deck under two names — "
                  "add an alias in mtg_stats.ARCHETYPE_ALIASES\n")
            continue
        if only_a:
            print(f"    only {a} plays: {', '.join(only_a)}")
        if only_b:
            print(f"    only {b} plays: {', '.join(only_b)}")
        if False:  # never auto-applied; see the module docstring
            # Only ever the `requires` half, never `excludes`.
            #
            # Applying both sides looked symmetric and was wrong. Near-identical
            # archetypes share most of their cards, so a deck often holds cards
            # from both lists: excluded from A, and not always satisfying B's
            # requires. On 2026-09-07 that turned 174 margin ties into 205
            # coverage failures — the gate disqualified both sides instead of
            # picking one.
            #
            # A one-sided requires is enough. A deck with B's distinctive cards
            # is eligible for both and outscores on B; a deck without them is
            # eligible for A and unaffected. Nothing can be stranded.
            #
            # `excludes` still exists for hand-authoring, where a person knows
            # the distinction is an absence — Mono Green Landfall not playing
            # the white half is the case it was built for.
            side = b if only_b else a
            cards = only_b or only_a
            refs[side]["requires"] = sorted(
                set(refs[side].get("requires") or []) | set(cards))
            print(f"    -> {side} requires any of them; {a if side == b else b} "
                  f"left open so nothing is stranded")
            changed += 1
        print()
    return changed


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--signatures", action="store_true", help="Derive signature cards")
    p.add_argument("--gates", action="store_true",
                   help="Propose requires/excludes for colliding pairs")
    p.add_argument("--write", action="store_true",
                   help="Apply what's proposed (default is to print only)")
    p.add_argument("--overlap", type=float, default=0.60, metavar="X",
                   help="Slot overlap that counts as a collision (default 0.60)")
    args = p.parse_args()
    if not (args.signatures or args.gates):
        p.error("pick --signatures, --gates, or both")

    doc = refs_store.load_doc(REFS_FILE)
    refs = doc["archetypes"]
    if not refs:
        print(f"No references in {REFS_FILE}.")
        return 1
    pools = labelled_pools()

    changed = 0
    if args.signatures:
        changed += do_signatures(refs, pools, args.write)
    if args.gates:
        do_gates(refs, pools, False, args.overlap)
        print("  Gates are reported, never written. Applying them in bulk was "
              "measured on 2026-09-07 and cost 151 classifications.\n"
              "  Add the ones you agree with by hand to archetype_refs.json.")

    if args.write and changed:
        refs_store.save(REFS_FILE, refs, source="refine-refs", quiet=True)
        print(f"Written. {changed} reference(s) refined.")
        print("Re-run python mtg.py classify-decks --rerun so live decks pick this up.")
    elif not args.write:
        print("Nothing written. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
