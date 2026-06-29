#!/usr/bin/env python3
"""
setup.py — one-time setup for the MTG Tournament Analysis skill.

Run this once from a terminal:

    python setup.py          (Windows)
    python3 setup.py         (macOS / Linux)

What it does, walking you through each step:
  1. Checks your Python version.
  2. Offers to install Playwright + Chromium (needed for melee.gg scraping).
  3. Lets you pick which MTG formats you want to track (Standard, Modern, ...).
  4. Builds a folder tree for each format, one place for raw scrapes and one
     for analysis output:

        <workspace>/
          Standard/
            scrapes/        <- melee_*.csv, mtgo_*.json, archetype_refs.json, ...
              baselines/
            insights/       <- [C] *.md notes, win-rate tracker, matchup matrix
              Archetypes/
              Snapshots/
              transcripts/
          Modern/
            scrapes/  ...
            insights/ ...

  5. Drops a per-format config and a ready-to-run scrape script into each
     folder, and writes a workspace manifest (mtg_workspace.json) at the root.
  6. Seeds each format's archetype baseline from mtgtop8 (optional, needs
     internet) so the classifier and the meta read have a starting point
     before your first local scrape.

The scrapers and analysis scripts read the MTG_DATA_DIR / MTG_OUTPUT_DIR
environment variables. The generated scrape scripts set those for you, so each
format scrapes into its own folder and nothing cross-contaminates.

The only network calls are the optional Playwright install and the optional
mtgtop8 baseline fetch in step 6 — both ask first.
"""

import json
import os
import subprocess
import sys
from datetime import date

# Windows consoles default to cp1252 and choke on the box-drawing characters
# below. Force UTF-8 where the stream supports it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

KNOWN_FORMATS = ["Standard", "Modern", "Pioneer", "Legacy", "Pauper", "Vintage"]

SCRAPE_SUBDIRS = ["baselines"]
INSIGHT_SUBDIRS = ["Archetypes", "Snapshots", "transcripts"]


def hr():
    print("-" * 64)


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans or (default or "")


def ask_yes_no(prompt, default=True):
    d = "Y/n" if default else "y/N"
    ans = ask(f"{prompt} ({d})")
    if not ans:
        return default
    return ans.lower().startswith("y")


def check_python():
    hr()
    print("Step 1 of 6  —  Python version")
    major, minor = sys.version_info[:2]
    print(f"  Found Python {major}.{minor} at {sys.executable}")
    if (major, minor) < (3, 10):
        print("  WARNING: this skill is built for Python 3.10 or newer.")
        print("  Some scripts may misbehave on older versions.")
        if not ask_yes_no("  Continue anyway?", default=False):
            sys.exit("Stopped. Install Python 3.10+ and run setup.py again.")
    else:
        print("  Good — that's new enough.")


def check_playwright():
    hr()
    print("Step 2 of 6  —  Playwright (melee.gg scraping)")
    print("  Melee.gg blocks plain HTTP, so its scraper drives a real browser.")
    print("  MTGO and magic.gg articles do NOT need this.")
    try:
        import playwright  # noqa: F401
        print("  Playwright is already installed.")
        return
    except ImportError:
        print("  Playwright is not installed yet.")

    if not ask_yes_no("  Install it now (pip install playwright + Chromium)?", default=True):
        print("  Skipped. You can install it later with:")
        print("      pip install playwright")
        print("      playwright install chromium")
        print("  Without it, melee.gg scraping won't run — MTGO still will.")
        return

    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("  Playwright + Chromium installed.")
    except subprocess.CalledProcessError as e:
        print(f"  Install failed ({e}). Run these two commands by hand:")
        print("      pip install playwright")
        print("      playwright install chromium")


def choose_workspace():
    hr()
    print("Step 3 of 6  —  Where to keep your data")
    default_root = os.path.join(os.path.dirname(SCRIPT_DIR), "MTG Skill")
    print("  Pick a folder to hold your scrapes and analysis. One subfolder")
    print("  per format will be created inside it.")
    root = ask("  Workspace folder", default=default_root)
    root = os.path.abspath(os.path.expanduser(root))
    os.makedirs(root, exist_ok=True)
    print(f"  Using: {root}")
    return root


def choose_formats():
    hr()
    print("Step 4 of 6  —  Which formats?")
    for i, fmt in enumerate(KNOWN_FORMATS, 1):
        print(f"    {i}. {fmt}")
    print("  Enter numbers or names, comma-separated (e.g. '1,2' or 'Standard, Modern').")
    while True:
        raw = ask("  Formats", default="Standard")
        picked = []
        for token in raw.replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(KNOWN_FORMATS):
                    picked.append(KNOWN_FORMATS[idx])
                else:
                    print(f"  '{token}' is out of range — skipping.")
            else:
                match = next((f for f in KNOWN_FORMATS if f.lower() == token.lower()), None)
                picked.append(match or token.title())
        # de-dupe, preserve order
        seen, ordered = set(), []
        for f in picked:
            if f not in seen:
                seen.add(f)
                ordered.append(f)
        if ordered:
            print(f"  Tracking: {', '.join(ordered)}")
            return ordered
        print("  Pick at least one format.")


def build_tree(root, fmt):
    fmt_dir = os.path.join(root, fmt)
    scrapes = os.path.join(fmt_dir, "scrapes")
    insights = os.path.join(fmt_dir, "insights")
    for sub in SCRAPE_SUBDIRS:
        os.makedirs(os.path.join(scrapes, sub), exist_ok=True)
    for sub in INSIGHT_SUBDIRS:
        os.makedirs(os.path.join(insights, sub), exist_ok=True)
    os.makedirs(scrapes, exist_ok=True)
    os.makedirs(insights, exist_ok=True)
    return fmt_dir, scrapes, insights


def write_format_config(scrapes, fmt):
    cfg_path = os.path.join(scrapes, "mtg_config.json")
    if os.path.exists(cfg_path):
        return  # don't clobber a config the user may have tuned
    cfg = {
        "_note": "Per-format scrape config. mtg_fetch.py and fetch_mtgo.py read "
                 "this when MTG_DATA_DIR points here.",
        "format": fmt,
        "weeks_window": 8,
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def copy_set_releases(scrapes):
    """Give each format its own copy of set_releases.json so set tracking is
    independent. Only meaningful for Standard, harmless elsewhere."""
    src = os.path.join(SCRIPT_DIR, "set_releases.json")
    dst = os.path.join(scrapes, "set_releases.json")
    if os.path.exists(src) and not os.path.exists(dst):
        with open(src, encoding="utf-8") as f:
            data = f.read()
        with open(dst, "w", encoding="utf-8") as f:
            f.write(data)


def write_runners(fmt_dir, scrapes, insights, fmt):
    """Write scrape scripts that set the env vars and call the skill scripts."""
    py = sys.executable
    skill = SCRIPT_DIR

    # Windows .bat
    bat = os.path.join(fmt_dir, "scrape.bat")
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("@echo off\r\n")
        f.write(f'set "MTG_DATA_DIR={scrapes}"\r\n')
        f.write(f'set "MTG_OUTPUT_DIR={insights}"\r\n')
        f.write(f'set "MTG_FORMAT={fmt}"\r\n')
        f.write("REM Extra flags after the script name (e.g. --since 2026-05-01,\r\n")
        f.write("REM --dry-run) are forwarded to BOTH fetchers below.\r\n")
        f.write("echo Scraping melee.gg for %MTG_FORMAT% ...\r\n")
        f.write(f'"{py}" "{os.path.join(skill, "mtg_fetch.py")}" --format {fmt} %*\r\n')
        f.write("echo Scraping MTGO for %MTG_FORMAT% ...\r\n")
        f.write(f'"{py}" "{os.path.join(skill, "fetch_mtgo.py")}" --format {fmt} %*\r\n')
        f.write("echo Done. Data is in %MTG_DATA_DIR%\r\n")
        f.write("pause\r\n")

    # macOS / Linux .sh
    sh = os.path.join(fmt_dir, "scrape.sh")
    with open(sh, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("set -e\n")
        f.write(f'export MTG_DATA_DIR="{scrapes}"\n')
        f.write(f'export MTG_OUTPUT_DIR="{insights}"\n')
        f.write(f'export MTG_FORMAT="{fmt}"\n')
        f.write('# Extra flags after the script name (e.g. --since 2026-05-01,\n')
        f.write('# --dry-run) are forwarded to BOTH fetchers below.\n')
        f.write(f'echo "Scraping melee.gg for $MTG_FORMAT ..."\n')
        f.write(f'"{py}" "{os.path.join(skill, "mtg_fetch.py")}" --format {fmt} "$@"\n')
        f.write(f'echo "Scraping MTGO for $MTG_FORMAT ..."\n')
        f.write(f'"{py}" "{os.path.join(skill, "fetch_mtgo.py")}" --format {fmt} "$@"\n')
        f.write(f'echo "Done. Data is in $MTG_DATA_DIR"\n')
    try:
        os.chmod(sh, 0o755)
    except OSError:
        pass


def write_manifest(root, formats_meta):
    manifest = {
        "_note": "Created by setup.py. Tells Cowork where each format's data "
                 "lives. Re-run setup.py to add formats.",
        "skill_dir": SCRIPT_DIR,
        "created": date.today().isoformat(),
        "formats": formats_meta,
    }
    path = os.path.join(root, "mtg_workspace.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return path


def seed_baselines(formats_meta):
    """Pull a starting metagame for each format from mtgtop8 (optional)."""
    hr()
    print("Step 6 of 6  —  Seed archetype baselines from mtgtop8")
    print("  mtgtop8 serves plain web pages, no browser needed, so we can pull a")
    print("  starting metagame for each format now: the archetypes, their share,")
    print("  and a modal decklist each. That gives the classifier something to")
    print("  match against and the meta read a reference point before you've")
    print("  scraped anything yourself.")

    # The builder's own list of supported formats is the source of truth.
    try:
        from build_mtgtop8_baseline import FORMAT_CODES
        supported = set(FORMAT_CODES)
    except Exception:
        supported = set(KNOWN_FORMATS)

    if not ask_yes_no("  Fetch baselines now (needs internet)?", default=True):
        print("  Skipped. Seed any format later with:")
        print("      python build_mtgtop8_baseline.py --format Standard")
        print("  (the format's scrape script sets MTG_DATA_DIR for you, or set it")
        print("   to that format's scrapes folder first).")
        return

    builder = os.path.join(SCRIPT_DIR, "build_mtgtop8_baseline.py")
    for fmt, meta in formats_meta.items():
        if fmt not in supported:
            print(f"  {fmt}: no mtgtop8 baseline for this format — skipping.")
            continue
        print(f"\n  {fmt}:")
        env = dict(os.environ, MTG_DATA_DIR=meta["scrapes"], MTG_FORMAT=fmt)
        try:
            subprocess.run([sys.executable, builder, "--format", fmt],
                           env=env, check=False)
        except Exception as e:
            print(f"  {fmt}: baseline step failed ({e}). Re-run it later.")


def main():
    print("=" * 64)
    print(" MTG Tournament Analysis — setup")
    print("=" * 64)

    check_python()
    check_playwright()
    root = choose_workspace()
    formats = choose_formats()

    hr()
    print("Step 5 of 6  —  Building your folders")
    formats_meta = {}
    for fmt in formats:
        fmt_dir, scrapes, insights = build_tree(root, fmt)
        write_format_config(scrapes, fmt)
        copy_set_releases(scrapes)
        write_runners(fmt_dir, scrapes, insights, fmt)
        formats_meta[fmt] = {
            "root": fmt_dir,
            "scrapes": scrapes,
            "insights": insights,
        }
        print(f"  {fmt}: ready  ({fmt_dir})")

    manifest_path = write_manifest(root, formats_meta)

    seed_baselines(formats_meta)

    hr()
    print("All set. Here's what to do next.")
    print("")
    runner = "scrape.bat" if os.name == "nt" else "./scrape.sh"
    first = formats[0]
    print(f"  1. Pull data for a format. Open its folder and run {runner}:")
    print(f"        {os.path.join(formats_meta[first]['root'], 'scrape.bat' if os.name=='nt' else 'scrape.sh')}")
    print("     (Run it whenever you want fresh results. It accumulates over time.)")
    print("")
    print("  2. In Cowork, ask about the meta. Your mtgtop8 baseline is already in")
    print("     place from step 6; the local scrape fills in melee matchup data.")
    print(f"     Point the skill at your data folder if it asks — the manifest lists every path:")
    print(f"        {manifest_path}")
    print("")
    print("  Re-run setup.py any time to add another format or refresh a baseline.")
    hr()


if __name__ == "__main__":
    main()
