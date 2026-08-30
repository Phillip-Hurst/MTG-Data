#!/usr/bin/env python3
"""
build_mtgtop8_baseline.py — seed a format's archetype baseline from mtgtop8.

Why this exists
---------------
On a fresh install the local pipeline has no archetype reference data, so
classify_decks.py has nothing to match a scraped MTGO list against and the
skill has no meta-share starting point. melee and MTGO can't be reached
without the browser scrapers, but mtgtop8 serves plain HTML that any HTTP
client can read. This script fetches the current metagame for a format from
mtgtop8 and writes:

  archetype_refs.json                          (in MTG_DATA_DIR)
      modal mainboard per archetype, the dictionary classify_decks.py matches
      MTGO lists against.

  baselines/meta_baseline_mtgtop8_<format>.json
      the meta-share snapshot: which archetypes, what share, sample size,
      the date it was pulled. The cross-reference point for "what's winning"
      before the user has scraped anything themselves.

It's meant to run once per format at setup time (setup.py calls it), and can
be re-run any time to refresh the baseline from the current mtgtop8 metagame.

Design notes
------------
- Standard library only. urllib does the fetching; mtgtop8 is server-rendered,
  so no browser is needed (unlike melee). Keeps the one-dependency story.
- The modal-mainboard aggregation is reused from classify_decks.build_ref_from_decks
  so card-name normalization stays identical across every reference builder.
  Do not reimplement it here.
- mtgtop8 groups several builds under one umbrella archetype ("Izzet Control"
  holds Izzet Lesson, Izzet Spellementals, ...). The deck-level label is the
  useful granularity and matches the vault's archetype names, so refs are keyed
  by the deck label, not the umbrella. The umbrella + share goes in the snapshot.
- Every fetch is wrapped and rate-limited. A failure on one archetype or one
  decklist degrades the result, it doesn't crash setup. With zero decklists
  parsed you still get the meta-share snapshot.

Usage
-----
  python build_mtgtop8_baseline.py --format Standard
  python build_mtgtop8_baseline.py --format Modern --max-archetypes 10 --decks-per-archetype 4
  python build_mtgtop8_baseline.py --format Standard --dry-run --verbose
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date

# Windows consoles default to cp1252 and choke on accented card/player names.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)

# Reuse the one true modal-aggregation + DFC normalization. If classify_decks
# can't be imported for some reason, fall back to a local copy that MUST stay
# byte-for-byte equivalent so reference keys never diverge between builders.
try:
    from classify_decks import build_ref_from_decks
except Exception:  # pragma: no cover - import shim
    from collections import Counter

    def build_ref_from_decks(decks_for_archetype):
        n = len(decks_for_archetype)
        if n == 0:
            return {}
        card_counts = {}
        for deck in decks_for_archetype:
            for card, count in deck.get("mainboard", {}).items():
                norm = card.split(" // ")[0].strip()
                card_counts.setdefault(norm, []).append(count)
        ref = {}
        for card, counts in card_counts.items():
            if len(counts) / n > 0.5:
                ref[card] = Counter(counts).most_common(1)[0][0]
        return ref


# MTG format name -> mtgtop8 format code. Matches setup.py's KNOWN_FORMATS.
FORMAT_CODES = {
    "Standard": "ST",
    "Modern": "MO",
    "Pioneer": "PI",
    "Legacy": "LE",
    "Pauper": "PAU",
    "Vintage": "VI",
}

BASE = "https://www.mtgtop8.com"
USER_AGENT = (
    "mtg-tournament-analysis baseline builder "
    "(personal, non-commercial; https://github.com/Phillip-Hurst/MTG-Data)"
)


def fetch(url, timeout=20):
    """GET a URL, return decoded text or None. mtgtop8 serves ISO-8859-1."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"  fetch failed: {url}\n    {e}")
        return None
    for enc in ("utf-8", "iso-8859-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_metagame(html):
    """From a format page, return (sample_size, [archetype, ...]).

    Each archetype: {name, a_id, meta, f, share_pct, href}. Share is paired to
    each archetype link positionally: the percentage that follows the link in
    document order is that archetype's share. The group-header percentages
    (AGGRO 51%, CONTROL 42%) sit *before* their first archetype link, so they're
    never consumed as an archetype share.
    """
    sample = None
    m = re.search(r"(\d+)\s+decks", html)
    if m:
        sample = int(m.group(1))

    # Tokenize archetype links and percentages in document order.
    # mtgtop8 uses unquoted href attributes (href=archetype?a=...>), so
    # no closing " before >.
    link_re = re.compile(
        r'archetype\?a=(\d+)&(?:amp;)?meta=(\d+)&(?:amp;)?f=(\w+)[^>]*>([^<]+)</a>',
        re.I,
    )
    # Percentage pattern requires at least one space before % so CSS values
    # like width:48% are not mistaken for archetype share values (which mtgtop8
    # renders as "20 %" with a space).
    token_re = re.compile(
        r'archetype\?a=(\d+)&(?:amp;)?meta=(\d+)&(?:amp;)?f=(\w+)[^>]*>([^<]+)</a>'
        r'|(\d+(?:\.\d+)?)\s+%'
    )

    archetypes = []
    pending = None  # the last archetype link still waiting for its percentage
    seen_ids = set()
    for t in token_re.finditer(html):
        if t.group(1):  # an archetype link
            a_id, meta, f, name = t.group(1), t.group(2), t.group(3), t.group(4).strip()
            pending = {
                "name": name,
                "a_id": a_id,
                "meta": meta,
                "f": f,
                "share_pct": None,
                "href": f"{BASE}/archetype?a={a_id}&meta={meta}&f={f}",
            }
        elif t.group(5) is not None and pending is not None:
            pending["share_pct"] = float(t.group(5))
            # The same archetype can be listed once; dedupe on (a_id) keeping first.
            if pending["a_id"] not in seen_ids:
                seen_ids.add(pending["a_id"])
                archetypes.append(pending)
            pending = None

    return sample, archetypes


def parse_archetype_decks(html):
    """From an archetype page, return ordered unique [{d_id, label}].

    Rows look like: event?e=NNN&d=MMM&f=ST">Izzet Lesson</a>. The page is sorted
    newest-first, so order is preserved for "take the most recent K".
    """
    row_re = re.compile(
        r'event\?e=\d+&(?:amp;)?d=(\d+)&(?:amp;)?f=\w+[^>]*>\s*([^<]+?)\s*</a>',
        re.I,
    )
    decks, seen = [], set()
    for m in row_re.finditer(html):
        d_id, label = m.group(1), m.group(2).strip()
        if d_id in seen:
            continue
        # Skip the metagame-breakdown archetype links (those are archetype?a=,
        # not event?e=&d=), already excluded by the pattern. Guard empty labels.
        if not label:
            continue
        seen.add(d_id)
        decks.append({"d_id": d_id, "label": label})
    return decks


def parse_decklist(text):
    """Parse the mtgo plaintext export into {mainboard: {card: count}}.

    Lines are 'COUNT Cardname' until a 'Sideboard' line. DFC names arrive as
    'Front/Back'; front-face them so keys match MTGO-sourced refs (which use
    'Front // Back', front-faced the same way downstream)."""
    mainboard = {}
    in_side = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower() == "sideboard":
            in_side = True
            continue
        if in_side:
            continue
        m = re.match(r"(\d+)\s+(.*)", line)
        if not m:
            continue
        count = int(m.group(1))
        name = m.group(2).strip()
        # Normalize single-slash DFC to the front face and collapse to the
        # ' // ' form build_ref_from_decks expects.
        name = name.split("/")[0].strip()
        mainboard[name] = mainboard.get(name, 0) + count
    return {"mainboard": mainboard}


def build(fmt, max_archetypes, decks_per_archetype, delay, verbose, dry_run):
    code = FORMAT_CODES.get(fmt)
    if not code:
        print(f"  No mtgtop8 format code for '{fmt}'. Known: {', '.join(FORMAT_CODES)}.")
        print("  Skipping baseline for this format.")
        return False

    print(f"  Fetching {fmt} metagame from mtgtop8 ...")
    html = fetch(f"{BASE}/format?f={code}")
    if not html:
        print("  Could not reach mtgtop8. Baseline skipped (you can re-run later).")
        return False

    sample, archetypes = parse_metagame(html)
    if not archetypes:
        print("  Parsed no archetypes from the metagame page. mtgtop8's layout may "
              "have changed — please open an issue. Baseline skipped.")
        return False

    archetypes.sort(key=lambda a: a["share_pct"] or 0, reverse=True)
    chosen = archetypes[:max_archetypes]
    print(f"  Found {len(archetypes)} archetypes ({sample or '?'} decks). "
          f"Pulling lists for the top {len(chosen)}.")

    refs = {}                 # deck label -> list of {mainboard}
    label_meta = {}           # deck label -> umbrella archetype name
    for arch in chosen:
        if verbose:
            print(f"    {arch['name']:24s} {arch['share_pct']}%")
        page = fetch(arch["href"])
        time.sleep(delay)
        if not page:
            continue
        decks = parse_archetype_decks(page)[:decks_per_archetype]
        for d in decks:
            dl = fetch(f"{BASE}/mtgo?d={d['d_id']}")
            time.sleep(delay)
            if not dl:
                continue
            parsed = parse_decklist(dl)
            if not parsed["mainboard"]:
                continue
            refs.setdefault(d["label"], []).append(parsed)
            label_meta.setdefault(d["label"], arch["name"])

    # Build modal refs per deck label (reusing the shared aggregator).
    archetype_refs = {}
    for label, decks in refs.items():
        mainboard = build_ref_from_decks(decks)
        if not mainboard:
            continue
        archetype_refs[label] = {
            "mainboard": mainboard,
            "notes": f"Baseline from mtgtop8 ({label_meta.get(label, '?')} umbrella), "
                     f"{len(decks)} list(s), {date.today().isoformat()}",
        }

    snapshot = {
        "source": "mtgtop8.com",
        "fetched": date.today().isoformat(),
        "format": fmt,
        "sample_size": sample,
        "umbrella_archetypes": [
            {"name": a["name"], "share_pct": a["share_pct"]} for a in archetypes
        ],
        "labels_sampled": {
            label: {"decks": len(decks), "umbrella": label_meta.get(label)}
            for label, decks in refs.items()
        },
        "note": "Meta-share baseline pulled from mtgtop8 at setup. Re-run "
                "build_mtgtop8_baseline.py to refresh. mtgtop8 data is © Wizards "
                "of the Coast; stored locally for personal, non-commercial analysis.",
    }

    print(f"  Built refs for {len(archetype_refs)} deck labels "
          f"from {sum(len(v) for v in refs.values())} lists.")

    if dry_run:
        print("  --dry-run: nothing written.")
        if verbose:
            print(json.dumps(snapshot, indent=2, ensure_ascii=False)[:2000])
        return True

    _write_refs(archetype_refs, fmt)
    _write_snapshot(snapshot, fmt)
    return True


def _era_guard(fmt):
    """
    (pool, banned) for the current era, or (None, set()) when unavailable.

    mtgtop8's "last 2 weeks" window is not era-aware. Run this the morning
    after a B&R and half the decks it returns are built around a card that is
    no longer legal, which then becomes a reference that live decks get matched
    against. It happened to be clean on 2026-08-29 only because the ban was 19
    days earlier — luck, not a guarantee.
    """
    try:
        import build_card_pool
        import validate_events as ve
        import mtg_era as _era
        e = _era.resolve_era(fmt=fmt)
        pool, _meta = build_card_pool.load_pool(fmt, DATA_DIR)
        return pool, ve.banned_as_of(fmt, e.get("start"))
    except Exception:
        return None, set()


def _ref_belongs(ref, pool, banned):
    names = {str(c).strip().lower() for c in (ref.get("mainboard") or {})}
    if not names:
        return False, "empty mainboard"
    hits = names & banned
    if hits:
        return False, "banned: " + ", ".join(sorted(hits))
    if pool is None:
        return True, ""
    illegal = names - pool
    if len(illegal) / len(names) > 0.05:
        return False, f"{len(illegal)}/{len(names)} off-format"
    return True, ""


def _write_refs(new_refs, fmt="Standard"):
    """Merge into archetype_refs.json without clobbering existing entries.

    Anything from another era or another format is dropped before it can
    become something live decks are classified against.
    """
    pool, banned = _era_guard(fmt)
    if pool is None:
        print("  NOTE: no card pool on file, so off-format references can't be "
              "filtered. Run build_card_pool.py.")
    kept, rejected = {}, []
    for label, ref in new_refs.items():
        ok, why = _ref_belongs(ref, pool, banned)
        (kept.__setitem__(label, ref) if ok else rejected.append((label, why)))
    if rejected:
        print(f"  Rejected {len(rejected)} reference(s) that don't belong in this era:")
        for label, why in rejected[:8]:
            print(f"    {label} — {why}")
    new_refs = kept

    path = os.path.join(DATA_DIR, "archetype_refs.json")
    data = {"_note": "Reference mainboard lists for archetype classification. "
                     "Each entry: {mainboard: {card: count}, notes: str}. "
                     "Seeded by build_mtgtop8_baseline.py; refined by "
                     "classify_decks.py once you have local scrapes.",
            "_schema_version": 1,
            "_source": "mtgtop8 baseline + local scrapes",
            "archetypes": {}}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("archetypes", {})
        except (OSError, ValueError) as e:
            print(f"  Existing archetype_refs.json unreadable ({e}); starting fresh.")
            data["archetypes"] = {}
    added = 0
    for label, ref in new_refs.items():
        if label not in data["archetypes"]:
            data["archetypes"][label] = ref
            added += 1
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  archetype_refs.json: {added} new label(s), "
          f"{len(data['archetypes'])} total -> {path}")


def _write_snapshot(snapshot, fmt):
    bdir = os.path.join(DATA_DIR, "baselines")
    os.makedirs(bdir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", fmt.lower()).strip("-")
    path = os.path.join(bdir, f"meta_baseline_mtgtop8_{slug}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    print(f"  meta snapshot -> {path}")


def main():
    p = argparse.ArgumentParser(description="Seed a format's archetype baseline from mtgtop8.")
    p.add_argument("--format", default=os.environ.get("MTG_FORMAT", "Standard"),
                   help="MTG format name (Standard, Modern, ...). Default: Standard or $MTG_FORMAT.")
    p.add_argument("--max-archetypes", type=int, default=12,
                   help="How many top archetypes to pull lists for (default 12).")
    p.add_argument("--decks-per-archetype", type=int, default=4,
                   help="Lists to sample per archetype for the modal build (default 4).")
    p.add_argument("--delay", type=float, default=0.7,
                   help="Seconds between requests, to be polite to mtgtop8 (default 0.7).")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Fetch and parse, but write nothing.")
    args = p.parse_args()

    print(f"mtgtop8 baseline — {args.format}")
    ok = build(args.format, args.max_archetypes, args.decks_per_archetype,
               args.delay, args.verbose, args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
