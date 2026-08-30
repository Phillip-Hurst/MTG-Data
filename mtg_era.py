#!/usr/bin/env python3
"""
mtg_era.py — resolve the current "format era" for a format.

An era is the stretch of time over which tournament results are comparable.
Two things end an era:

  1. A set release (set_releases.json). New cards, new format.
  2. A banned and restricted announcement (bans.json). Same cards minus a few,
     but the top of the metagame is gone and old win rates stop describing
     anything that still exists.

The era start is whichever of those two happened most recently. Everything in
the skill that used to anchor on "latest set release" anchors here instead, so
a ban splits the data the same way a rotation does.

Stdlib only. Imported by mtg_fetch.py, build_baseline.py and archive_era.py;
also runs standalone:

    python mtg_era.py                    # current Standard era
    python mtg_era.py --format Modern
    python mtg_era.py --json

Era slug rules (these become filenames, so they have to stay stable):
  - set-only era      → "marvel-super-heroes"
  - era after a ban   → "marvel-super-heroes-post-ban-2026-08-10"

A set-only slug is the same string the skill used before eras existed, so
baselines written before this change keep working and keep meaning what they
meant: the pre-ban era.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)

# A ban and a set release this close together are one format reset. Splitting
# them produces a second era only a few days long, and drops the results that
# fall between the two dates.
MERGE_ANCHOR_DAYS = 14

DATE_PATTERNS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%B %d, %Y",
    "%b %d, %Y",
    "%m/%d/%Y",
]


def find_config(name):
    """Data folder first, then the shipped copy next to the scripts.

    Same precedence the other scripts use, so a format that carries its own
    set_releases.json can carry its own bans.json too."""
    p = os.path.join(DATA_DIR, name)
    return p if os.path.exists(p) else os.path.join(SCRIPT_DIR, name)


def parse_date(text):
    if not text:
        return None
    text = str(text).strip()
    for pat in DATE_PATTERNS:
        try:
            return datetime.strptime(text, pat)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def _load(name, key):
    path = find_config(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(key, []) or []
    except (OSError, ValueError) as e:
        print(f"  ! couldn't read {os.path.basename(path)} ({e}) — ignoring it.",
              file=sys.stderr)
        return []


def load_sets():
    """[{name, code, release_date}, ...] from set_releases.json."""
    return _load("set_releases.json", "sets")


def load_bans(fmt=None):
    """B&R announcements from bans.json, newest first.

    Filtered to one format when fmt is given. Entries with no 'format' key
    apply to every format — that's the escape hatch for a change that hits
    everything at once."""
    out = []
    for a in _load("bans.json", "announcements"):
        dt = parse_date(a.get("effective", ""))
        if not dt:
            continue
        a_fmt = (a.get("format") or "").strip()
        if fmt and a_fmt and a_fmt.lower() != fmt.lower():
            continue
        out.append((dt, a))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def latest_set():
    """(datetime, set dict) for the most recent dated set, or (None, None)."""
    dated = [(parse_date(s.get("release_date", "")), s) for s in load_sets()]
    dated = [(d, s) for d, s in dated if d]
    if not dated:
        return None, None
    return max(dated, key=lambda x: x[0])


def resolve_era(fmt="Standard", weeks_window=8, since_override=None):
    """The era a given format is currently in.

    Returns a dict:
      start        datetime — window start, and the point the data splits at
      start_str    'YYYY-MM-DD'
      anchor       'override' | 'ban' | 'set-release' | 'rolling-window' | 'fallback'
      slug         filename-safe era id
      label        human sentence for notes and console output
      set_name     the set the era sits in, when there is one
      ban          the announcement dict, when a ban opened the era
      reason       one line explaining why the window starts where it does
    """
    if since_override:
        dt = parse_date(since_override)
        if dt:
            return {
                "start": dt, "start_str": dt.strftime("%Y-%m-%d"),
                "anchor": "override",
                "slug": f"since-{dt.strftime('%Y-%m-%d')}",
                "label": f"since {dt.strftime('%Y-%m-%d')} (manual override)",
                "set_name": None, "ban": None,
                "reason": "--since override on the command line",
            }

    set_dt, set_meta = latest_set()
    bans = load_bans(fmt)
    ban_dt, ban_meta = bans[0] if bans else (None, None)

    # Non-Standard formats have no rotation anchor, but they do still get
    # banned. A ban is the better anchor than an arbitrary rolling window, so
    # use it when it is inside the window we would have used anyway.
    if fmt.lower() != "standard":
        rolling = datetime.now() - timedelta(weeks=weeks_window)
        if ban_dt and ban_dt >= rolling:
            return _ban_era(ban_dt, ban_meta, None, fmt)
        return {
            "start": rolling, "start_str": rolling.strftime("%Y-%m-%d"),
            "anchor": "rolling-window",
            "slug": f"{slugify(fmt)}-last-{weeks_window}-weeks",
            "label": f"{fmt}, last {weeks_window} weeks",
            "set_name": None, "ban": None,
            "reason": f"{fmt} has no set-rotation anchor — using weeks_window from mtg_config.json",
        }

    # Two anchors inside the same fortnight are one reset, not two. The
    # 2026-08-10 bans and The Hobbit's 2026-08-14 release are 4 days apart;
    # anchoring on the later one would throw away three days of post-ban
    # results and open a second, near-empty era. Take the earlier start so no
    # data is lost, and name the era after both.
    if ban_dt and set_dt and abs((set_dt - ban_dt).days) <= MERGE_ANCHOR_DAYS:
        return _merged_era(ban_dt, ban_meta, set_dt, set_meta, fmt)

    if ban_dt and (set_dt is None or ban_dt > set_dt):
        return _ban_era(ban_dt, ban_meta, set_meta, fmt)

    if set_dt:
        return {
            "start": set_dt, "start_str": set_dt.strftime("%Y-%m-%d"),
            "anchor": "set-release",
            "slug": slugify(set_meta["name"]),
            "label": f"{set_meta['name']} ({set_dt.strftime('%Y-%m-%d')} onward)",
            "set_name": set_meta["name"], "ban": None,
            "reason": f"{set_meta['name']} released {set_dt.strftime('%Y-%m-%d')}, "
                      f"no later B&R change for {fmt}",
        }

    fallback = datetime.now() - timedelta(weeks=12)
    return {
        "start": fallback, "start_str": fallback.strftime("%Y-%m-%d"),
        "anchor": "fallback",
        "slug": f"{slugify(fmt)}-last-12-weeks",
        "label": f"{fmt}, last 12 weeks (no set or ban dates on file)",
        "set_name": None, "ban": None,
        "reason": "set_releases.json has no dates — run mtg_fetch.py --fetch-sets",
    }


def _merged_era(ban_dt, ban_meta, set_dt, set_meta, fmt):
    """One era for a ban and a set release that land within MERGE_ANCHOR_DAYS."""
    start = min(ban_dt, set_dt)
    date_str = start.strftime("%Y-%m-%d")
    tag = slugify(ban_meta.get("label") or "post-ban")
    changed = ban_meta.get("banned") or ban_meta.get("restricted") or []
    changed_str = ", ".join(changed) if changed else "no card changes listed"
    return {
        "start": start, "start_str": date_str,
        "anchor": "ban+set-release",
        "slug": f"{slugify(set_meta['name'])}-{tag}-{date_str}",
        "label": f"{set_meta['name']}, {ban_meta.get('label', 'post-ban')} ({date_str} onward)",
        "set_name": set_meta["name"],
        "ban": ban_meta,
        "reason": (f"B&R effective {ban_dt.strftime('%Y-%m-%d')} for {fmt} ({changed_str}) and "
                   f"{set_meta['name']} released {set_dt.strftime('%Y-%m-%d')} — "
                   f"{abs((set_dt - ban_dt).days)} days apart, treated as one reset "
                   f"starting {date_str}"),
    }


def _ban_era(ban_dt, ban_meta, set_meta, fmt):
    date_str = ban_dt.strftime("%Y-%m-%d")
    tag = slugify(ban_meta.get("label") or "post-ban")
    base = slugify(set_meta["name"]) if set_meta else slugify(fmt)
    changed = ban_meta.get("banned") or ban_meta.get("restricted") or []
    changed_str = ", ".join(changed) if changed else "no card changes listed"
    set_part = f"{set_meta['name']}, " if set_meta else ""
    return {
        "start": ban_dt, "start_str": date_str,
        "anchor": "ban",
        "slug": f"{base}-{tag}-{date_str}",
        "label": f"{set_part}{ban_meta.get('label', 'post-ban')} ({date_str} onward)",
        "set_name": set_meta["name"] if set_meta else None,
        "ban": ban_meta,
        "reason": f"B&R effective {date_str} for {fmt}: {changed_str}",
    }


def previous_era(fmt="Standard", weeks_window=8):
    """The era immediately before the current one, or None.

    This is what a cross-era comparison reads: the frozen reference the current
    numbers get measured against."""
    current = resolve_era(fmt, weeks_window)
    set_dt, set_meta = latest_set()
    bans = load_bans(fmt)

    if current["anchor"] == "ban":
        # Step back to whatever opened the era this ban closed: an earlier ban
        # inside the same set, else the set release itself.
        for dt, meta in bans[1:]:
            if set_dt is None or dt > set_dt:
                return _ban_era(dt, meta, set_meta, fmt)
        if set_dt:
            return {
                "start": set_dt, "start_str": set_dt.strftime("%Y-%m-%d"),
                "anchor": "set-release", "slug": slugify(set_meta["name"]),
                "label": f"{set_meta['name']} pre-ban "
                         f"({set_dt.strftime('%Y-%m-%d')} – {current['start_str']})",
                "set_name": set_meta["name"], "ban": None,
                "reason": "the stretch this ban closed",
            }
        return None

    if current["anchor"] == "set-release":
        others = [(parse_date(s.get("release_date", "")), s) for s in load_sets()]
        others = [(d, s) for d, s in others if d and d < current["start"]]
        if not others:
            return None
        dt, meta = max(others, key=lambda x: x[0])
        return {
            "start": dt, "start_str": dt.strftime("%Y-%m-%d"),
            "anchor": "set-release", "slug": slugify(meta["name"]),
            "label": f"{meta['name']} ({dt.strftime('%Y-%m-%d')} – {current['start_str']})",
            "set_name": meta["name"], "ban": None,
            "reason": "the set before this one",
        }

    return None


def main():
    p = argparse.ArgumentParser(description="Show the current format era.")
    p.add_argument("--format", default=None, help="Format (default: from mtg_config.json)")
    p.add_argument("--weeks-window", type=int, default=None)
    p.add_argument("--json", action="store_true", help="Machine-readable output")
    args = p.parse_args()

    cfg_path = find_config("mtg_config.json")
    cfg = {"format": "Standard", "weeks_window": 8}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
        except (OSError, ValueError):
            pass

    fmt = args.format or cfg["format"]
    weeks = args.weeks_window if args.weeks_window is not None else cfg["weeks_window"]

    era = resolve_era(fmt, weeks)
    prev = previous_era(fmt, weeks)

    if args.json:
        def clean(e):
            if not e:
                return None
            return {k: (v.strftime("%Y-%m-%d") if isinstance(v, datetime) else v)
                    for k, v in e.items()}
        print(json.dumps({"format": fmt, "current": clean(era), "previous": clean(prev)},
                         indent=2, ensure_ascii=False))
        return

    print(f"\nFormat: {fmt}")
    print(f"Current era: {era['label']}")
    print(f"  starts    {era['start_str']}  (anchor: {era['anchor']})")
    print(f"  slug      {era['slug']}")
    print(f"  why       {era['reason']}")
    if era.get("ban"):
        b = era["ban"]
        if b.get("banned"):
            print(f"  banned    {', '.join(b['banned'])}")
        if b.get("restricted"):
            print(f"  restricted {', '.join(b['restricted'])}")
        if b.get("decks_hit"):
            print(f"  decks hit {', '.join(b['decks_hit'])}")
    if prev:
        print(f"Previous era: {prev['label']}  (slug {prev['slug']})")
    else:
        print("Previous era: none on file")
    print()


if __name__ == "__main__":
    main()
