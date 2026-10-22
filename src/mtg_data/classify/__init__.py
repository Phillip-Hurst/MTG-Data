"""Put one canonical archetype name on every deck.

The classifier scores a decklist against reference lists and abstains when no
reference wins clearly. Abstentions go to a human review queue, and the human
rulings are stored apart from the scraped data so a re-scrape can't undo them.
"""
