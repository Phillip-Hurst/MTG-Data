#!/usr/bin/env python3
"""Run mtg-data from a checkout without installing it.

    python mtg.py --help
    python mtg.py <command> [options]

After `pip install -e .` the same commands are available as `mtg <command>`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from mtg_data.cli import main

if __name__ == "__main__":
    sys.exit(main())
