#!/usr/bin/env python3
"""
mtg_fetch.py — find tournaments on melee.gg since the current era started.

The format defaults to Standard; change it in mtg_config.json or with --format.
The search window opens at the start of the current format era: the later of
the newest set release (set_releases.json) and the newest B&R announcement for
this format (bans.json). See mtg_era.py. Formats with neither fall back to
'weeks_window' weeks (default 8).

Usage:
    python mtg_fetch.py                       # Standard since the era started
    python mtg_fetch.py --format Modern       # Modern instead of Standard
    python mtg_fetch.py --fetch-sets          # update set_releases.json from WotC, then run
    python mtg_fetch.py --since 2026-03-07    # override window start manually
    python mtg_fetch.py --dry-run             # show what it found, skip scraping
    python mtg_fetch.py --debug               # print all network activity

Output:
    Same as melee_scraper.py — pairings + standings CSVs in this folder.

Deps:
    pip install playwright
    playwright install chromium
"""

import re
import sys
import os
import json
import subprocess
import argparse
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from mtg_paths import resolve_data_dir, resolve_output_dir
import mtg_era

# Scheduled-task console is cp1252; box-drawing chars in prints crash it.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── config ─────────────────────────────────────────────────────────────────────

MELEE_TOURNAMENTS  = "https://melee.gg/Tournament/Index"
WOTC_STANDARD_URL  = "https://magic.wizards.com/en/formats/standard"
MELEE_ID_RE        = re.compile(r'/Tournament/View/(\d+)', re.IGNORECASE)
SCRIPT_DIR         = os.path.dirname(os.path.abspath(__file__))
# Data is written to MTG_DATA_DIR (defaults to the script folder so the flat
# single-format workflow is unchanged). setup.py sets it per format, and it
# propagates to the melee_scraper.py subprocess via the inherited environment.
DATA_DIR           = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)


def _find_config(name):
    """Look in the data folder first, fall back to the shipped copy."""
    p = os.path.join(DATA_DIR, name)
    return p if os.path.exists(p) else os.path.join(SCRIPT_DIR, name)


SCRAPER            = os.path.join(SCRIPT_DIR, "melee_scraper.py")
SET_RELEASES_PATH  = _find_config("set_releases.json")
CONFIG_PATH        = _find_config("mtg_config.json")
MIN_PLAYERS        = 30    # 30+ players only

# Discovery pagination. melee's tournament list is a DataTables endpoint that
# only ships one page of rows per scroll. Relying on scroll-and-capture missed
# events buried below a wall of future SCG CON sub-events (e.g. Cincinnati RC
# 370745). Instead we replay melee's own list POST with our own paging window
# and walk the whole result set.
LIST_PAGE_LEN      = 100
# melee caps TournamentSearch at 25 rows/page server-side no matter the length
# we ask for, so the ceiling is in pages-of-25. 250 pages ≈ 6,250 events — a
# safety stop that real result sets (Standard ≈ 1,000) never reach.
LIST_MAX_PAGES     = 250

DATE_PATTERNS = [
    "%B %d, %Y",   # January 15, 2026
    "%b %d, %Y",   # Jan 15, 2026
    "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 with Z
    "%Y-%m-%dT%H:%M:%S",   # ISO 8601 no Z
    "%Y-%m-%d",    # 2026-01-15
    "%m/%d/%Y",    # 01/15/2026
    "%d %B %Y",    # 15 January 2026
]


# ── helpers ────────────────────────────────────────────────────────────────────

def parse_date(text):
    if not text:
        return None
    text = text.strip()
    # Match the literal patterns as written (no surgery on the format string).
    # DATE_PATTERNS already includes the ISO-with-Z and ISO-no-Z forms.
    for pat in DATE_PATTERNS:
        try:
            return datetime.strptime(text, pat)
        except ValueError:
            continue
    # Final fallback: ISO 8601 with a trailing Z or numeric offset.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def within_weeks(date_val, weeks):
    if date_val is None:
        return True   # can't parse → keep it
    cutoff = datetime.now() - timedelta(weeks=weeks)
    if isinstance(date_val, str):
        dt = parse_date(date_val)
        if dt is None:
            return True
        return dt >= cutoff
    return date_val >= cutoff


# ── set release window ─────────────────────────────────────────────────────────

def load_set_releases():
    """Load set_releases.json. Returns list of {name, code, release_date} dicts."""
    if not os.path.exists(SET_RELEASES_PATH):
        return []
    with open(SET_RELEASES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("sets", [])


def save_set_releases(sets):
    existing = {}
    if os.path.exists(SET_RELEASES_PATH):
        with open(SET_RELEASES_PATH, encoding="utf-8") as f:
            existing = json.load(f)
    existing["sets"] = sets
    with open(SET_RELEASES_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


def load_config():
    """Load mtg_config.json. Returns dict with 'format' and 'weeks_window'."""
    defaults = {"format": "Standard", "weeks_window": 8}
    if not os.path.exists(CONFIG_PATH):
        return defaults
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        defaults.update({k: v for k, v in data.items() if not k.startswith("_")})
    except Exception as e:
        print(f"  ! couldn't read {os.path.basename(CONFIG_PATH)} ({e}); using "
              f"defaults (format={defaults['format']}, weeks_window={defaults['weeks_window']}).")
    return defaults


def get_window_start(since_override=None, fmt="Standard", weeks_window=8):
    """
    Returns the datetime to use as the search window start.

    The window opens at the start of the current format era, which mtg_era.py
    resolves as whichever came last: the newest set release (set_releases.json)
    or the newest B&R announcement for this format (bans.json). A ban ends an
    era the same way a rotation does — the decks that defined the old numbers
    are gone, so the results before it belong to a different format.

    Priority:
      1. --since override from CLI
      2. Era start: latest set release or latest ban, whichever is later
      3. Non-Standard with no recent ban: weeks_window weeks ago
      4. Fallback: 12 weeks ago
    """
    era = mtg_era.resolve_era(fmt=fmt, weeks_window=weeks_window,
                              since_override=since_override)
    print(f"  Window start: {era['start_str']} — {era['label']}")
    print(f"  Why: {era['reason']}")
    if era["anchor"] == "ban":
        print(f"  Pre-{era['start_str']} results are a different era. Archive them "
              f"with: python archive_era.py")
    elif era["anchor"] == "fallback":
        print(f"  Run: python mtg_fetch.py --fetch-sets   to auto-populate from WotC.")
    return era["start"]


def fetch_set_dates_from_wotc(page):
    """
    Scrape magic.wizards.com/en/formats/standard to find currently legal sets
    and their release dates. Updates set_releases.json.
    """
    print(f"\nFetching set list from {WOTC_STANDARD_URL} ...")
    try:
        page.goto(WOTC_STANDARD_URL, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        content = page.inner_text("body")
    except Exception as e:
        print(f"  Failed to load WotC page: {e}")
        return

    # Look for set name + date patterns like "Set Name — Released Month DD, YYYY"
    # or "Set Name (released Month YYYY)"
    pattern = re.compile(
        r'([A-Z][A-Za-z0-9 \':]+?)'         # set name
        r'[\s\-–—]+(?:Released?|released?)[\s:]+' # "Released"
        r'(\w+ \d{1,2},? \d{4})',            # date
        re.IGNORECASE
    )
    matches = pattern.findall(content)

    # Also look for lines that pair a set name with a year (broader fallback)
    date_near_name = re.compile(
        r'([A-Z][A-Za-z \']{4,40})\s*[\|\-–—:]\s*(\w+ \d{1,2},? \d{4})',
        re.IGNORECASE
    )
    matches += date_near_name.findall(content)

    existing = {s["name"]: s for s in load_set_releases()}
    new_count = 0

    for raw_name, raw_date in matches:
        name = raw_name.strip().rstrip("-–— ")
        dt = parse_date(raw_date.strip())
        if not dt or len(name) < 4:
            continue
        if name not in existing:
            existing[name] = {"name": name, "code": "", "release_date": dt.strftime("%Y-%m-%d")}
            print(f"  + {name}  ({dt.strftime('%Y-%m-%d')})")
            new_count += 1
        else:
            # Update date if it was blank
            if not existing[name].get("release_date"):
                existing[name]["release_date"] = dt.strftime("%Y-%m-%d")
                print(f"  ~ {name}  ({dt.strftime('%Y-%m-%d')})  [date updated]")
                new_count += 1

    if new_count:
        save_set_releases(list(existing.values()))
        print(f"  set_releases.json updated ({new_count} change(s)).")
    else:
        print(f"  No new dates found — you may need to add them manually to set_releases.json.")
        print(f"  Page text excerpt:")
        print(f"    {content[:600]}")


# ── API response capture ───────────────────────────────────────────────────────

def setup_capture(page, debug=False, dump=False):
    captured_json = []
    captured_all  = []   # for --dump: all responses regardless of type
    request_bodies = {}   # url → POST body, so we can replay the list endpoint

    # melee's tab/scroll clicks fire DataTables POSTs. We need both the URL and
    # the exact POST body to replay the list call with our own paging window.
    # These callbacks run on playwright's event loop; a navigation mid-flight
    # can raise CancelledError (a BaseException), so catch BaseException.
    def on_request(req):
        if "melee.gg" in req.url:
            try:
                request_bodies[req.url] = req.post_data or ""
            except BaseException:
                pass

    def on_response(resp):
        if "melee.gg" not in resp.url:
            return
        ct = resp.headers.get("content-type", "")
        status = resp.status
        if dump:
            captured_all.append({"url": resp.url, "status": status, "ct": ct})
        if debug:
            print(f"    [net] {status} {ct[:30]:30s}  {resp.url}")
        try:
            if "json" in ct and status == 200:
                data = resp.json()
                captured_json.append({"url": resp.url, "data": data})
        except BaseException:
            pass

    page.on("request",  on_request)
    page.on("response", on_response)
    return captured_json, captured_all, request_bodies


# ── paginated list-endpoint replay ──────────────────────────────────────────────

ID_KEYS   = ("ID", "Id", "id", "TournamentId", "tournamentId")
NAME_KEYS = ("Name", "TournamentName", "name")


def _looks_like_tournament_rows(data):
    """True if a captured JSON response is the tournament list DataTables payload.

    Wants a dict carrying recordsTotal/recordsFiltered and a non-empty `data`
    list whose rows have an ID or Name field. Returns (rows, records_total) or
    (None, None).
    """
    if not isinstance(data, dict):
        return None, None
    if "recordsTotal" not in data and "recordsFiltered" not in data:
        return None, None
    rows = data.get("data", data.get("Data", []))
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None, None
    first = rows[0]
    has_id   = any(k in first and first[k] for k in ID_KEYS)
    has_name = any(k in first for k in NAME_KEYS)
    if not (has_id or has_name):
        return None, None
    total = data.get("recordsTotal", data.get("recordsFiltered"))
    return rows, total


def _identify_list_endpoint(captured, request_bodies, debug=False):
    """Find melee's tournament-list endpoint and its POST body from captures.

    Picks the candidate with the largest recordsTotal (the real list, not a
    small lookup). Returns (url, body_template) or (None, None).
    """
    best = None   # (records_total, url)
    for item in captured:
        rows, total = _looks_like_tournament_rows(item["data"])
        if rows is None:
            continue
        try:
            t = int(total) if total is not None else len(rows)
        except (ValueError, TypeError):
            t = len(rows)
        if best is None or t > best[0]:
            best = (t, item["url"])

    if not best:
        return None, None

    url = best[1]
    body = request_bodies.get(url, "")
    # The response URL may carry a query string the request didn't (or vice
    # versa). If no exact body match, fall back to any captured body whose URL
    # shares the same path.
    if not body:
        path = url.split("?", 1)[0]
        for req_url, req_body in request_bodies.items():
            if req_body and req_url.split("?", 1)[0] == path:
                body = req_body
                break
    if debug:
        print(f"  List endpoint: {url}  (recordsTotal≈{best[0]}, "
              f"body {'captured' if body else 'MISSING'})")
    return url, body


def _paginate_list_api(page, url, body_template, debug=False):
    """Replay the list POST with our own paging window, walking every page.

    Returns a flat list of row dicts across all pages. Capped at LIST_MAX_PAGES
    so a bad recordsTotal can't loop forever.
    """
    def set_paging(body, start, length):
        if body:
            b = re.sub(r'length=\d+', f'length={length}', body)
            b = re.sub(r'start=\d+',  f'start={start}',   b)
            if 'length=' not in b:
                b += f'&length={length}'
            if 'start=' not in b:
                b += f'&start={start}'
            return b
        return f'draw=1&start={start}&length={length}'

    all_rows = []
    start = 0
    for _ in range(LIST_MAX_PAGES):
        body = set_paging(body_template, start, LIST_PAGE_LEN)
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
                print(f"    list page start={start} failed: {e}")
            break

        rows = []
        total = None
        if isinstance(result, dict):
            rows = result.get("data", result.get("Data", []))
            total = result.get("recordsTotal", result.get("recordsFiltered"))
        if not rows:
            break
        all_rows.extend(rows)
        if debug:
            print(f"    list start={start} → {len(rows)} rows (have {len(all_rows)}/{total})")

        # Advance by the rows actually returned, not the page size we asked for —
        # melee may cap length server-side, and over-advancing would skip events.
        start += len(rows)
        try:
            total_int = int(total) if total is not None else None
        except (ValueError, TypeError):
            total_int = None
        if total_int is not None:
            if start >= total_int:
                break
        elif len(rows) < LIST_PAGE_LEN:
            # No usable total: stop only when a short page comes back.
            break
    return all_rows


# ── tournament discovery ───────────────────────────────────────────────────────

def find_tournaments(page, since_dt, fmt="Standard", debug=False, dump=False):
    cutoff = since_dt
    captured, captured_all, request_bodies = setup_capture(page, debug=debug, dump=dump)
    found = []
    seen = set()
    undated = []

    # ── Step 1: load with URL filter params ───────────────────────────────────
    # Order descending by start date so recently-played events surface first.
    # NOTE: melee.gg ignores `&statuses=Ended` in the URL, so we filter on the
    # Status column in _extract_from_dom and date in _extract_from_api.
    filter_url = (
        f"{MELEE_TOURNAMENTS}"
        f"?ordering=-StartDate"
        f"&filters={fmt}%2CMagicTheGathering"
        f"&statuses=Ended"
        f"&mode=Table"
    )
    print(f"Loading: {filter_url}")
    try:
        page.goto(filter_url, wait_until="networkidle", timeout=30000)
        time.sleep(3)
    except PWTimeout:
        print("  Timed out — continuing with what loaded.")

    # ── Step 1.5: cookie wall + Results tab (melee.gg, June 2026 layout) ──────
    # The consent banner blocks the table, and the &statuses=Ended URL param
    # is ignored — the "Results" tab is the real Ended filter.
    for sel in ["button:has-text('Necessary cookies only')",
                "a:has-text('Necessary cookies only')",
                "button:has-text('Accept all cookies')"]:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible(timeout=1500):
                btn.click()
                time.sleep(1)
                if debug:
                    print(f"  Dismissed cookie banner via: {sel}")
                break
        except Exception:
            continue
    for sel in ["a:has-text('Results')", "button:has-text('Results')",
                "[role='tab']:has-text('Results')"]:
        try:
            tab = page.locator(sel).first
            if tab.count() > 0 and tab.is_visible(timeout=1500):
                tab.click()
                time.sleep(2.5)
                if debug:
                    print(f"  Clicked Results tab via: {sel}")
                break
        except Exception:
            continue

    # ── Step 2: try UI filter interactions ────────────────────────────────────
    # Click filter buttons / dropdowns to trigger the API call
    _try_ui_filters(page, fmt=fmt, debug=debug)
    time.sleep(2)

    # Scroll a few times to trigger the first DataTables POST so we can capture
    # its URL + body. We no longer lean on scrolling to surface deep events —
    # Step 3 pages the endpoint directly — but one scroll burst guarantees the
    # list call fires.
    for _ in range(5):
        page.keyboard.press("End")
        time.sleep(1.0)

    # ── Step 3: page the list endpoint directly ───────────────────────────────
    # Replay melee's own list POST with our paging window so events buried below
    # future SCG CON sub-events are still walked. Feeds the same parser via a
    # synthetic captured-style entry.
    list_url, list_body = _identify_list_endpoint(captured, request_bodies, debug=debug)
    if list_url:
        paged_rows = _paginate_list_api(page, list_url, list_body, debug=debug)
        if paged_rows:
            print(f"  Paged list endpoint → {len(paged_rows)} tournament rows")
            found, seen = _extract_from_api(
                [{"url": list_url, "data": {"data": paged_rows}}],
                None, cutoff, found, seen, debug=debug,
                target_fmt=fmt, undated=undated,
            )
    else:
        print("  Could not identify the list endpoint from captures — "
              "relying on captured responses + DOM fallback.")

    # ── Step 3b: also parse whatever responses were captured during load ──────
    found, seen = _extract_from_api(captured, None, cutoff, found, seen, debug=debug,
                                    target_fmt=fmt, undated=undated)

    # ── Step 4: fallback — extract tournament IDs from DOM links ──────────────
    if not found:
        print("  No API responses captured — falling back to DOM link extraction...")
        found, seen = _extract_from_dom(page, cutoff, found, seen, debug=debug, undated=undated)

    if dump:
        import json as _json
        net_path = os.path.join(DATA_DIR, "melee_tournaments_network.json")
        with open(net_path, "w", encoding="utf-8") as f:
            _json.dump(captured_all, f, indent=2)
        html_path = os.path.join(DATA_DIR, "melee_tournaments_page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"  Saved: melee_tournaments_network.json ({len(captured_all)} requests)")
        print(f"  Saved: melee_tournaments_page.html")

    if undated:
        print(f"\n  Skipped {len(undated)} event(s) melee returned with no usable date:")
        for tid, name in undated[:12]:
            print(f"    {tid}  {name[:52]}")
        if len(undated) > 12:
            print(f"    ...and {len(undated) - 12} more")
        print("  An event we can't date can't be placed in an era. To pull one anyway:")
        print(f"    python melee_scraper.py {' '.join(t for t, _ in undated[:6])}")
        print("  then re-run validate_events.py before trusting it.")

    return found


def _try_ui_filters(page, fmt="Standard", debug=False):
    """Try to interact with filter UI to trigger an API call with the chosen format filter."""
    selectors = [
        "input[placeholder*='format' i]",
        "input[placeholder*='game' i]",
        "input[placeholder*='search' i]",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=1000):
                loc.fill(fmt)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                time.sleep(1.5)
                if debug:
                    print(f"  Filled filter input: {sel}")
                break
        except Exception:
            continue

    # Try clicking a "Standard" option if a dropdown opened
    for txt in [fmt, f"Magic: The Gathering {fmt}"]:
        try:
            btn = page.locator(f"li:has-text('{txt}'), option:has-text('{txt}'), button:has-text('{txt}')").first
            if btn.count() > 0 and btn.is_visible(timeout=1000):
                btn.click()
                time.sleep(1)
                if debug:
                    print(f"  Clicked: {txt}")
                break
        except Exception:
            continue


def _extract_from_api(captured, weeks, cutoff, found, seen, debug=False,
                      target_fmt="Standard", undated=None):
    """Parse tournament data from captured JSON API responses.

    target_fmt gates the format column. undated collects (id, name) for rows
    melee returned with no usable date — those are skipped, not admitted, and
    reported at the end of the run so they can be scraped by hand if wanted.
    """
    if undated is None:
        undated = []
    for item in captured:
        url  = item["url"]
        data = item["data"]

        # The tournament list endpoint returns a DataTables-style response
        # OR a plain list — handle both
        rows = []
        if isinstance(data, dict):
            rows = data.get("data", data.get("Data", data.get("tournaments", [])))
        elif isinstance(data, list):
            rows = data

        for row in rows:
            if not isinstance(row, dict):
                continue

            # Extract tournament ID — check common field names
            tid = None
            for key in ["ID", "Id", "id", "TournamentId", "tournamentId"]:
                if key in row and row[key]:
                    tid = str(row[key])
                    break

            # Also check if any value looks like a link
            if not tid:
                for val in row.values():
                    if isinstance(val, str):
                        m = MELEE_ID_RE.search(val)
                        if m:
                            tid = m.group(1)
                            break

            if not tid or tid in seen:
                continue

            # Format filter — must name the target format.
            #
            # This used to accept any value containing "magic", which passes
            # every MTG event of every format because GameDescription is
            # "MagicTheGathering" on all of them. That's how a Modern team
            # trios event ended up in the Standard pool on 2026-08-27.
            # GameDescription is the game, not the format, so read the format
            # fields only and ignore it.
            fmt_val = str(row.get("Format", row.get("format",
                         row.get("FormatDescription", "")))).strip().lower()
            if fmt_val and target_fmt.lower() not in fmt_val:
                if debug:
                    print(f"  [api] skip {tid} — format={fmt_val!r}, want {target_fmt!r}")
                continue

            # Status filter — must be Ended. melee.gg returns Status like
            # "Ended", "InProgress", "RegistrationOpen", etc.
            status = str(row.get("Status", row.get("status", row.get("StatusDescription", ""))))
            if status and not re.search(r"end(ed)?|complet|finish", status, re.IGNORECASE):
                if debug:
                    print(f"  [api] skip {tid} — status={status!r}")
                continue

            # Date filter — fail closed.
            #
            # Every one of these filters used to sit behind `if date_val`, so a
            # row melee returned with no usable date skipped the window check
            # entirely and was admitted. On 2026-08-27 melee returned no date
            # for all 35 rows, and pre-ban events sailed past a window start
            # the run had just printed. An event we can't date is an event we
            # can't place in an era, so it doesn't go in the pool.
            date_val = (row.get("StartDate") or row.get("Date") or
                        row.get("DateCreated") or row.get("date", ""))
            dt = parse_date(str(date_val)) if date_val else None
            if dt is None:
                undated.append((tid, str(row.get("Name") or row.get("TournamentName") or "")))
                if debug:
                    print(f"  [api] skip {tid} — no parseable date (raw={date_val!r})")
                continue
            if dt > datetime.now():
                continue
            if weeks is not None and not within_weeks(str(date_val), weeks):
                continue
            if cutoff and dt < cutoff:
                if debug:
                    print(f"  [api] skip {tid} — {dt.date()} is before window start {cutoff.date()}")
                continue

            # Player count filter
            players = row.get("Players", row.get("PlayerCount", row.get("players", 0)))
            try:
                if players and int(players) < MIN_PLAYERS:
                    continue
            except (ValueError, TypeError):
                pass

            name = (row.get("Name") or row.get("TournamentName") or
                    row.get("name", f"Tournament {tid}"))
            seen.add(tid)
            found.append((tid, str(name), str(date_val)))
            if debug:
                print(f"  [api] {tid}  —  {name[:60]}")

    return found, seen


def _extract_from_dom(page, cutoff, found, seen, debug=False, undated=None):
    """
    Extract tournament IDs from the melee.gg table.
    Each row: Date | Name (link) | Game | Organizer | Status | Reg Type | Entry Fee | Players | Tags

    The Status column is the source of truth — only "Ended" events have rounds
    to scrape. melee.gg ignores the &statuses=Ended URL parameter, so we filter
    here instead. Future-dated and in-progress events are dropped.
    """
    if undated is None:
        undated = []
    try:
        links = page.locator("a[href*='/Tournament/View/']").all()
    except Exception:
        return found, seen

    # Recognized status values on melee.gg
    ENDED_PATTERN     = re.compile(r'\b(Ended|Completed|Finished)\b', re.IGNORECASE)
    NON_ENDED_PATTERN = re.compile(
        r'\b(Registration|Open|Closed|In Progress|Running|Started|'
        r'Cancelled|Canceled|Upcoming|Scheduled|Draft)\b',
        re.IGNORECASE,
    )

    for link in links:
        try:
            href = link.get_attribute("href") or ""
            m = MELEE_ID_RE.search(href)
            if not m:
                continue
            tid = m.group(1)
            if tid in seen:
                continue

            name = link.inner_text().strip() or f"Tournament {tid}"

            # Get the table row for date, status, and player count
            try:
                row = link.locator("xpath=ancestor::tr[1]").first
                row_text = row.inner_text() if row.count() > 0 else ""
            except Exception:
                row_text = ""

            # ── Status filter (primary gate) ─────────────────────────────────
            # If we can find a status value, require it to be Ended.
            # If we find a non-Ended status, drop it.
            has_ended     = bool(ENDED_PATTERN.search(row_text))
            has_non_ended = bool(NON_ENDED_PATTERN.search(row_text))
            if has_non_ended and not has_ended:
                if debug:
                    print(f"  [dom] skip {tid} — status not Ended  {name[:40]}")
                continue

            # Date filter — look for MM/DD/YYYY pattern (melee.gg table format)
            date_matches = re.findall(
                r'\b\d{2}/\d{2}/\d{4}\b'
                r'|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b',
                row_text, re.IGNORECASE
            )
            # Fail closed, same as the API path: a row whose date we can't read
            # can't be placed in an era, so it doesn't go in the pool.
            parsed = [p for p in (parse_date(d) for d in date_matches) if p]
            if not parsed:
                undated.append((tid, name[:60]))
                if debug:
                    print(f"  [dom] skip {tid} — no parseable date  {name[:40]}")
                continue
            if all(p > datetime.now() for p in parsed):
                if debug:
                    print(f"  [dom] skip {tid} — all dates in future  {name[:40]}")
                continue
            if cutoff and all(p < cutoff for p in parsed):
                if debug:
                    print(f"  [dom] skip {tid} — before cutoff  {name[:40]}")
                continue

            # Player count filter — look for a standalone number in the Players column.
            # Strip the date column(s) first so a 4-digit year can't be misread as a
            # player count (the bug that let future-year rows slip past the gate).
            scan_text = row_text
            for d in date_matches:
                scan_text = scan_text.replace(d, " ")
            player_nums = re.findall(r'\b(\d{2,4})\b', scan_text)
            if player_nums:
                max_players = max(int(p) for p in player_nums)
                if max_players < MIN_PLAYERS:
                    if debug:
                        print(f"  [dom] skip {tid} — players={max_players} < {MIN_PLAYERS}  {name[:40]}")
                    continue

            seen.add(tid)
            found.append((tid, name[:60], date_matches[0] if date_matches else "unknown"))
            print(f"  [dom] {tid}  —  {name[:55]}")

        except Exception:
            continue

    return found, seen


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Find Standard tournaments on melee.gg and scrape them."
    )
    parser.add_argument("--since",       default=None,
                        help="Override window start date (YYYY-MM-DD). Default: latest set release.")
    parser.add_argument("--fetch-sets",  action="store_true",
                        help="Update set_releases.json from WotC Standard page, then run")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Print found IDs but do not run the scraper")
    parser.add_argument("--debug",       action="store_true",
                        help="Print API network activity")
    parser.add_argument("--format",      default=None,
                        help="Format to scrape (e.g. Standard, Modern, Pioneer). "
                             "Overrides mtg_config.json.")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip the post-scrape event check. Not recommended.")
    args = parser.parse_args()

    config = load_config()
    fmt = (args.format or config.get("format", "Standard")).strip()
    weeks_window = config.get("weeks_window", 8)

    print(f"\nSearching melee.gg for {fmt} tournaments...\n")

    since_dt = get_window_start(since_override=args.since, fmt=fmt, weeks_window=weeks_window)

    with sync_playwright() as pw:
        # melee.gg's bot protection 403s every headless mode (probed 2026-06-10);
        # only real headful Chrome gets through. Spoofed UA removed for the same
        # reason — a mismatched fingerprint makes the block more likely.
        try:
            browser = pw.chromium.launch(channel="chrome", headless=False)
        except Exception:
            browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        if args.fetch_sets:
            fetch_set_dates_from_wotc(page)
            since_dt = get_window_start(since_override=args.since, fmt=fmt, weeks_window=weeks_window)

        results = find_tournaments(page, since_dt, fmt=fmt, debug=args.debug)

        browser.close()

    print(f"\n{'─' * 50}")
    print(f"Tournaments found: {len(results)}")
    for tid, name, date in results:
        print(f"  {tid}  {date:>14}  —  {name[:50]}")
    print(f"{'─' * 50}\n")

    if not results:
        print("Nothing found. Try:")
        print("  python mtg_fetch.py --debug              # print network activity")
        print("  python mtg_fetch.py --since 2026-01-01   # wider window")
        print("  python melee_scraper.py <id>             # scrape a specific event")
        sys.exit(1)

    if args.dry_run:
        ids_str = " ".join(tid for tid, _, __ in results)
        print(f"--dry-run. To scrape manually:\n  python melee_scraper.py {ids_str}")
        sys.exit(0)

    ids = [tid for tid, _, __ in results]
    print(f"Running melee_scraper.py with {len(ids)} tournament(s)...\n")
    env = os.environ.copy()
    env["MTG_FORMAT"] = fmt
    # Route the scraper's output to this format's folder. resolve_* returns the
    # env var if already set (the generated scrape.bat path), else the per-format
    # folder from mtg_workspace.json, else the script dir — so a by-hand run still
    # sorts into the right place.
    env["MTG_DATA_DIR"] = resolve_data_dir(fmt, SCRIPT_DIR)
    env["MTG_OUTPUT_DIR"] = resolve_output_dir(fmt, SCRIPT_DIR)
    result = subprocess.run(
        [sys.executable, SCRAPER] + ids,
        cwd=SCRIPT_DIR,
        env=env,
    )

    if result.returncode != 0:
        print("\nScraper hit errors — check output above.")
        sys.exit(result.returncode)

    print(f"\nDone. Combined data is in melee_{fmt.lower()}_all_pairings.csv "
          f"(in {env['MTG_DATA_DIR']}).")

    if args.no_validate:
        print("\n--no-validate: skipping the event check. The pool may contain "
              "off-format or pre-era events.")
        return

    # ── Validate before anything downstream reads this ────────────────────────
    # The window filters above trust melee's metadata. This pass trusts the
    # cards instead, and quarantines anything that doesn't belong. Exit code 2
    # means it removed something, which is a normal outcome, not a failure.
    print(f"\n{'─' * 50}")
    print("Validating scraped events...")
    validator = os.path.join(SCRIPT_DIR, "validate_events.py")
    if not os.path.isfile(validator):
        print("  validate_events.py not found — skipping. Off-format and "
              "pre-era events will NOT be caught.")
        return
    vres = subprocess.run(
        [sys.executable, validator, "--format", fmt],
        cwd=SCRIPT_DIR,
        env=env,
    )
    if vres.returncode == 2:
        print("\nSome events were quarantined. The combined CSVs have been "
              "rewritten without them; originals are in *.raw.csv.")
    elif vres.returncode not in (0, 2):
        print("\nValidation could not run. Treat the combined CSVs as unverified "
              "until it does.")
        sys.exit(vres.returncode)

    # ── Reapply human deck-label rulings ──────────────────────────────────────
    # A scrape refetches decklists and overwrites their archetype with whatever
    # the classifier says, which used to silently undo every correction made by
    # hand. The overrides file survives that; this puts it back.
    corrections = os.path.join(SCRIPT_DIR, "apply_corrections.py")
    if os.path.isfile(corrections):
        print(f"\n{'─' * 50}")
        print("Reapplying deck-label corrections...")
        subprocess.run([sys.executable, corrections, "--format", fmt, "--reapply"],
                       cwd=SCRIPT_DIR, env=env)

    # ── Audit the references ──────────────────────────────────────────────────
    # References are what every live deck gets matched against, so a bad one
    # renames real decks quietly. Reporting only: a finding here is for a human
    # to resolve, not something to fix mid-run.
    auditor = os.path.join(SCRIPT_DIR, "audit_refs.py")
    if os.path.isfile(auditor):
        print(f"\n{'─' * 50}")
        subprocess.run([sys.executable, auditor, "--format", fmt],
                       cwd=SCRIPT_DIR, env=env)


if __name__ == "__main__":
    main()
