"""`python -m mtg_data <command>`: the form the pipeline uses for its own subprocesses."""
import sys

from mtg_data.cli import main

sys.exit(main())
