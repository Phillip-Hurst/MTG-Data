import os
import sys

# Tests import the package from src/ and the release tooling from scripts/,
# whatever directory pytest is launched from and whether or not the package is
# installed.
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("src", "scripts"):
    path = os.path.join(REPO_DIR, sub)
    if path not in sys.path:
        sys.path.insert(0, path)
