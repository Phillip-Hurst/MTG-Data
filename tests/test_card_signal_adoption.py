"""
Tests for the sideboard adoption lens.

Before 2026-09-08 every lens in card_signal.py read `mainboard` and nothing
else, so a card that lived in the 15 was invisible to the whole card layer.
Sideboards were captured on all 835 MTGO decks in the pool the entire time.

Phill's 2026-09-07 ruling is that the sideboard is registered and reported and
never gated on. Classification still scores mainboards only. These tests pin the
reporting half and pin the boundary: `cards` and `counts` stay mainboard, so the
lenses that predate this behave exactly as they did.
"""
import os

import pytest

from mtg_data.analyze import card_signal as cs

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def deck(week_date, main=None, side=None, player="p", archetype="Placeholder A",
         place=1, etype="challenge"):
    main = main or {}
    side = side or {}
    all_counts = dict(main)
    for c, n in side.items():
        all_counts[c] = all_counts.get(c, 0) + n
    return {
        "date": week_date, "week": cs.iso_week(week_date),
        "event": "Event", "type": etype, "place": place, "player": player,
        "cards": set(main), "counts": main,
        "side": set(side), "side_counts": side,
        "all_cards": set(all_counts), "all_counts": all_counts,
        "archetype": archetype,
    }


def field(week_date, n, main=None, side=None, start=0, **kw):
    """n decks in one week, each with a distinct pilot."""
    return [deck(week_date, main=dict(main or {}), side=dict(side or {}),
                 player=f"p{start + i}", **kw) for i in range(n)]


# ── the week axis ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("day,monday", [
    ("2026-08-10", "2026-08-10"),  # a Monday
    ("2026-08-16", "2026-08-10"),  # the Sunday after it
    ("2026-08-17", "2026-08-17"),
])
def test_iso_week_snaps_to_monday(day, monday):
    assert cs.iso_week(day) == monday


def test_a_deck_with_no_date_has_no_week():
    assert cs.iso_week("") == ""
    assert cs.iso_week("not a date") == ""


def test_dateless_decks_are_dropped_and_counted(tmp_path):
    """
    Guardrail 1. A deck with no date can't be put in a week, and putting it in
    the wrong one is worse than leaving it out. This is why the melee cache
    isn't read here: its entries carry no event date.
    """
    decks = field("2026-08-10", 15) + field("2026-08-17", 15, start=15)
    for d in field("", 5, start=99):
        d["week"] = ""
        decks.append(d)

    weeks, _by_week, dropped = cs.weekly_buckets(decks)

    assert weeks == ["2026-08-10", "2026-08-17"]
    assert dropped["no_date"] == 5


def test_a_thin_week_is_dropped_and_named():
    """
    Weeks 3 and 4 of the live pool were 132 and 149 decks against 286 in week 1,
    and the 2026-09-07 week was 8. A share computed on 8 decks is noise wearing
    a percentage sign.
    """
    decks = field("2026-08-10", 20) + field("2026-08-17", 3, start=20)
    weeks, _b, dropped = cs.weekly_buckets(decks)

    assert weeks == ["2026-08-10"]
    assert dropped["thin_weeks"] == {"2026-08-17": 3}


# ── the sideboard, which is the whole point ───────────────────────────────────

def test_a_sideboard_only_card_is_found():
    """The bug in one test: this card is in no mainboard anywhere."""
    decks = (field("2026-08-10", 20, main={"island": 20}) +
             field("2026-08-17", 20, main={"island": 20},
                   side={"spell snare": 2}, start=20))

    rows, weeks, _ = cs.adoption(decks, board="side", min_pilots=3)
    found = {r["card"]: r for r in rows}

    assert "spell snare" in found
    assert found["spell snare"]["series"] == [0.0, 100.0]
    assert found["spell snare"]["move"] == 100.0
    assert found["spell snare"]["avg_copies"] == 2.0


def test_the_main_board_lens_ignores_the_sideboard():
    decks = (field("2026-08-10", 20, main={"island": 20}) +
             field("2026-08-17", 20, main={"island": 20},
                   side={"spell snare": 2}, start=20))

    rows, _w, _d = cs.adoption(decks, board="main", min_pilots=3)
    assert "spell snare" not in {r["card"] for r in rows}


def test_the_75_lens_sums_both_boards():
    """
    A card split 1 main and 3 side is a 4-of in the 75. Counting only one board
    is how "they went up to 4 Negate" reads as "they went down to 1".
    """
    decks = (field("2026-08-10", 20, main={"island": 20}) +
             field("2026-08-17", 20, main={"negate": 1}, side={"negate": 3},
                   start=20))

    rows, _w, _d = cs.adoption(decks, board="75", min_pilots=3)
    negate = next(r for r in rows if r["card"] == "negate")

    assert negate["avg_copies"] == 4.0
    assert negate["series"] == [0.0, 100.0]


def test_collect_decks_keeps_cards_and_counts_mainboard_only(tmp_path):
    """
    The boundary that protects the older lenses. rogue, deviation and trend all
    read `cards`, and quietly folding the sideboard into it would change every
    number they print without anyone asking for it.
    """
    import json
    ev = [{"url": "e1", "name": "Challenge", "date": "2026-08-10",
           "event_type": "challenge",
           "decks": [{"url": "d1", "player": "p1", "place": "1",
                      "mainboard": {"Island": 20},
                      "sideboard": {"Spell Snare": 2}}]}]
    (tmp_path / "mtgo_challenge_latest.json").write_text(json.dumps(ev))
    (tmp_path / "mtgo_5-0_latest.json").write_text("[]")
    (tmp_path / "mtgo_classifications.json").write_text("{}")

    decks = cs.collect_decks(str(tmp_path), None)

    assert decks[0]["cards"] == {"island"}
    assert decks[0]["side"] == {"spell snare"}
    assert decks[0]["all_cards"] == {"island", "spell snare"}
    assert decks[0]["week"] == "2026-08-10"


# ── filters ───────────────────────────────────────────────────────────────────

def test_a_card_that_barely_moved_is_not_reported():
    decks = (field("2026-08-10", 100, side={"annul": 1}, start=0) +
             field("2026-08-10", 0) +
             field("2026-08-17", 98, side={"annul": 1}, start=200) +
             field("2026-08-17", 2, start=400))
    rows, _w, _d = cs.adoption(decks, board="side", min_pilots=3)
    assert "annul" not in {r["card"] for r in rows}, \
        "100% to 98% is breathing, not a move"


def test_a_card_on_too_few_pilots_is_not_reported():
    decks = (field("2026-08-10", 20) +
             field("2026-08-17", 19, start=20) +
             [deck("2026-08-17", side={"rest in peace": 1}, player="solo")])
    rows, _w, _d = cs.adoption(decks, board="side", min_pilots=3)
    assert "rest in peace" not in {r["card"] for r in rows}


def test_one_week_of_data_reports_nothing():
    rows, weeks, _d = cs.adoption(field("2026-08-10", 30), board="side")
    assert rows == []
    assert len(weeks) == 1


def test_basic_lands_stay_out():
    decks = (field("2026-08-10", 20, side={"island": 1}) +
             field("2026-08-17", 20, start=20))
    rows, _w, _d = cs.adoption(decks, board="side", min_pilots=3)
    assert "island" not in {r["card"] for r in rows}


# ── card attributes ───────────────────────────────────────────────────────────

def test_attributes_ride_along_when_the_pool_has_them():
    """
    The pool held 5,365 names and nothing else until 2026-09-08, so the tool
    could count a card and say nothing about what kind of card it was.
    """
    decks = (field("2026-08-10", 20) +
             field("2026-08-17", 20, side={"flashfreeze": 2}, start=20))
    attrs = {"flashfreeze": {"cmc": 2.0, "colors": ["U"],
                             "color_identity": ["U"], "type_line": "Instant"}}

    rows, _w, _d = cs.adoption(decks, board="side", min_pilots=3, attrs=attrs)
    ff = next(r for r in rows if r["card"] == "flashfreeze")

    assert ff["colors"] == "U"
    assert ff["type"] == "Instant"
    assert ff["cmc"] == 2.0


def test_a_pool_with_no_attributes_leaves_the_columns_blank():
    """Blank, and the renderer says why. It must not imply the card is colourless."""
    decks = (field("2026-08-10", 20) +
             field("2026-08-17", 20, side={"flashfreeze": 2}, start=20))
    rows, _w, _d = cs.adoption(decks, board="side", min_pilots=3, attrs={})
    ff = next(r for r in rows if r["card"] == "flashfreeze")
    assert ff["colors"] == ""
    assert ff["type"] == ""


def test_the_renderer_says_when_attributes_are_missing():
    decks = (field("2026-08-10", 20) +
             field("2026-08-17", 20, side={"flashfreeze": 2}, start=20))
    text = cs.render(decks, 8.0, ["adoption"], 3, 15, None,
                     opts={"board": "side", "attrs": {}})
    assert "build-card-pool" in text


# ── per archetype ─────────────────────────────────────────────────────────────

def test_archetype_adoption_averages_copies_in_the_75():
    """
    Dimir Midrange going 1.5 to 2.3 Flashfreeze over 4 weeks is 30 pilots
    independently deciding the same thing about red and green. That reads as a
    hedge in a way a field-wide share never can.
    """
    decks = (field("2026-08-10", 6, main={"flashfreeze": 1},
                   archetype="Dimir Midrange") +
             field("2026-08-17", 6, side={"flashfreeze": 3},
                   archetype="Dimir Midrange", start=20) +
             field("2026-08-10", 20, archetype="Other Deck", start=50))

    rows, weeks, _d = cs.archetype_adoption(decks, "Dimir Midrange", board="75")
    ff = next(r for r in rows if r["card"] == "flashfreeze")

    assert len(weeks) == 2
    assert ff["series"] == [1.0, 3.0]
    assert ff["move"] == 2.0
    assert ff["n_per_week"] == [6, 6]


def test_archetype_adoption_matches_case_insensitively():
    decks = (field("2026-08-10", 6, main={"flashfreeze": 1},
                   archetype="Dimir Midrange") +
             field("2026-08-17", 6, main={"flashfreeze": 3},
                   archetype="Dimir Midrange", start=20))
    rows, _w, _d = cs.archetype_adoption(decks, "dimir midrange", board="75")
    assert rows


def test_an_archetype_with_no_decks_reports_nothing():
    rows, weeks, _d = cs.archetype_adoption(field("2026-08-10", 20),
                                            "Nonexistent Deck")
    assert rows == [] and weeks == []
