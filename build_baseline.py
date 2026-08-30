#!/usr/bin/env python3
"""
build_baseline.py — append a meta snapshot to the current set's baseline file.

Recreated 2026-06-10. The original lived in a Cowork session outputs folder
and was lost when the session was wiped. This version lives next to the
scrapers so it survives.

Reads:
  melee_all_standings.csv  (player/deck/rank per round, built by melee_scraper.py)
  set_releases.json        (current set name + release date)

Writes:
  baselines/meta_baseline_<set_slug>.json — appends one entry to snapshots[]

Usage:
  python build_baseline.py --label "Week 7 — post-Spotlight"
  python build_baseline.py --label "..." --dry-run     # print, don't write
  python build_baseline.py --label "..." --date 2026-06-10
  python build_baseline.py --label "..." --md-dir "<project>/Snapshots"

--md-dir also appends a human-readable section to a weekly markdown note,
one file per ISO week (Mon-Sun), named "[C] Meta Snapshot — Week of
<monday>.md". Both scheduled runs in a week (Mon 7pm, Thu 2am) land in the
same file; a new week starts a new file. The vault accumulates one note per
week for week-over-week comparison.

Notes:
  - melee_all_standings.csv holds one final-standings row per player per
    tournament (rebuilt 2026-06-10 with exact-dupe removal). If multiple
    rows per player ever reappear, the max-points row is treated as final.
  - Top 8 = final rank <= 8, deduped per player per tournament.
  - Junk labels ("Decklist", "Unknown", blank) are excluded; the share
    denominator is players with a real deck name — same convention as the
    2026-05-04 snapshot (total_players_with_deck).
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

# Windows consoles default to cp1252 and choke on box-drawing and accented
# characters in deck and player names. Force UTF-8 where the stream supports it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Importable no matter where this is run from — the scheduled task and the
# by-hand run don't share a working directory.
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import mtg_era  # noqa: E402  (needs SCRIPT_DIR on sys.path first)
# Data is read from MTG_DATA_DIR (defaults to the script folder so the flat
# single-format workflow is unchanged). setup.py points it at a per-format folder.
DATA_DIR = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)


def _find_config(name):
    """Look in the data folder first, fall back to the shipped copy next to the
    scripts. Lets each format carry its own set_releases.json without forcing it."""
    p = os.path.join(DATA_DIR, name)
    return p if os.path.exists(p) else os.path.join(SCRIPT_DIR, name)


# Combined standings file is tagged by format (melee_scraper.py writes it that
# way) so formats never share a filename.
_FMT_SLUG = (os.environ.get("MTG_FORMAT", "Standard").strip() or "Standard").lower()
STANDINGS = os.path.join(DATA_DIR, f"melee_{_FMT_SLUG}_all_standings.csv")
SET_RELEASES = _find_config("set_releases.json")
BASELINE_DIR = os.path.join(DATA_DIR, "baselines")

JUNK_DECKS = {"", "decklist", "unknown", "deck", "n/a", "-", "—"}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def current_set():
    with open(SET_RELEASES, encoding="utf-8") as f:
        data = json.load(f)
    sets = [s for s in data.get("sets", []) if s.get("release_date")]
    if not sets:
        sys.exit("set_releases.json has no sets with release dates.")
    sets.sort(key=lambda s: s["release_date"])
    return sets[-1]


def current_era():
    """The era this snapshot belongs to (see mtg_era.py).

    A ban opens a new era, and a new era means a new baseline file. Mixing
    pre-ban and post-ban snapshots in one snapshots[] array would make the
    run-over-run delta meaningless the week a ban lands — the decks in the
    previous entry no longer exist."""
    fmt = os.environ.get("MTG_FORMAT", "Standard").strip() or "Standard"
    return mtg_era.resolve_era(fmt=fmt)


def load_standings():
    if not os.path.exists(STANDINGS):
        sys.exit(f"Not found: {STANDINGS} — run mtg_fetch.py / melee_scraper.py first.")
    with open(STANDINGS, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _num(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return -1.0


def build_snapshot(rows, snap_date, label):
    # Final standings row per (tournament, player) = the max-points row
    final = {}        # (tid, player) -> row
    tournaments = {}  # tid -> name

    for r in rows:
        tid = (r.get("tournament_id") or "").strip()
        player = (r.get("player") or "").strip()
        if not tid or not player:
            continue
        tournaments.setdefault(tid, (r.get("tournament_name") or "").strip())
        key = (tid, player)
        if key not in final or _num(r.get("points")) > _num(final[key].get("points")):
            final[key] = r

    # Aggregate by archetype
    archetypes = {}
    for key, r in final.items():
        deck = re.sub(r"\s+", " ", (r.get("deck_name") or "")).strip()
        if deck.lower() in JUNK_DECKS:
            continue
        rank_raw = (r.get("rank") or "").strip()
        in_top8 = rank_raw.isdigit() and 1 <= int(rank_raw) <= 8
        a = archetypes.setdefault(deck, {"player_count": 0, "top8_appearances": 0})
        a["player_count"] += 1
        if in_top8:
            a["top8_appearances"] += 1

    total = sum(a["player_count"] for a in archetypes.values())
    for a in archetypes.values():
        a["meta_share_pct"] = round(100 * a["player_count"] / total, 1) if total else 0.0

    return {
        "date": snap_date,
        "label": label,
        "events_covered": len(tournaments),
        "total_players_with_deck": total,
        "archetypes": dict(sorted(archetypes.items())),
    }, tournaments


def week_monday(d):
    """Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def write_weekly_md(md_dir, snap, baseline, set_name, era=None):
    """Append this snapshot to the current week's markdown note.

    One file per ISO week; every run that week appends a dated section to the
    same file. Delta column compares against the snapshot immediately before
    this one in the baseline (run-over-run) — and because a ban starts a new
    baseline file, the first run of a new era shows every deck as "new" rather
    than a fake delta against decks that got banned out of the format."""
    snap_date = date.fromisoformat(snap["date"])
    monday = week_monday(snap_date)
    os.makedirs(md_dir, exist_ok=True)
    path = os.path.join(md_dir, f"[C] Meta Snapshot — Week of {monday.isoformat()}.md")

    snaps = baseline.get("snapshots", [])
    prev = snaps[-2] if len(snaps) >= 2 else None

    lines = []
    if not os.path.exists(path):
        lines += [
            "---",
            "author: claude",
            "type: note",
            "project: MTG Tournament Analysis Skill",
            f"week_of: {monday.isoformat()}",
            f"set: {set_name}",
            f"era: {era['slug'] if era else set_name}",
            "tags: [mtg, meta, snapshot]",
            "---",
            "",
            f"# Meta snapshot, week of {monday.isoformat()}",
            "",
            f"Set: {set_name}. Era: {era['label'] if era else set_name}.",
            "One section per scrape run; share deltas are vs the previous run in this era.",
        ]

    top = sorted(snap["archetypes"].items(), key=lambda kv: -kv[1]["player_count"])[:12]
    lines += [
        "",
        f"## {snap['date']} ({snap['label']})",
        "",
        f"Events: {snap['events_covered']} | players with deck: {snap['total_players_with_deck']}",
        "",
        "| Archetype | Players | Share | vs prev | Top 8 |",
        "|---|---|---|---|---|",
    ]
    for name, a in top:
        if prev is None:
            delta = ""
        elif name in prev.get("archetypes", {}):
            d = a["meta_share_pct"] - prev["archetypes"][name]["meta_share_pct"]
            delta = f"{d:+.1f}"
        else:
            delta = "new"
        lines.append(f"| {name} | {a['player_count']} | {a['meta_share_pct']}% | {delta} | {a['top8_appearances']} |")

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Weekly note: appended to {os.path.basename(path)}")


def validation_status(era):
    """
    Return a reason string when the pool isn't safe to snapshot, else None.

    Three ways this fails: the validator has never run, it ran against a
    different era than the one we're about to label, or the pool has been
    rescraped since it last ran.
    """
    report_path = os.path.join(DATA_DIR, f"event_quarantine_{_FMT_SLUG}.json")
    if not os.path.isfile(report_path):
        return "the event pool has never been validated (no event_quarantine file)"
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, ValueError):
        return "the event_quarantine file could not be read"

    if report.get("window_start") != era["start_str"]:
        return (f"the pool was validated for a window starting "
                f"{report.get('window_start')}, but the current era starts "
                f"{era['start_str']}")

    if os.path.isfile(STANDINGS):
        try:
            validated_at = datetime.fromisoformat(report["validated"]).timestamp()
            if os.path.getmtime(STANDINGS) > validated_at + 1:
                return "the standings file has been rescraped since the last validation"
        except (OSError, ValueError, KeyError, TypeError):
            return "the validation timestamp could not be compared to the standings file"

    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True, help='Snapshot label, e.g. "Week 7 — post-Spotlight"')
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--md-dir", default=None,
                   help="Folder for the weekly markdown snapshot notes (skip if omitted)")
    p.add_argument("--skip-validation-check", action="store_true",
                   help="Write a snapshot from an unvalidated pool. Not recommended.")
    args = p.parse_args()

    cs = current_set()
    era = current_era()

    if not args.skip_validation_check:
        stale = validation_status(era)
        if stale:
            print(f"\nRefusing to write a snapshot: {stale}")
            print("  Run:  python validate_events.py")
            print("  Then re-run this. On 2026-08-27 an unvalidated pool produced a "
                  '"post-ban era" snapshot reporting decks that had been banned 17 days '
                  "earlier — the check exists to stop that reaching a note.")
            print("  To override anyway: --skip-validation-check")
            sys.exit(1)
    # Era slug, not set slug. For a set-only era the two are the same string, so
    # baselines written before eras existed keep their filename and keep meaning
    # the pre-ban stretch they actually cover.
    baseline_path = os.path.join(BASELINE_DIR, f"meta_baseline_{era['slug']}.json")

    rows = load_standings()
    snap, tournaments = build_snapshot(rows, args.date, args.label)
    snap["era"] = era["slug"]
    snap["era_start"] = era["start_str"]

    print(f"Set: {cs['name']} (released {cs['release_date']})")
    print(f"Era: {era['label']} — data from {era['start_str']} onward")
    print(f"Standings rows: {len(rows)} | events: {snap['events_covered']} | "
          f"players with deck: {snap['total_players_with_deck']}")
    top = sorted(snap["archetypes"].items(), key=lambda kv: -kv[1]["player_count"])[:10]
    for name, a in top:
        print(f"  {name:30s} {a['player_count']:4d} players  "
              f"{a['meta_share_pct']:5.1f}%  top8 {a['top8_appearances']}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    os.makedirs(BASELINE_DIR, exist_ok=True)
    if os.path.exists(baseline_path):
        with open(baseline_path, encoding="utf-8") as f:
            baseline = json.load(f)
    else:
        baseline = {"set_name": cs["name"], "set_release": cs["release_date"],
                    "era": era["slug"], "era_label": era["label"],
                    "era_start": era["start_str"], "era_anchor": era["anchor"],
                    "era_reason": era["reason"],
                    "tournament_names": [], "notes": "", "snapshots": [],
                    "event_top8s": {}, "matchups": {}}
        if era.get("ban"):
            baseline["ban"] = {k: era["ban"].get(k) for k in
                               ("effective", "banned", "restricted", "decks_hit", "url")}

    if any(s.get("date") == args.date for s in baseline.get("snapshots", [])):
        print(f"\nA snapshot dated {args.date} already exists — not appending. "
              f"Use --date to disambiguate or edit the file.")
        return

    baseline.setdefault("snapshots", []).append(snap)
    names = set(baseline.get("tournament_names", [])) | set(tournaments.values())
    baseline["tournament_names"] = sorted(n for n in names if n)

    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)
    print(f"\nAppended snapshot '{args.label}' ({args.date}) to {os.path.basename(baseline_path)}")

    if args.md_dir:
        write_weekly_md(args.md_dir, snap, baseline, cs["name"], era)


if __name__ == "__main__":
    main()
