#!/usr/bin/env python3
"""
build_refs_from_melee.py - Build archetype_refs.json from melee.gg deck URLs.

Reads archetype name + deck URL pairs from melee pairings CSVs, scrapes the
card lists, detects mislabeled decks (where the melee label disagrees with
what the cards actually match), and writes archetype_refs.json.

Self-healing: new archetypes appear automatically as soon as melee players
start labeling their decks. Mislabeled decks are flagged for human review
rather than silently poisoning the reference lists.

Outputs:
  archetype_refs.json                       -- archetype reference card lists
  melee_deck_cache.json                     -- scraped card data (avoids re-scraping)
  (project)/[C] Mislabeled Decks YYYY-MM-DD.md  -- suspect labels for review

Usage:
  python build_refs_from_melee.py                 # scrape new URLs, rebuild refs
  python build_refs_from_melee.py --dry-run       # show what would be scraped
  python build_refs_from_melee.py --rebuild-only  # rebuild from cache, no scraping
  python build_refs_from_melee.py --max-per-arch 5  # cap N decks scraped per archetype
  python build_refs_from_melee.py --min-decks 5   # require N cached decks to build a ref
"""

import argparse
import csv
import glob
import json
import os
import sys
from collections import Counter
from datetime import date

# NOTE: Playwright is imported lazily inside the scraping function (see
# fetch_decklists) so the --rebuild-only path and --help work without it.

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
# Data is read from MTG_DATA_DIR (defaults to the script folder so the flat
# single-format workflow is unchanged). setup.py sets it per format.
DATA_DIR     = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)
# Mislabeled-decks report written next to the data by default.
# Set MTG_OUTPUT_DIR to write it elsewhere (e.g. your vault project folder).
_PROJECT_DIR = os.environ.get("MTG_OUTPUT_DIR", DATA_DIR)

REFS_FILE    = os.path.join(DATA_DIR, "archetype_refs.json")
CACHE_FILE   = os.path.join(DATA_DIR, "melee_deck_cache.json")

# Default thresholds — match classify_decks.py
CONFIDENT_SLOTS  = 45
UNCERTAIN_SLOTS  = 30
MIN_DECKS_FOR_REF = 3   # fewer than this and we can't reliably build a ref


# ─── I/O helpers ──────────────────────────────────────────────────────────────

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def load_refs():
    if not os.path.exists(REFS_FILE):
        return {}
    with open(REFS_FILE, encoding="utf-8") as f:
        return json.load(f).get("archetypes", {})


def save_refs(archetypes):
    existing = {}
    if os.path.exists(REFS_FILE):
        with open(REFS_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    existing["archetypes"] = archetypes
    existing.setdefault("_note",
        "Reference mainboard lists for archetype classification. "
        "Each entry: {mainboard: {card: count}, notes: str}. "
        "Auto-populated by build_refs_from_melee.py from melee.gg deck URLs.")
    existing.setdefault("_schema_version", 1)
    existing.setdefault("_thresholds", {
        "confident_slots": CONFIDENT_SLOTS,
        "uncertain_slots": UNCERTAIN_SLOTS,
        "note": "Match score = sum of min(deck_count, ref_count) per card. "
                "Confident >= 45/60 slots, uncertain 30-44, review queue < 30.",
    })
    with open(REFS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print(f"archetype_refs.json updated: {len(archetypes)} archetypes")


# ─── URL collection from pairings CSVs ────────────────────────────────────────

def collect_deck_urls():
    """
    Read all melee_*_pairings.csv files. Return:
      {deck_url: {archetype, player, tournament}}
    Only the first occurrence of each URL is kept (duplicates appear across rounds).
    """
    pattern = os.path.join(DATA_DIR, "melee_*_pairings.csv")
    csv_files = sorted(glob.glob(pattern))

    url_map = {}   # url -> {archetype, player, tournament}
    for path in csv_files:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for side in ("1", "2"):
                    url  = row.get(f"player{side}_deck_url", "").strip()
                    arch = row.get(f"player{side}_deck",     "").strip()
                    player = row.get(f"player{side}", "").strip()
                    tourn  = row.get("tournament_name", "").strip()
                    if url and arch and url not in url_map:
                        url_map[url] = {
                            "archetype":   arch,
                            "player":      player,
                            "tournament":  tourn,
                        }

    print(f"Collected {len(url_map)} unique deck URLs from {len(csv_files)} pairings file(s)")
    return url_map


def prioritize_urls(url_map, cache, max_per_arch):
    """
    From url_map, pick URLs not yet in cache, capped at max_per_arch per archetype.
    Archetypes are ordered by their total unique-deck count (most-played first) so
    we bootstrap the common archetypes before the long tail.
    """
    arch_url_count = Counter(info["archetype"] for info in url_map.values())

    # Group uncached URLs by archetype (most-played arch first)
    arch_uncached = {}
    for url, info in url_map.items():
        if url in cache:
            continue
        arch = info["archetype"]
        arch_uncached.setdefault(arch, []).append((url, info))

    to_scrape = {}
    for arch in sorted(arch_uncached, key=lambda a: -arch_url_count[a]):
        slots = arch_uncached[arch]
        if max_per_arch is not None:
            # How many of this archetype are already in cache?
            cached_this_arch = sum(
                1 for d in cache.values()
                if d.get("archetype") == arch and not d.get("failed")
            )
            remaining = max(0, max_per_arch - cached_this_arch)
            slots = slots[:remaining]
        for url, info in slots:
            to_scrape[url] = info

    return to_scrape


# ─── Playwright scraper ────────────────────────────────────────────────────────

# Verified against melee.gg DOM 2026-06-13:
#   .decklist-category        -- one per card type section (Creature, Sorcery, ..., Sideboard)
#   .decklist-category-title  -- section heading text, e.g. "Sideboard (15)"
#   .decklist-record          -- one per card line
#   .decklist-record-quantity -- card count (span, innerText = "4")
#   .decklist-record-name     -- card name (anchor)
_PARSE_JS = r"""() => {
    const main = {}, side = {};
    let inSide = false;
    for (const cat of document.querySelectorAll('.decklist-category')) {
        const title = (cat.querySelector('.decklist-category-title')?.innerText || '').toLowerCase().trim();
        if (title.startsWith('sideboard')) inSide = true;
        for (const rec of cat.querySelectorAll('.decklist-record')) {
            const qty  = parseInt(rec.querySelector('.decklist-record-quantity')?.innerText || '0');
            const name = (rec.querySelector('.decklist-record-name')?.innerText || '').trim();
            if (!qty || !name || name.length > 80) continue;
            if (inSide) { side[name] = (side[name] || 0) + qty; }
            else        { main[name] = (main[name] || 0) + qty; }
        }
    }
    return { mainboard: main, sideboard: side };
}"""


def scrape_decklist(page, url):
    """
    Load a melee.gg decklist page and extract card counts.
    Returns {mainboard: dict, sideboard: dict} or None on failure.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PWTimeout:
        print(f"      Timeout loading page")
        return None

    try:
        page.wait_for_selector(".decklist-record", timeout=15000, state="attached")
    except PWTimeout:
        # Page loaded but no card records — deck may be private or deleted
        print(f"      No .decklist-record found — deck may be private/deleted")
        return None

    cards = page.evaluate(_PARSE_JS)
    main_total = sum(cards["mainboard"].values()) if cards["mainboard"] else 0
    if main_total < 50:
        print(f"      Only {main_total} mainboard cards — skipping (too short to be legal)")
        return None

    return cards


def scrape_new_urls(to_scrape, cache):
    """
    Scrape the given {url: info} dict using Playwright.
    Updates cache in place. Saves a checkpoint every 20 decks.
    Returns count of successfully scraped decks.
    """
    if not to_scrape:
        print("Nothing new to scrape.")
        return 0

    # Lazy import so --rebuild-only and --help work without Playwright installed.
    global sync_playwright, PWTimeout
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        sys.exit("Playwright is required to scrape melee.gg. Install it with:\n"
                 "    pip install playwright\n"
                 "    playwright install chromium\n"
                 "Or run setup.py, which offers to install it for you.")

    print(f"\nScraping {len(to_scrape)} new deck URLs from melee.gg...")
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    succeeded = failed = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        for i, (url, info) in enumerate(to_scrape.items(), 1):
            arch = info["archetype"]
            print(f"  [{i}/{len(to_scrape)}] {arch:35s} | {info['player'][:20]}")
            cards = scrape_decklist(page, url)

            cache[url] = {
                "archetype":   arch,
                "player":      info["player"],
                "tournament":  info["tournament"],
                "mainboard":   cards["mainboard"] if cards else {},
                "sideboard":   cards["sideboard"] if cards else {},
                "scraped_at":  date.today().isoformat(),
                "failed":      cards is None,
            }

            if cards:
                succeeded += 1
            else:
                failed += 1

            # Checkpoint so a crash doesn't lose everything
            if i % 20 == 0:
                save_cache(cache)
                print(f"  [checkpoint {i}] Cache saved")

        ctx.close()
        browser.close()

    print(f"Scraping complete: {succeeded} succeeded, {failed} failed/skipped")
    return succeeded


# ─── Ref building ─────────────────────────────────────────────────────────────

def build_ref_from_decks(decks):
    """
    Modal copy count per card, only for cards appearing in >50% of decks.
    Same algorithm as classify_decks.py — keep them in sync.
    """
    n = len(decks)
    if n == 0:
        return {}

    card_counts = {}
    for deck in decks:
        for card, count in deck.get("mainboard", {}).items():
            # Normalize DFC names ("Front // Back" -> "Front") so refs
            # built from melee data match MTGO exports and vice versa.
            norm = card.split(" // ")[0].strip()
            card_counts.setdefault(norm, []).append(count)

    ref = {}
    for card, counts in card_counts.items():
        if len(counts) / n > 0.5:
            ref[card] = Counter(counts).most_common(1)[0][0]

    return ref


def build_refs_from_cache(cache, min_decks):
    """
    Group cached (non-failed) decks by archetype, build a ref for each.
    Archetypes with fewer than min_decks usable decks are skipped.
    """
    arch_decks = {}
    for url, data in cache.items():
        if data.get("failed") or not data.get("mainboard"):
            continue
        arch_decks.setdefault(data["archetype"], []).append(data)

    refs = {}
    skipped = []
    for arch, decks in sorted(arch_decks.items()):
        if len(decks) < min_decks:
            skipped.append((arch, len(decks)))
            continue
        ref = build_ref_from_decks(decks)
        if ref:
            refs[arch] = {
                "mainboard": ref,
                "notes": f"Built from {len(decks)} melee.gg decklist(s)",
            }
            print(f"  {arch:40s} {len(ref):3d} core cards from {len(decks):4d} lists")

    if skipped:
        print(f"\nSkipped {len(skipped)} archetype(s) with < {min_decks} cached decks:")
        for arch, n in sorted(skipped, key=lambda x: -x[1])[:10]:
            print(f"  {arch}: {n}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped)-10} more")

    return refs


# ─── Mislabel detection ────────────────────────────────────────────────────────

def match_score(deck_main, ref_main):
    return sum(min(deck_main.get(c, 0), n) for c, n in ref_main.items())


def ref_total(ref_main):
    return sum(ref_main.values()) or 60


def best_match(deck_main, refs):
    """Return (best_arch, best_score, best_ratio) across all refs."""
    if not refs or not deck_main:
        return None, 0, 0.0
    scores = {}
    for arch, ref in refs.items():
        ref_mb = ref.get("mainboard", {})
        if not ref_mb:
            continue
        s = match_score(deck_main, ref_mb)
        scores[arch] = (s, s / ref_total(ref_mb))
    if not scores:
        return None, 0, 0.0
    top = max(scores, key=lambda k: scores[k][1])
    return top, scores[top][0], scores[top][1]


def detect_mislabels(cache, refs):
    """
    Compare each cached deck's melee label against card-based classification.

    Flags two tiers:
      high  — card-based is confident (>=45 slots) for a DIFFERENT archetype
      low   — labeled arch scores poorly (<30 slots) AND another fits (30-44)

    Returns sorted list of mislabel dicts (high confidence first).
    """
    mislabels = []
    no_ref_archs = set()

    for url, data in cache.items():
        if data.get("failed") or not data.get("mainboard"):
            continue

        labeled = data["archetype"]
        main    = data["mainboard"]

        if labeled not in refs:
            no_ref_archs.add(labeled)
            continue

        labeled_ref   = refs[labeled].get("mainboard", {})
        labeled_score = match_score(main, labeled_ref)
        labeled_ratio = labeled_score / ref_total(labeled_ref)

        card_arch, card_score, card_ratio = best_match(main, refs)

        mislabel = None
        if (card_arch and card_arch != labeled
                and card_score >= CONFIDENT_SLOTS):
            # High: confident match to wrong archetype
            mislabel = "high"
        elif (card_arch and card_arch != labeled
              and labeled_score < UNCERTAIN_SLOTS
              and card_score >= UNCERTAIN_SLOTS):
            # Low: labeled arch doesn't fit, another does
            mislabel = "low"

        if mislabel:
            mislabels.append({
                "confidence":    mislabel,
                "url":           url,
                "player":        data.get("player", ""),
                "tournament":    data.get("tournament", ""),
                "labeled_arch":  labeled,
                "labeled_score": labeled_score,
                "labeled_ratio": labeled_ratio,
                "card_arch":     card_arch,
                "card_score":    card_score,
                "card_ratio":    card_ratio,
                "mainboard":     main,
            })

    # High confidence first, then by score gap descending
    mislabels.sort(key=lambda m: (0 if m["confidence"] == "high" else 1,
                                  -(m["card_score"] - m["labeled_score"])))

    if no_ref_archs:
        print(f"  {len(no_ref_archs)} archetype(s) in cache have no ref yet "
              f"(mislabel check skipped): "
              + ", ".join(sorted(no_ref_archs)[:5])
              + ("..." if len(no_ref_archs) > 5 else ""))

    return mislabels


def write_mislabel_report(mislabels, run_date_str):
    if not mislabels:
        print("No mislabeled decks detected.")
        return None

    path = os.path.join(
        _PROJECT_DIR,
        f"[C] Mislabeled Decks {run_date_str}.md",
    )

    high = [m for m in mislabels if m["confidence"] == "high"]
    low  = [m for m in mislabels if m["confidence"] == "low"]

    lines = [
        "---",
        "author: claude",
        "type: note",
        "project: MTG Tournament Analysis Skill",
        f"date: {run_date_str}",
        "tags: [mtg, melee, mislabel-review]",
        "---",
        "",
        f"# Melee mislabeled deck review — {run_date_str}",
        "",
        "Decks where the player-assigned melee archetype label disagrees with",
        "the card-based classification against archetype_refs.json.",
        "",
        "**High confidence** — card match is confident (>=45/60 slots) to a *different* archetype.",
        "**Low confidence** — labeled archetype scores poorly (<30 slots); another fits better (30–44).",
        "",
        f"High confidence: {len(high)}  |  Low confidence: {len(low)}",
        "",
        "To correct a ref: delete the bad deck URL from melee_deck_cache.json,",
        "change its archetype field, then rerun with --rebuild-only.",
        "",
        "---",
        "",
    ]

    for section_label, section in [("High confidence mislabels", high),
                                    ("Low confidence flags", low)]:
        if not section:
            continue
        lines += [f"## {section_label}", ""]
        for m in section:
            top5 = ", ".join(
                f"{v}x {k}"
                for k, v in sorted(m["mainboard"].items(), key=lambda x: -x[1])[:5]
            )
            lines += [
                f"### {m['player']} — {m['tournament']}",
                f"URL: {m['url']}",
                f"Melee label : **{m['labeled_arch']}**"
                f"  ({m['labeled_score']}/60 slots, {m['labeled_ratio']*100:.0f}%)",
                f"Card match  : **{m['card_arch']}**"
                f"  ({m['card_score']}/60 slots, {m['card_ratio']*100:.0f}%)",
                "",
                f"Top mainboard: {top5}",
                "",
                "---",
                "",
            ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Mislabel report: {os.path.basename(path)}")
    print(f"  High confidence: {len(high)},  Low confidence: {len(low)}")
    return path


# ─── main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--dry-run",      action="store_true",
                   help="Show what would be scraped; don't fetch anything")
    p.add_argument("--rebuild-only", action="store_true",
                   help="Rebuild refs from cache without any new scraping")
    p.add_argument("--max-per-arch", type=int, default=10, metavar="N",
                   help="Max new deck URLs to scrape per archetype per run (default 10)")
    p.add_argument("--min-decks",    type=int, default=MIN_DECKS_FOR_REF, metavar="N",
                   help=f"Min cached decks needed to build a ref (default {MIN_DECKS_FOR_REF})")
    p.add_argument("--no-mislabel",  action="store_true",
                   help="Skip mislabel detection (faster, useful after --rebuild-only)")
    return p.parse_args()


def main():
    args = parse_args()
    run_date_str = date.today().isoformat()

    # ── 1. Collect URLs from pairings CSVs ────────────────────────────────────
    url_map = collect_deck_urls()

    arch_url_counts = Counter(info["archetype"] for info in url_map.values())
    print(f"\nTop archetypes by unique deck count:")
    for arch, n in arch_url_counts.most_common(15):
        print(f"  {n:4d}  {arch}")

    # ── 2. Load cache ─────────────────────────────────────────────────────────
    cache = load_cache()
    cached_ok  = sum(1 for d in cache.values() if not d.get("failed"))
    cached_err = sum(1 for d in cache.values() if d.get("failed"))
    print(f"\nCache: {cached_ok} scraped OK, {cached_err} failed, "
          f"{len(url_map) - len(cache)} URLs not yet seen")

    # ── 3. Dry run ────────────────────────────────────────────────────────────
    if args.dry_run:
        to_scrape = prioritize_urls(url_map, cache, args.max_per_arch)
        print(f"\nDry run — would scrape {len(to_scrape)} URLs "
              f"(max {args.max_per_arch}/archetype):")
        prev_arch = None
        for url, info in list(to_scrape.items())[:30]:
            arch = info["archetype"]
            if arch != prev_arch:
                print(f"\n  [{arch}]")
                prev_arch = arch
            print(f"    {info['player']:25s}  {url[-36:]}")
        if len(to_scrape) > 30:
            print(f"\n  ... and {len(to_scrape) - 30} more")
        return

    # ── 4. Scrape new URLs ────────────────────────────────────────────────────
    if not args.rebuild_only:
        to_scrape = prioritize_urls(url_map, cache, args.max_per_arch)
        if to_scrape:
            scrape_new_urls(to_scrape, cache)
            save_cache(cache)
            print(f"Cache saved: {len(cache)} total entries")
        else:
            print("All URLs already cached — skipping scrape step")

    # ── 5. Build refs ─────────────────────────────────────────────────────────
    print(f"\nBuilding archetype refs (min {args.min_decks} decks required)...")
    refs = build_refs_from_cache(cache, args.min_decks)

    if not refs:
        print("No refs built — run without --rebuild-only or check cache.")
        return

    # ── 6. Mislabel detection ─────────────────────────────────────────────────
    if not args.no_mislabel and refs:
        print(f"\nChecking for mislabeled decks across {cached_ok} cached decks...")
        mislabels = detect_mislabels(cache, refs)
        print(f"  {len(mislabels)} potential mislabel(s) found")
        write_mislabel_report(mislabels, run_date_str)

    # ── 7. Write refs ─────────────────────────────────────────────────────────
    save_refs(refs)


if __name__ == "__main__":
    main()
