"""
The scoring model, and the two bugs that grew the review queue instead of
draining it. Both are regression-tested here by name.

  A raw 45-of-60 bar against references that range from 15 to 63 total slots
  meant 8 of 21 references could never produce a confident match, so every deck
  of those archetypes queued forever. Mono Green Landfall, the most-played deck
  in the format, was one of them.

  Selection had no margin, so Izzet / Izzet Elementals / Izzet Spellementals
  sat within 1-3 slots of each other and the winner was dictionary order.
"""
import pytest

from mtg_data.classify import classifier, refs_store


def entry(cards, **kw):
    mb = cards if isinstance(cards, dict) else {c: 4 for c in cards}
    e = {"mainboard": mb}
    e.update(kw)
    return e


def deck(cards, filler=0):
    d = cards if isinstance(cards, dict) else {c: 4 for c in cards}
    if filler:
        d = dict(d, **{f"Filler {i}": 1 for i in range(filler)})
    return d


# ── scoring ──────────────────────────────────────────────────────────────────

def test_coverage_and_containment_are_different_questions():
    ref = entry({"A": 4, "B": 4})                 # 8 slots
    d = {"A": 4, "B": 4, **{f"X{i}": 4 for i in range(13)}}   # 60 slots
    matched, coverage, containment = classifier.score_one(d, ref)
    assert matched == 8
    assert coverage == 1.0, "the reference is fully satisfied"
    assert containment == pytest.approx(8 / 60), "but it explains little of the deck"


def test_a_small_reference_can_now_reach_confidence():
    """
    The regression. A 36-slot reference can never score 45, so under the old
    raw-slot rule every deck of that archetype queued forever however perfect
    the match.
    """
    small = entry({f"C{i}": 3 for i in range(12)})   # 36 slots, unreachable before
    d = dict({f"C{i}": 3 for i in range(12)}, **{f"L{i}": 4 for i in range(6)})
    assert sum(small["mainboard"].values()) < 45
    v = classifier.classify(d, {"Small Deck": small})
    assert v.status == "confident"
    assert v.archetype == "Small Deck"


def test_a_reference_that_explains_a_third_of_the_deck_is_not_confident():
    thin = entry({"A": 4, "B": 4})
    d = dict({"A": 4, "B": 4}, **{f"X{i}": 4 for i in range(13)})
    v = classifier.classify(d, {"Thin": thin})
    assert v.status == "uncertain"
    assert v.reason == "containment"


# ── the margin ───────────────────────────────────────────────────────────────

def test_two_near_identical_references_produce_a_margin_verdict_not_a_coin_flip():
    """The Izzet trio. Dictionary order used to decide these."""
    shared = {f"S{i}": 4 for i in range(14)}
    a = entry(dict(shared, **{"A only": 4}))
    b = entry(dict(shared, **{"B only": 4}))
    d = dict(shared)
    v = classifier.classify(d, {"Izzet Elementals": a, "Izzet Spellementals": b})
    assert v.status == "uncertain"
    assert v.reason == "margin"
    assert {v.archetype, v.runner_up} == {"Izzet Elementals", "Izzet Spellementals"}


def test_a_clear_winner_still_wins():
    good = entry({f"C{i}": 4 for i in range(15)})
    poor = entry({f"D{i}": 4 for i in range(15)})
    d = {f"C{i}": 4 for i in range(15)}
    v = classifier.classify(d, {"Right": good, "Wrong": poor})
    assert v.status == "confident" and v.archetype == "Right"


def test_ordering_does_not_decide_a_tie():
    shared = {f"S{i}": 4 for i in range(15)}
    refs_ab = {"AAA": entry(shared), "ZZZ": entry(shared)}
    refs_ba = {"ZZZ": entry(shared), "AAA": entry(shared)}
    d = dict(shared)
    assert classifier.classify(d, refs_ab).status == "uncertain"
    assert classifier.classify(d, refs_ba).status == "uncertain"


# ── the gates ────────────────────────────────────────────────────────────────

def test_requires_keeps_a_deck_out_of_an_archetype_it_cannot_be():
    four_c = entry({f"S{i}": 4 for i in range(15)}, requires=["Inevitable Defeat"])
    jeskai_deck = {f"S{i}": 4 for i in range(15)}
    v = classifier.classify(jeskai_deck, {"Four-Color Control": four_c})
    assert v.status == "no_refs", "gated out entirely, not scored badly"


def test_excludes_separates_a_pair_that_margin_cannot():
    """
    Mono Green Landfall vs Selesnya Landfall: 61% shared slots, and on
    2026-09-07 that one pair was 108 of the 109 margin ties in the queue.
    """
    core = {f"G{i}": 4 for i in range(12)}
    mono = entry(dict(core, **{"Sapling Nursery": 3}), excludes=["Temple Garden", "Plains"])
    sels = entry(dict(core, **{"Temple Garden": 4}), requires=["Temple Garden", "Plains"])
    refs = {"Mono Green Landfall": mono, "Selesnya Landfall": sels}

    green = dict(core, **{"Sapling Nursery": 3, "Forest": 10})
    white = dict(core, **{"Temple Garden": 4, "Plains": 4, "Forest": 6})

    assert classifier.classify(green, refs).archetype == "Mono Green Landfall"
    assert classifier.classify(white, refs).archetype == "Selesnya Landfall"


def test_no_gates_means_eligible():
    assert refs_store.eligible({}, {"mainboard": {"A": 1}})
    assert refs_store.eligible({"Whatever": 4}, {"mainboard": {"A": 1}})


# ── signatures ───────────────────────────────────────────────────────────────

def test_signature_excludes_a_card_a_rival_also_plays():
    """
    Pooling rivals dilutes the test by the size of the field: Jeskai Revelation
    is in most Jeskai Control and most Four-Color Control decks, but those are
    30 decks in a 745-deck corpus, so pooled it reads as 4% elsewhere and passes
    as a signature of both.
    """
    labelled = []
    for _ in range(10):
        labelled.append(("Jeskai Control", {"Jeskai Revelation": 4, "Cori": 1}))
        labelled.append(("Four-Color Control", {"Jeskai Revelation": 4, "Defeat": 3}))
    for _ in range(10):
        labelled.append(("Mono Red", {"Lightning": 4}))

    sigs = classifier.signature_cards(labelled)
    assert "Jeskai Revelation" not in sigs.get("Jeskai Control", [])
    assert "Jeskai Revelation" not in sigs.get("Four-Color Control", [])
    assert "Defeat" in sigs.get("Four-Color Control", [])
    assert "Cori" in sigs.get("Jeskai Control", [])


def test_signature_needs_enough_decks_to_mean_anything():
    labelled = [("Brew", {"Weird Card": 4})] * 2 + [("Real", {"Normal": 4})] * 9
    sigs = classifier.signature_cards(labelled, min_decks=4)
    assert "Brew" not in sigs


def test_a_signature_settles_a_photo_finish():
    shared = {f"S{i}": 4 for i in range(15)}
    a = entry(dict(shared, **{"Tell": 1}), signature=["Tell"])
    b = entry(dict(shared, **{"Other": 1}))
    d = dict(shared, **{"Tell": 1})
    v = classifier.classify(d, {"A": a, "B": b})
    assert v.archetype == "A" and v.status == "confident"


def test_a_signature_cannot_overturn_a_better_coverage_match():
    """
    Coverage saturates at 1.0, so ranking on coverage-plus-bonus let a tell
    beat a reference that explained more of the deck. Signatures settle ties;
    they don't win arguments.
    """
    shared = {f"S{i}": 4 for i in range(10)}
    weak = entry(dict(shared, **{f"W{i}": 4 for i in range(8)}), signature=["Tell"])
    strong = entry(dict(shared, **{"Tell": 1}))
    d = dict(shared, **{"Tell": 1})
    v = classifier.classify(d, {"Weak With Tell": weak, "Strong": strong})
    assert v.archetype == "Strong"


def test_a_photo_finish_where_both_sides_have_a_tell_stays_uncertain():
    shared = {f"S{i}": 4 for i in range(15)}
    a = entry(shared, signature=["Tell A"])
    b = entry(shared, signature=["Tell B"])
    d = dict(shared, **{"Tell A": 1, "Tell B": 1})
    v = classifier.classify(d, {"A": a, "B": b})
    assert v.status == "uncertain" and v.reason == "margin"


# ── the verdict is actionable ────────────────────────────────────────────────

@pytest.mark.parametrize("refs,expected", [
    ({}, "no eligible reference"),
    ({"X": {"mainboard": {f"Z{i}": 4 for i in range(15)}}}, "coverage"),
])
def test_every_queued_deck_says_why(refs, expected):
    """A queue entry that doesn't say why it's there can't be acted on."""
    v = classifier.classify({f"A{i}": 4 for i in range(15)}, refs)
    assert v.reason == expected
    assert v.status != "confident"


def test_reasons_are_the_documented_set():
    allowed = {"confident", "coverage", "containment", "margin",
               "no eligible reference"}
    cases = [
        ({}, {}),
        ({"A": 4}, {"R": {"mainboard": {"A": 4}}}),
        ({"A": 4}, {"R": {"mainboard": {f"Z{i}": 4 for i in range(15)}}}),
    ]
    for d, r in cases:
        assert classifier.classify(d, r).reason in allowed
