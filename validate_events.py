#!/usr/bin/env python3
"""
validate_events.py — check every scraped event actually belongs in this pool.

The 2026-08-27 failure
----------------------
mtg_fetch.py logged "Window start: 2026-08-10 — post-ban" and then scraped
Sydney Standard Spectacular 100K (660 matches, pre-ban) and NRG Series $10k
Team Trios (184 matches, Modern). Both landed in melee_standard_all_*.csv,
build_baseline.py averaged them in, and the weekly snapshot reported Izzet
Prowess at 6.8% in a note headed "post-ban era" — 17 days after Stormchaser's
Talent was banned.

The scraper trusted melee's tournament index. This script trusts the cards.

Two tests, both run against the cached decklists rather than deck names,
because "Dimir Midrange" is a real deck in three different formats:

  format purity — what share of an event's decks are built entirely from
                  cards legal in the target format (card_pool_<fmt>.json)
  era purity    — what share contain a card banned as of the window start

Verdicts
--------
  ok            passes both tests
  off-format    too few decks are legal in the target format
  pre-era       too many decks run cards banned at the window start
  variant       a variant format on the same card pool (Artisan, Pauper,
                Brawl) — the cards pass, the metagame isn't this one
  seat          mixed-format event, but a clean single-format seat exists
                inside it and per-player results are published, so that
                seat's matches are kept and the rest dropped
  unverified    not enough cached decklists to judge — kept, but flagged

Effect
------
Writes event_quarantine.json, then rewrites melee_<fmt>_all_pairings.csv and
melee_<fmt>_all_standings.csv from the surviving events only. The originals
are preserved as *.raw.csv. Nothing is deleted; a quarantined event's own
per-event CSVs stay on disk so a verdict can be reviewed and overridden.

Usage
-----
    python validate_events.py                  # validate and rewrite
    python validate_events.py --dry-run        # report only
    python validate_events.py --since 2026-08-10
    python validate_events.py --allow 437430   # force-keep an event

Exit codes: 0 clean, 2 something was quarantined, 1 could not run.
"""
import argparse
import csv
import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from mtg_paths import resolve_data_dir  # noqa: E402
import build_card_pool  # noqa: E402
import mtg_era  # noqa: E402

# A deck counts as legal if this share of its distinct mainboard cards sit in
# the format's card pool. Not 100%: melee decklists carry the odd typo, and a
# brand-new set can land on melee a day before Scryfall's legality flips.
DECK_LEGAL_THRESHOLD = 0.95
# An event is off-format if fewer than this share of its cached decks are legal.
EVENT_LEGAL_THRESHOLD = 0.50
# An event is pre-era if at least this share of its cached decks run a card
# banned as of the window start. One stale list is a player error; a tenth of
# the field is the wrong tournament.
EVENT_BANNED_THRESHOLD = 0.10
# Below this many cached decklists there isn't enough evidence to judge.
MIN_DECKS_TO_JUDGE = 5
# A salvageable seat needs at least this many clean decks to be worth keeping.
MIN_SEAT_DECKS = 8

EVENT_CSV_RE = re.compile(r"^melee_(?:[a-z0-9-]+_)?(\d+)_(pairings|standings)\.csv$", re.IGNORECASE)

# melee.gg's own demo and QA tournaments show up in the public index with real
# pairings. They are not tournaments. "How it works" and "Melee Mobile build 40
# test" both landed in the 2026-08-27 Standard pool.
DEMO_EVENT_RE = re.compile(
    r"how it works|melee mobile|build \d+ test|\bsandbox\b|\bdemo\b|\btest event\b|"
    r"^enjoy yourself|^startuem",
    re.IGNORECASE,
)

# Variant formats built on the same card pool. Every card in a Standard Artisan
# deck is Standard-legal, so the card test passes them, but a commons-and-
# uncommons field is not the Standard metagame. After the 2026-08-27 cleanup,
# "Welcome to the Standard Artisan Cup" was the single largest surviving event
# at 16% of the pool, which would have skewed every share in the snapshot.
VARIANT_EVENT_RE = re.compile(
    r"\bartisan\b|\bpauper\b|\bpeasant\b|\bsingleton\b|\bbrawl\b|\bplanar\b|"
    r"\bbudget\b|\bblock\b|\bpandemonium\b|\bpre-?release\b",
    re.IGNORECASE,
)


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


def load_deck_cache(data_dir):
    for cand in (os.path.join(data_dir, "melee_deck_cache.json"),
                 os.path.join(SCRIPT_DIR, "melee_deck_cache.json")):
        if os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
    return {}


def banned_as_of(fmt, cutoff_dt):
    """Every card banned in this format on or before the window start.

    mtg_era.load_bans returns (datetime, announcement) pairs, newest first.
    """
    banned = set()
    for eff, ann in mtg_era.load_bans(fmt):
        if cutoff_dt and eff > cutoff_dt:
            continue
        for card in ann.get("banned", []):
            banned.add(str(card).strip().lower())
    return banned


def deck_names(entry):
    """Distinct lowercase card names in a cached decklist's mainboard."""
    mb = entry.get("mainboard") or {}
    if isinstance(mb, dict):
        names = list(mb.keys())
    else:
        names = list(mb)
    return {str(n).strip().lower() for n in names if str(n).strip()}


def judge_deck(cards, pool, banned):
    """Return (is_legal, runs_banned_card, offending_cards)."""
    if not cards:
        return None, False, []
    hits = sorted(cards & banned)
    if pool is None:
        return None, bool(hits), hits
    off = sorted(cards - pool)
    legal_share = 1.0 - (len(off) / len(cards))
    return legal_share >= DECK_LEGAL_THRESHOLD, bool(hits), (hits or off[:6])


def event_players(pairings_rows):
    """player -> decklist url, from an event's pairing rows."""
    out = {}
    for r in pairings_rows:
        for who, url_key in (("player1", "player1_deck_url"), ("player2", "player2_deck_url")):
            name = (r.get(who) or "").strip()
            url = (r.get(url_key) or "").strip()
            if name and url:
                out.setdefault(name, url)
    return out


def has_individual_results(pairings_rows):
    """
    True when the event publishes per-player match results.

    A team event that only reports the team's result is unusable: there's no
    way to know which seat won. One that reports each seat's own match can be
    split back apart.
    """
    for r in pairings_rows:
        if (r.get("winner") or "").strip() and (r.get("player2") or "").strip():
            return True
    return False


def validate_event(tid, name, pairings_rows, cache, pool, banned):
    players = event_players(pairings_rows)
    legal, illegal, banned_players, unknown = [], [], [], []
    samples = {}
    for player, url in players.items():
        entry = cache.get(url)
        if not entry:
            unknown.append(player)
            continue
        cards = deck_names(entry)
        is_legal, runs_banned, offenders = judge_deck(cards, pool, banned)
        if is_legal is None:
            unknown.append(player)
            continue
        if runs_banned:
            banned_players.append(player)
        (legal if is_legal else illegal).append(player)
        if offenders and len(samples) < 8:
            samples[player] = offenders

    judged = len(legal) + len(illegal)
    rec = {
        "tournament_id": tid,
        "tournament_name": name,
        "players": len(players),
        "decks_cached": judged,
        "legal_decks": len(legal),
        "illegal_decks": len(illegal),
        "banned_card_decks": len(banned_players),
        "sample_offenders": samples,
    }

    if DEMO_EVENT_RE.search(name or ""):
        rec["verdict"] = "off-format"
        rec["reason"] = "melee demo or QA event, not a real tournament"
        return rec

    if VARIANT_EVENT_RE.search(name or ""):
        rec["verdict"] = "variant"
        rec["reason"] = ("variant format built on the same card pool (Artisan, Pauper, "
                         "Brawl and friends) — legal cards, but not this format's metagame")
        return rec

    if judged < MIN_DECKS_TO_JUDGE:
        rec["verdict"] = "unverified"
        rec["reason"] = (f"only {judged} decklists cached, need {MIN_DECKS_TO_JUDGE}. "
                         "Kept, but do not treat as confirmed.")
        return rec

    legal_share = len(legal) / judged
    banned_share = len(banned_players) / judged
    rec["legal_share"] = round(legal_share, 3)
    rec["banned_share"] = round(banned_share, 3)

    if legal_share < EVENT_LEGAL_THRESHOLD:
        # Mixed-format or wrong-format. Can a clean seat be salvaged?
        if len(legal) >= MIN_SEAT_DECKS and has_individual_results(pairings_rows):
            rec["verdict"] = "seat"
            rec["keep_players"] = sorted(legal)
            rec["reason"] = (f"{len(legal)} of {judged} decks are {pool and 'in-format' or 'clean'}; "
                             "per-player results are published, so that seat is kept and "
                             "the rest of the event dropped.")
        else:
            rec["verdict"] = "off-format"
            why = (f"only {legal_share:.0%} of decks are legal in this format")
            if len(legal) >= MIN_SEAT_DECKS:
                why += ", and no per-player results to split seats apart"
            elif has_individual_results(pairings_rows):
                why += f", and the in-format seat is only {len(legal)} decks"
            rec["reason"] = why
        return rec

    if banned_share >= EVENT_BANNED_THRESHOLD:
        rec["verdict"] = "pre-era"
        rec["reason"] = (f"{banned_share:.0%} of decks run a card banned as of the window start "
                         "— this event predates the current era")
        return rec

    rec["verdict"] = "ok"
    return rec


UNREADABLE = []


def read_csv(path):
    """
    Read a CSV, recording anything that couldn't be opened.

    A file that can't be read must not be mistaken for a file with nothing
    wrong in it. OneDrive placeholders and locked files both surface as OSError
    here, and silently returning [] would let an unjudged event keep its
    per-event CSV visible to the matchup matrix.
    """
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError as e:
        UNREADABLE.append((os.path.basename(path), str(e)))
        return []


def combined_path(data_dir, fmt, kind):
    return os.path.join(data_dir, f"melee_{fmt.lower()}_all_{kind}.csv")


def discover_events(data_dir, fmt):
    """
    tournament_id -> list of pairing rows, from every source on disk.

    Both sources have to be read, because two different consumers read two
    different files: build_baseline.py reads the combined CSV, while
    matchup_matrix.py and winrate_analysis.py glob the per-event CSVs and
    explicitly skip the combined one.

    Reading only the combined file also makes validation non-idempotent. After
    the first clean pass the bad events are gone from it, so a second run sees
    nothing wrong and never renames the per-event files — leaving a quarantined
    event invisible to the snapshot and fully visible to the matchup matrix.
    Already-quarantined files are included too, so a verdict that reverses can
    put them back.
    """
    events = {}

    def absorb(rows):
        for r in rows:
            tid = (r.get("tournament_id") or "").strip()
            if tid:
                events.setdefault(tid, []).append(r)

    absorb(read_csv(combined_path(data_dir, fmt, "pairings")))

    for path in sorted(glob.glob(os.path.join(data_dir, "melee_*.csv"))):
        base = os.path.basename(path)
        if "_all_" in base or base.endswith(".raw.csv"):
            continue
        stem = base[:-len(".quarantined.csv")] + ".csv" if base.endswith(".quarantined.csv") else base
        m = EVENT_CSV_RE.match(stem)
        if not m or m.group(2).lower() != "pairings":
            continue
        tid = m.group(1)
        if tid in events:
            continue  # already have this event's rows from the combined file
        absorb(read_csv(path))

    return events


def quarantine_event_files(data_dir, fmt, verdicts, dry_run=False):
    """
    Hide quarantined events from the per-event glob, and unhide ones that pass.

    Cleaning the combined CSVs is not enough. matchup_matrix.py and
    winrate_analysis.py glob `melee_*_pairings.csv` and explicitly skip
    `_all_pairings.csv`, so they read the per-event files directly. Without
    this, a quarantined event stays invisible to the snapshot and fully visible
    to the matchup matrix — the worst of both.

    Renaming to `*.quarantined.csv` takes them out of that glob (the pattern
    requires the name to end `_pairings.csv`) without deleting anything.
    """
    drop = {v["tournament_id"] for v in verdicts
            if v["verdict"] in ("off-format", "pre-era", "variant")}
    keep = {v["tournament_id"] for v in verdicts
            if v["verdict"] in ("ok", "seat", "unverified")}
    hidden, restored = [], []

    for path in glob.glob(os.path.join(data_dir, "melee_*.csv")):
        base = os.path.basename(path)
        if "_all_" in base:
            continue
        quarantined = base.endswith(".quarantined.csv")
        stem = base[:-len(".quarantined.csv")] + ".csv" if quarantined else base
        m = EVENT_CSV_RE.match(stem)
        if not m:
            continue
        tid = m.group(1)

        if tid in drop and not quarantined:
            target = path[:-len(".csv")] + ".quarantined.csv"
            if not dry_run:
                try:
                    os.replace(path, target)
                except OSError:
                    continue
            hidden.append(base)
        elif tid in keep and quarantined:
            # A verdict changed (--allow, a corrected era, a refreshed pool).
            target = os.path.join(data_dir, stem)
            if not dry_run:
                try:
                    os.replace(path, target)
                except OSError:
                    continue
            restored.append(base)

    return hidden, restored


def rewrite_combined(data_dir, fmt, verdicts, dry_run=False):
    """Rebuild the combined CSVs from surviving events. Keeps a .raw.csv copy."""
    drop = {v["tournament_id"] for v in verdicts
             if v["verdict"] in ("off-format", "pre-era", "variant")}
    seats = {v["tournament_id"]: set(v.get("keep_players", []))
             for v in verdicts if v["verdict"] == "seat"}
    summary = {}
    for kind in ("pairings", "standings"):
        path = os.path.join(data_dir, f"melee_{fmt.lower()}_all_{kind}.csv")
        if not os.path.isfile(path):
            continue
        rows = read_csv(path)
        if not rows:
            continue
        kept = []
        for r in rows:
            tid = (r.get("tournament_id") or "").strip()
            if tid in drop:
                continue
            if tid in seats:
                keep = seats[tid]
                if kind == "pairings":
                    p1 = (r.get("player1") or "").strip()
                    p2 = (r.get("player2") or "").strip()
                    # Both seats must be in-format; a cross-format pairing means
                    # the labelling is wrong, not that the match happened.
                    if p1 not in keep or (p2 and p2 not in keep):
                        continue
                else:
                    if (r.get("player") or "").strip() not in keep:
                        continue
            kept.append(r)
        summary[kind] = {"before": len(rows), "after": len(kept), "removed": len(rows) - len(kept)}
        if dry_run:
            continue
        raw = path.replace(".csv", ".raw.csv")
        if not os.path.isfile(raw):
            shutil.copy2(path, raw)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(kept)
    return summary


# ── source caches ─────────────────────────────────────────────────────────────
#
# The CSVs are not the only thing an analysis reads, and for a long time they
# were the only thing this script cleaned.
#
# Found 2026-08-30, and it is the same shape as every other data bug here: every
# consumer reads its own file, so cleaning one cleans one. The era split shipped
# on 2026-08-15 and was enforced against the melee CSVs. Meanwhile
# mtgo_classifications.json still held classifications dated 2026-06-03, both
# MTGO dumps still carried events from 2026-08-08 and 08-09 (the era opens
# 08-10), and melee_deck_cache.json still held 71 decks running Badgermole Cub.
# build_refs_from_melee.py works around the dirty cache with a read-time
# era_filter(), which is why the references came out clean and nothing looked
# wrong. The next consumer that reads those files without its own guard inherits
# the whole problem.
#
# Two different tests, because the files carry different information:
#   - the MTGO files have a real event date, so date decides.
#   - melee_deck_cache.json has no event date at all (open problem: discovery
#     knows each event's date and throws it away), so cards decide, using the
#     same judge_deck predicate the event validator and the reference builder
#     already trust.

CACHE_DATE_FILES = {
    # file -> (entries live here, date lives here)
    "mtgo_classifications.json": "mapping",   # {url: {..., "date": "YYYY-MM-DD"}}
    "mtgo_challenge_latest.json": "list",     # [{"date": ..., "decks": [...]}, ...]
    "mtgo_5-0_latest.json": "list",
}


def _archive_dir(data_dir, cutoff):
    """Where removed entries go. Matches archive_era.py's layout on purpose."""
    stamp = cutoff.strftime("%Y-%m-%d") if cutoff else "unknown"
    return os.path.join(data_dir, "archive", f"through-{stamp}")


def _stash(dropped, data_dir, cutoff, filename, dry_run):
    """Park removed entries in the era archive, merging with an earlier run.

    Nothing is deleted. A wrong call here should cost a file move, not a
    rescrape, and the pre-era decks stay readable for cross-era questions.
    """
    if dry_run or not dropped:
        return None
    dest_dir = _archive_dir(data_dir, cutoff)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename.replace(".json", ".pre-era.json"))
    existing = {}
    if os.path.isfile(dest):
        try:
            with open(dest, encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, ValueError):
            existing = {}
    if isinstance(dropped, dict):
        if not isinstance(existing, dict):
            existing = {}
        existing.update(dropped)
        merged = existing
    else:
        merged = (existing if isinstance(existing, list) else []) + list(dropped)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=1, ensure_ascii=False)
    return dest


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        UNREADABLE.append((os.path.basename(path), str(exc)))
        return None


def _write_json(path, data, dry_run):
    """Write, keeping a one-time .bak of whatever was there first."""
    if dry_run:
        return
    bak = path + ".bak"
    if not os.path.isfile(bak) and os.path.isfile(path):
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def _event_runs_banned(entry, banned):
    """Share of an MTGO event's decks that register a card banned in this era.

    An MTGO decklist dump is stamped with its *publication* date, and a league
    dump published on the morning of a ban is a record of games played the week
    before it. The 2026-08-10 Standard League dump is the worked example: three
    of its six lists run Badgermole Cub, which nobody could register that day.

    So the date is evidence and the cards are proof. Where they disagree, the
    cards win. Same reasoning as judging events by decklists instead of by name.
    """
    decks = entry.get("decks") if isinstance(entry, dict) else None
    if not banned or not isinstance(decks, list) or not decks:
        return 0.0
    hits = 0
    for deck in decks:
        if not isinstance(deck, dict):
            continue
        if deck_names(deck) & banned:
            hits += 1
    return hits / len(decks)


def _entry_deck_runs_banned(entry, banned):
    """True when a classification records the *deck* running a banned card.

    `new_cards` is what this deck ran that its reference didn't, so a banned
    card there came off the decklist. `cuts` is the mirror: cards the reference
    has and the deck doesn't, so a banned card there says the reference is
    stale, not that the deck is illegal. Reading `cuts` as deck evidence would
    delete 23 perfectly good post-ban Jeskai Lessons classifications.
    """
    if not banned or not isinstance(entry, dict):
        return False
    for item in (entry.get("new_cards") or []):
        card = item.get("card") if isinstance(item, dict) else item
        if str(card).strip().lower() in banned:
            return True
    return False


def clean_date_cache(path, shape, cutoff, dry_run=False, data_dir=None,
                     banned=None):
    """Drop entries from before the window start, by date and by cards.

    Returns a summary dict, or None when there is nothing to judge against.
    """
    name = os.path.basename(path)
    data = _load_json(path)
    if data is None or cutoff is None:
        return None
    banned = banned or set()

    dropped_dates = []
    by_card = 0
    if shape == "mapping" and isinstance(data, dict):
        kept, dropped = {}, {}
        for key, entry in data.items():
            d = entry.get("date") if isinstance(entry, dict) else None
            parsed = mtg_era.parse_date(d) if d else None
            if parsed and parsed < cutoff:
                dropped[key] = entry
                dropped_dates.append(d)
            elif _entry_deck_runs_banned(entry, banned):
                dropped[key] = entry
                dropped_dates.append(d)
                by_card += 1
            else:
                kept[key] = entry
        before, after = len(data), len(kept)
    elif shape == "list" and isinstance(data, list):
        kept, dropped = [], []
        for entry in data:
            d = entry.get("date") if isinstance(entry, dict) else None
            parsed = mtg_era.parse_date(d) if d else None
            if parsed and parsed < cutoff:
                dropped.append(entry)
                dropped_dates.append(d)
            elif _event_runs_banned(entry, banned) > EVENT_BANNED_THRESHOLD:
                dropped.append(entry)
                dropped_dates.append(d)
                by_card += 1
            else:
                kept.append(entry)
        before, after = len(data), len(kept)
    else:
        return None

    if before != after:
        _stash(dropped, data_dir, cutoff, name, dry_run)
        _write_json(path, kept, dry_run)
    test = "event date before window start"
    if by_card:
        test += ", or decks running a card banned in this era"
    return {
        "file": name,
        "test": test,
        "before": before,
        "after": after,
        "removed": before - after,
        "removed_by_date": (before - after) - by_card,
        "removed_by_banned_cards": by_card,
        "oldest_removed": min(d for d in dropped_dates if d) if any(dropped_dates) else None,
        "newest_removed": max(d for d in dropped_dates if d) if any(dropped_dates) else None,
    }


def clean_deck_cache(path, pool, banned, cutoff, dry_run=False, data_dir=None):
    """Drop cached decks that are off-format or run a card banned in this era.

    Judged on cards because the cache carries no event date. Same predicate as
    judge_deck, so a deck this drops is a deck the event validator would also
    have refused.
    """
    name = os.path.basename(path)
    data = _load_json(path)
    if data is None or not isinstance(data, dict):
        return None
    if pool is None and not banned:
        return {"file": name, "test": "skipped: no card pool and no ban list",
                "before": len(data), "after": len(data), "removed": 0,
                "banned_decks": 0, "off_format_decks": 0}

    kept, dropped = {}, {}
    n_banned = n_off = 0
    for key, entry in data.items():
        if not isinstance(entry, dict) or entry.get("failed"):
            kept[key] = entry
            continue
        cards = deck_names(entry)
        if not cards:
            kept[key] = entry            # nothing to judge; never drop blind
            continue
        legal, runs_banned, _ = judge_deck(cards, pool, banned)
        if runs_banned:
            n_banned += 1
            dropped[key] = entry
        elif legal is False:
            n_off += 1
            dropped[key] = entry
        else:
            kept[key] = entry

    if dropped:
        _stash(dropped, data_dir, cutoff, name, dry_run)
        _write_json(path, kept, dry_run)
    return {
        "file": name,
        "test": "runs a banned card, or under "
                f"{int(DECK_LEGAL_THRESHOLD * 100)}% format-legal",
        "before": len(data),
        "after": len(kept),
        "removed": len(dropped),
        "banned_decks": n_banned,
        "off_format_decks": n_off,
    }


def clean_source_caches(data_dir, fmt, cutoff, pool, banned, dry_run=False):
    """Apply the era to every cache an analysis reads, not just the CSVs."""
    results = []
    for filename, shape in CACHE_DATE_FILES.items():
        for base in (data_dir, SCRIPT_DIR):
            path = os.path.join(base, filename)
            if os.path.isfile(path):
                rec = clean_date_cache(path, shape, cutoff, dry_run=dry_run,
                                       data_dir=data_dir, banned=banned)
                if rec:
                    results.append(rec)
                break

    for base in (data_dir, SCRIPT_DIR):
        path = os.path.join(base, "melee_deck_cache.json")
        if os.path.isfile(path):
            rec = clean_deck_cache(path, pool, banned, cutoff,
                                   dry_run=dry_run, data_dir=data_dir)
            if rec:
                results.append(rec)
            break
    return results


def main():
    parser = argparse.ArgumentParser(description="Quarantine scraped events that don't belong in this pool.")
    parser.add_argument("--format", default=None, help="Format to validate. Overrides mtg_config.json.")
    parser.add_argument("--since", default=None, help="Window start (YYYY-MM-DD). Default: current era.")
    parser.add_argument("--dry-run", action="store_true", help="Report only; don't rewrite anything.")
    parser.add_argument("--allow", nargs="*", default=[], help="Tournament IDs to keep regardless of verdict.")
    parser.add_argument("--refresh-pool", action="store_true", help="Refetch the card pool from Scryfall first.")
    parser.add_argument("--skip-caches", action="store_true",
                        help="Validate events only; leave the deck and MTGO caches alone.")
    args = parser.parse_args()

    config = load_config()
    fmt = (args.format or config.get("format", "Standard")).strip()
    data_dir = resolve_data_dir(fmt, SCRIPT_DIR)

    era = mtg_era.resolve_era(fmt=fmt, weeks_window=config.get("weeks_window", 8),
                              since_override=args.since)
    cutoff = era.get("start") if isinstance(era, dict) else None
    if isinstance(cutoff, str):
        cutoff = mtg_era.parse_date(cutoff)
    label = (era.get("label") if isinstance(era, dict) else None) or "current era"

    print(f"\nValidating {fmt} events in {data_dir}")
    print(f"  Era: {label}")
    print(f"  Window start: {cutoff.date() if cutoff else 'none'}")

    if args.refresh_pool:
        build_card_pool.build(fmt, data_dir, max_age_days=0)
    pool, pool_meta = build_card_pool.load_pool(fmt, data_dir)
    if pool is None:
        print(f"\n  No card_pool_{fmt.lower()}.json. Run: python build_card_pool.py")
        print("  Falling back to the ban test only — off-format events will NOT be caught.")
    else:
        print(f"  Card pool: {pool_meta.get('count')} names, fetched {pool_meta.get('fetched', '?')[:10]}")

    banned = banned_as_of(fmt, cutoff)
    print(f"  Banned as of window start: {', '.join(sorted(banned)) or 'none'}")

    cache = load_deck_cache(data_dir)
    print(f"  Decklist cache: {len(cache)} lists")

    events = discover_events(data_dir, fmt)
    if not events:
        print(f"\nNo rows in melee_{fmt.lower()}_all_pairings.csv and no per-event CSVs. "
              "Nothing to validate.")
        return 1
    print(f"  Events in pool: {len(events)}")

    allow = set(args.allow)
    verdicts = []
    for tid, rows in sorted(events.items()):
        name = rows[0].get("tournament_name", "") if rows else ""
        rec = validate_event(tid, name, rows, cache, pool, banned)
        if tid in allow and rec["verdict"] in ("off-format", "pre-era", "variant"):
            rec["overridden"] = rec["verdict"]
            rec["verdict"] = "ok"
            rec["reason"] = f"forced clean by --allow (was {rec['overridden']})"
        verdicts.append(rec)

    order = {"off-format": 0, "pre-era": 1, "variant": 2, "seat": 3, "unverified": 4, "ok": 5}
    verdicts.sort(key=lambda v: (order.get(v["verdict"], 9), -v["players"]))

    print(f"\n{'verdict':12s} {'id':>8s} {'plyrs':>6s} {'legal':>6s} {'ban':>5s}  event")
    print("-" * 78)
    for v in verdicts:
        print(f"{v['verdict']:12s} {v['tournament_id']:>8s} {v['players']:6d} "
              f"{v.get('legal_share', '-'):>6} {v.get('banned_share', '-'):>5}  {v['tournament_name'][:34]}")
        if v["verdict"] != "ok":
            print(f"{'':12s} └─ {v['reason']}")

    bad = [v for v in verdicts if v["verdict"] in ("off-format", "pre-era", "variant")]
    seats = [v for v in verdicts if v["verdict"] == "seat"]
    summary = rewrite_combined(data_dir, fmt, verdicts, dry_run=args.dry_run)
    hidden, restored = quarantine_event_files(data_dir, fmt, verdicts, dry_run=args.dry_run)
    caches = ([] if args.skip_caches
              else clean_source_caches(data_dir, fmt, cutoff, pool, banned,
                                       dry_run=args.dry_run))

    report = {
        "validated": datetime.now().isoformat(timespec="seconds"),
        "format": fmt,
        "era_label": label,
        "window_start": cutoff.strftime("%Y-%m-%d") if cutoff else None,
        "card_pool": pool_meta,
        "banned_as_of_window_start": sorted(banned),
        "thresholds": {
            "deck_legal": DECK_LEGAL_THRESHOLD,
            "event_legal": EVENT_LEGAL_THRESHOLD,
            "event_banned": EVENT_BANNED_THRESHOLD,
            "min_decks_to_judge": MIN_DECKS_TO_JUDGE,
            "min_seat_decks": MIN_SEAT_DECKS,
        },
        "rows": summary,
        "caches": caches,
        "unreadable_files": UNREADABLE,
        "events": verdicts,
    }
    out = os.path.join(data_dir, f"event_quarantine_{fmt.lower()}.json")
    if not args.dry_run:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)

    print()
    for kind, s in summary.items():
        print(f"  {kind}: {s['before']} rows → {s['after']} ({s['removed']} removed)")
    if hidden:
        print(f"  per-event files hidden from the matchup glob: {len(hidden)} "
              "(renamed *.quarantined.csv)")
    if restored:
        print(f"  per-event files restored: {len(restored)}")

    if caches:
        print("\n  Source caches (every analysis reads one of these, not just the CSVs):")
        for c in caches:
            note = ""
            if c.get("banned_decks") or c.get("off_format_decks"):
                note = (f"  [{c.get('banned_decks', 0)} banned, "
                        f"{c.get('off_format_decks', 0)} off-format]")
            elif c.get("oldest_removed"):
                note = f"  [{c['oldest_removed']} to {c['newest_removed']}]"
                if c.get("removed_by_banned_cards"):
                    note += (f", {c['removed_by_banned_cards']} caught by cards "
                             "despite an in-era date")
            print(f"    {c['file']:32s} {c['before']:5d} → {c['after']:5d} "
                  f"({c['removed']} removed){note}")
        moved = sum(c["removed"] for c in caches)
        if moved and not args.dry_run:
            print(f"    {moved} entr(ies) parked in "
                  f"archive/through-{cutoff.strftime('%Y-%m-%d') if cutoff else 'unknown'}/"
                  " and .bak kept beside each file")

    if UNREADABLE:
        print(f"\n  WARNING: {len(UNREADABLE)} file(s) could not be read, so the events "
              "in them were never judged:")
        for name, err in UNREADABLE[:8]:
            print(f"    {name}  ({err.split(':')[0]})")
        if len(UNREADABLE) > 8:
            print(f"    ...and {len(UNREADABLE) - 8} more")
        print("    On OneDrive this usually means cloud-only placeholders. Mark the "
              "data folder 'Always keep on this device' and re-run.")
        report_unreadable = True
    else:
        report_unreadable = False
    if args.dry_run:
        print("\n--dry-run: nothing written.")
    else:
        print(f"  Report: {out}")
        print(f"  Originals preserved as melee_{fmt.lower()}_all_*.raw.csv")

    if bad or seats:
        print(f"\n{len(bad)} event(s) quarantined, {len(seats)} salvaged as a single seat.")
        return 2
    print("\nAll events passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
