#!/usr/bin/env python3
"""
classify_decks.py -- classify MTGO decklists against known archetype references.

Reads card data from mtgo_challenge_latest.json and mtgo_5-0_latest.json
(produced by fetch_mtgo.py with the parseCards extension). Assigns archetypes
by comparing maindeck card counts against archetype_refs.json.

Classification thresholds:
  >= 45 / 60 maindeck card slots match a reference  ->  confident assignment
  30-44 / 60                                         ->  uncertain (flagged)
  <  30 / 60, or no refs exist yet                   ->  review queue

Outputs:
  mtgo_classifications.json          -- per-deck results (confident + uncertain)
  (project)/[C] MTGO Review Queue YYYY-MM-DD.md  -- decks needing manual attention

Modes:
  (default)                  Classify all decks with card data, skip already classified
  --rerun                    Reclassify everything (ignores existing classifications)
  --apply-reviews PATH       Read annotated review queue, update refs + classifications
  --build-refs               Rebuild archetype references from all confirmed classifications
  --score-challenges         Print archetype point totals from challenge data
  --analyze-5-0 [ARCHETYPE]  Mode list + aggregate + outlier analysis from 5-0 dumps
  --debug-cards              Print card counts from first deck in each JSON (selector check)
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
# Data is read from MTG_DATA_DIR (defaults to the script folder so the flat
# single-format workflow is unchanged). setup.py sets it per format.
DATA_DIR     = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)
# Review queue written next to the data by default.
# Set MTG_OUTPUT_DIR to write it elsewhere (e.g. your vault project folder).
_PROJECT_DIR = os.environ.get("MTG_OUTPUT_DIR", DATA_DIR)

REFS_FILE     = os.path.join(DATA_DIR, "archetype_refs.json")
CLASS_FILE    = os.path.join(DATA_DIR, "mtgo_classifications.json")
CHALL_JSON    = os.path.join(DATA_DIR, "mtgo_challenge_latest.json")
DUMP_JSON     = os.path.join(DATA_DIR, "mtgo_5-0_latest.json")
DECK_LOG      = os.path.join(DATA_DIR, "mtgo_deck_log.csv")

# Thresholds (out of 60 maindeck card slots)
CONFIDENT_SLOTS = 45
UNCERTAIN_SLOTS = 30

# Challenge point tables by event size
CHALLENGE_POINTS = {
    64: [(1, 10), (2, 7), (4, 5), (8, 3), (16, 1)],
    32: [(1,  8), (2, 6), (4, 4), (8, 2), (16, 1)],
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_refs():
    if not os.path.exists(REFS_FILE):
        return {}
    with open(REFS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("archetypes", {})


def save_refs(archetypes):
    existing = {}
    if os.path.exists(REFS_FILE):
        with open(REFS_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    existing["archetypes"] = archetypes
    existing.setdefault("_note",
        "Reference mainboard lists for archetype classification. "
        "Each entry: {mainboard: {card: count}, notes: str}. "
        "Populated by classify_decks.py --apply-reviews or --build-refs.")
    existing.setdefault("_schema_version", 1)
    with open(REFS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print(f"archetype_refs.json updated: {len(archetypes)} archetypes")


def load_events(*json_paths):
    """Load all events from one or more JSON files. Returns flat list of events."""
    events = []
    for path in json_paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            events.extend(data)
    return events


def load_classifications():
    if not os.path.exists(CLASS_FILE):
        return {}
    with open(CLASS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_classifications(classifications):
    with open(CLASS_FILE, "w", encoding="utf-8") as f:
        json.dump(classifications, f, indent=2, ensure_ascii=False)


def normalize_card_name(name: str) -> str:
    """
    Normalize a card name to its front face only.
    MTGO exports double-faced cards as "Front // Back" (e.g.
    "Aang, Swift Savior // Aang and La, Ocean's Fury"), while
    melee.gg and our refs store only the front face name.
    Stripping the back face lets match_score work across both sources.
    """
    return name.split(" // ")[0].strip()


def normalize_deck(card_dict: dict) -> dict:
    """
    Return a new dict with all card names normalized to front-face only.
    Counts are summed if two variants collapse to the same name
    (e.g. foil + non-foil DFCs -- shouldn't happen in practice).
    """
    out = {}
    for card, count in card_dict.items():
        norm = normalize_card_name(card)
        out[norm] = out.get(norm, 0) + count
    return out


def match_score(deck_main, ref_main):
    """
    Sum of min(deck_count, ref_count) over all cards in the reference.
    Measures how many card slots in the reference are satisfied by the deck.
    Both sides are expected to already be normalized (front-face only).
    """
    return sum(
        min(deck_main.get(card, 0), count)
        for card, count in ref_main.items()
    )


def ref_total(ref_main):
    return sum(ref_main.values()) or 60


def classify(deck_main, refs):
    """
    Returns (archetype_name, matched_slots, ratio, all_scores_dict).
    ratio = matched_slots / ref_total for the best match.
    Returns (None, 0, 0.0, {}) when no refs exist or deck has no cards.
    """
    if not refs or not deck_main:
        return None, 0, 0.0, {}

    scores = {}
    for name, ref in refs.items():
        ref_mb = ref.get("mainboard", {})
        if not ref_mb:
            continue
        score = match_score(deck_main, ref_mb)
        scores[name] = (score, score / ref_total(ref_mb))

    if not scores:
        return None, 0, 0.0, {}

    # Select by RAW matched slots, with ratio as the tie-breaker.
    # The confident/uncertain thresholds downstream are measured in raw slots
    # (45/30 of 60), so selection must use the same currency. Picking by ratio
    # let small/stub references (e.g. a 19-card land-only ref) win on a high
    # ratio, then fail the raw-slot threshold and wrongly send a complete,
    # well-matched deck to the review queue.
    best = max(scores, key=lambda k: (scores[k][0], scores[k][1]))
    best_score, best_ratio = scores[best]
    return best, best_score, best_ratio, {k: v[0] for k, v in scores.items()}


def divergent_cards(deck_main, ref_main):
    """
    Returns (new_cards, cuts).
    new_cards: in deck at >= 2 copies, absent from reference  ->  tech / new card
    cuts:      in reference at >= 3 copies, absent from deck  ->  potential strategy shift
    """
    new_cards = [
        {"card": card, "count": count}
        for card, count in deck_main.items()
        if card not in ref_main and count >= 2
    ]
    cuts = [
        {"card": card, "ref_count": count}
        for card, count in ref_main.items()
        if count >= 3 and card not in deck_main
    ]
    return new_cards, cuts


def score_place(place_str, event_name):
    """Points for a Challenge finish based on place and event size."""
    try:
        place = int(place_str)
    except (TypeError, ValueError):
        return 0

    # Detect event size from name ("challenge 64" vs "challenge 32")
    size = 64
    m = re.search(r'challenge[- ](\d+)', event_name, re.IGNORECASE)
    if m:
        size = int(m.group(1))
        if size not in CHALLENGE_POINTS:
            size = 64

    for cutoff, pts in sorted(CHALLENGE_POINTS[size]):
        if place <= cutoff:
            return pts
    return 0


def deck_uid(event, deck):
    """Stable identifier for a deck: event URL + deck fragment URL."""
    return f"{event.get('url','')};{deck.get('url','')}"


# ─── Review queue generation ──────────────────────────────────────────────────

def write_review_queue(to_review, run_date_str):
    """
    Write a markdown file listing decks that need manual archetype classification.
    to_review: list of dicts with keys: uid, event_name, event_date, place, player,
               mainboard, sideboard, best_match, best_score, best_ratio, status
    """
    path = os.path.join(
        _PROJECT_DIR,
        f"[C] MTGO Review Queue {run_date_str}.md"
    )

    lines = [
        "---",
        "author: claude",
        "type: note",
        "project: MTG Tournament Analysis Skill",
        f"date: {run_date_str}",
        "tags: [mtg, mtgo, review-queue]",
        "---",
        "",
        f"# MTGO classification review queue, {run_date_str}",
        "",
        "Fill in `archetype:` for each deck below.",
        "",
        "  Existing archetype  ->  archetype: Izzet Prowess",
        "  New archetype       ->  archetype: NEW: Grixis Midrange",
        "  Junk / skip         ->  archetype: SKIP",
        "",
        "When done, run from Skills/mtg-tournament-analysis/:",
        f"  python classify_decks.py --apply-reviews \"{path}\"",
        "",
        "---",
        "",
    ]

    for i, d in enumerate(to_review, 1):
        total_main = sum(d.get("mainboard", {}).values())
        total_side = sum(d.get("sideboard", {}).values())
        hint = ""
        if d.get("best_match") and d.get("status") == "uncertain":
            hint = (f"  (closest match: {d['best_match']}, "
                    f"{d['best_score']}/{int(d['best_ratio']*60+0.5)} slots, "
                    f"{d['best_ratio']*100:.0f}%)")

        lines += [
            f"## Deck {i} | player: {d.get('player','')} | place: {d.get('place','')} | "
            f"event: {d.get('event_name','')} {d.get('event_date','')}",
            f"deck_uid: {d.get('uid','')}",
            "",
            f"archetype: {hint}",
            "",
        ]

        if d.get("mainboard"):
            lines.append(f"### Mainboard ({total_main})")
            for card, count in sorted(d["mainboard"].items(), key=lambda x: -x[1]):
                lines.append(f"{count} {card}")
            lines.append("")

        if d.get("sideboard"):
            lines.append(f"### Sideboard ({total_side})")
            for card, count in sorted(d["sideboard"].items(), key=lambda x: -x[1]):
                lines.append(f"{count} {card}")
            lines.append("")

        lines.append("---")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Review queue written: {os.path.basename(path)}")
    print(f"  {len(to_review)} decks need attention")
    return path


# ─── apply-reviews parser ─────────────────────────────────────────────────────

def parse_review_file(path):
    """
    Read a user-annotated review queue markdown.
    Returns list of dicts: {uid, archetype, mainboard, sideboard}.
    Only entries with a non-empty, non-placeholder archetype are returned.
    """
    with open(path, encoding="utf-8") as f:
        content = f.read()

    # Split on "## Deck N" headers
    sections = re.split(r'\n## Deck \d+', content)
    results = []

    for section in sections[1:]:
        # Extract uid
        uid_m = re.search(r'^deck_uid:\s*(.+)$', section, re.MULTILINE)
        uid = uid_m.group(1).strip() if uid_m else ""

        # Extract archetype (skip blanks, hints, and placeholders)
        arch_m = re.search(r'^archetype:\s*(.+)$', section, re.MULTILINE)
        if not arch_m:
            continue
        archetype_raw = arch_m.group(1).strip()
        # Strip the hint comment "(closest match: ...)"
        archetype = re.sub(r'\s*\(closest match:.*\)', '', archetype_raw).strip()
        if not archetype or archetype in ('?', ''):
            continue

        # Extract mainboard
        mainboard = {}
        sideboard = {}
        target = None
        for line in section.split('\n'):
            if '### Mainboard' in line:
                target = mainboard
                continue
            if '### Sideboard' in line:
                target = sideboard
                continue
            if target is not None:
                # Allow long and double-faced names (e.g. "Front // Back");
                # the old 60-char cap silently dropped them from rebuilt refs.
                m = re.match(r'^(\d+)\s+(.{2,200})$', line.strip())
                if m:
                    target[m.group(2).strip()] = int(m.group(1))

        results.append({
            "uid": uid,
            "archetype": archetype,
            "mainboard": mainboard,
            "sideboard": sideboard,
        })

    return results


def build_ref_from_decks(decks_for_archetype):
    """
    Given a list of {mainboard: dict} for one archetype, build a reference
    mainboard using the modal copy count per card across those lists.
    Only includes cards appearing in > 50% of lists.
    """
    n = len(decks_for_archetype)
    if n == 0:
        return {}

    card_counts = {}  # card -> list of per-deck copy counts
    for deck in decks_for_archetype:
        for card, count in deck.get("mainboard", {}).items():
            # Normalize DFC names ("Front // Back" -> "Front") so refs built here
            # match those from build_refs_from_melee.py and MTGO exports. The two
            # build_ref_from_decks functions must stay in sync.
            norm = card.split(" // ")[0].strip()
            card_counts.setdefault(norm, []).append(count)

    ref = {}
    for card, counts in card_counts.items():
        freq = len(counts) / n
        if freq > 0.5:
            modal = Counter(counts).most_common(1)[0][0]
            ref[card] = modal

    return ref


# ─── 5-0 aggregate analysis ───────────────────────────────────────────────────

def analyze_5_0(events, classifications, archetype_filter=None):
    """
    For each archetype (or just archetype_filter if given):
    - mode list: cards in > 50% of lists, modal copy count
    - aggregate: all cards sorted by list frequency
    - outliers: in >= 2 lists but absent from mode list
    """
    # Group 5-0 decks by archetype
    arch_decks = {}
    for event in events:
        if event.get("event_type") != "5-0":
            continue
        for deck in event.get("decks", []):
            uid = deck_uid(event, deck)
            cl = classifications.get(uid, {})
            arch = cl.get("archetype")
            if not arch or arch in ("Unknown", "SKIP"):
                continue
            if archetype_filter and arch.lower() != archetype_filter.lower():
                continue
            arch_decks.setdefault(arch, []).append(deck)

    if not arch_decks:
        print("No classified 5-0 decks found. Run classify first, or check archetype name.")
        return

    for arch, decks in sorted(arch_decks.items()):
        n = len(decks)
        print(f"\n{'='*60}")
        print(f"  {arch}  ({n} 5-0 lists)")
        print(f"{'='*60}")

        card_data = {}
        for deck in decks:
            for card, count in deck.get("mainboard", {}).items():
                cd = card_data.setdefault(card, {"lists": 0, "counts": []})
                cd["lists"] += 1
                cd["counts"].append(count)

        # Mode list: > 50% frequency
        mode = {}
        for card, cd in card_data.items():
            if cd["lists"] / n > 0.5:
                modal = Counter(cd["counts"]).most_common(1)[0][0]
                mode[card] = {"modal_count": modal, "freq_pct": cd["lists"] / n * 100}

        print(f"\nModal build ({len(mode)} cards, core across >50% of lists):")
        for card, info in sorted(mode.items(), key=lambda x: (-x[1]["modal_count"], x[0])):
            print(f"  {info['modal_count']}  {card}  ({info['freq_pct']:.0f}% of lists)")

        # Aggregate: everything sorted by list frequency
        agg = sorted(card_data.items(), key=lambda x: -x[1]["lists"])
        total_mode_slots = sum(v["modal_count"] for v in mode.values())
        print(f"\nFull aggregate ({len(agg)} unique cards, {total_mode_slots} mode slots):")
        for card, cd in agg:
            avg = sum(cd["counts"]) / len(cd["counts"])
            in_mode = "*" if card in mode else " "
            print(f"  {in_mode} {cd['lists']:2d}/{n} lists  avg {avg:.1f}x  {card}")

        # Outliers: >= 2 lists, absent from mode
        outliers = [(card, cd) for card, cd in agg if cd["lists"] >= 2 and card not in mode]
        if outliers:
            print(f"\nOutliers (>=2 lists, not in mode build) -- tech / meta reads:")
            for card, cd in outliers:
                avg = sum(cd["counts"]) / len(cd["counts"])
                print(f"  {cd['lists']:2d}/{n} lists  avg {avg:.1f}x  {card}")


# ─── Challenge scoring ────────────────────────────────────────────────────────

def score_challenges(events, classifications):
    arch_points = {}
    arch_top8 = {}

    for event in events:
        if event.get("event_type") not in ("challenge", "other"):
            continue
        event_name = event.get("name", "")
        for deck in event.get("decks", []):
            uid = deck_uid(event, deck)
            cl = classifications.get(uid, {})
            arch = cl.get("archetype")
            if not arch or arch in ("Unknown", "SKIP", None):
                continue
            pts = score_place(deck.get("place", ""), event_name)
            arch_points[arch] = arch_points.get(arch, 0) + pts
            try:
                place = int(deck.get("place", "99"))
                if place <= 8:
                    arch_top8[arch] = arch_top8.get(arch, 0) + 1
            except ValueError:
                pass

    if not arch_points:
        print("No scored challenge decks found. Classify challenge decks first.")
        return

    print(f"\n{'Archetype':<35} {'Points':>7} {'Top 8s':>7}")
    print("-" * 52)
    for arch, pts in sorted(arch_points.items(), key=lambda x: -x[1]):
        t8 = arch_top8.get(arch, 0)
        print(f"  {arch:<33} {pts:>7} {t8:>7}")


# ─── Core classify run ────────────────────────────────────────────────────────

def run_classify(events, refs, classifications, rerun=False):
    to_review = []
    new_confident = 0
    new_uncertain = 0   # uncertain/unmatched with refs present
    new_no_refs = 0     # no refs yet
    no_cards = 0        # no card data in source

    for event in events:
        event_name = event.get("name", "")
        event_date = event.get("date", "")
        for deck in event.get("decks", []):
            uid = deck_uid(event, deck)

            if not rerun and uid in classifications:
                continue  # already classified

            # Normalize DFC names ("Front // Back" -> "Front") so MTGO
            # card data matches melee-sourced archetype_refs.json.
            main = normalize_deck(deck.get("mainboard", {}))
            side = normalize_deck(deck.get("sideboard", {}))

            if not main:
                no_cards += 1
                # Still add to review queue so user can see what we have
                to_review.append({
                    "uid": uid,
                    "event_name": event_name,
                    "event_date": event_date,
                    "place": deck.get("place", ""),
                    "player": deck.get("player", ""),
                    "mainboard": {},
                    "sideboard": {},
                    "status": "no_cards",
                    "best_match": None,
                    "best_score": 0,
                    "best_ratio": 0.0,
                })
                continue

            best_arch, best_score, best_ratio, all_scores = classify(main, refs)

            if not refs:
                # No refs yet — everything goes to review
                new_no_refs += 1
                to_review.append({
                    "uid": uid,
                    "event_name": event_name,
                    "event_date": event_date,
                    "place": deck.get("place", ""),
                    "player": deck.get("player", ""),
                    "mainboard": main,
                    "sideboard": side,
                    "status": "no_refs",
                    "best_match": None,
                    "best_score": 0,
                    "best_ratio": 0.0,
                })
                continue

            matched_slots = best_score
            status = (
                "confident" if matched_slots >= CONFIDENT_SLOTS else
                "uncertain" if matched_slots >= UNCERTAIN_SLOTS else
                "unmatched"
            )

            if status == "confident":
                ref_mb = refs[best_arch].get("mainboard", {})
                new_cards, cuts = divergent_cards(main, ref_mb)
                classifications[uid] = {
                    "archetype": best_arch,
                    "matched_slots": matched_slots,
                    "confidence": round(best_ratio * 100, 1),
                    "status": status,
                    "event": event_name,
                    "date": event_date,
                    "place": deck.get("place", ""),
                    "player": deck.get("player", ""),
                    "new_cards": new_cards,
                    "cuts": cuts,
                }
                new_confident += 1

                # Flag to user if there are notable divergences
                if new_cards or cuts:
                    diverge_note = []
                    if new_cards:
                        diverge_note.append(
                            "NEW in list: " + ", ".join(
                                f"{c['count']}x {c['card']}" for c in new_cards[:3]
                            )
                        )
                    if cuts:
                        diverge_note.append(
                            "CUT from ref: " + ", ".join(c['card'] for c in cuts[:3])
                        )
                    print(f"  [{best_arch}] {deck.get('player','')} ({deck.get('place','')}): "
                          + " | ".join(diverge_note))

            else:
                # uncertain or unmatched -> review queue
                new_uncertain += 1
                to_review.append({
                    "uid": uid,
                    "event_name": event_name,
                    "event_date": event_date,
                    "place": deck.get("place", ""),
                    "player": deck.get("player", ""),
                    "mainboard": main,
                    "sideboard": side,
                    "status": status,
                    "best_match": best_arch,
                    "best_score": matched_slots,
                    "best_ratio": best_ratio,
                })

    print(f"\nClassification summary:")
    print(f"  Auto-classified (confident) : {new_confident}")
    print(f"  Sent to review queue        : {len(to_review)}")
    if new_no_refs:
        print(f"    - no refs yet             : {new_no_refs}")
    if new_uncertain:
        print(f"    - uncertain / unmatched   : {new_uncertain}")
    if no_cards:
        print(f"    - no card data            : {no_cards}")

    return to_review


# ─── apply-reviews ────────────────────────────────────────────────────────────

def apply_reviews(review_path, refs, classifications):
    reviewed = parse_review_file(review_path)
    if not reviewed:
        print("No filled-in annotations found in review file.")
        return refs, classifications

    # Group by archetype for ref building
    arch_decks = {}
    for r in reviewed:
        arch = r["archetype"]
        if arch == "SKIP":
            # Mark in classifications as skipped, don't build refs
            classifications[r["uid"]] = {"archetype": "SKIP", "status": "skipped"}
            continue
        is_new = arch.upper().startswith("NEW:")
        arch_clean = re.sub(r'^NEW:\s*', '', arch, flags=re.IGNORECASE).strip()
        arch_decks.setdefault(arch_clean, []).append(r)

    updated_archs = []
    for arch_clean, decks in arch_decks.items():
        # Build or update the reference from these decks
        new_ref = build_ref_from_decks(decks)
        if not new_ref:
            print(f"  Skipping {arch_clean}: couldn't build reference (empty maindeck?)")
            continue

        # Merge with existing ref if present (existing data + new data, take modal)
        if arch_clean in refs:
            # Combine: existing ref cards + new deck cards, recompute modal
            combined = list(decks)
            combined.append({"mainboard": refs[arch_clean].get("mainboard", {})})
            new_ref = build_ref_from_decks(combined)

        refs[arch_clean] = refs.get(arch_clean, {})
        refs[arch_clean]["mainboard"] = new_ref
        refs[arch_clean].setdefault("notes", "")

        # Update classifications for these reviewed decks
        for r in decks:
            ref_mb = new_ref
            main = r.get("mainboard", {})
            score = match_score(main, ref_mb)
            ratio = score / (ref_total(ref_mb))
            new_cards, cuts = divergent_cards(main, ref_mb)
            classifications[r["uid"]] = {
                "archetype": arch_clean,
                "matched_slots": score,
                "confidence": round(ratio * 100, 1),
                "status": "manual",
                "event": "",
                "place": "",
                "player": "",
                "new_cards": new_cards,
                "cuts": cuts,
            }

        updated_archs.append(arch_clean)
        print(f"  {arch_clean}: ref built from {len(decks)} decks "
              f"({len(new_ref)} core cards)")

    return refs, classifications


# ─── build-refs (from all confirmed classifications) ──────────────────────────

def rebuild_all_refs(events, classifications):
    """Rebuild every archetype reference from all confirmed + manual classifications."""
    arch_decks = {}
    for event in events:
        for deck in event.get("decks", []):
            uid = deck_uid(event, deck)
            cl = classifications.get(uid)
            if not cl:
                continue
            arch = cl.get("archetype")
            if not arch or arch in ("Unknown", "SKIP", None):
                continue
            if cl.get("status") in ("confident", "manual"):
                arch_decks.setdefault(arch, []).append(deck)

    refs = {}
    for arch, decks in sorted(arch_decks.items()):
        new_ref = build_ref_from_decks(decks)
        if new_ref:
            refs[arch] = {"mainboard": new_ref, "notes": f"Built from {len(decks)} decklists"}
            print(f"  {arch}: {len(new_ref)} core cards from {len(decks)} lists")

    return refs


# ─── debug-cards ──────────────────────────────────────────────────────────────

def debug_cards(events):
    found = 0
    for event in events:
        for deck in event.get("decks", [])[:3]:
            main = deck.get("mainboard", {})
            side = deck.get("sideboard", {})
            if main or side:
                print(f"\nDeck: {deck.get('player','')} | {event.get('name','')} | "
                      f"place {deck.get('place','')}")
                print(f"  Mainboard ({sum(main.values())} cards, "
                      f"{len(main)} unique):")
                for card, count in sorted(main.items(), key=lambda x: -x[1])[:10]:
                    print(f"    {count}  {card}")
                if len(main) > 10:
                    print(f"    ... and {len(main)-10} more")
                if side:
                    print(f"  Sideboard ({sum(side.values())} cards): "
                          + ", ".join(f"{v}x {k}" for k, v in list(side.items())[:5]))
                found += 1
            else:
                print(f"\nDeck: {deck.get('player','')} -- NO CARD DATA "
                      f"(run fetch_mtgo.py --debug-cards to inspect DOM)")
        if found >= 3:
            break
    if not found:
        print("No decks with card data found. Run fetch_mtgo.py again with the "
              "updated parseCards extension, then retry.")


# ─── main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rerun",    action="store_true",
                   help="Reclassify all decks, even already-classified ones")
    p.add_argument("--apply-reviews", metavar="PATH",
                   help="Read annotated review queue file, update refs + classifications")
    p.add_argument("--build-refs", action="store_true",
                   help="Rebuild archetype references from all confirmed classifications")
    p.add_argument("--score-challenges", action="store_true",
                   help="Print archetype point totals from challenge data")
    p.add_argument("--analyze-5-0", nargs="?", const="ALL", metavar="ARCHETYPE",
                   help="Mode/aggregate/outlier analysis from 5-0 dumps (omit name for all)")
    p.add_argument("--debug-cards", action="store_true",
                   help="Print card counts from the first few decks (selector check)")
    return p.parse_args()


def main():
    args = parse_args()
    events = load_events(CHALL_JSON, DUMP_JSON)
    refs = load_refs()
    classifications = load_classifications()

    if args.debug_cards:
        debug_cards(events)
        return

    if args.score_challenges:
        score_challenges(events, classifications)
        return

    if args.analyze_5_0:
        arch = None if args.analyze_5_0 == "ALL" else args.analyze_5_0
        analyze_5_0(events, classifications, archetype_filter=arch)
        return

    if args.apply_reviews:
        path = args.apply_reviews
        if not os.path.exists(path):
            print(f"ERROR: review file not found: {path}")
            sys.exit(1)
        refs, classifications = apply_reviews(path, refs, classifications)
        save_refs(refs)
        save_classifications(classifications)
        print("Done. Run classify again to process any remaining unclassified decks.")
        return

    if args.build_refs:
        refs = rebuild_all_refs(events, classifications)
        save_refs(refs)
        return

    # Default: classify
    if not events:
        print("No events found. Run fetch_mtgo.py first.")
        sys.exit(1)

    if not refs:
        print("No archetype references found. All decks will go to the review queue.")
        print("After reviewing, run: python classify_decks.py --apply-reviews <path>")

    to_review = run_classify(events, refs, classifications, rerun=args.rerun)

    if to_review:
        run_date_str = date.today().isoformat()
        write_review_queue(to_review, run_date_str)

    save_classifications(classifications)
    print(f"\nClassifications saved: {CLASS_FILE}")


if __name__ == "__main__":
    main()
