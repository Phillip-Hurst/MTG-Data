#!/usr/bin/env python3
"""
deck_labels.py — one canonical archetype name per tournament result.

Why this exists
---------------
The classifier and the meta-share layer were reading different vocabularies.
`classify_decks.py` resolves a deck by its cards, `mtg_stats.ARCHETYPE_ALIASES`
folds organizer house styles onto one name, and `apply_corrections.py` records
Phill's rulings. `build_baseline.py` used none of them. It counted the deck
name an organizer typed into melee.

Measured on the 2026-09-07 snapshot: 44 labels for 78 players, 27 of them
singletons. Applying the alias table alone moved Izzet Spellementals from 6.4%
and fifth place to 10.3% and first. The published tier order was wrong, and it
was wrong for a reason already solved in another file.

The resolution order
--------------------
    override    a human ruling in archetype_overrides.json. Always wins.
    classifier  a confident verdict from the cached decklist's cards.
    organizer   the cached list exists but no reference is confident about it.
                Fall back to the organizer's text, aliased.
    dropped     no cached decklist. The row leaves the sample.

Dropping is Phill's rule, 2026-09-07: "If we have no decklist for a melee
result, that position should be discarded. Knowing someone went 2-6 or 7-1
means nothing if we do not know what they played."

That takes the live melee pool from 80 players to 61, and it makes the
remaining 61 mean something. Every caller gets the drop counts back and is
expected to print them, because a filter that doesn't report what it removed
can't be checked.

`source` travels with every label for the same reason. An `organizer` row is a
name somebody typed; a `classifier` row is a name the cards support. Pooling
them without saying which is which is how a thin label passes for a verified
one.
"""
import json
import os
import sys
from collections import Counter, namedtuple


from mtg_data.classify import classifier
from mtg_data.classify import refs_store
from mtg_data.core.paths import ROOT_DIR

from mtg_data.core.stats import normalize as _alias

# Organizer text that names no deck. Same list build_baseline has always used,
# kept here so the drop happens once, at resolution, rather than in each caller.
JUNK_DECKS = {"", "decklist", "unknown", "deck", "n/a", "-", "—"}

SOURCES = ("override", "classifier", "organizer")
DROPS = ("no_url", "no_decklist", "junk_name")

Label = namedtuple("Label", "name source detail")


def _read_json(path):
    """None when the file is absent or unreadable. Callers must not treat that
    as an empty-but-fine file (guardrail 2) — `Resolver.problems` carries it."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        return {"__error__": str(e)}


class Resolver:
    """
    Turns (deck_url, deck_name) into a canonical label, or into a drop.

    Build one per run and reuse it: it holds the deck cache, the overrides and
    the references, and it memoises classifier verdicts by URL because the same
    decklist appears once per standings row.
    """

    def __init__(self, data_dir, cache=None, overrides=None, refs=None):
        self.data_dir = data_dir
        self.problems = []
        self.counts = Counter()
        self._verdicts = {}

        self.cache = cache if cache is not None else self._load(
            "melee_deck_cache.json", unwrap=None)
        self.overrides = overrides if overrides is not None else self._load(
            "archetype_overrides.json", unwrap="overrides")
        if refs is not None:
            self.refs = refs
        else:
            path = os.path.join(data_dir, "archetype_refs.json")
            self.refs = refs_store.load(path) if os.path.exists(path) else {}
        # No references means every cached deck falls back to organizer text,
        # which looks exactly like the bug this module exists to kill. Say so
        # however the references arrived (guardrail 1: silence is the failure).
        if not self.refs:
            self.problems.append(
                "archetype_refs.json is missing or empty — every cached deck "
                "will fall back to its organizer label")

    def _load(self, name, unwrap):
        path = os.path.join(self.data_dir, name)
        if not os.path.exists(path):
            self.problems.append(f"{name} not found in {self.data_dir}")
            return {}
        doc = _read_json(path)
        if isinstance(doc, dict) and "__error__" in doc:
            self.problems.append(f"{name} could not be read: {doc['__error__']}")
            return {}
        if unwrap:
            doc = (doc or {}).get(unwrap, {})
        return doc if isinstance(doc, dict) else {}

    # ── resolution ───────────────────────────────────────────────────────────

    def _classify(self, url, mainboard):
        if url not in self._verdicts:
            self._verdicts[url] = classifier.classify(mainboard, self.refs)
        return self._verdicts[url]

    def resolve(self, deck_url, deck_name=""):
        """
        Label(name, source, detail), or Label(None, drop_reason, detail).

        A drop is reported, never silently waved through: an absent decklist is
        not a passing decklist.
        """
        url = (deck_url or "").strip()
        typed = (deck_name or "").strip()

        if not url:
            self.counts["no_url"] += 1
            return Label(None, "no_url", typed)

        ruling = (self.overrides or {}).get(url)
        if isinstance(ruling, dict) and (ruling.get("archetype") or "").strip():
            self.counts["override"] += 1
            return Label(_alias(ruling["archetype"]), "override",
                         ruling.get("decided") or "")

        entry = (self.cache or {}).get(url)
        mainboard = (entry or {}).get("mainboard") or {}
        if not mainboard:
            self.counts["no_decklist"] += 1
            return Label(None, "no_decklist", typed)

        verdict = self._classify(url, mainboard)
        if verdict.status == "confident" and verdict.archetype:
            self.counts["classifier"] += 1
            return Label(_alias(verdict.archetype), "classifier",
                         f"cov {verdict.coverage:.2f}")

        # We know what they played, we just have no reference confident enough
        # to name the shell. The row stays in the sample under the organizer's
        # name, flagged, because Phill's rule is about missing decklists rather
        # than about unnamed decks.
        fallback = _alias((entry or {}).get("archetype") or typed)
        if fallback.lower() in JUNK_DECKS:
            self.counts["junk_name"] += 1
            return Label(None, "junk_name", fallback)
        self.counts["organizer"] += 1
        return Label(fallback, "organizer", verdict.reason)

    # ── reporting ────────────────────────────────────────────────────────────

    @property
    def kept(self):
        return sum(self.counts[s] for s in SOURCES)

    @property
    def dropped(self):
        return sum(self.counts[d] for d in DROPS)

    def report_lines(self):
        """What was kept, what was dropped, and why. Print this. Always."""
        lines = [
            f"  labels resolved: {self.kept}  "
            f"(override {self.counts['override']}, "
            f"classifier {self.counts['classifier']}, "
            f"organizer {self.counts['organizer']})",
        ]
        if self.dropped:
            lines.append(
                f"  rows dropped:    {self.dropped}  "
                f"(no decklist {self.counts['no_decklist']}, "
                f"no deck url {self.counts['no_url']}, "
                f"unnamed {self.counts['junk_name']})")
        else:
            lines.append("  rows dropped:    0")
        for p in self.problems:
            lines.append(f"  WARNING: {p}")
        return lines

    def provenance(self):
        """The counts, for stamping onto a snapshot."""
        return {
            "override": self.counts["override"],
            "classifier": self.counts["classifier"],
            "organizer": self.counts["organizer"],
            "dropped_no_decklist": self.counts["no_decklist"],
            "dropped_no_deck_url": self.counts["no_url"],
            "dropped_unnamed": self.counts["junk_name"],
        }


# ── pairing rows ─────────────────────────────────────────────────────────────

# The two deck columns on a pairing row, with the URL that can name each one.
PAIRING_SEATS = (("player1_deck", "player1_deck_url"),
                 ("player2_deck", "player2_deck_url"))


def resolve_pairing_decks(rows, data_dir=None, resolver=None,
                          keep_organizer_text=True):
    """
    Fill in the deck names on melee pairing rows from the cached decklists.

    Returns (rows, stats). Rows are modified in place and handed back.

    Why this exists
    ---------------
    1.19.0 moved meta share onto this module and left the matchup layer behind:
    `mtg_stats.classify_row` reads the deck name straight off the CSV row, so
    matchup_matrix, winrate_analysis and update_archetypes got aliases but never
    a classifier verdict. The CHANGELOG has carried "moving them onto
    deck_labels is open" since.

    Resolution order is the same as everywhere else: override, then a confident
    classifier verdict off the cached list, then the organizer's aliased text.

    What it actually buys, measured 2026-09-08
    ------------------------------------------
    On the full rebuilt pool, 1,519 rows and 3,038 seats:

        distinct deck labels     122  ->  104
        seats relabelled                  387
        populated matchup cells  604  ->  493
        cells at the 10-match floor  8  ->   14

    The gain is **merging**, not recovery. Fewer, denser cells is the point: a
    deck filed under three house styles is three thin cells that each miss the
    floor, and one real one that clears it.

    What it cannot fix
    ------------------
    783 seats (26%) carry no usable deck name, and **only 8 of those have a
    deck URL**. For the other 775 the scraper captured neither a name nor a
    link, so there is nothing to look the deck up by. That is a melee_scraper
    gap rather than a naming gap, and no amount of work in this module touches
    it. An earlier read of this claimed those rows carried a URL; they don't.

    Where this deliberately differs from build_baseline
    ---------------------------------------------------
    build_baseline drops a result with no cached decklist, on Phill's rule that
    a finish says nothing when you don't know what they played. A pairing row is
    a different object: the row records who beat whom, and an organizer's label
    on both sides is weak evidence about a matchup rather than no evidence about
    the field. So organizer text is kept here by default and counted separately,
    and the caller is expected to report the split — a matrix that is mostly
    organizer text should say so. Pass `keep_organizer_text=False` for the
    strict reading.
    """
    if resolver is None:
        if data_dir is None:
            raise ValueError("resolve_pairing_decks needs a data_dir or a resolver")
        resolver = Resolver(data_dir)

    stats = Counter()
    for row in rows:
        for name_key, url_key in PAIRING_SEATS:
            typed = (row.get(name_key) or "").strip()
            url = (row.get(url_key) or "").strip()
            had_name = bool(typed) and typed.lower() not in JUNK_DECKS

            label = resolver.resolve(url, typed)
            if label.name:
                stats[f"seat_{label.source}"] += 1
                if not had_name:
                    stats["seat_recovered_from_blank"] += 1
                elif _alias(typed) != label.name:
                    stats["seat_relabelled"] += 1
                row[name_key] = label.name
                continue

            # The resolver has nothing. Fall back to what the organizer typed,
            # or blank the seat so classify_row drops the row rather than
            # counting a match against a deck nobody can name.
            if keep_organizer_text and had_name:
                stats["seat_row_text"] += 1
                row[name_key] = _alias(typed)
            else:
                stats[f"seat_unnamed_{label.source}"] += 1
                row[name_key] = ""

    stats["rows"] = len(rows)
    stats["rows_usable"] = sum(
        1 for r in rows
        if (r.get("player1_deck") or "").strip() and (r.get("player2_deck") or "").strip())
    return rows, stats


def pairing_report_lines(stats):
    """What the join recovered and what it couldn't. Print this."""
    named = sum(stats[f"seat_{s}"] for s in SOURCES)
    lines = [
        f"  deck names resolved: {named} seat(s)  "
        f"(override {stats['seat_override']}, "
        f"classifier {stats['seat_classifier']}, "
        f"organizer {stats['seat_organizer']}, "
        f"row text {stats['seat_row_text']})",
        f"  recovered from blank: {stats['seat_recovered_from_blank']} seat(s); "
        f"relabelled: {stats['seat_relabelled']}",
        f"  usable rows: {stats['rows_usable']} of {stats['rows']}",
    ]
    unnamed = sum(v for k, v in stats.items() if k.startswith("seat_unnamed_"))
    if unnamed:
        detail = ", ".join(
            f"{k[len('seat_unnamed_'):]} {v}"
            for k, v in sorted(stats.items()) if k.startswith("seat_unnamed_"))
        lines.append(f"  seats left unnamed: {unnamed}  ({detail})")
    return lines


# ── comparing two snapshots ──────────────────────────────────────────────────

# Below this many players a share delta is describing the sample, not the
# format. The 2026-09-03 snapshot had 61 players across 17 events.
MIN_PLAYERS_FOR_DELTA = 40
# Two snapshots built from event pools this dissimilar aren't measuring the
# same field. 2026-08-31 covered 23 events and 369 players; 2026-09-07 covered
# 20 and 78. A share delta across that pair measures which CSVs were in the
# folder that morning.
MIN_EVENT_OVERLAP = 0.50


def delta_is_honest(prev, cur):
    """
    (ok, reason). Can these two snapshots be subtracted from each other?

    Returns (True, None) when they can. The reason string is written into the
    weekly note in place of a number, so a reader can see why the column is
    blank instead of assuming nothing moved.
    """
    if not prev or not cur:
        return False, "no previous snapshot in this era"

    for snap, which in ((prev, "previous"), (cur, "this")):
        n = snap.get("total_players_with_deck") or 0
        if n < MIN_PLAYERS_FOR_DELTA:
            return False, (f"the {which} snapshot has {n} players, under the "
                           f"{MIN_PLAYERS_FOR_DELTA} needed for a share delta")

    a = set(prev.get("event_ids") or [])
    b = set(cur.get("event_ids") or [])
    if not a or not b:
        return False, "one of the snapshots predates event_ids being recorded"
    overlap = len(a & b) / len(a | b)
    if overlap < MIN_EVENT_OVERLAP:
        return False, (f"the event pools share only {overlap:.0%} of their "
                       f"events ({len(a & b)} of {len(a | b)}), so a delta "
                       f"would measure the pool rather than the format")
    return True, None
