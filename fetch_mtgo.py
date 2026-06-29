#!/usr/bin/env python3
"""
fetch_mtgo.py — pull MTGO results from MTGO.com directly, with MTGGoldfish fallback.

The format defaults to Standard; change it in mtg_config.json or with --format.

Primary source: https://www.mtgo.com/en/mtgo/decklists
  Scrapes anything tagged with the target format (Challenges, League 5-0 dumps, etc.)

Fallback: MTGGoldfish tournament search (used if MTGO.com returns nothing)

Outputs (Standard keeps existing names for backward compat):
  mtgo_5-0_latest.json        — most recent 5-0 / league decks
  mtgo_challenge_latest.json  — most recent Standard Challenge results
  mtgo_deck_log.csv           — cumulative card/archetype tracking (appended)

Outputs (non-Standard, e.g. --format Modern):
  mtgo_modern_5-0_latest.json
  mtgo_modern_challenge_latest.json
  mtgo_modern_deck_log.csv

Usage:
  python fetch_mtgo.py                  # fetch latest data (format from mtg_config.json)
  python fetch_mtgo.py --format Modern  # override format for this run
  python fetch_mtgo.py --dry-run        # show URLs to fetch without writing
  python fetch_mtgo.py --since 2026-04-24  # limit to events after date
  python fetch_mtgo.py --goldfish       # force MTGGoldfish fallback only

Deps: playwright (already installed for melee_scraper)
"""

import json, csv, os, re, sys, argparse
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from mtg_paths import resolve_data_dir, resolve_output_dir

# Scheduled-task console is cp1252; unicode in prints can crash it.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
# Data written to MTG_DATA_DIR (defaults to the script folder so the flat
# single-format workflow is unchanged). setup.py sets it per format.
DATA_DIR     = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)
# Config is read from the data folder first, then the shipped copy.
CONFIG_PATH  = (os.path.join(DATA_DIR, "mtg_config.json")
                if os.path.exists(os.path.join(DATA_DIR, "mtg_config.json"))
                else os.path.join(SCRIPT_DIR, "mtg_config.json"))
OUT_5_0      = os.path.join(DATA_DIR, "mtgo_5-0_latest.json")
OUT_CHALL    = os.path.join(DATA_DIR, "mtgo_challenge_latest.json")
OUT_LOG      = os.path.join(DATA_DIR, "mtgo_deck_log.csv")
# Deck log note written next to the data by default.
# Set the MTG_OUTPUT_DIR environment variable to write it elsewhere
# (e.g. your Obsidian vault project folder).
_OUTPUT_DIR = os.environ.get("MTG_OUTPUT_DIR", DATA_DIR)
VAULT_NOTE  = os.path.join(_OUTPUT_DIR, "mtgo_deck_log.md")

# Primary: MTGO's own decklist site — format filter built into the URL.
MTGO_DECKLISTS_URL = "https://www.mtgo.com/decklists?filter=Standard"

# Fallback: MTGGoldfish, which only mirrors MTGO results. main() rebuilds both
# URLs from the chosen format so a non-Standard run can never pull Standard data.
GOLDFISH_EVENTS_URL = ("https://www.mtggoldfish.com/tournament_searches/create?utf8=%E2%9C%93"
                       "&tournament_type%5B%5D=magic_online&format%5B%5D=standard"
                       "&date_range=&commit=Search")
GOLDFISH_5_0_URL    = ("https://www.mtggoldfish.com/tournament_searches/create?utf8=%E2%9C%93"
                       "&tournament_type%5B%5D=magic_online&format%5B%5D=standard"
                       "&date_range=&tournament_name=league&commit=Search")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--since", default=None, help="YYYY-MM-DD cutoff date")
    p.add_argument("--goldfish", action="store_true", help="Skip MTGO.com and use MTGGoldfish only")
    p.add_argument("--debug-cards", action="store_true",
                   help="Dump raw innerHTML of the first .decklist element to debug_deck.html "
                        "so you can inspect the DOM and verify card selectors")
    p.add_argument("--format", default=None,
                   help="Format to scrape (e.g. Standard, Modern, Pioneer). "
                        "Overrides mtg_config.json.")
    return p.parse_args()


def load_config():
    """Load mtg_config.json. Returns dict with 'format' and 'weeks_window'."""
    defaults = {"format": "Standard", "weeks_window": 8}
    if not os.path.exists(CONFIG_PATH):
        return defaults
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        defaults.update({k: v for k, v in data.items() if not k.startswith("_")})
    except Exception:
        pass
    return defaults


# ─────────────────────────────────────────────
# PRIMARY SOURCE: MTGO.com
# ─────────────────────────────────────────────

def _name_to_slug(name):
    """Convert event name to MTGO URL slug. e.g. 'Standard Challenge 32' -> 'standard-challenge-32'"""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch_mtgo_site_events(page, since_date=None):
    """
    Scrape mtgo.com/decklists?filter=Standard for Standard events.

    With user-agent set, the listing page renders anchor tags directly:
      /decklist/standard-league-2026-05-0610660
      /decklist/standard-challenge-32-2026-05-0412841388
    Filter to Standard events, extract URL + date from anchor text.
    """
    print(f"Loading MTGO.com: {MTGO_DECKLISTS_URL}")
    try:
        page.goto(MTGO_DECKLISTS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("a[href*='/decklist/standard']", timeout=12000)
    except PWTimeout:
        print("  Timeout — will try DOM anyway")

    # Let any in-flight navigation settle before evaluate (race condition fix)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    page.wait_for_timeout(1500)

    # With UA set, Standard event anchors render as real links — grab them directly.
    # href format: /decklist/standard-league-2026-05-0610660 (date + event ID in slug)
    eval_script = """() => {
        var results = [];
        var links = document.querySelectorAll('a[href*="/decklist/standard"]');
        for (var i = 0; i < links.length; i++) {
            var href = links[i].getAttribute('href') || '';
            var text = (links[i].innerText || '').trim();
            results.push({href: href, text: text});
        }
        return results;
    }"""
    try:
        anchors = page.evaluate(eval_script)
    except Exception as e:
        print(f"  evaluate raced with navigation ({e}) — retrying after stabilization")
        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass
        anchors = page.evaluate(eval_script)

    print(f"  Standard anchor tags found: {len(anchors)}")
    for a in anchors[:6]:
        print(f"    {a['href']!r:55s} | {a['text'][:40]!r}")

    events = []
    seen_urls = set()

    for a in anchors:
        href = a["href"]
        text = a["text"]

        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        full_url = f"https://www.mtgo.com{href}" if href.startswith("/") else href

        # Name: first line of anchor text
        name = text.split("\n")[0].strip()
        if not name:
            continue

        # Date from URL slug — it's always YYYY-MM-DD embedded before the event ID
        date_str = ""
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", href)
        if dm:
            date_str = dm.group(1)

        # Filter by since_date
        if since_date and date_str:
            try:
                if datetime.strptime(date_str, "%Y-%m-%d") < since_date:
                    continue
            except ValueError:
                pass

        name_lower = name.lower()
        if "league" in name_lower:
            event_type = "5-0"
        elif "challenge" in name_lower or "qualifier" in name_lower or "showcase" in name_lower:
            event_type = "challenge"
        else:
            event_type = "other"

        events.append({
            "name": name,
            "url": full_url,
            "date": date_str,
            "event_type": event_type,
            "source": "mtgo.com",
        })

    print(f"  Found {len(events)} Standard events on MTGO.com")
    return events


def fetch_mtgo_site_decklists(page, event_url):
    """
    Scrape an individual MTGO.com decklist event page.

    MTGO event pages have a tabbed layout: Bracket / Decklists / Standings.
    The Decklists tab content is what we want — actual deck rows inside the
    decklist container. The prior selector ('.decklist-index li,
    .decklist-index-entry') was too broad and picked up the tab anchors
    themselves plus page-chrome links (Discord, Twitch, Mozilla footer).

    Returns list of {place, deck, player, url}.
    """
    print(f"  Loading: {event_url}")
    try:
        page.goto(event_url, wait_until="domcontentloaded", timeout=30000)
    except PWTimeout:
        print("    Timeout loading event page")
        return []

    # Let any in-flight navigation settle
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PWTimeout:
        pass
    page.wait_for_timeout(2000)

    # Diagnostic: show what the DOM contains after load
    dom_info = page.evaluate("""() => ({
        title: document.title,
        url: window.location.href,
        deckSections: document.querySelectorAll('[id^="deck_"]').length,
        decklistPlayers: document.querySelectorAll('.decklist-player').length,
        decklistEls: document.querySelectorAll('.decklist').length,
        bodySnippet: (document.body.innerText || '').slice(0, 120).replace(/\\n/g, ' ')
    })""")
    print(f"    DOM: sections={dom_info['deckSections']} players={dom_info['decklistPlayers']} "
          f"decklists={dom_info['decklistEls']} | {dom_info['bodySnippet'][:80]!r}")

    # If decklists didn't render, click the Decklists tab via JS and wait
    if dom_info['decklistPlayers'] == 0:
        try:
            page.evaluate("""() => {
                // Find and click a tab/link that reveals the decklist content
                const tabs = [...document.querySelectorAll('a, button')];
                const dlTab = tabs.find(el => /^decklists?$/i.test((el.innerText || '').trim()));
                if (dlTab) dlTab.click();
            }""")
            page.wait_for_timeout(3000)
        except Exception:
            pass

    # Wait for deck player rows to be attached (they may be in a hidden tab panel)
    try:
        page.wait_for_selector(
            ".decklist .decklist-player, [id^='deck_'] .decklist-player",
            timeout=30000,
            state="attached",
        )
    except PWTimeout:
        print("    Timeout waiting for deck rows — event may not be published yet")
        return []

    decks = page.evaluate(r"""() => {

        // ── Card parser ───────────────────────────────────────────────────────
        // Tries multiple strategies in order; returns {mainboard:{}, sideboard:{}}.
        // Called once per div.decklist element so card data travels with each deck.
        function parseCards(deckEl) {
            const main = {}, side = {};

            // Strategy 1: June 2026 layout (verified against live DOM 2026-06-13).
            // Each deck section is a <section class="decklist" id="deck_PLAYER">.
            // The "sort by type" tab pane has class decklist-sort-type.
            // Cards: .decklist-category-card > a.decklist-card-link, text = "N CardName".
            // Sideboard: a .decklist-category-list that also has class decklist-sideboard.
            const sortType = deckEl.querySelector('.decklist-sort-type');
            if (sortType) {
                const sideList = sortType.querySelector('.decklist-sideboard');
                let found = 0;
                for (const card of sortType.querySelectorAll('.decklist-category-card')) {
                    const link = card.querySelector('.decklist-card-link');
                    if (!link) continue;
                    const txt = (link.innerText || link.textContent || '').trim();
                    const m = txt.match(/^(\d+)\s+(.+)$/);
                    if (!m) continue;
                    const qty = parseInt(m[1]);
                    const name = m[2].trim();
                    if (!qty || !name || name.length > 80) continue;
                    const t = (sideList && sideList.contains(card)) ? side : main;
                    t[name] = (t[name] || 0) + qty;
                    found++;
                }
                if (found > 0) return { mainboard: main, sideboard: side };
            }

            // Strategy 2: pre-2026 structured elements — count + name in separate nodes.
            const cardEls = deckEl.querySelectorAll(
                '.deck-card, .card-row, .card-item, [class*="card-row"], [class*="deckcard"]'
            );
            let sideGroups = new Set();
            deckEl.querySelectorAll(
                '[data-group], .deck-group, .deck-section, [class*="deck-group"]'
            ).forEach(g => {
                const title = (
                    g.getAttribute('data-group') ||
                    (g.querySelector('.group-name, .section-header, [class*="group-title"]') || {}).innerText ||
                    ''
                ).toLowerCase();
                if (title.includes('sideboard') || title.includes('side')) sideGroups.add(g);
            });

            let found2 = 0;
            for (const c of cardEls) {
                const qEl = c.querySelector(
                    '.deck-card-count, .card-count, .quantity, .count, ' +
                    '[class*="count"], [class*="qty"], [class*="quantity"]'
                );
                const nEl = c.querySelector(
                    '.deck-card-name, .card-name, .name, ' +
                    '[class*="cardname"], [class*="card-name"], [class*="name"]'
                );
                if (!qEl || !nEl) continue;
                const qty = parseInt((qEl.innerText || qEl.textContent || '').trim()) || 0;
                const name = (nEl.innerText || nEl.textContent || '').trim();
                if (!qty || !name || name.length > 80) continue;

                let inSide = false;
                for (const sg of sideGroups) { if (sg.contains(c)) { inSide = true; break; } }
                const t = inSide ? side : main;
                t[name] = (t[name] || 0) + qty;
                found2++;
            }
            if (found2 > 0) return { mainboard: main, sideboard: side };

            // Strategy 3: innerText line-by-line fallback.
            // Sideboard section is delimited by a line reading exactly "Sideboard".
            const SECTION_HEADERS = new Set([
                'creatures', 'instants', 'sorceries', 'enchantments',
                'artifacts', 'planeswalkers', 'lands', 'battles',
                'spells', 'noncreature spells',
            ]);
            let inSide3 = false;
            const txt = (deckEl.innerText || deckEl.textContent || '');
            for (const raw of txt.split('\n')) {
                const line = raw.trim();
                if (!line) continue;
                if (/^sideboard$/i.test(line)) { inSide3 = true; continue; }
                if (SECTION_HEADERS.has(line.toLowerCase())) continue;
                const m2 = line.match(/^(\d+)\s+(.{2,60})$/);
                if (!m2) continue;
                const qty = parseInt(m2[1]);
                const name = m2[2].trim();
                if (/^(bracket|decklists|standings|pairings|overview|discord|twitch)$/i.test(name)) continue;
                const t = inSide3 ? side : main;
                t[name] = (t[name] || 0) + qty;
            }

            return { mainboard: main, sideboard: side };
        }

        // ── June 2026 inline layout ───────────────────────────────────────────
        // Every deck renders as div.decklist with .decklist-player and a.decklist-link.
        // MTGO pages don't carry archetype names in the DOM, so deck stays 'Unknown'
        // until classify_decks.py runs. The URL fragment is the dedup key.
        {
            const inline = document.querySelectorAll('.decklist');
            const results = [];
            for (const d of inline) {
                const playerEl = d.querySelector('.decklist-player');
                const linkEl = d.querySelector('a.decklist-link');
                if (!playerEl || !linkEl) continue;
                const raw = (playerEl.innerText || '').trim();
                // Challenges: "JTL005 (1ST PLACE)"; leagues: "ALEFUNES84 (5-0)"
                const m = raw.match(/^(.*?)\s*\((?:(\d+)(?:ST|ND|RD|TH)\s+PLACE|\d+-\d+)\)\s*$/i);
                const href = linkEl.getAttribute('href') || '';
                if (!href.startsWith('#')) continue;
                const cards = parseCards(d);
                results.push({
                    place: (m && m[2]) ? m[2] : String(results.length + 1),
                    deck: 'Unknown',
                    player: m ? m[1].trim() : raw,
                    url: location.origin + location.pathname + href,
                    mainboard: cards.mainboard,
                    sideboard: cards.sideboard,
                });
            }
            if (results.length > 0) return results;
        }

        // Pre-2026 layouts below, kept as fallback.
        // Known noise labels: section tabs and footer chrome.
        const NOISE = new Set([
            'bracket', 'decklists', 'standings', 'overview', 'pairings',
            'discord', 'twitch', 'mozilla', 'facebook', 'twitter', 'youtube',
            'instagram', 'tiktok', '', 'follow us', 'magic online'
        ]);

        // Prefer the most specific containers first; fall back progressively.
        const containerSelectors = [
            'ul.decklist-index',
            'ul.decklist-list',
            '.decklist-index',
            '.decklist',
        ];

        let entries = [];
        for (const sel of containerSelectors) {
            const containers = document.querySelectorAll(sel);
            for (const c of containers) {
                // Direct children only — avoids matching nav anchors that
                // happen to live elsewhere in the DOM.
                const kids = c.querySelectorAll(':scope > li, :scope > .decklist-list-item, :scope > article');
                kids.forEach(k => entries.push(k));
            }
            if (entries.length > 0) break;
        }

        // Last-ditch fallback: any element that wraps an /deck/ link
        if (entries.length === 0) {
            const deckLinks = document.querySelectorAll("a[href*='/deck/']");
            const wrappers = new Set();
            deckLinks.forEach(a => {
                let p = a.closest('li, article, .decklist-list-item, .deck');
                if (p) wrappers.add(p);
            });
            entries = Array.from(wrappers);
        }

        const results = [];
        for (let i = 0; i < entries.length; i++) {
            const el = entries[i];
            const text = (el.innerText || '').trim();
            const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

            // Reject pure-nav entries
            const firstLine = (lines[0] || '').toLowerCase();
            if (NOISE.has(firstLine)) continue;

            // Require a deck-detail link inside this entry
            const link = el.querySelector("a[href*='/deck/'], a[href*='show=deck']");
            if (!link) continue;

            const href = link.getAttribute('href') || '';
            // Reject obviously-broken or self-referential links
            if (href === '#' || href.startsWith('javascript:')) continue;

            const cards = parseCards(el);
            results.push({
                place: String(results.length + 1),
                deck: lines[0] || 'Unknown',
                player: lines[1] || '',
                url: href.startsWith('http') ? href : ('https://www.mtgo.com' + href),
                mainboard: cards.mainboard,
                sideboard: cards.sideboard,
            });
        }
        return results;
    }""")

    if not decks:
        print("    No deck rows matched — page structure may have changed; "
              "re-probe with --dry-run or inspect the event URL manually")
    return decks


def fetch_recent_events(page, fmt_slug="standard", since_date=None):
    """Get recent MTGO events for this format from MTGGoldfish."""
    print(f"Loading: {GOLDFISH_EVENTS_URL}")
    try:
        page.goto(GOLDFISH_EVENTS_URL, wait_until="domcontentloaded", timeout=30000)
    except PWTimeout:
        print("  Goldfish events page timed out — results may be empty")
        return []
    try:
        page.wait_for_selector("table.table tbody tr", timeout=12000)
    except PWTimeout:
        print("  Goldfish events table didn't appear — results may be empty")

    events = []
    try:
        rows = page.query_selector_all("table.table tbody tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 3:
                continue
            link = cells[0].query_selector("a")
            if not link:
                continue
            name = link.inner_text().strip()
            href = link.get_attribute("href") or ""
            date_text = cells[1].inner_text().strip() if len(cells) > 1 else ""

            # Parse date
            event_date = None
            for fmt in ["%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"]:
                try:
                    event_date = datetime.strptime(date_text, fmt)
                    break
                except ValueError:
                    pass

            if since_date and event_date and event_date < since_date:
                continue

            # Only this format's events
            if fmt_slug in name.lower() or fmt_slug in href.lower():
                events.append({
                    "name": name,
                    "url": f"https://www.mtggoldfish.com{href}" if href.startswith("/") else href,
                    "date": date_text
                })
    except Exception as e:
        print(f"  Error fetching events: {e}")

    print(f"  Found {len(events)} recent Standard events")
    return events[:20]  # cap at 20 most recent


def fetch_event_decklists(page, event_url):
    """Scrape deck names and player names from an event page."""
    print(f"  Loading: {event_url}")
    try:
        page.goto(event_url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector("table.table-tournament tbody tr", timeout=12000)
        except PWTimeout:
            pass  # continue and try to read whatever loaded

        decks = []
        deck_rows = page.query_selector_all("table.table-tournament tbody tr")
        for row in deck_rows:
            cells = row.query_selector_all("td")
            if len(cells) < 2:
                continue
            place_cell = cells[0].inner_text().strip()
            deck_link = cells[1].query_selector("a") if len(cells) > 1 else None
            player_cell = cells[2].inner_text().strip() if len(cells) > 2 else ""

            if not deck_link:
                continue

            deck_name = deck_link.inner_text().strip()
            deck_href = deck_link.get_attribute("href") or ""

            decks.append({
                "place": place_cell,
                "deck": deck_name,
                "player": player_cell,
                "url": f"https://www.mtggoldfish.com{deck_href}" if deck_href.startswith("/") else deck_href
            })

        return decks
    except Exception as e:
        print(f"    Error: {e}")
        return []


def fetch_5_0_dumps(page, fmt_slug="standard", since_date=None):
    """Check MTGGoldfish for the most recent MTGO 5-0 league decklists for this format."""
    search_url = GOLDFISH_5_0_URL
    print(f"Loading 5-0 dumps: {search_url}")

    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector("table.table tbody tr", timeout=12000)
        except PWTimeout:
            pass

        results = []
        rows = page.query_selector_all("table.table tbody tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 2:
                continue
            link = cells[0].query_selector("a")
            if not link:
                continue
            name = link.inner_text().strip()
            href = link.get_attribute("href") or ""
            date_text = cells[1].inner_text().strip() if len(cells) > 1 else ""

            if "league" in name.lower() or "5-0" in name.lower():
                results.append({
                    "name": name,
                    "url": f"https://www.mtggoldfish.com{href}" if href.startswith("/") else href,
                    "date": date_text
                })

        return results[:5]  # last 5 league dumps
    except Exception as e:
        print(f"  Error fetching 5-0 dumps: {e}")
        return []


def merge_event_store(filepath, new_events, days_window=45):
    """
    Accumulate events in filepath by URL key. New events replace existing ones
    with the same URL (so card data is always fresh), but a run that finds zero
    events does NOT wipe previously-stored data. Events older than days_window
    are pruned. Returns the merged list that was written.
    """
    existing = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                for evt in json.load(f):
                    if isinstance(evt, dict) and evt.get("url"):
                        existing[evt["url"]] = evt
        except Exception as e:
            print(f"  ! {os.path.basename(filepath)} unreadable ({e}); starting a fresh store.")

    # New events override (updated card data etc.)
    for evt in new_events:
        url = evt.get("url", "")
        if url:
            existing[url] = evt

    # Prune events older than days_window
    if days_window:
        cutoff = (datetime.now() - timedelta(days=days_window)).strftime("%Y-%m-%d")
        existing = {url: evt for url, evt in existing.items()
                    if evt.get("date", "9999-12-31") >= cutoff}

    merged = sorted(existing.values(), key=lambda e: e.get("date", ""), reverse=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    kept = len(existing)
    added = len(new_events)
    print(f"  Event store {os.path.basename(filepath)}: {added} new/updated, {kept} total kept")
    return merged


def update_deck_log(events_data, source_type):
    """Append new deck entries to the cumulative CSV log."""
    fieldnames = ["date", "event", "event_type", "place", "deck_name", "player", "url"]

    existing = set()
    if os.path.exists(OUT_LOG):
        with open(OUT_LOG, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing.add(row.get("url", ""))

    new_rows = []
    for event in events_data:
        for deck in event.get("decks", []):
            if deck["url"] not in existing:
                new_rows.append({
                    "date": event.get("date", ""),
                    "event": event.get("name", ""),
                    "event_type": source_type,
                    "place": deck.get("place", ""),
                    "deck_name": deck.get("deck", ""),
                    "player": deck.get("player", ""),
                    "url": deck.get("url", "")
                })
                existing.add(deck["url"])

    if new_rows:
        write_header = not os.path.exists(OUT_LOG)
        with open(OUT_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
        print(f"  Added {len(new_rows)} new deck entries to log")
    else:
        print("  No new deck entries")

    return new_rows


def generate_vault_note(all_events, new_decks, run_date):
    """Generate / append to the MTGO Deck Log vault note."""
    # Count archetype frequencies
    arch_counts = {}
    for deck in new_decks:
        name = deck.get("deck_name", "Unknown")
        arch_counts[name] = arch_counts.get(name, 0) + 1

    top_archetypes = sorted(arch_counts.items(), key=lambda x: -x[1])[:15]

    entry_lines = [
        f"\n## {run_date.strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"- Events processed: {len(all_events)}",
        f"- New deck entries: {len(new_decks)}",
        f"",
        f"### Archetypes seen:",
    ]
    for arch, count in top_archetypes:
        entry_lines.append(f"- {arch}: {count}")

    entry_lines.append("")
    entry_lines.append("### Notable new cards / tech (manual review needed):")
    entry_lines.append("- [ ] Review mtgo_deck_log.csv for new sideboard inclusions")
    entry_lines.append("")

    # Create or append to vault note
    if not os.path.exists(VAULT_NOTE):
        header = """---
author: claude
type: solution
project: MTG Tournament Analysis Skill
date: {}
tags: [mtg, mtgo, standard, decklists]
---

# MTGO deck log

Tracks MTGO 5-0 league results and Standard Challenge top finishers.
Updated by fetch_mtgo.py — run it manually, or on whatever schedule you set up.

Use this file to spot new tech, emerging archetypes, and cards being tested before they show up at RCs and PTs.

---
""".format(run_date.strftime('%Y-%m-%d'))
        with open(VAULT_NOTE, "w", encoding="utf-8") as f:
            f.write(header)

    with open(VAULT_NOTE, "a", encoding="utf-8") as f:
        f.write("\n".join(entry_lines))

    print(f"  Deck log updated: {VAULT_NOTE}")


def main():
    args = parse_args()

    # Resolve format from --format flag or mtg_config.json, then reassign the
    # module-level path + URL constants so downstream functions pick up the
    # right format without extra parameters.
    global DATA_DIR, OUT_5_0, OUT_CHALL, OUT_LOG, VAULT_NOTE, MTGO_DECKLISTS_URL
    global GOLDFISH_EVENTS_URL, GOLDFISH_5_0_URL

    config = load_config()
    fmt = (args.format or config.get("format", "Standard")).strip()
    fmt_slug = fmt.lower()

    # Route data + output to this format's folder (env var, else workspace
    # manifest, else script dir) so a by-hand run sorts correctly.
    DATA_DIR = resolve_data_dir(fmt, SCRIPT_DIR)
    out_dir  = resolve_output_dir(fmt, SCRIPT_DIR)

    # Standard keeps the original filenames; other formats are tagged so two
    # formats never collide in a shared folder.
    tag = "" if fmt_slug == "standard" else f"{fmt_slug}_"
    OUT_5_0    = os.path.join(DATA_DIR, f"mtgo_{tag}5-0_latest.json")
    OUT_CHALL  = os.path.join(DATA_DIR, f"mtgo_{tag}challenge_latest.json")
    OUT_LOG    = os.path.join(DATA_DIR, f"mtgo_{tag}deck_log.csv")
    VAULT_NOTE = os.path.join(out_dir, f"mtgo_{tag}deck_log.md")

    # MTGO.com is the primary source and is rich for every format. MTGGoldfish is
    # only a fallback mirror; build its URLs from the format so a non-Standard run
    # can never write Standard data.
    MTGO_DECKLISTS_URL = f"https://www.mtgo.com/decklists?filter={fmt}"
    GOLDFISH_EVENTS_URL = ("https://www.mtggoldfish.com/tournament_searches/create?utf8=%E2%9C%93"
                           f"&tournament_type%5B%5D=magic_online&format%5B%5D={fmt_slug}"
                           "&date_range=&commit=Search")
    GOLDFISH_5_0_URL = ("https://www.mtggoldfish.com/tournament_searches/create?utf8=%E2%9C%93"
                        f"&tournament_type%5B%5D=magic_online&format%5B%5D={fmt_slug}"
                        "&date_range=&tournament_name=league&commit=Search")

    since_date = None
    if args.since:
        since_date = datetime.strptime(args.since, "%Y-%m-%d")

    if args.dry_run:
        print(f"Dry run -- {fmt} -- URLs to fetch:")
        print(f"  Primary (MTGO.com):    {MTGO_DECKLISTS_URL}")
        print(f"  Fallback (Challenges): {GOLDFISH_EVENTS_URL}")
        print(f"  Fallback (5-0):        {GOLDFISH_5_0_URL}")
        return

    if args.debug_cards:
        # Navigate to the most recently seen challenge URL and dump the raw
        # innerHTML of the first .decklist element to debug_deck.html so you
        # can verify the card selector strategy without a full scrape run.
        debug_out = os.path.join(DATA_DIR, "debug_deck.html")
        print(f"debug-cards: loading {MTGO_DECKLISTS_URL} to find a recent event...")
        UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)   # headed so you can watch
            ctx = browser.new_context(user_agent=UA)
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            events = fetch_mtgo_site_events(page)
            if events:
                evt = events[0]
                print(f"debug-cards: loading first event: {evt['url']}")
                page.goto(evt["url"], wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                html = page.evaluate("""() => {
                    const el = document.querySelector('.decklist');
                    return el ? el.innerHTML : 'No .decklist element found on this page.';
                }""")
                with open(debug_out, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"debug-cards: wrote {debug_out}")
                print("Open debug_deck.html in a browser or text editor to inspect the card structure.")
            else:
                print("debug-cards: no events found on MTGO.com -- check the selector.")
            ctx.close()
            browser.close()
        return

    run_date = datetime.now()
    all_new_decks = []
    challenge_data = []
    dump_data = []

    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        use_goldfish = args.goldfish

        # ── PRIMARY: MTGO.com ──────────────────────────────────────────────
        if not use_goldfish:
            print(f"\n=== MTGO.com — {fmt} events ===")
            mtgo_events = fetch_mtgo_site_events(page, since_date)

            if not mtgo_events:
                print("  MTGO.com returned nothing — falling back to MTGGoldfish")
                use_goldfish = True
            else:
                for evt in mtgo_events[:20]:
                    decks = fetch_mtgo_site_decklists(page, evt["url"])
                    if not decks:
                        continue
                    evt["decks"] = decks
                    print(f"  {evt['name']}: {len(decks)} decks")

                    if evt["event_type"] in ("challenge", "other"):
                        challenge_data.append(evt)
                    else:
                        dump_data.append(evt)

        # ── FALLBACK: MTGGoldfish ──────────────────────────────────────────
        if use_goldfish:
            print(f"\n=== MTGGoldfish fallback — {fmt} Challenges ===")
            challenge_events = fetch_recent_events(page, fmt_slug, since_date)
            for evt in challenge_events[:10]:
                if "challenge" in evt["name"].lower():
                    decks = fetch_event_decklists(page, evt["url"])
                    if decks:
                        evt["decks"] = decks
                        evt["event_type"] = "challenge"
                        evt["source"] = "mtggoldfish"
                        challenge_data.append(evt)
                        print(f"  {evt['name']}: {len(decks)} decks")

            print("\n=== MTGGoldfish fallback — 5-0 dumps ===")
            dump_events = fetch_5_0_dumps(page, fmt_slug, since_date)
            for evt in dump_events[:5]:
                decks = fetch_event_decklists(page, evt["url"])
                if decks:
                    evt["decks"] = decks
                    evt["event_type"] = "5-0"
                    evt["source"] = "mtggoldfish"
                    dump_data.append(evt)
                    print(f"  {evt['name']}: {len(decks)} decks")

        ctx.close()
        browser.close()

    # ── Write outputs ──────────────────────────────────────────────────────
    new_challenge = update_deck_log(challenge_data, "challenge")
    all_new_decks.extend(new_challenge)
    merge_event_store(OUT_CHALL, challenge_data)

    new_dumps = update_deck_log(dump_data, "5-0")
    all_new_decks.extend(new_dumps)
    merge_event_store(OUT_5_0, dump_data)

    generate_vault_note(challenge_data + dump_data, all_new_decks, run_date)

    sources_used = set(e.get("source", "mtgo.com") for e in challenge_data + dump_data)
    print(f"\nDone. {len(all_new_decks)} new deck entries logged. Sources: {', '.join(sources_used)}")


if __name__ == "__main__":
    main()
