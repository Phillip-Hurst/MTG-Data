#!/usr/bin/env python3
"""
cluster_shells.py — turn the unmatched pile into named archetypes.

The stage that was missing
--------------------------
References were only ever built by grouping decks that already had a label. So
a deck whose archetype had no reference never got classified, never contributed
to a reference, and came back in the queue on every run. The queue grew because
nothing in the pipeline could ever create a new category — only refine existing
ones.

Measured on 2026-09-07: of 238 queued MTGO decks, 200 failed on coverage, which
means no reference was close. Clustering those by card overlap found 20 shells
of 3+ decks covering 71% of them. They aren't 200 brews, they're 20 decks
nobody had named yet.

What it does
------------
1. Classify every deck. Take the ones that come back uncertain or unmatched.
2. Cluster them on the overlap of their non-land, 2-or-more-copies core.
3. For each cluster, cross-reference the melee cache and report what organizers
   called the closest lists — a data-derived name suggestion rather than a guess.
4. Write a naming note with a `Name:` line per shell.
5. `--apply` reads the note back and builds a reference for every named shell.

Naming stays the user's call. The script proposes evidence, never a verdict:
what a deck *is* is a judgement about the format, and the person playing it is
better placed to make it. What the script guarantees is that once a shell is
named, its decks stop coming back.

Usage
-----
    python cluster_shells.py                 # write the naming note
    python cluster_shells.py --min-decks 4   # only shells this big
    python cluster_shells.py --apply         # read names back, build references
    python cluster_shells.py --apply --dry-run
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import classifier      # noqa: E402
import refs_store      # noqa: E402
import classify_decks as cd  # noqa: E402
import fetch_vocabulary   # noqa: E402

DATA_DIR = os.environ.get("MTG_DATA_DIR", SCRIPT_DIR)
OUT_DIR = os.environ.get("MTG_OUTPUT_DIR", DATA_DIR)
REFS_FILE = os.path.join(DATA_DIR, "archetype_refs.json")
CACHE_FILE = os.path.join(DATA_DIR, "melee_deck_cache.json")

BASIC_LANDS = {"Island", "Swamp", "Mountain", "Forest", "Plains", "Wastes"}
DEFAULT_SIMILARITY = 0.50
DEFAULT_MIN_DECKS = 3
NOTE_PREFIX = "[C] Unnamed Shells "


def deck_core(mainboard):
    """
    The cards that say what a deck is: non-basic-land, two or more copies.

    Singletons are flex slots and basics are noise. Including either makes two
    unrelated decks look similar because they both play four Islands and a
    one-of sweeper.
    """
    return frozenset(c for c, n in (mainboard or {}).items()
                     if n >= 2 and c not in BASIC_LANDS)


def jaccard(a, b):
    union = a | b
    return len(a & b) / len(union) if union else 0.0


class Shell:
    def __init__(self, uid, main):
        self.members = [(uid, main)]
        self.centroid = deck_core(main)

    def add(self, uid, main):
        self.members.append((uid, main))
        # Centroid is what most of the shell agrees on. Recomputed on every add
        # so one odd list can't drag the whole cluster off its own core.
        counts = Counter()
        for _, m in self.members:
            for card in deck_core(m):
                counts[card] += 1
        need = len(self.members) * 0.5
        self.centroid = frozenset(c for c, n in counts.items() if n >= need)

    def top_cards(self, n=8):
        counts = Counter()
        for _, m in self.members:
            for card in deck_core(m):
                counts[card] += 1
        return [c for c, _ in counts.most_common(n)]

    def reference(self):
        """Modal copy count per card across the shell, best 60 slots."""
        per = {}
        for _, m in self.members:
            for card, n in m.items():
                per.setdefault(card, []).append(n)
        rows = []
        for card, counts in per.items():
            share = len(counts) / len(self.members)
            modal = Counter(counts).most_common(1)[0][0]
            rows.append((share, modal, card))
        rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
        mainboard, used = {}, 0
        for share, modal, card in rows:
            if used >= 60 or share < 0.5:
                break
            take = min(modal, 60 - used)
            mainboard[card] = take
            used += take
        return mainboard


def cluster(decks, similarity=DEFAULT_SIMILARITY):
    """
    Greedy single-pass clustering, biggest cores first.

    Ordering by core size makes the result stable run to run: a fully-formed
    list anchors the cluster, and the shorter variants join it, rather than a
    stub deck founding a cluster the real lists then miss.
    """
    shells = []
    for uid, main in sorted(decks, key=lambda d: -len(deck_core(d[1]))):
        core = deck_core(main)
        if not core:
            continue
        best, best_sim = None, 0.0
        for shell in shells:
            sim = jaccard(core, shell.centroid)
            if sim > best_sim:
                best, best_sim = shell, sim
        if best is not None and best_sim >= similarity:
            best.add(uid, main)
        else:
            shells.append(Shell(uid, main))
    shells.sort(key=lambda s: -len(s.members))
    return shells


def vocabulary_matches(shell, vocab, limit=3):
    """
    Name this shell from the format's published vocabulary.

    MTGGoldfish lists every archetype with the three cards that define it. A
    shell whose core contains Astrologian's Planisphere, Slickshot Show-Off and
    Pym Particles is Izzet Prowess, and the site says so. That's a better
    authority than whatever an organizer typed at 9am, and it keeps the names
    aligned with what the rest of the format calls these decks.

    Scored on how many defining cards the shell's core contains, then on the
    archetype's meta share, so a common deck outranks a fringe one on a tie.

    One defining card is not a match. Deceit defines both Dimir Excruciator and
    Golgari Midrange; Stock Up defines four control decks. Ranking a 1-of-3 hit
    by meta share proposed "Azorius Control" for an Izzet deck that happened to
    share one card. Two of three is the bar for a suggestion worth prefilling;
    single hits are still returned, flagged weak, because they're a useful
    starting point for a person even when they're wrong.
    """
    hits = []
    for name, meta in (vocab or {}).items():
        defining = meta.get("defining") or []
        if not defining:
            continue
        found = [c for c in defining if c in shell.centroid]
        if not found:
            continue
        hits.append((len(found) / len(defining), meta.get("meta_pct", 0.0),
                     name, found))
    hits.sort(reverse=True)
    return hits[:limit]


MIN_DEFINING_SHARE = 2 / 3


def _strong(share):
    return share >= MIN_DEFINING_SHARE - 1e-9


def name_suggestions(shell, cache, vocab=None, limit=3):
    """
    Name candidates, published vocabulary first, local scrape second.

    Both are lookups, not guesses. The vocabulary says what the format calls a
    deck; the melee cache says what the players in your own data called it. When
    they agree that's a strong signal, and when only the cache has an answer it's
    usually a deck too new or too fringe to have been catalogued yet.
    """
    out = []
    for share, meta_pct, name, found in vocabulary_matches(shell, vocab, limit):
        tag = "" if _strong(share) else "  (weak — one card in common, check it)"
        out.append((name, share if _strong(share) else 0.0,
                    f"mtggoldfish {meta_pct}% — matches {len(found)}/3 defining: "
                    f"{', '.join(found)}{tag}"))

    scored = []
    for _, data in (cache or {}).items():
        if data.get("failed") or not data.get("mainboard"):
            continue
        sim = jaccard(shell.centroid, deck_core(data["mainboard"]))
        if sim >= 0.40:
            scored.append((sim, data.get("archetype", "?")))
    scored.sort(reverse=True)
    seen = {n for n, _, _ in out}
    for sim, arch in scored:
        if arch in seen:
            continue
        seen.add(arch)
        out.append((arch, sim, f"melee lists with {sim:.0%} core overlap"))
        if len(out) >= limit * 2:
            break
    return out[:limit * 2]


def unmatched_decks(refs):
    """Every deck the classifier can't place confidently, with its verdict."""
    events = cd.load_events(cd.CHALL_JSON, cd.DUMP_JSON)
    out = []
    for event in events:
        for deck in event.get("decks", []):
            main = cd.normalize_deck(deck.get("mainboard") or {})
            if not main:
                continue
            verdict = classifier.classify(main, refs)
            if verdict.status in ("uncertain", "unmatched", "no_refs"):
                out.append((cd.deck_uid(event, deck), main))
    return out


def note_path(run_date):
    return os.path.join(OUT_DIR, f"{NOTE_PREFIX}{run_date}.md")


def write_note(shells, cache, run_date, min_decks):
    keep = [s for s in shells if len(s.members) >= min_decks]
    covered = sum(len(s.members) for s in keep)
    loose = sum(len(s.members) for s in shells) - covered

    lines = [
        "---", "author: claude", "type: note",
        "project: MTG Tournament Analysis Skill", f"date: {run_date}",
        "tags: [mtg, archetype, unnamed-shells]", "---", "",
        f"# Unnamed shells — {run_date}", "",
        "Decks the classifier can't place, grouped by what they actually play.",
        "Each block below is one deck that nobody has named yet, not a pile of brews.",
        "",
        f"**{len(keep)} shells of {min_decks}+ decks, covering {covered} queued decks.** "
        f"{loose} more decks are genuine one-offs and stay in the queue.",
        "",
        "Name a shell and its decks stop coming back. Leave the `Name:` line blank",
        "or write `skip` to defer — it'll be offered again next run.",
        "",
        "Suggestions come from melee lists with a similar core, so they're what an",
        "organizer typed for the same deck, not a guess. Check one before taking it.",
        "",
        "Then: `python cluster_shells.py --apply`",
        "", "---", "",
    ]

    vocab = fetch_vocabulary.load()
    for i, shell in enumerate(keep, 1):
        sugg = name_suggestions(shell, cache, vocab)
        lines.append(f"## Shell {i} — {len(shell.members)} decks")
        lines.append("")
        lines.append(f"Core: {', '.join(shell.top_cards(10))}")
        lines.append("")
        if sugg:
            lines.append("Candidates, best first:")
            for arch, score, why in sugg:
                lines.append(f"  - **{arch}** — {why}")
        else:
            lines.append("Nothing in the published vocabulary or the melee cache "
                         "has a similar core. This one is yours to name.")
        lines.append("")
        ref = shell.reference()
        top = ", ".join(f"{n}x {c}" for c, n in
                        sorted(ref.items(), key=lambda kv: (-kv[1], kv[0]))[:8])
        lines.append(f"Reference it would build: {top}")
        lines.append("")
        # The suggestion goes on its own line and `Name:` starts blank.
        # Prefilling it made a proposal indistinguishable from a decision: a
        # note nobody had opened would apply its own guesses on the next
        # --apply. Typing the name is the act that makes it a ruling.
        strong = [s for s in sugg if s[1] > 0]
        if strong:
            lines.append(f"Suggested: {strong[0][0]}   "
                         f"(copy it onto the Name: line if you agree)")
        lines.append("Name: ")
        lines.append("")
        lines.append("```shell-id")
        lines.append(json.dumps({"uids": [u for u, _ in shell.members]}))
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    path = note_path(run_date)
    if os.path.exists(path):
        n = 2
        while os.path.exists(os.path.join(OUT_DIR, f"{NOTE_PREFIX}{run_date} (run {n}).md")):
            n += 1
        path = os.path.join(OUT_DIR, f"{NOTE_PREFIX}{run_date} (run {n}).md")
        print(f"  A note for {run_date} already exists and may carry typed names, "
              f"so this run wrote a separate file.")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path, keep


NAME_RE = re.compile(r"^Name:\s*(?P<name>.*?)\s*$", re.MULTILINE)
IDS_RE = re.compile(r"```shell-id\s*(?P<ids>\{.*?\})\s*```", re.DOTALL)
SKIP = {"", "skip", "tbd", "?", "-", "todo", "unsure"}


def read_names(paths):
    """
    Every named shell across the notes, as (name, [uid, ...], source file).

    Parsed block by block rather than with one regex over the whole file. A
    single DOTALL pattern runs past a blank `Name:` line into the next shell and
    picks up its fence as the name, which produced references literally called
    "```shell-id".
    """
    out = []
    for path in paths:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        for block in text.split("\n## Shell ")[1:]:
            nm = NAME_RE.search(block)
            ids = IDS_RE.search(block)
            if not nm or not ids:
                continue
            name = nm.group("name").strip()
            if name.lower() in SKIP or name.startswith("`"):
                continue
            try:
                uids = json.loads(ids.group("ids")).get("uids", [])
            except ValueError:
                continue
            if uids:
                out.append((name, uids, os.path.basename(path)))
    return out


def apply_names(dry_run=False):
    import glob
    notes = sorted(glob.glob(os.path.join(OUT_DIR, f"{NOTE_PREFIX.replace('[', '[[]').replace(']', '[]]')}*.md")))
    if not notes:
        notes = sorted(glob.glob(os.path.join(OUT_DIR, "*Unnamed Shells*.md")))
    named = read_names(notes)
    if not named:
        print(f"No named shells found in {len(notes)} note(s) under {OUT_DIR}.")
        print("Fill in a `Name:` line and re-run.")
        return 1

    refs = refs_store.load(REFS_FILE)
    events = cd.load_events(cd.CHALL_JSON, cd.DUMP_JSON)
    by_uid = {}
    for event in events:
        for deck in event.get("decks", []):
            by_uid[cd.deck_uid(event, deck)] = cd.normalize_deck(
                deck.get("mainboard") or {})

    built = {}
    for name, uids, src in named:
        decks = [(u, by_uid[u]) for u in uids if by_uid.get(u)]
        if not decks:
            print(f"  {name}: none of its {len(uids)} decks are in the current "
                  f"data — skipping (era rolled over?)")
            continue
        shell = Shell(*decks[0])
        for u, m in decks[1:]:
            shell.add(u, m)
        built.setdefault(name, []).append(refs_store.make_entry(
            shell.reference(),
            notes=f"Named from an unmatched shell of {len(decks)} decks ({src})",
            decks=len(decks),
            source="shell-naming",
        ))

    # Two shells can honestly get the same name — a deck often clusters into a
    # main build and a smaller variant. Combining them is right; letting the
    # second overwrite the first in a dict would throw the bigger one away.
    incoming = {}
    for name, entries in built.items():
        incoming[name] = (entries[0] if len(entries) == 1
                          else refs_store.combine(entries))
        n = refs_store.decks_behind(incoming[name])
        verb = "would create" if name not in refs else "would improve"
        extra = f" ({len(entries)} shells combined)" if len(entries) > 1 else ""
        print(f"  {verb} {name:34} from {n} decks{extra}")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    refs_store.save(REFS_FILE, incoming, source="shell-naming")
    print("\nRun classify_decks.py --rerun so the queued decks pick up the new names.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--min-decks", type=int, default=DEFAULT_MIN_DECKS, metavar="N",
                   help=f"Only report shells with N+ decks (default {DEFAULT_MIN_DECKS})")
    p.add_argument("--similarity", type=float, default=DEFAULT_SIMILARITY, metavar="X",
                   help=f"Core overlap needed to join a shell (default {DEFAULT_SIMILARITY})")
    p.add_argument("--apply", action="store_true",
                   help="Read names back out of the notes and build references")
    p.add_argument("--dry-run", action="store_true", help="With --apply, show only")
    args = p.parse_args()

    if args.apply:
        return apply_names(dry_run=args.dry_run)

    refs = refs_store.load(REFS_FILE)
    decks = unmatched_decks(refs)
    if not decks:
        print("Nothing unmatched. The queue is empty.")
        return 0
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            cache = json.load(open(CACHE_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            pass

    shells = cluster(decks, args.similarity)
    keep = [s for s in shells if len(s.members) >= args.min_decks]
    covered = sum(len(s.members) for s in keep)

    print(f"{len(decks)} unmatched deck(s) -> {len(shells)} shell(s)")
    print(f"  {len(keep)} shell(s) of {args.min_decks}+ decks covering {covered} "
          f"({covered/len(decks)*100:.0f}% of the queue)")
    print(f"  {len(decks)-covered} genuine one-offs, left alone\n")
    vocab = fetch_vocabulary.load()
    if vocab:
        print(f"  naming against {len(vocab)} published archetype(s)\n")
    for i, s in enumerate(keep, 1):
        sugg = name_suggestions(s, cache, vocab, 1)
        strong = [x for x in sugg if x[1] > 0]
        hint = (f"  looks like: {strong[0][0]}" if strong
                else (f"  maybe: {sugg[0][0]}?" if sugg else ""))
        print(f"  Shell {i:2d}  {len(s.members):3d} decks  "
              f"{', '.join(s.top_cards(4))}{hint}")

    path, _ = write_note(shells, cache, date.today().isoformat(), args.min_decks)
    print(f"\nNaming note: {os.path.basename(path)}")
    print("Fill in the Name: lines, then: python cluster_shells.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
