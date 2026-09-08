#!/usr/bin/env python3
"""
build_card_pool.py — cache the legal card pool for a format from Scryfall.

Why this exists
---------------
On 2026-08-27 the scrape pulled a Modern team-trios event and a pre-ban paper
event into the Standard folder, and nothing downstream noticed. Deck *names*
can't catch that ("Dimir Midrange" exists in both formats), but the cards can:
a Modern deck is full of cards that have never been Standard-legal.

validate_events.py uses this pool to score each scraped event. Refresh it
whenever a set rotates in or out, or whenever a ban lands:

    python build_card_pool.py                  # format from mtg_config.json
    python build_card_pool.py --format Modern
    python build_card_pool.py --max-age-days 0 # force refresh

Output: card_pool_<format>.json in the format's data folder.
Names are stored lowercase, with the front face of a split/DFC also indexed,
because melee and MTGO disagree on how they print "Roaring Furnace // Steaming
Sauna".
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from mtg_paths import resolve_data_dir  # noqa: E402

SCRYFALL_SEARCH = "https://api.scryfall.com/cards/search"
USER_AGENT = "mtg-tournament-analysis/1.6 (github.com/Phillip-Hurst/MTG-Data)"
REQUEST_GAP_S = 0.25  # Scryfall asks for 50-100ms; a shared IP needs more headroom


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


def pool_path(fmt, data_dir):
    return os.path.join(data_dir, f"card_pool_{fmt.lower()}.json")


def _get_json(url, attempts=5):
    """
    One Scryfall page, with backoff on a 429 or a 5xx.

    Scryfall rate-limits by IP, so a shared address can 429 even at the
    documented gap. Without this the crawl dies partway and `build` raises,
    which on a scheduled run means the pool silently stops being refreshed and
    validate_events keeps scoring events against a stale card list. Retrying a
    throttle is the difference between slow and broken.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            retryable = e.code == 429 or 500 <= e.code < 600
            if not retryable or attempt == attempts:
                raise
            wait = float(e.headers.get("Retry-After") or 0) or delay
            print(f"    HTTP {e.code} from Scryfall, waiting {wait:.0f}s "
                  f"(attempt {attempt} of {attempts})")
            time.sleep(wait)
            delay = min(delay * 2, 30)
        except urllib.error.URLError as e:
            if attempt == attempts:
                raise
            print(f"    {e.reason}, retrying in {delay:.0f}s "
                  f"(attempt {attempt} of {attempts})")
            time.sleep(delay)
            delay = min(delay * 2, 30)


def _attributes(card):
    """
    The few fields a metagame question needs, off a card Scryfall already sent.

    Kept deliberately small. This file is read on every validation run, and a
    full Scryfall object per card would take it from 200 KB to tens of MB for
    fields nothing asks about.

    A double-faced card has its cost and type on the faces rather than the top
    level, so fall through to the front face. `cmc` stays top-level either way.
    """
    faces = card.get("card_faces") or []
    front = faces[0] if faces else card
    return {
        "cmc": card.get("cmc", front.get("cmc")),
        "colors": sorted(front.get("colors") or card.get("colors") or []),
        "color_identity": sorted(card.get("color_identity") or []),
        "type_line": card.get("type_line") or front.get("type_line") or "",
    }


def fetch_pool(fmt):
    """
    Page through Scryfall for every card legal in this format.

    Returns (names, attrs). `names` is the flat lowercase list
    validate_events.py has always read; `attrs` maps the same keys to the few
    card properties a metagame question needs.

    Why attrs exists
    ----------------
    The pool held 5,365 names and nothing else, so the tool could count how
    often a card appeared and could say nothing about what kind of card it was.
    "Blue decks are packing more cheap counterspells", "board wipes are showing
    up because creature decks won last week" and "Flashfreeze is up because red
    and green overperformed" are all colour, mana-value and type questions, and
    none of them could be asked.

    Phill scoped `color_identity` on 2026-09-07 as the blocker for sideboard
    splash weight. `cmc` and `type_line` come along because they cost nothing
    extra: the cards are already in hand, and the alternative is a second full
    crawl the first time somebody asks about two-drops.
    """
    query = f"legal:{fmt.lower()}"
    url = f"{SCRYFALL_SEARCH}?{urllib.parse.urlencode({'q': query, 'unique': 'cards'})}"
    names = set()
    attrs = {}
    pages = 0
    while url:
        try:
            data = _get_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 404 and pages == 0:
                raise SystemExit(f"Scryfall knows no cards for '{query}'. Check the format name.")
            raise
        pages += 1
        for card in data.get("data", []):
            name = card.get("name", "")
            if not name:
                continue
            props = _attributes(card)
            names.add(name.lower())
            attrs.setdefault(name.lower(), props)
            if " // " in name:
                # MTGO prints the full split name, melee often prints the front face.
                for face in name.split(" // "):
                    face = face.strip().lower()
                    names.add(face)
                    attrs.setdefault(face, props)
        print(f"  page {pages}: {len(names)} names so far")
        url = data.get("next_page")
        if url:
            time.sleep(REQUEST_GAP_S)
    return sorted(names), attrs


def is_stale(path, max_age_days):
    if not os.path.isfile(path):
        return True
    if max_age_days is None:
        return False
    try:
        with open(path, encoding="utf-8") as f:
            fetched = json.load(f).get("fetched", "")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(fetched)).days
    except (OSError, ValueError, TypeError):
        return True
    return age >= max_age_days


def build(fmt, data_dir, max_age_days=14, quiet=False):
    path = pool_path(fmt, data_dir)
    if not is_stale(path, max_age_days):
        if not quiet:
            print(f"Card pool for {fmt} is current: {path}")
        return path
    if not quiet:
        print(f"Fetching the {fmt} card pool from Scryfall...")
    names, attrs = fetch_pool(fmt)
    if len(names) < 100:
        raise SystemExit(f"Only {len(names)} cards came back for {fmt}. Refusing to write a pool that small.")
    payload = {
        "format": fmt,
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"{SCRYFALL_SEARCH}?q=legal:{fmt.lower()}",
        "count": len(names),
        # `cards` stays a flat list of names. validate_events.py reads it that
        # way on every run, and Phill's 2026-09-07 constraint was to add the
        # attributes as a separate map rather than reshape this.
        "cards": names,
        "attributes": attrs,
    }
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    if not quiet:
        print(f"Wrote {len(names)} legal card names to {path}")
    return path


def load_pool(fmt, data_dir):
    """Return (set_of_lowercase_names, meta) or (None, None) if there's no cache."""
    path = pool_path(fmt, data_dir)
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None, None
    cards = payload.get("cards") or []
    if not cards:
        return None, None
    # "attributes" is excluded alongside "cards": meta is stamped onto the
    # quarantine report, and a 5,000-entry map does not belong in it.
    meta = {k: v for k, v in payload.items() if k not in ("cards", "attributes")}
    return set(cards), meta


def load_attributes(fmt, data_dir):
    """
    name -> {cmc, colors, color_identity, type_line}, lowercase keys.

    Returns {} when the pool file is missing or predates attributes being
    stored. That is a real state and callers must say so rather than reporting
    a colour or curve answer built on nothing: a pool cached before 2026-09-08
    has names only. `python build_card_pool.py --max-age-days 0` refills it.
    """
    path = pool_path(fmt, data_dir)
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return {}
    attrs = payload.get("attributes")
    return attrs if isinstance(attrs, dict) else {}


def main():
    parser = argparse.ArgumentParser(description="Cache a format's legal card pool from Scryfall.")
    parser.add_argument("--format", default=None, help="Format name. Overrides mtg_config.json.")
    parser.add_argument("--max-age-days", type=int, default=14,
                        help="Refetch if the cache is at least this old. 0 forces a refresh.")
    args = parser.parse_args()

    config = load_config()
    fmt = (args.format or config.get("format", "Standard")).strip()
    data_dir = resolve_data_dir(fmt, SCRIPT_DIR)
    build(fmt, data_dir, max_age_days=args.max_age_days)


if __name__ == "__main__":
    main()
