"""mtg-data: Magic: The Gathering tournament results, from the scrape to the meta read.

The package is laid out in the order data moves through it:

    ingest/    pull raw results from melee.gg, MTGO, mtgtop8, Scryfall, MTGGoldfish
    quality/   decide what is allowed into the pool, and say why anything isn't
    classify/  put one canonical archetype name on every deck
    analyze/   turn the validated, labelled pool into win rates and signal
    review/    one player's own games: the play ledger and the rules lookup
    core/      paths, format eras and the shared counting rules

Every command-line step is listed by `python mtg.py --help`.
"""

__version__ = "2.0.0"
