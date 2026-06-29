"""
Update each archetype MD file with the latest matchup data, and create a
Meta Snapshot summarizing the current Standard state.

Everything written here is computed from the per-tournament melee_*_pairings.csv
files on disk. No hand-written narrative is baked in — the snapshot reflects
whatever data is present at run time, so it is safe to run unattended after a
scrape. (Earlier versions carried a fixed May-12 write-up; that was removed
2026-06-12 because it stamped stale prose with the current date.)
"""
import csv, os, glob, collections, re, json, sys
from datetime import datetime

from mtg_stats import classify_row, win_pct

# Windows consoles default to cp1252 and choke on box-drawing and accented
# characters in deck names. Force UTF-8 where the stream supports it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Scraped CSVs come from MTG_DATA_DIR (defaults to the script folder so the flat
# single-format workflow is unchanged). setup.py sets it per format.
DATA_DIR = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)
FORMAT = os.environ.get("MTG_FORMAT", "Standard").strip() or "Standard"


def _find_config(name):
    p = os.path.join(DATA_DIR, name)
    return p if os.path.exists(p) else os.path.join(SCRIPT_DIR, name)


def current_set_name():
    """Most recent set in set_releases.json. Used to title the Standard
    snapshot so it isn't frozen to one set. Falls back gracefully."""
    try:
        with open(_find_config("set_releases.json"), encoding="utf-8") as f:
            sets = [s for s in json.load(f).get("sets", []) if s.get("release_date")]
        if sets:
            sets.sort(key=lambda s: s["release_date"])
            return sets[-1]["name"]
    except (OSError, ValueError, KeyError):
        pass
    return None
# Derive the project + archetype folders from this script's location instead of
# hardcoding a username. The vault is laid out as:
#   <vault>\Skills\mtg-tournament-analysis   <- SCRIPT_DIR
#   <vault>\02 Projects\MTG Tournament Analysis Skill
# so the vault root is two levels up. This works on both the "Phill" and
# "PhillHurst" machines without editing.
# Archetype files written to an archetypes/ subfolder by default.
# Set MTG_OUTPUT_DIR to write them elsewhere (e.g. your vault project folder).
# Phill's vault layout: MTG_OUTPUT_DIR = <vault>\02 Projects\MTG Tournament Analysis Skill
PROJECT_DIR = os.environ.get("MTG_OUTPUT_DIR", DATA_DIR)
ARCH_DIR    = os.path.join(PROJECT_DIR, "Archetypes")

MIN_DECK_GAMES = 10
MIN_MATCHUP_GAMES = 10
DOC_THRESHOLD = 100   # games before an undocumented deck is flagged for a file
TODAY = datetime.now().strftime("%Y-%m-%d")

# Decks that are really "unclassified" rows, not archetypes.
JUNK_DECKS = {"", "decklist", "unknown", "deck", "n/a", "-", "—"}

# Map data archetype name → filename slug (file is "[C] {slug}.md")
NAME_TO_FILENAME = {
    "Mono-Green Landfall": "Mono Green Landfall",
    # rest are direct passthrough
}

# ── Load pairings ──────────────────────────────────────────────────────────

def load_pairings():
    rows = []
    for p in glob.glob(os.path.join(DATA_DIR, "melee_*_pairings.csv")):
        if os.path.basename(p).endswith("_all_pairings.csv"):
            continue
        with open(p, encoding="utf-8") as f:
            rows.extend(list(csv.DictReader(f)))
    return rows

def compute(rows):
    deck_wins    = collections.Counter()
    deck_losses  = collections.Counter()
    deck_draws   = collections.Counter()
    matchup_wins = collections.defaultdict(collections.Counter)
    tournaments  = set()
    for r in rows:
        c = classify_row(r)
        if not c:
            continue
        tournaments.add(r.get("tournament_id", ""))
        d1, d2, outcome = c
        if outcome == "p1":
            deck_wins[d1] += 1
            deck_losses[d2] += 1
            matchup_wins[d1][d2] += 1
        elif outcome == "p2":
            deck_wins[d2] += 1
            deck_losses[d1] += 1
            matchup_wins[d2][d1] += 1
        else:  # draw — sample size only, no win or loss
            deck_draws[d1] += 1
            deck_draws[d2] += 1
    decks = set(deck_wins) | set(deck_losses) | set(deck_draws)
    deck_games = {d: deck_wins[d] + deck_losses[d] + deck_draws[d] for d in decks}
    return deck_games, deck_wins, deck_losses, deck_draws, matchup_wins, tournaments

# ── Build matchup data section for a single archetype ──────────────────────

def matchup_section(deck, deck_games, deck_wins, deck_losses, deck_draws, matchup_wins, total_matches, n_tournaments):
    games = deck_games.get(deck, 0)
    if games == 0:
        return None
    wins = deck_wins[deck]
    losses = deck_losses[deck]
    draws = deck_draws[deck]
    wr = win_pct(wins, losses)
    mwr = (wins + 0.5*draws)/games*100 if games else 0

    # Opponents this deck faced in either direction; win rate over decided games.
    opp_set = set(matchup_wins[deck].keys())
    for opp in matchup_wins:
        if deck in matchup_wins[opp]:
            opp_set.add(opp)
    opp_set.discard(deck)
    opponents = []
    for opp in opp_set:
        w = matchup_wins[deck].get(opp, 0)
        decided = w + matchup_wins[opp].get(deck, 0)
        if decided < MIN_MATCHUP_GAMES:
            continue
        opponents.append((opp, decided, w, w/decided*100))
    opponents.sort(key=lambda x: -x[1])

    lines = []
    lines.append("## Matchup data")
    lines.append("")
    lines.append(f"*Updated: {TODAY} · {n_tournaments} melee.gg tournaments · {total_matches:,} {FORMAT} matches with deck names on both sides*")
    lines.append("")
    lines.append(f"**Overall: {games} games · {wins}W-{losses}L-{draws}D · Win rate {wr:.1f}% over decided games (match-win % incl. draws as 0.5: {mwr:.1f}%)**")
    lines.append("")
    if opponents:
        lines.append("| Opponent | Win% | N | Notes |")
        lines.append("|---|---:|---:|---|")
        for opp, n, w, opp_wr in opponents:
            note = "small sample" if n < 20 else ""
            lines.append(f"| {opp} | {opp_wr:.1f}% | {n} | {note} |")
    else:
        lines.append(f"_No matchup with at least {MIN_MATCHUP_GAMES} decided games yet._")
    lines.append("")
    return "\n".join(lines)

# ── Update each existing archetype file ────────────────────────────────────

def update_files(deck_games, deck_wins, deck_losses, deck_draws, matchup_wins, total_matches, n_tournaments):
    updated = []
    unmatched = []
    files = glob.glob(os.path.join(ARCH_DIR, "[[]C[]] *.md"))
    for fp in files:
        fname = os.path.basename(fp)
        # Derive deck name from filename: "[C] Izzet Prowess.md" → "Izzet Prowess"
        slug = re.sub(r"^\[C\]\s*", "", fname).replace(".md", "").strip()
        # Find matching data key
        data_key = None
        for k in deck_games.keys():
            slug_for_k = NAME_TO_FILENAME.get(k, k)
            if slug_for_k == slug:
                data_key = k
                break
        if not data_key:
            unmatched.append(slug)
            continue

        with open(fp, encoding="utf-8") as f:
            content = f.read()

        new_section = matchup_section(data_key, deck_games, deck_wins, deck_losses,
                                       deck_draws, matchup_wins, total_matches, n_tournaments)
        if not new_section:
            continue

        if "## Matchup data" in content:
            head = content[:content.index("## Matchup data")].rstrip() + "\n\n"
            new_content = head + new_section
        else:
            new_content = content.rstrip() + "\n\n---\n\n" + new_section

        # Bump frontmatter date if present
        new_content = re.sub(r"^date:\s*\d{4}-\d{2}-\d{2}",
                             f"date: {TODAY}", new_content, count=1, flags=re.M)

        with open(fp, "w", encoding="utf-8") as f:
            f.write(new_content)
        updated.append((slug, deck_games[data_key]))
    return updated, unmatched

# ── Build the meta snapshot (fully computed from data) ─────────────────────

def documented_slugs():
    slugs = set()
    for fp in glob.glob(os.path.join(ARCH_DIR, "[[]C[]] *.md")):
        fname = os.path.basename(fp)
        slugs.add(re.sub(r"^\[C\]\s*", "", fname).replace(".md", "").strip())
    return slugs

def build_meta(deck_games, deck_wins, deck_losses, deck_draws, matchup_wins, tournaments, total_matches):
    field_size = sum(deck_games.values()) // 2

    def wr(d):
        return win_pct(deck_wins[d], deck_losses[d])
    def share(d):
        return deck_games[d] / (field_size * 2) * 100 if field_size else 0

    real_decks = [(d, n) for d, n in sorted(deck_games.items(), key=lambda kv: -kv[1])
                  if d.lower() not in JUNK_DECKS]
    big_decks = [d for d, n in real_decks if n >= 100]

    lines = []
    lines.append("---")
    lines.append("author: claude")
    lines.append("type: solution")
    lines.append("project: MTG Tournament Analysis Skill")
    lines.append(f"date: {TODAY}")
    lines.append("tags: [mtg, standard, meta, snapshot]")
    lines.append("---")
    set_name = current_set_name()
    title = f"# {FORMAT} meta snapshot"
    if FORMAT == "Standard" and set_name:
        title += f" — {set_name}"
    lines.append("")
    lines.append(title)
    lines.append("")
    lines.append(f"As of {TODAY}. Computed from {len(tournaments)} melee.gg tournaments, {total_matches:,} {FORMAT} matches with a deck name on both sides. Field of roughly {field_size:,} deck-appearances. Everything below is generated from the pairing data, not hand-written — read it as a numbers summary, not a finished meta call.")
    lines.append("")

    # ── Headline (computed) ──────────────────────────────────────────────
    lines.append("## Headline")
    lines.append("")
    if big_decks:
        top = big_decks[0]
        by_wr = sorted(big_decks, key=lambda d: -wr(d))
        best, worst = by_wr[0], by_wr[-1]
        lines.append(f"Most-played deck: **{top}** at {deck_games[top]:,} games ({share(top):.1f}% of the field), winning {wr(top):.1f}%.")
        lines.append("")
        lines.append(f"Best win rate among 100+ game decks: **{best}** at {wr(best):.1f}% ({deck_games[best]:,} games). Worst: **{worst}** at {wr(worst):.1f}% ({deck_games[worst]:,} games).")
        lines.append("")
        lines.append(f"{len(big_decks)} archetypes cleared the 100-game bar this sample.")
    else:
        lines.append("No archetype has reached 100 games yet in this sample. Treat everything below as provisional.")
    lines.append("")

    # ── Tier list ────────────────────────────────────────────────────────
    lines.append("## Tier list — by win rate among 100+ game samples")
    lines.append("")
    lines.append("Tier S: 55%+. Tier A: 52-55%. Tier B: 50-52%. Tier C: 48-50%. Tier D: below 48%. Win % is computed over decided games; draws are excluded.")
    lines.append("")
    lines.append("| Tier | Deck | Games | Win % | Meta share |")
    lines.append("|---|---|---:|---:|---:|")
    tiered = sorted(((d, deck_games[d], wr(d)) for d in big_decks), key=lambda x: -x[2])
    for d, g, w in tiered:
        if w >= 55:    t = "S"
        elif w >= 52:  t = "A"
        elif w >= 50:  t = "B"
        elif w >= 48:  t = "C"
        else:          t = "D"
        lines.append(f"| {t} | {d} | {g:,} | {w:.1f}% | {share(d):.1f}% |")
    lines.append("")

    # ── Most-played decks ────────────────────────────────────────────────
    lines.append("## Most-played decks")
    lines.append("")
    lines.append("| Deck | Games | Meta share | Win % |")
    lines.append("|---|---:|---:|---:|")
    for d, n in real_decks[:15]:
        lines.append(f"| {d} | {n:,} | {share(d):.1f}% | {wr(d):.1f}% |")
    lines.append("")

    # ── Biggest matchup edges (computed) ─────────────────────────────────
    lines.append("## Biggest matchup edges (30+ games)")
    lines.append("")
    lines.append("Head-to-head pairings with at least 30 decided games where one deck is clearly ahead. Draws excluded from the count.")
    lines.append("")
    picks = []
    pair_keys = set()
    for a in matchup_wins:
        for b in matchup_wins[a]:
            if a != b:
                pair_keys.add(frozenset((a, b)))
    for key in pair_keys:
        a, b = sorted(key)  # stable order for the symmetric pair
        if a.lower() in JUNK_DECKS or b.lower() in JUNK_DECKS:
            continue
        a_wins = matchup_wins[a].get(b, 0)
        b_wins = matchup_wins[b].get(a, 0)
        all_n = a_wins + b_wins
        if all_n < 30:
            continue
        a_wr = a_wins/all_n*100
        if abs(a_wr - 50) < 5:
            continue
        winner, loser, wr_pct, sample = (a, b, a_wr, all_n) if a_wr > 50 else (b, a, 100-a_wr, all_n)
        picks.append((winner, loser, wr_pct, sample))
    picks.sort(key=lambda x: -x[2])
    if picks:
        for w, l, wp, s in picks[:15]:
            lines.append(f"- **{w} beats {l}** — {wp:.1f}% over {s} games")
    else:
        lines.append("_No pairing has 30+ decided games with a clear edge yet._")
    lines.append("")

    # ── Undocumented high-volume decks (computed) ────────────────────────
    docs = documented_slugs()
    undoc = []
    for d, n in real_decks:
        if n < DOC_THRESHOLD:
            continue
        slug = NAME_TO_FILENAME.get(d, d)
        if slug not in docs:
            undoc.append((d, n))
    lines.append("## High-volume decks without an archetype file")
    lines.append("")
    if undoc:
        lines.append(f"Decks with {DOC_THRESHOLD}+ games and no `[C] <name>.md` in /Archetypes. Candidates for a write-up.")
        lines.append("")
        for d, n in undoc:
            lines.append(f"- **{d}** — {n:,} games, {wr(d):.1f}% win rate")
    else:
        lines.append(f"Every deck with {DOC_THRESHOLD}+ games already has an archetype file.")
    lines.append("")

    # ── Data caveats (method, not date-specific) ─────────────────────────
    lines.append("## Data caveats")
    lines.append("")
    lines.append("- Archetype names are whatever the tournament organizer entered into melee.gg. Single-word lines (\"Izzet\", \"Selesnya\") sit separate from their proper-named variants and are unclassified until folded in on a later pass.")
    lines.append("- Win % is wins / decided games; a draw counts for neither side. The per-archetype files also carry a match-win % that counts a draw as half a win.")
    lines.append("- Coverage is only as wide as what got scraped — a few large events can dominate the sample. Check the tournament count above before reading too much into any single number.")
    lines.append("")

    if FORMAT == "Standard" and set_name:
        out_name = f"[C] Meta Snapshot — {set_name}.md"
    else:
        out_name = f"[C] Meta Snapshot — {FORMAT}.md"
    out = os.path.join(PROJECT_DIR, out_name)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Meta snapshot written: {out}")
    return out

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("Loading...")
    rows = load_pairings()
    if not rows:
        print(f"No melee pairing files found in:\n  {DATA_DIR}")
        print("Run the melee scraper first (scrape.bat / scrape.sh, or "
              "mtg_fetch.py), then try again.")
        return
    os.makedirs(PROJECT_DIR, exist_ok=True)
    os.makedirs(ARCH_DIR, exist_ok=True)
    dg, dw, dl, dd, mw, tn = compute(rows)
    total = sum(dg.values()) // 2
    print(f"  {total:,} matches across {len(tn)} tournaments\n")

    print("Updating archetype files...")
    updated, unmatched = update_files(dg, dw, dl, dd, mw, total, len(tn))
    for slug, n in updated:
        print(f"  OK  {slug}  ({n} games)")
    if unmatched:
        print(f"\n  (no matching data for: {', '.join(unmatched)})")

    print("\nCreating Meta Snapshot...")
    build_meta(dg, dw, dl, dd, mw, tn, total)

if __name__ == "__main__":
    main()
