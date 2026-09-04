"""
Tests for play_profile.py, the rollup behind vod-review's play profile.

Every assertion here pins a rule that the profile's credibility rests on. The
counts are the only reason a habit claim beats a vibe, so a counting bug is not
a cosmetic bug: it produces a confident, specific, wrong sentence about how
somebody plays.

Deck names in the fixtures are deliberately fake ("Test Deck A"). A placeholder
that is also a real archetype name stops being a placeholder the moment that
name gains behaviour in the alias table.
"""
import json
import os
import sys
import tempfile

import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

import play_profile as pp


# ------------------------------------------------------------------- fixtures

# A test registry rather than the shipped one, so these tests pin behaviour and
# not the current contents of play_patterns.json. Two patterns under the same
# kind is the case the old code could not represent: it is the whole reason
# `removal-timing` used to appear as a trend and a strength in one note.
TEST_PATTERNS = {
    "patterns": {
        "spends-removal-early": {
            "kind": "removal-timing",
            "label": "Spends removal on the first legal target",
            "description": "Fires the answer at whatever is in front of him.",
            "polarity": "leak",
        },
        "holds-removal-for-the-threat": {
            "kind": "removal-timing",
            "label": "Holds removal for the threat that matters",
            "description": "Waits for the card the deck is built around.",
            "polarity": "strength",
        },
        "taps-out-badly": {
            "kind": "mana-holding",
            "label": "Taps out with the answer in hand",
            "description": "Commits the turn's mana into open interaction.",
            "polarity": "leak",
        },
        "counts-the-hand": {
            "kind": "mulligan",
            "label": "Counts the hand before keeping",
            "description": "Works out what the hand needs and how many outs there are.",
            "polarity": "strength",
        },
        "snap-keeps": {
            "kind": "mulligan",
            "label": "Snap-keeps a seven without counting",
            "description": "Keeps on card count rather than on function.",
            "polarity": "leak",
        },
        "never-happens": {
            "kind": "combat-math",
            "label": "A pattern no fixture uses",
            "description": "Present so the unused-pattern report has something to say.",
            "polarity": "neutral",
        },
    }
}

_REGISTRY_DIR = tempfile.mkdtemp(prefix="play-patterns-")
PATTERNS_PATH = os.path.join(_REGISTRY_DIR, pp.PATTERNS_NAME)
with open(PATTERNS_PATH, "w", encoding="utf-8") as _fh:
    json.dump(TEST_PATTERNS, _fh)

PATTERNS = TEST_PATTERNS["patterns"]


def game(date, findings, game_no=1, result="L", pace=None, interview=None,
         your_deck="Test Deck A", their_deck="Placeholder Opponent",
         session_id=None, match_id=None):
    row = {
        "date": date,
        "session_id": session_id or "%s.1" % date,
        # One match per (date, deck, opponent) unless a test says otherwise.
        # (match_id, game) has to be unique, so the fixture derives it rather
        # than reusing one string everywhere.
        "match_id": match_id or "%s-%s-%s" % (date, your_deck, their_deck),
        "source": "test:fixture",
        "your_deck": your_deck,
        "their_deck": their_deck,
        "game": game_no,
        "result": result,
        "review_note": "[C] VOD Review - fixture %s.md" % date,
        "findings": findings,
    }
    if pace is not None:
        row["pace"] = pace
    if interview is not None:
        row["interview"] = interview
    return row


def finding(pattern_id="spends-removal-early", grade="punt", turn=4,
            kind=None, phase=None, **extra):
    """One finding. `phase` defaults from the kind, blind for a mulligan.

    A mulligan phase has to agree with the row's game number, and `game()`
    defaults to game 1, so a mulligan fixture defaults to the blind one. Pass
    `phase="mulligan-post-board"` with `game_no=2` for the informed case.
    """
    kind = kind or PATTERNS.get(pattern_id, {}).get("kind", "removal-timing")
    if phase is None:
        phase = {"mulligan": "mulligan-blind",
                 "sideboarding": "sideboard"}.get(kind, "in-game")
    f = {"phase": phase, "kind": kind, "pattern_id": pattern_id, "grade": grade}
    if phase == "in-game":
        f["turn"] = turn
    f.update(extra)
    return f


def validate(row, line_no=1, patterns=PATTERNS):
    return pp.validate_row(row, line_no, patterns)


def rollup(rows, min_occurrences=3, min_sessions=2, patterns=PATTERNS):
    return pp.roll_up(rows, min_occurrences, min_sessions, patterns)


def habit_named(rolled, pattern_id):
    for h in rolled["habits"]:
        if h["pattern_id"] == pattern_id:
            return h
    return None


def write_ledger(tmp_path, rows, name=pp.LEDGER_NAME, create_notes=True):
    """Write a ledger, and by default the review notes its rows cite.

    `read_ledger` checks that every `review_note` resolves, so a fixture that
    writes the ledger alone reports a broken citation on every row. Pass
    `create_notes=False` to test that check itself.
    """
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    if create_notes:
        touch_notes(tmp_path, rows)
    return str(path)


def touch_notes(tmp_path, rows):
    """Create the review notes these rows cite, so the pointer resolves."""
    for r in rows:
        ref = r.get("review_note")
        if ref:
            (tmp_path / ref).write_text("fixture prose\n", encoding="utf-8")


def run(tmp_path, argv, rows=None, ledger=None):
    """Invoke main() the way a shell would, returning the exit code."""
    if rows is not None:
        ledger = write_ledger(tmp_path, rows)
    args = ["play_profile.py", "--patterns", PATTERNS_PATH]
    if ledger:
        args += ["--ledger", ledger]
    args += ["--out", str(tmp_path / pp.PROFILE_NAME)]
    args += argv
    old = sys.argv
    sys.argv = args
    try:
        return pp.main()
    finally:
        sys.argv = old


# ----------------------------------------------------------------- validation

def test_a_clean_game_is_valid_with_an_empty_findings_list():
    """
    A game with nothing wrong in it is the most useful row in the ledger, and
    the review has to be able to record one. An empty list is not a missing
    field.
    """
    assert validate(game("2026-08-31", [])) == []


def test_an_unknown_kind_is_rejected_rather_than_counted():
    """
    The fixed vocabulary is the whole reason the ledger can be counted. A kind
    invented inline would count as its own habit forever, and the same habit
    spelled two ways splits into two.
    """
    row = game("2026-08-31", [finding(kind="removal_timing")])
    problems = validate(row, 7)
    assert problems and "line 7" in problems[0]
    assert "fixed vocabulary" in problems[0]


@pytest.mark.parametrize("mutation", [
    {"date": "31-08-2026"},
    {"date": None},
    {"your_deck": ""},
    {"their_deck": None},
    {"game": "1"},
    {"result": "loss"},
    {"findings": None},
])
def test_a_row_missing_or_malforming_a_counted_field_is_rejected(mutation):
    """An absent value is not a passing value."""
    row = game("2026-08-31", [finding()])
    row.update(mutation)
    assert validate(row, 1), f"{mutation} should have been rejected"


@pytest.mark.parametrize("bad", [
    {"measure": "stopwatch", "seconds_per_turn": 30, "tells": []},
    {"measure": "vod-timestamps", "seconds_per_turn": "fast", "tells": []},
    {"measure": "vod-timestamps", "seconds_per_turn": 30, "tells": ["rushed"]},
])
def test_pace_vocabularies_are_enforced(bad):
    row = game("2026-08-31", [], pace=bad)
    assert validate(row, 1)


def test_malformed_json_is_reported_per_line_and_the_rest_still_counts(tmp_path):
    """
    One bad line must not take the ledger down with it, and it must not vanish
    either. Silent drops and silent admissions are the same bug.
    """
    good = [game("2026-08-30", [finding()]), game("2026-08-31", [finding()])]
    path = tmp_path / pp.LEDGER_NAME
    path.write_text(
        json.dumps(good[0]) + "\n"
        + "{not json\n"
        + json.dumps(good[1]) + "\n",
        encoding="utf-8")
    touch_notes(tmp_path, good)

    rows, problems, unreadable = pp.read_ledger(str(path), PATTERNS)
    assert unreadable is None
    assert len(rows) == 2
    assert len(problems) == 1 and "line 2" in problems[0]


def test_an_unreadable_ledger_is_not_an_empty_one(tmp_path):
    """
    OneDrive raises OSError on a cloud-only placeholder that lists fine in the
    folder. Returning [] there would report a clean, empty profile.
    """
    rows, problems, unreadable = pp.read_ledger(str(tmp_path / "absent.jsonl"), PATTERNS)
    assert rows == [] and problems == []
    assert unreadable is not None


# --------------------------------------------------------------- the trend bar

def test_three_occurrences_across_two_sessions_is_a_trend():
    rolled = rollup([
        game("2026-08-30", [finding(), finding(turn=6)]),
        game("2026-08-31", [finding(turn=5)]),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["bucket"] == "leak"
    assert (h["occurrences"], h["sessions"]) == (3, 2)


def test_three_occurrences_in_one_night_is_not_a_trend():
    """Two or three occurrences on one night is one bad night."""
    rolled = rollup([
        game("2026-08-31", [finding(), finding(turn=5), finding(turn=6)]),
    ])
    assert habit_named(rolled, "spends-removal-early")["bucket"] == "watching"


def test_two_occurrences_is_watching_and_one_is_below_the_bar():
    rolled = rollup([
        game("2026-08-30", [finding(), finding(pattern_id="snap-keeps")]),
        game("2026-08-31", [finding(turn=5)]),
    ])
    assert habit_named(rolled, "spends-removal-early")["bucket"] == "watching"
    assert habit_named(rolled, "snap-keeps")["bucket"] == "below-bar"


def test_a_trend_that_stops_appearing_fades_rather_than_vanishing():
    """
    Someone who fixed a leak gets to see that they fixed it, and if it comes
    back the history is right there.
    """
    rows = [
        game("2026-08-01", [finding(), finding(turn=5)]),
        game("2026-08-02", [finding(turn=6)]),
        game("2026-08-30", [finding(pattern_id="snap-keeps")]),
        game("2026-08-31", [finding(pattern_id="snap-keeps")]),
    ]
    h = habit_named(rollup(rows), "spends-removal-early")
    assert h["bucket"] == "faded"
    assert h["last_seen"] == "2026-08-02"


def test_the_bar_is_configurable_without_touching_the_counting():
    rows = [game("2026-08-30", [finding()]), game("2026-08-31", [finding()])]
    assert habit_named(rollup(rows), "spends-removal-early")["bucket"] == "watching"
    loose = rollup(rows, min_occurrences=2, min_sessions=2)
    assert habit_named(loose, "spends-removal-early")["bucket"] == "leak"


# ------------------------------------------------------- honesty about the count

def test_a_mostly_profile_prompted_habit_is_flagged_for_discount():
    """
    The profile is read at the start of a review and written at the end, so it
    is easy to find the habit you expected. A count that is mostly confirmation
    says so rather than passing as evidence.
    """
    rolled = rollup([
        game("2026-08-30", [finding(prompted_by_profile=True),
                            finding(turn=5, prompted_by_profile=True)]),
        game("2026-08-31", [finding(turn=6, prompted_by_profile=True)]),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["bucket"] == "leak" and h["bias_flag"] is True

    # One deck in the fixture, so the habit reports in that deck's note rather
    # than the cross-deck one. The flag has to survive the move.
    text = pp.render_deck_profile("Test Deck A", rolled, [], today="2026-08-31")
    assert "Discount this count" in text


def test_a_flagged_trend_is_not_offered_as_the_thing_to_work_on():
    rolled = rollup([
        game("2026-08-30", [finding(prompted_by_profile=True),
                            finding(turn=5, prompted_by_profile=True)]),
        game("2026-08-31", [finding(turn=6, prompted_by_profile=True)]),
    ])
    text = pp.render_profile(rolled, [], today="2026-08-31")
    section = text.split("## What to work on", 1)[1]
    assert "Nothing has cleared the bar" in section


def test_intent_mismatch_is_counted_separately_from_the_habit():
    """
    Naming the right card to play around and then making a play that ignores it
    is an execution problem. Never considering the card is a judgement problem.
    Different practice, so they are counted apart.
    """
    rolled = rollup([
        game("2026-08-30", [finding(intent_matched_line=False),
                            finding(turn=5, intent_matched_line=True)]),
        game("2026-08-31", [finding(turn=6, intent_matched_line=False)]),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["intent_mismatch"] == 2
    assert "execution rather than judgement" in pp.render_deck_profile(
        "Test Deck A", rolled, [])


def test_strengths_clear_the_same_bar_as_leaks():
    """
    A profile listing only leaks is the default failure of automated review.
    `correct` means the line was right and the game went the other way.
    """
    rolled = rollup([
        game("2026-08-30", [finding(pattern_id="counts-the-hand", grade="correct"),
                            finding(pattern_id="counts-the-hand", grade="correct")]),
        game("2026-08-31", [finding(pattern_id="counts-the-hand", grade="correct")]),
    ])
    h = habit_named(rolled, "counts-the-hand")
    assert h["bucket"] == "strength"
    assert "## Strengths" in pp.render_profile(rolled, [])


def test_one_pattern_lands_in_exactly_one_bucket():
    """
    Live defect, 2026-09-04: `removal-timing` appeared under Trends and under
    Strengths in the same note, because the two were computed independently off
    a kind that lumped "spends removal on the first target" together with
    "holds removal for the real threat". Those are two patterns with two grade
    mixes, and each gets one bucket.
    """
    rolled = rollup([
        game("2026-08-30", [finding(grade="punt"),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=5)]),
        game("2026-08-31", [finding(grade="close", turn=6),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=7)]),
        game("2026-09-01", [finding(grade="punt", turn=8),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=9)]),
    ])
    early = habit_named(rolled, "spends-removal-early")
    holds = habit_named(rolled, "holds-removal-for-the-threat")
    assert early["kind"] == holds["kind"] == "removal-timing"
    assert early["bucket"] == "leak"
    assert holds["bucket"] == "strength"
    assert len({h["pattern_id"] for h in rolled["habits"]}) == 2


def test_a_strength_is_never_the_thing_to_work_on():
    """
    A decision type the player keeps getting right accumulates occurrences
    fastest, so ranking the work-on line on raw count promotes their best habit
    to the top of the list of things to fix. It did exactly that on 2026-09-04.
    """
    rolled = rollup([
        # The strength: 4 occurrences, 3 correct, and the most of anything here.
        game("2026-08-30", [finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct"),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=5),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="punt", turn=7)],
             your_deck="Deck One"),
        game("2026-08-31", [finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=6)],
             your_deck="Deck Two"),
        # The leak: 3 occurrences, all problems, and fewer of them.
        game("2026-08-30", [finding(pattern_id="taps-out-badly", grade="punt",
                                    turn=8),
                            finding(pattern_id="taps-out-badly", grade="close",
                                    turn=9)],
             your_deck="Deck One", game_no=2),
        game("2026-08-31", [finding(pattern_id="taps-out-badly", grade="close",
                                    turn=10)],
             your_deck="Deck Two", game_no=2),
    ])

    holds = habit_named(rolled, "holds-removal-for-the-threat")
    mana = habit_named(rolled, "taps-out-badly")
    assert holds["bucket"] == "strength"
    assert holds["occurrences"] > mana["occurrences"], "fixture must invert"

    section = pp.render_profile(
        rolled, [], today="2026-08-31").split("## What to work on", 1)[1]
    assert mana["label"] in section
    assert holds["label"] not in section


def test_a_punt_outweighs_a_close_in_the_work_on_ranking():
    """
    Live defect, 2026-09-04: with punts and closes weighted the same, a pattern
    with 6 closes and 0 punts topped the work-on line over one carrying real
    punts. A punt is worse than a close, so it counts double.
    """
    rolled = rollup([
        # Four closes, no punts. Score 4.
        game("2026-08-30", [finding(grade="close"),
                            finding(grade="close", turn=5),
                            finding(grade="close", turn=6)],
             your_deck="Deck One"),
        game("2026-08-31", [finding(grade="close", turn=7)],
             your_deck="Deck Two"),
        # Three punts. Score 6, on fewer occurrences.
        game("2026-08-30", [finding(pattern_id="taps-out-badly", grade="punt",
                                    turn=8),
                            finding(pattern_id="taps-out-badly", grade="punt",
                                    turn=9)],
             your_deck="Deck One", game_no=2),
        game("2026-08-31", [finding(pattern_id="taps-out-badly", grade="punt",
                                    turn=10)],
             your_deck="Deck Two", game_no=2),
    ])
    closes = habit_named(rolled, "spends-removal-early")
    punts = habit_named(rolled, "taps-out-badly")
    assert closes["occurrences"] > punts["occurrences"], "fixture must invert"
    assert (closes["problem_score"], punts["problem_score"]) == (4, 6)
    assert pp.work_on(rolled, cross_deck_only=True)["pattern_id"] == \
        "taps-out-badly"


def test_work_on_says_so_when_every_pattern_is_a_strength():
    """
    A clean profile is a legitimate result. The line says that rather than
    promoting the least-good strength to fill the heading.
    """
    rolled = rollup([
        game("2026-08-30", [finding(grade="correct"),
                            finding(grade="correct", turn=5)],
             your_deck="Deck One"),
        game("2026-08-31", [finding(grade="correct", turn=6)],
             your_deck="Deck Two"),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["bucket"] == "strength" and h["cross_deck"] is True
    section = pp.render_profile(
        rolled, [], today="2026-08-31").split("## What to work on", 1)[1]
    assert "listed above as a strength" in section


def test_the_registry_polarity_is_checked_against_the_grades():
    """
    `spends-removal-early` is declared a leak. Three correct grades make it a
    strength here. One of the two is wrong, and a tool that quietly trusts
    either has stopped being a measurement.
    """
    rolled = rollup([
        game("2026-08-30", [finding(grade="correct"),
                            finding(grade="correct", turn=5)],
             your_deck="Deck One"),
        game("2026-08-31", [finding(grade="correct", turn=6)],
             your_deck="Deck Two"),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["polarity"] == "leak" and h["bucket"] == "strength"
    assert h["polarity_conflict"] is True
    text = pp.render_profile(rolled, [], today="2026-08-31")
    assert "Registry disagrees with the grades" in text


def test_unusable_lines_are_declared_in_the_profile_itself():
    """
    Excluded rows make every count understate. The note has to say so, or the
    number cannot be checked.
    """
    rolled = rollup([game("2026-08-31", [finding()])])
    text = pp.render_profile(rolled, ["line 4: kind 'nope' is not in the fixed "
                                      "vocabulary"], today="2026-08-31")
    assert "Data problems" in text and "understates" in text


def test_a_thin_sample_says_so_before_it_says_anything_else():
    text = pp.render_profile(rollup([game("2026-08-31", [finding()])]), [])
    assert "Sample is thin" in text


# ---------------------------------------------------------------------- pace

def test_pace_averages_only_games_that_carried_a_measurement():
    rolled = rollup([
        game("2026-08-30", [], pace={"measure": "vod-timestamps",
                                     "seconds_per_turn": 20, "tells": []}),
        game("2026-08-31", [], game_no=2,
             pace={"measure": "vod-timestamps", "seconds_per_turn": 40,
                   "tells": []}),
        game("2026-08-31", [], game_no=3,
             pace={"measure": "none", "seconds_per_turn": None, "tells": []}),
    ])
    vod = rolled["pace"]["by_measure"]["vod-timestamps"]
    assert (vod["games"], vod["mean_seconds_per_turn"]) == (2, 30.0)
    assert rolled["pace"]["games_measured"] == 2
    assert rolled["pace"]["games_total"] == 3


def test_no_measurable_pace_says_so_instead_of_guessing():
    """Losing is not evidence about speed."""
    rolled = rollup([game("2026-08-31", [finding()], result="L")])
    assert rolled["pace"]["by_measure"] == {}
    assert "Never measurable so far" in pp.render_profile(rolled, [])


def test_tells_are_counted_across_games():
    rolled = rollup([
        game("2026-08-30", [], pace={"measure": "none", "tells":
                                     ["missed-trigger", "tapped-wrong-mana"]}),
        game("2026-08-31", [], pace={"measure": "none",
                                     "tells": ["missed-trigger"]}),
    ])
    assert rolled["pace"]["tells"]["missed-trigger"] == 2


# ------------------------------------------------------------------ behaviour

def test_a_missing_ledger_exits_one_rather_than_writing_an_empty_profile(tmp_path):
    code = run(tmp_path, [], ledger=str(tmp_path / "absent.jsonl"))
    assert code == 1
    assert not (tmp_path / pp.PROFILE_NAME).exists()


def test_unusable_lines_exit_two_so_the_run_can_gate_something(tmp_path):
    path = tmp_path / pp.LEDGER_NAME
    path.write_text(json.dumps(game("2026-08-31", [finding()])) + "\n"
                    + "{not json\n", encoding="utf-8")
    assert run(tmp_path, [], ledger=str(path)) == 2


def test_a_clean_run_exits_zero_and_writes_the_profile(tmp_path):
    code = run(tmp_path, [], rows=[game("2026-08-31", [finding()])])
    assert code == 0
    assert "# Play profile" in (tmp_path / pp.PROFILE_NAME).read_text(
        encoding="utf-8")


def test_dry_run_writes_nothing(tmp_path):
    run(tmp_path, ["--dry-run"], rows=[game("2026-08-31", [finding()])])
    assert not (tmp_path / pp.PROFILE_NAME).exists()


def test_the_second_run_is_a_no_op_and_leaves_no_backup(tmp_path):
    """
    Run it twice. If the second run behaves differently, something is reading
    state it also writes.
    """
    rows = [game("2026-08-31", [finding()])]
    run(tmp_path, [], rows=rows)
    first = (tmp_path / pp.PROFILE_NAME).read_text(encoding="utf-8")
    run(tmp_path, [], rows=rows)
    assert (tmp_path / pp.PROFILE_NAME).read_text(encoding="utf-8") == first
    assert not (tmp_path / pp.BACKUP_NAME).exists()


def test_a_rewrite_backs_up_the_previous_profile_first(tmp_path):
    """Anything destructive leaves a backup and names it."""
    ledger = write_ledger(tmp_path, [game("2026-08-30", [finding()])])
    run(tmp_path, [], ledger=ledger)
    before = (tmp_path / pp.PROFILE_NAME).read_text(encoding="utf-8")

    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(game("2026-08-31", [finding(turn=5)])) + "\n")
    run(tmp_path, [], ledger=ledger)

    assert (tmp_path / pp.BACKUP_NAME).read_text(encoding="utf-8") == before
    assert (tmp_path / pp.PROFILE_NAME).read_text(encoding="utf-8") != before


def test_the_empty_ledger_profile_claims_nothing(tmp_path):
    path = tmp_path / pp.LEDGER_NAME
    path.write_text("\n", encoding="utf-8")
    assert run(tmp_path, [], ledger=str(path)) == 0
    text = (tmp_path / pp.PROFILE_NAME).read_text(encoding="utf-8")
    assert "ledger is empty" in text
    assert "## Leaks" not in text


def test_output_is_pure_ascii(tmp_path):
    """
    A Windows console on cp1252 raises UnicodeEncodeError on a print it cannot
    encode, which kills the run at the reporting step, after the work. Keeping
    the module ASCII keeps every print safe.
    """
    with open(pp.__file__, "rb") as fh:
        high = [i for i, b in enumerate(fh.read()) if b > 127]
    assert not high, f"{len(high)} byte(s) above 0x7F in play_profile.py"


def test_the_kind_vocabulary_matches_the_reference_note():
    """
    A comment is not a guard. The vocabulary is documented in the skill's
    reference note, and a value added to one place and not the other produces a
    kind the script rejects and the skill tells Claude to write.
    """
    ref = os.path.join(SCRIPT_DIR, "skills", "vod-review", "reference",
                       "play-profile.md")
    with open(ref, encoding="utf-8") as fh:
        text = fh.read()
    missing = [k for k in pp.KINDS if k not in text]
    assert not missing, f"kinds absent from the reference note: {missing}"
    for tell in pp.PACE_TELLS:
        assert tell in text, f"pace tell absent from the reference note: {tell}"


# ------------------------------------------------------------- kept hands

def hand(kept_at=6, lands=2, cards=None, shape="interaction-heavy",
         outcome="screwed", **extra):
    h = {
        "kept_at": kept_at,
        "lands": lands,
        "cards": cards or ["Island", "Plains", "Stock Up", "Negate",
                           "Get Lost", "Day of Judgment"][:kept_at],
        "shape": shape,
        "outcome": outcome,
    }
    h.update(extra)
    return h


def game_with_hand(date="2026-09-01", result="L", game_no=1, **hand_kwargs):
    row = game(date, [], game_no=game_no, result=result)
    row["hand"] = hand(**hand_kwargs)
    return row


def test_a_hand_is_stored_card_for_card_and_counted_by_size():
    """
    "That was a keep" is an opinion. The cards, the land count and the result
    are what make a mulligan finding arguable, so all three survive the rollup.
    """
    rolled = rollup([
        game_with_hand(kept_at=6, lands=2, result="L"),
        game_with_hand(kept_at=7, lands=3, result="W", game_no=2,
                       shape="lands-and-spells", outcome="neither"),
    ])
    hands = rolled["hands"]
    assert hands["recorded"] == 2
    assert hands["by_size"][6]["record"] == "0-1-0"
    assert hands["by_size"][7]["record"] == "1-0-0"
    assert hands["by_size"][6]["mean_lands"] == 2.0
    assert hands["index"][0]["cards"][0] == "Island"
    assert hands["outcomes"]["screwed"] == 1


def test_a_hand_whose_card_count_disagrees_with_kept_at_is_rejected():
    """
    A six-card keep listing five cards means one was missed in transcription,
    and a hand that is wrong is worse than a hand that is absent: it gets
    counted, and the count is what the whole ledger is for.
    """
    row = game_with_hand()
    row["hand"]["cards"] = row["hand"]["cards"][:5]
    problems = validate(row, 1)
    assert any("kept_at" in p for p in problems)


@pytest.mark.parametrize("field,value", [
    ("shape", "felt-fine"),
    ("outcome", "unlucky"),
    ("kept_at", 9),
    ("lands", -1),
])
def test_hand_vocabularies_and_bounds_are_enforced(field, value):
    row = game_with_hand()
    row["hand"][field] = value
    assert validate(row, 1)


def test_a_game_with_no_hand_still_counts(tmp_path):
    """
    The ledger predates hand logging, so an older line has to stay usable. It
    just does not contribute to the hand counts.
    """
    row = game("2026-08-31", [finding()])
    assert validate(row, 1) == []
    rolled = rollup([row])
    assert rolled["hands"]["recorded"] == 0


def test_the_profile_says_when_no_hands_are_recorded():
    text = pp.render_profile(rollup([game("2026-08-31", [finding()])]), [])
    assert "## Opening hands" in text
    assert "No hands recorded yet" in text


def test_the_profile_reports_hands_when_they_exist():
    text = pp.render_profile(rollup([
        game_with_hand(kept_at=6, lands=2),
        game_with_hand(kept_at=6, lands=2, date="2026-09-02", game_no=2),
    ]), [])
    assert "Recorded for 2 of 2 game(s)" in text
    assert "interaction-heavy" in text
    assert "screwed" in text


def test_the_hand_vocabularies_match_the_reference_note():
    ref = os.path.join(SCRIPT_DIR, "skills", "vod-review", "reference",
                       "play-profile.md")
    with open(ref, encoding="utf-8") as fh:
        text = fh.read()
    for value in pp.HAND_SHAPES + pp.HAND_OUTCOMES:
        assert value in text, f"hand value absent from the reference note: {value}"


# --------------------------------------------------- decks, matchups, boarding

def test_a_habit_on_one_deck_is_not_yet_a_habit_of_the_player():
    """
    Holding up mana badly in a control mirror says nothing about how someone
    plays aggro. Until a second deck shows the habit it belongs to the deck,
    and the cross-deck note says where it lives instead of claiming it.
    """
    rolled = rollup([
        game("2026-08-30", [finding(), finding(turn=5)], your_deck="UW Control"),
        game("2026-08-31", [finding(turn=6)], your_deck="UW Control"),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["bucket"] == "leak"
    assert h["cross_deck"] is False
    assert h["decks"] == ["UW Control"]

    text = pp.render_profile(rolled, [])
    section = text.split("## Leaks", 1)[1].split("## Strengths", 1)[0]
    assert "Nothing has cleared the bar as a leak across two decks" in section
    assert "Cleared the bar on one deck only" in text


def test_a_habit_across_two_decks_is_a_habit_of_the_player():
    rolled = rollup([
        game("2026-08-30", [finding(), finding(turn=5)], your_deck="UW Control"),
        game("2026-08-31", [finding(turn=6)], your_deck="Mono Red"),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["cross_deck"] is True
    assert h["decks"] == ["Mono Red", "UW Control"]
    text = pp.render_profile(rolled, [])
    assert "Mono Red, UW Control" in text


def test_each_deck_gets_its_own_rollup():
    rows = [
        game("2026-08-30", [finding()], your_deck="UW Control", result="L"),
        game("2026-08-31", [finding(turn=6)], your_deck="Mono Red", result="W"),
    ]
    by_deck = pp.roll_up_by_deck(rows, 3, 2, PATTERNS)
    assert sorted(by_deck) == ["Mono Red", "UW Control"]
    assert by_deck["Mono Red"]["games"] == 1
    assert by_deck["Mono Red"]["results"] == {"W": 1}


def test_a_deck_name_cannot_write_outside_the_insights_folder():
    """
    Deck names come from the user through a review. A slash in one would
    otherwise put the note somewhere nobody looks for it.
    """
    name = pp.deck_filename("UW/Control: the ../deck")
    assert "/" not in name and "\\" not in name
    assert name.startswith("[C] Play Profile - ") and name.endswith(".md")


def test_a_small_personal_matchup_record_is_called_an_anecdote():
    """
    A handful of games is not a win rate. The archetype notes carry hundreds of
    matches and they win any disagreement; this section exists for texture.
    """
    rolled = rollup([
        game("2026-08-30", [], their_deck="Izzet Spellementals", result="L"),
        game("2026-08-31", [], their_deck="Izzet Spellementals", result="W",
             game_no=2),
    ])
    m = rolled["matchups"][0]
    assert m["games"] == 2 and m["record"] == "1-1-0"
    assert m["meaningful"] is False
    text = pp.render_deck_profile("Test Deck A", rolled, [])
    assert "anecdote" in text
    assert "the archetype note wins" in text


def test_a_matchup_becomes_worth_reading_at_the_threshold():
    rows = [game("2026-08-%02d" % (d + 1), [], their_deck="Dimir Midrange",
                 game_no=i + 1)
            for d in range(pp.MEANINGFUL_MATCHUP_GAMES) for i in [0]]
    rolled = rollup(rows)
    assert rolled["matchups"][0]["meaningful"] is True


def test_sideboarding_is_recorded_per_matchup():
    row = game("2026-08-30", [], their_deck="Izzet Spellementals")
    row["sideboard"] = {"in": ["Rest in Peace", "Flashfreeze"],
                        "out": ["Seam Rip", "Pyrrhic Strike"]}
    assert validate(row, 1) == []
    rolled = rollup([row])
    m = rolled["matchups"][0]
    assert {c["card"] for c in m["boarded_in"]} == {"Rest in Peace", "Flashfreeze"}
    assert {c["card"] for c in m["boarded_out"]} == {"Seam Rip", "Pyrrhic Strike"}
    assert "Rest in Peace" in pp.render_deck_profile("Test Deck A", rolled, [])


def test_a_malformed_sideboard_is_rejected_rather_than_counted():
    row = game("2026-08-30", [])
    row["sideboard"] = {"in": "Rest in Peace"}
    assert validate(row, 1)


def test_an_unbalanced_sideboard_is_reported_in_both_directions():
    """
    A deck keeps its size, so in and out are the same length by arithmetic. The
    reference note asked for this check from 1.12.0 and nothing did it, while
    the per-matchup test above pinned 2-in against 1-out as clean. A live row
    then carried 9 in against 7 out on both post-board games of one match.
    """
    short_out = game("2026-08-30", [])
    short_out["sideboard"] = {"in": ["Rest in Peace", "Flashfreeze"],
                              "out": ["Seam Rip"]}
    problem = pp._sideboard_balance(short_out, 7)
    assert problem and "line 7" in problem and "takes out 1" in problem

    short_in = game("2026-08-30", [])
    short_in["sideboard"] = {"in": ["Rest in Peace"],
                             "out": ["Seam Rip", "Pyrrhic Strike"]}
    assert pp._sideboard_balance(short_in, 1), "a short in-list is the same defect"

    balanced = game("2026-08-30", [])
    balanced["sideboard"] = {"in": ["Rest in Peace"], "out": ["Seam Rip"]}
    assert pp._sideboard_balance(balanced, 1) is None

    empty = game("2026-08-30", [])
    empty["sideboard"] = {"in": [], "out": []}
    assert pp._sideboard_balance(empty, 1) is None, \
        "a game boarded nothing is not a defect"

    none_at_all = game("2026-08-30", [])
    assert pp._sideboard_balance(none_at_all, 1) is None


def test_an_unbalanced_sideboard_costs_the_lists_and_not_the_findings(tmp_path):
    """
    Rejecting the whole row was the first fix and it was wrong. On the live row
    that found this defect the findings were a post-board mulligan punt and a
    boarding call, and the mulligan punt is the case the blind/post-board split
    was written for. A miscounted boarding list is not a reason to lose it.
    """
    row = game("2026-08-30", [finding(pattern_id="snap-keeps",
                                      phase="mulligan-post-board")],
               game_no=2, their_deck="Izzet Spellementals")
    row["sideboard"] = {"in": ["Rest in Peace", "Flashfreeze"],
                        "out": ["Seam Rip"]}
    ledger = write_ledger(tmp_path, [row])
    rows, problems, _ = pp.read_ledger(ledger, PATTERNS)

    assert len(rows) == 1, "the row survives"
    assert rows[0]["findings"], "and so do its findings"
    assert "sideboard" not in rows[0], "the wrong lists are set aside"
    assert len(problems) == 1 and "set aside" in problems[0]

    rolled = rollup(rows)
    assert habit_named(rolled, "snap-keeps"), "the finding still counts"
    assert not rolled["matchups"] or not rolled["matchups"][0]["boarded_in"], \
        "the boarding rollup does not carry a list known to be wrong"


def test_deck_profiles_are_written_next_to_the_cross_deck_note(tmp_path):
    code = run(tmp_path, [], rows=[
        game("2026-08-30", [], your_deck="UW Control"),
        game("2026-08-31", [], your_deck="Mono Red"),
    ])
    assert code == 0
    assert (tmp_path / pp.PROFILE_NAME).exists()
    assert (tmp_path / pp.deck_filename("UW Control")).exists()
    assert (tmp_path / pp.deck_filename("Mono Red")).exists()


def test_boarding_is_counted_per_game_not_per_copy():
    """
    Four copies of one card in one game is one boarding decision. Counting
    copies would report a four-of as four times the habit of a one-of.
    """
    row = game("2026-08-30", [], their_deck="Izzet Spellementals")
    row["sideboard"] = {"in": ["Flashfreeze"] * 4, "out": ["Seam Rip"] * 2}
    rolled = rollup([row])
    m = rolled["matchups"][0]
    assert m["boarded_in"][0] == {"card": "Flashfreeze", "games": 1}
    assert m["boarded_out"][0] == {"card": "Seam Rip", "games": 1}


# ------------------------------------------------- the pattern registry itself

def test_a_pattern_id_outside_the_registry_is_rejected_rather_than_counted():
    """
    The registry is the whole reason the ledger can be counted. An id invented
    inline would count as its own habit forever, and the same behaviour named
    two ways splits into two habits.
    """
    row = game("2026-08-31", [finding(pattern_id="made-this-up")])
    problems = validate(row, 7)
    assert problems and "line 7" in problems[0]
    assert pp.PATTERNS_NAME in problems[0]


def test_a_pattern_used_under_the_wrong_kind_is_rejected():
    """
    `taps-out-badly` is a mana-holding pattern. Filed under removal-timing it
    would land in the wrong kind's counts and nothing would say so.
    """
    row = game("2026-08-31", [finding(pattern_id="taps-out-badly",
                                      kind="removal-timing", turn=4)])
    assert any("belongs to kind" in p for p in validate(row))


def test_the_label_comes_from_the_registry_not_from_the_ledger():
    """
    The profile line reads as the pattern's declared label, the same every time,
    regardless of how any one finding was worded. Deriving a label from free
    text is what produced "removal-timing decisions (16 wordings)".
    """
    rolled = rollup([
        game("2026-08-30", [finding(note="first wording"),
                            finding(turn=5, note="a completely different one"),
                            finding(turn=6)]),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["label"] == "Spends removal on the first legal target"
    assert "wording" not in json.dumps(h)


def test_a_registry_missing_a_required_field_is_an_error_not_a_default(tmp_path):
    """
    A pattern with no polarity or no label would render as a blank heading. The
    loader refuses the whole registry rather than filling in a guess.
    """
    path = tmp_path / pp.PATTERNS_NAME
    path.write_text(json.dumps({"patterns": {
        "half-written": {"kind": "mulligan", "label": "Half written"}}}),
        encoding="utf-8")
    patterns, error = pp.load_patterns(str(path))
    assert patterns == {} and error and "polarity" in error


def test_a_missing_registry_stops_the_run_rather_than_counting_nothing(tmp_path):
    patterns, error = pp.load_patterns(str(tmp_path / "absent.json"))
    assert patterns == {} and error is not None


def test_the_shipped_registry_is_loadable_and_matches_the_reference_note():
    """
    A comment is not a guard. The registry ships, the reference note documents
    it, and a pattern added to one and not the other is a pattern the script
    accepts and no human can look up.
    """
    patterns, error = pp.load_patterns()
    assert error is None, error
    assert patterns, "the shipped registry has no patterns"
    for pid, spec in patterns.items():
        assert spec["kind"] in pp.KINDS
        assert spec["polarity"] in pp.POLARITIES

    ref = os.path.join(SCRIPT_DIR, "skills", "vod-review", "reference",
                       "play-profile.md")
    with open(ref, encoding="utf-8") as fh:
        text = fh.read()
    assert pp.PATTERNS_NAME in text
    for value in pp.PHASES + pp.POLARITIES:
        assert value in text, f"absent from the reference note: {value}"


def test_every_kind_carries_at_least_one_pattern():
    """
    A kind with no pattern is a category a reviewer can name and cannot file
    anything under: the pattern_id it needs does not exist, and an invented one
    is rejected. play-draw, combat-math and rules-error sat empty from 1.14.0,
    so a combat-math error was either dropped or filed under a pattern that did
    not describe it.
    """
    patterns, error = pp.load_patterns()
    assert error is None, error
    used = {spec["kind"] for spec in patterns.values()}
    empty = [k for k in pp.KINDS if k not in used]
    assert not empty, f"kinds with no pattern in the registry: {empty}"


# -------------------------------------------------------- the closed schema

def test_an_unrecognised_key_is_reported_rather_than_ignored():
    """
    Live defect, 2026-09-04: a review wrote `opening_hand` where the schema says
    `hand`, for all three games of a match. The rows validated clean, the run
    exited 0, and the hand count read as six games whose source never showed a
    hand. A script that does nothing looks exactly like one that worked.
    """
    row = game("2026-08-31", [finding()])
    row["opening_hand"] = {"kept_at": 7, "cards": []}
    problems = validate(row, 4)
    assert problems and "opening_hand" in problems[0]


@pytest.mark.parametrize("where,mutation", [
    ("finding", {"habit": "the old free-text field"}),
    ("hand", {"land_count": 2}),
    ("pace", {"seconds": 30}),
])
def test_unrecognised_keys_are_caught_inside_nested_objects(where, mutation):
    row = game("2026-08-31", [finding()])
    row["hand"] = {"kept_at": 6, "lands": 2, "shape": "land-light",
                   "outcome": "screwed",
                   "cards": ["a", "b", "c", "d", "e", "f"]}
    row["pace"] = {"measure": "none", "tells": []}
    target = row["findings"][0] if where == "finding" else row[where]
    target.update(mutation)
    assert any("unrecognised" in p for p in validate(row))


def test_the_same_game_appended_twice_is_reported(tmp_path):
    """
    (match_id, game) is the row's identity. Appending it twice doubles every
    count it touches, and the old schema had no way to notice.
    """
    row = game("2026-08-31", [finding()])
    path = tmp_path / pp.LEDGER_NAME
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n",
                    encoding="utf-8")
    touch_notes(tmp_path, [row])
    rows, problems, _ = pp.read_ledger(str(path), PATTERNS)
    assert len(rows) == 1
    assert problems and "already on line 1" in problems[0]


def test_a_turn_belongs_to_an_in_game_finding_only():
    """
    `turn` used to be a required integer with 0 standing in for "before the
    game started", and the profile printed `Turns: 0, 0, 0, 0`.
    """
    bad = game("2026-08-31", [finding(pattern_id="snap-keeps")])
    bad["findings"][0]["turn"] = 0
    assert any("does not belong" in p for p in validate(bad))

    missing = game("2026-08-31", [{"phase": "in-game", "kind": "removal-timing",
                                   "pattern_id": "spends-removal-early",
                                   "grade": "punt"}])
    assert any("positive integer" in p for p in validate(missing))

    good = game("2026-08-31", [finding(pattern_id="snap-keeps")])
    assert validate(good) == []


def test_a_pre_game_finding_contributes_no_turn_to_the_rollup():
    rolled = rollup([game("2026-08-31", [finding(pattern_id="snap-keeps")])])
    assert habit_named(rolled, "snap-keeps")["turns"] == []


# ------------------------------------------- blind and post-board mulligans

def test_a_blind_keep_and_an_informed_keep_are_counted_apart():
    """
    A game 1 keep is made with no idea what is across the table. A game 2 or 3
    keep is made knowing the matchup, and the same six cards can be a keep in
    one and a ship in the other. The 2026-09-01 Izzet Spellementals punt only
    exists because two games had already shown their curve.
    """
    rolled = rollup([
        game("2026-08-30", [finding(pattern_id="snap-keeps", grade="close")]),
        game("2026-08-30", [finding(pattern_id="snap-keeps", grade="punt",
                                    phase="mulligan-post-board")], game_no=2),
    ])
    mull = rolled["mulligans"]
    assert set(mull) == {"mulligan-blind", "mulligan-post-board"}
    assert mull["mulligan-blind"]["grades"] == {"close": 1}
    assert mull["mulligan-post-board"]["grades"] == {"punt": 1}

    # The pattern count stays whole. Splitting the counts as well would put a
    # two-occurrence habit below the bar twice and report neither.
    h = habit_named(rolled, "snap-keeps")
    assert h["occurrences"] == 2
    assert h["phases"] == {"mulligan-blind": 1, "mulligan-post-board": 1}

    text = pp.render_deck_profile("Test Deck A", rolled, [])
    section = text.split("## Mulligans", 1)[1].split("\n## ", 1)[0]
    assert "Blind, game 1" in section
    assert "Post-board, knowing the matchup" in section
    assert "1 close" in section and "1 punt" in section


@pytest.mark.parametrize("phase,game_no", [
    ("mulligan-blind", 2),        # a blind keep is game 1 by definition
    ("mulligan-post-board", 1),   # nothing has been boarded yet
    ("sideboard", 1),             # boarding happens between games
])
def test_a_phase_that_disagrees_with_the_game_number_is_rejected(phase, game_no):
    row = game("2026-08-31", [finding(pattern_id="snap-keeps", phase=phase)],
               game_no=game_no)
    assert any("does not happen in game" in p for p in validate(row))


def test_kept_hands_are_split_by_what_was_known_at_the_keep():
    """
    "What do I keep" is two questions. Averaging a blind keep with an informed
    one produces a mean that describes neither.
    """
    rolled = rollup([
        game_with_hand(kept_at=7, lands=3, result="W"),
        game_with_hand(kept_at=6, lands=2, result="L", game_no=2),
        game_with_hand(kept_at=6, lands=2, result="L", game_no=3),
    ])
    by = rolled["hands"]["by_knowledge"]
    assert by["blind"]["games"] == 1 and by["blind"]["record"] == "1-0-0"
    assert by["post-board"]["games"] == 2
    assert by["post-board"]["record"] == "0-2-0"
    assert by["blind"]["mean_lands"] == 3.0
    assert by["post-board"]["mean_lands"] == 2.0
    assert {h["knowledge"] for h in rolled["hands"]["index"]} == {
        "blind", "post-board"}


def test_the_profile_carries_one_classification_table():
    """
    One row per pattern that cleared the bar, one classification each. The
    old note had four headings that all read "(N wordings)" and listed
    removal-timing as a trend and a strength at once.
    """
    rolled = rollup([
        game("2026-08-30", [finding(grade="punt"),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=5)],
             your_deck="Deck One"),
        game("2026-08-31", [finding(grade="punt", turn=6),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=7)],
             your_deck="Deck Two"),
        game("2026-09-01", [finding(grade="close", turn=8),
                            finding(pattern_id="holds-removal-for-the-threat",
                                    grade="correct", turn=9)],
             your_deck="Deck One", game_no=2),
    ])
    table = pp._classification_table(rolled, cross_deck_only=True)
    assert table and table.count("\n") == 3, "header, rule, two patterns"
    assert "**Leak**" in table and "Strength" in table

    text = pp.render_profile(rolled, [], today="2026-09-01")
    assert "## At a glance" in text
    glance = text.split("## At a glance", 1)[1].split("## Leaks", 1)[0]
    for pid in ("Spends removal on the first legal target",
                "Holds removal for the threat that matters"):
        assert glance.count(pid) == 1, f"{pid} should appear once"


def test_ledger_prose_is_capped_so_it_cannot_become_the_profile():
    """
    The account of a decision lives in its review note. A `note` on the finding
    is a label for scanning the ledger, and it is never rolled up.
    """
    row = game("2026-08-31", [finding(note="x" * (pp.NOTE_MAX_CHARS + 1))])
    assert any("cap" in p for p in validate(row))

    rolled = rollup([game("2026-08-31", [finding(note="a telling sentence")])])
    assert "a telling sentence" not in json.dumps(rolled)


# ------------------------------------------------------- citations and fading

def test_every_pattern_carries_a_pointer_at_the_review_note():
    """
    The profile cites the prose instead of copying it. Without the pointer the
    count is unarguable, which is the same problem quoting was solving badly.
    """
    rolled = rollup([
        game("2026-08-30", [finding(), finding(turn=5)]),
        game("2026-08-31", [finding(turn=6)]),
    ])
    h = habit_named(rolled, "spends-removal-early")
    assert h["citations"] and all(c["review_note"] for c in h["citations"])
    assert "Read it in:" in pp.render_deck_profile("Test Deck A", rolled, [])


def test_a_citation_that_resolves_to_nothing_is_a_problem(tmp_path):
    """
    The pointer used to be checked for being a non-empty string and nothing
    else. On 2026-09-04 all 41 live rows cited a hyphenated filename while the
    notes on disk carried an em dash: 46 findings, 0 citations that resolved,
    and a run that reported no problems. The count still holds, so the row is
    reported rather than dropped.
    """
    rows = [game("2026-08-30", [finding()]), game("2026-08-31", [finding()])]
    ledger = write_ledger(tmp_path, rows, create_notes=False)
    parsed, problems, unreadable = pp.read_ledger(ledger, PATTERNS)
    assert unreadable is None
    assert len(parsed) == 2, "a broken pointer does not cost the count"
    assert len(problems) == 2
    assert "review_note" in problems[0] and "resolves to nothing" in problems[0]
    assert run(tmp_path, ["--dry-run"], ledger=ledger) == 2

    # And the same rows with their notes on disk come back clean.
    ok = write_ledger(tmp_path, rows)
    assert pp.read_ledger(ok, PATTERNS)[1] == []


def test_one_note_cited_by_many_rows_is_only_checked_once(tmp_path):
    """
    A 29-game cluster cites one note 29 times. The check caches, so a stat call
    per row is not the cost of reading the ledger.
    """
    rows = [game("2026-08-30", [finding()], game_no=n, match_id="cluster")
            for n in range(1, 6)]
    for r in rows:
        r["review_note"] = "[C] VOD Review - one note.md"
    ledger = write_ledger(tmp_path, rows, create_notes=False)
    _, problems, _ = pp.read_ledger(ledger, PATTERNS)
    assert len(problems) == 5, "every row says so, once each"


def test_a_deck_sitting_in_its_box_does_not_fade_its_habits():
    """
    Fade is measured against the sessions where the pattern's own deck was
    played. Measuring against all recent sessions faded every pattern of a deck
    the moment two sessions with another deck went by, which reports a habit as
    cured on no evidence at all.
    """
    rows = [
        game("2026-08-01", [finding(), finding(turn=5)], your_deck="Deck One"),
        game("2026-08-02", [finding(turn=6)], your_deck="Deck One"),
        # Two later sessions on a different deck entirely.
        game("2026-08-30", [finding(pattern_id="snap-keeps")],
             your_deck="Deck Two"),
        game("2026-08-31", [finding(pattern_id="snap-keeps")],
             your_deck="Deck Two"),
    ]
    h = habit_named(rollup(rows), "spends-removal-early")
    assert h["bucket"] == "leak", "Deck One's leak faded on Deck Two's sessions"
    assert h["last_seen"] == "2026-08-02"


def test_the_json_payload_leaves_out_what_the_profile_never_shows(tmp_path):
    """
    The old payload came back at 53 KB off a 46 KB ledger, so the cheap way to
    answer "what should I work on" cost more than reading the raw data.
    """
    rows = [game("2026-08-31", [finding()])]
    rows[0]["hand"] = {"kept_at": 6, "lands": 2, "shape": "land-light",
                       "outcome": "screwed",
                       "cards": ["Island", "Plains", "Negate", "Stock Up",
                                 "Get Lost", "Day of Judgment"]}
    ledger = write_ledger(tmp_path, rows)

    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        run(tmp_path, ["--json"], ledger=ledger)
    payload = json.loads(buf.getvalue())["rollup"]
    assert "index" not in payload["hands"]
    assert payload["hands"]["recorded"] == 1
    assert "below_bar" in payload
    assert "work_on" in payload

    buf = io.StringIO()
    with redirect_stdout(buf):
        run(tmp_path, ["--json", "--full"], ledger=ledger)
    full = json.loads(buf.getvalue())["rollup"]
    assert full["hands"]["index"][0]["cards"][0] == "Island"
