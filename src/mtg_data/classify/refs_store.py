#!/usr/bin/env python3
"""
refs_store.py — the one place archetype_refs.json gets written.

Why this module exists
----------------------
Three scripts used to write this file and all three were wrong in a different
direction.

  build_refs_from_melee.py   replaced the whole archetypes dict
  classify_decks.py          replaced the whole archetypes dict
  build_mtgtop8_baseline.py  only ever added labels, never improved one

The replacing pair silently deleted any reference the current run couldn't
rebuild. On 2026-09-07 a `--rebuild-only` in a sandbox dropped Four-Color
Control (Black Base) because only 2 of its decks were in the melee cache and
MIN_DECKS_FOR_REF is 3. It printed "20 archetypes" instead of 21 and exited 0.
The add-only one had the opposite problem: a 3-deck mtgtop8 seed outranked a
40-deck local rebuild forever, because "already present" was the whole test.

The references are a dataset that should grow across scrapes. So: merging is
the default, nothing is ever dropped by accident, and the entry with more
decklists behind it wins.

Entry shape
-----------
    {
      "mainboard": {card: count},     # required, what classification reads
      "notes":     str,
      "decks":     int,               # how many decklists this was built from
      "source":    str,               # melee-cache, mtgo-classifications, mtgtop8, manual
      "updated":   "YYYY-MM-DD",
      "pinned":    bool               # optional; never overwritten automatically
    }

Only `mainboard` is load-bearing for every existing reader. The rest is
provenance, and it's what makes a merge decidable. Entries written before this
module existed get their deck count read out of the old `notes` string, so the
file self-heals on the first write.

Merge policy, per label
-----------------------
    not in existing        -> ADD
    existing is pinned     -> KEEP  (pin it when a reference is anchored on a
                                     list that isn't in any scrape, the way the
                                     Deriu 4CC references are)
    incoming has >= decks  -> UPDATE
    otherwise              -> KEEP  (existing rests on more decklists)

A label absent from the incoming set is always kept. Retiring one is a
deliberate act: pass `drop=[...]`, or `replace=True` for a full reset, which
takes a backup first.
"""
import json
import os
import re
import shutil
from datetime import date

SCHEMA_VERSION = 2

DEFAULT_NOTE = (
    "Reference mainboard lists for archetype classification. "
    "Each entry: {mainboard: {card: count}, notes, decks, source, updated, pinned}. "
    "Written only through refs_store.py, which merges rather than replaces: a run "
    "that can't rebuild a reference leaves the existing one alone. Set "
    '"pinned": true on a reference anchored on a list that no scrape will ever '
    "produce, and no automated rebuild will touch it."
)

# Covers every note format the older scripts wrote:
#   "Built from 14 melee.gg decklist(s)"
#   "Built from 9 decklists"
#   "Baseline from mtgtop8 (Izzet Control umbrella), 5 list(s), 2026-08-29"
_DECKS_IN_NOTES = re.compile(
    r"(\d+)\s+(?:melee\.gg\s+)?(?:decklist|list)(?:s|\(s\))?\b", re.I)


def _infer_decks(entry):
    """How many decklists is this entry built on? 0 when we genuinely can't tell."""
    if not isinstance(entry, dict):
        return 0
    n = entry.get("decks")
    if isinstance(n, int) and n >= 0:
        return n
    m = _DECKS_IN_NOTES.search(entry.get("notes") or "")
    return int(m.group(1)) if m else 0


def decks_behind(entry):
    """Public name for the deck count. 0 when the entry doesn't record or imply one."""
    return _infer_decks(entry)


def combine(entries, cap=60):
    """
    Fold several references for the same deck into one.

    Used when aliases collapse two labels onto a canonical name. Picking the
    entry with the most decks behind it was the old rule and it threw away the
    better list: on 2026-09-07 collapsing Orzhov, Orzhov Combo and Orzhov
    Midrange kept the 4-deck 15-slot reference over the 3-deck 57-slot one,
    because 4 > 3.

    Instead, average each card's count weighted by how many decklists back it,
    then take cards in that order until `cap` slots are filled. A card in every
    contributing reference survives; a card in one thin one doesn't crowd it out.
    Deck counts add up, because the decks were real and distinct.
    """
    entries = [e for e in entries if isinstance(e, dict) and e.get("mainboard")]
    if not entries:
        return None
    if len(entries) == 1:
        return dict(entries[0])

    weights = [max(_infer_decks(e), 1) for e in entries]
    total_w = sum(weights)
    acc = {}
    for e, w in zip(entries, weights, strict=True):
        for card, n in e["mainboard"].items():
            acc[card] = acc.get(card, 0.0) + n * w
    ranked = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))

    mainboard, used = {}, 0
    for card, weighted in ranked:
        if used >= cap:
            break
        n = max(1, min(4, int(round(weighted / total_w))))
        n = min(n, cap - used)
        mainboard[card] = n
        used += n

    decks = sum(_infer_decks(e) for e in entries)
    out = {
        "mainboard": mainboard,
        "decks": decks,
        "notes": f"Combined from {len(entries)} aliased reference(s), "
                 f"{decks} decklist(s) total",
        "source": "alias-combine",
    }
    # A gate or a pin on any contributor applies to the combined entry: both are
    # deliberate statements about the deck, and dropping one silently would undo
    # a decision someone made on purpose.
    req = sorted({c for e in entries for c in (e.get("requires") or [])})
    if req:
        out["requires"] = req
    if any(e.get("pinned") for e in entries):
        out["pinned"] = True
    return out


def eligible(deck_mainboard, entry):
    """
    Is this deck even allowed to match this reference?

    Two optional gates, both lists of card names:

        "requires": a deck playing NONE of these can't be this archetype
        "excludes": a deck playing ANY of these can't be this archetype

    They exist because slot overlap alone can't see a colour. Four-Color
    Control and three-colour Jeskai Control share Jeskai Revelation, Tablet of
    Discovery, Consult the Star Charts, Stock Up and most of a manabase, so a
    Jeskai list scored 30-40 against the four-colour reference and came back
    flagged on every run. Requiring Inevitable Defeat settles it in one line.

    `excludes` is the same idea from the other side, for the case where the
    distinction is something one deck *doesn't* play. Mono Green Landfall and
    Selesnya Landfall share 61% of their slots; on 2026-09-07 that single pair
    was 108 of the 109 margin ties in the queue. The difference is the white
    half, so Mono Green excludes it and the pair separates deterministically
    instead of asking a person the same question 108 times.

    A pair that can't be separated by either gate is usually one deck wearing
    two names, and wants an alias rather than a rule.

    No gates means eligible, which is every entry that hasn't needed one.
    """
    if not isinstance(entry, dict):
        return True
    req = entry.get("requires") or []
    if req and not any(deck_mainboard.get(card, 0) > 0 for card in req):
        return False
    exc = entry.get("excludes") or []
    return not (exc and any(deck_mainboard.get(card, 0) > 0 for card in exc))


def discriminators(decks_a, decks_b, min_share=0.55, max_other=0.08, limit=8):
    """
    Cards that tell two overlapping archetypes apart, derived from their decks.

    Returns (only_in_a, only_in_b): cards played by at least `min_share` of one
    side and at most `max_other` of the other. Feed the result straight into a
    `requires` on one side and an `excludes` on the other.

    This is how a collision gets resolved once instead of every run. It answers
    "what does this deck play that the other one never does", which is the same
    question a person answers by eye, in a form the classifier can apply.
    """
    def profile(decks):
        n = len(decks) or 1
        counts = {}
        for m in decks:
            for card in m:
                counts[card] = counts.get(card, 0) + 1
        return {c: v / n for c, v in counts.items()}

    pa, pb = profile(decks_a), profile(decks_b)
    only_a = sorted(((s, c) for c, s in pa.items()
                     if s >= min_share and pb.get(c, 0) <= max_other), reverse=True)
    only_b = sorted(((s, c) for c, s in pb.items()
                     if s >= min_share and pa.get(c, 0) <= max_other), reverse=True)
    return [c for _, c in only_a[:limit]], [c for _, c in only_b[:limit]]


def make_entry(mainboard, notes=None, decks=None, source=None, pinned=False, when=None):
    """Build a well-formed entry. Callers should use this rather than a bare dict."""
    e = {"mainboard": mainboard}
    if notes:
        e["notes"] = notes
    e["decks"] = int(decks) if decks is not None else 0
    if source:
        e["source"] = source
    e["updated"] = (when or date.today()).isoformat()
    if pinned:
        e["pinned"] = True
    return e


def _normalise(label, entry, source, when):
    """Fill in provenance on an entry that predates this module."""
    if not isinstance(entry, dict) or "mainboard" not in entry:
        return None
    out = dict(entry)
    out.setdefault("decks", _infer_decks(entry))
    if source and not out.get("source"):
        out["source"] = source
    out.setdefault("updated", when.isoformat())
    return out


def load_doc(path):
    """The whole document, with `archetypes` guaranteed present."""
    doc = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            doc = {}
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("archetypes", {})
    return doc


def load(path):
    """Just the archetypes dict."""
    return load_doc(path).get("archetypes", {})


def merge(existing, incoming, source=None, when=None, drop=()):
    """
    Fold `incoming` into `existing` without losing anything.

    Returns (merged, report). The report lists label names under `added`,
    `updated`, `kept_richer`, `kept_pinned` and `dropped`, so a caller can show
    the dataset growing instead of printing one opaque total.
    """
    when = when or date.today()
    merged = {}
    report = {"added": [], "updated": [], "kept_richer": [], "kept_pinned": [],
              "untouched": [], "dropped": [], "rejected": []}

    for label, entry in (existing or {}).items():
        norm = _normalise(label, entry, None, when)
        if norm is None:
            report["rejected"].append(label)
            continue
        merged[label] = norm

    for label, entry in (incoming or {}).items():
        cand = _normalise(label, entry, source, when)
        if cand is None:
            report["rejected"].append(label)
            continue
        cand["updated"] = when.isoformat()
        cur = merged.get(label)
        if cur is None:
            merged[label] = cand
            report["added"].append(label)
        elif cur.get("pinned"):
            report["kept_pinned"].append(label)
        elif _infer_decks(cand) >= _infer_decks(cur):
            if cur.get("pinned"):
                cand["pinned"] = True
            merged[label] = cand
            report["updated"].append(label)
        else:
            report["kept_richer"].append(label)

    touched = set(report["added"]) | set(report["updated"]) \
        | set(report["kept_richer"]) | set(report["kept_pinned"])
    report["untouched"] = [k for k in merged if k not in touched]

    for label in drop or ():
        if merged.pop(label, None) is not None:
            report["dropped"].append(label)
            for k in report:
                if label in report[k] and k != "dropped":
                    report[k].remove(label)

    for k in report:
        report[k].sort()
    return merged, report


def format_report(report, total, decks_total=None):
    """One block of human-readable lines. Empty categories stay quiet."""
    lines = []
    order = [("added", "added"), ("updated", "updated with more decks"),
             ("kept_richer", "kept (existing rests on more decks)"),
             ("kept_pinned", "kept (pinned)"),
             ("untouched", "untouched (this run rebuilt nothing for them)"),
             ("dropped", "dropped"), ("replaced", "DISCARDED by --replace"),
             ("rejected", "rejected as malformed")]
    for key, human in order:
        names = report.get(key) or []
        if not names:
            continue
        shown = ", ".join(names[:6]) + (f", +{len(names)-6} more" if len(names) > 6 else "")
        lines.append(f"  {len(names):3d} {human}: {shown}")
    tail = f"  {total} reference(s) on file"
    if decks_total is not None:
        tail += f", {decks_total} decklist(s) behind them"
    lines.append(tail)
    return "\n".join(lines)


def save(path, incoming, *, source=None, replace=False, drop=(), note=None,
         thresholds=None, when=None, quiet=False, backup_name=None):
    """
    Merge `incoming` into the file at `path` and write it back.

    replace=True throws the existing references away instead, after copying the
    file to `archetype_refs.pre-replace.json`. That is a reset, not a rebuild,
    and nothing should reach for it on a schedule.

    Returns the report dict from merge().
    """
    when = when or date.today()
    doc = load_doc(path)
    existing = doc.get("archetypes", {})

    if replace:
        if os.path.exists(path):
            backup = os.path.join(os.path.dirname(path) or ".",
                                  backup_name or "archetype_refs.pre-replace.json")
            try:
                shutil.copyfile(path, backup)
                if not quiet:
                    print(f"  Previous references copied to {os.path.basename(backup)}")
            except OSError as e:
                if not quiet:
                    print(f"  WARNING: could not back up existing references ({e})")
        merged, report = merge({}, incoming, source=source, when=when, drop=drop)
        report["replaced"] = sorted(set(existing) - set(merged))
        if not quiet and report["replaced"]:
            print(f"  --replace dropped {len(report['replaced'])} existing reference(s): "
                  + ", ".join(report["replaced"][:8]))
    else:
        merged, report = merge(existing, incoming, source=source, when=when, drop=drop)

    doc["archetypes"] = merged
    doc["_note"] = note or DEFAULT_NOTE
    doc["_schema_version"] = SCHEMA_VERSION
    if thresholds:
        doc.setdefault("_thresholds", thresholds)
    if source:
        doc["_last_write"] = {"source": source, "date": when.isoformat()}

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

    if not quiet:
        behind = sum(_infer_decks(e) for e in merged.values())
        print(f"archetype_refs.json written from {source or 'unknown source'}:")
        print(format_report(report, len(merged), behind))
    return report
