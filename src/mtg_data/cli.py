"""
One entry point for every pipeline step.

    python mtg.py <command> [options]     from a checkout, no install needed
    mtg <command> [options]               after `pip install -e .`
    python -m mtg_data <command> [...]    what the pipeline uses for subprocesses

Each command is a module with a main() that parses its own options, so
`python mtg.py <command> --help` shows them. A command's name is its module's
name with hyphens: card_signal.py is `card-signal`.

The commands are listed in the order data moves through them. Ingest pulls raw
results, quality decides what is allowed into the pool, classify puts an
archetype name on every deck, analyze turns the pool into numbers, and review
works on one player's own games.
"""
import difflib
import importlib
import sys

from mtg_data import __version__

# (command, module, summary), grouped by pipeline stage.
STAGES = {
    "ingest": [
        ("fetch-melee", "mtg_data.ingest.fetch_melee",
         "Find this era's melee.gg events and scrape them, then validate"),
        ("melee-scraper", "mtg_data.ingest.melee_scraper",
         "Scrape pairings and standings for given melee.gg event IDs"),
        ("fetch-mtgo", "mtg_data.ingest.fetch_mtgo",
         "Pull MTGO Challenge and 5-0 league decklists"),
        ("build-card-pool", "mtg_data.ingest.build_card_pool",
         "Cache the format's legal card pool from Scryfall"),
        ("build-mtgtop8-baseline", "mtg_data.ingest.build_mtgtop8_baseline",
         "Seed archetype references and meta share from mtgtop8"),
        ("fetch-vocabulary", "mtg_data.ingest.fetch_vocabulary",
         "Refresh the published archetype names from MTGGoldfish"),
    ],
    "quality": [
        ("era", "mtg_data.core.era",
         "Print the current format era: where results stop being comparable"),
        ("validate-events", "mtg_data.quality.validate_events",
         "Judge every event by its decklists; quarantine what doesn't belong"),
        ("combine-events", "mtg_data.quality.combine_events",
         "Rebuild the combined pool from per-event files (the one writer)"),
        ("audit-refs", "mtg_data.quality.audit_refs",
         "Check archetype references are in-era, in-format and distinct"),
        ("archive-era", "mtg_data.quality.archive_era",
         "Move a closed era's data aside so it leaves the live numbers"),
    ],
    "classify": [
        ("classify-decks", "mtg_data.classify.classify_decks",
         "Classify MTGO decklists against the archetype references"),
        ("build-refs-from-melee", "mtg_data.classify.build_refs_from_melee",
         "Build archetype references from labelled melee.gg decklists"),
        ("refine-refs", "mtg_data.classify.refine_refs",
         "Derive signature cards and gates that separate close references"),
        ("cluster-shells", "mtg_data.classify.cluster_shells",
         "Group unclassified decks into candidate archetypes for review"),
        ("apply-corrections", "mtg_data.classify.apply_corrections",
         "Apply human label rulings everywhere the numbers read them"),
        ("freeze-archetypes", "mtg_data.classify.freeze_archetypes",
         "Stamp archetype notes with the era that just ended"),
    ],
    "analyze": [
        ("winrate-analysis", "mtg_data.analyze.winrate_analysis",
         "Win rates per archetype over the validated pool"),
        ("matchup-matrix", "mtg_data.analyze.matchup_matrix",
         "Head-to-head matchup matrix over the validated pool"),
        ("card-signal", "mtg_data.analyze.card_signal",
         "Card-level signal: rogue picks, deviations, trends, adoption"),
        ("build-baseline", "mtg_data.analyze.build_baseline",
         "Append a meta-share snapshot for week-over-week comparison"),
        ("update-archetypes", "mtg_data.analyze.update_archetypes",
         "Write matchup data into archetype notes and a meta snapshot"),
    ],
    "review": [
        ("untapped-log", "mtg_data.review.untapped_log",
         "Pull Arena match logs from untapped.gg and parse them"),
        ("play-profile", "mtg_data.review.play_profile",
         "Count the play ledger into leaks and strengths"),
        ("migrate-play-log-format", "mtg_data.review.migrate_play_log_format",
         "One-off: stamp a format onto every play ledger row"),
        ("rules-lookup", "mtg_data.review.rules_lookup",
         "Quote the current Comprehensive Rules by number or keyword"),
    ],
}

COMMANDS = {cmd: module for rows in STAGES.values() for cmd, module, _ in rows}


def usage() -> str:
    width = max(len(cmd) for cmd in COMMANDS)
    lines = [f"mtg-data {__version__}", "",
             "usage: python mtg.py <command> [options]",
             "       python mtg.py <command> --help", ""]
    for stage, rows in STAGES.items():
        lines.append(f"{stage}:")
        lines += [f"  {cmd:<{width}}  {summary}" for cmd, _, summary in rows]
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    if argv[0] in ("-V", "--version"):
        print(__version__)
        return 0

    cmd, rest = argv[0], argv[1:]
    module_name = COMMANDS.get(cmd)
    if module_name is None:
        print(f"mtg: unknown command {cmd!r}", file=sys.stderr)
        close = difflib.get_close_matches(cmd, COMMANDS, n=3)
        if close:
            print(f"     did you mean: {', '.join(close)}", file=sys.stderr)
        print("     run `python mtg.py --help` for the list", file=sys.stderr)
        return 2

    # Each command parses sys.argv itself, so hand it a clean one before import:
    # a few modules read their format from the command line at import time.
    sys.argv = [f"mtg {cmd}", *rest]
    module = importlib.import_module(module_name)
    result = module.main()
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
