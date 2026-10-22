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
  - A mirror match (the same deck in both seats) is a neutral entry. It
    counts toward the deck's games and meta share, and toward neither its win
    rate nor its match-win %. Counted as a win and a loss, as it was before
    2.0.0, it pulled every popular deck's rate toward 50%, and the more a deck
    was played, the harder it pulled.

Data shapes this expects (from melee_scraper.py):
  decided game : result "Jane Doe won 2-1-0", winner "Jane Doe"
  draw         : result "1-1-0 Draw",          winner ""
  bye          : result "Jane Doe was awarded a bye", opponent deck blank
"""

import math

# Archetype name aliases. Merge organizer labels that are the same deck.
# Keep this small and explicit; only merge when confirmed.
#
# The canonical name on the right is always one the vault already uses — the
# filenames in 02 Projects/MTG Tournament Analysis Skill/Archetypes/. That's
# the vocabulary the archetype notes, matchup tables and snapshots are written
# in, so pulling every source onto it keeps one deck under one name.
#
# 2026-08-29: seeding references from mtgtop8 on top of locally-built ones
# introduced 15 new labels, several of them the same deck under a different
# house style. audit_refs.py found 16 pairs sharing 60%+ of their slots, and
# classify_decks picks on raw slot overlap with no margin — so a near-tie is
# resolved by dictionary order, which is to say arbitrarily. These are the
# pairs confirmed to be one deck. The genuinely ambiguous ones are deliberately
# absent; naming a deck is the user's call, not the tooling's.
ARCHETYPE_ALIASES = {
    # Four-colour control: four names, one deck.
    "W-U-B-R Control": "Four-Color Control",
    "W-U-B-R": "Four-Color Control",
    "4/5C Control": "Four-Color Control",
    "4c Control": "Four-Color Control",
    "4-Color Control": "Four-Color Control",

    # melee lets players type a bare guild name; "Izzet" isn't a deck, it's an
    # unfinished label. Elementals and Spellementals are one deck under two
    # house styles: the post-ban clustering put all 43 into a single group
    # labelled 22 Spellementals / 20 Elementals, they share 84% of their slots,
    # and the mislabel report flags them against each other in both directions.
    # Spellementals is the name the vault's Archetypes folder uses.
    "Izzet": "Izzet Spellementals",
    "Izzet Elementals": "Izzet Spellementals",

    # mtgtop8 house style vs the vault's names.
    "Dimir Aggro": "Dimir Midrange",
    "Mardu Aggro": "Mardu Discard",
    "Azorius Fliers": "Azorius Momo",
    "Mono Green Aggro": "Mono Green Landfall",
    "Mono-Green": "Mono Green Landfall",
    "Mono-Green Landfall": "Mono Green Landfall",
    "Superior Doomsday": "Dimir Excruciator",

    # 2026-08-29, Phill's rulings.
    #
    # Azorius Tempo and Azorius Prison are one deck when both play the flash
    # game: Aang, Aven Interrupter, High Noon, Voice of Victory. Checked before
    # applying — both references carry all four, plus Avatar's Wrath, Floodpits
    # Drowner, Skycoach Conductor and Restless Anchorage. The vault already
    # settled the name: [C] Azorius Flash.md's front matter reads
    # "Azorius Flash (Azorius Tempo)".
    "Azorius Tempo": "Azorius Flash",
    "Azorius Prison": "Azorius Flash",

    # The Amalia deck. mtgtop8 files it under its colours; what it actually
    # does is gain life.
    "Orzhov Aggro": "Orzhov Lifegain",
    "Orzhov": "Orzhov Lifegain",
    "Orzhov Combo": "Orzhov Lifegain",
    "Orzhov Midrange": "Orzhov Lifegain",
}


def normalize(name):
    """Trim and fold known aliases to one canonical archetype name."""
    name = (name or "").strip()
    return ARCHETYPE_ALIASES.get(name, name)


def classify_row(row):
    """Map a pairing row to (deck1, deck2, outcome), decks already normalized.

    outcome is "p1", "p2", "draw" or "mirror". "mirror" means both seats are
    the same deck, whoever won; it is a neutral entry (see the module notes).
    Returns None for byes, deckless rows and unparseable results; callers drop
    those from every tally.
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
        outcome = "p1"
    elif winner and winner == p2:
        outcome = "p2"
    elif "draw" in result:
        outcome = "draw"
    else:
        # Winner matches neither player and the result isn't a draw. Drop it
        # rather than mis-bucket it as a draw (the bug this module was written
        # to kill). A mirror with an unparseable result is dropped the same way.
        return None
    if d1 == d2:
        return d1, d2, "mirror"
    return d1, d2, outcome


def win_pct(wins, losses):
    """Win rate over decided games only. Returns 0.0 when nothing is decided."""
    decided = wins + losses
    return (wins / decided * 100) if decided else 0.0


def wilson_interval(wins, losses, z=1.96):
    """95% Wilson score interval for a win rate over decided games, in percent.

    Returns (low, high). With nothing decided the rate could be anything, so
    the interval is (0.0, 100.0).

    Wilson rather than the textbook p +/- z*sqrt(p(1-p)/n) because that one
    collapses to zero width at 0 or 100% and spills outside 0-100 on small
    samples, and small samples are most of what one format era produces: a
    matchup cell at the 10-match floor at 60% runs from 31% to 83%.
    """
    n = wins + losses
    if n == 0:
        return 0.0, 100.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, (centre - half) * 100), min(100.0, (centre + half) * 100)
