"""
Build the installable plugin bundle:

    python scripts/build_plugin.py            # writes mtg-data.plugin next to the repo
    python scripts/build_plugin.py --dry-run  # list what would ship, write nothing

Most people never need this. The normal install is the marketplace:

    /plugin marketplace add Phillip-Hurst/MTG-Data
    /plugin install mtg-data@mtg-data

This script exists for release artifacts and for installing from a local
checkout. It produces a zip whose root is the plugin directory layout:

    mtg-data/
      .claude-plugin/plugin.json
      skills/<name>/SKILL.md, skills/<name>/reference/...
      src/mtg_data/...            the pipeline
      config/*.json               the versioned reference data
      scripts/setup_workspace.py, scripts/setup.bat
      docs/*.md
      mtg.py, pyproject.toml, README.md, CLAUDE.md, LICENSE

Everything else is left out: scraped data, run logs, the test suite, the
build tooling, transcripts, baselines, the personal notes the flat workflow
writes to the checkout root, vod-review's play ledger, and the archetype
working notes. Those last ones are one person's reading of a metagame; what an
end user needs is the canonical name list in config/archetype_names.json, and
that does ship.

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

repo = Path(__file__).resolve().parent.parent
out_file = repo.parent / f"{PLUGIN_NAME}.plugin"

# What ships is an allow-list. Until 2.0.0 this was a deny-list run over the
# whole working directory, and every new kind of local file was a leak until
# someone thought to name it: on 2026-09-08 that was 2.7 MB of one person's
# scraped MTGO data. The flat workflow writes data and notes to the checkout
# root, so nothing at the root ships unless it is named here.
ROOT_FILES = {"mtg.py", "pyproject.toml", "README.md", "CLAUDE.md", "LICENSE"}
SHIPPED_DIRS = ("skills", "src", "config", "scripts", "docs", ".claude-plugin")

# Config that ships. Every file in config/ is reference data the pipeline needs:
# play_patterns.json is vod-review's pattern registry (play_profile exits 1
# without it), archetype_vocabulary.json is deck-check's first lookup, and
# archetype_names.json is the vocabulary every deck label resolves onto.
KEEP_JSON = {"set_releases.json", "mtg_config.json", "bans.json",
             "archetype_names.json", "play_patterns.json",
             "archetype_vocabulary.json"}

# scripts/ holds tooling. Only the workspace setup is any use to an end user.
KEEP_SCRIPTS = {"setup_workspace.py", "setup.bat"}

# Directories excluded wherever they appear.
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
                ".venv", ".git"}

# A bundle carries the plugin, not one person's metagame reading. The archetype
# notes are working notes: they stay on the author's disk, out of the repo, and
# out of here. What ships instead is config/archetype_names.json.
EXCLUDE_ARCHETYPE_NOTES = "skills/mtg-tournament-analysis/reference/archetypes"

# The build fails if any of these match nothing. A bundle missing its archetype
# notes still zips cleanly and still installs; it is just wrong, and quietly.
REQUIRED = {
    "plugin manifest": lambda p: p == Path(".claude-plugin/plugin.json"),
    "plugin router": lambda p: p == Path("CLAUDE.md"),
    "command-line entry point": lambda p: p == Path("mtg.py"),
    "analysis skill": lambda p: p == Path("skills/mtg-tournament-analysis/SKILL.md"),
    "deck-check skill": lambda p: p == Path("skills/deck-check/SKILL.md"),
    "vod-review skill": lambda p: p == Path("skills/vod-review/SKILL.md"),
    "rules-check skill": lambda p: p == Path("skills/rules-check/SKILL.md"),
    "rules reference": lambda p: (
        p == Path("skills/rules-check/reference/rules-and-the-stack.md")),
    "command registry": lambda p: p == Path("src/mtg_data/cli.py"),
    "rules lookup": lambda p: p == Path("src/mtg_data/review/rules_lookup.py"),
    "play profile": lambda p: p == Path("src/mtg_data/review/play_profile.py"),
    "play pattern registry": lambda p: p == Path("config/play_patterns.json"),
    "archetype names": lambda p: p == Path("config/archetype_names.json"),
    # deck-check's lookup 1. fetch-vocabulary refreshes it and did ship on its
    # own, which is the worst of both: the refresher present, the seed gone.
    "archetype vocabulary": lambda p: p == Path("config/archetype_vocabulary.json"),
    # Imported by every reader of the pool. A bundle without it installs
    # cleanly and then fails at import on the first run.
    "combined pool writer": lambda p: p == Path("src/mtg_data/quality/combine_events.py"),
    # The one place a result becomes an archetype name.
    "deck label resolver": lambda p: p == Path("src/mtg_data/classify/deck_labels.py"),
}


def should_ship(rel: Path) -> bool:
    """Decide on the relative path, never on the filename alone."""
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if len(rel.parts) == 1:
        return rel.name in ROOT_FILES
    top = rel.parts[0]
    if top not in SHIPPED_DIRS:
        return False
    if top == ".claude-plugin":
        # marketplace.json describes the repo as a source; not part of the bundle.
        return rel.name == "plugin.json"
    if top == "config":
        return len(rel.parts) == 2 and rel.name in KEEP_JSON
    if top == "scripts":
        return len(rel.parts) == 2 and rel.name in KEEP_SCRIPTS
    if top == "src":
        return rel.suffix == ".py"
    if top == "docs":
        # The README links into docs/, so the bundle carries it.
        return len(rel.parts) == 2 and rel.suffix == ".md"
    # skills/: everything, reference notes included, except one person's
    # archetype working notes. The folder's README ships so a fresh install
    # knows what belongs there.
    if (rel.as_posix().startswith(EXCLUDE_ARCHETYPE_NOTES)
            and rel.name != "README.md"):
        return False
    return rel.suffix in (".md", ".json")


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
        with open(repo / "config" / "archetype_names.json", encoding="utf-8") as fh:
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

    # Leak check: belt and braces on top of the allow-list. Nothing that looks
    # like scraped data or a personal ledger ships, wherever it sits.
    leaks = [p for p in shipped
             if p.suffix in {".csv", ".log", ".txt", ".jsonl", ".bak"}
             or (p.suffix == ".json" and p.parts[0] not in ("config", ".claude-plugin"))
             or p.name.startswith("[C] ")]
    if leaks:
        print("\n  WARNING - these should NOT ship:")
        for p in leaks:
            print(f"    {p.as_posix()}")
        return 2
    print("  Leak check: clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
