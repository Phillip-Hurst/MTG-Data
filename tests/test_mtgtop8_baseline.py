"""
Tests for the mtgtop8 baseline parsers (build_mtgtop8_baseline).

All fixtures are static strings — no network. They mirror the real mtgtop8
markup (including the &amp; entity form hrefs arrive in) and the real mtgo
plaintext export, so the parsing logic is pinned without hitting the site.

Run:  pytest          (from the skill folder)
"""
import build_mtgtop8_baseline as b


# A trimmed but faithful mtgo decklist export (single-slash DFC, Sideboard split).
DECKLIST = """\
4 Opt
2 Roaring Furnace/Steaming Sauna
4 Eddymurk Crab
8 Island
Sideboard
2 Flashfreeze
1 Spell Pierce
"""


def test_parse_decklist_mainboard_only_and_dfc_frontfaced():
    parsed = b.parse_decklist(DECKLIST)
    mb = parsed["mainboard"]
    assert mb["Opt"] == 4
    assert mb["Eddymurk Crab"] == 4
    assert mb["Island"] == 8
    # DFC front-faced, single-slash stripped.
    assert mb["Roaring Furnace"] == 2
    assert "Steaming Sauna" not in mb
    # Sideboard excluded.
    assert "Flashfreeze" not in mb


# Metagame page: group headers carry their % BEFORE the first archetype link,
# archetype links carry their % AFTER. Includes an &amp; href to prove the
# entity form parses.
METAGAME = (
    '211 decks'
    'AGGRO 51%'
    '<a href="archetype?a=150&amp;meta=50&amp;f=ST">Selesnya Aggro</a>20 %'
    '<a href="archetype?a=207&meta=50&f=ST">UR Aggro</a>12 %'
    'CONTROL 42%'
    '<a href="archetype?a=15&meta=50&f=ST">Izzet Control</a>24 %'
    'COMBO 7%'
    '<a href="archetype?a=227&meta=50&f=ST">Reanimator</a>7 %'
)


def test_parse_metagame_sample_and_shares():
    sample, archs = b.parse_metagame(METAGAME)
    assert sample == 211
    by_name = {a["name"]: a for a in archs}
    # Group-header percentages (51, 42, 7 attached to AGGRO/CONTROL/COMBO) are
    # never read as an archetype share.
    assert by_name["Selesnya Aggro"]["share_pct"] == 20.0
    assert by_name["UR Aggro"]["share_pct"] == 12.0
    assert by_name["Izzet Control"]["share_pct"] == 24.0
    assert by_name["Reanimator"]["share_pct"] == 7.0
    # href rebuilt for the archetype-page fetch.
    assert by_name["Izzet Control"]["href"].endswith("archetype?a=15&meta=50&f=ST")


# Archetype page: deck rows are event?e=...&d=...&f=..., newest first, and the
# umbrella links at the top (archetype?a=) must NOT be picked up as decks.
ARCHETYPE_PAGE = (
    '<a href="archetype?a=15&meta=50&f=ST">Izzet Control</a>24 %'
    '<a href="event?e=87331&amp;d=862775&amp;f=ST">Izzet Lesson</a>'
    '<a href="event?e=87332&d=862786&f=ST">Izzet Spellementals</a>'
    '<a href="event?e=87300&d=862556&f=ST">Izzet Control</a>'
    '<a href="event?e=87331&d=862775&f=ST">Izzet Lesson</a>'  # dup d_id, dropped
)


def test_parse_archetype_decks_order_dedupe_and_no_umbrella():
    decks = b.parse_archetype_decks(ARCHETYPE_PAGE)
    ids = [d["d_id"] for d in decks]
    assert ids == ["862775", "862786", "862556"]      # order kept, dup removed
    labels = [d["label"] for d in decks]
    assert labels[0] == "Izzet Lesson"
    # The umbrella archetype?a=15 link is not a deck row.
    assert all(d["d_id"] != "15" for d in decks)


def test_build_ref_from_decks_is_reused_not_reimplemented():
    # Two lists, a card in both at modal 4 should survive; a 1-of in one of two
    # lists (<=50% frequency) should be dropped. Confirms we're using the shared
    # >50% modal rule.
    decks = [
        {"mainboard": {"Opt": 4, "Spell Pierce": 1}},
        {"mainboard": {"Opt": 4}},
    ]
    ref = b.build_ref_from_decks(decks)
    assert ref["Opt"] == 4
    assert "Spell Pierce" not in ref
