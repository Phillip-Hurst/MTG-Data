"""
Mirror matches are a neutral entry.

When both seats play the same deck, the deck gets one win and one loss from the
same match. Counted that way, as it was before 2.0.0, every mirror pulls the
deck's win rate toward 50%, and the most-played decks play the most mirrors, so
the decks people most want a number for got the most flattened one. A mirror
now counts toward a deck's games and meta share and toward neither its win rate
nor its match-win %.
"""
from mtg_data.analyze import update_archetypes, winrate_analysis
from mtg_data.core import stats

DECK = "Placeholder Deck A"
OTHER = "Placeholder Deck B"


def pairing(d1, d2, winner="p1", p1="Ann", p2="Bo"):
    result = {"p1": f"{p1} won 2-1-0", "p2": f"{p2} won 2-1-0", "draw": "1-1-1 Draw",
              "junk": "something odd"}[winner]
    who = {"p1": p1, "p2": p2}.get(winner, "")
    return {"player1": p1, "player2": p2, "player1_deck": d1, "player2_deck": d2,
            "result": result, "winner": who, "tournament_id": "1"}


# ── classify_row ─────────────────────────────────────────────────────────────

def test_a_decided_mirror_is_a_mirror_whoever_won():
    assert stats.classify_row(pairing(DECK, DECK, "p1")) == (DECK, DECK, "mirror")
    assert stats.classify_row(pairing(DECK, DECK, "p2")) == (DECK, DECK, "mirror")


def test_a_drawn_mirror_is_a_mirror():
    assert stats.classify_row(pairing(DECK, DECK, "draw")) == (DECK, DECK, "mirror")


def test_a_mirror_with_an_unparseable_result_is_still_dropped():
    assert stats.classify_row(pairing(DECK, DECK, "junk")) is None


def test_two_spellings_of_one_deck_make_a_mirror():
    """The check runs after alias folding, so 'Izzet Elementals' against
    'Izzet Spellementals' is the same deck playing itself."""
    got = stats.classify_row(pairing("Izzet Elementals", "Izzet Spellementals"))
    assert got == ("Izzet Spellementals", "Izzet Spellementals", "mirror")


def test_a_non_mirror_is_unchanged():
    assert stats.classify_row(pairing(DECK, OTHER, "p1")) == (DECK, OTHER, "p1")


# ── the win-rate tracker ─────────────────────────────────────────────────────

def _field():
    # DECK: 3 wins and 1 loss against OTHER, plus 2 mirrors and a drawn mirror
    rows = [pairing(DECK, OTHER, "p1")] * 3 + [pairing(DECK, OTHER, "p2")]
    rows += [pairing(DECK, DECK, "p1"), pairing(DECK, DECK, "p2"), pairing(DECK, DECK, "draw")]
    return rows


def test_mirrors_move_neither_the_win_rate_nor_the_record():
    games, wins, losses, draws, mirrors, matchups = winrate_analysis.compute_winrates(_field())
    assert (wins[DECK], losses[DECK], draws[DECK]) == (3, 1, 0)
    assert stats.win_pct(wins[DECK], losses[DECK]) == 75.0


def test_mirrors_count_toward_games_once_per_seat():
    games, wins, losses, draws, mirrors, matchups = winrate_analysis.compute_winrates(_field())
    assert mirrors[DECK] == 6, "three mirror matches, two seats each"
    assert games[DECK] == 4 + 6
    assert sum(games.values()) // 2 == 7, "seven matches in, seven out"


def test_the_matchup_table_has_no_mirror_cell():
    *_, matchups = winrate_analysis.compute_winrates(_field())
    assert DECK not in matchups[DECK]


def test_the_report_leaves_mirrors_out_of_match_win(tmp_path, monkeypatch):
    monkeypatch.setattr(winrate_analysis, "VAULT_NOTE", str(tmp_path / "tracker.md"))
    monkeypatch.setattr(winrate_analysis, "MIN_DECK_GAMES", 1)
    games, wins, losses, draws, mirrors, matchups = winrate_analysis.compute_winrates(_field())
    winrate_analysis.write_report(games, wins, losses, draws, mirrors, matchups,
                                  {"1": ("Test RCQ", 7)}, 7)
    text = (tmp_path / "tracker.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith(f"| {DECK} |"))
    cells = [c.strip() for c in line.strip("|").split("|")]
    # Deck | Games | W | L | D | M | Win % | 95% range | Match-win %
    assert cells[1:6] == ["10", "3", "1", "0", "6"]
    assert cells[6] == "75.0%"
    assert cells[8] == "75.0%", "match-win % over the 4 non-mirror games"


# ── the archetype notes ──────────────────────────────────────────────────────

def test_archetype_notes_count_mirrors_the_same_way():
    games, wins, losses, draws, mirrors, matchups, events = update_archetypes.compute(_field())
    assert stats.win_pct(wins[DECK], losses[DECK]) == 75.0
    section = update_archetypes.matchup_section(DECK, games, wins, losses, draws, matchups,
                                                7, 1, mirrors)
    assert "3W-1L-0D" in section
    assert "3 mirror match(es), counted in games only" in section
    assert "Win rate 75.0%" in section
    assert "match-win % incl. draws as 0.5: 75.0%" in section
