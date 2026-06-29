"""
Run this once from a terminal to create the installable .skill file:

    python package.py

It produces mtg-tournament-analysis.skill in the parent folder. Drop that
file into Cowork to install the skill.

The .skill contains SKILL.md, the Python scripts (including setup.py), and the
shipped config (set_releases.json, mtg_config.json). It deliberately excludes:
  - every scraped data file (CSV/JSON the scrapers generate)
  - run logs (*.log) and dev/probe scripts
  - loose notes (*.md) other than SKILL.md, so personal vault notes never ship
  - the scraped-event registry (standings_only_events.json)
  - plugin metadata, README/CHANGELOG, baselines, transcripts

After it builds, it prints the full file list AND a leak check that flags
anything suspicious. Always eyeball that list before publishing a release.
"""
import zipfile
from pathlib import Path

skill_dir = Path(__file__).parent
out_file = skill_dir.parent / "mtg-tournament-analysis.skill"

# Directories excluded entirely from the .skill
EXCLUDE_DIRS = {
    "transcripts",
    "__pycache__",
    ".pytest_cache",  # created by running the test suite; must not ship
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "baselines",
    "logs",
    "tests",          # repo-only; the installed skill doesn't need the test suite
    ".claude-plugin",
    ".git",
}

# Individual files excluded from the .skill
EXCLUDE_FILES = {
    "package.py",
    "probe_log.txt",
    "run_log.txt",
    "probe_melee.py",
    "probe_page.py",
    "mtgdecks_fetch.py",   # orphan: Cloudflare-blocked, not referenced in SKILL.md
    "analyze_weekend.py",  # hardcoded to specific tournament IDs; stays local, doesn't ship
    "standings_only_events.json",  # the user's scraped-event registry
    ".gitignore",
}

# Config files that SHOULD ship even though they're .json (they seed a setup).
KEEP_JSON = {"set_releases.json", "mtg_config.json"}

# The only .md that ships. Everything else (vault notes, README, CHANGELOG,
# deck logs saved as .md) stays out.
KEEP_MD = {"SKILL.md"}


def should_exclude(name: str) -> bool:
    """True for files that must never ship in the public .skill."""
    if name in EXCLUDE_FILES:
        return True
    if name.endswith(".log"):
        return True
    if name.endswith(".md") and name not in KEEP_MD:
        return True
    if name.endswith(".html"):   # all debug / scraped HTML dumps
        return True
    if name.endswith((".csv",)):  # all scraped CSVs
        return True
    if name.endswith(".json") and name not in KEEP_JSON:
        return True  # scraped JSON, caches, classifications, registries
    return False


added = []
with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zf:
    for f in skill_dir.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(skill_dir)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if should_exclude(f.name):
            continue
        arcname = f.relative_to(skill_dir.parent)
        zf.write(f, arcname)
        added.append(str(arcname))
        print(f"  Added: {arcname}")

print(f"\nDone -> {out_file}  ({len(added)} files)")

# Leak check: flag anything that looks like it shouldn't be public.
suspicious = [a for a in added
              if a.endswith((".log", ".csv"))
              or (a.endswith(".md") and not a.endswith("SKILL.md"))
              or (a.endswith(".json") and Path(a).name not in KEEP_JSON)]
if suspicious:
    print("\n  WARNING — these look like they should NOT ship:")
    for s in suspicious:
        print(f"    {s}")
else:
    print("  Leak check: clean. No data files, logs, or stray notes in the package.")
