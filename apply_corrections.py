#!/usr/bin/env python3
"""
apply_corrections.py — read deck-label decisions back out of Obsidian.

The loop
--------
1. build_refs_from_melee.py writes "[C] Mislabeled Decks YYYY-MM-DD.md" with a
   `Decision:` line under each flagged deck, pre-filled with the card match.
2. You edit those lines in Obsidian. Leave it to accept, change it to override,
   blank it or write `skip` to defer.
3. This script reads every review note, records each decision in
   archetype_overrides.json keyed by decklist URL, and applies them to
   melee_deck_cache.json and mtgo_classifications.json.

Why an overrides file rather than editing the cache
---------------------------------------------------
The old instruction was "delete the bad deck URL from melee_deck_cache.json,
change its archetype field, then rerun with --rebuild-only". That works until
the next scrape refetches the deck and overwrites the correction, silently,
with no record that a human had ever ruled on it. Overrides are durable: they
live in their own file, they carry who decided and when, and --reapply puts
them back after any scrape.

Usage
-----
    python apply_corrections.py                 # read notes, apply, report
    python apply_corrections.py --dry-run       # show what would change
    python apply_corrections.py --reapply       # skip the notes, just reapply
    python apply_corrections.py --notes-dir ... # non-default review-note folder
    python apply_corrections.py --list          # print current overrides
"""
import argparse
import csv
import glob
import json
import os
import re
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from mtg_paths import resolve_data_dir, resolve_output_dir  # noqa: E402

OVERRIDES_NAME = "archetype_overrides.json"
RESOLVED_DIRNAME = "Mislabel Review Resolved"
NOTE_GLOB = "[[]C[]] Mislabeled Decks *.md"

ENTRY_RE = re.compile(
    r"^###\s+(?P<player>.+?)\s+—\s+(?P<tournament>.+?)\s*$"
    r"(?P<body>.*?)"
    r"(?=^###\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
URL_RE = re.compile(r"^URL:\s*(?P<url>\S+)", re.MULTILINE)
MELEE_LABEL_RE = re.compile(r"^Melee label\s*:\s*\*\*(?P<arch>[^*]+)\*\*", re.MULTILINE)
CARD_MATCH_RE = re.compile(r"^Card match\s*:\s*\*\*(?P<arch>[^*]+)\*\*", re.MULTILINE)
DECISION_RE = re.compile(r"^Decision:\s*(?P<decision>.*?)\s*$", re.MULTILINE)

SKIP_WORDS = {"", "skip", "tbd", "?", "unsure", "n/a", "-", "todo"}


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


def overrides_path(data_dir):
    return os.path.join(data_dir, OVERRIDES_NAME)


def load_overrides(data_dir):
    path = overrides_path(data_dir)
    if not os.path.isfile(path):
        return {"note": ("Human rulings on deck archetype labels, keyed by decklist URL. "
                         "Written by apply_corrections.py from the [C] Mislabeled Decks "
                         "notes. Reapplied after every scrape so a rescrape can't quietly "
                         "undo a decision."),
                "overrides": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"overrides": {}}
    data.setdefault("overrides", {})
    return data


def save_overrides(data_dir, data):
    with open(overrides_path(data_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def parse_note(text, source):
    """Yield one decision dict per entry that carries a usable Decision line."""
    out = []
    for m in ENTRY_RE.finditer(text):
        body = m.group("body")
        url_m = URL_RE.search(body)
        dec_m = DECISION_RE.search(body)
        if not url_m or not dec_m:
            continue
        decision = dec_m.group("decision").strip()
        card_m = CARD_MATCH_RE.search(body)
        melee_m = MELEE_LABEL_RE.search(body)
        out.append({
            "url": url_m.group("url").strip(),
            "player": m.group("player").strip(),
            "tournament": m.group("tournament").strip(),
            "decision": decision,
            "card_match": card_m.group("arch").strip() if card_m else None,
            "melee_label": melee_m.group("arch").strip() if melee_m else None,
            "source": source,
        })
    return out


def candidate_note_dirs(fmt, explicit=None):
    """
    Every folder the review notes might be in, most specific first.

    This is deliberately generous. Run-MtgScrapes.ps1 sets MTG_OUTPUT_DIR to
    the project folder, so a scheduled run writes the notes there. A person
    running this script by hand has no such env var, and with no
    mtg_workspace.json on disk mtg_paths falls back to the script folder —
    where there are no notes. That combination made this script print
    "Read 0 review note(s)" and exit 0, which is the same silent no-op that
    let a contaminated pool reach a snapshot for 17 days.
    """
    dirs = []

    def add(d):
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)

    # An explicit --notes-dir is exclusive. Searching elsewhere as well would
    # quietly widen a deliberately narrow request, and --backfill rewrites files.
    if explicit:
        add(explicit)
        return dirs

    add(os.environ.get("MTG_OUTPUT_DIR"))
    add(resolve_output_dir(fmt, SCRIPT_DIR))

    # Walk up looking for the Obsidian project folder the notes are written to.
    d = SCRIPT_DIR
    for _ in range(4):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
        projects = os.path.join(d, "02 Projects")
        if os.path.isdir(projects):
            for entry in sorted(os.listdir(projects)):
                if "mtg" in entry.lower():
                    add(os.path.join(projects, entry))
            break

    add(SCRIPT_DIR)
    return dirs


def read_notes(notes_dirs):
    """Read every review note across the candidate folders. Returns (decisions, files, searched)."""
    if isinstance(notes_dirs, str):
        notes_dirs = [notes_dirs]
    decisions, files, searched = [], [], []
    seen = set()
    for d in notes_dirs:
        hits = sorted(glob.glob(os.path.join(d, NOTE_GLOB)))
        searched.append((d, len(hits)))
        for path in hits:
            key = os.path.basename(path)
            if key in seen:
                continue  # same note reachable from two paths
            seen.add(key)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            files.append(path)
            decisions.extend(parse_note(text, key))
    return decisions, files, searched


def archive_resolved_notes(files, overrides, data_dir, delete=False):
    """
    Retire a review note once every deck in it has been ruled on.

    Without this the project folder accumulates one to-do note per scrape
    forever, and there's no way to tell at a glance which still need attention.
    A note is resolved when every entry carrying a URL has a recorded override.
    A single `skip` keeps the whole note in the queue, which is the point: the
    folder is the to-do list.

    Archives by default rather than deleting. These are notes in the user's
    vault, and a wrong verdict here should cost a move, not a recovery.
    """
    resolved = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        entries = [d for d in parse_note(text, os.path.basename(path)) if d["url"]]
        if not entries:
            continue
        if not all(d["url"] in overrides for d in entries):
            continue

        name = os.path.basename(path)
        if delete:
            try:
                os.remove(path)
            except OSError:
                continue
        else:
            archive_dir = os.path.join(os.path.dirname(path), RESOLVED_DIRNAME)
            try:
                os.makedirs(archive_dir, exist_ok=True)
                os.replace(path, os.path.join(archive_dir, name))
            except OSError:
                continue
        resolved.append(name)
    return resolved


def backfill_note(path, dry_run=False):
    """
    Add a `Decision:` line to entries in a review note written before they existed.

    Notes generated before 2026-08-29 have no Decision line, so there is nothing
    for this script to read. Rather than making people retype 40 entries, insert
    the line pre-filled with the card match, exactly as a fresh note would have.
    Entries that already have one are left alone.
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return 0

    added = 0
    out, pos = [], 0
    for m in ENTRY_RE.finditer(text):
        body = m.group("body")
        if DECISION_RE.search(body) or not URL_RE.search(body):
            continue
        card_m = CARD_MATCH_RE.search(body)
        if not card_m:
            continue
        # Insert before the entry's trailing separator so the note still reads well.
        entry_end = m.end()
        stripped = body.rstrip()
        if stripped.endswith("---"):
            insert_at = m.start("body") + body.rfind("---")
            line = f"Decision: {card_m.group('arch').strip()}\n\n"
        else:
            insert_at = entry_end
            line = f"\nDecision: {card_m.group('arch').strip()}\n"
        out.append(text[pos:insert_at])
        out.append(line)
        pos = insert_at
        added += 1
    out.append(text[pos:])

    if added and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(out))
    return added


def apply_to_cache(data_dir, overrides, dry_run=False):
    """Write overridden archetypes into melee_deck_cache.json, keyed by URL."""
    path = os.path.join(data_dir, "melee_deck_cache.json")
    if not os.path.isfile(path):
        path = os.path.join(SCRIPT_DIR, "melee_deck_cache.json")
    if not os.path.isfile(path):
        return 0, 0
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return 0, 0
    changed, missing = 0, 0
    for url, rec in overrides.items():
        entry = cache.get(url)
        if entry is None:
            missing += 1
            continue
        if entry.get("archetype") != rec["archetype"]:
            entry["archetype"] = rec["archetype"]
            entry["archetype_source"] = "human-override"
            changed += 1
    if changed and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1, ensure_ascii=False)
    return changed, missing


def apply_to_pairings(data_dir, overrides, dry_run=False):
    """
    Rewrite the deck-name columns in every pairing and standings CSV.

    This is the step that makes a correction show up in a matchup check.
    matchup_matrix.py and winrate_analysis.py go through mtg_stats.classify_row,
    which reads `player1_deck` / `player2_deck` straight off the CSV row — not
    the decklist cache. Relabelling only the cache leaves the matrix reporting
    the melee label forever.

    Matches on the decklist URL, which is stable across rescrapes. Covers the
    per-event CSVs (what the matchup matrix globs) and the combined ones (what
    build_baseline.py reads), including quarantined files so a verdict that is
    later reversed comes back with the corrections already applied.
    """
    patterns = ["melee_*_pairings.csv", "melee_*_standings.csv",
                "melee_*_pairings.quarantined.csv", "melee_*_standings.quarantined.csv"]
    paths = []
    for pat in patterns:
        paths.extend(glob.glob(os.path.join(data_dir, pat)))
    if data_dir != SCRIPT_DIR:
        for pat in patterns:
            paths.extend(glob.glob(os.path.join(SCRIPT_DIR, pat)))

    files_changed, rows_changed = 0, 0
    for path in sorted(set(paths)):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fields = reader.fieldnames or []
                rows = list(reader)
        except OSError:
            continue
        if not rows:
            continue

        # (url column, name column) pairs present in this file
        cols = [(u, n) for u, n in (("player1_deck_url", "player1_deck"),
                                    ("player2_deck_url", "player2_deck"),
                                    ("deck_url", "deck_name"))
                if u in fields and n in fields]
        if not cols:
            continue

        touched = 0
        for r in rows:
            for url_col, name_col in cols:
                url = (r.get(url_col) or "").strip()
                rec = overrides.get(url)
                if rec and r.get(name_col) != rec["archetype"]:
                    r[name_col] = rec["archetype"]
                    touched += 1
        if not touched:
            continue
        rows_changed += touched
        files_changed += 1
        if not dry_run:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)
    return files_changed, rows_changed


def apply_to_classifications(data_dir, overrides, dry_run=False):
    """
    Same rulings, applied to the MTGO side.

    mtgo_classifications.json is keyed "event_url;deck_url", so match on the
    deck URL appearing anywhere in the key.
    """
    path = os.path.join(data_dir, "mtgo_classifications.json")
    if not os.path.isfile(path):
        path = os.path.join(SCRIPT_DIR, "mtgo_classifications.json")
    if not os.path.isfile(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            cls = json.load(f)
    except (OSError, ValueError):
        return 0
    changed = 0
    for url, rec in overrides.items():
        for key, entry in cls.items():
            if url in key and entry.get("archetype") != rec["archetype"]:
                entry["archetype"] = rec["archetype"]
                entry["status"] = "human-override"
                changed += 1
    if changed and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cls, f, indent=1, ensure_ascii=False)
    return changed


def main():
    p = argparse.ArgumentParser(description="Apply deck-label corrections made in Obsidian.")
    p.add_argument("--format", default=None, help="Format. Overrides mtg_config.json.")
    p.add_argument("--notes-dir", default=None,
                   help="Folder holding the review notes. Without this, the script "
                        "searches MTG_OUTPUT_DIR, the workspace manifest, the Obsidian "
                        "project folder, and its own folder.")
    p.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    p.add_argument("--reapply", action="store_true",
                   help="Skip the notes and reapply the stored overrides. Run after a scrape.")
    p.add_argument("--list", action="store_true", help="Print stored overrides and exit.")
    p.add_argument("--delete-resolved", action="store_true",
                   help="Delete fully-resolved review notes instead of archiving them.")
    p.add_argument("--backfill", action="store_true",
                   help="Add Decision: lines to review notes that predate them, "
                        "pre-filled with the card match. Run --dry-run first.")
    args = p.parse_args()

    config = load_config()
    fmt = (args.format or config.get("format", "Standard")).strip()
    data_dir = resolve_data_dir(fmt, SCRIPT_DIR)


    store = load_overrides(data_dir)
    overrides = store["overrides"]

    if args.list:
        if not overrides:
            print("No overrides on file.")
            return 0
        print(f"{len(overrides)} override(s) in {overrides_path(data_dir)}\n")
        for url, rec in sorted(overrides.items(), key=lambda kv: kv[1].get("decided", "")):
            print(f"  {rec['archetype']:28s}  was {str(rec.get('was')):28s}  {rec.get('decided','?')}")
            print(f"    {rec.get('player','?')} — {rec.get('tournament','?')}")
        return 0

    if not args.reapply:
        note_dirs = candidate_note_dirs(fmt, explicit=args.notes_dir)
        decisions, files, searched = read_notes(note_dirs)
        print("Searched for review notes:")
        for d, n in searched:
            print(f"  {n:3d} note(s)  {d}")
        if not files:
            print(f"\nNo files matching '{NOTE_GLOB}' in any of the folders above.")
            print("  Point at the right one with --notes-dir, or run")
            print("  build_refs_from_melee.py first to generate a review note.")
            print("  Exiting non-zero rather than reporting success on nothing.")
            return 1
        print(f"\nRead {len(files)} review note(s)")

        if args.backfill:
            total = 0
            for path in files:
                n = backfill_note(path, dry_run=args.dry_run)
                if n:
                    total += n
                    print(f"  +{n:3d} Decision line(s)  {os.path.basename(path)}")
            print(f"\nBackfilled {total} entry/entries with the card match as the default.")
            if args.dry_run:
                print("--dry-run: nothing written.")
                return 0
            if total:
                decisions, files, _ = read_notes(note_dirs)
                print("Re-read the notes. Edit any you disagree with, then run again "
                      "without --backfill.")
                return 0

        if not decisions:
            print("\nNo `Decision:` lines found in those notes.")
            print("  Notes written before 2026-08-29 predate the Decision line. To add")
            print("  them, pre-filled with the card match:")
            print("    python apply_corrections.py --backfill --dry-run")
            print("    python apply_corrections.py --backfill")
            print("  Notes from the next scrape onward carry the line already.")
            return 1

        new, updated, skipped, unchanged = 0, 0, 0, 0
        for d in decisions:
            choice = d["decision"].strip()
            if choice.lower() in SKIP_WORDS:
                skipped += 1
                continue
            prior = overrides.get(d["url"])
            if prior and prior.get("archetype") == choice:
                unchanged += 1
                continue
            overrides[d["url"]] = {
                "archetype": choice,
                "was": d["melee_label"],
                "card_match": d["card_match"],
                "player": d["player"],
                "tournament": d["tournament"],
                "decided": date.today().isoformat(),
                "source_note": d["source"],
            }
            if prior:
                updated += 1
            else:
                new += 1
        print(f"  {len(decisions)} decision line(s): {new} new, {updated} changed, "
              f"{unchanged} already recorded, {skipped} left for later")

    if not overrides:
        print("\nNo overrides to apply.")
        return 0

    cache_changed, cache_missing = apply_to_cache(data_dir, overrides, dry_run=args.dry_run)
    cls_changed = apply_to_classifications(data_dir, overrides, dry_run=args.dry_run)
    csv_files, csv_rows = apply_to_pairings(data_dir, overrides, dry_run=args.dry_run)

    print(f"\n{len(overrides)} override(s) on file")
    print(f"  melee_deck_cache.json:      {cache_changed} deck(s) relabelled")
    if cache_missing:
        print(f"    ({cache_missing} override(s) reference a deck not in the cache — "
              "kept, they'll apply if it's rescraped)")
    print(f"  mtgo_classifications.json:  {cls_changed} deck(s) relabelled")
    print(f"  pairing/standings CSVs:     {csv_rows} cell(s) across {csv_files} file(s)")
    print("    ^ this is the one the matchup matrix and win-rate scripts read")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    save_overrides(data_dir, store)
    print(f"  Overrides: {overrides_path(data_dir)}")

    if not args.reapply:
        resolved = archive_resolved_notes(files, overrides, data_dir,
                                          delete=args.delete_resolved)
        if resolved:
            verb = "Deleted" if args.delete_resolved else "Archived"
            print(f"\n{verb} {len(resolved)} fully-resolved review note(s):")
            for name in resolved:
                print(f"  {name}")
            if not args.delete_resolved:
                print(f"  → {os.path.join(RESOLVED_DIRNAME, '')} "
                      "(pass --delete-resolved to remove them instead)")
        else:
            print("\nNo review note is fully resolved yet — every one still has at "
                  "least one entry left to decide.")

    print("\nRebuild the references so the corrections feed future matching:")
    print("  python build_refs_from_melee.py --rebuild-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
