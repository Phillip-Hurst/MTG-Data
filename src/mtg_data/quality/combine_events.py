#!/usr/bin/env python3
"""
combine_events.py — the one writer of melee_<fmt>_all_*.csv.

The 2026-09-08 failure
----------------------
Three scripts wrote the combined CSVs, each with a different definition of
what belonged in them:

  melee_scraper.rebuild_all_csv      rebuilt from the per-event glob, deduped,
                                     no verdict filter
  validate_events.rewrite_combined   read the combined file, filtered it, and
                                     wrote it back over itself
  winrate_analysis.rebuild_all_pairings
                                     rebuilt from the per-event glob, no dedupe
                                     and no verdict filter

So the pool depended on which script ran last, and `event_quarantine_<fmt>.json`
stayed dated, in-era and post-scrape either way. The skill's hard rule 3 ("check
the pool before quoting a number") passed while the file it guards had changed
definition underneath it.

The in-place filter was the worse half. It read the combined file, dropped rows,
and wrote the result back, so every run filtered an already-filtered file. Rows
could leave and could never come back. `melee_standard_all_standings.csv` went
553 rows in August to 312 to 241 while 27 per-event files sat on disk, and
build_baseline.py — the meta share table and the 1.19.0 honest-delta machinery —
reads only that file. The `.raw.csv` safety net was written under
`if not os.path.isfile(raw)`, so it froze on the first run and was 11 days stale
by the time anyone looked.

The rule this module enforces
-----------------------------
**The combined CSVs are derived.** They are rebuilt from the per-event files on
disk every time, with the quarantine's verdicts applied at rebuild time, and
nothing ever filters them in place. Deleting one costs a rebuild, not a
recovery.

Per-event files are the source of truth because they are what the scraper
writes, they carry a tournament_id in the filename, and quarantining renames
them rather than deleting them (see validate_events.quarantine_event_files).
Both live and `*.quarantined.csv` files are read here: the verdict decides what
survives, not the filename, so a verdict that reverses puts an event back.

Guardrails this satisfies (see [C] Script Guardrails.md)
--------------------------------------------------------
  1  an event with no verdict is counted and reported, never waved through
     silently
  2  an unreadable file is recorded and reported, never mistaken for an empty
     one; OneDrive cloud-only placeholders raise OSError here
  3  every downstream reader was checked before this landed
  4  idempotent by construction — the output depends only on the per-event
     files and the verdicts, never on the previous output
 11  the previous combined file is copied to `*.pre-rebuild.csv` on every run
     and the path is printed
 12  what was dropped is counted, printed, and written to a coverage sidecar

Usage
-----
    python mtg.py combine-events                    # rebuild both, current format
    python mtg.py combine-events --format Modern
    python mtg.py combine-events --dry-run          # report only, write nothing

Exit codes: 0 clean, 1 could not run, 2 ran with something worth reading
(unreadable files, or events with no verdict).
"""
import argparse
import csv
import glob
import io
import json
import os
import shutil
import sys
from datetime import datetime
from mtg_data.core.paths import CONFIG_DIR, ROOT_DIR, resolve_data_dir


# Verdicts that take an event out of the pool. Everything else is kept:
# "ok" passes both tests, "unverified" has too few cached decklists to judge
# and is kept flagged, and "seat" keeps only the clean seat inside a
# mixed-format event.
DROP_VERDICTS = frozenset({"off-format", "pre-era", "variant"})

PAIRING_FIELDS = [
    "tournament_id", "tournament_name", "round", "table_num",
    "player1", "player1_deck", "player1_deck_url",
    "player2", "player2_deck", "player2_deck_url",
    "result", "winner",
]
STANDING_FIELDS = [
    "tournament_id", "tournament_name", "round",
    "rank", "player", "deck_name", "deck_url",
    "match_record", "game_record", "points",
    "omw_pct", "tgw_pct", "ogw_pct",
]

# A re-scraped tournament must not double its rows.
DEDUPE_KEYS = {
    "pairings":  ("tournament_id", "round", "table_num", "player1", "player2"),
    "standings": ("tournament_id", "round", "player"),
}
FIELDS = {"pairings": PAIRING_FIELDS, "standings": STANDING_FIELDS}


def combined_path(data_dir, fmt, kind):
    return os.path.join(data_dir, f"melee_{fmt.lower()}_all_{kind}.csv")


def coverage_path(data_dir, fmt):
    return os.path.join(data_dir, f"melee_{fmt.lower()}_all_coverage.json")


def quarantine_path(data_dir, fmt):
    return os.path.join(data_dir, f"event_quarantine_{fmt.lower()}.json")


def _event_files(data_dir, fmt, kind):
    """
    Per-event CSVs for one format and kind, live and quarantined alike.

    Returns [(tournament_id, path, is_quarantined)], sorted by id so the output
    row order is stable across runs. A stable order is what makes "the second
    run produced an identical file" a check a person can actually run.
    """
    slug = fmt.lower()
    found = {}
    for path in glob.glob(os.path.join(data_dir, f"melee_{slug}_*_{kind}.csv")) + \
            glob.glob(os.path.join(data_dir, f"melee_{slug}_*_{kind}.quarantined.csv")):
        base = os.path.basename(path)
        if "_all_" in base or base.endswith(".raw.csv") or base.endswith(".pre-rebuild.csv"):
            continue
        quarantined = base.endswith(".quarantined.csv")
        stem = base[:-len(".quarantined.csv")] if quarantined else base[:-len(".csv")]
        # melee_<slug>_<id>_<kind>
        parts = stem.split("_")
        if len(parts) < 4 or parts[-1] != kind:
            continue
        tid = parts[-2]
        if not tid.isdigit():
            continue
        # A live file wins over a quarantined one for the same id: the rename
        # is the quarantine, so both existing means a verdict reversed and the
        # live copy is the current one.
        if tid in found and not found[tid][1]:
            continue
        found[tid] = (path, quarantined)
    return [(tid, p, q) for tid, (p, q) in sorted(found.items())]


def load_verdicts(data_dir, fmt):
    """
    tournament_id -> verdict record, from the quarantine file.

    Returns (verdicts, path_or_None). A missing quarantine file is not an
    error: a fresh scrape has none yet. It is reported, and every event then
    counts as unjudged.
    """
    path = quarantine_path(data_dir, fmt)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}, None
    verdicts = {}
    for rec in data.get("events", []):
        tid = str(rec.get("tournament_id") or "").strip()
        if tid:
            verdicts[tid] = rec
    return verdicts, path


def _keep_row(row, kind, verdict_rec):
    """Seat filtering. An event with no seat restriction keeps every row."""
    if not verdict_rec or verdict_rec.get("verdict") != "seat":
        return True
    keep = set(verdict_rec.get("keep_players") or [])
    if kind == "pairings":
        p1 = (row.get("player1") or "").strip()
        p2 = (row.get("player2") or "").strip()
        # Both seats must be in-format. A cross-format pairing means the
        # labelling is wrong, not that the match happened.
        return p1 in keep and (not p2 or p2 in keep)
    return (row.get("player") or "").strip() in keep


def rebuild(data_dir, fmt, kind, verdicts=None, dry_run=False, quiet=False,
            allow_partial=False):
    """
    Rebuild one combined CSV from the per-event files. Returns a summary dict.

    Never reads the file it writes. That is the whole point: the output is a
    function of the per-event files and the verdicts, so running it twice
    produces the same bytes and running it after a bad run repairs the file
    instead of compounding it.

    `verdicts=None` loads them from the quarantine file rather than defaulting
    to "no verdicts". An empty dict is the unfiltered pool, and that has to be
    something a caller asks for on purpose: it's how a scrape used to put a
    quarantined event straight back into the pool.
    """
    if verdicts is None:
        verdicts, _ = load_verdicts(data_dir, fmt)
    fields, dedupe_keys = FIELDS[kind], DEDUPE_KEYS[kind]
    out_path = combined_path(data_dir, fmt, kind)

    seen, combined = set(), []
    unreadable, dropped, unjudged, seat_trimmed = [], {}, [], {}
    events_in, events_out = 0, set()
    rows_dropped = 0

    for tid, path, _quarantined in _event_files(data_dir, fmt, kind):
        events_in += 1
        rec = verdicts.get(tid)
        if rec is None:
            unjudged.append(tid)
        verdict = (rec or {}).get("verdict")
        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except OSError as e:
            # An unreadable file is not a clean file. OneDrive cloud-only
            # placeholders land here, and returning [] would quietly shrink
            # the pool by a whole event.
            unreadable.append((os.path.basename(path), str(e)))
            continue
        if verdict in DROP_VERDICTS:
            # Read it anyway, so "removed" is a real count rather than a
            # number of files. A filter that can't say how much it removed
            # can't be checked.
            dropped[tid] = verdict
            rows_dropped += len(rows)
            continue
        trimmed = 0
        for row in rows:
            if not _keep_row(row, kind, rec):
                trimmed += 1
                continue
            key = tuple((row.get(k) or "").strip() for k in dedupe_keys)
            if key in seen:
                continue
            seen.add(key)
            combined.append(row)
            events_out.add(tid)
        if trimmed:
            seat_trimmed[tid] = trimmed

    trimmed_rows = sum(seat_trimmed.values())
    summary = {
        "kind": kind,
        "path": out_path,
        "rows": len(combined),
        "rows_dropped_by_verdict": rows_dropped,
        "rows_seat_trimmed": trimmed_rows,
        # Rows the per-event files offered this run, before any filtering.
        # Stable across runs, which is what makes the removed count checkable;
        # the old in-place filter reported a delta against its own last output.
        "rows_available": len(combined) + rows_dropped + trimmed_rows,
        "events_in": events_in,
        "events_kept": len(events_out),
        "dropped_by_verdict": dropped,
        "seat_trimmed_rows": seat_trimmed,
        "unjudged_events": unjudged,
        "unreadable_files": unreadable,
        "backup": None,
        "previous_rows": None,
        "refused": False,
        "unchanged": False,
    }

    # What the file held before this run, so a surprise can be spotted.
    try:
        with open(out_path, newline="", encoding="utf-8") as f:
            summary["previous_rows"] = sum(1 for _ in csv.DictReader(f))
    except OSError:
        summary["previous_rows"] = None

    # Fail closed. A file that couldn't be read is an event's worth of rows
    # missing, and writing the smaller pool anyway would hand every consumer a
    # quietly shorter answer. The loud message is not enough on its own: a
    # warning above a written file still leaves the written file in place.
    #
    # This is the OneDrive case. Cloud-only placeholders raise OSError, so an
    # unhydrated folder would otherwise trim real events out of the pool on the
    # next run of anything.
    if unreadable and not allow_partial:
        summary["refused"] = True

    if dry_run or summary["refused"]:
        # A dry run that prints nothing is indistinguishable from one that
        # found nothing. Report first, then decline to write.
        if not quiet:
            _print_summary(summary)
        return summary

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore",
                       lineterminator="\r\n")
    w.writeheader()
    w.writerows(combined)
    text = buf.getvalue()

    # An identical rebuild must not touch the file. build_baseline.py refuses
    # to publish a snapshot when the standings file is newer than the last
    # validation, and a no-op write that bumps mtime would trip that guard on
    # every run of anything. Idempotent has to mean the file too, not just the
    # bytes we would have written.
    try:
        with open(out_path, newline="", encoding="utf-8") as f:
            if f.read() == text:
                summary["unchanged"] = True
                if not quiet:
                    _print_summary(summary)
                return summary
    except OSError:
        pass

    if os.path.isfile(out_path):
        backup = out_path[:-len(".csv")] + ".pre-rebuild.csv"
        try:
            shutil.copy2(out_path, backup)
            summary["backup"] = backup
        except OSError as e:
            unreadable.append((os.path.basename(out_path), f"backup failed: {e}"))

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        f.write(text)

    if not quiet:
        _print_summary(summary)
    return summary


def _print_summary(s):
    prev = s["previous_rows"]
    delta = "" if prev is None else f"  (file held {prev})"
    print(f"  {os.path.basename(s['path'])}: {s['rows']} of "
          f"{s['rows_available']} available rows{delta}, "
          f"from {s['events_kept']} of {s['events_in']} events")
    if s["dropped_by_verdict"]:
        by = {}
        for tid, v in s["dropped_by_verdict"].items():
            by.setdefault(v, []).append(tid)
        for v, ids in sorted(by.items()):
            print(f"    dropped {len(ids)} event(s) as {v}: {', '.join(sorted(ids))}")
    if s["seat_trimmed_rows"]:
        n = sum(s["seat_trimmed_rows"].values())
        print(f"    seat filter removed {n} row(s) from "
              f"{len(s['seat_trimmed_rows'])} mixed-format event(s)")
    if s["unjudged_events"]:
        print(f"    {len(s['unjudged_events'])} event(s) have no verdict and were "
              f"kept unjudged: {', '.join(sorted(s['unjudged_events']))}")
        print("      run python mtg.py validate-events to judge them")
    if s["unreadable_files"]:
        print(f"    ! {len(s['unreadable_files'])} file(s) could not be read and "
              f"contributed nothing:")
        for name, err in s["unreadable_files"]:
            print(f"        {name}: {err}")
        print("      on OneDrive these are cloud-only placeholders. Mark the data "
              "folder 'Always keep on this device'.")
    if s["refused"]:
        print(f"    REFUSED to write {os.path.basename(s['path'])}: rebuilding now "
              "would drop the events in those files.")
        print("      the existing file is untouched. Hydrate them and re-run, or "
              "pass --allow-partial to accept the smaller pool.")
    if s["unchanged"]:
        print("    unchanged, so the file was not rewritten")
    if s["backup"]:
        print(f"    previous version kept at {os.path.basename(s['backup'])}")


def rebuild_all(data_dir, fmt, verdicts=None, dry_run=False, quiet=False,
                allow_partial=False):
    """
    Rebuild both combined CSVs and write the coverage sidecar.

    Returns {"pairings": summary, "standings": summary, "coverage": path|None}.
    """
    if verdicts is None:
        verdicts, qpath = load_verdicts(data_dir, fmt)
        if qpath is None and not quiet:
            print("  (no event_quarantine file — every event counts as unjudged)")
    out = {}
    for kind in ("pairings", "standings"):
        out[kind] = rebuild(data_dir, fmt, kind, verdicts=verdicts,
                            dry_run=dry_run, quiet=quiet,
                            allow_partial=allow_partial)
    refused = any(out[k]["refused"] for k in ("pairings", "standings"))
    # The sidecar describes the pool on disk. Writing it after a refusal would
    # describe a pool that was never written.
    out["coverage"] = None if (dry_run or refused) else write_coverage(data_dir, fmt, out)
    return out


def load_pool(data_dir, fmt, kind, refresh=True, resolve_names=False):
    """
    The validated pool for one kind, as rows. Returns (rows, summary).

    `resolve_names=True` also runs the pairing rows through
    `deck_labels.resolve_pairing_decks`, so a consumer gets names in the
    classifier's vocabulary rather than whatever the organizer typed. The
    resolver's counts land on `summary["label_stats"]`, and callers are
    expected to print them: a matrix built mostly on organizer text should say
    so.

    Every consumer should read the pool through here rather than globbing the
    per-event files itself. Globbing skips the seat filter, so a mixed-format
    event's cross-format pairings reach the win-rate math even after the
    validator has ruled on them — a match between a Standard player and a
    Modern player in a team event never happened as a Standard match.

    `refresh=True` rebuilds first, so the pool is never staler than the files
    on disk. That is cheap (a few hundred KB) and it removes the class of bug
    where a consumer reports numbers from whatever the last script left behind.
    """
    summary = rebuild(data_dir, fmt, kind, quiet=True) if refresh else None
    path = combined_path(data_dir, fmt, kind)
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        raise SystemExit(f"Could not read the {kind} pool at {path}: {e}")
    if summary is not None:
        # What the caller actually got. After a refusal that's the file already
        # on disk, which is a different pool from the one the rebuild would
        # have written, and a consumer printing the wrong one is the whole
        # class of bug this module exists to close.
        summary["loaded_rows"] = len(rows)

    if resolve_names and kind == "pairings":
        from mtg_data.classify import deck_labels  # local: keeps the pool loader importable on its own
        rows, label_stats = deck_labels.resolve_pairing_decks(rows, data_dir=data_dir)
        if summary is not None:
            summary["label_stats"] = label_stats
    return rows, summary


def describe_pool(summary):
    """One line a consumer can print so a reader knows what the pool was."""
    if not summary:
        return ""
    loaded = summary.get("loaded_rows", summary["rows"])
    bits = [f"{loaded} rows from {summary['events_kept']} events"]
    if summary["refused"]:
        bits = [f"{loaded} rows from the existing file — REBUILD REFUSED, so this "
                f"is not the {summary['rows']} rows the per-event files hold"]
    if summary["dropped_by_verdict"]:
        bits.append(f"{len(summary['dropped_by_verdict'])} event(s) quarantined")
    if summary["rows_seat_trimmed"]:
        bits.append(f"{summary['rows_seat_trimmed']} row(s) seat-trimmed")
    if summary["unjudged_events"]:
        bits.append(f"{len(summary['unjudged_events'])} event(s) unjudged")
    if summary["unreadable_files"]:
        bits.append(f"{len(summary['unreadable_files'])} file(s) UNREADABLE")
    return "; ".join(bits)


def write_coverage(data_dir, fmt, summaries):
    """
    Say in a file which events are in the pool and which aren't.

    A CSV can't carry a note about what's missing from it, and "how many events
    is this number built on" is the question every published snapshot needs to
    answer. build_baseline.py already records event_ids per snapshot; this is
    the same idea one level down, at the file the snapshot is built from.
    """
    path = coverage_path(data_dir, fmt)
    payload = {
        "rebuilt": datetime.now().isoformat(timespec="seconds"),
        "format": fmt,
        "note": "Derived file. Rebuilt from the per-event CSVs by "
                "combine_events.py; never edited in place.",
    }
    for kind in ("pairings", "standings"):
        s = summaries[kind]
        payload[kind] = {
            "rows": s["rows"],
            "rows_available": s["rows_available"],
            "rows_dropped_by_verdict": s["rows_dropped_by_verdict"],
            "rows_seat_trimmed": s["rows_seat_trimmed"],
            "events_in_folder": s["events_in"],
            "events_kept": s["events_kept"],
            "dropped_by_verdict": s["dropped_by_verdict"],
            "unjudged_events": sorted(s["unjudged_events"]),
            "unreadable_files": [n for n, _ in s["unreadable_files"]],
            "seat_trimmed_rows": s["seat_trimmed_rows"],
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    return path


def _exit_code(summaries):
    for kind in ("pairings", "standings"):
        s = summaries[kind]
        if s["refused"] or s["unreadable_files"] or s["unjudged_events"]:
            return 2
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Rebuild the combined melee CSVs from the per-event files.")
    p.add_argument("--format", default=None, help="Format. Overrides mtg_config.json.")
    p.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    p.add_argument("--allow-partial", action="store_true",
                   help="Write even though some per-event files could not be read. "
                        "Accepts a pool missing those events.")
    args = p.parse_args()

    fmt = args.format
    if not fmt:
        try:
            with open(os.path.join(CONFIG_DIR, "mtg_config.json"), encoding="utf-8") as f:
                fmt = json.load(f).get("format", "Standard")
        except (OSError, ValueError):
            fmt = "Standard"

    data_dir = resolve_data_dir(fmt, ROOT_DIR)

    print(f"Rebuilding combined CSVs for {fmt} from {data_dir}")
    summaries = rebuild_all(data_dir, fmt, dry_run=args.dry_run,
                            allow_partial=args.allow_partial)
    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0
    if summaries["coverage"]:
        print(f"\nCoverage written to {os.path.basename(summaries['coverage'])}")
    else:
        print("\nNothing written. Fix the unreadable files above, or re-run with "
              "--allow-partial.")
    return _exit_code(summaries)


if __name__ == "__main__":
    sys.exit(main())
