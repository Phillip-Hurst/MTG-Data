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

import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

import play_profile as pp


# ------------------------------------------------------------------- fixtures

def game(date, findings, game_no=1, result="L", pace=None, interview=None,
         your_deck="Test Deck A", their_deck="Placeholder Opponent"):
    row = {
        "date": date,
        "source": "test:fixture",
        "your_deck": your_deck,
        "their_deck": their_deck,
        "game": game_no,
        "result": result,
        "findings": findings,
    }
    if pace is not None:
        row["pace"] = pace
    if interview is not None:
        row["interview"] = interview
    return row


def finding(kind="removal-timing", grade="punt", turn=4,
            habit="spent removal on the first legal target", **extra):
    f = {"kind": kind, "grade": grade, "turn": turn, "habit": habit}
    f.update(extra)
    return f


def rollup(rows, min_occurrences=3, min_sessions=2):
    return pp.roll_up(rows, min_occurrences, min_sessions)


def habit_named(rolled, kind):
    for h in rolled["habits"]:
        if h["kind"] == kind:
            return h
    return None


def write_ledger(tmp_path, rows, name=pp.LEDGER_NAME):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return str(path)


def run(tmp_path, argv, rows=None, ledger=None):
    """Invoke main() the way a shell would, returning (exit_code, stdout)."""
    if rows is not None:
        ledger = write_ledger(tmp_path, rows)
    args = ["play_profile.py"]
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
    assert pp.validate_row(game("2026-08-31", []), 1) == []


def test_an_unknown_kind_is_rejected_rather_than_counted():
    """
    The fixed vocabulary is the whole reason the ledger can be counted. A kind
    invented inline would count as its own habit forever, and the same habit
    spelled two ways splits into two.
    """
    row = game("2026-08-31", [finding(kind="removal_timing")])
    problems = pp.validate_row(row, 7)
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
    assert pp.validate_row(row, 1), f"{mutation} should have been rejected"


@pytest.mark.parametrize("bad", [
    {"measure": "stopwatch", "seconds_per_turn": 30, "tells": []},
    {"measure": "vod-timestamps", "seconds_per_turn": "fast", "tells": []},
    {"measure": "vod-timestamps", "seconds_per_turn": 30, "tells": ["rushed"]},
])
def test_pace_vocabularies_are_enforced(bad):
    row = game("2026-08-31", [], pace=bad)
    assert pp.validate_row(row, 1)


def test_malformed_json_is_reported_per_line_and_the_rest_still_counts(tmp_path):
    """
    One bad line must not take the ledger down with it, and it must not vanish
    either. Silent drops and silent admissions are the same bug.
    """
    path = tmp_path / pp.LEDGER_NAME
    path.write_text(
        json.dumps(game("2026-08-30", [finding()])) + "\n"
        + "{not json\n"
        + json.dumps(game("2026-08-31", [finding()])) + "\n",
        encoding="utf-8")

    rows, problems, unreadable = pp.read_ledger(str(path))
    assert unreadable is None
    assert len(rows) == 2
    assert len(problems) == 1 and "line 2" in problems[0]


def test_an_unreadable_ledger_is_not_an_empty_one(tmp_path):
    """
    OneDrive raises OSError on a cloud-only placeholder that lists fine in the
    folder. Returning [] there would report a clean, empty profile.
    """
    rows, problems, unreadable = pp.read_ledger(str(tmp_path / "absent.jsonl"))
    assert rows == [] and problems == []
    assert unreadable is not None


# --------------------------------------------------------------- the trend bar

def test_three_occurrences_across_two_sessions_is_a_trend():
    rolled = rollup([
        game("2026-08-30", [finding(), finding(turn=6)]),
        game("2026-08-31", [finding(turn=5)]),
    ])
    h = habit_named(rolled, "removal-timing")
    assert h["bucket"] == "trend"
    assert (h["occurrences"], h["sessions"]) == (3, 2)


def test_three_occurrences_in_one_night_is_not_a_trend():
    """Two or three occurrences on one night is one bad night."""
    rolled = rollup([
        game("2026-08-31", [finding(), finding(turn=5), finding(turn=6)]),
    ])
    assert habit_named(rolled, "removal-timing")["bucket"] == "watching"


def test_two_occurrences_is_watching_and_one_is_below_the_bar():
    rolled = rollup([
        game("2026-08-30", [finding(), finding(kind="mulligan", turn=0,
                                               habit="kept a two-lander")]),
        game("2026-08-31", [finding(turn=5)]),
    ])
    assert habit_named(rolled, "removal-timing")["bucket"] == "watching"
    assert habit_named(rolled, "mulligan")["bucket"] == "below-bar"


def test_a_trend_that_stops_appearing_fades_rather_than_vanishing():
    """
    Someone who fixed a leak gets to see that they fixed it, and if it comes
    back the history is right there.
    """
    rows = [
        game("2026-08-01", [finding(), finding(turn=5)]),
        game("2026-08-02", [finding(turn=6)]),
        game("2026-08-30", [finding(kind="mulligan", turn=0, habit="snap kept")]),
        game("2026-08-31", [finding(kind="mulligan", turn=0, habit="snap kept")]),
    ]
    h = habit_named(rollup(rows), "removal-timing")
    assert h["bucket"] == "faded"
    assert h["last_seen"] == "2026-08-02"


def test_the_bar_is_configurable_without_touching_the_counting():
    rows = [game("2026-08-30", [finding()]), game("2026-08-31", [finding()])]
    assert habit_named(rollup(rows), "removal-timing")["bucket"] == "watching"
    loose = rollup(rows, min_occurrences=2, min_sessions=2)
    assert habit_named(loose, "removal-timing")["bucket"] == "trend"


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
    h = habit_named(rolled, "removal-timing")
    assert h["bucket"] == "trend" and h["bias_flag"] is True

    text = pp.render_profile(rolled, [], today="2026-08-31")
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
    h = habit_named(rolled, "removal-timing")
    assert h["intent_mismatch"] == 2
    assert "execution rather than judgement" in pp.render_profile(rolled, [])


def test_strengths_clear_the_same_bar_as_leaks():
    """
    A profile listing only leaks is the default failure of automated review.
    `correct` means the line was right and the game went the other way.
    """
    rolled = rollup([
        game("2026-08-30", [finding(grade="correct", kind="mulligan", turn=0,
                                    habit="counted the hand before keeping"),
                            finding(grade="correct", kind="mulligan", turn=0,
                                    habit="counted the hand before keeping")]),
        game("2026-08-31", [finding(grade="correct", kind="mulligan", turn=0,
                                    habit="counted the hand before keeping")]),
    ])
    h = habit_named(rolled, "mulligan")
    assert h["strength"] is True
    assert "## Strengths" in pp.render_profile(rolled, [])


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
    assert "## Trends" not in text


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
