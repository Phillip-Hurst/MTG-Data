"""
Shared scoring helpers for the melee pairing analysis scripts.

One source of truth for how a pairing row becomes a result, so winrate_analysis,
matchup_matrix and update_archetypes all count byes, draws and decided games the
same way. Before this module existed each script reimplemented the logic and
they drifted.

Counting rules:
  - A bye, or any row missing a deck name on either side, is ignored entirely.
  - A game is "decided" only when the winner column matches one of the two
    players. Win rate = wins / decided games. A draw is neither a win nor a
    loss, so it is excluded from that denominator.
  - A row whose winner can't be matched to a player and isn't a recorded draw
    is skipped, not silently counted as a draw.

Data shapes this expects (from melee_scraper.py):
  decided game : result "Jane Doe won 2-1-0", winner "Jane Doe"
  draw         : result "1-1-0 Draw",          winner ""
  bye          : result "Jane Doe was awarded a bye", opponent deck blank
"""

# Archetype name aliases. Merge organizer labels that are the same deck.
# Keep this small and explicit; only merge when confirmed.
ARCHETYPE_ALIASES = {
    "W-U-B-R Control": "Four-Color Control",
}


def normalize(name):
    """Trim and fold known aliases to one canonical archetype name."""
    name = (name or "").strip()
    return ARCHETYPE_ALIASES.get(name, name)


def classify_row(row):
    """Map a pairing row to (deck1, deck2, outcome), decks already normalized.

    outcome is "p1", "p2" or "draw". Returns None for byes, deckless rows and
    unparseable results; callers drop those from every tally.
    """
    d1 = normalize(row.get("player1_deck"))
    d2 = normalize(row.get("player2_deck"))
    if not d1 or not d2:
        return None  # draft round, missing list, or a bye (the bye row has no opponent deck)

    p1 = (row.get("player1") or "").strip()
    p2 = (row.get("player2") or "").strip()
    if not p1 or not p2 or p2.lower() in ("bye", "-bye-"):
        return None

    result = (row.get("result") or "").strip().lower()
    if "awarded a bye" in result:
        return None

    winner = (row.get("winner") or "").strip()
    if winner and winner == p1:
        return d1, d2, "p1"
    if winner and winner == p2:
        return d1, d2, "p2"
    if "draw" in result:
        return d1, d2, "draw"
    # Winner matches neither player and the result isn't a draw. Drop it rather
    # than mis-bucket it as a draw (the bug this module was written to kill).
    return None


def win_pct(wins, losses):
    """Win rate over decided games only. Returns 0.0 when nothing is decided."""
    decided = wins + losses
    return (wins / decided * 100) if decided else 0.0
