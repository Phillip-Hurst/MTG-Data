"""
Tests for deck_labels.resolve_pairing_decks.

1.19.0 moved meta share onto deck_labels and left the matchup layer reading
deck names straight off the CSV row, so matchup_matrix, winrate_analysis and
update_archetypes got aliases but never a classifier verdict. One deck under
three house styles was three thin cells that each missed the 10-match floor.

Measured 2026-09-08 on the full rebuilt pool (1,519 rows): distinct labels went
122 to 104, 387 seats were relabelled, and cells at the floor went 8 to 14.
"""
import os
import sys

import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

import deck_labels as dl  # noqa: E402


class FakeVerdict:
    def __init__(self, archetype, status="confident", coverage=0.9, reason=""):
        self.archetype = archetype
        self.status = status
        self.coverage = coverage
        self.reason = reason


class FakeResolver(dl.Resolver):
    """A Resolver with the cache, overrides and classifier stubbed out."""

    def __init__(self, cache=None, overrides=None, verdicts=None):
        self.data_dir = "."
        self.problems = []
        from collections import Counter
        self.counts = Counter()
        self._verdicts = {}
        self.cache = cache or {}
        self.overrides = overrides or {}
        self.refs = {"Placeholder Ref": {}}
        self._forced = verdicts or {}

    def _classify(self, url, mainboard):
        return self._forced.get(url, FakeVerdict(None, status="unsure",
                                                 reason="no reference"))


def row(p1_deck="", p1_url="", p2_deck="", p2_url=""):
    return {
        "tournament_id": "111", "tournament_name": "Event 111",
        "round": "1", "table_num": "1",
        "player1": "a", "player1_deck": p1_deck, "player1_deck_url": p1_url,
        "player2": "b", "player2_deck": p2_deck, "player2_deck_url": p2_url,
        "result": "a won 2-0-0", "winner": "a",
    }


# ── the merge, which is where the value is ────────────────────────────────────

def test_a_classifier_verdict_overrides_the_organizers_text():
    """
    The whole point. A deck filed under the wrong name is a thin cell that
    misses the 10-match floor, plus another thin cell where it belonged.

    `seat_relabelled` counts against the aliased row text, because the alias
    table already ran before this change. It measures what the classifier
    moved, not what an alias would have moved anyway.
    """
    r = FakeResolver(
        cache={"u1": {"mainboard": {"island": 4}, "archetype": "Izzet Tempo"}},
        verdicts={"u1": FakeVerdict("Izzet Spellementals")},
    )
    rows, stats = dl.resolve_pairing_decks(
        [row("Izzet Tempo", "u1", "Placeholder B", "")], resolver=r)

    assert rows[0]["player1_deck"] == "Izzet Spellementals"
    assert stats["seat_classifier"] == 1
    assert stats["seat_relabelled"] == 1


def test_an_alias_alone_does_not_count_as_a_relabel():
    """
    "Izzet Elementals" already resolved to "Izzet Spellementals" through
    mtg_stats before any of this. Counting it here would inflate the claim
    about what the classifier join changed.
    """
    r = FakeResolver(
        cache={"u1": {"mainboard": {"island": 4}}},
        verdicts={"u1": FakeVerdict("Izzet Spellementals")},
    )
    _, stats = dl.resolve_pairing_decks([row("Izzet Elementals", "u1")], resolver=r)

    assert stats["seat_relabelled"] == 0


def test_an_override_beats_the_classifier():
    r = FakeResolver(
        cache={"u1": {"mainboard": {"island": 4}}},
        overrides={"u1": {"archetype": "Azorius Flash", "decided": "2026-09-01"}},
        verdicts={"u1": FakeVerdict("Azorius Momo")},
    )
    rows, stats = dl.resolve_pairing_decks([row("Azorius Tempo", "u1")], resolver=r)

    assert rows[0]["player1_deck"] == "Azorius Flash"
    assert stats["seat_override"] == 1


def test_an_unconfident_verdict_falls_back_to_the_cached_archetype():
    r = FakeResolver(cache={"u1": {"mainboard": {"island": 4},
                                   "archetype": "Dimir Aggro"}})
    rows, stats = dl.resolve_pairing_decks([row("", "u1")], resolver=r)

    # Dimir Aggro is an alias of Dimir Midrange in mtg_stats.
    assert rows[0]["player1_deck"] == "Dimir Midrange"
    assert stats["seat_organizer"] == 1


def test_aliases_are_applied_to_plain_row_text():
    """No URL, so nothing to look up. The alias table still has to run."""
    r = FakeResolver()
    rows, stats = dl.resolve_pairing_decks([row("W-U-B-R Control", "")], resolver=r)

    assert rows[0]["player1_deck"] == "Four-Color Control"
    assert stats["seat_row_text"] == 1


# ── what it cannot fix ────────────────────────────────────────────────────────

def test_a_seat_with_no_name_and_no_url_is_blanked():
    """
    775 of the 783 unnamed seats in the live pool have no deck URL at all, so
    there is nothing to look them up by. Blanking the seat makes classify_row
    drop the row rather than counting a match against a deck nobody can name.
    """
    r = FakeResolver()
    rows, stats = dl.resolve_pairing_decks(
        [row("", "", "Jeskai Control", "")], resolver=r)

    assert rows[0]["player1_deck"] == ""
    assert rows[0]["player2_deck"] == "Jeskai Control"
    assert stats["seat_unnamed_no_url"] == 1


def test_junk_organizer_text_is_not_a_deck_name():
    r = FakeResolver()
    rows, stats = dl.resolve_pairing_decks([row("Decklist", "")], resolver=r)
    assert rows[0]["player1_deck"] == ""


def test_strict_mode_drops_organizer_text_entirely():
    """
    build_baseline's rule, available here for the strict reading: a row whose
    deck has no cached list says nothing about what was played.
    """
    r = FakeResolver()
    rows, stats = dl.resolve_pairing_decks(
        [row("Boros Aggro", "")], resolver=r, keep_organizer_text=False)

    assert rows[0]["player1_deck"] == ""
    assert stats["seat_row_text"] == 0


# ── accounting ────────────────────────────────────────────────────────────────

def test_usable_rows_needs_both_seats_named():
    r = FakeResolver()
    rows, stats = dl.resolve_pairing_decks([
        row("Boros Aggro", "", "Jeskai Control", ""),
        row("Boros Aggro", "", "", ""),
    ], resolver=r)

    assert stats["rows"] == 2
    assert stats["rows_usable"] == 1


def test_the_report_names_what_was_left_unnamed():
    """Guardrail 12. A join that only reports successes can't be checked."""
    r = FakeResolver()
    _, stats = dl.resolve_pairing_decks([row("", ""), row("Boros Aggro", "")],
                                        resolver=r)
    text = "\n".join(dl.pairing_report_lines(stats))

    assert "seats left unnamed" in text
    assert "no_url" in text
    assert "usable rows: 0 of 2" in text


def test_resolving_twice_is_stable():
    """Guardrail 4. The second pass sees names it wrote on the first."""
    r = FakeResolver(
        cache={"u1": {"mainboard": {"island": 4}, "archetype": "Izzet Elementals"}},
        verdicts={"u1": FakeVerdict("Izzet Spellementals")},
    )
    rows = [row("Izzet Elementals", "u1", "Jeskai Control", "")]
    rows, _ = dl.resolve_pairing_decks(rows, resolver=r)
    first = [dict(x) for x in rows]
    rows, _ = dl.resolve_pairing_decks(rows, resolver=r)

    assert rows == first


def test_it_needs_a_data_dir_or_a_resolver():
    with pytest.raises(ValueError):
        dl.resolve_pairing_decks([row()])
