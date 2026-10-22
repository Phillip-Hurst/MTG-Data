"""
Tests for deck_labels.py and the baseline's use of it.

Every case here pins a failure that actually reached a published note:
organizer free text counted as three decks, a result with no decklist counted
anyway, and a share delta drawn between two snapshots built from different
event pools.

Fixture names are deliberately fake (guardrail 10) so a real archetype gaining
an alias can't quietly change what these assert.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from mtg_data.classify import deck_labels


PLACEHOLDER_REF = {
    "Placeholder Aggro": {
        "mainboard": {"Test Card A": 4, "Test Card B": 4, "Test Card C": 4,
                      "Test Card D": 4, "Test Card E": 4},
    },
}

CACHED_MAIN = {"Test Card A": 4, "Test Card B": 4, "Test Card C": 4,
               "Test Card D": 4, "Test Card E": 4}


def resolver(cache=None, overrides=None, refs=None):
    return deck_labels.Resolver(
        data_dir=ROOT,
        cache=cache if cache is not None else {},
        overrides=overrides if overrides is not None else {},
        refs=refs if refs is not None else PLACEHOLDER_REF,
    )


# ── dropping ─────────────────────────────────────────────────────────────────

def test_result_with_no_decklist_is_dropped():
    """Phill's rule, 2026-09-07: a finish with no list tells us nothing."""
    r = resolver(cache={})
    label = r.resolve("https://example.invalid/Decklist/View/999999", "Some Deck")
    assert label.name is None
    assert label.source == "no_decklist"
    assert r.counts["no_decklist"] == 1
    assert r.kept == 0


def test_result_with_no_deck_url_is_dropped_separately():
    r = resolver()
    assert r.resolve("", "Some Deck").source == "no_url"
    assert r.counts["no_url"] == 1


def test_cached_entry_with_empty_mainboard_counts_as_no_decklist():
    """A failed scrape leaves the URL in the cache with nothing in it. An
    absent value is not a passing value (guardrail 1)."""
    r = resolver(cache={"u": {"mainboard": {}, "failed": True}})
    assert r.resolve("u", "Some Deck").source == "no_decklist"


def test_drops_are_reported_not_silent():
    r = resolver(cache={})
    r.resolve("u1", "A")
    r.resolve("", "B")
    text = "\n".join(r.report_lines())
    assert "rows dropped:    2" in text
    assert "no decklist 1" in text
    assert "no deck url 1" in text


# ── resolution order ─────────────────────────────────────────────────────────

def test_override_beats_the_classifier():
    r = resolver(
        cache={"u": {"mainboard": CACHED_MAIN, "archetype": "Placeholder Aggro"}},
        overrides={"u": {"archetype": "Placeholder Combo", "decided": "2026-09-07"}},
    )
    label = r.resolve("u", "Placeholder Aggro")
    assert label.name == "Placeholder Combo"
    assert label.source == "override"


def test_classifier_beats_organizer_text():
    r = resolver(cache={"u": {"mainboard": CACHED_MAIN, "archetype": "Untitled Pile"}})
    label = r.resolve("u", "Untitled Pile")
    assert label.name == "Placeholder Aggro"
    assert label.source == "classifier"


def test_unconfident_deck_falls_back_to_organizer_text_and_says_so():
    """We know what they played, we just can't name the shell. The row stays."""
    r = resolver(cache={"u": {"mainboard": {"Unknown Card": 60},
                              "archetype": "Placeholder Brew"}})
    label = r.resolve("u", "Placeholder Brew")
    assert label.name == "Placeholder Brew"
    assert label.source == "organizer"


def test_junk_organizer_name_is_dropped_not_counted_as_a_deck():
    r = resolver(cache={"u": {"mainboard": {"Unknown Card": 60}, "archetype": "Decklist"}})
    assert r.resolve("u", "Decklist").name is None
    assert r.counts["junk_name"] == 1


def test_aliases_are_applied_to_every_source():
    """The whole point of the change: one deck, one name, whichever layer
    produced it."""
    from mtg_data.core.stats import ARCHETYPE_ALIASES
    alias, canonical = next(iter(ARCHETYPE_ALIASES.items()))
    r = resolver(cache={"u": {"mainboard": {"Unknown Card": 60}, "archetype": alias}})
    assert r.resolve("u", alias).name == canonical

    r2 = resolver(cache={"u": {"mainboard": CACHED_MAIN}},
                  overrides={"u": {"archetype": alias}})
    assert r2.resolve("u", "").name == canonical


def test_verdicts_are_memoised_per_url():
    r = resolver(cache={"u": {"mainboard": CACHED_MAIN}})
    r.resolve("u", "")
    r.resolve("u", "")
    assert len(r._verdicts) == 1
    assert r.counts["classifier"] == 2


def test_missing_refs_are_reported_rather_than_silently_unnaming_everything():
    r = deck_labels.Resolver(data_dir=ROOT, cache={}, overrides={}, refs={})
    assert any("archetype_refs" in p for p in r.problems)


# ── delta honesty ────────────────────────────────────────────────────────────

def snap(players, events, archetypes=None):
    return {"total_players_with_deck": players,
            "event_ids": [str(i) for i in events],
            "archetypes": archetypes or {}}


def test_delta_refused_when_the_event_pools_barely_overlap():
    """2026-08-31 covered 23 events and 369 players; 2026-09-07 covered 20 and
    78. Subtracting those measured the folder, not the format."""
    ok, why = deck_labels.delta_is_honest(snap(369, range(0, 23)),
                                          snap(78, range(50, 70)))
    assert ok is False
    assert "share only" in why


def test_delta_refused_on_a_thin_sample():
    ok, why = deck_labels.delta_is_honest(snap(369, range(0, 23)),
                                          snap(12, range(0, 23)))
    assert ok is False
    assert "12 players" in why


def test_delta_allowed_when_pools_and_sizes_line_up():
    ok, why = deck_labels.delta_is_honest(snap(300, range(0, 20)),
                                          snap(320, range(0, 22)))
    assert ok is True
    assert why is None


def test_delta_refused_when_a_snapshot_predates_event_ids():
    old = {"total_players_with_deck": 369, "archetypes": {}}
    ok, why = deck_labels.delta_is_honest(old, snap(300, range(0, 20)))
    assert ok is False
    assert "event_ids" in why


def test_no_previous_snapshot_is_not_a_delta():
    ok, why = deck_labels.delta_is_honest(None, snap(300, range(0, 20)))
    assert ok is False


# ── the snapshot itself ──────────────────────────────────────────────────────

def standings_row(tid, player, url, deck, rank="1", points="9"):
    return {"tournament_id": tid, "tournament_name": f"Event {tid}",
            "player": player, "deck_url": url, "deck_name": deck,
            "rank": rank, "points": points}


def test_snapshot_counts_only_players_with_a_cached_decklist():
    from mtg_data.analyze import build_baseline
    rows = [
        standings_row("t1", "Player One", "u1", "Untitled Pile"),
        standings_row("t1", "Player Two", "u2", "Placeholder Aggro"),
    ]
    r = resolver(cache={"u1": {"mainboard": CACHED_MAIN}})
    s, _tournaments, res = build_baseline.build_snapshot(rows, "2026-09-07", "test", r)
    assert s["total_players_with_deck"] == 1
    assert s["archetypes"]["Placeholder Aggro"]["player_count"] == 1
    assert s["label_provenance"]["dropped_no_decklist"] == 1
    assert res.dropped == 1


def test_snapshot_records_only_events_that_contributed_a_player():
    from mtg_data.analyze import build_baseline
    rows = [
        standings_row("t1", "Player One", "u1", "Untitled Pile"),
        standings_row("t2", "Player Two", "u2", "Placeholder Aggro"),
    ]
    r = resolver(cache={"u1": {"mainboard": CACHED_MAIN}})
    s, tournaments, _res = build_baseline.build_snapshot(rows, "2026-09-07", "test", r)
    assert s["events_covered"] == 1
    assert s["events_in_pool"] == 2
    assert s["event_ids"] == ["t1"]
    assert set(tournaments) == {"t1", "t2"}


def test_snapshot_folds_three_organizer_names_into_one_deck():
    """44 labels for 78 players was the defect. This is it in miniature."""
    from mtg_data.analyze import build_baseline
    rows = [
        standings_row("t1", "Player One", "u1", "Whatever"),
        standings_row("t1", "Player Two", "u2", "Something Else"),
        standings_row("t1", "Player Three", "u3", "A Third Name"),
    ]
    cache = {u: {"mainboard": CACHED_MAIN} for u in ("u1", "u2", "u3")}
    s, _t, _r = build_baseline.build_snapshot(rows, "2026-09-07", "test",
                                              resolver(cache=cache))
    assert list(s["archetypes"]) == ["Placeholder Aggro"]
    assert s["archetypes"]["Placeholder Aggro"]["meta_share_pct"] == 100.0


def test_snapshot_tracks_which_layer_named_each_deck():
    from mtg_data.analyze import build_baseline
    rows = [
        standings_row("t1", "Player One", "u1", "Whatever"),
        standings_row("t1", "Player Two", "u2", "Placeholder Aggro"),
    ]
    r = resolver(
        cache={"u1": {"mainboard": CACHED_MAIN},
               "u2": {"mainboard": CACHED_MAIN}},
        overrides={"u2": {"archetype": "Placeholder Aggro"}},
    )
    s, _t, _res = build_baseline.build_snapshot(rows, "2026-09-07", "test", r)
    by = s["archetypes"]["Placeholder Aggro"]["by_source"]
    assert by == {"classifier": 1, "override": 1}


def test_second_run_produces_the_same_snapshot(tmp_path):
    """Guardrail 4: run it twice."""
    from mtg_data.analyze import build_baseline
    rows = [standings_row("t1", "Player One", "u1", "Whatever")]
    cache = {"u1": {"mainboard": CACHED_MAIN}}
    a, _, _ = build_baseline.build_snapshot(rows, "2026-09-07", "test", resolver(cache=cache))
    b, _, _ = build_baseline.build_snapshot(rows, "2026-09-07", "test", resolver(cache=cache))
    assert a == b


def test_empty_standings_produce_an_empty_snapshot_not_a_crash():
    from mtg_data.analyze import build_baseline
    s, t, r = build_baseline.build_snapshot([], "2026-09-07", "test", resolver())
    assert s["total_players_with_deck"] == 0
    assert s["archetypes"] == {}
    assert t == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
