"""The source caches get the era applied too, not just the CSVs.

Every one of these tests is a defect that was live on 2026-08-30, three weeks
after the era mechanism supposedly shipped:

  - mtgo_classifications.json held classifications dated 2026-06-03, two months
    before the era opened.
  - mtgo_challenge_latest.json and mtgo_5-0_latest.json held events dated
    2026-08-08 and 08-09; the era opens 08-10.
  - melee_deck_cache.json held 71 decks running Badgermole Cub, 41 running
    Stormchaser's Talent, 33 running Gran-Gran.

Everything exited 0 the whole time, which is the reason these are tests and not
a note.
"""

import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validate_events as ve   # noqa: E402


CUTOFF = dt.datetime(2026, 8, 10)
POOL = {"lightning bolt", "island", "mountain", "opt"}
BANNED = {"badgermole cub"}


def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


# ── date-based cleaning ───────────────────────────────────────────────────────

def test_mapping_cache_drops_entries_dated_before_the_window(tmp_path):
    path = _write(tmp_path, "mtgo_classifications.json", {
        "pre":  {"archetype": "Izzet Prowess", "date": "2026-06-03"},
        "edge": {"archetype": "Dimir Midrange", "date": "2026-08-09"},
        "open": {"archetype": "Dimir Midrange", "date": "2026-08-10"},
        "post": {"archetype": "Mono Green Landfall", "date": "2026-08-27"},
    })
    rec = ve.clean_date_cache(path, "mapping", CUTOFF, data_dir=str(tmp_path))
    assert rec["before"] == 4 and rec["after"] == 2 and rec["removed"] == 2
    kept = json.loads(open(path, encoding="utf-8").read())
    assert set(kept) == {"open", "post"}, "the window start itself is in the era"


def test_list_cache_drops_events_dated_before_the_window(tmp_path):
    path = _write(tmp_path, "mtgo_challenge_latest.json", [
        {"name": "Challenge 32", "date": "2026-08-08", "decks": [1, 2]},
        {"name": "Challenge 64", "date": "2026-08-16", "decks": [3]},
    ])
    rec = ve.clean_date_cache(path, "list", CUTOFF, data_dir=str(tmp_path))
    assert rec["removed"] == 1
    assert [e["name"] for e in json.loads(open(path, encoding="utf-8").read())] \
        == ["Challenge 64"]


def test_an_undated_entry_is_kept_not_guessed_at(tmp_path):
    """Fail open here on purpose: dropping a record because a field is missing
    loses data silently. The event validator is what catches undated events."""
    path = _write(tmp_path, "mtgo_classifications.json", {
        "nodate": {"archetype": "Jeskai Control"},
        "old": {"archetype": "Izzet Prowess", "date": "2026-06-03"},
    })
    rec = ve.clean_date_cache(path, "mapping", CUTOFF, data_dir=str(tmp_path))
    assert rec["removed"] == 1
    assert set(json.loads(open(path, encoding="utf-8").read())) == {"nodate"}


def test_date_cleaning_is_idempotent(tmp_path):
    path = _write(tmp_path, "mtgo_5-0_latest.json", [
        {"name": "League", "date": "2026-08-09", "decks": []},
        {"name": "League", "date": "2026-08-23", "decks": []},
    ])
    first = ve.clean_date_cache(path, "list", CUTOFF, data_dir=str(tmp_path))
    second = ve.clean_date_cache(path, "list", CUTOFF, data_dir=str(tmp_path))
    assert first["removed"] == 1
    assert second["removed"] == 0, "a second run must be a no-op"


# ── the publication-date trap ─────────────────────────────────────────────────
#
# An MTGO dump is stamped with the date it was published, not the date the games
# were played. The real 2026-08-10 Standard League dump is stamped on the ban
# date and three of its six lists run Badgermole Cub. A date-only filter admits
# it, because 08-10 is "in the era".

def test_an_in_era_event_full_of_banned_cards_is_still_pre_era(tmp_path):
    path = _write(tmp_path, "mtgo_5-0_latest.json", [
        {"name": "Standard League", "date": "2026-08-10", "decks": [
            {"player": "WOLF2222", "mainboard": {"Badgermole Cub": 4}},
            {"player": "BLASPHEMOUSACT", "mainboard": {"Badgermole Cub": 4}},
            {"player": "CLEAN", "mainboard": {"Opt": 4}},
        ]},
        {"name": "Standard League", "date": "2026-08-23", "decks": [
            {"player": "LATER", "mainboard": {"Opt": 4}},
        ]},
    ])
    rec = ve.clean_date_cache(path, "list", CUTOFF, data_dir=str(tmp_path),
                              banned=BANNED)
    assert rec["removed"] == 1
    assert rec["removed_by_banned_cards"] == 1
    assert rec["removed_by_date"] == 0
    kept = json.loads(open(path, encoding="utf-8").read())
    assert [e["date"] for e in kept] == ["2026-08-23"]


def test_a_clean_in_era_event_survives(tmp_path):
    path = _write(tmp_path, "mtgo_challenge_latest.json", [
        {"name": "Challenge 32", "date": "2026-08-16", "decks": [
            {"player": "A", "mainboard": {"Opt": 4}},
            {"player": "B", "mainboard": {"Lightning Bolt": 4}},
        ]},
    ])
    rec = ve.clean_date_cache(path, "list", CUTOFF, data_dir=str(tmp_path),
                              banned=BANNED)
    assert rec["removed"] == 0


def test_new_cards_is_deck_evidence_and_cuts_is_not(tmp_path):
    """`cuts` names cards the *reference* runs and the deck doesn't. Reading it
    as deck evidence would have deleted 23 good post-ban Jeskai Lessons rows."""
    path = _write(tmp_path, "mtgo_classifications.json", {
        "deck_ran_it": {"archetype": "Mono Green Landfall", "date": "2026-08-10",
                        "new_cards": [{"card": "Badgermole Cub", "count": 4}]},
        "stale_ref": {"archetype": "Jeskai Lessons", "date": "2026-08-16",
                      "cuts": [{"card": "Gran-Gran", "ref_count": 4}]},
    })
    rec = ve.clean_date_cache(path, "mapping", CUTOFF, data_dir=str(tmp_path),
                              banned=BANNED)
    assert rec["removed"] == 1 and rec["removed_by_banned_cards"] == 1
    assert set(json.loads(open(path, encoding="utf-8").read())) == {"stale_ref"}


def test_card_check_is_skipped_when_no_ban_list_is_supplied(tmp_path):
    path = _write(tmp_path, "mtgo_5-0_latest.json", [
        {"date": "2026-08-16", "decks": [{"mainboard": {"Badgermole Cub": 4}}]},
    ])
    rec = ve.clean_date_cache(path, "list", CUTOFF, data_dir=str(tmp_path))
    assert rec["removed"] == 0, "no ban list means no card verdict"


# ── card-based cleaning ───────────────────────────────────────────────────────

def test_deck_cache_drops_decks_running_a_banned_card(tmp_path):
    path = _write(tmp_path, "melee_deck_cache.json", {
        "a": {"archetype": "Izzet Prowess",
              "mainboard": {"Badgermole Cub": 4, "Island": 20}},
        "b": {"archetype": "Dimir Midrange",
              "mainboard": {"Lightning Bolt": 4, "Island": 20}},
    })
    rec = ve.clean_deck_cache(path, POOL, BANNED, CUTOFF, data_dir=str(tmp_path))
    assert rec["banned_decks"] == 1 and rec["removed"] == 1
    assert set(json.loads(open(path, encoding="utf-8").read())) == {"b"}


def test_deck_cache_drops_off_format_decks(tmp_path):
    """The 2026-08-29 rebuild produced 6 Modern references off this cache."""
    path = _write(tmp_path, "melee_deck_cache.json", {
        "modern": {"archetype": "Boros Energy",
                   "mainboard": {"Ragavan, Nimble Pilferer": 4,
                                 "Guide of Souls": 4, "Ocelot Pride": 4}},
        "std": {"archetype": "Dimir Midrange",
                "mainboard": {"Lightning Bolt": 4, "Opt": 4}},
    })
    rec = ve.clean_deck_cache(path, POOL, BANNED, CUTOFF, data_dir=str(tmp_path))
    assert rec["off_format_decks"] == 1
    assert set(json.loads(open(path, encoding="utf-8").read())) == {"std"}


def test_deck_cache_keeps_entries_it_cannot_judge(tmp_path):
    path = _write(tmp_path, "melee_deck_cache.json", {
        "failed": {"archetype": None, "failed": True, "mainboard": {}},
        "empty": {"archetype": "Unknown", "mainboard": {}},
    })
    rec = ve.clean_deck_cache(path, POOL, BANNED, CUTOFF, data_dir=str(tmp_path))
    assert rec["removed"] == 0, "never drop a deck blind"


def test_deck_cache_skips_when_it_has_nothing_to_judge_against(tmp_path):
    """No card pool and no ban list means no basis for a verdict. Say so and
    change nothing, rather than emptying the cache."""
    path = _write(tmp_path, "melee_deck_cache.json", {
        "a": {"mainboard": {"Badgermole Cub": 4}}})
    rec = ve.clean_deck_cache(path, None, set(), CUTOFF, data_dir=str(tmp_path))
    assert rec["removed"] == 0 and "skipped" in rec["test"]
    assert set(json.loads(open(path, encoding="utf-8").read())) == {"a"}


# ── safety ────────────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path):
    payload = {"a": {"archetype": "X", "date": "2026-06-03"}}
    path = _write(tmp_path, "mtgo_classifications.json", payload)
    rec = ve.clean_date_cache(path, "mapping", CUTOFF, dry_run=True,
                              data_dir=str(tmp_path))
    assert rec["removed"] == 1, "it still reports what it would do"
    assert json.loads(open(path, encoding="utf-8").read()) == payload
    assert not os.path.exists(path + ".bak")
    assert not os.path.isdir(os.path.join(str(tmp_path), "archive"))


def test_removed_entries_are_archived_not_deleted(tmp_path):
    path = _write(tmp_path, "mtgo_classifications.json", {
        "old": {"archetype": "Izzet Prowess", "date": "2026-06-03"},
        "new": {"archetype": "Dimir Midrange", "date": "2026-08-20"},
    })
    ve.clean_date_cache(path, "mapping", CUTOFF, data_dir=str(tmp_path))
    dest = os.path.join(str(tmp_path), "archive", "through-2026-08-10",
                        "mtgo_classifications.pre-era.json")
    assert os.path.isfile(dest), "pre-era data must stay readable"
    assert set(json.loads(open(dest, encoding="utf-8").read())) == {"old"}


def test_the_original_is_backed_up_once(tmp_path):
    path = _write(tmp_path, "mtgo_classifications.json", {
        "old": {"archetype": "X", "date": "2026-06-03"},
        "new": {"archetype": "Y", "date": "2026-08-20"},
    })
    ve.clean_date_cache(path, "mapping", CUTOFF, data_dir=str(tmp_path))
    bak = path + ".bak"
    assert os.path.isfile(bak)
    assert set(json.loads(open(bak, encoding="utf-8").read())) == {"old", "new"}
    first = open(bak, encoding="utf-8").read()
    ve.clean_date_cache(path, "mapping", CUTOFF, data_dir=str(tmp_path))
    assert open(bak, encoding="utf-8").read() == first, \
        "a second run must not overwrite the backup with already-cleaned data"


def test_unreadable_cache_is_reported_not_swallowed(tmp_path):
    p = tmp_path / "mtgo_classifications.json"
    p.write_text("{ this is not json", encoding="utf-8")
    before = len(ve.UNREADABLE)
    rec = ve.clean_date_cache(str(p), "mapping", CUTOFF, data_dir=str(tmp_path))
    assert rec is None
    assert len(ve.UNREADABLE) == before + 1


def test_no_cutoff_means_no_date_cleaning(tmp_path):
    """Without a resolved era there is no window, so there is no verdict."""
    payload = {"a": {"archetype": "X", "date": "2020-01-01"}}
    path = _write(tmp_path, "mtgo_classifications.json", payload)
    assert ve.clean_date_cache(path, "mapping", None, data_dir=str(tmp_path)) is None
    assert json.loads(open(path, encoding="utf-8").read()) == payload


# ── the orchestrator ──────────────────────────────────────────────────────────

def test_clean_source_caches_covers_every_file_a_consumer_reads(tmp_path):
    """The bug was scope, not logic. If a file drops off this list, an analysis
    silently reads pre-era data again."""
    _write(tmp_path, "mtgo_classifications.json",
           {"a": {"date": "2026-06-03"}, "b": {"date": "2026-08-20"}})
    _write(tmp_path, "mtgo_challenge_latest.json",
           [{"date": "2026-08-08"}, {"date": "2026-08-20"}])
    _write(tmp_path, "mtgo_5-0_latest.json",
           [{"date": "2026-08-09"}, {"date": "2026-08-23"}])
    _write(tmp_path, "melee_deck_cache.json",
           {"x": {"mainboard": {"Badgermole Cub": 4}},
            "y": {"mainboard": {"Opt": 4}}})

    results = ve.clean_source_caches(str(tmp_path), "Standard", CUTOFF,
                                     POOL, BANNED)
    touched = {r["file"] for r in results}
    assert touched == {"mtgo_classifications.json", "mtgo_challenge_latest.json",
                       "mtgo_5-0_latest.json", "melee_deck_cache.json"}
    assert sum(r["removed"] for r in results) == 4


def test_every_date_cache_declares_its_shape():
    """A file added to CACHE_DATE_FILES with the wrong shape is a silent no-op."""
    assert set(ve.CACHE_DATE_FILES.values()) <= {"mapping", "list"}
    for name in ve.CACHE_DATE_FILES:
        assert name.endswith(".json")


@pytest.mark.parametrize("name", ["mtgo_classifications.json",
                                  "mtgo_challenge_latest.json",
                                  "mtgo_5-0_latest.json"])
def test_the_known_dirty_files_are_all_covered(name):
    assert name in ve.CACHE_DATE_FILES
