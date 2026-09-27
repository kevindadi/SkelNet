"""Test path setup: make the ``python/`` package root importable."""

import sys
from pathlib import Path

PY_ROOT = Path(__file__).resolve().parents[1]
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))

REPO_ROOT = PY_ROOT.parent
