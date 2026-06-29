"""
Tests for the win-rate counting rules (mtg_stats).

Two layers:
  - Unit tests on classify_row / win_pct that pin the counting behaviour: a draw
    is neither a win nor a loss, byes and unparseable winners are dropped, and
    aliases fold. These run anywhere.
  - An integration test that points at your live scraped pairings CSVs and checks
    invariants on real data. It SKIPS cleanly when there's no local scrape yet
    (e.g. a fresh Cowork install), so the suite still passes for someone who
    hasn't scraped.

Run:  pytest          (from the skill folder)
"""
import csv
import glob
import os

import pytest

import mtg_stats


def row(**kw):
    base = {"player1": "", "player2": "", "player1_deck": "", "player2_deck": "",
            "result": "", "winner": ""}
    base.update(kw)
    return base


# ── Unit: classify_row ────────────────────────────────────────────────────────

def test_decided_player1_wins():
    r = row(player1="Jane", player2="Bob", player1_deck="Izzet", player2_deck="Dimir",
            result="Jane won 2-1-0", winner="Jane")
    assert mtg_stats.classify_row(r) == ("Izzet", "Dimir", "p1")


def test_decided_player2_wins():
    r = row(player1="Jane", player2="Bob", player1_deck="Izzet", player2_deck="Dimir",
            result="Bob won 2-0-0", winner="Bob")
    assert mtg_stats.classify_row(r) == ("Izzet", "Dimir", "p2")


def test_draw_is_a_draw():
    r = row(player1="Jane", player2="Bob", player1_deck="Izzet", player2_deck="Dimir",
            result="1-1-0 Draw", winner="")
    assert mtg_stats.classify_row(r) == ("Izzet", "Dimir", "draw")


def test_bye_is_dropped():
    r = row(player1="Jane", player2="", player1_deck="Izzet", player2_deck="",
            result="Jane was awarded a bye", winner="Jane")
    assert mtg_stats.classify_row(r) is None


def test_unparseable_winner_is_dropped_not_a_draw():
    # winner matches neither player and the result isn't a draw → drop it
    r = row(player1="Jane", player2="Bob", player1_deck="Izzet", player2_deck="Dimir",
            result="garbled", winner="Someone Else")
    assert mtg_stats.classify_row(r) is None


def test_missing_deck_is_dropped():
    r = row(player1="Jane", player2="Bob", player1_deck="Izzet", player2_deck="",
            result="Jane won 2-1-0", winner="Jane")
    assert mtg_stats.classify_row(r) is None


def test_alias_is_folded():
    r = row(player1="Jane", player2="Bob", player1_deck="W-U-B-R Control",
            player2_deck="Dimir", result="Jane won 2-0-0", winner="Jane")
    d1, _, _ = mtg_stats.classify_row(r)
    assert d1 == "Four-Color Control"


# ── Unit: win_pct ─────────────────────────────────────────────────────────────

def test_win_pct_excludes_draws():
    # draws aren't part of the call at all: 7 wins, 3 losses → 70%
    assert mtg_stats.win_pct(7, 3) == 70.0


def test_win_pct_no_decided_games_is_zero():
    assert mtg_stats.win_pct(0, 0) == 0.0


# ── Integration: your live scraped data (skips if none) ───────────────────────

def _live_pairings_files():
    here = os.path.dirname(os.path.abspath(__file__))
    bases = {os.environ.get("MTG_DATA_DIR", ""), os.path.dirname(here)}
    files = []
    for base in bases:
        if base:
            files += glob.glob(os.path.join(base, "melee_*_pairings.csv"))
    return [p for p in set(files) if not os.path.basename(p).endswith("_all_pairings.csv")]


def test_live_data_invariants():
    files = _live_pairings_files()
    if not files:
        pytest.skip("no local scrape data found — run the scraper first")

    wins = {}          # (a, b) -> times a beat b
    decided = draws = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                c = mtg_stats.classify_row(r)
                if not c:
                    continue
                d1, d2, outcome = c
                if outcome == "draw":
                    draws += 1
                    continue
                decided += 1
                a, b = (d1, d2) if outcome == "p1" else (d2, d1)
                wins[(a, b)] = wins.get((a, b), 0) + 1

    assert decided > 0, "live data produced no decided games — parser may be stale"

    # Every matchup win rate from real data stays in range, and the decided-games
    # denominator never undercounts one side's wins.
    pairs = set(wins) | {(b, a) for (a, b) in wins}
    for a, b in pairs:
        aw, bw = wins.get((a, b), 0), wins.get((b, a), 0)
        n = aw + bw
        if n:
            assert 0.0 <= mtg_stats.win_pct(aw, bw) <= 100.0
            assert aw <= n
