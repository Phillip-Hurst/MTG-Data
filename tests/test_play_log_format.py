"""
Tests for `format` on the play ledger.

The ledger had no format field and play_profile.resolve_dir sorts the insights
notes by format, so 29 Historic games (Golgari Yawgmoth) and 12 Standard games
(UW Control) rolled up into one Standard profile. The `era` field recorded the
difference and nothing partitioned on it, so "Golgari Yawgmoth vs Goblin
Charbelcher, 4 games" sat in the folder a Standard question reads.

The rule these pin: a deck, a matchup record and a kept hand belong to one
format; a habit does not.
"""
import json
import os
import sys

import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from mtg_data.review import play_profile as pp
from mtg_data.review import migrate_play_log_format as mig


# ── inferring the format ──────────────────────────────────────────────────────

def test_an_explicit_format_wins():
    assert pp.row_format({"format": "Modern", "era": "historic-2026-08"}) == "Modern"


@pytest.mark.parametrize("era,expected", [
    ("historic-2026-08", "Historic"),
    ("the-hobbit-post-ban-2026-08-10", "Standard"),
    ("pioneer-2026-05", "Pioneer"),
    ("modern-horizons-3", "Modern"),
])
def test_the_era_slug_carries_the_format(era, expected):
    """Every era slug this project has written names the format unless it's Standard."""
    assert pp.row_format({"era": era}) == expected


def test_no_format_and_no_era_falls_back_to_the_run():
    assert pp.row_format({}, default="Pauper") == "Pauper"


def test_an_empty_format_string_is_not_a_format():
    assert pp.row_format({"format": "  ", "era": "historic-2026-08"}) == "Historic"


# ── the split ─────────────────────────────────────────────────────────────────

def rows():
    return [
        {"format": "Standard", "your_deck": "UW Control"},
        {"format": "Standard", "your_deck": "UW Control"},
        {"format": "Historic", "your_deck": "Golgari Yawgmoth"},
        {"era": "historic-2026-08", "your_deck": "Golgari Yawgmoth"},
    ]


def test_split_keeps_this_format_and_hands_back_the_rest():
    mine, theirs = pp.split_by_format(rows(), "Standard")
    assert len(mine) == 2
    assert len(theirs) == 2, "a row from another format is set aside, never dropped"


def test_split_is_case_insensitive():
    mine, _ = pp.split_by_format([{"format": "standard"}], "Standard")
    assert len(mine) == 1


def test_nothing_is_lost_by_the_split():
    """Guardrail 1. Every row lands on one side or the other."""
    all_rows = rows()
    mine, theirs = pp.split_by_format(all_rows, "Standard")
    assert len(mine) + len(theirs) == len(all_rows)


def test_a_ledger_with_no_format_field_still_splits():
    """The pre-2026-09-08 ledger has no format anywhere. It must still work."""
    legacy = [{"era": "the-hobbit-post-ban-2026-08-10"}, {"era": "historic-2026-08"}]
    mine, theirs = pp.split_by_format(legacy, "Standard")
    assert len(mine) == 1 and len(theirs) == 1


# ── the schema ────────────────────────────────────────────────────────────────

def test_format_is_an_accepted_key():
    assert "format" in pp.ROW_KEYS


def test_format_is_not_required():
    """
    Optional on purpose. Making it required would reject every line of the
    ledger written before the field existed, which is a migration disguised as
    a validation error.
    """
    assert "format" not in pp.ROW_REQUIRED


# ── the migration ─────────────────────────────────────────────────────────────

def ledger_lines():
    return [
        json.dumps({"date": "2026-08-05", "era": "historic-2026-08",
                    "your_deck": "Golgari Yawgmoth", "game": 1}) + "\n",
        json.dumps({"date": "2026-09-01", "era": "the-hobbit-post-ban-2026-08-10",
                    "your_deck": "UW Control", "game": 1}) + "\n",
    ]


def test_the_plan_stamps_from_the_era():
    steps = mig.plan(ledger_lines(), "Standard")
    assert [s[2] for s in steps] == ["Historic", "Standard"]
    assert all(s[3] == "stamp" for s in steps)


def test_a_row_that_already_has_a_format_is_left_alone():
    line = json.dumps({"date": "2026-08-05", "format": "Modern"}) + "\n"
    steps = mig.plan([line], "Standard")
    assert steps[0][3] == "already"
    assert mig.apply([line], steps) == [line], "byte for byte"


def test_an_unparseable_line_is_reported_and_left_byte_for_byte():
    """
    A migration that rewrites a line it could not parse is how a ledger loses a
    game. Report it and move on.
    """
    lines = ["{not json\n", ledger_lines()[0]]
    steps = mig.plan(lines, "Standard")
    assert steps[0][3] == "unparseable"
    out = mig.apply(lines, steps)
    assert out[0] == "{not json\n"


def test_blank_and_comment_lines_survive():
    lines = ["\n", "// a note\n", ledger_lines()[0]]
    steps = mig.plan(lines, "Standard")
    out = mig.apply(lines, steps)
    assert out[0] == "\n" and out[1] == "// a note\n"


def test_apply_puts_format_next_to_era_and_keeps_every_field():
    lines = ledger_lines()
    steps = mig.plan(lines, "Standard")
    out = mig.apply(lines, steps)
    row = json.loads(out[0])

    assert row["format"] == "Historic"
    assert list(row).index("format") == list(row).index("era") + 1
    assert row["your_deck"] == "Golgari Yawgmoth"
    assert row["game"] == 1


def test_the_migration_is_idempotent():
    """Guardrail 4. Running it twice must not change anything the second time."""
    lines = ledger_lines()
    once = mig.apply(lines, mig.plan(lines, "Standard"))
    twice = mig.apply(once, mig.plan(once, "Standard"))
    assert once == twice


# ── stale deck notes ──────────────────────────────────────────────────────────

def test_a_deck_note_for_another_format_is_named_not_rewritten(tmp_path):
    """
    After the split, a Historic deck note sits in the Standard folder and never
    gets regenerated. A stale generated note nobody mentions reads exactly like
    a current one.
    """
    (tmp_path / "[C] Play Profile - UW Control.md").write_text("current")
    (tmp_path / "[C] Play Profile - Golgari Yawgmoth.md").write_text("stale")
    (tmp_path / "[C] Play Profile.md").write_text("the cross-deck note")

    stale = pp._stale_deck_notes(str(tmp_path), {"UW Control": {}})

    assert stale == ["[C] Play Profile - Golgari Yawgmoth.md"]


def test_the_cross_deck_note_is_never_called_stale(tmp_path):
    (tmp_path / "[C] Play Profile.md").write_text("x")
    assert pp._stale_deck_notes(str(tmp_path), {}) == []


def test_a_rollup_backup_is_not_a_stale_deck_note(tmp_path):
    (tmp_path / "[C] Play Profile - UW Control.pre-rollup.md").write_text("x")
    assert pp._stale_deck_notes(str(tmp_path), {"UW Control": {}}) == []
