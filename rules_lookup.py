#!/usr/bin/env python3
"""Look rules up in the current Comprehensive Rules, by number or by keyword.

The point of this script is that it quotes the real document. A rules answer
recited from memory is confidently wrong roughly as often as it is right, and the
CR is revised with every set, so "I remember rule 603.10" is not an answer.

Downloads the current CR text file from magic.wizards.com and caches it next to
the scripts. Re-downloads when the cached copy is older than CACHE_DAYS or when
the rules page points at a newer dated file.

Stdlib only, same as mtg_era.py and build_mtgtop8_baseline.py.

Usage:
    python rules_lookup.py 117.3b            # one rule, verbatim
    python rules_lookup.py 704               # a whole section
    python rules_lookup.py --search "split second"
    python rules_lookup.py --search "legend rule" --context 2
    python rules_lookup.py --glossary "deathtouch"
    python rules_lookup.py --refresh         # force a re-download
    python rules_lookup.py --version         # what's cached and how old
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import urllib.parse
import urllib.request

RULES_PAGE = "https://magic.wizards.com/en/rules"
USER_AGENT = "mtg-data rules_lookup (https://github.com/Phillip-Hurst/MTG-Data)"
CACHE_DAYS = 14
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(SCRIPT_DIR, "comp_rules_cache.txt")
STAMP = os.path.join(SCRIPT_DIR, "comp_rules_cache.version")

# A rule number: 117, 117.3, 117.3b. Section headings are bare integers.
RULE_RE = re.compile(r"^(\d{3}(?:\.\d+[a-z]?)?)\.?\s")


def _get(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def find_current_txt_url() -> str:
    """Scrape the rules page for the current dated .txt link.

    The filename carries a date and changes with every CR revision, so hardcoding
    it guarantees a stale answer within a couple of months.
    """
    html = _get(RULES_PAGE, timeout=30)
    hits = re.findall(r'href="([^"]*MagicCompRules[^"]*\.txt)"', html, re.I)
    if not hits:
        raise SystemExit(
            "Could not find a MagicCompRules .txt link on " + RULES_PAGE +
            "\nThe page layout may have changed. Check it by hand and open an issue."
        )
    url = hits[0]
    if url.startswith("//"):
        url = "https:" + url
    # The published filename contains a space; requests need it encoded.
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, urllib.parse.quote(parts.path), parts.query, "")
    )


def cache_age_days() -> float | None:
    if not os.path.exists(CACHE):
        return None
    age = dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(CACHE))
    return age.total_seconds() / 86400


def cached_version() -> str:
    if os.path.exists(STAMP):
        return open(STAMP, encoding="utf-8").read().strip()
    return "unknown"


def download(force: bool = False) -> str:
    """Return the CR text, downloading it if the cache is missing or stale."""
    age = cache_age_days()
    # A cache with no version stamp can't report what it is, so it doesn't count
    # as fresh. Otherwise `--version` says "unknown" forever and the whole point
    # of quoting a dated document is gone.
    if (not force and age is not None and age < CACHE_DAYS
            and cached_version() != "unknown"):
        return open(CACHE, encoding="utf-8").read()

    try:
        url = find_current_txt_url()
    except Exception as exc:                      # network down, page moved
        if os.path.exists(CACHE):
            print(f"! could not reach the rules page ({exc}).", file=sys.stderr)
            print(f"! using the cached copy, {age:.0f} days old, "
                  f"version {cached_version()}.", file=sys.stderr)
            return open(CACHE, encoding="utf-8").read()
        raise SystemExit(f"No cached rules and could not reach {RULES_PAGE}: {exc}")

    version = os.path.basename(urllib.parse.unquote(urllib.parse.urlsplit(url).path))
    if not force and version == cached_version() and os.path.exists(CACHE):
        os.utime(CACHE, None)                     # same file; reset the clock
        return open(CACHE, encoding="utf-8").read()

    print(f"downloading {version} ...", file=sys.stderr)
    text = _get(url)
    with open(CACHE, "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(STAMP, "w", encoding="utf-8") as fh:
        fh.write(version)
    print(f"cached {len(text):,} characters as {os.path.basename(CACHE)}",
          file=sys.stderr)
    return text


def rule_lines(text: str) -> list[tuple[str, str]]:
    """Every numbered rule line, as (number, full line)."""
    out = []
    for line in text.splitlines():
        m = RULE_RE.match(line.strip())
        if m:
            out.append((m.group(1), line.strip()))
    return out


def show_rule(text: str, number: str) -> int:
    """Print a rule and everything nested beneath it."""
    number = number.rstrip(".")
    rules = rule_lines(text)
    hits = [(n, l) for n, l in rules
            if n == number or n.startswith(number + ".") or
            (re.fullmatch(r"\d+\.\d+", number) and re.fullmatch(
                re.escape(number) + r"[a-z]", n))]
    if not hits:
        print(f"No rule {number} in {cached_version()}.")
        print("Rule numbers look like 117, 117.3, or 117.3b. "
              "Try --search for a keyword instead.")
        return 1
    seen = set()
    for n, line in hits:
        if n in seen:
            continue
        seen.add(n)
        print(line)
        print()
    print(f"-- {len(seen)} rule(s) from {cached_version()}", file=sys.stderr)
    return 0


def search(text: str, term: str, context: int = 0, limit: int = 40) -> int:
    rules = rule_lines(text)
    pat = re.compile(re.escape(term), re.I)
    hits = [i for i, (_, line) in enumerate(rules) if pat.search(line)]
    if not hits:
        print(f'Nothing matching "{term}" in {cached_version()}.')
        return 1
    for i in hits[:limit]:
        lo, hi = max(0, i - context), min(len(rules), i + context + 1)
        for j in range(lo, hi):
            marker = ">" if j == i else " "
            print(f"{marker} {rules[j][1]}")
        print()
    shown = min(len(hits), limit)
    print(f"-- {shown} of {len(hits)} match(es) for \"{term}\" in {cached_version()}",
          file=sys.stderr)
    if len(hits) > limit:
        print("-- narrow the term, or raise --limit", file=sys.stderr)
    return 0


def glossary(text: str, term: str) -> int:
    """The Glossary is the last section, entries as 'Term\\n definition'."""
    idx = text.rfind("\nGlossary\n")
    if idx == -1:
        print("Could not locate the Glossary section.", file=sys.stderr)
        return 1
    body = text[idx:]
    lines = body.splitlines()
    pat = re.compile(r"^" + re.escape(term) + r"\b", re.I)
    found = False
    for i, line in enumerate(lines):
        if pat.match(line.strip()) and line.strip():
            found = True
            print(line.strip())
            for j in range(i + 1, min(i + 12, len(lines))):
                nxt = lines[j]
                if not nxt.strip():
                    break
                print("   " + nxt.strip())
            print()
    if not found:
        print(f'No glossary entry starting with "{term}" in {cached_version()}.')
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Quote the current Comprehensive Rules, by number or keyword.")
    ap.add_argument("rule", nargs="?", help="rule number, e.g. 117.3b or 704")
    ap.add_argument("--search", metavar="TERM", help="keyword search across rule text")
    ap.add_argument("--glossary", metavar="TERM", help="look a term up in the Glossary")
    ap.add_argument("--context", type=int, default=0,
                    help="rules to show either side of a search hit")
    ap.add_argument("--limit", type=int, default=40, help="max search hits to print")
    ap.add_argument("--refresh", action="store_true", help="force a re-download")
    ap.add_argument("--version", action="store_true",
                    help="report the cached CR version and its age")
    args = ap.parse_args()

    if args.version:
        age = cache_age_days()
        if age is None:
            print("No cached rules yet. Run any lookup, or --refresh, to fetch them.")
            return 0
        print(f"cached: {cached_version()}  ({age:.1f} days old, "
              f"refreshes after {CACHE_DAYS})")
        return 0

    text = download(force=args.refresh)

    if args.glossary:
        return glossary(text, args.glossary)
    if args.search:
        return search(text, args.search, context=args.context, limit=args.limit)
    if args.rule:
        return show_rule(text, args.rule)

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
