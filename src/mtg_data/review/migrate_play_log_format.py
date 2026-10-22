#!/usr/bin/env python3
"""
migrate_play_log_format.py — stamp `format` onto every ledger row.

Why
---
`play_log.jsonl` had no format field, and `play_profile.resolve_dir` sorts the
insights notes by format. So 29 Historic games and 12 Standard games rolled up
into one Standard profile: "Golgari Yawgmoth vs Goblin Charbelcher, 4 games"
sat in the folder a Standard question reads, and a deck recommendation for a
Standard weekend could pick a deck that isn't Standard-legal.

The `era` field already carried the answer (`historic-2026-08` against
`the-hobbit-post-ban-2026-08-10`). Nothing partitioned on it. This writes the
inference down once so nothing has to re-derive it.

What it does not do
-------------------
It does not move rows between folders. Splitting a play history across two
ledgers is a decision about someone's own records, and `play_profile.py`
already sets the other format's rows aside and says how to roll them up. Run
that first and see what it reports.

Usage
-----
    python mtg.py migrate-play-log-format --dry-run     # print the diff, write nothing
    python mtg.py migrate-play-log-format               # migrate, keeping a backup
    python mtg.py migrate-play-log-format --format Standard --ledger path/to/play_log.jsonl

Exit codes: 0 nothing to do, 1 could not run, 2 rows were changed (or would be).
"""
import argparse
import collections
import json
import os
import shutil
import sys

from mtg_data.core.paths import CONFIG_DIR
from mtg_data.review import play_profile

BACKUP_SUFFIX = ".pre-format.jsonl"


def default_format():
    try:
        with open(os.path.join(CONFIG_DIR, "mtg_config.json"), encoding="utf-8") as fh:
            return json.load(fh).get("format", "Standard")
    except (OSError, ValueError):
        return "Standard"


def read_lines(path):
    """Raw lines, so a row that fails validation is still migrated rather than lost."""
    with open(path, encoding="utf-8") as fh:
        return fh.readlines()


def plan(lines, fmt):
    """[(line_no, row, resolved_format, action)] plus the untouched raw lines."""
    out = []
    for line_no, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text or text.startswith("//"):
            out.append((line_no, None, None, "skip"))
            continue
        try:
            row = json.loads(text)
        except ValueError:
            # Not this script's job to fix. Report it and leave the line alone,
            # byte for byte: a migration that rewrites a line it can't parse is
            # how a ledger loses a game.
            out.append((line_no, None, None, "unparseable"))
            continue
        if (row.get("format") or "").strip():
            out.append((line_no, row, row["format"], "already"))
            continue
        resolved = play_profile.row_format(row, fmt)
        out.append((line_no, row, resolved, "stamp"))
    return out


def apply(lines, steps):
    """Rewrite only the lines being stamped. Everything else passes through."""
    out = list(lines)
    for line_no, row, resolved, action in steps:
        if action != "stamp":
            continue
        # Rebuild in schema order so the file stays readable by eye, with
        # `format` next to `era` because that is what it was inferred from.
        ordered = {}
        for key in ("date", "session_id", "match_id", "source", "era", "format"):
            if key == "format":
                ordered["format"] = resolved
            elif key in row:
                ordered[key] = row[key]
        for key, value in row.items():
            if key not in ordered:
                ordered[key] = value
        out[line_no - 1] = json.dumps(ordered, ensure_ascii=False) + "\n"
    return out


def main():
    p = argparse.ArgumentParser(description="Stamp `format` onto play_log.jsonl rows.")
    p.add_argument("--format", default=None,
                   help="Fallback format for rows whose era says nothing.")
    p.add_argument("--ledger", default=None, help="Path to play_log.jsonl.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would change and write nothing.")
    args = p.parse_args()

    fmt = args.format or default_format()
    ledger = args.ledger or os.path.join(play_profile.resolve_dir(fmt),
                                         play_profile.LEDGER_NAME)
    if not os.path.exists(ledger):
        print("No ledger at %s" % ledger)
        return 1
    try:
        lines = read_lines(ledger)
    except OSError as exc:
        print("Could not read %s: %s" % (ledger, exc))
        print("On OneDrive a cloud-only placeholder raises this while still "
              "listing in the folder. Open the file once to hydrate it.")
        return 1

    steps = plan(lines, fmt)
    stamping = [s for s in steps if s[3] == "stamp"]
    already = [s for s in steps if s[3] == "already"]
    broken = [s for s in steps if s[3] == "unparseable"]

    print("Ledger: %s" % ledger)
    print("  %d row(s) already carry a format" % len(already))
    print("  %d row(s) to stamp" % len(stamping))
    if broken:
        print("  %d line(s) could not be parsed and are left exactly as they are: %s"
              % (len(broken), ", ".join(str(s[0]) for s in broken)))

    if stamping:
        by_fmt = collections.Counter(s[2] for s in stamping)
        print()
        for resolved, n in sorted(by_fmt.items()):
            eras = collections.Counter(
                (s[1].get("era") or "(no era)") for s in stamping if s[2] == resolved)
            decks = collections.Counter(
                (s[1].get("your_deck") or "?") for s in stamping if s[2] == resolved)
            print("  %-10s %3d game(s)" % (resolved, n))
            print("     from era: %s" % ", ".join("%s x%d" % kv for kv in eras.most_common()))
            print("     decks:    %s" % ", ".join("%s x%d" % kv for kv in decks.most_common()))
        print()
        print("  Format is inferred from the era slug, falling back to %s." % fmt)

    if not stamping:
        print("\nNothing to do.")
        return 0

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 2

    backup = ledger[:-len(".jsonl")] + BACKUP_SUFFIX
    shutil.copy2(ledger, backup)
    with open(ledger, "w", encoding="utf-8") as fh:
        fh.writelines(apply(lines, steps))
    print("\nStamped %d row(s)." % len(stamping))
    print("  previous version kept at %s" % os.path.basename(backup))
    print("  run `python mtg.py play-profile --validate` to check the result")
    return 2


if __name__ == "__main__":
    sys.exit(main())
