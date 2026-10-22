"""
Comprehensive win-rate analysis across the validated melee.gg pool.

Reads the pool through combine_events (which rebuilds it from the per-event
files with the quarantine's verdicts and the seat filter applied), resolves
every deck name through deck_labels, filters out byes / draft / no-deck rounds,
then computes:
  - per-archetype appearance count + win rate (min 10 games), draws excluded
  - head-to-head matchup win rates (min 10 decided games)

Writes a markdown report into the vault.

2026-09-08: this module used to glob the per-event CSVs itself and write its
own version of melee_<format>_all_pairings.csv with no verdict filter, which
made the combined file's contents depend on run order. It also read deck names
straight off the CSV row, so it saw organizer text where build_baseline saw
classifier verdicts. Both are now handled upstream.
"""

import argparse
import collections
import os
import sys
from datetime import datetime

from mtg_data.classify import deck_labels
from mtg_data.core.paths import ROOT_DIR
from mtg_data.core.stats import classify_row, wilson_interval, win_pct
from mtg_data.quality import combine_events

# Windows consoles default to cp1252 and choke on box-drawing and accented
# characters in deck names. Force UTF-8 where the stream supports it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Data (the scraped CSVs) is read from MTG_DATA_DIR; defaults to the checkout
# root, the flat single-format workflow. setup_workspace.py points this at a
# per-format folder so formats don't cross-contaminate.
DATA_DIR = os.environ.get("MTG_DATA_DIR", ROOT_DIR)
# Win-rate report written next to the data by default.
# Set MTG_OUTPUT_DIR to write it elsewhere (e.g. your vault project folder).
_OUTPUT_DIR = os.environ.get("MTG_OUTPUT_DIR", DATA_DIR)
VAULT_NOTE  = os.path.join(_OUTPUT_DIR, "melee_win_rate_tracker.md")
# Format slug tags the rebuilt combined CSV so formats never share a filename.
FMT_SLUG = (os.environ.get("MTG_FORMAT", "Standard").strip() or "Standard").lower()

MIN_DECK_GAMES = 10
MIN_MATCHUP_GAMES = 10

PAIRING_FIELDS = [
    "tournament_id", "tournament_name", "round", "table_num",
    "player1", "player1_deck", "player1_deck_url",
    "player2", "player2_deck", "player2_deck_url",
    "result", "winner",
]

def load_pool():
    """
    The validated pairing pool, plus a per-tournament breakdown.

    This module used to glob the per-event CSVs itself and then write its own
    version of melee_<fmt>_all_pairings.csv with no verdict filter, which made
    the combined file's contents depend on which script ran last. It also meant
    the win-rate math skipped the seat filter, so a Standard player paired
    against a Modern player inside a team event counted as a Standard match.

    combine_events owns the pool now. It rebuilds from the per-event files,
    applies the verdicts and the seat filter, and is the only writer.
    """
    rows, summary = combine_events.load_pool(DATA_DIR, FMT_SLUG, "pairings",
                                            resolve_names=True)
    tournaments = collections.OrderedDict()
    for r in rows:
        tid = (r.get("tournament_id") or "").strip()
        name, n = tournaments.get(tid, ((r.get("tournament_name") or "").strip(), 0))
        tournaments[tid] = (name, n + 1)
    return rows, tournaments, summary


def compute_winrates(rows):
    """Tally decided games and draws per deck and per matchup.

    Byes, deckless rows and unparseable winners are dropped by classify_row, so
    they never reach these counters. Win rate is computed over decided games
    only (wins + losses); draws are tracked separately and excluded from it.
    """
    deck_wins    = collections.Counter()
    deck_losses  = collections.Counter()
    deck_draws   = collections.Counter()
    matchup_wins = collections.defaultdict(collections.Counter)  # d1 → Counter(d2 beaten)

    for r in rows:
        c = classify_row(r)
        if not c:
            continue
        d1, d2, outcome = c
        if outcome == "p1":
            deck_wins[d1] += 1
            deck_losses[d2] += 1
            matchup_wins[d1][d2] += 1
        elif outcome == "p2":
            deck_wins[d2] += 1
            deck_losses[d1] += 1
            matchup_wins[d2][d1] += 1
        else:  # draw — counts for neither side's win rate
            deck_draws[d1] += 1
            deck_draws[d2] += 1

    decks = set(deck_wins) | set(deck_losses) | set(deck_draws)
    deck_games = {d: deck_wins[d] + deck_losses[d] + deck_draws[d] for d in decks}
    return deck_games, deck_wins, deck_losses, deck_draws, matchup_wins


def write_report(deck_games, deck_wins, deck_losses, deck_draws, matchup_wins, tournaments, total_rows):
    today = datetime.now().strftime("%Y-%m-%d")
    total_kept = sum(deck_games.values()) // 2  # each match counted twice

    lines = []
    lines.append("---")
    lines.append("author: claude")
    lines.append("type: solution")
    lines.append("project: MTG Tournament Analysis Skill")
    lines.append(f"date: {today}")
    lines.append("tags: [mtg, standard, melee, winrates]")
    lines.append("---")
    lines.append("")
    lines.append("# Melee win-rate tracker")
    lines.append("")
    lines.append(f"Last updated: {today}")
    lines.append(f"Source: {len(tournaments)} tournaments, {total_kept:,} Standard matches with deck names on both sides ({total_rows:,} total pairing rows loaded).")
    lines.append("")
    lines.append("## Tournaments in dataset")
    lines.append("")
    lines.append("| ID | Name | Pairing rows |")
    lines.append("|---|---|---|")
    for tid, (name, n) in tournaments.items():
        clean_name = name.replace("|", "/")[:70]
        lines.append(f"| {tid} | {clean_name} | {n:,} |")
    lines.append("")
    lines.append(f"## Deck win rates (min {MIN_DECK_GAMES} games)")
    lines.append("")
    lines.append("Win % = wins / decided games (wins + losses). A draw is neither a win nor a loss, so it is excluded from that rate. Match-win %, shown for reference, counts a draw as half a win across all games.")
    lines.append("")
    lines.append("The 95% range is a Wilson score interval on the win rate. Where it straddles 50%, this sample can't tell the deck from a coin flip yet.")
    lines.append("")
    lines.append("| Deck | Games | W | L | D | Win % | 95% range | Match-win % |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")

    ranked = []
    for deck, games in deck_games.items():
        if games < MIN_DECK_GAMES:
            continue
        wins = deck_wins[deck]
        losses = deck_losses[deck]
        draws = deck_draws[deck]
        wr = win_pct(wins, losses)
        mwr = (wins + 0.5 * draws) / games * 100 if games else 0
        ranked.append((deck, games, wins, losses, draws, wr, mwr))
    ranked.sort(key=lambda x: -x[5])
    for deck, games, wins, losses, draws, wr, mwr in ranked:
        lo, hi = wilson_interval(wins, losses)
        lines.append(f"| {deck} | {games} | {wins} | {losses} | {draws} | {wr:.1f}% "
                     f"| {lo:.0f}-{hi:.0f}% | {mwr:.1f}% |")
    lines.append("")

    lines.append(f"## Head-to-head matchup matrix (min {MIN_MATCHUP_GAMES} games per pairing)")
    lines.append("")
    lines.append("Read as: row deck's win rate vs column deck. Symmetric data — both perspectives counted.")
    lines.append("")

    # Keep the matrix manageable: decks with 30+ total games, top 18 by volume.
    big_decks = [d for d, games, *_ in ranked if games >= 30]
    big_decks = sorted(big_decks, key=lambda d: -deck_games[d])[:18]

    # Header row
    header = "| Matchup |" + "|".join(f" {d[:14]} " for d in big_decks) + "|"
    sep = "|---|" + "|".join("---:" for _ in big_decks) + "|"
    lines.append(header)
    lines.append(sep)
    for row_deck in big_decks:
        cells = [f"**{row_deck[:18]}**"]
        for col_deck in big_decks:
            if row_deck == col_deck:
                cells.append(" — ")
                continue
            row_wins = matchup_wins[row_deck].get(col_deck, 0)
            col_wins = matchup_wins[col_deck].get(row_deck, 0)
            decided = row_wins + col_wins
            if decided < MIN_MATCHUP_GAMES:
                cells.append(" · ")
            else:
                wr = row_wins / decided * 100
                cells.append(f"{wr:.0f}% ({decided})")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Most-played head-to-head pairings")
    lines.append("")
    lines.append("Decided games only (draws excluded). A win % is from Deck A's side.")
    lines.append("")
    lines.append("| Deck A | Deck B | A wins | B wins | Decided | A win % | 95% range |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    seen_pairs = set()
    top_matchups = []
    for d1 in list(matchup_wins):
        for d2 in list(matchup_wins[d1]):
            key = frozenset((d1, d2))
            if key in seen_pairs or d1 == d2:
                continue
            seen_pairs.add(key)
            a_wins = matchup_wins[d1].get(d2, 0)
            b_wins = matchup_wins.get(d2, {}).get(d1, 0)
            total = a_wins + b_wins
            if total < MIN_MATCHUP_GAMES:
                continue
            wr = a_wins / total * 100 if total else 0
            top_matchups.append((d1, d2, a_wins, b_wins, total, wr))
    top_matchups.sort(key=lambda x: -x[4])
    for d1, d2, aw, bw, total, wr in top_matchups[:30]:
        lo, hi = wilson_interval(aw, bw)
        lines.append(f"| {d1} | {d2} | {aw} | {bw} | {total} | {wr:.1f}% | {lo:.0f}-{hi:.0f}% |")
    lines.append("")

    with open(VAULT_NOTE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nWin-rate report updated: {VAULT_NOTE}")
    print(f"  Decks with {MIN_DECK_GAMES}+ games: {len(ranked)}")
    print(f"  Matchup pairings with {MIN_MATCHUP_GAMES}+ games: {len(top_matchups)}")


def main():
    argparse.ArgumentParser(
        prog="mtg winrate-analysis",
        description="Win rates per archetype over the validated melee.gg pool. "
                    "Reads MTG_DATA_DIR and writes melee_win_rate_tracker.md to "
                    "MTG_OUTPUT_DIR.").parse_args()
    print("Loading the validated pairing pool...")
    rows, tournaments, summary = load_pool()
    if not rows:
        print(f"\nNo melee pairing rows in:\n  {DATA_DIR}")
        print("Run the melee scraper first (scrape.bat / scrape.sh, or "
              "python mtg.py fetch-melee), then python mtg.py validate-events, then try again.")
        return 1
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    print(f"  Pool: {combine_events.describe_pool(summary)}")
    for line in deck_labels.pairing_report_lines(summary["label_stats"]):
        print(line)
    for tid, (name, n) in tournaments.items():
        print(f"    {tid}  {n:5,}  {name[:60]}")
    if summary and summary["unjudged_events"]:
        print(f"\n  {len(summary['unjudged_events'])} event(s) carry no verdict. "
              "Run python mtg.py validate-events before quoting these numbers.")
    if summary and summary["unreadable_files"]:
        print(f"  ! {len(summary['unreadable_files'])} per-event file(s) could not "
              "be read, so those events contributed nothing.")

    print("\nComputing win rates...")
    dg, dw, dl, dd, mw = compute_winrates(rows)
    valid = sum(dg.values()) // 2
    print(f"  Matches with decks on both sides (byes/draws handled): {valid:,}")
    print(f"  Unique archetypes seen: {len(dg)}")
    print(f"  Archetypes with {MIN_DECK_GAMES}+ games: {sum(1 for d,n in dg.items() if n >= MIN_DECK_GAMES)}")

    write_report(dg, dw, dl, dd, mw, tournaments, len(rows))


if __name__ == "__main__":
    main()
