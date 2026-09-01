"""
Structural tests for the plugin itself.

Every one of these pins a mistake that was live in the repo on 2026-08-30, the
day it stopped being a single skill and became a plugin holding several:

  - package.py decided exclusions on the bare filename, so all 25 shipped
    archetype notes were dropped from the bundle. It zipped cleanly every time.
  - the plugin was named `mtg-tournament-analysis`, the same as one of the
    skills inside it.
  - both SKILL.md files listed `mtg-price-check` in their "Related skills in
    this plugin" table. That skill is not in this plugin.

None of the three raised anything. That is the point of this file.
"""
import json
import os
import re
import sys

import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

PLUGIN_JSON = os.path.join(SCRIPT_DIR, ".claude-plugin", "plugin.json")
MARKETPLACE_JSON = os.path.join(SCRIPT_DIR, ".claude-plugin", "marketplace.json")
SKILLS_DIR = os.path.join(SCRIPT_DIR, "skills")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _skill_dirs():
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(d for d in os.listdir(SKILLS_DIR)
                  if os.path.isfile(os.path.join(SKILLS_DIR, d, "SKILL.md")))


def _front_matter_name(text):
    m = re.search(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return None
    m2 = re.search(r"^name:\s*(.+?)\s*$", m.group(1), re.M)
    return m2.group(1) if m2 else None


# ---------------------------------------------------------------- manifests

def test_plugin_manifest_parses_and_is_complete():
    data = _load(PLUGIN_JSON)
    for field in ("name", "version", "description"):
        assert data.get(field), f"plugin.json is missing {field}"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", data["name"]), \
        f"plugin name {data['name']!r} should be lowercase kebab-case"


def test_marketplace_lists_this_plugin_and_agrees_with_it():
    """
    The marketplace entry is what an installer reads. If it drifts from
    plugin.json, `/plugin install` and the installed plugin disagree.
    """
    market = _load(MARKETPLACE_JSON)
    plugin = _load(PLUGIN_JSON)

    entries = market.get("plugins") or []
    assert entries, "marketplace.json lists no plugins"

    match = [e for e in entries if e.get("name") == plugin["name"]]
    assert match, (
        f"marketplace.json has no entry named {plugin['name']!r}; "
        f"it lists {[e.get('name') for e in entries]}")

    entry = match[0]
    assert entry.get("version") == plugin["version"], (
        f"version drift: plugin.json {plugin['version']}, "
        f"marketplace.json {entry.get('version')}")

    source = entry.get("source", "./")
    target = os.path.normpath(os.path.join(SCRIPT_DIR, source))
    assert os.path.isfile(os.path.join(target, ".claude-plugin", "plugin.json")), \
        f"marketplace source {source!r} has no .claude-plugin/plugin.json"


def test_plugin_name_does_not_collide_with_a_skill_name():
    """
    The plugin was `mtg-tournament-analysis` while containing a skill of the
    same name. Ambiguous in every error message, and worse with each skill
    added. Renamed to `mtg-data` on 2026-08-30.
    """
    name = _load(PLUGIN_JSON)["name"]
    skills = _skill_dirs()
    assert name not in skills, (
        f"the plugin and the skill {name!r} share a name. "
        "Rename the plugin so the two are tellable apart.")


def test_changelog_documents_the_shipped_version():
    version = _load(PLUGIN_JSON)["version"]
    with open(os.path.join(SCRIPT_DIR, "CHANGELOG.md"), encoding="utf-8") as f:
        text = f.read()
    assert re.search(rf"^##\s+{re.escape(version)}\b", text, re.M), \
        f"CHANGELOG.md has no section for the shipped version {version}"


# ------------------------------------------------------------------- skills

def test_no_stray_skill_md_at_the_repo_root():
    """
    A root SKILL.md alongside a skills/ folder risks registering the skill
    twice on install. The restructure moved it; this stops it coming back.
    """
    assert not os.path.exists(os.path.join(SCRIPT_DIR, "SKILL.md")), \
        "SKILL.md is back at the repo root; it belongs in skills/<name>/"


def test_every_skill_dir_has_front_matter_matching_its_folder():
    skills = _skill_dirs()
    assert len(skills) >= 2, f"expected at least two skills, found {skills}"

    for d in skills:
        path = os.path.join(SKILLS_DIR, d, "SKILL.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        name = _front_matter_name(text)
        assert name, f"skills/{d}/SKILL.md has no `name:` in its front matter"
        assert name == d, (
            f"skills/{d}/SKILL.md declares name {name!r}; "
            "the folder and the declared name must match")


def test_sibling_tables_only_name_skills_that_are_actually_here():
    """
    Both SKILL.md files listed `mtg-price-check` under "Related skills in this
    plugin". It ships separately, so the table was telling the reader something
    untrue about what they had installed.

    Related skills that live elsewhere are fine to mention. Just not inside
    the table, which is specifically about this plugin's contents.
    """
    skills = set(_skill_dirs())
    problems = []

    for d in sorted(skills):
        path = os.path.join(SKILLS_DIR, d, "SKILL.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()

        m = re.search(r"^##\s+Related skills in this plugin\s*$(.*?)(?=^##\s|\Z)",
                      text, re.M | re.S)
        assert m, f"skills/{d}/SKILL.md has no Related skills table"

        rows = [ln for ln in m.group(1).splitlines() if ln.strip().startswith("|")]
        named = {n for ln in rows for n in re.findall(r"`([a-z0-9][a-z0-9-]*)`", ln)}

        for n in sorted(named - skills):
            problems.append(f"skills/{d}/SKILL.md table names {n!r}, "
                            "which is not a skill in this plugin")
        for sibling in sorted(skills - {d}):
            if sibling not in named:
                problems.append(f"skills/{d}/SKILL.md table never names "
                                f"its sibling {sibling!r}")

    assert not problems, "\n  ".join([""] + problems)


# ---------------------------------------------------------------- packaging

def test_package_ships_the_manifest_skills_and_the_name_manifest():
    """
    The old should_exclude() took a bare filename, so anything not literally
    called SKILL.md was dropped: every archetype note, and the manifest with
    them. The bundle still built and still installed. It was just wrong.
    """
    import package
    from pathlib import Path

    must_ship = [
        ".claude-plugin/plugin.json",
        "skills/mtg-tournament-analysis/SKILL.md",
        "skills/deck-check/SKILL.md",
        "skills/mtg-tournament-analysis/reference/archetypes/README.md",
        "archetype_names.json",
        "mtg_stats.py",
        "play_profile.py",
        "set_releases.json",
        "bans.json",
        "README.md",
        "LICENSE",
    ]
    missing = [p for p in must_ship if not package.should_ship(Path(p))]
    assert not missing, f"package.py would drop: {missing}"


def test_package_excludes_data_logs_tests_and_vault_notes():
    import package
    from pathlib import Path

    must_not_ship = [
        "melee_standard_all_pairings.csv",
        "melee_standard_439208_standings.csv",
        "mtgo_classifications.json",
        "archetype_refs.json",
        "card_pool_standard.json",
        "event_quarantine_standard.json",
        "build_refs_run.log",
        "probe_log.txt",
        "mtgdecks_fetch.py",
        "analyze_weekend.py",
        "package.py",
        "CHANGELOG.md",
        ".claude-plugin/marketplace.json",
        "[C] MTGO Review Queue 2026-08-29.md",
        "[C] Play Profile.md",
        "[C] Play Profile - UW Control.md",
        "skills/mtg-tournament-analysis/reference/archetypes/[C] Izzet Prowess.md",
        "play_log.jsonl",
        "play_log_standard.jsonl",
        "tests/test_plugin_structure.py",
        "transcripts/anything.md",
        "baselines/meta_baseline_standard.json",
        "archive/through-2026-08-10/manifest.json",
        "__pycache__/mtg_stats.cpython-313.pyc",
    ]
    leaked = [p for p in must_not_ship if package.should_ship(Path(p))]
    assert not leaked, f"package.py would ship: {leaked}"


def test_package_required_set_covers_the_archetype_names():
    """
    should_ship() saying yes is not enough. The name list is what every deck
    label resolves onto, so a bundle without it installs and then merges
    nothing. The build has to fail instead.
    """
    import package
    from pathlib import Path

    assert "archetype names" in package.REQUIRED
    match = package.REQUIRED["archetype names"]
    assert match(Path("archetype_names.json"))
    assert not match(Path("skills/mtg-tournament-analysis/SKILL.md"))


def test_the_archetype_names_manifest_is_on_disk_and_populated():
    path = os.path.join(SCRIPT_DIR, "archetype_names.json")
    assert os.path.exists(path), "archetype_names.json is missing"
    with open(path, encoding="utf-8") as fh:
        names = json.load(fh)["names"]
    assert len(names) >= 20 and all(isinstance(n, str) and n.strip()
                                    for n in names)


def test_archetype_working_notes_stay_out_of_the_bundle():
    """
    The notes are one person's metagame reading. An end user needs the names,
    not the notes, and the repo is public.
    """
    import package
    from pathlib import Path

    note = Path("skills/mtg-tournament-analysis/reference/archetypes/"
                "[C] Izzet Prowess.md")
    readme = Path("skills/mtg-tournament-analysis/reference/archetypes/README.md")
    assert not package.should_ship(note)
    assert package.should_ship(readme)
