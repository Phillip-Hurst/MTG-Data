"""
Render a clean matchup matrix and a Jeskai vs 4-Color Control side-by-side comparison.
Reads the per-tournament pairing CSVs (same loader as winrate_analysis.py).
"""
import csv, os, glob, collections, sys

from mtg_stats import classify_row

# Windows consoles default to cp1252 and choke on box-drawing and accented
# characters in deck names. Force UTF-8 where the stream supports it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Scraped CSVs come from MTG_DATA_DIR (defaults to the script folder); the
# rendered matrix is written under MTG_OUTPUT_DIR. setup.py sets both per format.
DATA_DIR   = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)
OUTPUT_DIR = os.environ.get("MTG_OUTPUT_DIR", DATA_DIR)
OUT_TXT    = os.path.join(OUTPUT_DIR, "transcripts", "matchup_matrix.txt")

MIN_MATCHUP_GAMES = 10

def load_pairings():
    rows = []
    for p in glob.glob(os.path.join(DATA_DIR, "melee_*_pairings.csv")):
        if os.path.basename(p).endswith("_all_pairings.csv"):
            continue
        with open(p, encoding="utf-8") as f:
            rows.extend(list(csv.DictReader(f)))
    return rows

def compute(rows):
    """Tally per-deck games and decided matchup wins via the shared classifier.

    deck_games counts every decided game and draw a deck played (used only to
    order and size the matrix). matchup_wins[a][b] is how many times a beat b,
    so cell win rates run over decided games and draws never inflate a
    denominator; byes are dropped entirely.
    """
    deck_games   = collections.Counter()
    matchup_wins = collections.defaultdict(collections.Counter)
    for r in rows:
        c = classify_row(r)
        if not c:
            continue
        d1, d2, outcome = c
        deck_games[d1] += 1
        deck_games[d2] += 1
        if outcome == "p1":
            matchup_wins[d1][d2] += 1
        elif outcome == "p2":
            matchup_wins[d2][d1] += 1
        # a draw still counts toward deck_games (sample size), no win for either
    return deck_games, matchup_wins

# ── Render helpers ──────────────────────────────────────────────────────────

def matrix_table(decks, deck_games, matchup_wins):
    out = []
    col_w = 14
    out.append("\n# MATCHUP MATRIX — % win rate for ROW deck vs COLUMN deck (decided games in parens)")
    out.append(f"# Minimum {MIN_MATCHUP_GAMES} decided games to print a cell. Decks ordered by total games played.\n")

    # Header
    header = f"{'Deck (n games)':<28} | " + " | ".join(f"{d[:col_w]:>{col_w}}" for d in decks)
    out.append(header)
    out.append("-" * len(header))
    for row in decks:
        rg = deck_games[row]
        cells = []
        for col in decks:
            if row == col:
                cells.append(f"{'—':>{col_w}}")
                continue
            w = matchup_wins[row].get(col, 0)
            decided = w + matchup_wins[col].get(row, 0)
            if decided < MIN_MATCHUP_GAMES:
                cells.append(f"{'·':>{col_w}}")
            else:
                wr = w/decided*100
                cells.append(f"{wr:4.0f}% ({decided:>4d}) "[:col_w].rjust(col_w))
        out.append(f"{row[:26] + ' ('+str(rg)+')':<28} | " + " | ".join(cells))
    return "\n".join(out)

def control_comparison(deck_games, matchup_wins):
    """Side-by-side: Jeskai Control vs Four-Color Control performance into each opponent."""
    out = []
    out.append("\n\n# JESKAI CONTROL vs FOUR-COLOR CONTROL — SIDE-BY-SIDE")
    out.append("# How each control archetype performs into the same opponent set.")
    out.append("# Note: W-U-B-R Control is merged into Four-Color Control (same archetype, different organizer label).\n")

    def decided(a, b):
        return matchup_wins[a].get(b, 0) + matchup_wins[b].get(a, 0)

    controls = ["Jeskai Control", "Four-Color Control"]
    # All opponents either control deck has 10+ decided games against
    opponents = set()
    for c in controls:
        for opp in deck_games:
            if opp != c and decided(c, opp) >= MIN_MATCHUP_GAMES:
                opponents.add(opp)
    opponents = sorted(opponents, key=lambda d: -deck_games[d])

    # Header
    header = f"{'Opponent':<26} | " + " | ".join(f"{c[:18]:>20}" for c in controls)
    out.append(header)
    out.append("-" * len(header))

    for opp in opponents:
        row = [f"{opp[:24]} ({deck_games[opp]:>4})"]
        for c in controls:
            n = decided(c, opp)
            w = matchup_wins[c].get(opp, 0)
            if n < MIN_MATCHUP_GAMES:
                row.append(f"{'·  (n='+str(n)+')':>20}")
            else:
                wr = w/n*100
                row.append(f"{wr:5.1f}%  (n={n:>3})".rjust(20))
        out.append(f"{row[0]:<26} | " + " | ".join(row[1:]))

    # Totals
    out.append("-" * len(header))
    totals = []
    for c in controls:
        total_n = sum(decided(c, o) for o in deck_games if decided(c, o) >= MIN_MATCHUP_GAMES)
        total_w = sum(matchup_wins[c].get(o, 0) for o in deck_games if decided(c, o) >= MIN_MATCHUP_GAMES)
        if total_n:
            totals.append(f"{total_w/total_n*100:5.1f}%  (n={total_n:>3})".rjust(20))
        else:
            totals.append(f"{'(no qualifying)':>20}")
    out.append(f"{'WEIGHTED AVG (10+ games)':<26} | " + " | ".join(totals))

    # Overall full record (all opponents)
    out.append("")
    out.append(f"{'OVERALL (all games)':<26} | " + " | ".join(
        f"{deck_games[c]:>5} games".rjust(20) for c in controls
    ))

    return "\n".join(out)

def main():
    rows = load_pairings()
    if not rows:
        print(f"No melee pairing files found in:\n  {DATA_DIR}")
        print("Run the melee scraper first (scrape.bat / scrape.sh, or "
              "mtg_fetch.py), then try again.")
        return
    dg, mw = compute(rows)

    # 18 most-played decks
    big = [d for d,n in dg.most_common(18)]
    out_lines = [matrix_table(big, dg, mw), control_comparison(dg, mw)]

    text = "\n".join(out_lines)
    os.makedirs(os.path.dirname(OUT_TXT), exist_ok=True)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)

if __name__ == "__main__":
    main()
