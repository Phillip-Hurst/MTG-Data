"""
Regression tests for the 2026-08-27 contamination bug.

What went wrong: mtg_fetch.py printed "Window start: 2026-08-10 — post-ban",
then admitted Sydney Standard Spectacular 100K (pre-ban) and NRG Series $10k
Team Trios (Modern) into the Standard pool. Two causes:

  1. every date filter in _extract_from_api sat behind `if date_val`, so a row
     melee returned with no date skipped the window check entirely
  2. the format filter accepted any value containing "magic", and melee's
     GameDescription is "MagicTheGathering" on every event of every format

These tests pin both fixes, plus the validator that catches whatever still
gets through.
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta

import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

# mtg_fetch imports playwright at module scope; the extraction helpers under
# test don't touch a browser, so stub it rather than requiring the install.
if "playwright" not in sys.modules:
    pw = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: None
    sync_api.TimeoutError = type("TimeoutError", (Exception,), {})
    pw.sync_api = sync_api
    sys.modules["playwright"] = pw
    sys.modules["playwright.sync_api"] = sync_api

import mtg_fetch  # noqa: E402
import mtg_era  # noqa: E402
import validate_events as ve  # noqa: E402


def api_rows(rows):
    return [{"url": "https://melee.gg/api/list", "data": {"data": rows}}]


def run_api(rows, cutoff, target_fmt="Standard"):
    found, seen, undated = [], set(), []
    found, seen = mtg_fetch._extract_from_api(
        api_rows(rows), None, cutoff, found, seen,
        target_fmt=target_fmt, undated=undated,
    )
    return [t for t, _, __ in found], undated


# ── the date bug ──────────────────────────────────────────────────────────────

def test_undated_event_is_skipped_not_admitted():
    """The exact 2026-08-27 shape: melee returns a row with no date field."""
    cutoff = datetime(2026, 8, 10)
    ids, undated = run_api(
        [{"ID": "439208", "Name": "Sydney Standard Spectacular 100K",
          "Format": "Standard", "Status": "Ended", "Players": 136}],
        cutoff,
    )
    assert ids == [], "an event with no date must not enter the pool"
    assert [t for t, _ in undated] == ["439208"], "and it must be reported, not silently dropped"


def test_empty_string_date_is_treated_as_undated():
    cutoff = datetime(2026, 8, 10)
    ids, undated = run_api(
        [{"ID": "1", "Name": "No date", "Format": "Standard",
          "Status": "Ended", "StartDate": "", "Players": 40}],
        cutoff,
    )
    assert ids == []
    assert len(undated) == 1


def test_unparseable_date_is_treated_as_undated():
    cutoff = datetime(2026, 8, 10)
    ids, undated = run_api(
        [{"ID": "2", "Name": "Garbage date", "Format": "Standard",
          "Status": "Ended", "StartDate": "not a date", "Players": 40}],
        cutoff,
    )
    assert ids == []
    assert len(undated) == 1


def test_event_before_window_start_is_dropped():
    cutoff = datetime(2026, 8, 10)
    ids, _ = run_api(
        [{"ID": "3", "Name": "Pre-ban RCQ", "Format": "Standard",
          "Status": "Ended", "StartDate": "2026-08-02", "Players": 40}],
        cutoff,
    )
    assert ids == []


def test_event_inside_window_is_kept():
    cutoff = datetime(2026, 8, 10)
    ids, undated = run_api(
        [{"ID": "4", "Name": "Post-ban RCQ", "Format": "Standard",
          "Status": "Ended", "StartDate": "2026-08-22", "Players": 40}],
        cutoff,
    )
    assert ids == ["4"]
    assert undated == []


def test_future_event_is_dropped():
    cutoff = datetime(2026, 8, 10)
    later = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    ids, _ = run_api(
        [{"ID": "5", "Name": "Not played yet", "Format": "Standard",
          "Status": "Ended", "StartDate": later, "Players": 40}],
        cutoff,
    )
    assert ids == []


# ── the format bug ────────────────────────────────────────────────────────────

def test_game_description_no_longer_passes_every_format():
    """
    GameDescription is "MagicTheGathering" on every MTG event. Reading it as a
    format filter is how a Modern team trios event reached the Standard pool.
    """
    cutoff = datetime(2026, 8, 10)
    ids, _ = run_api(
        [{"ID": "437430", "Name": "NRG Series: Magic $10k Team Trios Showdown",
          "GameDescription": "MagicTheGathering", "Format": "Modern",
          "Status": "Ended", "StartDate": "2026-08-16", "Players": 66}],
        cutoff,
    )
    assert ids == [], "a Modern event must not enter the Standard pool"


def test_matching_format_is_kept():
    cutoff = datetime(2026, 8, 10)
    ids, _ = run_api(
        [{"ID": "6", "Name": "Standard RCQ", "GameDescription": "MagicTheGathering",
          "Format": "Standard", "Status": "Ended", "StartDate": "2026-08-22", "Players": 40}],
        cutoff,
    )
    assert ids == ["6"]


def test_missing_format_field_is_allowed_through_to_the_validator():
    """melee doesn't always populate Format. Card-level validation catches those."""
    cutoff = datetime(2026, 8, 10)
    ids, _ = run_api(
        [{"ID": "7", "Name": "Unlabelled", "Status": "Ended",
          "StartDate": "2026-08-22", "Players": 40}],
        cutoff,
    )
    assert ids == ["7"]


# ── era anchors ───────────────────────────────────────────────────────────────

def test_ban_and_set_release_within_a_fortnight_merge_to_the_earlier_date():
    """
    The Hobbit released 2026-08-14, four days after the 2026-08-10 bans.
    Anchoring on the set would throw away three days of post-ban results.
    """
    era = mtg_era.resolve_era(fmt="Standard")
    assert era["start_str"] == "2026-08-10"
    assert era["anchor"] == "ban+set-release"
    assert "Hobbit" in era["label"]


def test_the_hobbit_is_on_file():
    names = {s["name"] for s in mtg_era.load_sets()}
    assert "The Hobbit" in names, "set_releases.json must carry every Standard-legal set"


# ── the validator ─────────────────────────────────────────────────────────────

STANDARD_POOL = {"llanowar elves", "icetill explorer", "mightform harmonizer",
                 "sazh's chocobo", "forest", "island", "swamp",
                 "enduring curiosity", "kaito, bane of nightmares",
                 "badgermole cub", "stormchaser's talent"}
BANNED = {"badgermole cub", "stormchaser's talent", "gran-gran"}


def deck(*cards):
    return {"mainboard": {c: 4 for c in cards}}


def pairing(p1, p2, url1, url2, winner):
    return {"tournament_id": "1", "tournament_name": "Test", "round": "1",
            "player1": p1, "player1_deck": "", "player1_deck_url": url1,
            "player2": p2, "player2_deck": "", "player2_deck_url": url2,
            "result": "", "winner": winner}


def build_event(specs, name="Test Event", individual_results=True):
    """specs: list of (player, [cards]). Returns (rows, cache)."""
    cache, rows = {}, []
    for i, (player, cards) in enumerate(specs):
        cache[f"url{i}"] = deck(*cards)
    names = [s[0] for s in specs]
    for i in range(0, len(names) - 1, 2):
        rows.append(pairing(names[i], names[i + 1], f"url{i}", f"url{i+1}",
                            names[i] if individual_results else ""))
    for r in rows:
        r["tournament_name"] = name
    return rows, cache


def test_clean_standard_event_passes():
    rows, cache = build_event([(f"p{i}", ["llanowar elves", "icetill explorer", "forest"])
                               for i in range(10)])
    rec = ve.validate_event("1", "Standard RCQ", rows, cache, STANDARD_POOL, BANNED)
    assert rec["verdict"] == "ok"


def test_pre_ban_event_is_quarantined():
    """Sydney's shape: legal cards, but a third of the field runs a banned one."""
    specs = [(f"p{i}", ["llanowar elves", "forest", "badgermole cub"]) for i in range(4)]
    specs += [(f"q{i}", ["llanowar elves", "icetill explorer", "forest"]) for i in range(6)]
    rows, cache = build_event(specs)
    rec = ve.validate_event("439208", "Sydney Standard Spectacular 100K",
                            rows, cache, STANDARD_POOL, BANNED)
    assert rec["verdict"] == "pre-era"
    assert rec["banned_share"] >= ve.EVENT_BANNED_THRESHOLD


def test_one_stale_list_does_not_condemn_an_event():
    """A single player on a banned card is a player error, not the wrong event."""
    specs = [("stale", ["llanowar elves", "forest", "badgermole cub"])]
    specs += [(f"q{i}", ["llanowar elves", "icetill explorer", "forest"]) for i in range(19)]
    rows, cache = build_event(specs)
    rec = ve.validate_event("1", "Standard RCQ", rows, cache, STANDARD_POOL, BANNED)
    assert rec["verdict"] == "ok"


def test_off_format_event_is_quarantined():
    rows, cache = build_event([(f"p{i}", ["goryo's vengeance", "atraxa, grand unifier",
                                          "flooded strand"]) for i in range(10)],
                              name="NRG Series: Magic $10k Team Trios Showdown")
    rec = ve.validate_event("437430", "NRG Series: Magic $10k Team Trios Showdown",
                            rows, cache, STANDARD_POOL, BANNED)
    assert rec["verdict"] == "off-format"


def test_mixed_format_team_event_salvages_the_standard_seat():
    """
    Phill's rule: if the event publishes each seat's own record, keep the
    Standard seat and drop the rest.
    """
    specs = [(f"std{i}", ["llanowar elves", "icetill explorer", "forest"]) for i in range(10)]
    specs += [(f"mod{i}", ["goryo's vengeance", "atraxa, grand unifier", "flooded strand"])
              for i in range(14)]
    rows, cache = build_event(specs, name="Team Trios", individual_results=True)
    rec = ve.validate_event("999", "Team Trios", rows, cache, STANDARD_POOL, BANNED)
    assert rec["verdict"] == "seat"
    assert len(rec["keep_players"]) == 10
    assert all(p.startswith("std") for p in rec["keep_players"])


def test_team_event_without_individual_results_is_dropped_entirely():
    """No per-seat record means no way to know which seat won. Exclude it."""
    specs = [(f"std{i}", ["llanowar elves", "icetill explorer", "forest"]) for i in range(10)]
    specs += [(f"mod{i}", ["goryo's vengeance", "atraxa, grand unifier", "flooded strand"])
              for i in range(14)]
    rows, cache = build_event(specs, name="Team Trios", individual_results=False)
    rec = ve.validate_event("999", "Team Trios", rows, cache, STANDARD_POOL, BANNED)
    assert rec["verdict"] == "off-format"
    assert "per-player results" in rec["reason"]


def test_rewrite_keeps_only_the_seat_and_drops_quarantined_events(tmp_path):
    """
    End to end on the real rewrite: a quarantined event disappears, a salvaged
    event keeps only its own seat, and a Standard player paired against a
    Modern player is dropped because that match never happened.
    """
    import csv
    rows = [
        pairing("std0", "std1", "a", "b", "std0"),      # seat event, both in seat
        pairing("std0", "mod0", "a", "c", "std0"),      # seat event, cross-format
        pairing("clean1", "clean2", "d", "e", "clean1"),
        pairing("bad1", "bad2", "f", "g", "bad1"),
    ]
    rows[0]["tournament_id"] = rows[1]["tournament_id"] = "999"
    rows[2]["tournament_id"] = "111"
    rows[3]["tournament_id"] = "437430"

    path = tmp_path / "melee_standard_all_pairings.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    verdicts = [
        {"tournament_id": "999", "verdict": "seat", "keep_players": ["std0", "std1"]},
        {"tournament_id": "111", "verdict": "ok"},
        {"tournament_id": "437430", "verdict": "off-format"},
    ]
    summary = ve.rewrite_combined(str(tmp_path), "Standard", verdicts)

    assert summary["pairings"]["before"] == 4
    assert summary["pairings"]["after"] == 2

    with open(path, encoding="utf-8") as f:
        kept = list(csv.DictReader(f))
    assert {r["tournament_id"] for r in kept} == {"999", "111"}
    assert all(r["player2"] != "mod0" for r in kept)
    assert (tmp_path / "melee_standard_all_pairings.raw.csv").exists(), \
        "the original pool must be preserved"


def test_thin_event_is_flagged_not_dropped():
    rows, cache = build_event([(f"p{i}", ["llanowar elves", "forest"]) for i in range(2)])
    rec = ve.validate_event("1", "Tiny FNM", rows, cache, STANDARD_POOL, BANNED)
    assert rec["verdict"] == "unverified"


def test_melee_demo_events_are_dropped():
    for name in ("How it works", "Melee Mobile build 40 test"):
        rows, cache = build_event([(f"p{i}", ["llanowar elves", "forest"]) for i in range(10)],
                                  name=name)
        rec = ve.validate_event("1", name, rows, cache, STANDARD_POOL, BANNED)
        assert rec["verdict"] == "off-format", name


def test_banned_as_of_respects_the_window_start():
    before = mtg_era.parse_date("2026-08-01")
    after = mtg_era.parse_date("2026-08-29")
    assert ve.banned_as_of("Standard", before) == set()
    assert "badgermole cub" in ve.banned_as_of("Standard", after)


# ── corrections reaching the matchup data ─────────────────────────────────────

def test_corrections_reach_the_columns_the_matchup_matrix_reads(tmp_path):
    """
    mtg_stats.classify_row reads player1_deck / player2_deck off the CSV row,
    not the decklist cache. A correction that only touches the cache never
    shows up in a matchup check.
    """
    import csv
    import apply_corrections as ac
    import mtg_stats

    path = tmp_path / "melee_standard_500001_pairings.csv"
    fields = ["tournament_id", "tournament_name", "round", "table_num",
              "player1", "player1_deck", "player1_deck_url",
              "player2", "player2_deck", "player2_deck_url", "result", "winner"]
    row = dict(zip(fields, ["500001", "Test RCQ", "1", "1",
                            "Alice", "Selesnya Aggro", "url-a",
                            "Bob", "Izzet", "url-b", "Alice won 2-1-0", "Alice"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(row)

    # Deliberately using canonical names with no alias entry, so this tests the
    # CSV write rather than incidentally re-testing ARCHETYPE_ALIASES.
    overrides = {"url-a": {"archetype": "Mono Green Landfall"},
                 "url-b": {"archetype": "Izzet Spellementals"}}
    files, cells = ac.apply_to_pairings(str(tmp_path), overrides)
    assert files == 1 and cells == 2

    with open(path, encoding="utf-8") as f:
        got = next(csv.DictReader(f))
    assert mtg_stats.classify_row(got) == ("Mono Green Landfall", "Izzet Spellementals", "p1")


def test_aliases_resolve_to_names_the_vault_actually_uses():
    """
    An alias pointing at a name the Archetypes folder doesn't carry splits a
    deck instead of merging it. That's how "Izzet" first got mapped to "Izzet
    Elementals", which has no note, while "Izzet Spellementals" does.
    """
    from mtg_stats import ARCHETYPE_ALIASES

    # The shipped copy first, so this holds for anyone who installs the plugin.
    # The vault folder is the fallback for a working copy that predates it.
    candidates = [
        os.path.join(SCRIPT_DIR, "skills", "mtg-tournament-analysis",
                     "reference", "archetypes"),
        os.path.join(os.path.dirname(SCRIPT_DIR), "..", "02 Projects",
                     "MTG Tournament Analysis Skill", "Archetypes"),
    ]
    arch_dir = next((d for d in candidates if os.path.isdir(d)), None)
    if arch_dir is None:
        pytest.skip("no archetype reference folder reachable from here")

    vault = {f[4:-3] for f in os.listdir(arch_dir)
             if f.startswith("[C] ") and f.endswith(".md")}
    targets = set(ARCHETYPE_ALIASES.values())
    unknown = {t for t in targets if t not in vault}
    assert not unknown, (
        f"alias target(s) with no note in Archetypes/: {sorted(unknown)}. "
        "Either add the note or point the alias at the name the vault uses.")


def test_no_alias_target_is_itself_aliased():
    """A -> B -> C means normalize() is order-dependent. Keep the table flat."""
    from mtg_stats import ARCHETYPE_ALIASES
    chained = {v for v in ARCHETYPE_ALIASES.values() if v in ARCHETYPE_ALIASES}
    assert not chained, f"alias chain via {sorted(chained)}"


def test_quarantined_event_files_leave_the_matchup_glob(tmp_path):
    """
    matchup_matrix.py globs melee_*_pairings.csv and skips _all_pairings.csv,
    so cleaning only the combined file leaves the matrix reading bad events.
    """
    import glob as _glob
    for tid in ("500001", "437430"):
        (tmp_path / f"melee_standard_{tid}_pairings.csv").write_text("tournament_id\n", encoding="utf-8")

    verdicts = [{"tournament_id": "500001", "verdict": "ok"},
                {"tournament_id": "437430", "verdict": "off-format"}]
    hidden, restored = ve.quarantine_event_files(str(tmp_path), "Standard", verdicts)

    assert hidden == ["melee_standard_437430_pairings.csv"]
    visible = [os.path.basename(p) for p in
               _glob.glob(os.path.join(str(tmp_path), "melee_*_pairings.csv"))]
    assert visible == ["melee_standard_500001_pairings.csv"]

    # And a reversed verdict brings it back.
    verdicts[1]["verdict"] = "ok"
    hidden, restored = ve.quarantine_event_files(str(tmp_path), "Standard", verdicts)
    assert restored == ["melee_standard_437430_pairings.quarantined.csv"]
    assert len(_glob.glob(os.path.join(str(tmp_path), "melee_*_pairings.csv"))) == 2


def test_resolved_notes_are_archived_and_unresolved_ones_stay(tmp_path):
    """The review folder is the to-do list, so a finished day has to leave it."""
    import apply_corrections as ac

    def note(name, entries):
        body = f"# Review {name}\n\n---\n\n"
        for player, url, decision in entries:
            body += (f"### {player} — Test RCQ\nURL: {url}\n"
                     f"Melee label : **Old**  (1/60 slots, 1%)\n"
                     f"Card match  : **New**  (2/60 slots, 2%)\n\n"
                     f"Decision: {decision}\n\n---\n\n")
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        return str(p)

    done = note("[C] Mislabeled Decks 2026-08-30.md",
                [("Alice", "url-a", "New"), ("Bob", "url-b", "New")])
    partial = note("[C] Mislabeled Decks 2026-08-31.md",
                   [("Carol", "url-c", "New"), ("Dave", "url-d", "skip")])

    overrides = {"url-a": {"archetype": "New"}, "url-b": {"archetype": "New"},
                 "url-c": {"archetype": "New"}}
    resolved = ac.archive_resolved_notes([done, partial], overrides, str(tmp_path))

    assert resolved == ["[C] Mislabeled Decks 2026-08-30.md"]
    assert not os.path.exists(done)
    assert os.path.exists(partial), "one skip keeps the whole note in the queue"
    assert os.path.exists(tmp_path / ac.RESOLVED_DIRNAME / os.path.basename(done))


# ── the sibling-awareness rule ────────────────────────────────────────────────

def test_every_skill_in_this_plugin_names_its_siblings():
    """
    Standing rule: a multi-skill plugin gives each SKILL.md a Related skills
    table. Adding a skill means updating the others.

    This used to also glob a root SKILL.md. That file moved into
    skills/mtg-tournament-analysis/ on 2026-08-30, so the special-casing it
    needed is gone. test_plugin_structure.py checks it stays moved, and checks
    the table doesn't name skills that ship somewhere else.
    """
    import glob as _glob
    skill_files = _glob.glob(os.path.join(SCRIPT_DIR, "skills", "*", "SKILL.md"))
    assert len(skill_files) >= 2, "expected at least two skills in this plugin"

    names = {os.path.basename(os.path.dirname(p)) for p in skill_files}

    for path in skill_files:
        text = open(path, encoding="utf-8").read()
        assert "Related skills in this plugin" in text, f"{path} has no Related skills table"
        self_name = os.path.basename(os.path.dirname(path))
        for other in names - {self_name}:
            assert other in text, f"{path} never mentions sibling {other}"


def test_shipped_shell_scripts_are_strictly_ascii():
    """
    Windows PowerShell 5.1 reads a BOM-less file as ANSI, so a UTF-8 em dash
    decodes into three bytes that include a quote-like character and the parser
    dies mid-string. It killed every scheduled scrape on 2026-06-11/12, and it
    killed the push script on 2026-08-29 the same way.

    The comment at the top of Run-MtgScrapes.ps1 says so. A comment is not a
    guard; this is.
    """
    import glob as _glob
    scripts = []
    for pat in ("*.bat", "*.ps1", "*.cmd"):
        scripts.extend(_glob.glob(os.path.join(SCRIPT_DIR, pat)))
    if not scripts:
        pytest.skip("no shell scripts in the repo")

    offenders = []
    for path in scripts:
        try:
            raw = open(path, "rb").read()
        except OSError:
            continue
        bad = [(i, b) for i, b in enumerate(raw) if b > 127]
        if bad:
            i, b = bad[0]
            context = raw[max(0, i - 30):i + 10].decode("utf-8", "replace")
            offenders.append(f"{os.path.basename(path)}: {len(bad)} non-ASCII byte(s), "
                             f"first {b:#x} near ...{context}...")
    assert not offenders, (
        "PowerShell 5.1 will mis-parse these. Replace the character with ASCII:\n  "
        + "\n  ".join(offenders))


def test_card_pool_cache_is_present_and_sane():
    pool, meta = ve.build_card_pool.load_pool("Standard", SCRIPT_DIR)
    if pool is None:
        pytest.skip("no card_pool_standard.json — run build_card_pool.py")
    assert len(pool) > 1000
    assert "llanowar elves" in pool
    assert "goryo's vengeance" not in pool, "Modern-only card must not be in the Standard pool"
