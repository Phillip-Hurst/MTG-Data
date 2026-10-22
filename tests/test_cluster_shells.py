"""
The stage that was missing: turning unmatched decks into named categories.

References used to be built only by grouping decks that already had a label, so
a deck whose archetype had no reference never got classified, never fed a
reference, and returned in the queue every run. The queue grew because nothing
in the pipeline could create a category.
"""
import json

import pytest

from mtg_data.classify import cluster_shells as cs
from mtg_data.classify import refs_store


def landfall(extra=None, n=4):
    d = {"Llanowar Elves": 4, "Icetill Explorer": 4, "Fabled Passage": 4,
         "Sapling Nursery": 3, "Forest": 12}
    if extra:
        d.update(extra)
    return d


def prowess(extra=None):
    d = {"Slickshot Show-Off": 4, "Elusive Otter": 4, "Opt": 4,
         "Spirebluff Canal": 4, "Island": 8}
    if extra:
        d.update(extra)
    return d


# ── the core signature ───────────────────────────────────────────────────────

def test_basics_and_singletons_are_not_what_a_deck_is():
    core = cs.deck_core({"Real Card": 4, "One Of": 1, "Island": 12, "Forest": 8})
    assert core == {"Real Card"}


def test_two_unrelated_decks_are_not_similar_just_because_both_play_islands():
    a = cs.deck_core({"Island": 12, "A": 4, "B": 4})
    b = cs.deck_core({"Island": 12, "C": 4, "D": 4})
    assert cs.jaccard(a, b) == 0.0


# ── clustering ───────────────────────────────────────────────────────────────

def test_variants_of_one_deck_land_in_one_shell():
    decks = [(f"u{i}", landfall({"Tech Card": i % 2 + 1})) for i in range(6)]
    shells = cs.cluster(decks)
    assert len(shells) == 1
    assert len(shells[0].members) == 6


def test_two_decks_stay_two_shells():
    decks = [(f"g{i}", landfall()) for i in range(4)]
    decks += [(f"p{i}", prowess()) for i in range(4)]
    shells = cs.cluster(decks)
    assert len(shells) == 2
    assert sorted(len(s.members) for s in shells) == [4, 4]


def test_clustering_is_stable_regardless_of_input_order():
    decks = [(f"g{i}", landfall()) for i in range(4)] + \
            [(f"p{i}", prowess()) for i in range(3)]
    a = [len(s.members) for s in cs.cluster(decks)]
    b = [len(s.members) for s in cs.cluster(list(reversed(decks)))]
    assert a == b


def test_a_shell_builds_a_reference_from_what_its_decks_agree_on():
    decks = [(f"u{i}", landfall()) for i in range(5)]
    shell = cs.cluster(decks)[0]
    ref = shell.reference()
    assert ref["Llanowar Elves"] == 4
    assert sum(ref.values()) <= 60


def test_a_card_only_half_the_shell_plays_stays_out_of_the_reference():
    decks = [("a", landfall({"Splash": 2})), ("b", landfall({"Splash": 2})),
             ("c", landfall()), ("d", landfall()), ("e", landfall())]
    shell = cs.cluster(decks)[0]
    assert "Splash" not in shell.reference()


# ── the note round trip ──────────────────────────────────────────────────────

def _note(tmp_path, blocks):
    text = "# Unnamed shells\n\n"
    for name, uids in blocks:
        text += (f"\n## Shell x — {len(uids)} decks\n\nCore: whatever\n\n"
                 f"Name: {name}\n\n```shell-id\n"
                 f"{json.dumps({'uids': uids})}\n```\n\n---\n")
    p = tmp_path / "[C] Unnamed Shells 2026-09-07.md"
    p.write_text(text, encoding="utf-8")
    return [str(p)]


def test_named_shells_are_read_back(tmp_path):
    paths = _note(tmp_path, [("Golgari Demons", ["u1", "u2"])])
    got = cs.read_names(paths)
    assert [(n, u) for n, u, _ in got] == [("Golgari Demons", ["u1", "u2"])]


def test_a_blank_name_does_not_swallow_the_next_shell(tmp_path):
    """
    One DOTALL regex over the whole file ran past a blank Name: into the next
    block and took its fence as the name, which produced references literally
    called "```shell-id".
    """
    paths = _note(tmp_path, [("", ["u1"]), ("Real Name", ["u2"])])
    got = cs.read_names(paths)
    assert [(n, u) for n, u, _ in got] == [("Real Name", ["u2"])]
    assert not any(n.startswith("`") for n, _, _ in got)


@pytest.mark.parametrize("word", ["skip", "SKIP", "tbd", "?", ""])
def test_deferring_a_shell_keeps_it_out(tmp_path, word):
    paths = _note(tmp_path, [(word, ["u1"])])
    assert cs.read_names(paths) == []


def test_two_shells_with_the_same_name_are_combined_not_overwritten():
    """A deck often clusters into a main build and a smaller variant."""
    a = refs_store.make_entry({"A": 4, "B": 4}, decks=18)
    b = refs_store.make_entry({"A": 4, "C": 4}, decks=3)
    combined = refs_store.combine([a, b])
    assert refs_store.decks_behind(combined) == 21
    assert "A" in combined["mainboard"]


def test_name_suggestions_come_from_the_cache_not_from_thin_air():
    decks = [(f"u{i}", landfall()) for i in range(4)]
    shell = cs.cluster(decks)[0]
    cache = {"url1": {"archetype": "Mono Green Landfall", "mainboard": landfall()},
             "url2": {"archetype": "Izzet Prowess", "mainboard": prowess()}}
    sugg = cs.name_suggestions(shell, cache)
    assert sugg and sugg[0][0] == "Mono Green Landfall"
    assert "Izzet Prowess" not in [a for a, _, _ in sugg]


def test_no_similar_cache_deck_means_no_suggestion():
    shell = cs.cluster([("u1", landfall()), ("u2", landfall())])[0]
    cache = {"url": {"archetype": "Izzet Prowess", "mainboard": prowess()}}
    assert cs.name_suggestions(shell, cache) == []


def test_a_suggestion_is_never_written_onto_the_name_line(tmp_path, monkeypatch):
    """
    A proposal must not look like a decision. Prefilling `Name:` meant a note
    nobody had opened would apply its own guesses on the next --apply.
    """
    monkeypatch.setattr(cs, "OUT_DIR", str(tmp_path))
    shells = cs.cluster([(f"u{i}", landfall()) for i in range(4)])
    vocab = {"Mono-Green Landfall": {"meta_pct": 17.7, "decks": 227,
             "defining": ["Icetill Explorer", "Llanowar Elves", "Sapling Nursery"]}}
    monkeypatch.setattr(cs.fetch_vocabulary, "load", lambda: vocab)

    path, _ = cs.write_note(shells, {}, "2026-09-07", 3)
    text = open(path, encoding="utf-8").read()

    assert "Suggested: Mono-Green Landfall" in text
    assert cs.read_names([path]) == [], "a suggestion alone is not a ruling"

    text = text.replace("Name: ", "Name: Mono-Green Landfall")
    open(path, "w", encoding="utf-8").write(text)
    assert [n for n, _, _ in cs.read_names([path])] == ["Mono-Green Landfall"]
