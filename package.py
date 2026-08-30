"""
Build the installable plugin bundle:

    python package.py            # writes mtg-data.plugin next to the repo
    python package.py --dry-run  # list what would ship, write nothing

Most people never need this. The normal install is the marketplace:

    /plugin marketplace add Phillip-Hurst/MTG-Data
    /plugin install mtg-data@mtg-data

This script exists for release artifacts and for installing from a local
checkout. It produces a zip whose root is the plugin directory layout:

    mtg-data/
      .claude-plugin/plugin.json
      skills/mtg-tournament-analysis/SKILL.md
      skills/mtg-tournament-analysis/reference/archetypes/*.md
      skills/deck-check/SKILL.md
      *.py, set_releases.json, mtg_config.json, bans.json, setup.bat
      README.md, LICENSE

What it deliberately leaves out: scraped data (CSV/JSON the scrapers write),
run logs, dev and probe scripts, the test suite, transcripts, baselines, and
the personal vault notes at the repo root.

Exclusion is decided on the *relative path*, not the bare filename. An earlier
version tested the filename only, so every .md that was not literally called
SKILL.md was dropped, which silently excluded all 25 shipped archetype notes.
Those notes are the canonical archetype vocabulary, so the bundle was broken in
exactly the way a passing run cannot show you. `REQUIRED` below now fails the
build if they go missing again.
"""
import argparse
import sys
import zipfile
from pathlib import Path

PLUGIN_NAME = "mtg-data"

repo = Path(__file__).parent
out_file = repo.parent / f"{PLUGIN_NAME}.plugin"

# Directories excluded entirely, matched on any path segment.
EXCLUDE_DIRS = {
    ".git",
    "transcripts",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "baselines",
    "archive",        # frozen previous-era scrape data, written by archive_era.py
    "logs",
    "tests",          # repo-only; an installed plugin doesn't need the test suite
}

# Individual files excluded, matched on the bare filename.
EXCLUDE_FILES = {
    "package.py",
    "probe_log.txt",
    "run_log.txt",
    "probe_melee.py",
    "probe_page.py",
    "mtgdecks_fetch.py",   # orphan: Cloudflare-blocked, not referenced in any SKILL.md
    "analyze_weekend.py",  # hardcoded to specific tournament IDs; stays local
    "standings_only_events.json",  # the user's scraped-event registry
    ".gitignore",
    ".gitattributes",
    "CHANGELOG.md",
    "marketplace.json",    # describes the repo as a source; not part of the bundle
}

# Config that SHOULD ship even though it is .json (it seeds a fresh setup).
KEEP_JSON = {"set_releases.json", "mtg_config.json", "bans.json"}

# The only .md files that ship from the repo root. Everything under skills/
# ships regardless: that is where the archetype notes live.
KEEP_ROOT_MD = {"README.md"}

# The build fails if any of these match nothing. A bundle missing its archetype
# notes still zips cleanly and still installs; it is just wrong, and quietly.
REQUIRED = {
    "plugin manifest": lambda p: p == Path(".claude-plugin/plugin.json"),
    "analysis skill": lambda p: p == Path("skills/mtg-tournament-analysis/SKILL.md"),
    "deck-check skill": lambda p: p == Path("skills/deck-check/SKILL.md"),
    "archetype notes": lambda p: (
        p.match("skills/mtg-tournament-analysis/reference/archetypes/*.md")
        and p.name != "README.md"
    ),
}


def should_ship(rel: Path) -> bool:
    """Decide on the relative path, never on the filename alone."""
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if rel.name in EXCLUDE_FILES:
        return False
    if rel.name.endswith((".log", ".txt", ".html", ".csv")):
        return False

    # Everything under skills/ ships, including reference notes.
    if rel.parts and rel.parts[0] == "skills":
        return True

    # The manifest ships; nothing else in .claude-plugin does.
    if rel.parts and rel.parts[0] == ".claude-plugin":
        return rel.name == "plugin.json"

    if rel.suffix == ".md":
        return rel.name in KEEP_ROOT_MD
    if rel.suffix == ".json":
        return rel.name in KEEP_JSON
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the mtg-data plugin bundle.")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would ship and write nothing")
    args = ap.parse_args()

    shipped: list[Path] = []
    skipped: list[Path] = []
    unreadable: list[tuple[Path, str]] = []

    for f in sorted(repo.rglob("*")):
        try:
            if not f.is_file():
                continue
        except OSError as e:
            # OneDrive cloud-only placeholders raise here on a path that a
            # directory listing shows as present. Unreadable is not clean.
            unreadable.append((f.relative_to(repo), str(e)))
            continue
        rel = f.relative_to(repo)
        if should_ship(rel):
            shipped.append(rel)
        else:
            skipped.append(rel)

    # Fail closed before writing anything.
    missing = [label for label, match in REQUIRED.items()
               if not any(match(p) for p in shipped)]
    if missing:
        print("Bundle is missing required content, nothing written:")
        for label in missing:
            print(f"  - {label}")
        return 1

    if unreadable:
        print(f"{len(unreadable)} file(s) could not be read, nothing written:")
        for rel, err in unreadable[:10]:
            print(f"  - {rel}: {err}")
        print("\nOn OneDrive, mark the repo folder 'Always keep on this device'.")
        return 1

    n_notes = sum(1 for p in shipped if REQUIRED["archetype notes"](p))

    if args.dry_run:
        for rel in shipped:
            print(f"  Would add: {PLUGIN_NAME}/{rel.as_posix()}")
    else:
        with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in shipped:
                zf.write(repo / rel, f"{PLUGIN_NAME}/{rel.as_posix()}")
                print(f"  Added: {PLUGIN_NAME}/{rel.as_posix()}")

    verb = "Would write" if args.dry_run else "Wrote"
    print(f"\n{verb} -> {out_file}")
    print(f"  {len(shipped)} file(s) shipped, {n_notes} archetype note(s)")
    print(f"  {len(skipped)} file(s) excluded (data, logs, tests, vault notes)")

    # Leak check: anything shipping from the repo root that looks like data.
    leaks = [p for p in shipped
             if len(p.parts) == 1
             and (p.suffix in {".csv", ".log", ".txt"}
                  or (p.suffix == ".json" and p.name not in KEEP_JSON)
                  or (p.suffix == ".md" and p.name not in KEEP_ROOT_MD))]
    if leaks:
        print("\n  WARNING - these should NOT ship:")
        for p in leaks:
            print(f"    {p.as_posix()}")
        return 2
    print("  Leak check: clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
