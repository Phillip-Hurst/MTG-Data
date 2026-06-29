#!/usr/bin/env python3
"""
melee_scraper.py — scrape round pairings and standings from melee.gg.

Intercepts melee.gg's API calls as round tabs are clicked to discover all
RoundIds, then uses page.evaluate() to fetch the full paginated data for
each round (GetRoundMatches + GetRoundStandings, length=1000).

Usage:
    python melee_scraper.py 393283 339227
    python melee_scraper.py 393283 --headed     # watch the browser
    python melee_scraper.py 393283 --debug      # print API activity
    python melee_scraper.py 393283 --dump-json  # save raw API responses

Output (every file tagged with the format slug, e.g. "standard"):
    melee_{fmt}_{id}_pairings.csv   — one row per match, per round
    melee_{fmt}_{id}_standings.csv  — one row per player (final standings)
    melee_{fmt}_all_pairings.csv    — combined across all tournaments
    melee_{fmt}_all_standings.csv   — combined across all tournaments
"""

import csv, sys, time, re, json, argparse, os, glob

# Windows consoles default to cp1252 and choke on the ✓/✗/→ and accented
# characters printed below. Force UTF-8 where the stream supports it. This runs
# before any print() and matters doubly because mtg_fetch.py launches this as a
# subprocess — an encode crash here would surface only as an opaque exit code.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from mtg_paths import resolve_data_dir, resolve_output_dir
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── config ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
# Format this run is scraping (mtg_fetch.py passes MTG_FORMAT via subprocess
# env). Every output file is tagged with the slug so formats never share a
# filename, even when they share a folder.
_MTG_FORMAT  = os.environ.get("MTG_FORMAT", "Standard").strip() or "Standard"
_FMT_SLUG    = _MTG_FORMAT.lower()
# Where scraped CSVs are read and written: MTG_DATA_DIR if set (the generated
# scrape.bat does this), else the per-format folder from mtg_workspace.json if
# setup.py built one, else the script folder. So a by-hand run still sorts into
# the right format folder.
DATA_DIR     = resolve_data_dir(_MTG_FORMAT, SCRIPT_DIR)
# Project folder (where [C] *.md notes live), resolved the same way.
PROJECT_DIR  = resolve_output_dir(_MTG_FORMAT, SCRIPT_DIR)
BASE_URL     = "https://melee.gg/Tournament/View/{}"
PLAYOFF_TABS = ["Quarterfinals", "Semifinals", "Finals"]
MAX_ROUNDS   = 20

# Player floor that lets an event onto melee in the first place (mirrors
# MIN_PLAYERS in mtg_fetch.py). Used only to flag whether a decklist-less
# event was big enough to be worth chasing lists for later.
MELEE_MIN_PLAYERS = 30

# Pagination: melee's DataTables endpoints page on start/length. A single
# length=1000 POST silently truncates any round bigger than that (it has
# happened on 1k+ player opens). Page through on recordsTotal instead.
PAGE_LEN     = 500
MAX_PAGES    = 50   # hard ceiling: 25k rows/round, can never spin forever

PAIRING_FIELDS = [
    "tournament_id", "tournament_name", "round", "table_num",
    "player1", "player1_deck", "player1_deck_url",
    "player2", "player2_deck", "player2_deck_url",
    "result", "winner",
]
STANDING_FIELDS = [
    "tournament_id", "tournament_name", "round",
    "rank", "player", "deck_name", "deck_url",
    "match_record", "game_record", "points",
    "omw_pct", "tgw_pct", "ogw_pct",
]


# ── cookie consent ─────────────────────────────────────────────────────────────

def dismiss_cookie_banner(page):
    for sel in [
        "button:has-text('Accept All')", "button:has-text('Accept all')",
        "button:has-text('Accept')",     "button:has-text('I Agree')",
        "button:has-text('Agree')",      "button:has-text('OK')",
        "[class*='consent'] button",     "[class*='cookie'] button",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                time.sleep(0.8)
                print("  Cookie banner dismissed.")
                return
        except Exception:
            continue


# ── tab helpers ────────────────────────────────────────────────────────────────

def visible_tabs(page):
    found = []
    for i in range(1, MAX_ROUNDS + 1):
        label = f"Round {i}"
        if page.locator(f"button:text-is('{label}'), a:text-is('{label}')").count() > 0:
            found.append(label)
    for label in PLAYOFF_TABS:
        if page.locator(f"button:text-is('{label}'), a:text-is('{label}')").count() > 0:
            found.append(label)
    return found


def click_tab(page, label):
    page.locator(f"button:text-is('{label}'), a:text-is('{label}')").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except PWTimeout:
        pass
    time.sleep(1.2)


# ── response capture ───────────────────────────────────────────────────────────

def setup_capture(page, debug=False):
    """Capture all JSON responses from melee.gg and POST bodies for standings."""
    responses = []
    request_bodies = {}   # url → post_data string

    # NOTE: these run as playwright event callbacks on the asyncio loop.
    # When a page navigates or closes mid-flight, resp.json() raises
    # asyncio.CancelledError, which subclasses BaseException (not Exception)
    # in Python 3.8+. A bare `except Exception` lets it escape and crash the
    # whole run. Catch BaseException here so a single in-flight response can
    # never take down the scrape.
    def on_request(req):
        if "melee.gg" in req.url:
            try:
                request_bodies[req.url] = req.post_data or ""
            except BaseException:
                pass

    def on_response(resp):
        if "melee.gg" not in resp.url:
            return
        try:
            ct = resp.headers.get("content-type", "")
            if "json" not in ct or resp.status != 200:
                return
            data = resp.json()
            responses.append({"url": resp.url, "data": data})
            if debug:
                print(f"    [net] {resp.url}")
        except BaseException:
            pass

    page.on("request",  on_request)
    page.on("response", on_response)
    return responses, request_bodies


# ── paginated API fetchers (run inside the page for auth/cookies) ──────────────

def _set_paging(body_template, start, length):
    """Return a DataTables POST body with start/length set to the given values.

    Reuses the captured request body so every column param melee expects is
    preserved; only the paging window changes. Falls back to a minimal body
    when nothing was captured.
    """
    if body_template:
        body = re.sub(r'length=\d+', f'length={length}', body_template)
        body = re.sub(r'start=\d+',  f'start={start}',   body)
        if 'length=' not in body:
            body += f'&length={length}'
        if 'start=' not in body:
            body += f'&start={start}'
        return body
    return f'draw=1&start={start}&length={length}'


def _paginate_post(page, url, body_template, debug=False, label=""):
    """POST to a melee DataTables endpoint, paging on recordsTotal.

    Loops start += PAGE_LEN until a short page comes back or recordsTotal is
    reached, capped at MAX_PAGES so a malformed response can't spin forever.
    Runs inside the page so melee's auth cookies ride along.
    """
    all_rows = []
    start = 0
    for _ in range(MAX_PAGES):
        body = _set_paging(body_template, start, PAGE_LEN)
        try:
            result = page.evaluate("""async ([url, body]) => {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
                    body: body
                });
                if (!resp.ok) return null;
                return await resp.json();
            }""", [url, body])
        except Exception as e:
            if debug:
                print(f"    {label} start={start} failed: {e}")
            break

        rows  = result.get("data", []) if result else []
        total = result.get("recordsTotal") if result else None
        if not rows:
            break
        all_rows.extend(rows)
        if debug:
            print(f"    {label} start={start} → {len(rows)} rows "
                  f"(have {len(all_rows)}/{total})")

        # Advance by rows actually returned (melee may cap length server-side),
        # and stop on recordsTotal — or a short page when no total is given.
        start += len(rows)
        try:
            total_int = int(total) if total is not None else None
        except (ValueError, TypeError):
            total_int = None
        if total_int is not None:
            if start >= total_int:
                break
        elif len(rows) < PAGE_LEN:
            break
    return all_rows


def fetch_round_matches(page, round_id, post_body_template, debug=False):
    """
    Call GetRoundMatches as a POST (DataTables), paging through every match.
    post_body_template is captured from a round tab click — the round_id is in
    the URL path, not the body, so the same template works for all rounds.
    Returns the raw data[] list across all pages.
    """
    url = f"https://melee.gg/Match/GetRoundMatches/{round_id}"
    return _paginate_post(page, url, post_body_template, debug=debug,
                          label=f"GetRoundMatches/{round_id}")


def fetch_round_standings(page, post_body_template, round_id, debug=False):
    """
    Replay the GetRoundStandings POST, paging through every player.
    post_body_template is the raw POST string from a captured request, which
    preserves all DataTables column params and the roundId; only the paging
    window is rewritten per page.
    """
    return _paginate_post(page, "https://melee.gg/Standing/GetRoundStandings",
                          post_body_template, debug=debug,
                          label=f"GetRoundStandings round={round_id}")


# ── JSON parsers (field names confirmed from api_dump.json) ────────────────────

def parse_match(item, tid, name):
    """
    Parse one match object from GetRoundMatches.

    Structure (confirmed):
      item.Competitors[0].Team.Players[0].DisplayName  → player1
      item.Competitors[0].Decklists[0].DecklistName    → deck1
      item.Competitors[0].Decklists[0].DecklistId      → deck1 uuid
      item.ResultString                                 → "NeilsonZhang won 2-1-0"
      item.TableNumber                                  → 1
      item.RoundName                                    → "Finals"
      item.RoundNumber                                  → 17
    """
    try:
        comps = item.get("Competitors", [])
        if len(comps) < 1:
            return None

        def get_player(comp):
            players = comp.get("Team", {}).get("Players", [])
            return players[0].get("DisplayName", "") if players else ""

        def get_deck_name(comp):
            decks = comp.get("Decklists", [])
            return decks[0].get("DecklistName", "") if decks else ""

        def get_deck_url(comp):
            decks = comp.get("Decklists", [])
            uid = decks[0].get("DecklistId", "") if decks else ""
            return f"https://melee.gg/Decklist/View/{uid}" if uid else ""

        p1 = get_player(comps[0]) if len(comps) > 0 else ""
        p2 = get_player(comps[1]) if len(comps) > 1 else ""
        d1 = get_deck_name(comps[0])
        d2 = get_deck_name(comps[1]) if len(comps) > 1 else ""
        u1 = get_deck_url(comps[0])
        u2 = get_deck_url(comps[1]) if len(comps) > 1 else ""

        result = item.get("ResultString", "")
        round_label = item.get("RoundName") or str(item.get("RoundNumber", "?"))
        table_num   = str(item.get("TableNumber", ""))

        # Winner from ResultString (starts with winning player's name)
        winner = ""
        r_lower = result.lower()
        if p1 and r_lower.startswith(p1.lower()):
            winner = p1
        elif p2 and r_lower.startswith(p2.lower()):
            winner = p2

        return {
            "tournament_id":    tid,
            "tournament_name":  name,
            "round":            round_label,
            "table_num":        table_num,
            "player1":          p1,
            "player1_deck":     d1,
            "player1_deck_url": u1,
            "player2":          p2,
            "player2_deck":     d2,
            "player2_deck_url": u2,
            "result":           result,
            "winner":           winner,
        }
    except Exception:
        return None


def parse_standing(item, tid, name):
    """
    Parse one standing object from GetRoundStandings.

    Structure (confirmed):
      item.Team.Players[0].DisplayName        → player
      item.Rank                               → rank
      item.Points                             → points
      item.MatchRecord                        → "14-3-0"
      item.GameRecord                         → "31-13-0"
      item.OpponentMatchWinPercentage         → OMW%
      item.TeamGameWinPercentage              → TGW%
      item.OpponentGameWinPercentage          → OGW%
      item.Decklists[0].DecklistName          → deck name
      item.Decklists[0].DecklistId            → deck uuid
      item.Round                              → "Finals"
      item.RoundId                            → 1381255
    """
    try:
        players = item.get("Team", {}).get("Players", [])
        player  = players[0].get("DisplayName", "") if players else ""

        decks     = item.get("Decklists", [])
        deck_name = decks[0].get("DecklistName", "") if decks else ""
        deck_id   = decks[0].get("DecklistId",   "") if decks else ""
        deck_url  = f"https://melee.gg/Decklist/View/{deck_id}" if deck_id else ""

        round_label = item.get("Round") or str(item.get("RoundNumber", "?"))

        return {
            "tournament_id":   tid,
            "tournament_name": name,
            "round":           round_label,
            "rank":            str(item.get("Rank",   "")),
            "player":          player,
            "deck_name":       deck_name,
            "deck_url":        deck_url,
            "match_record":    item.get("MatchRecord", ""),
            "game_record":     item.get("GameRecord",  ""),
            "points":          str(item.get("Points",  "")),
            "omw_pct":         str(item.get("OpponentMatchWinPercentage", "")),
            "tgw_pct":         str(item.get("TeamGameWinPercentage",      "")),
            "ogw_pct":         str(item.get("OpponentGameWinPercentage",  "")),
        }
    except Exception:
        return None


# ── main tournament scraper ────────────────────────────────────────────────────

def scrape_tournament(page, tid, debug=False, dump=False):
    url = BASE_URL.format(tid)
    print(f"\n→ {url}")

    responses, request_bodies = setup_capture(page, debug=debug)

    page.goto(url, wait_until="networkidle", timeout=45000)
    time.sleep(2)
    dismiss_cookie_banner(page)
    time.sleep(1)

    # Tournament name
    name = f"Tournament {tid}"
    for sel in ("h1", "h2", "h3"):
        for loc in page.locator(sel).all():
            try:
                text = loc.inner_text().strip()
                if text and "cookie" not in text.lower() and len(text) > 5:
                    name = text
                    break
            except Exception:
                continue
        if name != f"Tournament {tid}":
            break
    print(f"  Name: {name}")

    # Click all tabs to trigger API calls and discover RoundIds
    tabs = visible_tabs(page)
    if not tabs:
        print("  No tabs on first load — reloading...")
        page.reload(wait_until="networkidle")
        time.sleep(3)
        tabs = visible_tabs(page)
    if not tabs:
        print("  No tabs found.")
        return [], []

    print(f"  Tabs: {tabs}")
    print("  Clicking tabs to discover round IDs...")

    for tab in tabs:
        print(f"  [{tab}]", end=" ", flush=True)
        try:
            click_tab(page, tab)
            print("✓", end=" ", flush=True)
        except Exception as e:
            print(f"✗", end=" ", flush=True)
    print()

    if dump:
        path = os.path.join(DATA_DIR, f"melee_{_FMT_SLUG}_{tid}_api_dump.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(responses, f, indent=2)
        print(f"  Raw responses saved → {os.path.basename(path)}")

    # ── Extract RoundIds from captured standings responses ─────────────────────
    round_ids_seen = {}   # round_label → round_id
    standings_post_body = ""

    for item in responses:
        if "GetRoundStandings" in item["url"]:
            data_rows = item["data"].get("data", [])
            if data_rows:
                first = data_rows[0]
                rid   = first.get("RoundId")
                rlabel = first.get("Round") or str(first.get("RoundNumber", ""))
                if rid and rlabel and rlabel not in round_ids_seen:
                    round_ids_seen[rlabel] = rid
                    if debug:
                        print(f"  Discovered RoundId {rid} → {rlabel}")

    # Get the POST body template for standings (from first captured request)
    for url_key, body in request_bodies.items():
        if "GetRoundStandings" in url_key and body:
            standings_post_body = body
            break

    # Get the POST body template for matches (captured from Finals tab click)
    matches_post_body = ""
    for url_key, body in request_bodies.items():
        if "GetRoundMatches" in url_key and body:
            matches_post_body = body
            break

    if not round_ids_seen:
        print("  No round IDs discovered from standings responses.")
        return [], []

    print(f"  Discovered {len(round_ids_seen)} rounds: {list(round_ids_seen.keys())}")

    # ── Fetch complete data for every round ────────────────────────────────────
    all_pairings  = []
    all_standings = []

    for round_label, round_id in sorted(round_ids_seen.items(),
                                        key=lambda x: x[1]):  # sort by round_id
        print(f"  Fetching {round_label} (id={round_id})...", end=" ", flush=True)

        # Full pairings
        match_rows = fetch_round_matches(page, round_id, matches_post_body, debug=debug)
        for item in match_rows:
            r = parse_match(item, tid, name)
            if r:
                all_pairings.append(r)

        # Full standings
        standing_rows = fetch_round_standings(page, standings_post_body, round_id, debug=debug)
        for item in standing_rows:
            r = parse_standing(item, tid, name)
            if r:
                all_standings.append(r)

        print(f"matches={len(match_rows)}  standings={len(standing_rows)}")

    return all_pairings, all_standings


# ── output ─────────────────────────────────────────────────────────────────────

def write_csv(rows, path, fields):
    if not rows:
        print(f"  (no data for {path})")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓  {path}  ({len(rows)} rows)")


def rebuild_all_csv(pattern, out_path, fields, dedupe_keys):
    """
    Combine every per-tournament CSV matching `pattern` into `out_path`.
    Dedupes rows on the tuple of `dedupe_keys` so a tournament that gets
    re-scraped doesn't double up. This runs at the end of every scrape so
    melee_all_*.csv is rebuilt from per-tournament truth on disk — no more
    overwriting prior baselines.
    """
    paths = sorted(glob.glob(os.path.join(DATA_DIR, pattern)))
    # Exclude the combined file itself — otherwise every re-run doubles rows
    paths = [p for p in paths if "_all_" not in os.path.basename(p)]
    if not paths:
        print(f"  (no per-tournament files for {pattern} — skipping rebuild)")
        return

    seen = set()
    combined = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    key = tuple((row.get(k) or "").strip() for k in dedupe_keys)
                    if key in seen:
                        continue
                    seen.add(key)
                    combined.append(row)
        except Exception as e:
            print(f"  ! couldn't read {p}: {e}")
            continue

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(combined)
    print(f"  ✓  {out_path}  ({len(combined)} rows from {len(paths)} tournaments)")


def update_standings_only_bucket():
    """
    Some organizers post results to melee but never attach decklists (F2FTour
    is the recurring example). Those events carry real standings — finishing
    order, records, tiebreakers, the round-by-round match graph — but zero deck
    data, so they add nothing to the win-rate math and shouldn't be mistaken
    for a scrape failure.

    Scan every per-tournament standings CSV on disk, find the ones with players
    but no deck names anywhere, and keep a growing registry of them in
    standings_only_events.json. Driven from disk truth like rebuild_all_csv: an
    event that later gains decklists simply stops qualifying and drops out, but
    first_seen dates are preserved across runs. A human-readable mirror lands in
    the project folder as [C] Standings-Only Events.md.
    """
    today   = time.strftime("%Y-%m-%d")
    reg_path = os.path.join(DATA_DIR, "standings_only_events.json")
    try:
        with open(reg_path, encoding="utf-8") as f:
            prior = {e["tournament_id"]: e for e in json.load(f).get("events", [])}
    except (FileNotFoundError, ValueError, KeyError):
        prior = {}

    current = {}
    for p in sorted(glob.glob(os.path.join(DATA_DIR, f"melee_{_FMT_SLUG}_*_standings.csv"))):
        if "_all_" in os.path.basename(p):
            continue
        m = re.search(rf"melee_{re.escape(_FMT_SLUG)}_(\d+)_standings\.csv", os.path.basename(p))
        if not m:
            continue
        tid = m.group(1)
        try:
            with open(p, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except Exception as e:
            print(f"  ! standings-only scan couldn't read {p}: {e}")
            continue
        if not rows:
            continue
        players  = {r.get("player", "") for r in rows if r.get("player")}
        decks    = sum(1 for r in rows if (r.get("deck_name") or "").strip())
        if players and decks == 0:
            name = next((r.get("tournament_name", "") for r in rows
                         if r.get("tournament_name")), "")
            n = len(players)
            current[tid] = {
                "tournament_id":   tid,
                "tournament_name": name,
                "players":         n,
                "meets_threshold": n >= MELEE_MIN_PLAYERS,
                "first_seen":      prior.get(tid, {}).get("first_seen", today),
                "last_seen":       today,
            }

    bucket = sorted(current.values(),
                    key=lambda e: (not e["meets_threshold"], -e["players"]))
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump({"updated": today,
                   "min_players": MELEE_MIN_PLAYERS,
                   "events": bucket}, f, indent=2, ensure_ascii=False)
    print(f"  ✓  standings_only_events.json  ({len(bucket)} deck-less events; "
          f"{sum(1 for e in bucket if e['meets_threshold'])} at/over {MELEE_MIN_PLAYERS}p)")

    # Human-readable mirror in the project folder.
    worth = [e for e in bucket if e["meets_threshold"]]
    small = [e for e in bucket if not e["meets_threshold"]]
    lines = [
        "---", "author: claude", "type: note",
        "project: MTG Tournament Analysis Skill",
        f"updated: {today}", "tags: [mtg, scraper, coverage, standings-only]",
        "---", "",
        "# Standings-only events",
        "",
        "Events that posted results to melee.gg but never attached decklists. "
        "We have finishing order, match and game records, tiebreakers, and the "
        "round-by-round match graph for these. We do not have what anyone "
        "played, not even the archetype. They are correctly excluded from the "
        "win-rate math, not a scrape failure.",
        "",
        "Auto-maintained by melee_scraper.py on every run. An event drops off "
        "this list automatically if it later gains decklists. If we want the "
        f"archetypes, the lists have to come from another source.",
        "",
        f"## Worth chasing ({MELEE_MIN_PLAYERS}+ players)",
        "",
    ]
    if worth:
        lines += ["| Event | ID | Players | First seen |",
                  "|---|---|---:|---|"]
        lines += [f"| {e['tournament_name']} | {e['tournament_id']} | "
                  f"{e['players']} | {e['first_seen']} |" for e in worth]
    else:
        lines.append("_None right now._")
    lines += ["", "## Below threshold (noise)", ""]
    if small:
        lines += ["| Event | ID | Players | First seen |",
                  "|---|---|---:|---|"]
        lines += [f"| {e['tournament_name']} | {e['tournament_id']} | "
                  f"{e['players']} | {e['first_seen']} |" for e in small]
    else:
        lines.append("_None right now._")
    lines.append("")

    md_path = os.path.join(PROJECT_DIR, "[C] Standings-Only Events.md")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  ✓  {md_path}")
    except Exception as e:
        print(f"  ! couldn't write standings-only note: {e}")


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids",         nargs="+",        help="melee.gg tournament IDs")
    parser.add_argument("--debug",     action="store_true", help="Print API activity")
    parser.add_argument("--dump-json", action="store_true", help="Save raw API JSON")
    args = parser.parse_args()

    all_pairings  = []
    all_standings = []

    with sync_playwright() as pw:
        # melee.gg 403s headless browsers (2026-06-10) — must run headful Chrome.
        try:
            browser = pw.chromium.launch(channel="chrome", headless=False)
        except Exception:
            browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        for tid in args.ids:
            # One failed tournament must never abort the whole run. Catch
            # everything (including BaseException-derived errors like
            # CancelledError), log it, try to recover the page, and move on.
            # The per-tournament CSVs already written stay on disk, and the
            # rebuild step below still runs from disk truth.
            try:
                p, s = scrape_tournament(page, tid,
                                         debug=args.debug,
                                         dump=args.dump_json)
                all_pairings.extend(p)
                all_standings.extend(s)
                write_csv(p, os.path.join(DATA_DIR, f"melee_{_FMT_SLUG}_{tid}_pairings.csv"),  PAIRING_FIELDS)
                write_csv(s, os.path.join(DATA_DIR, f"melee_{_FMT_SLUG}_{tid}_standings.csv"), STANDING_FIELDS)
            except BaseException as e:
                print(f"  ! Error scraping tournament {tid}: {type(e).__name__}: {e}")
                print(f"    Skipping to next tournament — data already on disk is kept.")
                # If the page/browser died, stand up a fresh one so the rest of
                # the queue isn't lost to one bad event.
                try:
                    if page.is_closed():
                        page = ctx.new_page()
                except BaseException:
                    try:
                        ctx  = browser.new_context(viewport={"width": 1440, "height": 900})
                        page = ctx.new_page()
                    except BaseException:
                        print("    Browser unrecoverable — stopping scrape early; "
                              "will still rebuild combined CSVs from disk.")
                        break
                continue

        try:
            browser.close()
        except BaseException:
            pass

    # Rebuild the combined CSVs from EVERY per-tournament file on disk, not
    # just the ones we scraped this run. This preserves prior baselines instead
    # of overwriting them.
    # Every format tags its combined files, so two formats never collide even in
    # a shared folder. (Standard used to keep un-prefixed names; that shared
    # filename was the cross-contamination path, and it's gone.)
    _all_pairings  = os.path.join(DATA_DIR, f"melee_{_FMT_SLUG}_all_pairings.csv")
    _all_standings = os.path.join(DATA_DIR, f"melee_{_FMT_SLUG}_all_standings.csv")

    print(f"\nRebuilding combined CSVs from per-tournament files on disk...")
    # Glob is format-specific so one format's per-event files can never be folded
    # into another's combined CSV, even when the two share a folder.
    rebuild_all_csv(
        pattern=f"melee_{_FMT_SLUG}_*_pairings.csv",
        out_path=_all_pairings,
        fields=PAIRING_FIELDS,
        dedupe_keys=("tournament_id", "round", "table_num", "player1", "player2"),
    )
    rebuild_all_csv(
        pattern=f"melee_{_FMT_SLUG}_*_standings.csv",
        out_path=_all_standings,
        fields=STANDING_FIELDS,
        dedupe_keys=("tournament_id", "round", "player"),
    )

    # Refresh the standings-only bucket from disk truth (deck-less events).
    print(f"\nUpdating standings-only bucket...")
    update_standings_only_bucket()

    print(f"\nDone — this run added {len(all_pairings)} pairing rows, {len(all_standings)} standing rows")


if __name__ == "__main__":
    main()
