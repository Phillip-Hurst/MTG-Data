#!/usr/bin/env python3
"""
archive_era.py — freeze the previous era's scraped data so the current era
starts from a clean slate.

Why this exists: winrate_analysis.py, matchup_matrix.py and update_archetypes.py
all glob `melee_*_pairings.csv` out of the data folder and treat everything they
find as one pool. That's right inside an era and wrong across one. The morning
after a ban, those globs would blend a dead format's win rates into the live
numbers and nothing in the output would say so.

The glob is not recursive, so moving the old files into a subfolder is the whole
fix. They stay on disk, readable, labelled, and out of the live pool.

    python archive_era.py --dry-run     # list what would move, touch nothing
    python archive_era.py               # move it
    python archive_era.py --era secrets-of-strixhaven   # name the folder yourself

What moves into archive/<era-slug>/ :
    melee_*_pairings.csv, melee_*_standings.csv   (per-event and combined)
    mtgo_5-0_latest.json, mtgo_challenge_latest.json, mtgo_deck_log.csv
    melee_deck_cache.json, standings_only_events.json
    baselines/meta_baseline_<previous era slug>.json

What stays put:
    every .py, the config json, archetype_refs.json, mtgo_classifications.json
    (deck classification is card-based, and cards don't change when a deck dies)

A manifest.json lands in the archive folder with the era, the ban that closed
it, the file list, and the row counts, so the frozen data can still be read and
cited later without guessing what window it covers.
"""
import argparse
import csv
import glob
import json
import os
import shutil
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

DATA_DIR = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)

# Globs relative to DATA_DIR. Order matters only for readability.
MOVE_GLOBS = [
    "melee_*_pairings.csv",
    "melee_*_standings.csv",
]
MOVE_FILES = [
    "mtgo_5-0_latest.json",
    "mtgo_challenge_latest.json",
    "mtgo_deck_log.csv",
    "mtgo_deck_log.md",
    "melee_deck_cache.json",
    "standings_only_events.json",
]


def count_rows(path):
    """Data rows in a CSV, header excluded. Best effort — a file we can't read
    still gets archived, it just gets a null count."""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            return max(0, sum(1 for _ in csv.reader(f)) - 1)
    except OSError:
        return None


def collect(data_dir):
    paths = []
    for pattern in MOVE_GLOBS:
        paths += glob.glob(os.path.join(data_dir, pattern))
    for name in MOVE_FILES:
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            paths.append(p)
    # Dedupe, keep files only, stable order.
    return sorted({p for p in paths if os.path.isfile(p)})


def main():
    ap = argparse.ArgumentParser(description="Freeze the previous era's scraped data.")
    ap.add_argument("--era", default=None,
                    help="Archive folder name. Default: through-<era start date>.")
    ap.add_argument("--format", default=None, help="Format (default: mtg_config.json)")
    ap.add_argument("--dry-run", action="store_true", help="List, don't move")
    args = ap.parse_args()

    cfg_path = mtg_era.find_config("mtg_config.json")
    cfg = {"format": "Standard", "weeks_window": 8}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
        except (OSError, ValueError):
            pass
    fmt = args.format or cfg["format"]

    current = mtg_era.resolve_era(fmt=fmt, weeks_window=cfg["weeks_window"])
    previous = mtg_era.previous_era(fmt=fmt, weeks_window=cfg["weeks_window"])
    # Named for what the folder actually holds: everything scraped up to the
    # break. That's usually more than one era — the data folder accumulates
    # across set releases — so naming it after the previous era alone would
    # overclaim. manifest.json carries the precise era labels.
    era_slug = args.era or f"through-{current['start_str']}"

    print(f"\nFormat: {fmt}")
    print(f"Current era:  {current['label']}  (starts {current['start_str']})")
    if previous:
        print(f"Archiving:    {previous['label']}")
    else:
        print(f"Archiving:    everything before {current['start_str']}")
    print(f"Into:         archive/{era_slug}/\n")

    if current["anchor"] not in ("ban", "set-release") and not args.era:
        print("The current era isn't anchored to a ban or a set release, so there's "
              "nothing obvious to split on. Pass --era to name the archive yourself.")
        sys.exit(1)

    paths = collect(DATA_DIR)
    if not paths:
        print("Nothing to archive — no scraped CSVs or MTGO dumps in the data folder.")
        sys.exit(0)

    dest_dir = os.path.join(DATA_DIR, "archive", era_slug)
    manifest_files = []
    total_rows = 0
    for p in paths:
        name = os.path.basename(p)
        rows = count_rows(p) if name.endswith(".csv") else None
        if rows:
            total_rows += rows
        manifest_files.append({"file": name, "rows": rows,
                               "bytes": os.path.getsize(p)})

    # The previous era's baseline moves too, so a fresh build_baseline run in the
    # new era can't append to it by accident.
    baseline_src = None
    if previous:
        cand = os.path.join(DATA_DIR, "baselines", f"meta_baseline_{previous['slug']}.json")
        if os.path.exists(cand):
            baseline_src = cand
            manifest_files.append({"file": f"baselines/{os.path.basename(cand)}",
                                   "rows": None, "bytes": os.path.getsize(cand)})

    print(f"{len(manifest_files)} file(s), {total_rows:,} CSV data rows:")
    for m in manifest_files[:12]:
        rows = f"{m['rows']:>7,} rows" if m["rows"] is not None else " " * 12
        print(f"  {m['file']:<48} {rows}")
    if len(manifest_files) > 12:
        print(f"  ... and {len(manifest_files) - 12} more")

    if args.dry_run:
        print("\n--dry-run: nothing moved.")
        return

    os.makedirs(dest_dir, exist_ok=True)
    os.makedirs(os.path.join(dest_dir, "baselines"), exist_ok=True)

    moved = 0
    for p in paths:
        dst = os.path.join(dest_dir, os.path.basename(p))
        if os.path.exists(dst):
            print(f"  ! already in the archive, skipping: {os.path.basename(p)}")
            continue
        shutil.move(p, dst)
        moved += 1
    if baseline_src:
        dst = os.path.join(dest_dir, "baselines", os.path.basename(baseline_src))
        if not os.path.exists(dst):
            shutil.move(baseline_src, dst)
            moved += 1

    manifest = {
        "archived": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "format": fmt,
        "era": era_slug,
        "era_label": previous["label"] if previous else f"before {current['start_str']}",
        "covers_through": current["start_str"],
        "closed_by": {
            "anchor": current["anchor"],
            "date": current["start_str"],
            "reason": current["reason"],
        },
        "file_count": len(manifest_files),
        "csv_data_rows": total_rows,
        "files": manifest_files,
        "note": "Frozen reference. Read it for cross-era comparison; do not merge it "
                "into live win-rate or matchup numbers. The analysis scripts glob the "
                "parent folder only, so these files are out of the live pool by design.",
    }
    if current.get("ban"):
        manifest["closed_by"]["ban"] = current["ban"]

    with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\nMoved {moved} file(s) into archive/{era_slug}/")
    print(f"Wrote archive/{era_slug}/manifest.json")
    print(f"\nThe data folder is now empty of scraped results. Next:")
    print(f"  python mtg_fetch.py        # scrape the {current['label']} era from scratch")


if __name__ == "__main__":
    main()
