import os
import sys

# Put the skill folder (one level up from tests/) on sys.path so the tests can
# `import mtg_stats` whatever directory pytest is launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
