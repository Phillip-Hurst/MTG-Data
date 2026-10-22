"""
Regression tests for the 2026-09-08 combined-CSV shrink.

What went wrong: three scripts wrote melee_<fmt>_all_*.csv with three different
definitions of the pool.

  melee_scraper.rebuild_all_csv          per-event glob, deduped, no verdicts
  validate_events.rewrite_combined       read the combined file, filtered it,
                                         wrote it back over itself
  winrate_analysis.rebuild_all_pairings  per-event glob, no dedupe, no verdicts

The in-place filter was the damaging one. Each run filtered an already-filtered
file, so rows could leave and never come back: melee_standard_all_standings.csv
went 553 rows in August to 312 to 241 while 27 per-event files sat on disk, and
build_baseline.py reads only that file. The .raw.csv backup was written under
`if not os.path.isfile(raw)`, so it froze on the first run.

These tests pin the fix: the combined CSVs are derived from the per-event files
every time, with the verdicts applied, and nothing filters them in place.
"""
import csv
import json
import os
import sys

import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from mtg_data.quality import combine_events as ce


# ── fixtures ──────────────────────────────────────────────────────────────────

def pairing(tid, p1, p2, winner, d1="Placeholder A", d2="Placeholder B", rnd="1",
            table="1"):
    return {
        "tournament_id": tid, "tournament_name": f"Event {tid}",
        "round": rnd, "table_num": table,
        "player1": p1, "player1_deck": d1, "player1_deck_url": "",
        "player2": p2, "player2_deck": d2, "player2_deck_url": "",
        "result": f"{winner} won 2-0-0", "winner": winner,
    }


def write_event(tmp_path, tid, rows, kind="pairings", quarantined=False):
    suffix = ".quarantined.csv" if quarantined else ".csv"
    path = tmp_path / f"melee_standard_{tid}_{kind}{suffix}"
    fields = ce.FIELDS[kind]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def write_combined(tmp_path, rows, kind="pairings"):
    path = tmp_path / f"melee_standard_all_{kind}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ce.FIELDS[kind], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── the shrink ────────────────────────────────────────────────────────────────

def test_rebuild_reads_the_per_event_files_not_the_previous_output(tmp_path):
    """
    The bug: the combined file was the input to its own filter, so a run could
    only ever remove rows. Here it holds one row while the per-event files hold
    five, and the rebuild has to produce five.
    """
    rows = [pairing("111", f"p{i}", f"q{i}", f"p{i}", table=str(i)) for i in range(5)]
    write_event(tmp_path, "111", rows)
    write_combined(tmp_path, rows[:1])

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)

    assert s["rows"] == 5, "the rebuild must come from the per-event files"
    assert s["previous_rows"] == 1
    assert len(read_rows(tmp_path / "melee_standard_all_pairings.csv")) == 5


def test_a_second_run_produces_an_identical_file(tmp_path):
    """Guardrail 4. A rebuild that reads its own output drifts; this one can't."""
    write_event(tmp_path, "111",
                [pairing("111", f"p{i}", f"q{i}", f"p{i}", table=str(i))
                 for i in range(4)])

    ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)
    first = (tmp_path / "melee_standard_all_pairings.csv").read_bytes()
    ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)
    second = (tmp_path / "melee_standard_all_pairings.csv").read_bytes()

    assert first == second, "the rebuild must be idempotent, byte for byte"


def test_an_unchanged_rebuild_does_not_touch_the_file(tmp_path):
    """
    build_baseline.py refuses to publish a snapshot when the standings file is
    newer than the last validation. A no-op write that bumped mtime would trip
    that guard on every run of anything, so idempotent has to mean the file too.
    """
    import os
    import time

    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    path = tmp_path / "melee_standard_all_pairings.csv"

    ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)
    first_mtime = os.path.getmtime(path)
    time.sleep(1.1)
    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)

    assert s["unchanged"] is True
    assert os.path.getmtime(path) == first_mtime
    assert not (tmp_path / "melee_standard_all_pairings.pre-rebuild.csv").exists(), \
        "an unchanged run has nothing to back up"


def test_a_changed_rebuild_does_touch_the_file(tmp_path):
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)

    write_event(tmp_path, "222", [pairing("222", "c", "d", "c")])
    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)

    assert s["unchanged"] is False
    assert s["rows"] == 2


def test_the_previous_file_is_backed_up_on_every_run(tmp_path):
    """
    The old backup sat behind `if not os.path.isfile(raw)`, so it captured the
    first run and nothing after it. By 2026-09-08 the live .raw.csv was 11 days
    stale and held a different pool from either live file.
    """
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)

    backup = tmp_path / "melee_standard_all_pairings.pre-rebuild.csv"
    write_event(tmp_path, "222", [pairing("222", "c", "d", "c")])
    ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)

    assert backup.exists()
    assert len(read_rows(backup)) == 1, \
        "the backup must hold the run before this one, not the very first run"
    assert len(read_rows(tmp_path / "melee_standard_all_pairings.csv")) == 2


# ── verdicts ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("verdict", ["off-format", "pre-era", "variant"])
def test_a_quarantined_event_stays_out(tmp_path, verdict):
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    write_event(tmp_path, "999", [pairing("999", "c", "d", "c")])
    verdicts = {"999": {"tournament_id": "999", "verdict": verdict}}

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts=verdicts, quiet=True)

    assert s["rows"] == 1
    assert s["dropped_by_verdict"] == {"999": verdict}
    assert s["rows_dropped_by_verdict"] == 1, \
        "a filter that can't say how many rows it removed can't be checked"


@pytest.mark.parametrize("verdict", ["ok", "unverified", "seat"])
def test_a_kept_verdict_keeps_the_event(tmp_path, verdict):
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    verdicts = {"111": {"tournament_id": "111", "verdict": verdict,
                        "keep_players": ["a", "b"]}}
    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts=verdicts, quiet=True)
    assert s["rows"] == 1


def test_the_seat_filter_drops_a_cross_format_pairing(tmp_path):
    """
    A Standard player paired against a Modern player inside a team event never
    happened as a Standard match. winrate_analysis and matchup_matrix used to
    glob past this filter entirely.
    """
    write_event(tmp_path, "999", [
        pairing("999", "std0", "std1", "std0", table="1"),
        pairing("999", "std0", "mod0", "std0", table="2"),
    ])
    verdicts = {"999": {"tournament_id": "999", "verdict": "seat",
                        "keep_players": ["std0", "std1"]}}

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts=verdicts, quiet=True)

    assert s["rows"] == 1
    assert s["rows_seat_trimmed"] == 1
    kept = read_rows(tmp_path / "melee_standard_all_pairings.csv")
    assert all(r["player2"] != "mod0" for r in kept)


def test_a_scrape_cannot_reinstate_a_quarantined_event(tmp_path):
    """
    melee_scraper used to rebuild with no verdict filter, so the next scrape
    put a quarantined event straight back into the pool the validator had just
    removed it from. rebuild() with verdicts=None loads the quarantine rather
    than defaulting to "no verdicts".
    """
    write_event(tmp_path, "999", [pairing("999", "c", "d", "c")])
    with open(tmp_path / "event_quarantine_standard.json", "w", encoding="utf-8") as f:
        json.dump({"events": [{"tournament_id": "999", "verdict": "off-format"}]}, f)

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", quiet=True)

    assert s["rows"] == 0
    assert s["dropped_by_verdict"] == {"999": "off-format"}


def test_an_event_with_no_verdict_is_kept_and_counted(tmp_path):
    """Guardrail 1. Unjudged is a state worth reporting, not a silent pass."""
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)
    assert s["rows"] == 1
    assert s["unjudged_events"] == ["111"]


def test_a_reversed_verdict_puts_the_live_file_back_in(tmp_path):
    """
    Quarantining renames the per-event file rather than deleting it, so both
    copies can exist after a verdict reverses. The live one is the current one.
    """
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a", table="1")],
                quarantined=True)
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a", table="1"),
                                  pairing("111", "c", "d", "c", table="2")])

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)
    assert s["rows"] == 2, "the live file wins over the quarantined copy"


# ── unreadable files ──────────────────────────────────────────────────────────

def _make_unreadable(tmp_path, tid, kind="pairings"):
    """A directory where a CSV should be. Opening it raises OSError."""
    os.mkdir(tmp_path / f"melee_standard_{tid}_{kind}.csv")


def test_an_unreadable_file_refuses_the_write(tmp_path):
    """
    Guardrail 2, with teeth. A warning printed above a written file still
    leaves the smaller file written, and every consumer then reads it. On
    OneDrive a cloud-only placeholder raises OSError, so an unhydrated folder
    would trim real events out of the pool on the next run of anything.
    """
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    original = write_combined(tmp_path, [pairing("111", "a", "b", "a"),
                                         pairing("222", "c", "d", "c")])
    before = original.read_bytes()
    _make_unreadable(tmp_path, "222")

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)

    assert s["refused"] is True
    assert len(s["unreadable_files"]) == 1
    assert original.read_bytes() == before, \
        "a refused rebuild must leave the existing pool exactly as it was"


def test_allow_partial_writes_anyway(tmp_path):
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    write_combined(tmp_path, [])
    _make_unreadable(tmp_path, "222")

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={},
                   quiet=True, allow_partial=True)

    assert s["refused"] is False
    assert s["rows"] == 1


def test_an_unreadable_file_in_a_dropped_event_still_refuses(tmp_path):
    """
    The file can't be read, so its verdict can't be checked against what's in
    it. Guessing that an unreadable file was the one we meant to drop is the
    kind of assumption this module exists to stop making.
    """
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    _make_unreadable(tmp_path, "999")
    verdicts = {"999": {"tournament_id": "999", "verdict": "off-format"}}

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts=verdicts, quiet=True)
    assert s["refused"] is True


# ── coverage sidecar ──────────────────────────────────────────────────────────

def test_coverage_sidecar_describes_the_pool(tmp_path):
    """
    A CSV can't carry a note about what's missing from it, and "how many events
    is this built on" is the question every published snapshot has to answer.
    """
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    write_event(tmp_path, "111", [{"tournament_id": "111", "tournament_name": "E",
                                   "round": "1", "rank": "1", "player": "a",
                                   "deck_name": "Placeholder A", "deck_url": "",
                                   "match_record": "1-0-0", "game_record": "2-0",
                                   "points": "3", "omw_pct": "", "tgw_pct": "",
                                   "ogw_pct": ""}], kind="standings")
    write_event(tmp_path, "999", [pairing("999", "c", "d", "c")])
    verdicts = {"999": {"tournament_id": "999", "verdict": "off-format"}}

    out = ce.rebuild_all(str(tmp_path), "Standard", verdicts=verdicts, quiet=True)

    assert out["coverage"], "a successful rebuild writes the sidecar"
    with open(out["coverage"], encoding="utf-8") as f:
        cov = json.load(f)
    assert cov["pairings"]["events_kept"] == 1
    assert cov["pairings"]["dropped_by_verdict"] == {"999": "off-format"}
    assert cov["pairings"]["unjudged_events"] == ["111"]


def test_no_sidecar_is_written_when_the_rebuild_was_refused(tmp_path):
    """A sidecar after a refusal would describe a pool that was never written."""
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    _make_unreadable(tmp_path, "222")

    out = ce.rebuild_all(str(tmp_path), "Standard", verdicts={}, quiet=True)

    assert out["coverage"] is None
    assert not (tmp_path / "melee_standard_all_coverage.json").exists()


# ── the loader every consumer uses ────────────────────────────────────────────

def test_load_pool_applies_the_seat_filter(tmp_path):
    """
    The point of routing every consumer through one loader. Globbing the
    per-event files skips this, which is how a cross-format pairing reached the
    win-rate math after the validator had ruled on it.
    """
    write_event(tmp_path, "999", [
        pairing("999", "std0", "std1", "std0", table="1"),
        pairing("999", "std0", "mod0", "std0", table="2"),
    ])
    with open(tmp_path / "event_quarantine_standard.json", "w", encoding="utf-8") as f:
        json.dump({"events": [{"tournament_id": "999", "verdict": "seat",
                               "keep_players": ["std0", "std1"]}]}, f)

    rows, summary = ce.load_pool(str(tmp_path), "Standard", "pairings")

    assert len(rows) == 1
    assert summary["rows_seat_trimmed"] == 1


def test_dedupe_survives_a_rescrape(tmp_path):
    """A tournament scraped twice must not double its rows."""
    row = pairing("111", "a", "b", "a")
    write_event(tmp_path, "111", [row, dict(row)])
    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)
    assert s["rows"] == 1


def test_another_formats_files_are_never_folded_in(tmp_path):
    write_event(tmp_path, "111", [pairing("111", "a", "b", "a")])
    modern = tmp_path / "melee_modern_222_pairings.csv"
    with open(modern, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ce.FIELDS["pairings"], extrasaction="ignore")
        w.writeheader()
        w.writerow(pairing("222", "c", "d", "c"))

    s = ce.rebuild(str(tmp_path), "Standard", "pairings", verdicts={}, quiet=True)
    assert s["rows"] == 1
