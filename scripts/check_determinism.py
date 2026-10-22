#!/usr/bin/env python3
"""
Run every offline command twice on the same data and check the results match.

    python scripts/check_determinism.py --data <folder with scraped data>

Each run gets a fresh copy of the data folder and a different PYTHONHASHSEED,
which changes the iteration order of every set and every string-keyed dict
built from a set. A command whose output depends on that order prints different
results for the same input. On 2026-10-21 this found one: cluster-shells broke
ties between cards on set order, so a shell's Core line changed every run.

Compared per command: the exit code, stdout and stderr, and every file the
command wrote or changed. ISO timestamps are masked before comparing, because a
"rebuilt at" stamp differing between two runs is expected.

Needs real scraped data, so it isn't part of CI. Exit 0 when every command
matches, 1 when any differs, 2 when it can't run.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Offline commands only: nothing here touches the network.
RUNS = [
    ["era", "--json"],
    ["winrate-analysis"],
    ["matchup-matrix"],
    ["card-signal", "--json"],
    ["card-signal", "--lens", "adoption", "--board", "side"],
    ["audit-refs", "--json"],
    ["validate-events", "--dry-run"],
    ["play-profile", "--json"],
    ["play-profile", "--validate"],
    ["play-profile", "--dry-run"],
    ["combine-events", "--dry-run"],
    ["combine-events"],
    ["build-baseline", "--dry-run", "--label", "determinism", "--date", "2026-01-01"],
    ["apply-corrections", "--list"],
    ["apply-corrections", "--dry-run"],
    ["cluster-shells", "--dry-run"],
    ["update-archetypes"],
    ["build-refs-from-melee", "--dry-run"],
    ["archive-era", "--dry-run"],
    ["refine-refs", "--signatures"],
    ["migrate-play-log-format", "--dry-run"],
    ["classify-decks"],
]

TIMESTAMP = re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?")


def _masked(data: bytes) -> bytes:
    return TIMESTAMP.sub(b"<timestamp>", data)


def _snapshot(folder):
    out = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, folder)] = hashlib.sha256(_masked(fh.read())).hexdigest()
    return out


def run_once(source, args, seed, scratch):
    # Same path for both runs, so a path written into a note can't differ.
    data = os.path.join(scratch, "data")
    if os.path.exists(data):
        shutil.rmtree(data)
    shutil.copytree(source, data)
    before = _snapshot(data)
    env = dict(os.environ, MTG_DATA_DIR=data, MTG_OUTPUT_DIR=data,
               PYTHONHASHSEED=str(seed), PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, os.path.join(REPO, "mtg.py"), *args],
                          cwd=REPO, env=env, capture_output=True, timeout=900)
    after = _snapshot(data)
    written = {k: v for k, v in after.items() if before.get(k) != v}
    out = _masked(proc.stdout + b"\n" + proc.stderr)
    return proc.returncode, hashlib.sha256(out).hexdigest(), written


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    ap.add_argument("--data", required=True, help="folder holding a format's scraped data")
    ap.add_argument("--seeds", type=int, nargs=2, default=[1, 2], metavar=("A", "B"))
    args = ap.parse_args()
    if not os.path.isdir(args.data):
        print(f"No data folder at {args.data}")
        return 2

    differing = 0
    with tempfile.TemporaryDirectory(prefix="mtg-determinism-") as scratch:
        for run in RUNS:
            a = run_once(args.data, run, args.seeds[0], scratch)
            b = run_once(args.data, run, args.seeds[1], scratch)
            problems = []
            if a[0] != b[0]:
                problems.append(f"exit {a[0]} vs {b[0]}")
            if a[1] != b[1]:
                problems.append("output differs")
            files = sorted(k for k in set(a[2]) | set(b[2]) if a[2].get(k) != b[2].get(k))
            if files:
                problems.append("files differ: " + ", ".join(files[:4]))
            differing += bool(problems)
            label = " ".join(run)
            print(f"  {'DIFF' if problems else 'same'}  {label:<55} {'; '.join(problems)}")

    print(f"\n{len(RUNS)} runs, {differing} differing under seeds {args.seeds[0]} and {args.seeds[1]}.")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
