#!/usr/bin/env python3
"""
card_signal.py — track individual cards across the whole field.

What this is for
----------------
The skill has had a qualitative card layer since 2026-05-02: SKILL.md Step 3.5,
the seven coverage angles, and the goto-list baseline ("we don't see Slickshot
Show-Off from Tony's build"). That tells you how to *write* about a card once
you've found it. This is the half that finds it.

Card tracking is not a property of uncategorized decks. A rogue one-of winning
inside a known archetype matters as much as a card in a shell nobody has named,
and for deck construction it usually matters more — it's a slot you could
actually change tomorrow. So this reads the whole field, and treats "the deck
has no name yet" as one lens among several rather than the scope.

The four lenses
---------------
  rogue        low adoption, good finishes. The deckbuilding shortlist: cards
               few people are on, that keep beating the field.
  deviation    a card in an archetype's lists that isn't in that archetype's
               goto build. The caster's framing, made countable — signal is a
               card replacing a 4-of, not a card filling a flex slot.
  trend        adoption moving across the window. A card going from 3 pilots to
               14 is a different story from one that has always been at 14.
  unnamed      shells the classifier can't name, grouped by co-occurrence. Real
               decks with real records and no label. Hand them to deck-check.

Usage
-----
    python card_signal.py                     # everything, current era
    python card_signal.py --lens rogue        # one section
    python card_signal.py --min-pilots 4 --top 25
    python card_signal.py --archetype "Mono-Green"   # deviations in one deck
    python card_signal.py --write             # save a note
    python card_signal.py --json
"""
import argparse
import collections
import json
import os
import statistics
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from mtg_paths import resolve_data_dir, resolve_output_dir  # noqa: E402
import mtg_era  # noqa: E402

DEFAULT_MIN_PILOTS = 3
# A card in more than this share of the field is a staple. Staples are not
# deckbuilding decisions; you already know about them.
STAPLE_CEILING = 0.35
# A rogue card is one below this share of the field. Deliberately generous:
# 8% of a 500-deck field is 40 decks, which is still a minority choice.
ROGUE_CEILING = 0.08
# A card in at least this share of an archetype's lists is part of its goto
# build. Everything else is a deviation worth a look.
GOTO_THRESHOLD = 0.70
# An archetype needs this many decks before a goto list means anything.
MIN_DECKS_FOR_GOTO = 8
IGNORE = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "starting town", "multiversal passage", "cavern of souls",
}


def _find_config(name):
    for d in (os.getcwd(), SCRIPT_DIR):
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
    return os.path.join(SCRIPT_DIR, name)


def load_config():
    try:
        with open(_find_config("mtg_config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def collect_decks(data_dir, since):
    """Every MTGO deck in the window, with its archetype if the classifier named one."""
    classifications = load_json(os.path.join(data_dir, "mtgo_classifications.json")) or {}
    decks = []
    for fname in ("mtgo_challenge_latest.json", "mtgo_5-0_latest.json"):
        for ev in load_json(os.path.join(data_dir, fname)) or []:
            if since and ev.get("date", "") < since:
                continue
            for d in ev.get("decks", []):
                cls = classifications.get(f"{ev.get('url')};{d.get('url')}")
                try:
                    place = int(str(d.get("place", "")).strip() or 0)
                except ValueError:
                    place = 0
                mb = d.get("mainboard") or {}
                decks.append({
                    "date": ev.get("date", ""),
                    "event": ev.get("name", ""),
                    "type": ev.get("event_type", ""),
                    "place": place,
                    "player": d.get("player", ""),
                    "cards": {str(c).strip().lower() for c in mb},
                    "counts": {str(c).strip().lower(): n for c, n in mb.items()},
                    "archetype": (cls or {}).get("archetype"),
                })
    return decks


def field_baseline(decks):
    places = [d["place"] for d in decks if d["type"] == "challenge" and d["place"] > 0]
    return statistics.mean(places) if places else None


def card_stats(card, decks, total_decks):
    holders = [d for d in decks if card in d["cards"]]
    places = [d["place"] for d in holders if d["type"] == "challenge" and d["place"] > 0]
    copies = [d["counts"].get(card, 0) for d in holders]
    return {
        "card": card,
        "decks": len(holders),
        "pilots": len({d["player"] for d in holders}),
        "events": len({d["event"] + d["date"] for d in holders}),
        "avg_place": round(statistics.mean(places), 1) if places else None,
        "top8": sum(1 for p in places if p <= 8),
        "challenge_decks": len(places),
        "best": min(places) if places else None,
        "field_share": round(100 * len(holders) / total_decks, 1) if total_decks else 0.0,
        "avg_copies": round(statistics.mean(copies), 1) if copies else 0,
        "_holders": holders,
    }


# ── lens 1: rogue cards ───────────────────────────────────────────────────────

def rogue_cards(decks, baseline, min_pilots):
    """Low adoption, good finishes. The deckbuilding shortlist."""
    total = len(decks)
    seen = collections.Counter()
    for d in decks:
        for c in d["cards"]:
            seen[c] += 1

    rows = []
    for card, n in seen.items():
        if card in IGNORE:
            continue
        if n / total > ROGUE_CEILING:
            continue
        s = card_stats(card, decks, total)
        if s["pilots"] < min_pilots or s["challenge_decks"] < 2:
            continue
        if baseline is None or s["avg_place"] is None or s["avg_place"] >= baseline:
            continue
        s["beats_field_by"] = round(baseline - s["avg_place"], 1)
        # Where is it living? Name the archetypes so it's actionable.
        homes = collections.Counter(d["archetype"] or "(unnamed)" for d in s["_holders"])
        s["homes"] = homes.most_common(3)
        rows.append(s)

    rows.sort(key=lambda r: (-r["beats_field_by"], -r["pilots"]))
    return rows


# ── lens 2: deviations from the goto list ─────────────────────────────────────

def goto_lists(decks):
    """archetype -> set of cards in GOTO_THRESHOLD of its lists."""
    by_arch = collections.defaultdict(list)
    for d in decks:
        if d["archetype"]:
            by_arch[d["archetype"]].append(d)
    goto = {}
    for arch, ds in by_arch.items():
        if len(ds) < MIN_DECKS_FOR_GOTO:
            continue
        counts = collections.Counter()
        for d in ds:
            for c in d["cards"]:
                counts[c] += 1
        goto[arch] = ({c for c, n in counts.items() if n / len(ds) >= GOTO_THRESHOLD}, ds)
    return goto


def deviations(decks, baseline, only_archetype=None):
    """
    Cards showing up in an archetype that aren't in its goto build.

    This is the caster's read made countable: a new card in a list isn't signal
    if it filled a flex slot, it's signal when several pilots independently
    reach for it and finish better than the pilots who didn't.
    """
    out = []
    for arch, (core, ds) in goto_lists(decks).items():
        if only_archetype and only_archetype.lower() not in arch.lower():
            continue
        arch_places = [d["place"] for d in ds if d["type"] == "challenge" and d["place"] > 0]
        arch_avg = statistics.mean(arch_places) if arch_places else None
        counts = collections.Counter()
        for d in ds:
            for c in d["cards"]:
                if c not in core and c not in IGNORE:
                    counts[c] += 1
        for card, n in counts.items():
            if n < 2:
                continue
            holders = [d for d in ds if card in d["cards"]]
            places = [d["place"] for d in holders if d["type"] == "challenge" and d["place"] > 0]
            if len(places) < 2:
                continue
            avg = statistics.mean(places)
            pilots = len({d["player"] for d in holders})
            if pilots < 2:
                continue
            out.append({
                "archetype": arch,
                "card": card,
                "decks": n,
                "arch_decks": len(ds),
                "pilots": pilots,
                "avg_place": round(avg, 1),
                "arch_avg": round(arch_avg, 1) if arch_avg else None,
                "delta": round(arch_avg - avg, 1) if arch_avg else None,
                "avg_copies": round(statistics.mean(
                    [d["counts"].get(card, 0) for d in holders]), 1),
            })
    out.sort(key=lambda r: (-(r["delta"] or -99), -r["pilots"]))
    return out


# ── lens 3: trend ─────────────────────────────────────────────────────────────

def trend(decks, min_pilots):
    """Adoption in the second half of the window against the first."""
    dates = sorted({d["date"] for d in decks if d["date"]})
    if len(dates) < 4:
        return [], None
    mid = dates[len(dates) // 2]
    early = [d for d in decks if d["date"] < mid]
    late = [d for d in decks if d["date"] >= mid]
    if not early or not late:
        return [], None

    def share(ds):
        c = collections.Counter()
        for d in ds:
            for card in d["cards"]:
                c[card] += 1
        return {k: v / len(ds) for k, v in c.items()}, c

    e_share, e_count = share(early)
    l_share, l_count = share(late)
    rows = []
    for card in set(e_share) | set(l_share):
        if card in IGNORE:
            continue
        pilots = len({d["player"] for d in decks if card in d["cards"]})
        if pilots < min_pilots:
            continue
        delta = (l_share.get(card, 0) - e_share.get(card, 0)) * 100
        if abs(delta) < 3:
            continue
        rows.append({
            "card": card,
            "early_pct": round(100 * e_share.get(card, 0), 1),
            "late_pct": round(100 * l_share.get(card, 0), 1),
            "delta": round(delta, 1),
            "early_n": e_count.get(card, 0),
            "late_n": l_count.get(card, 0),
        })
    rows.sort(key=lambda r: -abs(r["delta"]))
    return rows, mid


# ── lens 4: unnamed shells ────────────────────────────────────────────────────

def shell_candidates(decks, min_pilots):
    unnamed = [d for d in decks if not d["archetype"]]
    if not unnamed:
        return [], []
    total = len(decks)
    counts = collections.Counter()
    for d in unnamed:
        for c in d["cards"]:
            counts[c] += 1
    rows = []
    for card, n in counts.items():
        if card in IGNORE:
            continue
        s = card_stats(card, unnamed, len(unnamed))
        s["field_share"] = round(100 * counts[card] / total, 1)
        if s["pilots"] < min_pilots:
            continue
        if s["field_share"] / 100 >= STAPLE_CEILING:
            continue
        rows.append(s)
    rows.sort(key=lambda r: (-r["pilots"], r["avg_place"] if r["avg_place"] else 99))
    return group_into_shells(rows, unnamed), unnamed


def group_into_shells(rows, unnamed, min_decks=4, overlap=0.45):
    """Collapse cards that keep appearing together into one shell."""
    carded = {r["card"]: r for r in rows}
    deck_sets = {c: {id(d) for d in unnamed if c in d["cards"]} for c in carded}
    shells, claimed = [], set()
    for r in rows:
        card = r["card"]
        if card in claimed:
            continue
        core, base = [card], deck_sets[card]
        for other in rows:
            oc = other["card"]
            if oc == card or oc in claimed:
                continue
            union = base | deck_sets[oc]
            if union and len(base & deck_sets[oc]) / len(union) >= overlap:
                core.append(oc)
        if len(core) < 3:
            continue
        # A shell whose whole core is format-wide mana is a colour pair, not a
        # deck. Require cards that actually distinguish it.
        if len([c for c in core if carded[c]["field_share"] < 15.0]) < 2:
            continue
        core.sort(key=lambda c: carded[c]["field_share"])
        members = set.intersection(*[deck_sets[c] for c in core])
        ds = [d for d in unnamed if id(d) in members]
        if len(ds) < min_decks:
            continue
        claimed.update(core)
        places = [d["place"] for d in ds if d["type"] == "challenge" and d["place"] > 0]
        shells.append({
            "core": core,
            "decks": len(ds),
            "pilots": len({d["player"] for d in ds}),
            "top8": sum(1 for p in places if p <= 8),
            "avg_place": round(statistics.mean(places), 1) if places else None,
        })
    shells.sort(key=lambda s: -s["decks"])
    return shells


# ── render ────────────────────────────────────────────────────────────────────

def render(decks, baseline, lenses, min_pilots, top, only_archetype):
    out = []
    named = [d for d in decks if d["archetype"]]
    unnamed_n = len(decks) - len(named)
    out.append(f"Decks in window: {len(decks)}  |  unnamed: {unnamed_n} "
               f"({100 * unnamed_n / len(decks):.0f}%)")
    if baseline:
        out.append(f"Field average finish (Challenges): {baseline:.1f}")
    out.append("")

    if "rogue" in lenses:
        rows = rogue_cards(decks, baseline, min_pilots)
        out.append("## Rogue cards — few pilots, better finishes than the field")
        out.append("")
        out.append("The deckbuilding shortlist. Under "
                   f"{ROGUE_CEILING * 100:.0f}% of the field is on these, and the "
                   "pilots who are finish above average. Verify each on Scryfall "
                   "before writing it up.")
        out.append("")
        if not rows:
            out.append("  Nothing cleared the bar this window.")
        else:
            out.append(f"{'card':30s} {'pilots':>6s} {'avgPl':>6s} {'vs field':>9s} "
                       f"{'T8':>3s} {'copies':>6s} {'field%':>7s}  homes")
            out.append("-" * 96)
            for r in rows[:top]:
                homes = ", ".join(f"{a} x{n}" for a, n in r["homes"])
                thin = "*" if r["pilots"] < 4 else " "
                out.append(f"{r['card'][:30]:30s} {r['pilots']:5d}{thin} {r['avg_place']:6.1f} "
                           f"{r['beats_field_by']:>+9.1f} {r['top8']:3d} "
                           f"{r['avg_copies']:6.1f} {r['field_share']:6.1f}%  {homes[:34]}")
        out.append("")

    if "deviation" in lenses:
        rows = deviations(decks, baseline, only_archetype)
        out.append("## Deviations — cards outside an archetype's goto build")
        out.append("")
        out.append("Signal is a card replacing a 4-of, not one filling a flex slot. "
                   "'vs arch' is how much better these pilots finished than the rest "
                   "of that archetype. Rows marked * rest on fewer than 4 pilots — "
                   "a lead to check, not a conclusion.")
        out.append("")
        if not rows:
            out.append("  No archetype has enough decks for a goto list yet "
                       f"(needs {MIN_DECKS_FOR_GOTO}).")
        else:
            out.append(f"{'archetype':24s} {'card':26s} {'pilots':>6s} {'decks':>6s} "
                       f"{'avgPl':>6s} {'vs arch':>8s} {'copies':>6s}")
            out.append("-" * 92)
            for r in rows[:top]:
                delta = f"{r['delta']:+.1f}" if r["delta"] is not None else "-"
                thin = " *" if r["pilots"] < 4 else ""
                out.append(f"{r['archetype'][:24]:24s} {r['card'][:26]:26s} "
                           f"{r['pilots']:6d} {r['decks']:>3d}/{r['arch_decks']:<2d} "
                           f"{r['avg_place']:6.1f} {delta:>8s} {r['avg_copies']:6.1f}{thin}")
        out.append("")

    if "trend" in lenses:
        rows, mid = trend(decks, min_pilots)
        out.append("## Trend — adoption moving inside the window")
        out.append("")
        if not rows:
            out.append("  Not enough dated events to split the window.")
        else:
            out.append(f"Split at {mid}. Percentages are share of decks in each half.")
            out.append("A block of cards moving together is one deck moving, not eight "
                       "discoveries. The outlier in the other direction is usually the "
                       "more interesting line.")
            out.append("")
            out.append(f"{'card':34s} {'early':>7s} {'late':>7s} {'move':>7s}")
            out.append("-" * 60)
            for r in rows[:top]:
                out.append(f"{r['card'][:34]:34s} {r['early_pct']:6.1f}% "
                           f"{r['late_pct']:6.1f}% {r['delta']:>+6.1f}")
        out.append("")

    if "unnamed" in lenses:
        shells, unnamed = shell_candidates(decks, min_pilots)
        out.append("## Unnamed shells — whole decks with no archetype yet")
        out.append("")
        out.append("Each is one archetype, not a spread of brews. Hand them to deck-check.")
        out.append("")
        if not shells:
            out.append("  Nothing grouped. Either the window is thin or the unnamed "
                       "decks share nothing.")
        else:
            for s in shells[:top]:
                avg = f"{s['avg_place']:.1f}" if s["avg_place"] is not None else "-"
                beats = ""
                if s["avg_place"] is not None and baseline:
                    d = baseline - s["avg_place"]
                    beats = f", {abs(d):.1f} places {'better' if d > 0 else 'worse'} than field"
                out.append(f"  {s['decks']} decks / {s['pilots']} pilots  "
                           f"avg finish {avg}{beats}, {s['top8']} top 8s")
                out.append(f"    core: {', '.join(s['core'][:8])}")
                out.append("")
        if unnamed and len(unnamed) / len(decks) > 0.30:
            out.append("More than a third of the field is unnamed. That means the "
                       "archetype references predate the current era, not that the "
                       "format is unusually brewy. Run "
                       "`build_refs_from_melee.py --rebuild-only`.")
            out.append("")

    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description="Track individual cards across the field.")
    p.add_argument("--format", default=None, help="Format. Overrides mtg_config.json.")
    p.add_argument("--since", default=None, help="Window start YYYY-MM-DD. Default: era start.")
    p.add_argument("--lens", nargs="*", default=None,
                   choices=["rogue", "deviation", "trend", "unnamed"],
                   help="Sections to print. Default: all four.")
    p.add_argument("--archetype", default=None, help="Limit deviations to one archetype.")
    p.add_argument("--min-pilots", type=int, default=DEFAULT_MIN_PILOTS)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true", help="Save [C] Card Signal <date>.md")
    args = p.parse_args()

    config = load_config()
    fmt = (args.format or config.get("format", "Standard")).strip()
    data_dir = resolve_data_dir(fmt, SCRIPT_DIR)
    era = mtg_era.resolve_era(fmt=fmt, weeks_window=config.get("weeks_window", 8),
                              since_override=args.since)
    since = args.since or era.get("start_str")

    decks = collect_decks(data_dir, since)
    if not decks:
        print(f"No MTGO decks in {data_dir} since {since}. Run fetch_mtgo.py first.")
        return 1

    baseline = field_baseline(decks)
    lenses = args.lens or ["rogue", "deviation", "trend", "unnamed"]

    if args.json:
        print(json.dumps({
            "era": era.get("label"), "since": since, "decks": len(decks),
            "field_avg_place": baseline,
            "rogue": [{k: v for k, v in r.items() if not k.startswith("_")}
                      for r in rogue_cards(decks, baseline, args.min_pilots)],
            "deviations": deviations(decks, baseline, args.archetype),
            "trend": trend(decks, args.min_pilots)[0],
            "shells": shell_candidates(decks, args.min_pilots)[0],
        }, indent=1))
        return 0

    header = f"\n{fmt} — {era.get('label', 'current era')}, from {since}\n"
    body = render(decks, baseline, lenses, args.min_pilots, args.top, args.archetype)
    print(header)
    print(body)

    if args.write:
        out_dir = resolve_output_dir(fmt, SCRIPT_DIR)
        path = os.path.join(out_dir, f"[C] Card Signal {date.today().isoformat()}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("---\nauthor: claude\ntype: note\n"
                    "project: MTG Tournament Analysis Skill\n"
                    f"date: {date.today().isoformat()}\n"
                    "tags: [mtg, signal, cards]\n---\n\n")
            f.write(f"# Card signal — {date.today().isoformat()}\n")
            f.write(header + "\n```\n" + body + "\n```\n")
        print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
