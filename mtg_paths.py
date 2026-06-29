"""
Resolve where a format's scraped data and analysis output live.

Order of precedence:
  1. MTG_DATA_DIR / MTG_OUTPUT_DIR environment variables. The generated
     scrape.bat / scrape.sh set these, so an explicit choice always wins.
  2. An mtg_workspace.json manifest (written by setup.py), found by searching up
     from the current directory and from the calling script's directory. This
     routes each format to its own scrapes/insights folder, so even a fetch run
     by hand sorts into the right format folder instead of dumping next to the
     scripts.
  3. Fall back to the script's own folder (the flat, no-setup workflow).

Keeping this in one place means mtg_fetch, fetch_mtgo and melee_scraper all
agree on where a format's data belongs.
"""
import json
import os


def _find_workspace(start_dirs):
    """Walk up from each start dir looking for an mtg_workspace.json."""
    seen = set()
    for start in start_dirs:
        d = os.path.abspath(start)
        while d not in seen:
            seen.add(d)
            cand = os.path.join(d, "mtg_workspace.json")
            if os.path.isfile(cand):
                return cand
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def _format_meta(fmt, script_dir):
    cand = _find_workspace([os.getcwd(), script_dir])
    if not cand:
        return None
    try:
        with open(cand, encoding="utf-8") as f:
            formats = json.load(f).get("formats", {})
    except (OSError, ValueError):
        return None
    for name, meta in formats.items():
        if name.lower() == fmt.lower():
            return meta
    return None


def resolve_data_dir(fmt, script_dir):
    """Folder to read and write scraped CSVs for this format."""
    env = os.environ.get("MTG_DATA_DIR")
    if env:
        return env
    meta = _format_meta(fmt, script_dir)
    if meta and meta.get("scrapes"):
        return meta["scrapes"]
    return script_dir


def resolve_output_dir(fmt, script_dir):
    """Folder to write analysis notes ([C] *.md) for this format."""
    env = os.environ.get("MTG_OUTPUT_DIR")
    if env:
        return env
    meta = _format_meta(fmt, script_dir)
    if meta and meta.get("insights"):
        return meta["insights"]
    return script_dir
