"""
Where everything lives: the checkout, its shipped config, and each format's
scraped data and analysis output.

Three fixed locations, derived from this file's place in the checkout:

    ROOT_DIR    the checkout root. With nothing configured, scraped data and
                analysis notes land here, and .gitignore keeps them out of git.
    CONFIG_DIR  config/, the versioned reference data: set releases, the ban
                list, the archetype name vocabulary, the play pattern registry.
                These are reviewed like code because every number depends on them.
    SRC_DIR     src/, so a subprocess can import mtg_data without an install.

A format's data and output folders resolve in this order:
  1. MTG_DATA_DIR / MTG_OUTPUT_DIR environment variables. The generated
     scrape.bat / scrape.sh set these, so an explicit choice always wins.
  2. An mtg_workspace.json manifest (written by scripts/setup_workspace.py),
     found by searching up from the current directory and from ROOT_DIR. This
     routes each format to its own scrapes/insights folder, so even a fetch run
     by hand sorts into the right format folder.
  3. ROOT_DIR (the flat, no-setup workflow).

Keeping this in one place means every stage agrees on where a format's data
belongs.
"""
import json
import os

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.dirname(PACKAGE_DIR)
ROOT_DIR = os.path.dirname(SRC_DIR)
CONFIG_DIR = os.path.join(ROOT_DIR, "config")


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


def _format_meta(fmt, base_dir):
    cand = _find_workspace([os.getcwd(), base_dir])
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


def resolve_data_dir(fmt, base_dir=ROOT_DIR):
    """Folder to read and write scraped CSVs for this format."""
    env = os.environ.get("MTG_DATA_DIR")
    if env:
        return env
    meta = _format_meta(fmt, base_dir)
    if meta and meta.get("scrapes"):
        return meta["scrapes"]
    return base_dir


def resolve_output_dir(fmt, base_dir=ROOT_DIR):
    """Folder to write analysis notes ([C] *.md) for this format."""
    env = os.environ.get("MTG_OUTPUT_DIR")
    if env:
        return env
    meta = _format_meta(fmt, base_dir)
    if meta and meta.get("insights"):
        return meta["insights"]
    return base_dir


def config_path(name, *search_first):
    """A shipped config file, unless a folder searched first carries its own.

    Pass the data folder (and the working directory, where a script always
    looked) to let one format override, say, its own set_releases.json.
    Falls back to CONFIG_DIR, which is where the versioned copy lives.
    """
    for d in search_first:
        if d:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return os.path.join(CONFIG_DIR, name)


def subprocess_env(env=None):
    """A copy of `env` with src/ on PYTHONPATH, for `python -m mtg_data ...`."""
    env = dict(os.environ if env is None else env)
    parts = [SRC_DIR] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(parts))
    return env
