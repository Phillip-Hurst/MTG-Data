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
REQUEST_GAP_S = 0.12  # Scryfall asks for 50-100ms between requests


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


def _get_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_pool(fmt):
    """Page through Scryfall for every card legal in this format."""
    query = f"legal:{fmt.lower()}"
    url = f"{SCRYFALL_SEARCH}?{urllib.parse.urlencode({'q': query, 'unique': 'cards'})}"
    names = set()
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
            names.add(name.lower())
            if " // " in name:
                # MTGO prints the full split name, melee often prints the front face.
                for face in name.split(" // "):
                    names.add(face.strip().lower())
        print(f"  page {pages}: {len(names)} names so far")
        url = data.get("next_page")
        if url:
            time.sleep(REQUEST_GAP_S)
    return sorted(names)


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
    names = fetch_pool(fmt)
    if len(names) < 100:
        raise SystemExit(f"Only {len(names)} cards came back for {fmt}. Refusing to write a pool that small.")
    payload = {
        "format": fmt,
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"{SCRYFALL_SEARCH}?q=legal:{fmt.lower()}",
        "count": len(names),
        "cards": names,
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
    meta = {k: v for k, v in payload.items() if k != "cards"}
    return set(cards), meta


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
