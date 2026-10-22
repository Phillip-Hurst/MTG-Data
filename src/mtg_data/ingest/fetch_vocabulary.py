#!/usr/bin/env python3
"""
fetch_vocabulary.py — the published archetype vocabulary, from MTGGoldfish.

Why
---
Naming a shell used to lean on the local melee cache: whatever organizers had
typed for a list with a similar core. That works, but it inherits every typo and
every bare colour-pair label a player entered at 9am, and it can only suggest a
name someone in your own scrape data already used.

MTGGoldfish publishes the format's actual vocabulary — archetype name, meta
share, deck count, and the three cards that define it. That's a far better
naming authority, and the defining cards make it matchable: a shell whose core
contains Astrologian's Planisphere, Slickshot Show-Off and Pym Particles is
Izzet Prowess, and the site says so.

It also keeps the categories honest as the format moves. On 2026-09-07 this
table showed Izzet Prowess alive at 1.0% and 13 decks after the Stormchaser's
Talent ban, which is how a "that deck is gone" assumption gets caught.

Output
------
`archetype_vocabulary.json`:

    {"source": "mtggoldfish", "format": "Standard", "fetched": "YYYY-MM-DD",
     "window_days": 30,
     "archetypes": {name: {"meta_pct": float, "decks": int,
                           "defining": [card, card, card], "url": str}}}

Usage
-----
    python mtg.py fetch-vocabulary                     # fetch and write
    python mtg.py fetch-vocabulary --dry-run           # print what it found
    python mtg.py fetch-vocabulary --from-file page.html   # parse a saved page

`cluster_shells.py` reads the file if it's there and ignores it if it isn't, so
nothing breaks when the fetch can't run.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date
from mtg_data.core.paths import CONFIG_DIR, ROOT_DIR


DATA_DIR = os.environ.get("MTG_DATA_DIR", CONFIG_DIR)
VOCAB_FILE = os.path.join(DATA_DIR, "archetype_vocabulary.json")

BASE = "https://www.mtggoldfish.com/metagame/{fmt}/full"
UA = {"User-Agent": "Mozilla/5.0 (compatible; mtg-tournament-analysis/1.18)"}

# One archetype block: the deck link carrying the name, the three defining
# cards, and the META% figure with its deck count in brackets.
BLOCK_RE = re.compile(
    r'<a[^>]+href="(?P<url>/archetype/[^"#]+)"[^>]*>(?P<name>[^<]+)</a>'
    r'(?P<body>.*?)'
    r'(?P<pct>\d+\.\d+)%\s*\((?P<decks>\d+)\)',
    re.DOTALL)
CARD_RE = re.compile(r'<li[^>]*>\s*([^<]+?)\s*</li>')


def fetch(fmt="standard", timeout=30):
    url = BASE.format(fmt=fmt)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse(html):
    """{name: {meta_pct, decks, defining, url}} — best entry per name kept."""
    out = {}
    for m in BLOCK_RE.finditer(html):
        name = m.group("name").strip()
        if not name or name.startswith("<"):
            continue
        cards = [c.strip() for c in CARD_RE.findall(m.group("body"))][:3]
        entry = {
            "meta_pct": float(m.group("pct")),
            "decks": int(m.group("decks")),
            "defining": cards,
            "url": "https://www.mtggoldfish.com" + m.group("url"),
        }
        # The same name appears once per view (online/paper). Keep the richer.
        prev = out.get(name)
        if not prev or entry["decks"] > prev["decks"] or (
                not prev["defining"] and entry["defining"]):
            out[name] = entry
    return out


def load():
    """The vocabulary, or {} when there isn't one. Callers must tolerate {}."""
    if not os.path.exists(VOCAB_FILE):
        return {}
    try:
        with open(VOCAB_FILE, encoding="utf-8") as f:
            return json.load(f).get("archetypes", {})
    except (OSError, ValueError):
        return {}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--format", default="standard")
    p.add_argument("--from-file", metavar="PATH",
                   help="Parse a saved page instead of fetching")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.from_file:
        html = open(args.from_file, encoding="utf-8", errors="replace").read()
    else:
        try:
            html = fetch(args.format)
        except Exception as e:
            print(f"Could not reach MTGGoldfish: {e}")
            print("Save the page and pass --from-file, or try again later.")
            print("Naming still works without this; it falls back to the melee cache.")
            return 1

    archetypes = parse(html)
    if not archetypes:
        print("Parsed nothing. MTGGoldfish probably changed its markup — check "
              "BLOCK_RE against the page source.")
        return 1

    print(f"{len(archetypes)} archetype(s) in the published vocabulary:\n")
    for name, a in sorted(archetypes.items(), key=lambda kv: -kv[1]["meta_pct"])[:20]:
        print(f"  {a['meta_pct']:5.1f}%  {a['decks']:4d} decks  {name:28} "
              f"{', '.join(a['defining'][:3])}")
    if len(archetypes) > 20:
        print(f"  ... and {len(archetypes)-20} more")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    doc = {"source": "mtggoldfish", "format": args.format.title(),
           "fetched": date.today().isoformat(), "window_days": 30,
           "url": BASE.format(fmt=args.format), "archetypes": archetypes}
    with open(VOCAB_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"\nWritten: {os.path.basename(VOCAB_FILE)}")
    print("cluster-shells will use it for name suggestions from now on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
