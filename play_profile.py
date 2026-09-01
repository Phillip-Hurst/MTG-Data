#!/usr/bin/env python3
"""
play_profile.py - roll vod-review's play ledger up into a play profile.

The ledger (`play_log.jsonl`) is append-only: one JSON object per reviewed game,
written by `vod-review` at the end of each review. This script counts it and
rewrites `[C] Play Profile.md` from those counts.

Counting is the whole point. "You're impatient with removal" is a vibe. "You
spent removal on the first legal target in 5 of 7 games across 3 sessions, 4 of
them graded punt" is a finding someone can argue with. Reading six review notes
and remembering what they said produces the first sentence. This produces the
second.

Stdlib only, same as mtg_era.py and rules_lookup.py.

    python play_profile.py                 # roll up, write the profile
    python play_profile.py --dry-run       # print the rollup, write nothing
    python play_profile.py --validate      # check the ledger, write nothing
    python play_profile.py --json          # machine-readable, writes nothing
    python play_profile.py --hands         # the index of kept hands, card by card

Exit codes carry meaning, because a tool that always exits 0 cannot gate
anything:

    0   ran clean
    1   could not run (no ledger, nothing readable, bad arguments)
    2   ran, and found ledger lines it could not use

Neither the ledger nor the profile ships with this plugin, and neither belongs
in the repo. They are a record of one person's own games. `package.py` drops
`play_log*.jsonl` and root `[C] *.md`, and `.gitignore` covers both.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import mtg_paths
except ImportError:                                    # standalone copy
    mtg_paths = None

LEDGER_NAME = "play_log.jsonl"
PROFILE_NAME = "[C] Play Profile.md"
BACKUP_NAME = "[C] Play Profile.pre-rollup.md"

# The fixed vocabularies. These are the reason the ledger can be counted at all:
# free text splits one habit spelled three ways into three habits, which is the
# same failure mtg_stats.ARCHETYPE_ALIASES exists to prevent for deck names.
# Adding a value means adding it here AND in
# skills/vod-review/reference/play-profile.md. Never inline.
KINDS = (
    "mulligan",
    "play-draw",
    "land-sequencing",
    "mana-holding",
    "trading",
    "removal-timing",
    "combat-math",
    "sideboarding",
    "lost-turn",
    "rules-error",
)
GRADES = ("punt", "close", "correct")
RESULTS = ("W", "L", "D")
PACE_MEASURES = ("vod-timestamps", "untapped-duration", "self-report", "none")
PACE_TELLS = (
    "tapped-wrong-mana",
    "cast-before-land-drop",
    "missed-trigger",
    "attacked-before-pump",
    "same-15-every-matchup",
    "sequenced-into-own-counterspell",
)

# The kept hand. A mulligan finding without the hand behind it is unarguable:
# "that was a keep" is an opinion, "you kept a 6 with two lands and four
# four-drops" is a review. Storing the card list also makes the ledger the index
# of what this player actually keeps, which `--hands` prints.
HAND_SHAPES = (
    "lands-and-spells",     # functional: enough lands, a curve to spend them on
    "interaction-heavy",    # removal and counters, light on lands or threats
    "threat-heavy",         # threats with too little interaction or mana
    "land-light",           # fewer lands than the deck wants to function
    "land-heavy",           # lands with too little action
    "no-early-play",        # nothing castable before the opponent's clock lands
    "unknown",
)
# What the draw actually did to the hand afterwards. Kept separate from shape so
# a keep can be graded on what was knowable, then compared against what happened.
HAND_OUTCOMES = ("screwed", "flooded", "neither", "unknown")

# The trend bar. Two occurrences on one night is one bad night, so sessions are
# counted separately from games.
DEFAULT_MIN_OCCURRENCES = 3
DEFAULT_MIN_SESSIONS = 2

# A trend whose last appearance is older than this many of the most recent
# sessions has gone quiet. It moves to Faded rather than being deleted: someone
# who fixed a leak gets to see that they fixed it.
FADE_AFTER_SESSIONS = 2

# Above this share of a kind's findings being profile-prompted, the count is
# worth less than it looks, and the profile says so.
BIAS_FLAG_SHARE = 0.5


# --------------------------------------------------------------- locating files

def resolve_dir(fmt):
    """Where the insights notes for this format live.

    Same resolution the rest of the plugin uses, so the ledger sorts into the
    per-format insights folder rather than landing next to the scripts.
    """
    if mtg_paths is not None:
        return mtg_paths.resolve_output_dir(fmt, SCRIPT_DIR)
    return os.environ.get("MTG_OUTPUT_DIR") or SCRIPT_DIR


# ------------------------------------------------------------------- validation

def _is_date(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_row(row, line_no):
    """Return a list of problems with one ledger row. Empty means usable.

    An absent value is not a passing value. A row missing a field this counts on
    is excluded and reported, never waved through and counted as something.
    """
    problems = []

    def bad(msg):
        problems.append("line %d: %s" % (line_no, msg))

    if not isinstance(row, dict):
        bad("not a JSON object")
        return problems

    if not _is_date(row.get("date")):
        bad("date %r is not YYYY-MM-DD" % (row.get("date"),))
    for field in ("your_deck", "their_deck"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            bad("%s is missing or empty" % field)
    if not isinstance(row.get("game"), int):
        bad("game %r is not an integer" % (row.get("game"),))
    if row.get("result") not in RESULTS:
        bad("result %r is not one of %s" % (row.get("result"), "/".join(RESULTS)))

    findings = row.get("findings")
    if not isinstance(findings, list):
        bad("findings is missing or not a list (use [] for a clean game)")
        findings = []

    for i, f in enumerate(findings):
        where = "finding %d" % i
        if not isinstance(f, dict):
            bad("%s is not an object" % where)
            continue
        if f.get("kind") not in KINDS:
            bad("%s kind %r is not in the fixed vocabulary" % (where, f.get("kind")))
        if f.get("grade") not in GRADES:
            bad("%s grade %r is not one of %s"
                % (where, f.get("grade"), "/".join(GRADES)))
        if not isinstance(f.get("turn"), int):
            bad("%s turn %r is not an integer" % (where, f.get("turn")))
        if not isinstance(f.get("habit"), str) or not f["habit"].strip():
            bad("%s habit is missing or empty" % where)

    hand = row.get("hand")
    if hand is not None:
        if not isinstance(hand, dict):
            bad("hand is not an object")
        else:
            kept_at = hand.get("kept_at")
            if not isinstance(kept_at, int) or not 0 <= kept_at <= 7:
                bad("hand kept_at %r is not an integer 0-7" % (kept_at,))
            lands = hand.get("lands")
            if not isinstance(lands, int) or lands < 0:
                bad("hand lands %r is not a non-negative integer" % (lands,))
            cards = hand.get("cards")
            if not isinstance(cards, list) or not all(
                    isinstance(c, str) and c.strip() for c in cards):
                bad("hand cards is missing or not a list of card names")
            elif isinstance(kept_at, int) and len(cards) != kept_at:
                bad("hand has %d card(s) listed but kept_at is %d"
                    % (len(cards), kept_at))
            if hand.get("shape") not in HAND_SHAPES:
                bad("hand shape %r is not in the fixed vocabulary"
                    % (hand.get("shape"),))
            outcome = hand.get("outcome", "unknown")
            if outcome not in HAND_OUTCOMES:
                bad("hand outcome %r is not in the fixed vocabulary" % (outcome,))

    pace = row.get("pace")
    if pace is not None:
        if not isinstance(pace, dict):
            bad("pace is not an object")
        else:
            if pace.get("measure") not in PACE_MEASURES:
                bad("pace measure %r is not in the fixed vocabulary"
                    % (pace.get("measure"),))
            spt = pace.get("seconds_per_turn")
            if spt is not None and not isinstance(spt, (int, float)):
                bad("pace seconds_per_turn %r is not a number" % (spt,))
            tells = pace.get("tells", [])
            if not isinstance(tells, list):
                bad("pace tells is not a list")
            else:
                for t in tells:
                    if t not in PACE_TELLS:
                        bad("pace tell %r is not in the fixed vocabulary" % (t,))

    return problems


def read_ledger(path):
    """Parse the ledger. Returns (rows, problems, unreadable).

    An unreadable file is not a clean file, so an OSError comes back as a
    reported problem rather than an empty list. This vault sits on OneDrive,
    where a cloud-only placeholder raises OSError on a file that lists fine.
    """
    rows, problems, unreadable = [], [], None

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return [], [], "%s: %s" % (path, exc)

    for line_no, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text or text.startswith("//"):
            continue
        try:
            row = json.loads(text)
        except ValueError as exc:
            problems.append("line %d: not valid JSON (%s)" % (line_no, exc))
            continue
        row_problems = validate_row(row, line_no)
        if row_problems:
            problems.extend(row_problems)
            continue
        rows.append(row)

    return rows, problems, unreadable


# ------------------------------------------------------------------- rollup

def hand_keeps_top(card_keeps, limit=10):
    """Cards that show up most often in hands this player chose to keep.

    Not a judgement, a frequency. It answers "what am I actually keeping" with
    a count rather than an impression, which is the same trade the habit table
    makes.
    """
    return [{"card": c, "hands": n} for c, n in card_keeps.most_common(limit)]


def roll_up(rows, min_occurrences, min_sessions):
    """Count the ledger. No judgement here, just arithmetic."""
    sessions = sorted({r["date"] for r in rows})
    recent_sessions = set(sessions[-FADE_AFTER_SESSIONS:]) if sessions else set()

    by_kind = defaultdict(lambda: {
        "kind": None,
        "occurrences": 0,
        "games": set(),
        "sessions": set(),
        "grades": Counter(),
        "habits": Counter(),
        "prompted": 0,
        "intent_mismatch": 0,
        "last_seen": None,
        "turns": [],
    })

    decks = Counter()
    opponents = Counter()
    results = Counter()
    interview = Counter()
    pace_by_measure = defaultdict(list)
    tells = Counter()
    games_with_pace = 0
    hand_rows = []
    hands_by_size = defaultdict(lambda: {
        "games": 0, "results": Counter(), "lands": [], "outcomes": Counter(),
    })
    hand_shapes = Counter()
    hand_outcomes = Counter()
    card_keeps = Counter()

    for r in rows:
        game_key = (r["date"], r["their_deck"], r["game"])
        decks[r["your_deck"]] += 1
        opponents[r["their_deck"]] += 1
        results[r["result"]] += 1

        for f in r["findings"]:
            k = by_kind[f["kind"]]
            k["kind"] = f["kind"]
            k["occurrences"] += 1
            k["games"].add(game_key)
            k["sessions"].add(r["date"])
            k["grades"][f["grade"]] += 1
            k["habits"][f["habit"].strip()] += 1
            k["turns"].append(f["turn"])
            if f.get("prompted_by_profile") is True:
                k["prompted"] += 1
            if f.get("intent_matched_line") is False:
                k["intent_mismatch"] += 1
            if k["last_seen"] is None or r["date"] > k["last_seen"]:
                k["last_seen"] = r["date"]

        pace = r.get("pace") or {}
        measure = pace.get("measure")
        spt = pace.get("seconds_per_turn")
        if measure and measure != "none" and isinstance(spt, (int, float)):
            pace_by_measure[measure].append(float(spt))
            games_with_pace += 1
        for t in pace.get("tells", []) or []:
            tells[t] += 1

        iv = r.get("interview") or {}
        for field in ("asked", "answered", "dont_remember"):
            value = iv.get(field)
            if isinstance(value, int):
                interview[field] += value

        hand = r.get("hand")
        if isinstance(hand, dict):
            size = hand["kept_at"]
            outcome = hand.get("outcome", "unknown")
            bucket = hands_by_size[size]
            bucket["games"] += 1
            bucket["results"][r["result"]] += 1
            bucket["lands"].append(hand["lands"])
            bucket["outcomes"][outcome] += 1
            hand_shapes[hand["shape"]] += 1
            hand_outcomes[outcome] += 1
            for card in hand["cards"]:
                card_keeps[card.strip()] += 1
            hand_rows.append({
                "date": r["date"],
                "game": r["game"],
                "your_deck": r["your_deck"],
                "their_deck": r["their_deck"],
                "result": r["result"],
                "on_the_play": r.get("on_the_play"),
                "kept_at": size,
                "lands": hand["lands"],
                "shape": hand["shape"],
                "outcome": outcome,
                "cards": list(hand["cards"]),
                "note": hand.get("note"),
            })

    total_games = len({(r["date"], r["their_deck"], r["game"]) for r in rows})

    habits = []
    for kind, k in by_kind.items():
        occurrences = k["occurrences"]
        n_sessions = len(k["sessions"])
        if occurrences >= min_occurrences and n_sessions >= min_sessions:
            bucket = "trend"
        elif occurrences >= 2:
            bucket = "watching"
        else:
            bucket = "below-bar"

        faded = bool(
            bucket == "trend"
            and recent_sessions
            and k["last_seen"] not in recent_sessions
        )

        prompted_share = (k["prompted"] / occurrences) if occurrences else 0.0
        correct = k["grades"].get("correct", 0)
        strength = bool(
            correct >= min_occurrences
            and n_sessions >= min_sessions
            and correct > (occurrences - correct)
        )

        habits.append({
            "kind": kind,
            "bucket": "faded" if faded else bucket,
            "strength": strength,
            "occurrences": occurrences,
            "games": len(k["games"]),
            "sessions": n_sessions,
            "session_dates": sorted(k["sessions"]),
            "grades": dict(k["grades"]),
            "top_habit": k["habits"].most_common(1)[0][0] if k["habits"] else "",
            "habit_wordings": [h for h, _ in k["habits"].most_common()],
            "prompted_by_profile": k["prompted"],
            "prompted_share": round(prompted_share, 3),
            "bias_flag": prompted_share > BIAS_FLAG_SHARE and occurrences >= 2,
            "intent_mismatch": k["intent_mismatch"],
            "last_seen": k["last_seen"],
            "turns": sorted(k["turns"]),
        })

    habits.sort(key=lambda h: (-h["occurrences"], h["kind"]))

    pace = {
        "games_measured": games_with_pace,
        "games_total": total_games,
        "by_measure": {
            m: {
                "games": len(v),
                "mean_seconds_per_turn": round(sum(v) / len(v), 1),
                "fastest": round(min(v), 1),
                "slowest": round(max(v), 1),
            }
            for m, v in sorted(pace_by_measure.items())
        },
        "tells": dict(sorted(tells.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

    hands = {
        "recorded": len(hand_rows),
        "games_total": total_games,
        "by_size": {
            size: {
                "games": v["games"],
                "record": "-".join(str(v["results"].get(g, 0)) for g in RESULTS),
                "mean_lands": round(sum(v["lands"]) / len(v["lands"]), 1)
                if v["lands"] else None,
                "outcomes": dict(sorted(v["outcomes"].items())),
            }
            for size, v in sorted(hands_by_size.items(), reverse=True)
        },
        "shapes": dict(hand_shapes.most_common()),
        "outcomes": dict(hand_outcomes.most_common()),
        "most_kept_cards": hand_keeps_top(card_keeps),
        "index": sorted(hand_rows, key=lambda h: (h["date"], h["game"])),
    }

    return {
        "games": total_games,
        "rows": len(rows),
        "hands": hands,
        "sessions": len(sessions),
        "session_dates": sessions,
        "first_date": sessions[0] if sessions else None,
        "last_date": sessions[-1] if sessions else None,
        "your_decks": dict(decks.most_common()),
        "their_decks": dict(opponents.most_common()),
        "results": dict(results),
        "habits": habits,
        "pace": pace,
        "interview": dict(interview),
        "bar": {"min_occurrences": min_occurrences, "min_sessions": min_sessions},
    }


# ------------------------------------------------------------------- rendering

def _grade_split(grades):
    order = [g for g in GRADES if grades.get(g)]
    return ", ".join("%d %s" % (grades[g], g) for g in order) or "none"


def _table(rollup, buckets):
    rows = [h for h in rollup["habits"] if h["bucket"] in buckets]
    if not rows:
        return None
    out = ["| Habit | Kind | Count | Sessions | Grade split | Last seen |",
           "|---|---|---|---|---|---|"]
    for h in rows:
        out.append("| %s | %s | %d in %d game(s) | %d | %s | %s |" % (
            h["top_habit"] or "(unnamed)",
            h["kind"],
            h["occurrences"],
            h["games"],
            h["sessions"],
            _grade_split(h["grades"]),
            h["last_seen"] or "unknown",
        ))
    return "\n".join(out)


def render_profile(rollup, problems, today=None):
    """The note a human reads. Rewritten from the ledger every run."""
    today = today or date.today().isoformat()
    bar = rollup["bar"]
    lines = []

    lines += [
        "---",
        "author: claude",
        "type: solution",
        "project: MTG Tournament Analysis Skill",
        "date: %s" % today,
        "tags: [mtg, vod-review, play-profile]",
        "games_reviewed: %d" % rollup["games"],
        "range: %s to %s" % (rollup["first_date"] or "n/a",
                             rollup["last_date"] or "n/a"),
        "generated_by: play_profile.py",
        "---",
        "",
        "# Play profile",
        "",
    ]

    if not rollup["games"]:
        lines += [
            "**The ledger is empty.** Nothing to profile yet. Review a match and "
            "this fills in.",
            "",
        ]
        return "\n".join(lines)

    decks = ", ".join("%s (%d)" % (d, n) for d, n in rollup["your_decks"].items())
    record = "-".join(str(rollup["results"].get(g, 0)) for g in RESULTS)
    lines += [
        "**%d games across %d session(s), %s to %s.** Record %s (W-L-D). "
        "Decks: %s." % (rollup["games"], rollup["sessions"], rollup["first_date"],
                        rollup["last_date"], record, decks),
        "",
        "Rolled up by `play_profile.py` from `play_log.jsonl`. Anything here is "
        "countable back to a review note. The bar for a trend is %d occurrence(s) "
        "across %d session(s)." % (bar["min_occurrences"], bar["min_sessions"]),
        "",
    ]

    if rollup["games"] < 5:
        lines += [
            "**Sample is thin.** %d games is not enough to call a habit. Read the "
            "sections below as what is being watched, not as conclusions."
            % rollup["games"],
            "",
        ]

    # Trends
    lines += ["## Trends", ""]
    table = _table(rollup, {"trend"})
    if table:
        lines += [table, ""]
        for h in [x for x in rollup["habits"] if x["bucket"] == "trend"]:
            note = ["**%s** (`%s`). %d time(s) in %d game(s) across %d session(s), "
                    "last on %s. Turns: %s." % (
                        h["top_habit"] or h["kind"], h["kind"], h["occurrences"],
                        h["games"], h["sessions"], h["last_seen"],
                        ", ".join(str(t) for t in h["turns"]))]
            if h["intent_mismatch"]:
                note.append(
                    "In %d of these the stated plan and the line disagreed, so "
                    "this reads as execution rather than judgement."
                    % h["intent_mismatch"])
            if h["bias_flag"]:
                note.append(
                    "**Discount this count.** %d of %d were found because the "
                    "profile predicted them, so it is partly confirmation."
                    % (h["prompted_by_profile"], h["occurrences"]))
            if len(h["habit_wordings"]) > 1:
                note.append("Also written as: %s."
                            % "; ".join(h["habit_wordings"][1:]))
            lines += [" ".join(note), ""]
    else:
        lines += ["Nothing has cleared the bar yet.", ""]

    # Strengths
    lines += ["## Strengths", ""]
    strengths = [h for h in rollup["habits"] if h["strength"]]
    if strengths:
        for h in strengths:
            lines += ["**%s** (`%s`). Graded correct %d of %d time(s) across %d "
                      "session(s), last on %s. The line was right and the game "
                      "went the other way." % (
                          h["top_habit"] or h["kind"], h["kind"],
                          h["grades"].get("correct", 0), h["occurrences"],
                          h["sessions"], h["last_seen"]), ""]
    else:
        lines += ["Nothing has cleared the bar yet. This section needs `correct` "
                  "grades, which is the bucket a review has to be honest to use.",
                  ""]

    # Opening hands
    lines += ["## Opening hands", ""]
    hands = rollup["hands"]
    if hands["recorded"]:
        lines += ["**Recorded for %d of %d game(s).** Every kept hand is listed "
                  "card-for-card in its review note; this is the count."
                  % (hands["recorded"], hands["games_total"]), ""]
        lines += ["| Kept at | Games | Record (W-L-D) | Mean lands | Outcomes |",
                  "|---|---|---|---|---|"]
        for size, v in hands["by_size"].items():
            outcomes = ", ".join("%s %d" % (k, n)
                                 for k, n in v["outcomes"].items()) or "none"
            lines.append("| %d | %d | %s | %s | %s |" % (
                size, v["games"], v["record"],
                "n/a" if v["mean_lands"] is None else v["mean_lands"], outcomes))
        lines.append("")

        shapes = ", ".join("%s x%d" % (s, n) for s, n in hands["shapes"].items())
        lines += ["Shapes kept: %s." % shapes, ""]

        screwed = hands["outcomes"].get("screwed", 0)
        flooded = hands["outcomes"].get("flooded", 0)
        if screwed or flooded:
            lines += ["Mana outcome: %d screwed, %d flooded, out of %d hand(s). "
                      "A keep is graded on what was knowable when it was made, so "
                      "this line describes the draws, not the decisions."
                      % (screwed, flooded, hands["recorded"]), ""]

        if hands["most_kept_cards"]:
            lines += ["Most-kept cards: %s." % ", ".join(
                "%s (%d)" % (c["card"], c["hands"])
                for c in hands["most_kept_cards"]), ""]
    else:
        lines += ["**No hands recorded yet.** A mulligan finding needs the hand "
                  "behind it to be arguable, so reviews from here on log the kept "
                  "hand card-for-card.", ""]

    # Pace
    lines += ["## Pace", ""]
    pace = rollup["pace"]
    if pace["by_measure"]:
        lines += ["**Measured on %d of %d game(s).**"
                  % (pace["games_measured"], pace["games_total"]), ""]
        lines += ["| Measure | Games | Mean sec/turn | Fastest | Slowest |",
                  "|---|---|---|---|---|"]
        for m, v in pace["by_measure"].items():
            lines.append("| %s | %d | %s | %s | %s |" % (
                m, v["games"], v["mean_seconds_per_turn"], v["fastest"],
                v["slowest"]))
        lines.append("")
    else:
        lines += ["**Never measurable so far.** No game in the ledger carried a "
                  "usable timing source. A YouTube VOD gives real seconds per "
                  "turn; a pasted log gives nothing.", ""]

    if pace["tells"]:
        lines += ["Tells recorded: %s." % ", ".join(
            "%s x%d" % (t, n) for t, n in pace["tells"].items()), ""]
    iv = rollup["interview"]
    if iv.get("asked"):
        lines += ["Interview: %d question(s) asked, %d answered, %d came back as "
                  "\"don't remember\". A decision that left no memory of its "
                  "reasoning is usually a fast one." % (
                      iv.get("asked", 0), iv.get("answered", 0),
                      iv.get("dont_remember", 0)), ""]

    # Watching
    lines += ["## Watching", ""]
    table = _table(rollup, {"watching"})
    if table:
        lines += ["Two occurrences. Counted, not concluded.", "", table, ""]
    else:
        lines += ["Nothing at two occurrences.", ""]

    # Faded
    lines += ["## Faded", ""]
    table = _table(rollup, {"faded"})
    if table:
        lines += ["Cleared the bar once and has not appeared in the last %d "
                  "session(s)." % FADE_AFTER_SESSIONS, "", table, ""]
    else:
        lines += ["Nothing has gone quiet yet.", ""]

    # What to work on
    lines += ["## What to work on", ""]
    trends = [h for h in rollup["habits"]
              if h["bucket"] == "trend" and not h["bias_flag"]]
    if trends:
        top = trends[0]
        lines += ["**%s.** %d time(s) across %d session(s). One thing, and it "
                  "stays this one until the ledger shows it moving." % (
                      top["top_habit"] or top["kind"], top["occurrences"],
                      top["sessions"]), ""]
    else:
        lines += ["Nothing has cleared the bar. Keep reviewing.", ""]

    if problems:
        lines += ["---", "",
                  "## Data problems", "",
                  "**%d ledger line(s) could not be used**, so every count above "
                  "understates by that much. Run `python play_profile.py "
                  "--validate` for the list." % len(problems), ""]

    return "\n".join(lines)


# ----------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(
        description="Roll vod-review's play ledger up into a play profile.")
    p.add_argument("--format", default=None,
                   help="Format whose insights folder holds the ledger "
                        "(default: from mtg_config.json, else Standard)")
    p.add_argument("--ledger", default=None, help="Path to play_log.jsonl")
    p.add_argument("--out", default=None, help="Path to write the profile note")
    p.add_argument("--dry-run", action="store_true",
                   help="print the rollup and write nothing")
    p.add_argument("--validate", action="store_true",
                   help="check the ledger and write nothing")
    p.add_argument("--json", action="store_true",
                   help="machine-readable rollup on stdout; writes nothing")
    p.add_argument("--hands", action="store_true",
                   help="print the index of kept hands, newest last; "
                        "writes nothing")
    p.add_argument("--min-occurrences", type=int, default=DEFAULT_MIN_OCCURRENCES)
    p.add_argument("--min-sessions", type=int, default=DEFAULT_MIN_SESSIONS)
    args = p.parse_args()

    if args.min_occurrences < 1 or args.min_sessions < 1:
        print("The trend bar has to be at least 1 occurrence and 1 session.")
        return 1

    fmt = args.format
    if fmt is None:
        cfg = os.path.join(SCRIPT_DIR, "mtg_config.json")
        fmt = "Standard"
        try:
            with open(cfg, encoding="utf-8") as fh:
                fmt = json.load(fh).get("format", "Standard")
        except (OSError, ValueError):
            pass

    out_dir = resolve_dir(fmt)
    ledger = args.ledger or os.path.join(out_dir, LEDGER_NAME)
    profile = args.out or os.path.join(out_dir, PROFILE_NAME)

    if not os.path.exists(ledger):
        print("No ledger at %s" % ledger)
        print("Nothing to roll up. vod-review appends a line per reviewed game.")
        return 1

    rows, problems, unreadable = read_ledger(ledger)

    if unreadable:
        print("Could not read the ledger: %s" % unreadable)
        print("On OneDrive a cloud-only placeholder raises this while still "
              "listing in the folder. Open the file once to hydrate it.")
        return 1

    if not rows and problems:
        print("Read %s and could not use a single line of it." % ledger)
        for msg in problems:
            print("  %s" % msg)
        return 1

    rollup = roll_up(rows, args.min_occurrences, args.min_sessions)

    if args.json:
        print(json.dumps({"rollup": rollup, "problems": problems},
                         indent=2, ensure_ascii=False))
        return 2 if problems else 0

    if args.hands:
        hands = rollup["hands"]
        print("\nKept hands: %s" % ledger)
        if not hands["recorded"]:
            print("  None recorded. Reviews log the kept hand card-for-card; "
                  "older ledger lines predate that.")
            return 2 if problems else 0
        print("  %d of %d game(s) carry a hand\n"
              % (hands["recorded"], hands["games_total"]))
        for h in hands["index"]:
            print("  %s  G%d  %s vs %s  %s  kept %d (%d land%s, %s, %s)%s"
                  % (h["date"], h["game"], h["your_deck"], h["their_deck"],
                     h["result"], h["kept_at"], h["lands"],
                     "" if h["lands"] == 1 else "s", h["shape"], h["outcome"],
                     "  on the play" if h["on_the_play"] else ""))
            print("      %s" % ", ".join(h["cards"]))
            if h.get("note"):
                print("      %s" % h["note"])
        print()
        return 2 if problems else 0

    if args.validate:
        print("\nLedger: %s" % ledger)
        print("  %d line(s) usable, %d problem(s)" % (len(rows), len(problems)))
        for msg in problems:
            print("  %s" % msg)
        print("  vocabularies: %d kinds, %d grades, %d pace measures, %d tells, "
              "%d hand shapes, %d hand outcomes"
              % (len(KINDS), len(GRADES), len(PACE_MEASURES), len(PACE_TELLS),
                 len(HAND_SHAPES), len(HAND_OUTCOMES)))
        print("  hands recorded: %d of %d game(s)"
              % (rollup["hands"]["recorded"], rollup["hands"]["games_total"]))
        print()
        return 2 if problems else 0

    text = render_profile(rollup, problems)

    print("\nLedger: %s" % ledger)
    print("  %d game(s) over %d session(s), %s to %s"
          % (rollup["games"], rollup["sessions"],
             rollup["first_date"], rollup["last_date"]))
    trends = [h for h in rollup["habits"] if h["bucket"] == "trend"]
    watching = [h for h in rollup["habits"] if h["bucket"] == "watching"]
    faded = [h for h in rollup["habits"] if h["bucket"] == "faded"]
    strengths = [h for h in rollup["habits"] if h["strength"]]
    print("  %d trend(s), %d watching, %d faded, %d strength(s)"
          % (len(trends), len(watching), len(faded), len(strengths)))
    for h in trends:
        print("    trend    %-16s %d in %d game(s), %d session(s)%s"
              % (h["kind"], h["occurrences"], h["games"], h["sessions"],
                 "  [discount: profile-prompted]" if h["bias_flag"] else ""))
    for h in watching:
        print("    watching %-16s %d occurrence(s)" % (h["kind"], h["occurrences"]))
    if rollup["pace"]["by_measure"]:
        for m, v in rollup["pace"]["by_measure"].items():
            print("  pace     %-16s %d game(s), mean %s sec/turn"
                  % (m, v["games"], v["mean_seconds_per_turn"]))
    else:
        print("  pace     not measurable from any game in the ledger")

    if problems:
        print("  %d ledger line(s) unusable and excluded from every count above:"
              % len(problems))
        for msg in problems:
            print("    %s" % msg)
        print("  Fix them in the ledger and re-run. Counts understate until then.")

    if args.dry_run:
        print("\n--dry-run: nothing written. The profile would be:\n")
        print(text)
        return 2 if problems else 0

    backup = None
    if os.path.exists(profile):
        try:
            with open(profile, encoding="utf-8") as fh:
                previous = fh.read()
        except OSError as exc:
            print("\nThe existing profile is unreadable, so it will not be "
                  "overwritten: %s" % exc)
            return 1
        if previous == text:
            print("\nProfile already current: %s" % profile)
            print()
            return 2 if problems else 0
        backup = os.path.join(os.path.dirname(profile), BACKUP_NAME)
        try:
            with open(backup, "w", encoding="utf-8") as fh:
                fh.write(previous)
        except OSError as exc:
            print("\nCould not write the backup, so nothing was overwritten: %s"
                  % exc)
            return 1

    try:
        with open(profile, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        print("\nCould not write the profile: %s" % exc)
        return 1

    print("\nWrote %s" % profile)
    if backup:
        print("Previous version kept at %s" % backup)
    print()
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
