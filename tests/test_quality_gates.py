"""
Gates the 2.0.0 audit found with no test behind them.

Each of these was documented, in a docstring or the README, as something the
pipeline does. None had a test, so nothing would notice if it stopped. One of
them (the unreadable-file exit code) had already stopped: the flag recording it
was set and never read.
"""
import csv
import json
import os
import time
from collections import Counter

import pytest

from mtg_data.analyze import build_baseline
from mtg_data.classify import cluster_shells
from mtg_data.quality import validate_events as ve

FIELDS = ["tournament_id", "tournament_name", "round", "table_num",
          "player1", "player1_deck", "player1_deck_url",
          "player2", "player2_deck", "player2_deck_url", "result", "winner"]


# ── variant formats ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["Friday Night Artisan", "Pauper Showdown",
                                  "Standard Brawl League", "Prerelease Sealed"])
def test_a_variant_event_is_quarantined_even_when_every_card_is_legal(name):
    """Artisan uses Standard's card pool, so every card test passes. The
    metagame is a different one, and its results don't belong in Standard's."""
    rec = ve.validate_event("1", name, [], {}, pool=None, banned=set())
    assert rec["verdict"] == "variant"


def test_a_plain_standard_event_is_not_mistaken_for_a_variant():
    rec = ve.validate_event("1", "Standard RCQ - Toronto", [], {}, pool=None, banned=set())
    assert rec["verdict"] != "variant"


# ── unreadable input is not a clean pool ─────────────────────────────────────

def _one_event(data_dir):
    path = data_dir / "melee_standard_900001_pairings.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow({"tournament_id": "900001", "tournament_name": "Standard RCQ",
                    "round": "1", "table_num": "1", "player1": "A", "player1_deck": "X",
                    "player1_deck_url": "", "player2": "B", "player2_deck": "Y",
                    "player2_deck_url": "", "result": "A won 2-0-0", "winner": "A"})


def _run_validator(monkeypatch, data_dir, unreadable):
    monkeypatch.setenv("MTG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MTG_OUTPUT_DIR", str(data_dir))
    monkeypatch.setattr(ve, "UNREADABLE", list(unreadable))
    monkeypatch.setattr("sys.argv", ["mtg validate-events", "--dry-run", "--format", "Standard"])
    return ve.main()


def test_a_clean_pool_passes(tmp_path, monkeypatch):
    _one_event(tmp_path)
    assert _run_validator(monkeypatch, tmp_path, []) == 0


def test_an_unreadable_file_means_the_pool_was_not_judged(tmp_path, monkeypatch, capsys):
    """Until 2.0.0 this printed "All events passed" and exited 0, and
    fetch-melee carried the pool forward as clean."""
    _one_event(tmp_path)
    rc = _run_validator(monkeypatch, tmp_path, [("melee_standard_900002_pairings.csv", "OSError")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "All events passed" not in out
    assert "Not all events were judged" in out


# ── no snapshot from an unvalidated pool ─────────────────────────────────────

ERA = {"start_str": "2026-09-29"}


@pytest.fixture
def baseline_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(build_baseline, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(build_baseline, "STANDINGS",
                        str(tmp_path / "melee_standard_all_standings.csv"))
    monkeypatch.setattr(build_baseline, "_FMT_SLUG", "standard")
    return tmp_path


def _report(d, window_start, validated):
    (d / "event_quarantine_standard.json").write_text(
        json.dumps({"window_start": window_start, "validated": validated}), encoding="utf-8")


def test_a_snapshot_is_refused_when_the_pool_was_never_validated(baseline_dir):
    assert "never been validated" in build_baseline.validation_status(ERA)


def test_a_snapshot_is_refused_for_a_pool_validated_under_another_era(baseline_dir):
    _report(baseline_dir, "2026-08-10", "2026-10-12T17:12:02")
    reason = build_baseline.validation_status(ERA)
    assert "2026-08-10" in reason and "2026-09-29" in reason


def test_a_snapshot_is_refused_after_a_rescrape(baseline_dir):
    _report(baseline_dir, "2026-09-29", "2026-10-01T00:00:00")
    standings = baseline_dir / "melee_standard_all_standings.csv"
    standings.write_text("x\n", encoding="utf-8")
    later = time.mktime((2026, 10, 2, 0, 0, 0, 0, 0, -1))
    os.utime(standings, (later, later))
    assert "rescraped" in build_baseline.validation_status(ERA)


def test_a_current_validated_pool_may_be_snapshotted(baseline_dir):
    standings = baseline_dir / "melee_standard_all_standings.csv"
    standings.write_text("x\n", encoding="utf-8")
    earlier = time.mktime((2026, 10, 1, 0, 0, 0, 0, 0, -1))
    os.utime(standings, (earlier, earlier))
    _report(baseline_dir, "2026-09-29", "2026-10-02T00:00:00")
    assert build_baseline.validation_status(ERA) is None


# ── same data, same output ───────────────────────────────────────────────────

def test_a_shells_core_cards_break_ties_on_the_name():
    """Ties used to break on set iteration order, so one shell printed a
    different Core line on every run of the same data."""
    deck = {c: 4 for c in ["Zebra Card", "Apple Card", "Mango Card", "Kiwi Card"]}
    shell = cluster_shells.Shell("a", deck)
    shell.add("b", dict(deck))
    top = shell.top_cards(10)
    counts = Counter()
    for _, m in shell.members:
        counts.update(cluster_shells.deck_core(m))
    expected = [c for c, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:10]
    assert top == expected
    assert top == sorted(top), "every card ties here, so the order is alphabetical"
