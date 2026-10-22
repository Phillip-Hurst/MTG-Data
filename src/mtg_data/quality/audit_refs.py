#!/usr/bin/env python3
"""
audit_refs.py — is archetype_refs.json fit to classify against?

Why
---
References are what every live deck gets matched against, so a bad one is
worse than a missing one: it silently renames real decks. Two ways they go bad,
both seen on 2026-08-29:

  wrong era     a rebuild from melee_deck_cache.json produced 45 references,
                6 of them Modern, because the cache still held decks from
                events the validator had already quarantined out of the CSVs
  collisions    seeding from mtgtop8 on top of locally-built refs added 15
                labels, several near-identical to ones already there. Two refs
                that share 90% of their slots produce near-tied match scores,
                which is exactly the documented cause of the review-queue flood

This reports both, plus coverage against what's actually being played. It
changes nothing on its own.

Usage
-----
    python mtg.py audit-refs                 # full report
    python mtg.py audit-refs --strict        # exit 1 on any error-level finding
    python mtg.py audit-refs --overlap 0.75  # tighter collision threshold
    python mtg.py audit-refs --json
"""
import argparse
import collections
import itertools
import json
import os
import re
import sys


from mtg_data.core.paths import resolve_data_dir
from mtg_data.core import era as mtg_era
from mtg_data.classify import refs_store
from mtg_data.core.paths import CONFIG_DIR, ROOT_DIR
from mtg_data.core.stats import normalize
from mtg_data.ingest import build_card_pool
from mtg_data.quality import validate_events as ve

# Two references sharing this much of their mainboard will produce near-tied
# match scores. classify_decks picks on raw slot overlap with no margin, so a
# tie is decided by dictionary order — which is to say, arbitrarily.
DEFAULT_OVERLAP = 0.60
# Below this many cards a reference can match almost anything in its colours.
MIN_REF_CARDS = 8
# An archetype at this share of the live field with no reference is a real gap.
COVERAGE_ALERT_SHARE = 0.03


def _find_config(name):
    for d in (os.getcwd(), CONFIG_DIR):
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
    return os.path.join(CONFIG_DIR, name)


def load_config():
    try:
        with open(_find_config("mtg_config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def norm_label(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def apply_aliases(refs):
    """
    Collapse aliased labels onto the canonical name from mtg_stats.

    Two references for one deck is worse than one: near-tied refs used to be
    resolved by dictionary order, and the Izzet trio sat at 94% slot overlap for
    weeks.

    The old rule kept whichever side had more decklists behind it. That threw
    away the better list — collapsing Orzhov, Orzhov Combo and Orzhov Midrange
    kept the 4-deck 15-slot reference over the 3-deck 57-slot one, because
    4 > 3, and left an archetype that could never clear the confidence bar.

    Now the contributors are combined: every card weighted by the decks behind
    it, best 60 slots kept, deck counts added. See refs_store.combine.
    """
    groups, moves = {}, []
    for name, ref in refs.items():
        canon = normalize(name)
        if canon != name:
            moves.append((name, canon))
        groups.setdefault(canon, []).append(ref)

    merged = {}
    for canon, entries in groups.items():
        merged[canon] = refs_store.combine(entries) if len(entries) > 1 else entries[0]
    return merged, moves


def check_era(refs, fmt, data_dir):
    """Banned cards and off-format cards inside references."""
    findings = []
    try:
        era = mtg_era.resolve_era(fmt=fmt)
        banned = ve.banned_as_of(fmt, era.get("start"))
        pool, meta = build_card_pool.load_pool(fmt, data_dir)
    except Exception as e:
        return [{"level": "warn", "kind": "era",
                 "msg": f"could not load the era guard ({e}); era checks skipped"}], None

    if pool is None:
        findings.append({"level": "warn", "kind": "era",
                         "msg": "no card pool on file — off-format references "
                                "cannot be detected. Run python mtg.py build-card-pool."})

    for name, r in sorted(refs.items()):
        cards = {str(c).strip().lower() for c in (r.get("mainboard") or {})}
        if not cards:
            findings.append({"level": "error", "kind": "empty", "archetype": name,
                             "msg": "reference has an empty mainboard"})
            continue
        hits = cards & banned
        if hits:
            findings.append({"level": "error", "kind": "banned", "archetype": name,
                             "msg": f"contains banned card(s): {', '.join(sorted(hits))}"})
        if pool is not None:
            illegal = cards - pool
            if len(illegal) / len(cards) > 0.05:
                findings.append({"level": "error", "kind": "off-format", "archetype": name,
                                 "msg": f"{len(illegal)}/{len(cards)} cards not legal in "
                                        f"{fmt}: {', '.join(sorted(illegal)[:5])}"})
        if len(cards) < MIN_REF_CARDS:
            findings.append({"level": "warn", "kind": "thin", "archetype": name,
                             "msg": f"only {len(cards)} cards — will over-match"})
    return findings, era


def check_collisions(refs, threshold):
    """References so similar that a match between them is a coin flip."""
    findings = []
    by_norm = collections.defaultdict(list)
    for name in refs:
        by_norm[norm_label(name)].append(name)
    for _, names in by_norm.items():
        if len(names) > 1:
            findings.append({"level": "error", "kind": "duplicate-label",
                             "archetypes": sorted(names),
                             "msg": "labels differ only by punctuation or case"})

    mbs = {n: {str(c).strip().lower() for c in (r.get("mainboard") or {})}
           for n, r in refs.items()}
    for a, b in itertools.combinations(sorted(mbs), 2):
        A, B = mbs[a], mbs[b]
        if not A or not B:
            continue
        j = len(A & B) / len(A | B)
        if j >= threshold:
            findings.append({
                "level": "error" if j >= 0.85 else "warn",
                "kind": "collision", "archetypes": [a, b], "overlap": round(j, 3),
                "msg": f"{j:.0%} of slots shared ({len(A)} vs {len(B)} cards) — "
                       "match scores will be near-tied",
            })
    findings.sort(key=lambda f: -(f.get("overlap") or 0))
    return findings


def check_coverage(refs, data_dir, since):
    """What's being played that no reference covers."""
    cls = load_json(os.path.join(data_dir, "mtgo_classifications.json")) or {}
    total = named = 0
    for fname in ("mtgo_challenge_latest.json", "mtgo_5-0_latest.json"):
        for ev in load_json(os.path.join(data_dir, fname)) or []:
            if since and ev.get("date", "") < since:
                continue
            for d in ev.get("decks", []):
                total += 1
                if cls.get(f"{ev.get('url')};{d.get('url')}"):
                    named += 1
    unnamed = total - named
    findings = []
    if total:
        share = unnamed / total
        level = "error" if share > 0.35 else ("warn" if share > 0.20 else "info")
        findings.append({
            "level": level, "kind": "coverage",
            "msg": f"{unnamed} of {total} decks in the window have no archetype "
                   f"({share:.0%})",
        })
        if share > 0.20:
            findings.append({
                "level": "info", "kind": "coverage",
                "msg": "Seed more references: python mtg.py build-mtgtop8-baseline "
                       "--format Standard",
            })
    # References nothing matched — dead weight that can still cause collisions.
    used = collections.Counter(v.get("archetype") for v in cls.values())
    unused = [n for n in refs if not used.get(n)]
    if unused:
        findings.append({
            "level": "info", "kind": "unused", "archetypes": sorted(unused),
            "msg": f"{len(unused)} reference(s) matched nothing in the current data",
        })
    return findings, total, named


def main():
    p = argparse.ArgumentParser(description="Audit archetype_refs.json.")
    p.add_argument("--format", default=None)
    p.add_argument("--since", default=None, help="Window start. Default: era start.")
    p.add_argument("--overlap", type=float, default=DEFAULT_OVERLAP)
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 if anything is error-level.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--apply-aliases", action="store_true",
                   help="Collapse aliased labels onto the vault's canonical names.")
    p.add_argument("--dry-run", action="store_true",
                   help="With --apply-aliases: show the merge, write nothing.")
    args = p.parse_args()

    config = load_config()
    fmt = (args.format or config.get("format", "Standard")).strip()
    data_dir = resolve_data_dir(fmt, ROOT_DIR)

    refs_doc = load_json(os.path.join(data_dir, "archetype_refs.json"))
    if not refs_doc:
        print(f"No readable archetype_refs.json in {data_dir}.")
        print("  Seed one: python mtg.py build-mtgtop8-baseline --format " + fmt)
        return 1
    refs = refs_doc.get("archetypes", {})

    if args.apply_aliases:
        merged, moves = apply_aliases(refs)
        if not moves:
            print("No aliased labels in archetype_refs.json. Nothing to merge.")
            return 0
        print(f"\nMerging {len(moves)} aliased label(s) onto the vault's names:")
        for old, new in sorted(moves):
            print(f"  {old:28s} -> {new}")
        print(f"\n{len(refs)} reference(s) -> {len(merged)}")
        if args.dry_run:
            print("\n--dry-run: nothing written.")
            return 0
        # This one genuinely removes labels, so it's the one place a replace is
        # right. It still goes through refs_store, which takes the backup and
        # keeps the provenance fields consistent with every other writer.
        path = os.path.join(data_dir, "archetype_refs.json")
        refs_store.save(path, merged, source="alias-merge", replace=True,
                        backup_name="archetype_refs.pre-alias.json", quiet=True)
        doc = refs_store.load_doc(path)
        doc["_aliases_applied"] = True
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        print("Written. Previous version kept at archetype_refs.pre-alias.json.")
        print("Re-run python mtg.py classify-decks --rerun so live decks pick up the merged names.")
        return 0

    era_findings, era = check_era(refs, fmt, data_dir)
    since = args.since or (era.get("start_str") if era else None)
    collisions = check_collisions(refs, args.overlap)
    coverage, total, named = check_coverage(refs, data_dir, since)
    findings = era_findings + collisions + coverage

    if args.json:
        print(json.dumps({"format": fmt, "refs": len(refs),
                          "era": era.get("label") if era else None,
                          "decks": total, "named": named,
                          "findings": findings}, indent=1))
        return 1 if (args.strict and any(f["level"] == "error" for f in findings)) else 0

    print(f"\narchetype_refs.json — {len(refs)} reference(s), {fmt}")
    if era:
        print(f"  Era: {era.get('label')}")
    print(f"  Source: {refs_doc.get('_source', 'unrecorded')}")
    # The evidence behind the references, which is the number that should climb
    # scrape over scrape. If it drops, something replaced instead of merging.
    behind = sum(refs_store.decks_behind(r) for r in refs.values())
    unattributed = sum(1 for r in refs.values() if refs_store.decks_behind(r) == 0)
    pinned = sorted(k for k, r in refs.items() if isinstance(r, dict) and r.get("pinned"))
    line = f"  Decklists behind them: {behind}"
    if unattributed:
        line += f"  ({unattributed} reference(s) record no count)"
    print(line)
    if pinned:
        print(f"  Pinned (never auto-overwritten): {', '.join(pinned)}")
    last = refs_doc.get("_last_write")
    if last:
        print(f"  Last write: {last.get('source')} on {last.get('date')}")
    print()

    errors = [f for f in findings if f["level"] == "error"]
    warns = [f for f in findings if f["level"] == "warn"]
    infos = [f for f in findings if f["level"] == "info"]

    for label, group in (("ERROR", errors), ("WARN", warns), ("INFO", infos)):
        if not group:
            continue
        print(f"## {label} ({len(group)})")
        for f in group:
            who = f.get("archetype") or " / ".join(f.get("archetypes", [])[:2])
            if f.get("kind") == "unused":
                print(f"  {f['msg']}")
                print(f"    {', '.join(f['archetypes'][:10])}"
                      + (" ..." if len(f["archetypes"]) > 10 else ""))
            elif who:
                print(f"  [{f['kind']}] {who}")
                print(f"    {f['msg']}")
            else:
                print(f"  [{f['kind']}] {f['msg']}")
        print()

    if not errors and not warns:
        print("Clean. References are in-era, in-format, and distinct.")
    elif errors:
        print("Collisions and off-era references both cause the same failure: a real "
              "deck gets renamed to something it isn't, quietly. Resolve before "
              "trusting a share or a matchup number.")

    return 1 if (args.strict and errors) else 0


if __name__ == "__main__":
    sys.exit(main())
