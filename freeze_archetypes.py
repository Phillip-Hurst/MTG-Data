#!/usr/bin/env python3
"""
freeze_archetypes.py — mark the archetype notes as belonging to the era that
just ended, and flag the decks a ban took apart.

Run this once, right after archive_era.py, whenever a B&R announcement lands.
It does two things to each `[C] *.md` in the Archetypes folder:

  1. Renames the live `## Matchup data` heading to
     `## Matchup data (pre-ban, through YYYY-MM-DD)`. The numbers stay exactly
     as they are — they were true, they're just true about a format that no
     longer exists. A future session appends a new `## Matchup data` section
     below rather than overwriting history.

  2. Inserts a ban banner under the H1 of every deck that actually ran a banned
     card, naming the card and what it did in that deck.

It does NOT delete anything, and it's safe to run twice — files that already
carry the banner or the renamed heading are left alone.

    python freeze_archetypes.py --dry-run
    python freeze_archetypes.py
    python freeze_archetypes.py --also "Selesnya Landfall=inherits the Mono Green Landfall core"

The "runs a banned card" test is a card name at the start of a key-cards table
row, or a count like "4 Badgermole Cub" in a decklist block. A card named in
prose ("Boulder Dash kills Badgermole Cub") is a mention, not a inclusion, and
doesn't earn a banner. Decks that run a banned card only through another
archetype's shell won't be caught by that test — that's what --also is for.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import mtg_era  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Where the vault's archetype notes live. update_archetypes.py resolves the same
# folder from MTG_OUTPUT_DIR; fall back to the known vault path.
DEFAULT_ARCH_DIR = os.environ.get("MTG_ARCHETYPE_DIR") or os.path.join(
    os.path.expanduser("~"),
    "OneDrive - Connected Sensors", "Documents", "Claude", "Second Brain Starter",
    "02 Projects", "MTG Tournament Analysis Skill", "Archetypes",
)

BANNER_MARK = "> [!warning] Banned"
FROZEN_RE = re.compile(r"^## Matchup data \(", re.MULTILINE)
LIVE_HEADING_RE = re.compile(r"^## Matchup data\s*$", re.MULTILINE)


def runs_card(text, card):
    """True when the note shows the deck playing the card, not just naming it."""
    for ln in text.split("\n"):
        if card not in ln:
            continue
        if re.match(r"^\s*\|\s*(\*\*)?" + re.escape(card), ln):
            return True
        if re.search(r"\b[1-4]\s+" + re.escape(card), ln):
            return True
    return False


def role_for(text, card):
    """Pull the deck's own one-line description of the card out of its key-cards
    table, so the banner says what the card did here rather than in general."""
    for ln in text.split("\n"):
        if re.match(r"^\s*\|\s*(\*\*)?" + re.escape(card), ln):
            cells = [c.strip(" *") for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[1]:
                return cells[1].rstrip(" .")
    return None


def build_banner(hits, ban, date_str, extra_reason=None):
    lines = [f"{BANNER_MARK} {date_str}"]
    for card, role in hits:
        if role:
            lines.append(f"> **{card}** is banned in Standard. In this deck it was: {role}.")
        else:
            lines.append(f"> **{card}** is banned in Standard.")
    if extra_reason:
        lines.append(f"> This deck {extra_reason}.")
    lines.append(">")
    lines.append("> Everything below is a record of how the deck played before the "
                 f"{date_str} banned and restricted announcement. The list can't be "
                 "registered as written, and the matchup numbers describe a field that "
                 "no longer exists. Read it as history.")
    if ban.get("url"):
        lines.append(f">")
        lines.append(f"> Announcement: {ban['url']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch-dir", default=DEFAULT_ARCH_DIR)
    ap.add_argument("--format", default="Standard")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--also", action="append", default=[],
                    metavar="ARCHETYPE=REASON",
                    help="Flag a deck the card-name test can't see, e.g. one that "
                         "inherits another archetype's shell. Repeatable.")
    args = ap.parse_args()

    era = mtg_era.resolve_era(fmt=args.format)
    if era["anchor"] != "ban" or not era.get("ban"):
        sys.exit(f"Current {args.format} era isn't a post-ban era ({era['label']}). "
                 f"Nothing to freeze.")
    ban = era["ban"]
    date_str = era["start_str"]
    banned = list(ban.get("banned") or []) + list(ban.get("restricted") or [])

    extra = {}
    for item in args.also:
        name, _, reason = item.partition("=")
        extra[name.strip().lower()] = reason.strip() or "runs a banned card through another shell"

    if not os.path.isdir(args.arch_dir):
        sys.exit(f"Archetypes folder not found: {args.arch_dir}\n"
                 f"Pass --arch-dir or set MTG_ARCHETYPE_DIR.")

    print(f"\nEra: {era['label']}")
    print(f"Banned: {', '.join(banned)}")
    print(f"Folder: {args.arch_dir}\n")

    frozen = flagged = skipped = 0
    for fn in sorted(os.listdir(args.arch_dir)):
        if not fn.endswith(".md") or not fn.startswith("[C] "):
            continue
        path = os.path.join(args.arch_dir, fn)
        with open(path, encoding="utf-8") as f:
            text = original = f.read()
        name = fn[4:-3]
        actions = []

        # 1. Freeze the live matchup heading.
        if LIVE_HEADING_RE.search(text):
            text = LIVE_HEADING_RE.sub(
                f"## Matchup data (pre-ban, through {date_str})", text, count=1)
            actions.append("froze matchup heading")
        elif FROZEN_RE.search(text):
            actions.append("heading already frozen")

        # 2. Ban banner.
        hits = [(c, role_for(text, c)) for c in banned if runs_card(text, c)]
        extra_reason = extra.get(name.lower())
        if (hits or extra_reason) and BANNER_MARK not in text:
            banner = build_banner(hits, ban, date_str, extra_reason)
            m = re.search(r"^# .+$", text, re.MULTILINE)
            if m:
                idx = m.end()
                text = text[:idx] + "\n\n" + banner + "\n" + text[idx:]
            else:
                text = banner + "\n\n" + text
            cards = ", ".join(c for c, _ in hits) or "inherited"
            actions.append(f"banner ({cards})")
            flagged += 1
        elif BANNER_MARK in text:
            actions.append("banner already present")

        if text != original:
            frozen += 1
            print(f"  {name:28s} — {'; '.join(actions)}")
            if not args.dry_run:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
        else:
            skipped += 1

    print(f"\n{frozen} file(s) changed, {flagged} ban banner(s), {skipped} unchanged.")
    if args.dry_run:
        print("--dry-run: nothing written.")


if __name__ == "__main__":
    main()
