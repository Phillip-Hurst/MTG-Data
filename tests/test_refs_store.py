"""
The references are a dataset that accumulates. These tests are the guard against
the two ways it used to reset itself:

  build_refs_from_melee.py / classify_decks.py replaced the whole archetypes dict,
  so any reference the current run couldn't rebuild vanished, silently, exit 0.

  build_mtgtop8_baseline.py only added missing labels, so a 3-deck seed outranked
  a 40-deck local rebuild forever.

Both are regression-tested here by name.
"""
import json
from datetime import date

import pytest

from mtg_data.classify import refs_store


def ref(cards, decks=None, notes=None, **kw):
    mb = {c: 4 for c in cards} if isinstance(cards, (list, tuple)) else cards
    return refs_store.make_entry(mb, notes=notes, decks=decks, **kw)


# ── deck counting ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("notes,expected", [
    ("Built from 14 melee.gg decklist(s)", 14),
    ("Built from 9 decklists", 9),
    ("Baseline from mtgtop8 (Izzet Control umbrella), 5 list(s), 2026-08-29", 5),
    ("Built from 1 decklist", 1),
    ("hand-written, no provenance", 0),
    ("", 0),
])
def test_deck_count_read_out_of_legacy_notes(notes, expected):
    """Entries written before refs_store existed still have to be comparable."""
    assert refs_store.decks_behind({"mainboard": {}, "notes": notes}) == expected


def test_explicit_count_beats_the_notes_string():
    e = {"mainboard": {}, "notes": "Built from 3 decklists", "decks": 40}
    assert refs_store.decks_behind(e) == 40


# ── the merge policy ─────────────────────────────────────────────────────────

def test_a_label_missing_from_the_incoming_set_survives():
    """The Four-Color Control (Black Base) regression, 2026-09-07."""
    existing = {"Black Base": ref(["Duress"], decks=3),
                "Jeskai Base": ref(["Lightning Helix"], decks=13)}
    incoming = {"Jeskai Base": ref(["Lightning Helix", "Sear"], decks=14)}

    merged, report = refs_store.merge(existing, incoming)

    assert "Black Base" in merged
    assert merged["Black Base"]["decks"] == 3
    assert report["updated"] == ["Jeskai Base"]
    assert report["added"] == []


def test_more_decks_wins():
    existing = {"Dimir": ref(["Deceit"], decks=4)}
    incoming = {"Dimir": ref(["Deceit", "Duress"], decks=11)}
    merged, report = refs_store.merge(existing, incoming)
    assert merged["Dimir"]["decks"] == 11
    assert "Duress" in merged["Dimir"]["mainboard"]
    assert report["updated"] == ["Dimir"]


def test_fewer_decks_loses_and_says_so():
    existing = {"Dimir": ref(["Deceit", "Duress"], decks=11)}
    incoming = {"Dimir": ref(["Deceit"], decks=2)}
    merged, report = refs_store.merge(existing, incoming)
    assert merged["Dimir"]["decks"] == 11
    assert "Duress" in merged["Dimir"]["mainboard"]
    assert report["kept_richer"] == ["Dimir"]


def test_a_seed_fills_a_gap_then_gets_superseded():
    """The build_mtgtop8_baseline regression: add-only froze thin seeds in place."""
    seeded, _ = refs_store.merge({}, {"Izzet": ref(["Sunderflock"], decks=3)},
                                 source="mtgtop8")
    assert seeded["Izzet"]["decks"] == 3

    grown, report = refs_store.merge(
        seeded, {"Izzet": ref(["Sunderflock", "Eddymurk Crab"], decks=40)},
        source="melee-cache")
    assert grown["Izzet"]["decks"] == 40
    assert grown["Izzet"]["source"] == "melee-cache"
    assert report["updated"] == ["Izzet"]


def test_equal_counts_refresh_rather_than_stall():
    existing = {"Boros": ref(["Helix"], decks=6)}
    incoming = {"Boros": ref(["Helix", "Sear"], decks=6)}
    merged, report = refs_store.merge(existing, incoming, when=date(2026, 9, 7))
    assert "Sear" in merged["Boros"]["mainboard"]
    assert merged["Boros"]["updated"] == "2026-09-07"
    assert report["updated"] == ["Boros"]


def test_pinned_references_are_never_overwritten():
    """For references anchored on a list no scrape will ever produce."""
    existing = {"Deriu 4CC": ref(["Inevitable Defeat"], decks=3, pinned=True)}
    incoming = {"Deriu 4CC": ref(["Something Else"], decks=99)}
    merged, report = refs_store.merge(existing, incoming)
    assert "Inevitable Defeat" in merged["Deriu 4CC"]["mainboard"]
    assert report["kept_pinned"] == ["Deriu 4CC"]
    assert report["updated"] == []


def test_malformed_entries_are_rejected_not_written():
    existing = {"Good": ref(["A"], decks=1), "Bad": {"notes": "no mainboard"}}
    merged, report = refs_store.merge(existing, {})
    assert set(merged) == {"Good"}
    assert report["rejected"] == ["Bad"]


def test_dropping_a_label_is_explicit():
    existing = {"Keep": ref(["A"], decks=1), "Retire": ref(["B"], decks=1)}
    merged, report = refs_store.merge(existing, {}, drop=["Retire"])
    assert set(merged) == {"Keep"}
    assert report["dropped"] == ["Retire"]


# ── save() round trip ────────────────────────────────────────────────────────

def test_save_merges_by_default(tmp_path):
    path = str(tmp_path / "archetype_refs.json")
    refs_store.save(path, {"A": ref(["x"], decks=2), "B": ref(["y"], decks=2)},
                    source="melee-cache", quiet=True)
    refs_store.save(path, {"A": ref(["x", "z"], decks=5)},
                    source="melee-cache", quiet=True)

    got = refs_store.load(path)
    assert set(got) == {"A", "B"}, "B was dropped by a run that couldn't rebuild it"
    assert got["A"]["decks"] == 5


def test_save_replace_needs_asking_for_and_backs_up(tmp_path):
    path = str(tmp_path / "archetype_refs.json")
    refs_store.save(path, {"A": ref(["x"], decks=2), "B": ref(["y"], decks=2)},
                    source="melee-cache", quiet=True)
    report = refs_store.save(path, {"A": ref(["x"], decks=2)},
                             source="melee-cache", replace=True, quiet=True)

    assert set(refs_store.load(path)) == {"A"}
    assert report["replaced"] == ["B"]
    backup = tmp_path / "archetype_refs.pre-replace.json"
    assert backup.exists()
    assert set(json.loads(backup.read_text(encoding="utf-8"))["archetypes"]) == {"A", "B"}


def test_save_backfills_provenance_onto_legacy_entries(tmp_path):
    """A file written by the old scripts self-heals on the first merge."""
    path = tmp_path / "archetype_refs.json"
    path.write_text(json.dumps({
        "_schema_version": 1,
        "archetypes": {
            "Legacy": {"mainboard": {"Card": 4},
                       "notes": "Built from 7 melee.gg decklist(s)"}}
    }), encoding="utf-8")

    refs_store.save(str(path), {}, source="melee-cache", quiet=True)
    got = refs_store.load(str(path))
    assert got["Legacy"]["decks"] == 7
    assert got["Legacy"]["updated"]


def test_save_leaves_the_file_intact_when_incoming_is_empty(tmp_path):
    path = str(tmp_path / "archetype_refs.json")
    refs_store.save(path, {"A": ref(["x"], decks=2)}, source="melee-cache", quiet=True)
    refs_store.save(path, {}, source="melee-cache", quiet=True)
    assert set(refs_store.load(path)) == {"A"}


def test_mainboard_is_the_only_shape_older_readers_need(tmp_path):
    """Provenance keys are additive; nothing downstream reads them."""
    path = str(tmp_path / "archetype_refs.json")
    refs_store.save(path, {"A": ref({"Island": 4}, decks=2)},
                    source="melee-cache", quiet=True)
    entry = refs_store.load(path)["A"]
    assert entry["mainboard"] == {"Island": 4}
    assert set(entry) >= {"mainboard", "decks", "source", "updated"}


# ── the writers actually route through it ────────────────────────────────────

@pytest.mark.parametrize("module_name", [
    "mtg_data.classify.build_refs_from_melee", "mtg_data.classify.classify_decks",
    "mtg_data.ingest.build_mtgtop8_baseline", "mtg_data.quality.audit_refs",
])
def test_every_writer_uses_the_shared_store(module_name):
    """
    No script may hand-roll a write to archetype_refs.json. That is how the two
    opposite bugs got in, and how a third would.
    """
    import importlib
    mod = importlib.import_module(module_name)
    assert getattr(mod, "refs_store", None) is refs_store, (
        f"{module_name} does not import refs_store")


def test_no_script_writes_the_refs_file_directly():
    import pathlib
    root = pathlib.Path(refs_store.__file__).parent.parent   # the mtg_data package
    offenders = []
    for py in sorted(root.rglob("*.py")):
        if py.name in ("refs_store.py", "archive_era.py"):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "archetype_refs.json" in line and 'open(' in line and '"w"' in line:
                offenders.append(f"{py.name}:{i}")
    assert not offenders, ("writes archetype_refs.json outside refs_store: "
                           + ", ".join(offenders))


def test_untouched_labels_are_reported_not_silently_carried():
    """
    The old failure was invisible: nothing said a reference had been dropped.
    The report has to account for every label on file, including the ones this
    run had nothing to say about.
    """
    existing = {"A": ref(["x"], decks=1), "B": ref(["y"], decks=1),
                "C": ref(["z"], decks=1)}
    incoming = {"A": ref(["x", "w"], decks=9)}
    merged, report = refs_store.merge(existing, incoming)

    accounted = set(report["added"]) | set(report["updated"]) \
        | set(report["kept_richer"]) | set(report["kept_pinned"]) \
        | set(report["untouched"])
    assert accounted == set(merged) == {"A", "B", "C"}
    assert report["untouched"] == ["B", "C"]


def test_a_dropped_label_is_only_reported_as_dropped():
    existing = {"A": ref(["x"], decks=1), "Retire": ref(["y"], decks=1)}
    merged, report = refs_store.merge(existing, {}, drop=["Retire"])
    assert report["dropped"] == ["Retire"]
    assert "Retire" not in report["untouched"]
    assert "Retire" not in merged


def test_requires_gates_a_reference():
    """
    Three-colour Jeskai shares most of its 60 with four-colour Jeskai Tablet.
    Without a gate it scores into the wrong reference and comes back through
    the review queue on every scrape.
    """
    four_c = ref(["Jeskai Revelation", "Tablet of Discovery", "Inevitable Defeat"],
                 decks=14)
    four_c["requires"] = ["Inevitable Defeat"]

    jeskai_deck = {"Jeskai Revelation": 4, "Tablet of Discovery": 4, "Stock Up": 4}
    four_c_deck = dict(jeskai_deck, **{"Inevitable Defeat": 3})

    assert not refs_store.eligible(jeskai_deck, four_c)
    assert refs_store.eligible(four_c_deck, four_c)


def test_no_requires_means_no_gate():
    plain = ref(["Anything"], decks=1)
    assert refs_store.eligible({}, plain)
    assert refs_store.eligible({"Whatever": 4}, plain)


def test_requires_survives_a_merge():
    existing = {}
    gated = ref(["A"], decks=2)
    gated["requires"] = ["Key Card"]
    merged, _ = refs_store.merge(existing, {"X": gated})
    assert merged["X"]["requires"] == ["Key Card"]

    # and a richer incoming entry without the gate must not silently drop it
    merged2, _ = refs_store.merge(merged, {"X": ref(["A", "B"], decks=9)})
    assert merged2["X"]["decks"] == 9


@pytest.mark.local_data
def test_the_two_4cc_references_require_inevitable_defeat():
    """Guards the split itself: without this, Jeskai lists drift back into 4CC.

    archetype_refs.json is built from scraped decklists and .gitignore keeps it
    out of the repo, so on a fresh clone there is nothing to check. Before 2.0.0
    this test failed there instead of saying so, which made CI impossible.
    """
    import os

    from mtg_data.core.paths import ROOT_DIR
    path = os.path.join(os.environ.get("MTG_DATA_DIR") or ROOT_DIR, "archetype_refs.json")
    if not os.path.exists(path):
        pytest.skip("no local archetype_refs.json (scraped data, not in the repo)")
    refs = refs_store.load(path)
    for label in ("Four-Color Control (Jeskai Base)", "Four-Color Control (Black Base)"):
        assert label in refs, f"{label} missing from archetype_refs.json"
        assert refs[label].get("requires") == ["Inevitable Defeat"], label
