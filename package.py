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
      skills/mtg-tournament-analysis/reference/archetypes/README.md
      skills/deck-check/SKILL.md
      *.py, set_releases.json, mtg_config.json, bans.json, setup.bat
      README.md, LICENSE

What it deliberately leaves out: scraped data (CSV/JSON the scrapers write),
run logs, dev and probe scripts, the test suite, transcripts, baselines, the
personal vault notes at the repo root, vod-review's play ledger, and the
archetype working notes. Those last ones are one person's reading of a
metagame; what an end user needs is the canonical name list in
archetype_names.json, and that does ship.

Exclusion is decided on the *relative path*, not the bare filename. An earlier
version tested the filename only, so every .md that was not literally called
SKILL.md was dropped, which silently excluded the archetype content the bundle
depended on. The bundle was broken in exactly the way a passing run cannot show
you. `REQUIRED` below now fails the build if required content goes missing.
"""
import argparse
import os
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
    "untapped_logs",  # the user's own Arena games, pulled by untapped_log.py
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
    # vod-review's play ledger. In the flat no-setup workflow
    # mtg_paths.resolve_output_dir() falls back to the script's own folder, so
    # this lands at the repo root, and it is a record of someone's own games.
    "play_log.jsonl",
    # The cached Comprehensive Rules and its version stamp. rules_lookup.py
    # downloads them on first use, so shipping a copy only guarantees a stale
    # one. The .txt is already caught by the suffix rule; the stamp is not, and
    # a stamp without its document makes --version lie.
    "comp_rules_cache.txt",
    "comp_rules_cache.version",
    ".gitignore",
    ".gitattributes",
    "CHANGELOG.md",
    "marketplace.json",    # describes the repo as a source; not part of the bundle
}

# Config that SHOULD ship even though it is .json (it seeds a fresh setup).
# play_patterns.json is vod-review's pattern registry: general facts about how
# Magic decisions go wrong, true regardless of who was holding the cards. It is
# not optional. play_profile.py exits 1 without it, so a bundle that drops it
# installs cleanly and then refuses to run.
# archetype_vocabulary.json is deck-check's first lookup, per its SKILL.md: the
# format's published names with the three cards that define each one. Without it
# the suggestion step falls through to lookup 2 on every deck, and the skill
# still runs, so a bundle that drops it fails quietly rather than loudly.
# fetch_vocabulary.py shipped without it until 2026-09-08.
KEEP_JSON = {"set_releases.json", "mtg_config.json", "bans.json",
             "archetype_names.json", "play_patterns.json",
             "archetype_vocabulary.json"}

# A bundle carries the plugin, not one person's metagame reading. The archetype
# notes are working notes: they stay on the author's disk, out of the repo, and
# out of here. What ships instead is archetype_names.json, the canonical name
# list every source's spelling resolves onto, which an end user does need.
EXCLUDE_ARCHETYPE_NOTES = "skills/mtg-tournament-analysis/reference/archetypes"

# The only .md files that ship from the repo root. Everything else under skills/
# ships regardless: that is where the reference notes live.
# CLAUDE.md is the plugin router. It ships because a reader who opens the
# installed plugin should land on the map before a SKILL.md.
KEEP_ROOT_MD = {"README.md", "CLAUDE.md"}

# The build fails if any of these match nothing. A bundle missing its archetype
# notes still zips cleanly and still installs; it is just wrong, and quietly.
REQUIRED = {
    "plugin manifest": lambda p: p == Path(".claude-plugin/plugin.json"),
    "plugin router": lambda p: p == Path("CLAUDE.md"),
    "analysis skill": lambda p: p == Path("skills/mtg-tournament-analysis/SKILL.md"),
    "deck-check skill": lambda p: p == Path("skills/deck-check/SKILL.md"),
    "vod-review skill": lambda p: p == Path("skills/vod-review/SKILL.md"),
    "rules-check skill": lambda p: p == Path("skills/rules-check/SKILL.md"),
    "rules reference": lambda p: (
        p == Path("skills/rules-check/reference/rules-and-the-stack.md")),
    "rules lookup script": lambda p: p == Path("rules_lookup.py"),
    "play profile script": lambda p: p == Path("play_profile.py"),
    "play pattern registry": lambda p: p == Path("play_patterns.json"),
    "archetype names": lambda p: p == Path("archetype_names.json"),
    # deck-check's lookup 1. fetch_vocabulary.py refreshes it and did ship on
    # its own, which is the worst of both: the refresher present, the seed gone.
    "archetype vocabulary": lambda p: p == Path("archetype_vocabulary.json"),
    # Imported by validate_events, melee_scraper, matchup_matrix,
    # winrate_analysis and update_archetypes. A bundle without it installs
    # cleanly and then fails at import on the first run of any of them.
    "combined pool writer": lambda p: p == Path("combine_events.py"),
    # The one place a result becomes an archetype name, for standings and
    # pairings alike.
    "deck label resolver": lambda p: p == Path("deck_labels.py"),
}


def should_ship(rel: Path) -> bool:
    """Decide on the relative path, never on the filename alone."""
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if rel.name in EXCLUDE_FILES:
        return False
    if rel.name.endswith((".log", ".txt", ".html", ".csv", ".jsonl")):
        return False
    # Local scrape backups and derived pool files. .gitignore already keeps
    # these out of the repo (`*.json.bak`), but the bundle is built from the
    # working directory rather than from git, so an untracked file ships
    # anyway. On 2026-09-08 that was 2.7 MB of one person's scraped MTGO data
    # in a public plugin: melee_deck_cache.json.bak, mtgo_classifications.json.bak
    # and two more.
    if rel.name.endswith((".bak", ".raw.csv", ".quarantined.csv",
                          ".pre-rebuild.csv")):
        return False
    if ".pre-" in rel.name and rel.suffix in (".json", ".jsonl", ".md", ".csv"):
        return False

    # Everything under skills/ ships, including reference notes, except one
    # person's archetype working notes. The folder's README ships so a fresh
    # install knows what belongs there.
    if rel.parts and rel.parts[0] == "skills":
        if (rel.as_posix().startswith(EXCLUDE_ARCHETYPE_NOTES)
                and rel.name != "README.md"):
            return False
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

    n_names = 0
    try:
        import json
        with open(repo / "archetype_names.json", encoding="utf-8") as fh:
            n_names = len(json.load(fh).get("names", []))
    except (OSError, ValueError):
        pass

    if args.dry_run:
        for rel in shipped:
            print(f"  Would add: {PLUGIN_NAME}/{rel.as_posix()}")
    else:
        # Build to a temp file and rename on success. A file that becomes
        # unreadable between the pre-check and the write (a OneDrive
        # placeholder evicting mid-run is the way this happens) used to raise
        # partway through the zip, leaving a truncated .plugin on disk that
        # looks exactly like a finished one.
        tmp_file = out_file.with_suffix(out_file.suffix + ".tmp")
        try:
            with zipfile.ZipFile(tmp_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for rel in shipped:
                    zf.write(repo / rel, f"{PLUGIN_NAME}/{rel.as_posix()}")
                    print(f"  Added: {PLUGIN_NAME}/{rel.as_posix()}")
        except OSError as e:
            leftover = None
            try:
                tmp_file.unlink()
            except OSError:
                # Can happen on a synced folder that refuses the delete. Say so
                # rather than claiming a clean failure; a stray .tmp somebody
                # later renames is the same partial bundle by another name.
                leftover = tmp_file if tmp_file.exists() else None
            print(f"\nCould not read a file while zipping: {e}")
            print(f"{out_file.name} was not replaced; any previous bundle is "
                  "untouched.")
            if leftover:
                print(f"  A partial build is at {leftover.name} and could not "
                      "be removed. Delete it by hand.")
            print("On OneDrive, mark the repo folder 'Always keep on this device'.")
            return 1
        os.replace(tmp_file, out_file)

    verb = "Would write" if args.dry_run else "Wrote"
    print(f"\n{verb} -> {out_file}")
    print(f"  {len(shipped)} file(s) shipped, {n_names} canonical archetype "
          f"name(s)")
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
