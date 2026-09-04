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

Findings are counted under a `pattern_id` from `play_patterns.json`, never under
a `kind`. Kind is a decision category and every game contains several of each,
so counting kinds measures how much someone played rather than how they played:
any kind clears a three-occurrence bar within a few sessions no matter what.
A pattern names the behaviour, and one pattern lands in exactly one bucket:

    leak        cleared the bar, punt and close outnumber correct
    strength    cleared the bar, correct outnumbers punt and close
    mixed       cleared the bar, the two tie
    watching    two or more occurrences, bar not cleared
    below-bar   one occurrence, stays in the review note

The prose about a decision lives in its review note and nowhere else. A ledger
finding carries the pattern, the grade, and a pointer; the profile cites the
note rather than quoting it.

Stdlib only, same as mtg_era.py and rules_lookup.py.

    python play_profile.py                 # roll up, write the profile
    python play_profile.py --dry-run       # print the rollup, write nothing
    python play_profile.py --validate      # check the ledger, write nothing
    python play_profile.py --json          # the counts, writes nothing
    python play_profile.py --json --full   # the counts plus the hand index
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
# One note per deck, plus the cross-deck note above. A habit that only ever
# happens with one deck is usually the deck talking, not the player.
DECK_PROFILE_NAME = "[C] Play Profile - %s.md"

# The pattern registry, which ships with the plugin and is the vocabulary the
# profile counts on. It lives next to this script, not in the insights folder:
# the patterns are general facts about how Magic decisions go wrong, and the
# ledger of who made which one is the private part.
PATTERNS_NAME = "play_patterns.json"

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

# Where in the game the decision was made. This exists so `turn` can stop being
# a required integer with 0 standing in for "before the game started". A
# mulligan happens at no turn, and printing "Turns: 0, 0, 0, 0" was the tell.
#
# The two mulligans are separated because they are not the same decision. A
# game 1 keep is made in the dark: no idea what deck is across the table, so
# the hand can only be judged against the format. A game 2 or 3 keep is made
# knowing the matchup, and the same six cards can be a keep in one and a ship
# in the other. Grading them together averages a blind decision with an
# informed one and reports the mean as a habit.
#
# The 2026-09-01 Izzet Spellementals punt only exists because of the
# difference: bottoming Erode was a punt *because* two games had already shown
# that their whole battlefield costs two and three. Blind, it is a close call.
PHASES = ("mulligan-blind", "mulligan-post-board", "sideboard", "in-game")
MULLIGAN_PHASES = ("mulligan-blind", "mulligan-post-board")

# Phases that can only happen once the match is under way. A blind mulligan is
# game 1 by definition, and boarding happens between games, so each phase has a
# game number it agrees with. The validator checks, because a phase that
# disagrees with its game number is one of the two being wrong.
PHASE_GAME_RULE = {
    "mulligan-blind": (1, 1),
    "mulligan-post-board": (2, None),
    "sideboard": (2, None),
}

# Declared in the registry, checked against the grade mix. See play_patterns.json.
POLARITIES = ("leak", "strength", "neutral")

# A punt is worse than a close, and ranking them equally is how a decision type
# with six closes and no punts reached the top of "what to work on" on
# 2026-09-04. The weights are what the work-on line sorts by.
GRADE_WEIGHTS = {"punt": 2, "close": 1, "correct": 0}

# The closed schema. An unrecognised key is a problem rather than a passing
# value, because the 2026-09-04 review wrote `opening_hand` where the schema
# says `hand` and the run reported 0 problems while dropping three hands. A
# script that does nothing looks exactly like one that worked.
ROW_KEYS = frozenset((
    "date", "session_id", "match_id", "source", "era", "your_deck",
    "their_deck", "game", "result", "on_the_play", "review_note",
    "findings", "hand", "sideboard", "pace", "interview",
))
ROW_REQUIRED = ("date", "session_id", "match_id", "your_deck", "their_deck",
                "game", "result", "findings")
FINDING_KEYS = frozenset((
    "phase", "turn", "kind", "pattern_id", "grade", "note", "stated_reason",
    "intent_matched_line", "prompted_by_profile",
))
HAND_KEYS = frozenset(("kept_at", "lands", "cards", "shape", "outcome", "note"))
SIDEBOARD_KEYS = frozenset(("in", "out"))
PACE_KEYS = frozenset(("measure", "seconds_per_turn", "tells"))
INTERVIEW_KEYS = frozenset(("asked", "answered", "dont_remember"))

# Prose in the ledger is capped and never rolled up. The full account of a
# decision belongs in its review note, which `review_note` points at; a finding
# carries an identifier and a pointer. Printing every wording into the profile
# is what turned an 11 KB note into 59% quoted play-by-play.
NOTE_MAX_CHARS = 300
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

# A habit seen with only one deck is the deck's habit until a second deck shows
# it. Holding up mana badly in a control mirror says nothing about how someone
# plays aggro; it might be the archetype, the matchup, or one week of practice.
MIN_DECKS_FOR_PLAYER_HABIT = 2

# Below this many games, a personal matchup record is an anecdote and the
# profile says so in those words. Tournament data at any sample beats it.
MEANINGFUL_MATCHUP_GAMES = 20

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


# ------------------------------------------------------- the pattern registry

def load_patterns(path=None):
    """Read play_patterns.json. Returns (patterns, error).

    `patterns` maps pattern_id to {kind, label, description, polarity}. An
    error string means the registry could not be used, and the caller stops:
    without the vocabulary there is nothing to count findings under, and
    guessing labels from free text is the bug this replaced.
    """
    path = path or os.path.join(SCRIPT_DIR, PATTERNS_NAME)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        return {}, "%s: %s" % (path, exc)
    except ValueError as exc:
        return {}, "%s is not valid JSON (%s)" % (path, exc)

    patterns = raw.get("patterns")
    if not isinstance(patterns, dict) or not patterns:
        return {}, "%s has no `patterns` object" % path

    problems = []
    clean = {}
    for pid, spec in sorted(patterns.items()):
        if not isinstance(spec, dict):
            problems.append("pattern %r is not an object" % pid)
            continue
        if spec.get("kind") not in KINDS:
            problems.append("pattern %r kind %r is not in the fixed vocabulary"
                            % (pid, spec.get("kind")))
        if not isinstance(spec.get("label"), str) or not spec["label"].strip():
            problems.append("pattern %r has no label" % pid)
        if spec.get("polarity") not in POLARITIES:
            problems.append("pattern %r polarity %r is not one of %s"
                            % (pid, spec.get("polarity"), "/".join(POLARITIES)))
        clean[pid] = spec
    if problems:
        return {}, "%s: %s" % (path, "; ".join(problems))
    return clean, None


# ------------------------------------------------------------------- validation

def _is_date(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _unknown_keys(obj, allowed, label, bad):
    extra = sorted(set(obj) - set(allowed))
    if extra:
        bad("%s has unrecognised key(s) %s. A field this does not know is a "
            "field it silently ignores, so it is a problem rather than a "
            "passing value." % (label, ", ".join(repr(k) for k in extra)))


def validate_row(row, line_no, patterns=None):
    """Return a list of problems with one ledger row. Empty means usable.

    An absent value is not a passing value, and neither is an unrecognised one.
    A row missing a field this counts on is excluded and reported, never waved
    through and counted as something. A row carrying a key this does not know
    is reported for the same reason: `opening_hand` instead of `hand` cost
    three recorded opening hands on 2026-09-04 and the run exited 0.
    """
    problems = []
    patterns = patterns or {}

    def bad(msg):
        problems.append("line %d: %s" % (line_no, msg))

    if not isinstance(row, dict):
        bad("not a JSON object")
        return problems

    _unknown_keys(row, ROW_KEYS, "row", bad)

    if not _is_date(row.get("date")):
        bad("date %r is not YYYY-MM-DD" % (row.get("date"),))
    for field in ("your_deck", "their_deck", "session_id", "match_id"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            bad("%s is missing or empty" % field)
    if not isinstance(row.get("game"), int) or row["game"] < 1:
        bad("game %r is not a positive integer" % (row.get("game"),))
    if row.get("result") not in RESULTS:
        bad("result %r is not one of %s" % (row.get("result"), "/".join(RESULTS)))
    note_ref = row.get("review_note")
    if note_ref is not None and (not isinstance(note_ref, str)
                                 or not note_ref.strip()):
        bad("review_note is present but not a filename")

    findings = row.get("findings")
    if not isinstance(findings, list):
        bad("findings is missing or not a list (use [] for a clean game)")
        findings = []

    for i, f in enumerate(findings):
        where = "finding %d" % i
        if not isinstance(f, dict):
            bad("%s is not an object" % where)
            continue
        _unknown_keys(f, FINDING_KEYS, where, bad)
        kind = f.get("kind")
        if kind not in KINDS:
            bad("%s kind %r is not in the fixed vocabulary" % (where, kind))
        pid = f.get("pattern_id")
        if not isinstance(pid, str) or pid not in patterns:
            bad("%s pattern_id %r is not in %s. Add the pattern to the "
                "registry rather than inline: a habit spelled two ways counts "
                "as two habits." % (where, pid, PATTERNS_NAME))
        elif patterns[pid]["kind"] != kind:
            bad("%s pattern_id %r belongs to kind %r, not %r"
                % (where, pid, patterns[pid]["kind"], kind))
        if f.get("grade") not in GRADES:
            bad("%s grade %r is not one of %s"
                % (where, f.get("grade"), "/".join(GRADES)))
        phase = f.get("phase")
        if phase not in PHASES:
            bad("%s phase %r is not one of %s"
                % (where, phase, "/".join(PHASES)))
        turn = f.get("turn")
        if phase == "in-game":
            if not isinstance(turn, int) or turn < 1:
                bad("%s is in-game, so turn %r has to be a positive integer"
                    % (where, turn))
        elif turn is not None:
            bad("%s is %s, which happens at no turn, so turn %r does not "
                "belong on it" % (where, phase, turn))
        # A blind mulligan is game 1 and boarding happens between games, so a
        # phase that disagrees with the game number means one of the two is
        # wrong and the finding would be counted under the other kind.
        rule = PHASE_GAME_RULE.get(phase)
        if rule and isinstance(row.get("game"), int):
            low, high = rule
            if row["game"] < low or (high is not None and row["game"] > high):
                bad("%s is %s, which does not happen in game %d"
                    % (where, phase, row["game"]))
        fnote = f.get("note")
        if fnote is not None:
            if not isinstance(fnote, str):
                bad("%s note is not a string" % where)
            elif len(fnote) > NOTE_MAX_CHARS:
                bad("%s note is %d characters, over the %d cap. The account of "
                    "a decision lives in the review note; this is a label."
                    % (where, len(fnote), NOTE_MAX_CHARS))

    hand = row.get("hand")
    if hand is not None:
        if not isinstance(hand, dict):
            bad("hand is not an object")
        else:
            _unknown_keys(hand, HAND_KEYS, "hand", bad)
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

    board = row.get("sideboard")
    if board is not None:
        if not isinstance(board, dict):
            bad("sideboard is not an object")
        else:
            _unknown_keys(board, SIDEBOARD_KEYS, "sideboard", bad)
            for side in ("in", "out"):
                cards = board.get(side, [])
                if not isinstance(cards, list) or not all(
                        isinstance(c, str) and c.strip() for c in cards):
                    bad("sideboard %r is not a list of card names" % side)

    pace = row.get("pace")
    if pace is not None:
        if not isinstance(pace, dict):
            bad("pace is not an object")
        else:
            _unknown_keys(pace, PACE_KEYS, "pace", bad)
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

    iv = row.get("interview")
    if iv is not None:
        if not isinstance(iv, dict):
            bad("interview is not an object")
        else:
            _unknown_keys(iv, INTERVIEW_KEYS, "interview", bad)

    return problems


def read_ledger(path, patterns=None):
    """Parse the ledger. Returns (rows, problems, unreadable).

    An unreadable file is not a clean file, so an OSError comes back as a
    reported problem rather than an empty list. This vault sits on OneDrive,
    where a cloud-only placeholder raises OSError on a file that lists fine.

    (match_id, game) is the row's identity and it has to be unique. Appending
    the same game twice doubles every count it touches, and nothing in the old
    schema could see it happen.
    """
    rows, problems, unreadable = [], [], None
    seen = {}

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
        row_problems = validate_row(row, line_no, patterns)
        if row_problems:
            problems.extend(row_problems)
            continue
        key = (row["match_id"], row["game"])
        if key in seen:
            problems.append(
                "line %d: match %s game %d is already on line %d. Appending a "
                "game twice doubles every count it touches."
                % (line_no, key[0], key[1], seen[key]))
            continue
        seen[key] = line_no
        rows.append(row)

    return rows, problems, unreadable


# ------------------------------------------------------------------- rollup

def classify(occurrences, sessions, grades, min_occurrences, min_sessions):
    """Which one bucket a pattern belongs in. Exactly one, always.

    The old code could put the same row under Trends and under Strengths in the
    same note, because it computed the two independently off a `kind` that
    lumped "spends removal on the first target" together with "holds removal
    for the real threat". Once patterns are separate those are two rows with
    two different grade mixes, and one bucket each is the honest answer.

        leak        cleared the bar, and punt+close outnumber correct
        strength    cleared the bar, and correct outnumbers punt+close
        mixed       cleared the bar, and they tie
        watching    2 or more occurrences that did not clear the bar
        below-bar   a single occurrence. Stays in the review note
    """
    if occurrences >= min_occurrences and sessions >= min_sessions:
        problems = grades.get("punt", 0) + grades.get("close", 0)
        correct = grades.get("correct", 0)
        if problems > correct:
            return "leak"
        if correct > problems:
            return "strength"
        return "mixed"
    if occurrences >= 2:
        return "watching"
    return "below-bar"


def hand_keeps_top(card_keeps, limit=10):
    """Cards that show up most often in hands this player chose to keep.

    Not a judgement, a frequency. It answers "what am I actually keeping" with
    a count rather than an impression, which is the same trade the habit table
    makes.
    """
    return [{"card": c, "hands": n} for c, n in card_keeps.most_common(limit)]


def roll_up(rows, min_occurrences, min_sessions, patterns=None):
    """Count the ledger. No judgement here, just arithmetic.

    Grouping is on `pattern_id`, not on `kind`. Kind counts how many decisions
    of a type got made, which tracks games played rather than mistakes made:
    every game contains removal-timing decisions, so any kind clears a
    three-occurrence bar within a few sessions no matter how well someone
    played. A pattern counts the behaviour.
    """
    patterns = patterns or {}
    sessions = sorted({r["session_id"] for r in rows})
    # Sessions in which each deck was played. Fading is measured against the
    # sessions where the pattern's deck was actually on the table, because
    # switching decks for a fortnight is not the same event as fixing a habit.
    # Without this, every Yawgmoth pattern faded the moment three UW sessions
    # went by, which reports a habit as cured on no evidence at all.
    deck_sessions = defaultdict(set)
    for r in rows:
        deck_sessions[r["your_deck"]].add(r["session_id"])

    by_pattern = defaultdict(lambda: {
        "kind": None,
        "occurrences": 0,
        "games": set(),
        "sessions": set(),
        "decks": set(),
        "grades": Counter(),
        "prompted": 0,
        "intent_mismatch": 0,
        "last_seen": None,
        "turns": [],
        "citations": [],
        "phases": Counter(),
    })

    matchups = defaultdict(lambda: {"games": 0, "results": Counter(),
                                    "dates": set()})
    boarded_in = defaultdict(Counter)
    boarded_out = defaultdict(Counter)

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
    # Blind keeps and informed keeps, counted apart. Game 1 is made with no
    # idea what is across the table; game 2 and 3 are made knowing the matchup.
    # Averaging the two answers "what do I keep" with a number that describes
    # neither situation.
    hands_by_knowledge = defaultdict(lambda: {
        "games": 0, "results": Counter(), "lands": [], "outcomes": Counter(),
        "shapes": Counter(), "kept_at": Counter(),
    })
    mulligans = defaultdict(lambda: {
        "occurrences": 0, "grades": Counter(), "patterns": Counter(),
    })

    for r in rows:
        game_key = (r["match_id"], r["game"])
        decks[r["your_deck"]] += 1
        opponents[r["their_deck"]] += 1
        results[r["result"]] += 1

        opp = matchups[r["their_deck"]]
        opp["games"] += 1
        opp["results"][r["result"]] += 1
        opp["dates"].add(r["date"])

        # Counted per game, not per copy. Four copies of one card in one game is
        # still one boarding decision, and counting copies would report a
        # four-of as four times the habit of a one-of.
        board = r.get("sideboard") or {}
        for card in {c.strip() for c in board.get("in", []) or []}:
            boarded_in[r["their_deck"]][card] += 1
        for card in {c.strip() for c in board.get("out", []) or []}:
            boarded_out[r["their_deck"]][card] += 1

        for f in r["findings"]:
            k = by_pattern[f["pattern_id"]]
            k["kind"] = f["kind"]
            k["occurrences"] += 1
            k["games"].add(game_key)
            k["sessions"].add(r["session_id"])
            k["decks"].add(r["your_deck"])
            k["grades"][f["grade"]] += 1
            k["phases"][f["phase"]] += 1
            if f.get("turn") is not None:
                k["turns"].append(f["turn"])
            # The pointer back into the prose. The profile cites the review note
            # instead of quoting it, which is what keeps the aggregate small and
            # the detail one click away rather than four copies deep.
            if r.get("review_note"):
                k["citations"].append({
                    "review_note": r["review_note"],
                    "date": r["date"],
                    "game": r["game"],
                    "phase": f["phase"],
                    "turn": f.get("turn"),
                    "grade": f["grade"],
                })
            if f["phase"] in MULLIGAN_PHASES:
                m = mulligans[f["phase"]]
                m["occurrences"] += 1
                m["grades"][f["grade"]] += 1
                m["patterns"][f["pattern_id"]] += 1
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
            # A game 1 hand is a blind keep by definition. Derived from the
            # game number rather than stored, because a stored copy could
            # disagree with it and there is only one right answer.
            knowledge = "blind" if r["game"] == 1 else "post-board"
            kb = hands_by_knowledge[knowledge]
            kb["games"] += 1
            kb["results"][r["result"]] += 1
            kb["lands"].append(hand["lands"])
            kb["outcomes"][outcome] += 1
            kb["shapes"][hand["shape"]] += 1
            kb["kept_at"][size] += 1
            for card in hand["cards"]:
                card_keeps[card.strip()] += 1
            hand_rows.append({
                "date": r["date"],
                "knowledge": knowledge,
                "session_id": r["session_id"],
                "match_id": r["match_id"],
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

    total_games = len({(r["match_id"], r["game"]) for r in rows})

    habits = []
    for pid, k in by_pattern.items():
        occurrences = k["occurrences"]
        n_sessions = len(k["sessions"])
        spec = patterns.get(pid, {})

        bucket = classify(occurrences, n_sessions, k["grades"],
                          min_occurrences, min_sessions)

        # A pattern that cleared the bar and has gone quiet is kept, not
        # deleted. Someone who fixed a leak gets to see that they fixed it.
        # Quiet is measured against the sessions where one of this pattern's
        # own decks was played, so a deck sitting in its box does not fade its
        # habits.
        relevant = set()
        for deck in k["decks"]:
            relevant |= deck_sessions.get(deck, set())
        recent = sorted(relevant)[-FADE_AFTER_SESSIONS:]
        faded = bool(
            bucket in {"leak", "strength", "mixed"}
            and recent
            and not (k["sessions"] & set(recent))
        )

        prompted_share = (k["prompted"] / occurrences) if occurrences else 0.0
        problems_seen = k["grades"].get("punt", 0) + k["grades"].get("close", 0)
        # Weighted, because a punt is worse than a close. Ranking them equally
        # is how a pattern with six closes and no punts topped the work-on line.
        problem_score = sum(GRADE_WEIGHTS.get(g, 0) * n
                            for g, n in k["grades"].items())

        # The registry declares what shape a pattern is. The ledger measures
        # what it actually graded. Where they disagree, one of the two is wrong
        # and the profile says so rather than quietly trusting either.
        declared = spec.get("polarity", "neutral")
        measured = bucket if bucket in {"leak", "strength"} else None
        polarity_conflict = bool(
            measured and declared in {"leak", "strength"} and measured != declared)

        habits.append({
            "pattern_id": pid,
            "kind": k["kind"],
            "label": spec.get("label") or pid,
            "description": spec.get("description") or "",
            "polarity": declared,
            "bucket": "faded" if faded else bucket,
            "polarity_conflict": polarity_conflict,
            "occurrences": occurrences,
            "problem_occurrences": problems_seen,
            "problem_score": problem_score,
            "games": len(k["games"]),
            "sessions": n_sessions,
            "session_ids": sorted(k["sessions"]),
            "decks": sorted(k["decks"]),
            "cross_deck": len(k["decks"]) >= MIN_DECKS_FOR_PLAYER_HABIT,
            "grades": dict(k["grades"]),
            "prompted_by_profile": k["prompted"],
            "prompted_share": round(prompted_share, 3),
            "bias_flag": prompted_share > BIAS_FLAG_SHARE and occurrences >= 2,
            "intent_mismatch": k["intent_mismatch"],
            "last_seen": k["last_seen"],
            "turns": sorted(k["turns"]),
            "phases": dict(sorted(k["phases"].items())),
            "citations": sorted(k["citations"],
                                key=lambda c: (c["date"], c["game"]))[-3:],
        })

    habits.sort(key=lambda h: (-h["occurrences"], h["pattern_id"]))

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
        "by_knowledge": {
            k: {
                "games": v["games"],
                "record": "-".join(str(v["results"].get(g, 0)) for g in RESULTS),
                "mean_lands": round(sum(v["lands"]) / len(v["lands"]), 1)
                if v["lands"] else None,
                "outcomes": dict(sorted(v["outcomes"].items())),
                "shapes": dict(v["shapes"].most_common()),
                "kept_at": dict(sorted(v["kept_at"].items(), reverse=True)),
            }
            for k, v in sorted(hands_by_knowledge.items())
        },
        "index": sorted(hand_rows, key=lambda h: (h["date"], h["game"])),
    }

    mulligan_rows = {
        phase: {
            "occurrences": v["occurrences"],
            "grades": dict(v["grades"]),
            "patterns": dict(v["patterns"].most_common()),
        }
        for phase, v in sorted(mulligans.items())
    }

    matchup_rows = []
    for opp, v in sorted(matchups.items()):
        matchup_rows.append({
            "their_deck": opp,
            "games": v["games"],
            "record": "-".join(str(v["results"].get(g, 0)) for g in RESULTS),
            "wins": v["results"].get("W", 0),
            "dates": sorted(v["dates"]),
            "meaningful": v["games"] >= MEANINGFUL_MATCHUP_GAMES,
            "boarded_in": [{"card": c, "games": n}
                           for c, n in boarded_in[opp].most_common()],
            "boarded_out": [{"card": c, "games": n}
                            for c, n in boarded_out[opp].most_common()],
        })
    matchup_rows.sort(key=lambda m: (-m["games"], m["their_deck"]))

    all_dates = sorted({r["date"] for r in rows})
    return {
        "games": total_games,
        "rows": len(rows),
        "hands": hands,
        "mulligans": mulligan_rows,
        "matchups": matchup_rows,
        "sessions": len(sessions),
        "session_ids": sessions,
        "session_dates": all_dates,
        "first_date": all_dates[0] if all_dates else None,
        "last_date": all_dates[-1] if all_dates else None,
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


def _table(rollup, buckets, cross_deck_only=False):
    rows = [h for h in rollup["habits"] if h["bucket"] in buckets]
    if cross_deck_only:
        rows = [h for h in rows if h["cross_deck"]]
    if not rows:
        return None
    out = ["| Pattern | Kind | Count | Sessions | Decks | Grade split | Last seen |",
           "|---|---|---|---|---|---|---|"]
    for h in rows:
        out.append("| %s | %s | %d in %d game(s) | %d | %s | %s | %s |" % (
            h["label"],
            h["kind"],
            h["occurrences"],
            h["games"],
            h["sessions"],
            ", ".join(h["decks"]) or "unknown",
            _grade_split(h["grades"]),
            h["last_seen"] or "unknown",
        ))
    return "\n".join(out)


def _cite(h):
    """Where to go and read what actually happened.

    The profile carries the count and a pointer. The prose stays in the review
    note, in one place, instead of being copied into the ledger and then into
    two profile notes on top of that.
    """
    if not h["citations"]:
        return ""
    parts = []
    for c in h["citations"]:
        where = ("turn %d" % c["turn"]) if c["turn"] is not None else c["phase"]
        parts.append("`%s` G%d %s" % (c["review_note"], c["game"], where))
    return "Read it in: %s." % "; ".join(parts)


PHASE_WORDS = {
    "mulligan-blind": "blind, game 1",
    "mulligan-post-board": "post-board, knowing the matchup",
    "sideboard": "boarding",
    "in-game": "in game",
}


def _classification_table(rollup, cross_deck_only=False):
    """Every pattern that cleared the bar, in one table, classified.

    The per-bucket sections below carry the argument. This is the version you
    can read in one glance, which is what a profile is for.
    """
    order = {"leak": 0, "mixed": 1, "strength": 2, "faded": 3}
    rows = [h for h in rollup["habits"] if h["bucket"] in order]
    if cross_deck_only:
        rows = [h for h in rows if h["cross_deck"]]
    if not rows:
        return None
    rows.sort(key=lambda h: (order[h["bucket"]], -h["problem_score"],
                             -h["occurrences"], h["pattern_id"]))
    out = ["| Pattern | Classification | Kind | Count | Grade split | Decks |",
           "|---|---|---|---|---|---|"]
    for h in rows:
        label = {"leak": "**Leak**", "strength": "Strength",
                 "mixed": "Mixed", "faded": "Faded"}[h["bucket"]]
        out.append("| %s | %s | %s | %d in %d game(s) | %s | %d |" % (
            h["label"], label, h["kind"], h["occurrences"], h["games"],
            _grade_split(h["grades"]), len(h["decks"])))
    return "\n".join(out)


def _mulligan_section(rollup, lines):
    """Blind keeps and informed keeps, counted apart.

    A game 1 keep is judged against the format because nothing else is known.
    A game 2 or 3 keep is judged against a deck you have now seen, and the same
    six cards can be a keep in one and a ship in the other.
    """
    lines += ["## Mulligans", ""]
    mull = rollup["mulligans"]
    hands = rollup["hands"].get("by_knowledge") or {}
    if not mull and not hands:
        lines += ["Nothing recorded yet.", ""]
        return

    lines += ["Blind and post-board keeps are counted apart. A game 1 keep is "
              "made with no idea what is across the table; a game 2 or 3 keep "
              "is made knowing the matchup. The same six cards can be a keep "
              "in one and a ship in the other, so a single number describes "
              "neither.", ""]

    if hands:
        lines += ["| Keeps | Hands | Record (W-L-D) | Mean lands | Sizes | Outcomes |",
                  "|---|---|---|---|---|---|"]
        for name in ("blind", "post-board"):
            v = hands.get(name)
            if not v:
                continue
            sizes = ", ".join("%d x%d" % (s, n)
                              for s, n in v["kept_at"].items()) or "none"
            outcomes = ", ".join("%s %d" % (k, n)
                                 for k, n in v["outcomes"].items()) or "none"
            lines.append("| %s | %d | %s | %s | %s | %s |" % (
                name, v["games"], v["record"],
                "n/a" if v["mean_lands"] is None else v["mean_lands"],
                sizes, outcomes))
        lines.append("")

    if mull:
        for phase in MULLIGAN_PHASES:
            v = mull.get(phase)
            if not v:
                continue
            pats = ", ".join("%s (%d)" % (p, n)
                             for p, n in v["patterns"].items())
            lines += ["**%s.** %d graded finding(s): %s. Patterns: %s."
                      % (PHASE_WORDS[phase].capitalize(), v["occurrences"],
                         _grade_split(v["grades"]), pats), ""]
    else:
        lines += ["No mulligan has been graded yet. The hands above are "
                  "recorded, which is what makes a future grade arguable.", ""]


def _habit_note(h, scope_line=""):
    """One paragraph for one pattern. Count, caveats, citation. No prose dump."""
    note = ["**%s** (`%s`). %d time(s) in %d game(s) across %d session(s), last "
            "on %s." % (h["label"], h["pattern_id"], h["occurrences"],
                        h["games"], h["sessions"], h["last_seen"])]
    if h["description"]:
        note.append(h["description"])
    phases = h.get("phases") or {}
    if set(phases) & set(MULLIGAN_PHASES):
        note.append("Split %s." % ", ".join(
            "%d %s" % (n, PHASE_WORDS.get(p, p)) for p, n in phases.items()))
    if h["turns"]:
        note.append("Turns: %s." % ", ".join(str(t) for t in h["turns"]))
    if scope_line:
        note.append(scope_line)
    if h["intent_mismatch"]:
        note.append("In %d of these the stated plan and the line disagreed, so "
                    "this reads as execution rather than judgement."
                    % h["intent_mismatch"])
    if h["polarity_conflict"]:
        note.append("**Declared %s in the registry and grading as a %s here.** "
                    "One of the two is wrong: either the pattern is mislabelled "
                    "or these findings are." % (h["polarity"], h["bucket"]))
    if h["bias_flag"]:
        note.append("**Discount this count.** %d of %d were found because the "
                    "profile predicted them, so it is partly confirmation."
                    % (h["prompted_by_profile"], h["occurrences"]))
    cite = _cite(h)
    if cite:
        note.append(cite)
    return " ".join(note)


def deck_filename(deck):
    """The per-deck profile's filename. ASCII, no path separators.

    Deck names come from the ledger, which comes from a review, which takes them
    from the user. A name with a slash in it would otherwise write outside the
    insights folder.
    """
    safe = "".join(c if (c.isalnum() or c in " -_") else "-" for c in deck)
    safe = " ".join(safe.split()) or "Unnamed Deck"
    return DECK_PROFILE_NAME % safe


def roll_up_by_deck(rows, min_occurrences, min_sessions, patterns=None):
    """One rollup per deck, keyed by deck name.

    Counting each deck separately is what makes the cross-deck layer mean
    anything: a habit that only ever shows up on one deck is that deck's habit
    until a second deck shows it too.
    """
    by_deck = defaultdict(list)
    for r in rows:
        by_deck[r["your_deck"]].append(r)
    return {
        deck: roll_up(deck_rows, min_occurrences, min_sessions, patterns)
        for deck, deck_rows in sorted(by_deck.items())
    }


def work_on(rollup, cross_deck_only=False):
    """The one thing to practise, or None.

    Ranked on weighted problem grades among patterns that graded as a leak.
    A strength is not eligible, and neither is a profile-prompted count.
    Mixed patterns are the fallback, because a pattern splitting evenly is
    still a coin flip worth practising once no clear leak has cleared the bar.
    """
    pool = rollup["habits"]
    if cross_deck_only:
        pool = [h for h in pool if h["cross_deck"]]
    for buckets in ({"leak"}, {"mixed"}):
        cands = [h for h in pool
                 if h["bucket"] in buckets
                 and not h["bias_flag"]
                 and h["problem_score"] >= 1]
        if cands:
            cands.sort(key=lambda h: (-h["problem_score"], -h["occurrences"],
                                      h["pattern_id"]))
            return cands[0]
    return None


def _matchup_section(rollup, lines):
    """Personal matchup record. Never a win rate, and never called data."""
    lines += ["## Matchups played (personal experience)", ""]
    matchups = rollup["matchups"]
    if not matchups:
        lines += ["Nothing reviewed yet.", ""]
        return
    lines += ["This is a record of games reviewed here, not tournament data. "
              "Where it disagrees with the matchup table in an archetype note, "
              "**the archetype note wins**: it is built on hundreds of matches "
              "and this is built on a handful. Under %d games a line here is an "
              "anecdote, and it is labelled as one."
              % MEANINGFUL_MATCHUP_GAMES, ""]
    lines += ["| Opponent | Games | Record (W-L-D) | Sample | Last played |",
              "|---|---|---|---|---|"]
    for m in matchups:
        lines.append("| %s | %d | %s | %s | %s |" % (
            m["their_deck"], m["games"], m["record"],
            "worth reading" if m["meaningful"] else "anecdote",
            m["dates"][-1] if m["dates"] else "unknown"))
    lines.append("")


def _sideboard_section(rollup, lines):
    lines += ["## Sideboarding", ""]
    boarded = [m for m in rollup["matchups"]
               if m["boarded_in"] or m["boarded_out"]]
    if not boarded:
        lines += ["No boarding recorded yet. Reviews log what came in and what "
                  "went out for games two and three.", ""]
        return
    for m in boarded:
        ins = ", ".join("%s (%d)" % (c["card"], c["games"])
                        for c in m["boarded_in"]) or "nothing recorded"
        outs = ", ".join("%s (%d)" % (c["card"], c["games"])
                         for c in m["boarded_out"]) or "nothing recorded"
        lines += ["**vs %s** (%d game(s), %s)" % (m["their_deck"], m["games"],
                                                  m["record"]), "",
                  "- In: %s" % ins,
                  "- Out: %s" % outs, ""]


def render_deck_profile(deck, rollup, problems, today=None):
    """The note for one deck. Habits here may be the deck rather than the player.

    The cross-deck note is where a habit gets promoted to something about how
    this person plays, and only after a second deck shows it.
    """
    today = today or date.today().isoformat()
    lines = [
        "---",
        "author: claude",
        "type: solution",
        "project: MTG Tournament Analysis Skill",
        "date: %s" % today,
        "tags: [mtg, vod-review, play-profile, deck-profile]",
        "deck: %s" % deck,
        "games_reviewed: %d" % rollup["games"],
        "range: %s to %s" % (rollup["first_date"] or "n/a",
                             rollup["last_date"] or "n/a"),
        "generated_by: play_profile.py",
        "---",
        "",
        "# Play profile: %s" % deck,
        "",
    ]

    record = "-".join(str(rollup["results"].get(g, 0)) for g in RESULTS)
    lines += [
        "**%d game(s) across %d session(s), %s to %s.** Record %s (W-L-D)."
        % (rollup["games"], rollup["sessions"], rollup["first_date"],
           rollup["last_date"], record),
        "",
        "Everything here is about this deck. A habit in this note is the deck's "
        "until a second deck shows it too, at which point `[C] Play Profile.md` "
        "picks it up as a habit of the player. See that note for the cross-deck "
        "picture.",
        "",
    ]

    table = _classification_table(rollup)
    if table:
        lines += ["## At a glance", "",
                  "Every pattern on this deck that cleared the bar, in one "
                  "table. The sections below carry the argument.", "",
                  table, ""]

    for heading, buckets, blurb in (
        ("Leaks on this deck", {"leak"},
         "Cleared the bar, and the punt-and-close grades outnumber the correct "
         "ones."),
        ("Strengths on this deck", {"strength"},
         "Cleared the same bar the other way up. A profile that lists only "
         "leaks is a worse tool than one that also says what someone does "
         "well."),
        ("Mixed on this deck", {"mixed"},
         "Cleared the bar with the grades split evenly. Right about as often "
         "as not."),
    ):
        lines += ["## %s" % heading, ""]
        table = _table(rollup, buckets)
        if table:
            lines += [blurb, "", table, ""]
            for h in rollup["habits"]:
                if h["bucket"] not in buckets:
                    continue
                scope = ("Also seen on other decks, so the cross-deck note "
                         "carries it." if h["cross_deck"]
                         else "Only seen on this deck so far.")
                lines += [_habit_note(h, scope), ""]
        else:
            lines += ["Nothing here yet.", ""]

    for heading, buckets, blurb in (
        ("Watching on this deck", {"watching"},
         "Two or more occurrences that have not cleared the bar. Counted, not "
         "concluded."),
        ("Faded on this deck", {"faded"},
         "Cleared the bar once and has not appeared in the last %d session(s)."
         % FADE_AFTER_SESSIONS),
    ):
        table = _table(rollup, buckets)
        if table:
            lines += ["## %s" % heading, "", blurb, "", table, ""]

    lines += ["## What to work on with this deck", ""]
    top = work_on(rollup)
    if top:
        lines += ["**%s** (`%s`). %d of %d occurrence(s) graded a problem (%s), "
                  "across %d session(s). %s"
                  % (top["label"], top["pattern_id"],
                     top["problem_occurrences"], top["occurrences"],
                     _grade_split(top["grades"]), top["sessions"], _cite(top)),
                  ""]
    else:
        lines += ["Nothing has cleared the bar as a leak on this deck.", ""]

    _mulligan_section(rollup, lines)
    _matchup_section(rollup, lines)
    _sideboard_section(rollup, lines)

    lines += ["## Opening hands on this deck", ""]
    hands = rollup["hands"]
    if hands["recorded"]:
        lines += ["| Kept at | Games | Record (W-L-D) | Mean lands | Outcomes |",
                  "|---|---|---|---|---|"]
        for size, v in hands["by_size"].items():
            outcomes = ", ".join("%s %d" % (k, n)
                                 for k, n in v["outcomes"].items()) or "none"
            lines.append("| %d | %d | %s | %s | %s |" % (
                size, v["games"], v["record"],
                "n/a" if v["mean_lands"] is None else v["mean_lands"], outcomes))
        lines += ["", "Every hand card-for-card: `python play_profile.py "
                  "--hands`.", ""]
    else:
        lines += ["No hands recorded for this deck yet.", ""]

    if problems:
        lines += ["---", "", "## Data problems", "",
                  "**%d ledger line(s) could not be used** across the whole "
                  "ledger. Run `python play_profile.py --validate`."
                  % len(problems), ""]

    return "\n".join(lines)


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
        "Rolled up by `play_profile.py` from `play_log.jsonl`, counted under the "
        "patterns in `play_patterns.json`. Every line here is countable back to "
        "a review note and cites the one to read. The bar is %d occurrence(s) "
        "across %d session(s), and a pattern that clears it lands in exactly "
        "one of the sections below."
        % (bar["min_occurrences"], bar["min_sessions"]),
        "",
    ]

    if rollup["games"] < 5:
        lines += [
            "**Sample is thin.** %d games is not enough to call a habit. Read the "
            "sections below as what is being watched, not as conclusions."
            % rollup["games"],
            "",
        ]

    # Decks
    lines += ["## Decks", ""]
    lines += ["Each deck has its own note, and this one carries what shows up "
              "across more than one of them. A habit seen with a single deck "
              "stays in that deck's note: it might be the archetype, the "
              "matchup, or a week of practice rather than how this person "
              "plays.", ""]
    lines += ["| Deck | Games | Note |", "|---|---|---|"]
    for deck, n in rollup["your_decks"].items():
        lines.append("| %s | %d | `%s` |" % (deck, n, deck_filename(deck)))
    lines.append("")

    cleared = [h for h in rollup["habits"]
               if h["bucket"] in {"leak", "strength", "mixed", "faded"}
               and not h["cross_deck"]]
    watched = [h for h in rollup["habits"]
               if h["bucket"] == "watching" and not h["cross_deck"]]
    if cleared:
        lines += ["Cleared the bar on one deck only, so they live in that "
                  "deck's note rather than here:", ""]
        lines += ["| Pattern | Bucket | Deck | Count |", "|---|---|---|---|"]
        for h in cleared:
            lines.append("| %s | %s | %s | %d |"
                         % (h["label"], h["bucket"], h["decks"][0],
                            h["occurrences"]))
        lines.append("")
    if watched:
        lines += ["%d more single-deck pattern(s) sit under the bar at two "
                  "occurrences. The deck notes count them." % len(watched), ""]

    table = _classification_table(rollup, cross_deck_only=True)
    if table:
        lines += ["## At a glance", "",
                  "Every cross-deck pattern that cleared the bar, classified. "
                  "One row per pattern and one classification each, so nothing "
                  "here is a leak and a strength at the same time. The sections "
                  "below carry the argument and the citations.", "",
                  table, ""]

    # Leaks, strengths, mixed. One bucket per pattern, so nothing appears twice.
    lines += ["## Leaks", ""]
    lines += ["A pattern here has cleared the bar, graded punt-and-close more "
              "often than correct, **and** shown up with at least %d deck(s). "
              "That last condition is what separates how you play from what a "
              "deck makes you do." % MIN_DECKS_FOR_PLAYER_HABIT, ""]
    table = _table(rollup, {"leak"}, cross_deck_only=True)
    if table:
        lines += [table, ""]
        for h in [x for x in rollup["habits"]
                  if x["bucket"] == "leak" and x["cross_deck"]]:
            lines += [_habit_note(h), ""]
    else:
        lines += ["Nothing has cleared the bar as a leak across two decks.", ""]

    lines += ["## Strengths", ""]
    lines += ["The same bar the other way up: cleared it, and graded correct "
              "more often than not. A profile that lists only leaks is a worse "
              "tool than one that also says what you do well, and it is the "
              "default failure of every automated review.", ""]
    table = _table(rollup, {"strength"}, cross_deck_only=True)
    if table:
        lines += [table, ""]
        for h in [x for x in rollup["habits"]
                  if x["bucket"] == "strength" and x["cross_deck"]]:
            lines += [_habit_note(h), ""]
    else:
        lines += ["Nothing has cleared the bar as a strength across two decks. "
                  "This section needs `correct` grades, which is the bucket a "
                  "review has to be honest to use.", ""]

    table = _table(rollup, {"mixed"}, cross_deck_only=True)
    if table:
        lines += ["## Mixed", "",
                  "Cleared the bar with the grades split evenly. Right about as "
                  "often as not, which is its own kind of finding.", "",
                  table, ""]
        for h in [x for x in rollup["habits"]
                  if x["bucket"] == "mixed" and x["cross_deck"]]:
            lines += [_habit_note(h), ""]

    conflicts = [h for h in rollup["habits"] if h["polarity_conflict"]]
    if conflicts:
        lines += ["## Registry disagrees with the grades", "",
                  "These patterns are declared one way in `play_patterns.json` "
                  "and grading the other way here. Either the label is wrong or "
                  "the grades are, and both are worth fixing.", ""]
        for h in conflicts:
            lines += ["- **%s** (`%s`) is declared %s and grading as a %s: %s."
                      % (h["label"], h["pattern_id"], h["polarity"],
                         h["bucket"], _grade_split(h["grades"]))]
        lines.append("")

    _mulligan_section(rollup, lines)

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
    table = _table(rollup, {"watching"}, cross_deck_only=True)
    if table:
        lines += ["Two or more occurrences that have not cleared the bar. "
                  "Counted, not concluded.", "", table, ""]
    elif any(h["bucket"] == "watching" for h in rollup["habits"]):
        lines += ["Nothing across two decks. There are %d single-deck "
                  "pattern(s) at this level, counted in the deck notes."
                  % len([h for h in rollup["habits"]
                         if h["bucket"] == "watching"]), ""]
    else:
        lines += ["Nothing under the bar with two occurrences.", ""]

    # Faded
    lines += ["## Faded", ""]
    table = _table(rollup, {"faded"}, cross_deck_only=True)
    if table:
        lines += ["Cleared the bar once and has not appeared in the last %d "
                  "session(s). Kept rather than deleted: someone who fixed a "
                  "leak gets to see that they fixed it."
                  % FADE_AFTER_SESSIONS, "", table, ""]
    else:
        lines += ["Nothing has gone quiet yet.", ""]

    # What to work on. Ranked on weighted problem grades among leaks, so a punt
    # outweighs a close and a strength can never land here. Raw occurrences was
    # the wrong ranking and it failed in the obvious direction on 2026-09-04.
    lines += ["## What to work on", ""]
    top = work_on(rollup, cross_deck_only=True)
    if top:
        lines += ["**%s** (`%s`). %d of %d occurrence(s) graded a problem (%s), "
                  "across %d session(s) and %d deck(s). %s"
                  % (top["label"], top["pattern_id"],
                     top["problem_occurrences"], top["occurrences"],
                     _grade_split(top["grades"]), top["sessions"],
                     len(top["decks"]), top["description"]), ""]
        cite = _cite(top)
        if cite:
            lines += [cite, ""]
        lines += ["One thing, and it stays this one until the ledger shows it "
                  "moving. Ranked on a punt counting double a close, so a "
                  "pattern you mostly get right cannot land here on volume.",
                  ""]
    else:
        strengths = [h for h in rollup["habits"]
                     if h["bucket"] == "strength" and h["cross_deck"]]
        if strengths:
            lines += ["Nothing to name. Every pattern that cleared the bar "
                      "across two decks is listed above as a strength, so there "
                      "is no leak here with a count behind it. A clean profile "
                      "is a legitimate result and this line says so rather than "
                      "promoting the least-good strength.", ""]
        else:
            lines += ["Nothing has cleared the bar across two decks. The deck "
                      "notes have their own work-on line in the meantime.", ""]

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
    p.add_argument("--patterns", default=None,
                   help="Path to play_patterns.json")
    p.add_argument("--full", action="store_true",
                   help="with --json, include the card-for-card hand index. "
                        "Off by default: it is the biggest thing in the payload "
                        "and answering a question about habits never needs it")
    p.add_argument("--min-occurrences", type=int, default=DEFAULT_MIN_OCCURRENCES)
    p.add_argument("--min-sessions", type=int, default=DEFAULT_MIN_SESSIONS)
    args = p.parse_args()

    if args.min_occurrences < 1 or args.min_sessions < 1:
        print("The trend bar has to be at least 1 occurrence and 1 session.")
        return 1

    patterns, pattern_error = load_patterns(args.patterns)
    if pattern_error:
        print("Could not read the pattern registry: %s" % pattern_error)
        print("Without it there is no vocabulary to count findings under, and "
              "guessing a label from free text is the bug this replaced.")
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

    rows, problems, unreadable = read_ledger(ledger, patterns)

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

    rollup = roll_up(rows, args.min_occurrences, args.min_sessions, patterns)

    if args.json:
        # Aggregates only unless --full is asked for. The old payload came back
        # at 53 KB off a 46 KB ledger, so the cheap way to answer "what should I
        # work on" cost more than reading the raw data. The card-for-card hand
        # index was most of it, and `--hands` prints that on demand.
        payload = dict(rollup)
        if not args.full:
            payload["hands"] = {k: v for k, v in rollup["hands"].items()
                                if k != "index"}
            payload["matchups"] = [
                {k: v for k, v in m.items()
                 if k not in {"boarded_in", "boarded_out"}}
                for m in rollup["matchups"]
            ]
            # A single occurrence stays in its review note and never reaches
            # the profile, so it has no business in the payload either. The
            # description lives in the registry, which is keyed on the same id.
            drop = {"description", "session_ids", "citations",
                    "prompted_share", "turns"}
            payload["habits"] = [
                {k: v for k, v in h.items() if k not in drop}
                for h in rollup["habits"] if h["bucket"] != "below-bar"
            ]
            payload["below_bar"] = sorted(
                h["pattern_id"] for h in rollup["habits"]
                if h["bucket"] == "below-bar")
        top = work_on(rollup, cross_deck_only=True)
        payload["work_on"] = top["pattern_id"] if top else None
        print(json.dumps({"rollup": payload, "problems": problems},
                         indent=2, ensure_ascii=False))
        return 2 if problems else 0

    if args.hands:
        hands = rollup["hands"]
        print("\nKept hands: %s" % ledger)
        if not hands["recorded"]:
            print("  None recorded. Reviews log the kept hand card-for-card; "
                  "older ledger lines predate that.")
            return 2 if problems else 0
        print("  %d of %d game(s) carry a hand"
              % (hands["recorded"], hands["games_total"]))
        for name, v in (hands.get("by_knowledge") or {}).items():
            print("  %-10s %d hand(s), %s, mean %s land(s)"
                  % (name, v["games"], v["record"],
                     "n/a" if v["mean_lands"] is None else v["mean_lands"]))
        print()
        for h in hands["index"]:
            print("  %s  G%d  %-10s %s vs %s  %s  kept %d (%d land%s, %s, %s)%s"
                  % (h["date"], h["game"], h["knowledge"], h["your_deck"],
                     h["their_deck"], h["result"], h["kept_at"], h["lands"],
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
        print("  vocabularies: %d patterns, %d kinds, %d grades, %d phases, "
              "%d pace measures, %d tells, %d hand shapes, %d hand outcomes"
              % (len(patterns), len(KINDS), len(GRADES), len(PHASES),
                 len(PACE_MEASURES), len(PACE_TELLS), len(HAND_SHAPES),
                 len(HAND_OUTCOMES)))
        print("  hands recorded: %d of %d usable game(s)"
              % (rollup["hands"]["recorded"], rollup["hands"]["games_total"]))
        if problems:
            print("  The hand count above is of USABLE rows only. Rows rejected "
                  "above are not in it, so a rejected row is not a game whose "
                  "source never showed a hand.")
        unused = sorted(set(patterns) - {h["pattern_id"] for h in rollup["habits"]})
        if unused:
            print("  %d registry pattern(s) never seen in the ledger: %s"
                  % (len(unused), ", ".join(unused)))
        print()
        return 2 if problems else 0

    text = render_profile(rollup, problems)

    print("\nLedger: %s" % ledger)
    print("  %d game(s) over %d session(s), %s to %s"
          % (rollup["games"], rollup["sessions"],
             rollup["first_date"], rollup["last_date"]))
    buckets = {b: [h for h in rollup["habits"] if h["bucket"] == b]
               for b in ("leak", "strength", "mixed", "watching", "faded")}
    print("  %d leak(s), %d strength(s), %d mixed, %d watching, %d faded"
          % tuple(len(buckets[b]) for b in
                  ("leak", "strength", "mixed", "watching", "faded")))
    for b in ("leak", "strength", "mixed", "watching", "faded"):
        for h in buckets[b]:
            print("    %-9s %-42s %d in %d game(s), %d session(s), %d deck(s)%s"
                  % (b, h["pattern_id"], h["occurrences"], h["games"],
                     h["sessions"], len(h["decks"]),
                     "  [discount: profile-prompted]" if h["bias_flag"] else ""))
    conflicts = [h for h in rollup["habits"] if h["polarity_conflict"]]
    for h in conflicts:
        print("    CONFLICT  %s is declared %s and grading as a %s"
              % (h["pattern_id"], h["polarity"], h["bucket"]))
    top = work_on(rollup, cross_deck_only=True)
    print("  work on  %s" % (top["pattern_id"] if top else
                             "nothing has cleared the bar as a leak"))
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

    by_deck = roll_up_by_deck(rows, args.min_occurrences, args.min_sessions,
                              patterns)
    for deck, deck_rollup in by_deck.items():
        path = os.path.join(os.path.dirname(profile), deck_filename(deck))
        deck_text = render_deck_profile(deck, deck_rollup, problems)
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    if fh.read() == deck_text:
                        print("Deck profile already current: %s" % path)
                        continue
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(deck_text)
        except OSError as exc:
            print("Could not write the deck profile for %s: %s" % (deck, exc))
            continue
        print("Wrote %s  (%d game(s))" % (path, deck_rollup["games"]))
    print()
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
